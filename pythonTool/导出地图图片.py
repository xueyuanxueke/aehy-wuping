# -*- coding: utf-8 -*-
"""把 物资地图.html / index.html 中 SCENES 各地图的 base64 背景大图提取为外部
PNG 文件(地图图片/), 并将 HTML 里的 "bg": "data:image/png;base64,..." 替换为
相对路径引用。<img src> 相对路径不受 file:// CORS 限制, 双击直接打开也能加载。
可重复运行: 已是外部路径时自动跳过。在 物资一览/ 或 pythonTool/ 下运行均可。
用法: python pythonTool/导出地图图片.py
"""
import base64
import io
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE) if os.path.basename(HERE) == "pythonTool" else HERE
PATHS = [os.path.join(ROOT, "物资地图.html"), os.path.join(ROOT, "index.html")]
OUT_DIR = os.path.join(ROOT, "地图图片")

os.makedirs(OUT_DIR, exist_ok=True)

def png_size(b):
    assert b[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    w = int.from_bytes(b[16:20], "big")
    h = int.from_bytes(b[20:24], "big")
    return w, h

for path in PATHS:
    print(f"== {os.path.basename(path)} ==")
    with io.open(path, encoding="utf-8") as f:
        html = f.read()

    m = re.search(r"const SCENES = ", html)
    data, _ = json.JSONDecoder().raw_decode(html[m.end():])

    changed = False
    for key, sc in data.items():
        bg = sc["bg"]
        if not bg.startswith("data:image/"):
            print(f"  图{key} {sc['name']}: 已是外部路径, 跳过")
            continue
        header, b64 = bg.split(",", 1)
        ext = header.split(":")[1].split(";")[0].split("/")[1]
        raw = base64.b64decode(b64)
        w, h = png_size(raw)
        assert (w, h) == (sc["tw"], sc["th"]), f"图{key} 尺寸不符: {w}x{h}"
        fname = f"图{key}_{sc['name']}.{ext}"
        png_path = os.path.join(OUT_DIR, fname)
        if not (os.path.exists(png_path) and open(png_path, "rb").read() == raw):
            with open(png_path, "wb") as f:
                f.write(raw)
        assert html.count(bg) == 1
        html = html.replace(bg, f"地图图片/{fname}")
        changed = True
        print(f"  图{key} {sc['name']}: {len(raw)/1e6:.2f} MB -> 地图图片/{fname} ({w}x{h})")

    if changed:
        with io.open(path, "w", encoding="utf-8", newline="") as f:
            f.write(html)
        print(f"  新大小: {len(html.encode('utf-8'))/1e6:.2f} MB")
print("OK")
