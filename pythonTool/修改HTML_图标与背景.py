# -*- coding: utf-8 -*-
"""一次性修改 物资地图.html / index.html:
1) 物资图标改为优先加载 wupingIcon/, 未命中时 onerror 回退 ../assets/Texture2D,
   两级都缺失时显示 ? 占位(不出破图);
2) 新增"背景图"开关按钮, 控制是否在地图下方显示 地图图片/dituBack.png (羊皮纸底衬),
   选择状态存入 localStorage。
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
    # 图标基础路径: wupingIcon 优先, 记录回退目录
    html = patch(
        html,
        'const ICON_BASE = "../assets/Texture2D";',
        'const ICON_BASE = "wupingIcon";            // 图标覆盖目录: 优先加载\n'
        'const FALLBACK_ICON_BASE = "../assets/Texture2D";  // wupingIcon 缺失时回退',
        marker='const FALLBACK_ICON_BASE',
    )

    # 列表图标: wupingIcon -> assets 两级回退, 都失败换 ? 占位
    html = patch(
        html,
        'const im = info.icon ? `<img loading="lazy" src="${ICON_BASE}/${info.icon}">`'
        " : '<span style=\"width:26px;text-align:center\">?</span>';",
        'const im = info.icon ? `<img loading="lazy" src="${ICON_BASE}/${info.icon}"'
        ' onerror="if(!this.dataset.f){this.dataset.f=1;'
        "this.src='${FALLBACK_ICON_BASE}/${info.icon}'}"
        "else{this.replaceWith(Object.assign(document.createElement('span'),"
        "{style:'width:26px;text-align:center',textContent:'?'}))}\">`"
        " : '<span style=\"width:26px;text-align:center\">?</span>';",
        marker='textContent:\'?\'',
    )

    # 背景图常量 + 开关状态(本地记忆)
    html = patch(
        html,
        "const app = { map: null, scale: 1, tx: 0, ty: 0, marks: [], active: [] };"
        "   // active: 摆放id(字符串), 按选择顺序, 最多5",
        'const BACK_IMG = "地图图片/dituBack.png";  // 可开关的羊皮纸背景图\n'
        "const app = { map: null, scale: 1, tx: 0, ty: 0, marks: [], active: [],"
        " showBack: (() => { try { return localStorage.getItem('aehyShowBack') !== '0'; } catch(e){ return true; } })() };"
        "   // active: 摆放id(字符串), 按选择顺序, 最多5",
        marker="const BACK_IMG",
    )

    # 背景图层管理函数(插入在 loadMap 之前)
    html = patch(
        html,
        "function loadMap(lv){",
        """// ---------- 可开关的背景图 ----------
let backImgEl = null;
function updateBack(){
  if (backImgEl){ backImgEl.remove(); backImgEl = null; }
  if (!app.showBack || !app.map) return;
  backImgEl = document.createElement('img');
  backImgEl.className = 'bg';
  backImgEl.src = BACK_IMG;
  backImgEl.style.left = (-app.map.tw * 0.06) + 'px';   // 四周露出 6% 边框
  backImgEl.style.top = (-app.map.th * 0.06) + 'px';
  backImgEl.style.width = (app.map.tw * 1.12) + 'px';
  backImgEl.style.height = (app.map.th * 1.12) + 'px';
  world.insertBefore(backImgEl, world.firstChild);
}
function renderBackBtn(){
  const b = document.getElementById('backBtn');
  b.textContent = app.showBack ? '背景图:开' : '背景图:关';
  b.style.color = app.showBack ? '#7fc' : '#8aa';
}
function loadMap(lv){""",
        marker="let backImgEl",
    )

    # loadMap 内重建背景层
    html = patch(
        html,
        "  world.appendChild(bg);",
        "  world.appendChild(bg);\n  backImgEl = null; updateBack();",
        marker="backImgEl = null; updateBack();",
    )

    # 顶栏按钮
    html = patch(
        html,
        '<button id="allBtn">Top5</button><button id="noneBtn">清空</button>',
        '<button id="allBtn">Top5</button><button id="noneBtn">清空</button>'
        '<button id="backBtn">背景图:开</button>',
        marker='<button id="backBtn">',
    )

    # 按钮事件
    html = patch(
        html,
        "document.getElementById('noneBtn').onclick = () => { app.active = []; buildList(); refresh(); };",
        "document.getElementById('noneBtn').onclick = () => { app.active = []; buildList(); refresh(); };\n"
        "document.getElementById('backBtn').onclick = () => {\n"
        "  app.showBack = !app.showBack;\n"
        "  try { localStorage.setItem('aehyShowBack', app.showBack ? '1' : '0'); } catch(e){}\n"
        "  renderBackBtn(); updateBack();\n"
        "};",
        marker="localStorage.setItem('aehyShowBack'",
    )

    # 启动时同步按钮文字
    html = patch(
        html,
        "(async () => {\n  const ok = await loadGlobalItems();",
        "(async () => {\n  renderBackBtn();\n  const ok = await loadGlobalItems();",
        marker="renderBackBtn();\n  const ok = await loadGlobalItems();",
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
