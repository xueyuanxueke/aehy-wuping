# -*- coding: utf-8 -*-
"""
从存档数据库导出「物资位置」数据源。

输入：data/marooned_with_ed.db 的三张 wuping 表
      marooned_wuping_data  : level 1-9
      marooned_wuping_data2 : level 11, 13
      marooned_wuping_data3 : level 14, 15
输出：data/物资位置.json      （供网页 fetch 加载；失败时网页回退到 HTML 内联数据）

用法：
    python pythonTool/导出物资位置.py
    python pythonTool/导出物资位置.py --db 其它存档.db --out data/物资位置.json

地图元信息（名称 / 世界矩形 prm / 底图尺寸 / 底图路径）在本文件的 PLACES 表里维护。
新增地图时只需在这里加一行再重跑；改 prm 不需要动 HTML。
"""
import argparse
import datetime
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # 物资一览/
DEF_DB = os.path.join(ROOT, "data", "marooned_with_ed.db")
DEF_OUT = os.path.join(ROOT, "data", "物资位置.json")

# level -> (名称, prm, tw, th, bg, prmSource)
#   prm = [w, h, l, r, t, b]，l/r = 世界 x 范围，b/t = 世界 z 范围（min/max）
#   网页变换：px = (x-l)/(r-l)*tw ，py = (t-z)/(t-b)*th
#   bg = "" 表示没有底图，网页用合成网格底图
#   prmSource: "official" 由存档/原始数据确定；"estimated" 为估算，可随时改
PLACES = {
    1:  ("泰国丛林",      [500, 194,    -188.7,   82.5,    52.2,   -88.6], 692, 269,
         "地图图片/图1_泰国丛林.png", "official"),
    2:  ("非洲平原",      [505, 314,    -108.7,   97.9,   109.5,   -68.2], 505, 314,
         "地图图片/图2_非洲平原.png", "official"),
    3:  ("菲律宾海岛",    [512, 175.43, -142.8,  174.8,    89.4,   -62.2], 712, 244,
         "地图图片/图3_菲律宾海岛.png", "official"),
    4:  ("丛林沼泽",      [500, 193.1,  -191.31,  79.24,   58.19,  -89.13], 670, 259,
         "地图图片/图4_丛林沼泽.png", "official"),
    5:  ("罗马尼亚高山",  [512, 359,    -165.1,  192.8,   175.66, -161.7], 646, 453,
         "地图图片/图5_罗马尼亚高山.png", "official"),
    6:  ("挨饿德的噩梦",  [552, 263,    -208.3,  190.0,   181.8,   -93.5], 707, 346,
         "地图图片/图6_挨饿德的噩梦.png", "official"),
    7:  ("帕劳群岛",      [512, 197,    -349.0,  335.8,   190.0,  -181.3], 545, 210,
         "地图图片/图7_帕劳群岛.png", "official"),
    8:  ("挪威雪山",      [552, 222,    -244.0,  340.0,   107.0,  -202.0], 1024, 413,
         "地图图片/图8_挪威雪山.png", "official"),
    9:  ("蒙古戈壁",      [512, 240,    -316.3,  327.3,   196.7,  -216.0], 995, 467,
         "地图图片/图9_蒙古戈壁.png", "official"),
    # 10/12：prm 存档里没有，按物资点包围盒自动推算（见 derive_prm），拿到准确值后改成数字即可
    10: ("荒野一家",      None, 700, 336,
         "地图图片/图10_荒野一家.png", "estimated"),
    11: ("博茨瓦纳",      [512, 246,    -295.9,  319.2,   189.4,  -205.16], 661, 299,
         "地图图片/图11_博茨瓦纳.png", "official"),
    12: ("幽冥之地",      None, 666, 338,
         "地图图片/图12_幽冥之地.png", "estimated"),
    13: ("巴塔哥尼亚",    [512, 233,    -160.0,  163.9,    74.2,  -124.2], 682, 310,
         "地图图片/图13_巴塔哥尼亚.png", "official"),
    14: ("亚马逊雨林",    [512, 225,    -391.7,  339.2,   218.3,  -239.4], 668, 294,
         "地图图片/图14_亚马逊雨林.png", "official"),
    # 15：纳米比亚（新版本地图）。底图已到位（766x279），但 prm 仍然只能估算：
    #     用「物资点 ∪ 猎物区域」的并集包围盒，按 14 张 official 图统计出的
    #     数据占宽 0.918 / 占高 0.910 反推（中心对齐），比单看物资点更贴合
    #     —— 猎物区域框（如珍珠鸡那种大粗框）会超出物资点包围盒。
    15: ("纳米比亚",      [674, 333,    -326.65, 347.65,  180.98, -151.98], 766, 279,
         "地图图片/图15_纳米比亚.png", "estimated"),
}

# 用物资点包围盒反推 prm：对 12 张 official 图统计得到 prm 宽/点位宽 中位数 1.12，
# prm 高/点位高 中位数 1.16，且点位包围盒中心与 prm 中心偏移 <2%（图8 除外）。
# 所以没给 prm 的图按「包围盒按 1.12/1.16 外扩、中心对齐」推算。
EXPAND_X, EXPAND_Z = 1.12, 1.16

TABLES = ["marooned_wuping_data", "marooned_wuping_data2", "marooned_wuping_data3"]

EOL = "\r\n" if sys.platform == "win32" else "\n"


def derive_prm(rows):
    if not rows:
        return None
    xs = [r[1] for r in rows]
    zs = [r[2] for r in rows]
    cx = (min(xs) + max(xs)) / 2.0
    cz = (min(zs) + max(zs)) / 2.0
    w = (max(xs) - min(xs)) * EXPAND_X
    h = (max(zs) - min(zs)) * EXPAND_Z
    l, r = cx - w / 2.0, cx + w / 2.0
    b, t = cz - h / 2.0, cz + h / 2.0
    return [round(w), round(h), round(l, 1), round(r, 1), round(t, 1), round(b, 1)]


def collect(db_path):
    """扫描三张 wuping 表，返回 {level: [[id, x, z, s, tag], ...]}（level 自动发现）"""
    if not os.path.exists(db_path):
        raise SystemExit("找不到存档数据库：%s" % db_path)
    con = sqlite3.connect(db_path)
    out = {}
    for tbl in TABLES:
        try:
            levels = [r[0] for r in con.execute(
                "select distinct level from %s order by level" % tbl)]
        except sqlite3.Error as e:
            raise SystemExit("读 %s 失败：%s" % (tbl, e))
        for lv in levels:
            rows = con.execute(
                "select wpType, x, z, status, wpTag from %s "
                "where level = ? order by rowid" % tbl, (lv,)).fetchall()
            out.setdefault(int(lv), []).extend(
                [[int(r[0]), round(r[1] or 0.0, 3), round(r[2] or 0.0, 3),
                  int(r[3] or 0), r[4] or ""] for r in rows])
    con.close()
    return out


def build(db_path):
    rows_by_lv = collect(db_path)
    unknown = sorted(set(rows_by_lv) - set(PLACES))
    for lv in unknown:
        print("! 存档里有 level %d，但 PLACES 表里没有它的名称/底图，按默认值输出" % lv)
    places = []
    for lv in sorted(set(PLACES) | set(rows_by_lv)):
        meta = PLACES.get(lv)
        rows = rows_by_lv.get(lv, [])
        if meta:
            name, prm, tw, th, bg, src = meta
        else:
            name, prm, tw, th, bg, src = ("图%d" % lv, None, 1000, 470, "", "estimated")
        if not prm:
            prm = derive_prm(rows) or [1000, 470, -500, 500, 235, -235]
        places.append({
            "level": lv,
            "name": name,
            "prm": prm,
            "tw": tw,
            "th": th,
            "bg": bg,
            "prmSource": src,
            "count": len(rows),
            "rows": rows,
        })
    return {
        "meta": {
            "title": "物资位置",
            "desc": "每张地图上所有可拾取物资的摆放点。网页启动时加载本文件，"
                    "失败则回退到 index.html 内联的旧数据。",
            "source": "data/marooned_with_ed.db → marooned_wuping_data / _data2 / _data3",
            "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "coordinateSystem": {
                "axes": ["x", "z"],
                "ignored": "y",
                "note": "Unity 世界坐标，取 x/z 平面；网页 px=(x-l)/(r-l)*tw，py=(t-z)/(t-b)*th",
            },
            "rowFields": ["id", "x", "z", "s", "tag"],
            "rowFieldsNote": "id=物资编号(同 物资映射.csv 的「编号」)；x/z=世界坐标；"
                             "s=状态(0 未拾取/1 已拾取)；tag=存档内唯一标记，形如 tag_4227",
            "placeFields": "level(图号) / name(地图名) / prm(世界矩形[w,h,l,r,t,b]) / "
                           "tw,th(底图像素尺寸) / bg(底图路径，空串=无底图) / "
                           "prmSource(official|estimated) / count(点位数) / rows",
            "levelsNote": "level 与网页「图N」一一对应；level 10/12 在存档中尚无物资点，rows 为空数组",
        },
        "places": places,
    }


def dumps(obj):
    """顶层缩进、rows 整行输出，既好读又不至于膨胀。"""
    m = json.dumps(obj["meta"], ensure_ascii=False, indent=2)
    lines = ["{"]
    lines.append('"meta": ' + m.replace("\n", "\n") + ",")
    lines.append('"places": [')
    ps = []
    for p in obj["places"]:
        head = json.dumps({k: p[k] for k in
                           ("level", "name", "prm", "tw", "th", "bg", "prmSource", "count")},
                          ensure_ascii=False)
        head = head[:-1]  # 去掉收尾的 }
        ps.append(head + ', "rows": ' + json.dumps(p["rows"], ensure_ascii=False) + "}")
    lines.append(",\n".join(ps))
    lines.append("]")
    lines.append("}")
    return EOL.join(lines) + EOL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEF_DB)
    ap.add_argument("--out", default=DEF_OUT)
    a = ap.parse_args()

    obj = build(a.db)
    txt = dumps(obj)
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        f.write(txt)

    tot = sum(p["count"] for p in obj["places"])
    print("已写出 %s" % a.out)
    print("  %.1f KB，%d 张地图，共 %d 个物资点" % (len(txt.encode("utf-8")) / 1024.0,
                                                len(obj["places"]), tot))
    for p in obj["places"]:
        print("  图%-2d %-12s %5d 点  prm=%s  %s" % (
            p["level"], p["name"], p["count"], p["prm"], p["prmSource"]))


if __name__ == "__main__":
    main()
