# -*- coding: utf-8 -*-
"""从 物资地图.html 提取物资编号 → 名称/预制体/图标 的映射, 导出为 物资映射.csv
映射是全局的: 同一编号在所有地图中的 名称/英文名/预制体/图标 完全一致(已验证),
数量(count)可由 rows 摆放记录统计得出, 故 CSV 不含数量列。
用法: python 导出物资映射.py
"""
import csv
import json
import re

HTML = "物资地图.html"
CSV = "物资映射.csv"

with open(HTML, encoding="utf-8") as f:
    content = f.read()

m = re.search(r"const SCENES = ", content)
data, _ = json.JSONDecoder().raw_decode(content[m.end():])

# 合并所有地图的映射(静态字段跨地图一致)
merged = {}
for sc in data.values():
    for iid, info in sc["items"].items():
        merged.setdefault(
            int(iid),
            {
                "nm": info.get("nm", ""),
                "en": info.get("en", ""),
                "pf": info.get("pf", ""),
                "icon": info.get("icon") or "",
            },
        )

with open(CSV, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["编号", "名称", "英文名", "预制体", "图标"])
    for iid in sorted(merged):
        it = merged[iid]
        w.writerow([iid, it["nm"], it["en"], it["pf"], it["icon"]])

print(f"已导出 {len(merged)} 条映射 -> {CSV}")
