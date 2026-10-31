# -*- coding: utf-8 -*-
"""生成「世界物件 → 物品/变体」对照表（data/物件变体.csv）

为什么要这张表
--------------
存档 `marooned_wuping_data*` 的 `wpType` 是**世界物件 id**，不是 Wuping 枚举：
    wpType=202 → Prefab/Build/ThrowStone（石头），而 Wuping 202 = Shoe（草鞋）
同一件东西在世界里有多个模型（地面/树上/雪地/水面），各自是不同物件 id，
但采到的物品相同。官方两张常量表把这条链补上：

    PlaceConstants.prefabMap       : 物件 id → 预制体路径        （place_out/prefab_map.json）
    PlaceConstants.couldFindWuping : 物品    → 物件 id 数组      （place_out/couldfind_map.json）

变体标签由预制体路径推断（实测规则，覆盖库里全部 218 个 wpType）：
    Snow 目录 / Snow 前缀  → 雪地
    Up 前缀（UpXxx、XxxUpHome）→ 树上/高处
    Tree 目录、Animals/*Home → 树上/树上巢（Animals 无 Up 的为地面巢）
    Floor 前缀 / Floor 目录 → 地面
    StoneWater 目录、名含 Water → 水面
    其余 → 普通

用法
----
    python pythonTool/导出物件变体.py                # 写 data/物件变体.csv
    python pythonTool/导出物件变体.py --dry          # 只打印统计
"""
import argparse
import csv
import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                                  # 物资一览/
BASE = os.path.dirname(ROOT)                                  # 仓库根
PO = os.path.join(BASE, "aehy-mod-master", "tools", "place_out")

PREFAB_MAP = os.path.join(PO, "prefab_map.json")               # 物件 id → 预制体
COULDFIND = os.path.join(PO, "couldfind_map.json")              # 物品 → 物件 id[]
NAMES = os.path.join(PO, "wuping_names.json")                   # 物品 id → [图标,简中,繁中,英,...]
CSV_IN = os.path.join(ROOT, "data", "物资映射.csv")              # 物件 id → 名称/预制体/图标
DB = os.path.join(ROOT, "data", "marooned_with_ed.db")
OUT = os.path.join(ROOT, "data", "物件变体.csv")

TABLES = ["marooned_wuping_data", "marooned_wuping_data2", "marooned_wuping_data3"]


def variant_of(prefab):
    """由预制体路径推断"这一份是哪来的"（同一物品的多形态）。

    前缀可叠加：`SnowUpTengtiao` = 雪地 + 树上；`FloorTree1` 在 Tree 目录但前缀是
    Floor，是地上的倒树（地面），不能因为落在 Tree 目录就算"树上"。
    """
    parts = prefab.split("/")
    folder = parts[1] if len(parts) > 2 else ""
    base = parts[-1]
    tags = []
    rest = base
    if folder == "Snow" or base.startswith("Snow"):
        tags.append("雪地")
        rest = base[4:] if base.startswith("Snow") else base
    if rest.startswith("Up"):
        tags.append("树上")
        rest = rest[2:]
    if rest.startswith("Down"):
        tags.append("地上")
        rest = rest[4:]
    if rest.startswith("Floor"):
        tags.append("地面")
    if folder == "Animals" or "Home" in base or "NiaoWo" in base:
        tags.append("树上巢" if "Up" in base else "地面巢")
    if folder == "StoneWater" or "Water" in base:
        tags.append("水面")
    tags = list(dict.fromkeys(tags))
    # 去冗余：雪地已隐含"在雪上"，有巢标签时也不必再说地面/地上
    if "雪地" in tags:
        tags = [t for t in tags if t not in ("地面", "地上")]
    if "地面巢" in tags or "树上巢" in tags:
        tags = [t for t in tags if t not in ("地面", "地上")]
    return "+".join(tags) or "普通"


_STRIP_PRE = ("snow", "up", "down", "floor", "tree", "grassbig", "grass",
              "small", "big", "da", "xiao", "new", "wild", "dead", "water")
_STRIP_SUF = ("home", "wupi", "obj", "wo", "thing")


def norm_name(base):
    n = base.lower()
    changed = True
    while changed:
        changed = False
        for p in _STRIP_PRE:
            if n.startswith(p) and len(n) > len(p) + 2:
                n = n[len(p):]
                changed = True
        for suf in _STRIP_SUF:
            if n.endswith(suf) and len(n) > len(suf) + 2:
                n = n[:-len(suf)]
                changed = True
    return n


def load_stats(db_path):
    """物件 id → 库内行数（哪个物件在存档里出现过多少次）。"""
    stats = {}
    if not os.path.exists(db_path):
        return stats
    con = sqlite3.connect(db_path)
    for t in TABLES:
        try:
            for wp, n in con.execute("select wpType,count(*) from %s group by wpType" % t):
                stats[int(wp)] = stats.get(int(wp), 0) + n
        except sqlite3.Error:
            pass
    con.close()
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成 物件 → 物品/变体 对照表")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--dry", action="store_true", help="只统计不写文件")
    a = ap.parse_args(argv)

    prefab = {int(k): v for k, v in json.load(open(PREFAB_MAP, encoding="utf-8")).items() if v}
    couldfind = {int(k): v for k, v in json.load(open(COULDFIND, encoding="utf-8")).items()}
    names = json.load(open(NAMES, encoding="utf-8"))
    id2item = {}
    for item, objs in couldfind.items():
        for o in objs:
            id2item.setdefault(int(o), int(item))

    enum_by_lower = {}
    for k, v in names.items():
        try:
            enum_by_lower.setdefault(str(v[1]).lower(), int(k))
        except (IndexError, ValueError):
            pass
    # 枚举名（英文）→ id，用于预制体名回退
    enum_en = {}
    lines = open(os.path.join(BASE, "261030", "Il2CppDumper-out", "dump.cs"),
                 encoding="utf-8", errors="replace").read()
    for m in re.finditer(r"public const Wuping (\w+) = (-?\d+);", lines):
        enum_en[m.group(1).lower()] = int(m.group(2))

    csv_name = {}
    if os.path.exists(CSV_IN):
        with open(CSV_IN, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                try:
                    csv_name[int(r["编号"])] = (r.get("名称") or "").strip()
                except (TypeError, ValueError):
                    continue
    stats = load_stats(DB)

    def item_name(i):
        v = names.get(str(i))
        return v[1] if v and len(v) > 1 else ""

    rows = []
    for oid in sorted(set(prefab) | set(stats)):
        pf = prefab.get(oid, "")
        item, how = id2item.get(oid), "官方表"
        if item is None and pf:
            cand = norm_name(pf.split("/")[-1])
            if cand in enum_en:
                item, how = enum_en[cand], "名称推断"
        rows.append({
            "物件id": oid,
            "预制体": pf,
            "变体": variant_of(pf) if pf else "",
            "现用名称": csv_name.get(oid, ""),
            "物品id": "" if item is None else item,
            "物品名": item_name(item) if item is not None else "",
            "匹配方式": how if item is not None else "",
            "库内行数": stats.get(oid, 0),
        })

    used = [r for r in rows if r["库内行数"]]
    fam = {}
    for r in rows:
        if r["物品id"] != "":
            fam.setdefault(r["物品id"], []).append(r)
    multi = {k: v for k, v in fam.items() if len(v) > 1}
    print("物件 %d 个（存档里出现 %d 个）；可反查到物品 %d 个" %
          (len(rows), len(used), len(fam)))
    print("多变体物品 %d 个，例如：" % len(multi))
    for k in list(sorted(multi))[:6]:
        v = multi[k]
        print("   物品 %-4s %-8s ← %s" % (k, item_name(k) or "?",
              " / ".join("%s(%s)'%s'" % (x["物件id"], x["变体"], x["预制体"].split("/")[-1]) for x in v)))
    noitem = [r["物件id"] for r in used if r["物品id"] == ""]
    print("存档里出现但 couldFindWuping 没登记的物件 %d 个（多为宝箱/木雕/怪石等特殊物件）：%s"
          % (len(noitem), noitem[:12]))

    if a.dry:
        return 0
    with open(a.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["物件id", "预制体", "变体", "现用名称",
                                          "物品id", "物品名", "匹配方式", "库内行数"])
        w.writeheader()
        w.writerows(rows)
    print("已写入", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
