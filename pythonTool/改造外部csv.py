# -*- coding: utf-8 -*-
"""将 物资地图.html / index.html 改为优先从外部 物资映射.csv 加载物资编号→
名称/预制体/图标 映射, 加载失败(如 file:// 直开被 CORS 拦截)时回退内置映射。
可重复运行: 以插入内容中的唯一标记判断是否已应用, 不会重复插入。"""
import io

PATHS = ["物资地图.html", "index.html"]

def patch(s, old, new, marker):
    """marker: new 内容中足以代表"已应用"的唯一子串"""
    if marker in s:
        print("  跳过(已应用):", marker)
        return s
    n = s.count(old)
    assert n == 1, f"expect 1 occurrence, got {n}: {old[:60]!r}"
    print("  应用:", marker)
    return s.replace(old, new)

def apply_patches(html):
    html = patch(
        html,
        'const ICON_BASE = "../assets/Texture2D";',
        'const ICON_BASE = "../assets/Texture2D";\n'
        'const CSV_URL = "物资映射.csv";   // 外部映射表: 编号,名称,英文名,预制体,图标\n'
        "let GLOBAL_ITEMS = null;          // CSV 加载成功后的全局映射; null = 用内置映射",
        marker="const CSV_URL",
    )
    html = patch(
        html,
        "function loadMap(lv){",
        """// ---------- 外部 CSV 映射表 ----------
function parseCSV(text){
  const lines = text.replace(/^\\uFEFF/, '').split(/\\r?\\n/).filter(l => l.trim());
  const tbl = {};
  for (const line of lines.slice(1)){
    const c = line.split(',');
    if (c.length < 5 || !c[0].trim()) continue;
    tbl[c[0].trim()] = {nm: c[1].trim(), en: c[2].trim(), pf: c[3].trim(), icon: c[4].trim() || null};
  }
  return tbl;
}
async function loadGlobalItems(){
  try {
    const res = await fetch(CSV_URL, {cache: 'no-store'});
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const tbl = parseCSV(await res.text());
    if (Object.keys(tbl).length < 50) throw new Error('条目过少');
    GLOBAL_ITEMS = tbl;
    return true;
  } catch (e) { return false; }
}
// 每张图的 items: 优先由全局映射 + rows 摆放统计合成(数量可由 rows 推导)
function sceneItems(sc){
  if (!GLOBAL_ITEMS) return sc.items;
  if (!sc._items){
    const cnt = {};
    for (const r of sc.rows) cnt[r.id] = (cnt[r.id] || 0) + 1;
    sc._items = {};
    for (const id in cnt){
      const g = GLOBAL_ITEMS[id];
      if (g) sc._items[id] = {nm: g.nm, en: g.en, pf: g.pf, icon: g.icon, count: cnt[id]};
    }
  }
  return sc._items;
}
function loadMap(lv){""",
        marker="async function loadGlobalItems",
    )
    html = patch(
        html,
        "  const sc = SCENES[lv];\n  app.map = sc;",
        "  const sc = SCENES[lv];\n  app.map = sc;\n  sc.items = sceneItems(sc);",
        marker="sc.items = sceneItems(sc);",
    )
    html = patch(
        html,
        '<span style="color:#8aa" id="stat"></span>',
        '<span style="color:#8aa" id="stat"></span>\n'
        '  <span id="srcBadge" style="font-size:12px"></span>',
        marker='id="srcBadge"',
    )
    html = patch(
        html,
        "loadMap(1);",
        """(async () => {
  const ok = await loadGlobalItems();
  const badge = document.getElementById('srcBadge');
  if (ok){ badge.textContent = '映射:外部CSV'; badge.style.color = '#7fc'; }
  else { badge.textContent = '映射:内置(CSV未加载)'; badge.style.color = '#f96'; }
  loadMap(1);
})();""",
        marker="const ok = await loadGlobalItems();",
    )
    return html

for path in PATHS:
    print(f"== {path} ==")
    with io.open(path, encoding="utf-8") as f:
        html = f.read()
    html = apply_patches(html)
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(html)
print("OK")
