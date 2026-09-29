# -*- coding: utf-8 -*-
"""把 物资映射.csv 中引用的全部图标, 从 assets/Sprite(优先) 和 assets/Texture2D
按文件名(忽略大小写)查找, 复制到 wupingIcon/ 下, 使页面不依赖仓库外的 assets 目录
(便于整个 物资一览/ 作为独立仓库同步/克隆/开 GitHub Pages)。
可重复运行: 内容相同的文件跳过, 内容不同则保留 wupingIcon 现有文件并提示。
在 物资一览/ 或 pythonTool/ 下运行均可。用法: python pythonTool/同步图标.py
"""
import csv
import filecmp
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE) if os.path.basename(HERE) == "pythonTool" else HERE
CSV = os.path.join(ROOT, "物资映射.csv")
ASSET_DIRS = [os.path.join(ROOT, "..", "assets", "Sprite"),
              os.path.join(ROOT, "..", "assets", "Texture2D")]
OUT_DIR = os.path.join(ROOT, "wupingIcon")

with open(CSV, encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

# CSV 引用的全部非空图标(忽略大小写去重)
wanted = sorted({(r["图标"] or "").strip().lower() for r in rows} - {""})
print(f"CSV 引用图标: {len(wanted)} 个")

idx = {}
for root in ASSET_DIRS:
    if not os.path.isdir(root):
        continue
    for fn in os.listdir(root):
        idx.setdefault(fn.lower(), os.path.join(root, fn))

os.makedirs(OUT_DIR, exist_ok=True)

copied = skipped = 0
missing = []
for low in wanted:
    src = idx.get(low)
    if not src:
        missing.append(low)
        continue
    dst = os.path.join(OUT_DIR, os.path.basename(src))
    if os.path.exists(dst):
        if filecmp.cmp(src, dst, shallow=False):
            skipped += 1
            continue
        print(f"!! {dst} 已存在且内容不同, 保留现有文件")
        continue
    shutil.copy2(src, dst)
    copied += 1

print(f"新复制 {copied} 个, 已存在跳过 {skipped} 个, 未找到 {len(missing)} 个")
if missing:
    print("未找到:", ", ".join(missing))
