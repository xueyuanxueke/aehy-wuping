# -*- coding: utf-8 -*-
"""
把「物资位置」改成外部数据源：网页启动时 fetch data/物资位置.json，
成功后用它覆盖 SCENES 里每张图的 rows / prm / tw / th / bg，并补齐存档里
新增的地图（如 level 15 纳米比亚）；失败则继续用 HTML 内联的旧数据。

幂等：重复运行只会替换 /*===WUP_BEGIN===*/ … /*===WUP_END===*/ 之间的内容。
同时写 物资地图.html 与 index.html（两者内容必须一致）。

用法：
    python pythonTool/新增HTML_物资数据外置.py
    python pythonTool/新增HTML_物资数据外置.py --data data/物资位置.json
"""
import argparse
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

BEGIN = "/*===WUP_BEGIN===*/"
END = "/*===WUP_END===*/"
# 插在 zone 模块之后、初始化 IIFE 之前，这样能用上 rebuildMapSel / applyMap
ANCHOR = "/*===ZONE_END===*/\n(async () => {"

TEMPLATE = r'''/*===WUP_BEGIN===*/
// ---------------- 物资位置：外部数据源 ----------------
// data/物资位置.json 由 pythonTool/导出物资位置.py 从存档数据库导出。
// 加载成功 -> 覆盖 SCENES 的 rows/prm/tw/th/bg，并补齐存档里才有的新地图；
// 加载失败（例如直接双击打开、file:// 下 fetch 被拦） -> 沿用本文件内联的旧数据。
const WUP_URL = "@@URL@@";

// 没有底图的地图（如 level 15 纳米比亚）：临时画一张网格当坐标系底图
function wupNoBg(tw, th) {
  const s = "<svg xmlns='http://www.w3.org/2000/svg' width='" + tw + "' height='" + th + "'>" +
    "<defs><pattern id='g' width='40' height='40' patternUnits='userSpaceOnUse'>" +
    "<path d='M40 0H0V40' fill='none' stroke='#1b2226' stroke-width='1'/></pattern></defs>" +
    "<rect width='100%' height='100%' fill='#12171a'/>" +
    "<rect width='100%' height='100%' fill='url(#g)'/></svg>";
  return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(s);
}

// 包一层 loadMap：bg 为空时现画一张网格底图，其余逻辑完全走原函数
(function () {
  const orig = loadMap;
  loadMap = function (lv) {
    const sc = SCENES[lv];
    if (sc && !sc.bg) sc.bg = wupNoBg(sc.tw, sc.th);
    return orig(lv);
  };
})();

// 返回新数据的点位总数；失败返回 -1
async function loadWupingData() {
  try {
    const res = await fetch(WUP_URL, { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const D = await res.json();
    if (!D.places || !D.places.length) throw new Error("空数据");
    let n = 0;
    for (const p of D.places) {
      let sc = SCENES[p.level];
      if (!sc) sc = SCENES[p.level] = { name: "图" + p.level, prm: p.prm, tw: p.tw, th: p.th, bg: p.bg, rows: [], items: {} };
      if (p.name) sc.name = p.name;
      if (p.prm) sc.prm = p.prm;
      if (p.tw) sc.tw = p.tw;
      if (p.th) sc.th = p.th;
      if (typeof p.bg === "string") sc.bg = p.bg;
      if (p.prmSource) sc.prmSource = p.prmSource;
      sc.rows = (p.rows || []).map(r => ({ id: r[0], x: r[1], z: r[2], s: r[3], tag: r[4] }));
      delete sc._items;            // 让 sceneItems() 按新 rows 重算数量与图标
      n += sc.rows.length;
    }
    // 没有真实底图的地图（图15 纳米比亚）：prm 原本只按物资点算，猎物区域框会伸到网格外，
    // 这里把 prm 撑到「物资点 ∪ 猎物区域」的并集，让两类标记都落在同一张坐标系里
    if (typeof ZDATA !== "undefined" && ZDATA.places) {
      for (const p of D.places) {
        const sc = SCENES[p.level];
        if (!sc || (sc.bg && sc.bg.indexOf("data:image/svg") !== 0)) continue;
        const zp = ZDATA.places.find(x => x.place === p.level);
        if (!zp || !zp.bounds) continue;
        const b0 = sc.prm;
        sc.prm = [b0[0], b0[1],
                  Math.min(b0[2], zp.bounds.minX), Math.max(b0[3], zp.bounds.maxX),
                  Math.max(b0[4], zp.bounds.maxZ), Math.min(b0[5], zp.bounds.minZ)];
      }
    }
    return n;
  } catch (e) {
    return -1;
  }
}

(async () => {
  const n = await loadWupingData();
  const badge = document.getElementById("srcBadge");
  if (badge && badge.parentNode) {
    const sp = document.createElement("span");
    sp.id = "wupBadge";
    sp.style.cssText = "font-size:12px;color:" + (n >= 0 ? "#7fc" : "#f96");
    sp.textContent = n >= 0 ? "数据:外置JSON " + n + "点" : "数据:内置";
    badge.insertAdjacentElement("afterend", sp);
  }
  if (n >= 0) { rebuildMapSel(); applyMap(); }
})();
/*===WUP_END===*/'''


def patch(t, url):
    # 数据目录调整后，映射表也从 data/ 读（幂等：替换过一次后匹配不到）
    t = t.replace('const CSV_URL = "物资映射.csv";', 'const CSV_URL = "data/物资映射.csv";')
    if BEGIN in t:
        i = t.index(BEGIN)
        j = t.index(END, i) + len(END)
        t = t[:i].rstrip() + "\n" + t[j:].lstrip("\n")
    block = TEMPLATE.replace("@@URL@@", url)
    if ANCHOR not in t:
        raise SystemExit("找不到插入锚点：/*===ZONE_END===*/ + (async () => {")
    return t.replace(ANCHOR, "/*===ZONE_END===*/\n" + block + "\n(async () => {", 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/物资位置.json", help="相对路径写进网页")
    a = ap.parse_args()

    src = os.path.join(ROOT, "物资地图.html")
    t = io.open(src, encoding="utf-8").read()
    n0 = len(t)
    t = patch(t, a.data.replace("\\", "/"))

    for f in ("物资地图.html", "index.html"):
        p = os.path.join(ROOT, f)
        io.open(p, "w", encoding="utf-8", newline="").write(t)
        print("已写入 %s  (%d -> %d 字符)" % (f, n0, len(t)))
    print("数据源：%s" % a.data)


if __name__ == "__main__":
    main()
