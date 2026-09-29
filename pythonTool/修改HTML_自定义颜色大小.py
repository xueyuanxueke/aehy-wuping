# -*- coding: utf-8 -*-
"""一次性修改 物资地图.html / index.html:
图例区每种物资支持自定义颜色与圆点大小——
  图例行新增 颜色选择器(input type=color) 和 大小输入框(px),
  即时作用于 地图圆点 / 图例 / 左侧列表圆点,
  按物资编号存入 localStorage('aehyCustom'), 刷新后保留, 提供"恢复默认样式"。
可重复运行: 以插入内容中的唯一标记判断是否已应用, 不会重复插入。"""
import io

PATHS = ["物资地图.html", "index.html"]

def patch(s, old, new, marker):
    if marker in s:
        print("  跳过(已应用):", marker)
        return s
    n = s.count(old)
    assert n == 1, f"expect 1 occurrence, got {n}: {old[:60]!r}"
    print("  应用:", marker)
    return s.replace(old, new)

def apply_patches(html):
    # 1) app 增加 custom 状态(本地记忆)
    html = patch(
        html,
        " showBack: (() => { try { return localStorage.getItem('aehyShowBack') !== '0'; } catch(e){ return true; } })() };",
        " showBack: (() => { try { return localStorage.getItem('aehyShowBack') !== '0'; } catch(e){ return true; } })(),\n"
        " custom: (() => { try { return JSON.parse(localStorage.getItem('aehyCustom') || '{}'); } catch(e){ return {}; } })() };",
        marker="aehyCustom",
    )

    # 2) 样式: 图例区的颜色/大小输入控件
    html = patch(
        html,
        " #legend .chip{width:13px;height:13px;border-radius:50%;border:1.5px solid #fff;flex:none;box-shadow:0 1px 2px #000a}",
        " #legend .chip{width:13px;height:13px;border-radius:50%;border:1.5px solid #fff;flex:none;box-shadow:0 1px 2px #000a}\n"
        " #legend input.chip{width:16px;height:16px;padding:0;border:1.5px solid #fff;border-radius:50%;background:none;cursor:pointer;flex:none}\n"
        " #legend input.chip::-webkit-color-swatch-wrapper{padding:0}\n"
        " #legend input.chip::-webkit-color-swatch{border:none;border-radius:50%}\n"
        " #legend .szin{width:32px;padding:1px 2px;font-size:11px;background:#262e32;color:#dde;border:1px solid #3a444a;border-radius:3px;text-align:center;flex:none}",
        marker="#legend input.chip",
    )

    # 3) 取色/取大小辅助函数(自定义优先, 否则按选择顺序配色/默认 5px)
    html = patch(
        html,
        "function refresh(){",
        """// ---------- 每种物资的自定义颜色/大小(浏览器本地记忆) ----------
function saveCustom(){
  try { localStorage.setItem('aehyCustom', JSON.stringify(app.custom)); } catch(e){}
}
function itemColor(id, ci){
  const c = app.custom[id];
  return (c && c.col) || COLORS[ci];
}
function itemSize(id){
  const c = app.custom[id];
  return (c && c.sz) ? c.sz : 5;
}
function refresh(){""",
        marker="function itemColor",
    )

    # 4) 地图圆点: 应用自定义颜色与大小
    html = patch(
        html,
        "    d.style.background = COLORS[ci];",
        "    d.style.background = itemColor(String(it.id), ci);\n"
        "    const dsz = itemSize(String(it.id));\n"
        "    if (dsz !== 5){ d.style.width = dsz + 'px'; d.style.height = dsz + 'px'; }",
        marker="itemSize(String(it.id))",
    )

    # 5) 图例: 每行加颜色选择器 + 大小输入框, 底部提供恢复默认
    html = patch(
        html,
        """  lg.innerHTML = app.active.length
    ? app.active.map(id => {
        const it = app.map.items[id];
        const ci = app.active.indexOf(id);
        return `<div class="row"><span class="chip" style="background:${COLORS[ci]}"></span>${it.nm} <span style="color:#789">#${id}</span> <span style="color:#8aa">×${it.count}</span></div>`;
      }).join('')
    : '<div style="color:#789">选择物资后显示圆点（最多5种）</div>';""",
        """  lg.innerHTML = app.active.length
    ? app.active.map(id => {
        const it = app.map.items[id];
        const ci = app.active.indexOf(id);
        return `<div class="row">` +
          `<input type="color" class="chip" value="${itemColor(id, ci)}" data-id="${id}" title="点击修改颜色">` +
          `<input type="number" class="szin" min="3" max="20" step="1" value="${itemSize(id)}" data-id="${id}" title="圆点大小(px)">` +
          `${it.nm} <span style="color:#789">#${id}</span> <span style="color:#8aa">×${it.count}</span></div>`;
      }).join('') +
      (app.active.some(id => app.custom[id])
        ? '<div class="row"><a href="javascript:void(0)" id="resetCustom" style="color:#789;font-size:12px">↺ 恢复默认样式</a></div>'
        : '')
    : '<div style="color:#789">选择物资后显示圆点（最多5种）</div>';
  document.querySelectorAll('#legend input[type="color"]').forEach(inp => {
    inp.oninput = () => {
      (app.custom[inp.dataset.id] = app.custom[inp.dataset.id] || {}).col = inp.value;
      saveCustom(); refresh();
    };
  });
  document.querySelectorAll('#legend .szin').forEach(inp => {
    inp.onchange = () => {
      const v = Math.max(3, Math.min(20, +inp.value || 5));
      inp.value = v;
      (app.custom[inp.dataset.id] = app.custom[inp.dataset.id] || {}).sz = v;
      saveCustom(); refresh();
    };
  });
  const rb = document.getElementById('resetCustom');
  if (rb) rb.onclick = () => {
    for (const id of app.active) delete app.custom[id];
    saveCustom(); refresh();
  };""",
        marker="id=\"resetCustom\"",
    )

    # 6) 左侧列表圆点同步自定义颜色
    html = patch(
        html,
        'const cd = sel ? `<span class="cdot" style="background:${COLORS[ci]}"></span>`',
        'const cd = sel ? `<span class="cdot" style="background:${itemColor(id, ci)}"></span>`',
        marker='class="cdot" style="background:${itemColor(id, ci)}"',
    )

    # 7) 改色时同步重绘左侧列表(圆点颜色即时更新)
    html = patch(
        html,
        "      (app.custom[inp.dataset.id] = app.custom[inp.dataset.id] || {}).col = inp.value;\n"
        "      saveCustom(); refresh();",
        "      (app.custom[inp.dataset.id] = app.custom[inp.dataset.id] || {}).col = inp.value;\n"
        "      saveCustom(); buildList(); refresh();",
        marker="saveCustom(); buildList(); refresh();",
    )

    # 8) loadMap 前插范围行改用 insertAdjacentHTML:
    #    原来的 "lg.innerHTML = 行 + lg.innerHTML" 会重建全部图例子节点,
    #    导致 refresh 刚挂上的颜色/大小控件事件丢失
    html = patch(
        html,
        "lg.innerHTML = `<div style=\"color:#9ab;margin-bottom:2px\">${range}</div>` + lg.innerHTML;",
        "lg.insertAdjacentHTML('afterbegin', `<div style=\"color:#9ab;margin-bottom:2px\">${range}</div>`);",
        marker="insertAdjacentHTML('afterbegin'",
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
