# -*- coding: utf-8 -*-
"""
从游戏元数据里导出「每张地图的底图世界矩形」（sceneDituWHMap）。

为什么需要它
------------
网页把世界坐标换成底图像素用的是游戏自己的公式（DituManager.V3ToV2）：

    px = w * (x - (l+r)/2) / (r-l) + w/2   →   px = (x-l)/(r-l)*tw
    py = h * (z - (t+b)/2) / (t-b) + h/2   →   py = (t-z)/(t-b)*th

其中 (l,r,t,b) 是底图覆盖的世界矩形。这个矩形在游戏里是常量表
`Constants.sceneDituWHMap : Dictionary<int, float[]>`
（float[6] = [w, h, left, right, top, bottom]，w/h 是底图的基准像素，
在公式里和 tw/th 一起约掉，只有比例有用）。

字典是 cctor 里用 `RuntimeHelpers.InitializeArray` 从静态字段数据填的，
字段句柄静态不可解；但数组本体作为 6 个连续 float 存在 global-metadata.dat
的静态字段数据区，因此直接按「6 个连续 float」扫元数据即可。
候选再用存档里的物资点位做交叉验证（矩形必须包住该图所有点位，
且矩形/点位包围盒的比例接近其他图的中位数），避免误采。

用法
----
    python pythonTool/导出地图矩形.py                     # 默认读 261030
    python pythonTool/导出地图矩形.py --meta 260109/global-metadata.dat
    python pythonTool/导出地图矩形.py --json data/地图矩形.json --apply

--apply 会把结果回写到 导出物资位置.py 的 PLACES 表（prm 与 prmSource），
之后再跑 导出物资位置.py 即可更新 data/物资位置.json。
"""
import argparse
import io
import json
import os
import re
import sqlite3
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # 物资一览/
AEHY = os.path.dirname(ROOT)                      # 仓库根

DEF_META = os.path.join(AEHY, "261030", "global-metadata.dat")
DEF_DB = os.path.join(ROOT, "data", "marooned_with_ed.db")
DEF_JSON = os.path.join(ROOT, "data", "地图矩形.json")

# level -> 点位所在的表（用于交叉验证；缺表则跳过验证，只做几何筛选）
TABLES = ["marooned_wuping_data", "marooned_wuping_data2", "marooned_wuping_data3"]

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


# ---------------------------------------------------------------- 元数据扫描
def scan_candidates(meta_path):
    """扫出所有「像地图矩形」的 6 连续 float。返回 [(offset, [w,h,l,r,t,b]), ...]"""
    md = open(meta_path, "rb").read()
    n = len(md) // 4
    vals = struct.unpack("<%df" % n, md[:n * 4])
    out, seen = [], set()
    for i in range(n - 5):
        w, h, l, r, t, b = vals[i:i + 6]
        # 几何合理性：底图基准像素 400~1200 宽；矩形非退化且不夸张
        if not (400 <= w <= 1200 and 120 <= h <= 700):
            continue
        if not (l < r and t > b):
            continue
        dw, dh = r - l, t - b
        if not (100 <= dw <= 1000 and 60 <= dh <= 800):
            continue
        if max(abs(l), abs(r), abs(t), abs(b)) > 1000:
            continue
        key = (round(w, 2), round(h, 2), round(l, 2), round(r, 2),
               round(t, 2), round(b, 2))
        if key in seen:          # 同一数组可能被相邻窗口重复命中
            continue
        seen.add(key)
        out.append((i * 4, key))
    return out


# ---------------------------------------------------------------- 点位统计
def level_points(db_path):
    """{level: (minx, maxx, minz, maxz, count, [(x,z) 采样])}"""
    con = sqlite3.connect(db_path)
    res = {}
    for tbl in TABLES:
        try:
            levels = [r[0] for r in con.execute(
                "select distinct level from %s" % tbl)]
        except sqlite3.Error:
            continue
        for lv in levels:
            r = con.execute(
                "select min(x), max(x), min(z), max(z), count(*) from %s where level=?"
                % tbl, (lv,)).fetchone()
            if not r or not r[4]:
                continue
            smp = con.execute(
                "select x, z from %s where level=? limit 800" % tbl, (lv,)).fetchall()
            res.setdefault(int(lv), (r[0], r[1], r[2], r[3], r[4], smp))
    con.close()
    return res


def png_ratios():
    """{level: 底图宽高比}，用来给「近似矩形」消歧（同图的 w/h 必须等于 PNG 宽高比）。"""
    out = {}
    d = os.path.join(ROOT, "地图图片")
    for f in os.listdir(d) if os.path.isdir(d) else []:
        m = re.match(r"图(\d+)_", f)
        if not m or not f.lower().endswith(".png"):
            continue
        with open(os.path.join(d, f), "rb") as fh:
            head = fh.read(33)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            continue
        w, h = struct.unpack(">II", head[16:24])
        out[int(m.group(1))] = w / h
    return out


def build_cost(cands, pts, ratios):
    """代价矩阵 cost[level][cand]：不可行 = None。

    可行条件：包住该图全部采样点、矩形/点位比例与其它图同量级、中心基本对齐；
    代价越小越像：比例贴近中位数 1.12/1.16、中心偏移小、PNG 宽高比与 w/h 一致。
    """
    cost, feasible = {}, 0
    for lv, (minx, maxx, minz, maxz, cnt, smp) in pts.items():
        bw, bh = maxx - minx, maxz - minz
        if bw <= 0 or bh <= 0:
            continue
        row = []
        for off, (w, h, l, r, t, b) in cands:
            rx, rz = (r - l) / bw, (t - b) / bh
            if not (0.95 <= rx <= 1.40 and 0.95 <= rz <= 1.45):
                row.append(None); continue
            px, pz = (r - l) * 0.01, (t - b) * 0.01
            if not all(l - px <= x <= r + px and b - pz <= z <= t + pz for x, z in smp):
                row.append(None); continue
            cx = ((minx + maxx) / 2 - (l + r) / 2) / (r - l)
            cz = ((minz + maxz) / 2 - (b + t) / 2) / (t - b)
            if abs(cx) > 0.12 or abs(cz) > 0.12:
                row.append(None); continue
            c = 2.0 * (abs(rx - 1.12) + abs(rz - 1.16)) + 6.0 * (abs(cx) + abs(cz))
            asp = ratios.get(lv)
            if asp:                              # 宽高比越接近越好（权重给大，用来区分近似矩形）
                c += 8.0 * abs(__import__("math").log(asp / (w / h)))
            row.append(c)
            feasible += 1
        cost[lv] = row
    return cost, feasible


def solve(cost):
    """精确求解一对一匹配：可行边很少（几十条），直接按「候选少的关卡优先」回溯。"""
    lvls = sorted(cost, key=lambda lv: sum(1 for c in cost[lv] if c is not None))
    best = {"cost": float("inf"), "pick": None}

    def dfs(i, used, acc, pick):
        if acc >= best["cost"]:
            return
        if i == len(lvls):
            best["cost"], best["pick"] = acc, dict(pick)
            return
        lv = lvls[i]
        for j, c in enumerate(cost[lv]):
            if c is None or j in used:
                continue
            used.add(j); pick[lv] = j
            dfs(i + 1, used, acc + c, pick)
            pick.pop(lv); used.discard(j)
        # 该关卡没有可用候选 → 放弃这一关（允许漏配，但代价高）
        dfs(i + 1, used, acc + 50.0, pick)

    dfs(0, set(), 0.0, {})
    return best["pick"] or {}


def match(cands, pts):
    ratios = png_ratios()
    cost, feasible = build_cost(cands, pts, ratios)
    print("可行配对 %d 组（图 %d × 候选 %d）" % (feasible, len(cost), len(cands)))
    pick = solve(cost)
    chosen = {}
    for lv, j in sorted(pick.items()):
        off, (w, h, l, r, t, b) = cands[j]
        minx, maxx, minz, maxz, cnt, smp = pts[lv]
        info = dict(offset=off,
                    ratioX=round((r - l) / (maxx - minx), 3),
                    ratioZ=round((t - b) / (maxz - minz), 3),
                    offX=round(((minx + maxx) / 2 - (l + r) / 2) / (r - l), 3),
                    offZ=round(((minz + maxz) / 2 - (b + t) / 2) / (t - b), 3),
                    aspectErr=round(abs(__import__("math").log(
                        ratios[lv] / (w / h))), 4) if lv in ratios else None,
                    rect=(w, h, l, r, t, b))
        chosen[lv] = info
    return chosen, {info["offset"] for info in chosen.values()}


# ---------------------------------------------------------------- 回写 PLACES
def apply_to_places(json_path, chosen, places_py):
    """把结果写进 导出物资位置.py 的 PLACES（只改已存在条目的 prm / prmSource）。"""
    with open(places_py, encoding="utf-8", newline="") as fh:   # newline="" 保留原换行风格
        src = fh.read()
    n = 0
    for lv, info in sorted(chosen.items()):
        w, h, l, r, t, b = info["rect"]
        # 匹配 “15: ("纳米比亚",      [..], 766, 279,” 这种行
        pat = re.compile(r"(\n    %d:\s*\(\"[^\"]+\",\s*)(\[[^\]]*\]|None)(,\s*\d+,\s*\d+,)" % lv)
        m = pat.search(src)
        if not m:
            print("  ! level %d 在 PLACES 里没有对应行，跳过" % lv)
            continue
        new_prm = "[%g, %g, %g, %g, %g, %g]" % (w, h, l, r, t, b)
        src = src[:m.start(2)] + new_prm + src[m.end(2):]
        n += 1
    # prmSource：把这些 level 从 estimated 改成 official
    for lv, info in sorted(chosen.items()):
        pat = re.compile(r"(\n    %d:\s*\([^;]*?\")(estimated)(\"\),)" % lv, re.S)
        src = pat.sub(r"\1official\3", src, count=1)
    with open(places_py, "w", encoding="utf-8", newline="") as fh:
        fh.write(src)
    print("已回写 %d 条 prm 到 %s" % (n, os.path.basename(places_py)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", default=DEF_META, help="global-metadata.dat 路径")
    ap.add_argument("--db", default=DEF_DB, help="存档数据库")
    ap.add_argument("--json", default=DEF_JSON, help="输出 JSON")
    ap.add_argument("--apply", action="store_true",
                    help="把结果回写 导出物资位置.py 的 PLACES 表")
    a = ap.parse_args()

    if not os.path.exists(a.meta):
        raise SystemExit("找不到 %s（用 --meta 指定）" % a.meta)

    cands = scan_candidates(a.meta)
    print("元数据里扫到 %d 个候选矩形" % len(cands))

    pts = level_points(a.db) if os.path.exists(a.db) else {}
    chosen, used = match(cands, pts) if pts else ({}, set())

    data = {}
    for lv in sorted(chosen):
        info = chosen[lv]
        w, h, l, r, t, b = info["rect"]
        data[str(lv)] = {
            "w": w, "h": h, "left": l, "right": r, "top": t, "bottom": b,
            "prm": [w, h, l, r, t, b],
            "verified": {"ratioX": info["ratioX"], "ratioZ": info["ratioZ"],
                         "offX": info["offX"], "offZ": info["offZ"]},
        }

    print("\n%-4s %-9s %-9s %-22s %-14s %s" % ("图", "w×h", "矩形/点位X", "x 范围", "中心偏移", "点位范围"))
    for lv in sorted(chosen):
        info = chosen[lv]
        w, h, l, r, t, b = info["rect"]
        p = pts.get(lv)
        pr = "x[%.1f,%.1f]" % (p[0], p[1]) if p else "-"
        print("%-4d %-9s %6.3f/%-6.3f x[%8.2f,%7.2f] %+6.3f/%+6.3f %s" % (
            lv, "%g×%g" % (w, h), info["ratioX"], info["ratioZ"], l, r,
            info["offX"], info["offZ"], pr))

    unused = [c for c in cands if c[0] not in used]
    if unused:
        print("\n未配到关卡的候选（可能是别的 float[6] 表，可人工核对）：")
        for off, rect in unused[:10]:
            print("  off=%#x  %s" % (off, rect))

    with open(a.json, "w", encoding="utf-8", newline="") as f:
        json.dump({
            "meta": {
                "title": "地图矩形（sceneDituWHMap）",
                "desc": "每张地图底图覆盖的世界矩形。像素换算："
                        "px=(x-left)/(right-left)*tw，py=(top-z)/(top-bottom)*th",
                "source": "global-metadata.dat 静态字段数据（float[6]=w,h,left,right,top,bottom）",
                "validatedBy": "存档物资点位（矩形包住全部点位 + 比例/中心与其它图一致）",
                "metaPath": os.path.relpath(a.meta, AEHY).replace("\\", "/"),
                "levels": len(data),
            },
            "places": data,
        }, f, ensure_ascii=False, indent=1)
    print("\n已写出 %s（%d 张图）" % (a.json, len(data)))

    if a.apply:
        apply_to_places(a.json, chosen, os.path.join(HERE, "导出物资位置.py"))


if __name__ == "__main__":
    main()
