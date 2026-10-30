# -*- coding: utf-8 -*-
r"""未填中文名的物资，各处以英文名/编号回退显示（而不是空白）。

用途：新版本补充进 data/物资映射.csv 的条目只有英文名，中文待手工补；
补之前会显示成空白，看不出是哪个东西。此脚本把三处渲染都改成
  名称 → 英文名 → #编号
三级回退，只改渲染表达式，不动其它逻辑：
  1. 左侧列表标题   <span>${info.nm}</span>
  2. 图例/底部名称牌 ${it.nm} <span ...>#${id}</span>
  3. 右键详情卡片    <b>${info.nm}</b>

幂等：已改过则跳过。同时写 物资地图.html 与 index.html。
"""
import io, os, sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ["物资地图.html", "index.html"]

# (旧, 新, 说明)
REPS = [
    ("<span>${info.nm}</span>",
     "<span>${info.nm || info.en || ('#' + id)}</span>",
     "列表标题"),
    ("${it.nm} <span style=\"color:#789\">#${id}</span>",
     "${it.nm || it.en || ('#' + id)} <span style=\"color:#789\">#${id}</span>",
     "图例/名称牌"),
    ("<b>${info.nm}</b>",
     "<b>${info.nm || info.en || ('#' + it.id)}</b>",
     "详情卡片"),
    # 早期版本写过的冗余形式，顺带规范化
    ("<b>${info.nm || info.en || ('#' + (it && it.id || ''))}</b>",
     "<b>${info.nm || info.en || ('#' + it.id)}</b>",
     "详情卡片(旧)"),
]


def patch(path):
    t = open(path, encoding="utf-8").read()
    msgs = []
    for old, new, tag in REPS:
        if new in t:
            msgs.append("%s:已应用" % tag)
            continue
        if old not in t:
            msgs.append("%s:!未找到" % tag)
            continue
        n = t.count(old)
        t = t.replace(old, new)
        msgs.append("%s:替换%d处" % (tag, n))
    open(path, "w", encoding="utf-8", newline="").write(t)
    return " ".join(msgs)


for f in FILES:
    p = os.path.join(OUT, f)
    if not os.path.exists(p):
        print("! 缺文件", p)
        continue
    print("%-14s %s" % (f, patch(p)))
