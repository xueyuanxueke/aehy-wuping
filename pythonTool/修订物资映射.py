# -*- coding: utf-8 -*-
"""修订 data/物资映射.csv 的显示名称（图标不动）

命名规则（按可靠性排序）
------------------------
1. `物件变体.csv` 里有 `物品id/物品名`（来自 `PlaceConstants.couldFindWuping` 或预制体名推断）
   → 用**物品名**，非"普通"变体加后缀，如 `藤条[树上]`、`藤条[雪地+树上]`、`鸟蛋[地面巢]`。
   理由：同一物品有多个世界模型（地面/树上/雪地），地图上按物品聚合更符合"能采到什么"。
2. 没有物品映射（宝箱、木雕、怪石、竹子、动物巢…）→ 保留人工维护的名称；
   为空时按预制体名查小表 `PREFAB_CN` 补一个。
3. 仍然为空 → 留空，网页退回 英文名 → #编号（图标位置显示首字徽标）。

同时把 `预制体` 列按 `prefab_map.json` 校正（旧表里有几行填成了图标路径）。

用法
----
    python pythonTool/修订物资映射.py --dry     # 只看会改哪些
    python pythonTool/修订物资映射.py           # 写入（先备份 物资映射.bak.csv）
"""
import argparse
import csv
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BASE = os.path.dirname(ROOT)
PO = os.path.join(BASE, "aehy-mod-master", "tools", "place_out")

VAR_CSV = os.path.join(ROOT, "data", "物件变体.csv")
MAP_CSV = os.path.join(ROOT, "data", "物资映射.csv")
PREFAB_MAP = os.path.join(PO, "prefab_map.json")

# 没有物品映射、又缺名称的，按预制体基名兜底（人工确认过的几条）
PREFAB_CN = {
    "StoneFishHome": "石头鱼",
    "FrogHqHome": "青蛙",
    "TanglangxiaHome": "螳螂虾",
    "LangzhuHome": "狼蛛",
    "FireGrassNew": "干草",
    "SnowPangxieHome": "螃蟹",
    "SnowSongshuHome": "松鼠",
    "SnowSongshuUpHome": "松鼠",
    "SnowTuziHome": "雪兔",
    "SnowThrowStone": "石头",
    "SnowZuziTree": "竹子",
    "SnowGrassBig": "大叶片",
    "SnowKushu": "枯树",
    "FeizhouZuziTree": "竹子",
    "BanzhuTree": "斑竹树",
    "HaitanTree1": "海滩树",
    "Shupi2": "树皮",
    "Shupi3": "树皮",
    "GrassBig1": "大叶子",
    "GrassBig2": "大叶子",
    "FloorBigLeaf": "大型叶片",
    "BigShuihulu": "大型水葫芦",
    "DreamCi": "噩梦荆刺",
    "Kushu": "枯树",
    "Fenbian": "大便",
}


def suffix(variant):
    v = (variant or "").strip()
    if not v or v == "普通":
        return ""
    return "[" + v + "]"


def main(argv=None):
    ap = argparse.ArgumentParser(description="修订 物资映射.csv 的显示名称")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)

    var = {}
    with open(VAR_CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if int(r["库内行数"] or 0) > 0:            # 只处理存档里真的出现过的物件
                var[r["物件id"]] = r
    prefab = {str(k): v for k, v in json.load(open(PREFAB_MAP, encoding="utf-8")).items() if v}

    with open(MAP_CSV, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    fields = list(rows[0].keys())
    byid = {r["编号"]: r for r in rows}

    # 库内出现、但 CSV 里没有的物件 → 追加
    for oid in sorted(var, key=int):
        if oid not in byid:
            r = {"编号": oid, "名称": "", "英文名": "", "预制体": "", "图标": ""}
            rows.append(r)
            byid[oid] = r

    changed = []
    for oid, r in byid.items():
        v = var.get(oid)
        if not v:
            continue
        oid_int = int(oid)
        if oid_int > 2042 or oid_int < 0:              # 非物件 id（旧表里混进来的物品 id），不动
            continue
        old = (r.get("名称") or "").strip()
        item = (v.get("物品名") or "").strip()
        pf = prefab.get(oid, "")
        if item:
            new = item + suffix(v.get("变体"))
        elif not old:
            base = pf.rsplit("/", 1)[-1] if pf else ""
            new = PREFAB_CN.get(base, "")
            if new and not new.endswith("]"):
                new += suffix(v.get("变体"))
        else:
            new = old
            if not new.endswith("]"):
                new += suffix(v.get("变体"))
        if new and new != old:
            changed.append((oid, old, new, v.get("变体"), pf))
            r["名称"] = new
        if pf and (r.get("预制体") or "").strip() != pf:
            r["预制体"] = pf
        if not (r.get("英文名") or "").strip() and pf:
            r["英文名"] = pf.rsplit("/", 1)[-1]

    print("库内物件 %d 个；改名 %d 条" % (len(var), len(changed)))
    for c in changed:
        print("   %-5s %-14s → %-16s (%s, %s)" % (c[0], c[1] or "(空)", c[2], c[3] or "普通", c[4].rsplit("/", 1)[-1]))


    empty = [oid for oid, v in var.items() if not (byid[oid].get("名称") or "").strip()]
    print("仍无名称（将显示 英文名 / #编号 + 首字徽标）%d 个：%s" % (len(empty), sorted(empty, key=int)))

    if a.dry:
        return 0
    if not os.path.exists(os.path.join(ROOT, "data", "物资映射.bak.csv")):
        shutil.copyfile(MAP_CSV, os.path.join(ROOT, "data", "物资映射.bak.csv"))
    rows.sort(key=lambda r: int(r["编号"]) if r["编号"].isdigit() else 0)

    def dump(path):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    try:
        dump(MAP_CSV)
        print("已写入 %s（备份 物资映射.bak.csv）" % MAP_CSV)
    except PermissionError:
        alt = os.path.join(ROOT, "data", "物资映射.new.csv")
        dump(alt)
        print("！%s 被其它程序占用（Excel/WPS 打开了？）" % MAP_CSV)
        print("！已写入 %s，关闭占用后把它改名覆盖即可" % alt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
