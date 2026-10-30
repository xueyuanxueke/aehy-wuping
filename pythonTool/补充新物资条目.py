# -*- coding: utf-8 -*-
"""把新版本里出现、但 物资映射.csv 还没有的物资/猎物补进去（只填编号 + 英文名，中文留空待手工补）。

数据来源：
  data/物资位置.json       —— 存档里实际出现过的 id（优先，必须能显示）
  enums.json（可选）        —— Wuping 枚举 值->名，用于填 英文名

用法：
  python 补充新物资条目.py [--dry]
  可用环境变量 AEHY_ENUMS 指定 enums.json 路径，
  默认 <AEHY>\..\_fish\v261030\enums.json（不存在时 英文名 留空）
"""
import csv, io, json, os, sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

OUT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # ...\物资一览
AEHY = os.path.dirname(OUT)
CSV  = os.path.join(OUT, "data", "物资映射.csv")
WUP  = os.path.join(OUT, "data", "物资位置.json")
ENUM = os.environ.get("AEHY_ENUMS", os.path.join(AEHY, "_fish", "v261030", "enums.json"))
DRY  = "--dry" in sys.argv
COLS = ["编号", "名称", "英文名", "预制体", "图标"]

rows = list(csv.DictReader(open(CSV, encoding="utf-8-sig")))
have = {int(r["编号"]) for r in rows if r["编号"].strip()}

# 1) 存档里出现过的 id
used = set()
if os.path.exists(WUP):
    for p in json.load(open(WUP, encoding="utf-8"))["places"]:
        for r in p["rows"]:
            used.add(int(r[0]))

# 2) 枚举名（Wuping / BuildThing 都可能是物资）
name_of = {}
if os.path.exists(ENUM):
    en = json.load(open(ENUM, encoding="utf-8"))
    for tbl in ("Wuping", "BuildThing"):
        for k, v in en.get(tbl, {}).items():
            name_of.setdefault(int(k), v)
else:
    print("! 未找到 enums.json（%s），英文名将留空" % ENUM)

# 3) 待补 = 存档里出现但 CSV 没有的
todo = {i for i in used if i not in have}
#     + 新版本新增枚举（>=460）里 CSV 也没有的
todo |= {i for i in name_of if i >= 460 and i not in have}

add = []
for i in sorted(todo):
    nm = name_of.get(i, "")
    if nm == "None":           # 枚举里有个占位成员就叫 None，不代表物资名
        nm = ""
    add.append({"编号": str(i), "名称": "", "英文名": nm, "预制体": "", "图标": ""})

print("CSV 现有 %d 条；存档出现 %d 个 id；本次补 %d 条" % (len(rows), len(used), len(add)))
for a in add:
    print("   + %-5s %s" % (a["编号"], a["英文名"] or "(无英文名)"))

if not add:
    print("无需改动")
    sys.exit(0)
if DRY:
    print("\n--dry：未写入")
    sys.exit(0)

allrows = rows + add
allrows.sort(key=lambda r: int(r["编号"]))
with open(CSV, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=COLS, lineterminator="\r\n")
    w.writeheader()
    for r in allrows:
        w.writerow({c: r.get(c, "") or "" for c in COLS})
print("\n已写入 %s（共 %d 条），中文名待补的行：%d" %
      (CSV, len(allrows), sum(1 for r in allrows if not (r["名称"] or "").strip())))

