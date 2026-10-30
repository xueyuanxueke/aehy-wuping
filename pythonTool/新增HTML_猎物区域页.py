# -*- coding: utf-8 -*-
"""给物资地图网页增加「猎物区域」Tab（第二个页签）。

数据来自 ../data/猎物区域.json（由 _fish/build_zone_json.py 生成，字段说明见该文件 meta）。
本脚本只做注入，不产生新数据；可重复运行，每次都会用最新的 json 覆盖页面里的旧数据。

用法：
    python pythonTool/新增HTML_猎物区域页.py
"""

import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.dirname(HERE)
DATA_DIR = os.path.join(OUT, "data")
DATA = os.path.join(DATA_DIR, "猎物区域.json")
DATA_MIN = os.path.join(DATA_DIR, "猎物区域.min.json")
TARGETS = ["物资地图.html", "index.html"]

MARK_BEGIN = "/*===ZONE_BEGIN===*/"
MARK_END = "/*===ZONE_END===*/"

CSS = """<style id="zoneStyle">
 /* ---- 猎物区域 Tab ---- */
 #tabs{display:inline-flex;border:1px solid #3a444a;border-radius:5px;overflow:hidden;flex:none}
 #tabs button{border:0;border-radius:0;background:#262e32;color:#cde;padding:4px 12px;font-size:13px}
 #tabs button.on{background:#2f7a52;color:#fff}
 #zoneLayer{position:absolute;left:0;top:0;pointer-events:none}
 #zoneLayer .zbox{position:absolute;box-sizing:border-box;border:1px solid;pointer-events:auto;cursor:pointer;transition:opacity .12s}
 #zoneLayer .zbox.on{border-width:2px;box-shadow:0 0 0 1px #000a}
 #zoneLayer .zbox.dim{opacity:.26}
 #app:not(.tab-zone) #zoneLayer{display:none}
 #app.tab-zone .mk{display:none}
 .zph{width:26px;height:26px;flex:none;display:inline-flex;align-items:center;justify-content:center;
      border-radius:5px;font-size:13px;color:#fff;background:#33424a;margin-right:0}
 .synthbg{position:absolute;left:0;top:0;background:#12171a;
      background-image:linear-gradient(#1b2226 1px,transparent 1px),linear-gradient(90deg,#1b2226 1px,transparent 1px);
      background-size:40px 40px}
</style>"""

TABS = ('<span id="tabs"><button class="tab on" data-tab="wuping">物资位置</button>'
        '<button class="tab" data-tab="zone">猎物区域</button></span>')

JS = r"""
/*===ZONE_BEGIN===*/
/* ---- 猎物区域 Tab（由 pythonTool/新增HTML_猎物区域页.py 注入，请勿手改） ---- */
const ZDATA = __ZDATA__;
const ZPAL = ['#4fc3f7','#81c784','#ffb74d','#e57373','#ba68c8','#4db6ac','#f06292',
              '#9575cd','#ffd54f','#7986cb','#a1887f','#aed581','#b39ddb','#ff8a65'];
let MODE = 'wuping';
let zoneSel = [];
let zoneLayer = null;
let zoneBoxes = [];
const ZSYN = {};

const ZKEYS = Object.keys(ZDATA.animals).map(Number).sort((a, b) => a - b);
const zAnim = k => ZDATA.animals[k] || { zh: '#' + k, en: '', icon: null };
const zPlace = lv => ZDATA.places.find(p => p.place === +lv) || null;
const zMapName = id => SCENES[id] ? SCENES[id].name : ('Place' + id + '（无背景图）');
/* 颜色按「当前地图内第几种猎物」分配，保证同图配色不重复 */
function zColor(k) {
  const pl = zPlace(document.getElementById('mapSel').value);
  const i = pl ? pl.animals.findIndex(a => a.key === k) : -1;
  return ZPAL[(i < 0 ? ZKEYS.indexOf(k) : i) % ZPAL.length];
}

/* 没有背景图的地图（图10 / 图12）：按区域包围盒合成 prm，1 世界单位 = 2px */
function zSynth(pl) {
  if (ZSYN[pl.place]) return ZSYN[pl.place];
  const b = pl.bounds, pad = 0.05, k = 2;
  const spanX = b.maxX - b.minX, spanZ = b.maxZ - b.minZ;
  const sx = spanX * (1 + pad * 2), sz = spanZ * (1 + pad * 2);
  const l = b.minX - spanX * pad, t = b.maxZ + spanZ * pad;
  return ZSYN[pl.place] = {
    name: pl.name, bg: null, synthetic: true, items: {}, rows: [],
    tw: Math.max(64, Math.round(sx * k)), th: Math.max(64, Math.round(sz * k)),
    prm: [sx, sz, l, l + sx, t, t - sz]
  };
}

function zGetLayer() {
  if (!zoneLayer || !zoneLayer.parentNode) {
    zoneLayer = document.createElement('div');
    zoneLayer.id = 'zoneLayer';
    world.appendChild(zoneLayer);
  }
  return zoneLayer;
}

/* 世界坐标 -> 图片像素：px = (x-l)/(r-l)*tw , py = (t-z)/(t-b)*th */
function renderZones() {
  const box = zGetLayer();
  box.innerHTML = '';
  zoneBoxes = [];
  const pl = zPlace(document.getElementById('mapSel').value);
  if (!pl || !app.map) return;
  const prm = app.map.prm, tw = app.map.tw, th = app.map.th;
  const l = prm[2], r = prm[3], t = prm[4], b = prm[5];
  box.style.width = tw + 'px';
  box.style.height = th + 'px';
  const anySel = zoneSel.length > 0;
  for (const a of pl.animals) {
    const on = zoneSel.indexOf(a.key) >= 0, col = zColor(a.key), info = zAnim(a.key);
    for (const bx of a.boxes) {
      const x0 = (bx.minX - l) / (r - l) * tw, x1 = (bx.maxX - l) / (r - l) * tw;
      const y0 = (t - bx.maxZ) / (t - b) * th, y1 = (t - bx.minZ) / (t - b) * th;
      const d = document.createElement('div');
      d.className = 'zbox' + (on ? ' on' : '') + (anySel && !on ? ' dim' : '');
      d.style.left = x0 + 'px';
      d.style.top = y0 + 'px';
      d.style.width = Math.max(1, x1 - x0) + 'px';
      d.style.height = Math.max(1, y1 - y0) + 'px';
      d.style.borderColor = col;
      d.style.background = col + (on ? '3d' : '17');
      d.dataset.z = a.key;
      d.dataset.tip = '<b>' + info.zh + '</b> <span style="color:#9ab">' + (info.en || '') + '</span><br>' +
        'x ' + bx.minX + ' ~ ' + bx.maxX + '<br>z ' + bx.minZ + ' ~ ' + bx.maxZ;
      box.appendChild(d);
      zoneBoxes.push(d);
    }
  }
}

function buildZoneList() {
  const list = document.getElementById('list');
  const q = document.getElementById('searchBox').value.trim().toLowerCase();
  const pl = zPlace(document.getElementById('mapSel').value);
  list.innerHTML = '';
  if (!pl) {
    list.innerHTML = '<div style="color:#789;padding:10px">该地图无猎物区域数据</div>';
    return;
  }
  const arr = pl.animals.slice().sort((x, y) => y.boxes.length - x.boxes.length);
  for (const a of arr) {
    const info = zAnim(a.key), sel = zoneSel.indexOf(a.key) >= 0;
    if (q && !((info.zh || '') + (info.en || '') + a.key).toLowerCase().includes(q)) continue;
    const im = info.icon
      ? '<img loading="lazy" src="' + ICON_BASE + '/' + info.icon + '" onerror="this.replaceWith(Object.assign(document.createElement(\'span\'),{className:\'zph\',textContent:\'' + (info.zh || '?').charAt(0) + '\'}))">'
      : '<span class="zph" style="background:' + zColor(a.key) + '">' + (info.zh || '?').charAt(0) + '</span>';
    const cd = sel
      ? '<span class="cdot" style="background:' + zColor(a.key) + '"></span>'
      : '<span class="cdot" style="background:transparent;border-color:#456"></span>';
    const d = document.createElement('div');
    d.className = 'item' + (sel ? ' sel' : ' off');
    d.innerHTML = cd + im + '<span>' + info.zh + '</span>' +
      '<span class="wid">' + (info.en || a.key) + '</span>' +
      '<span class="cnt">' + a.boxes.length + '框</span>';
    if (info.nameSrc === 'inferred') d.title = '中文名为按枚举名推断，可能不准';
    d.onclick = () => toggleZone(a.key);
    list.appendChild(d);
  }
}

function buildZoneLegend() {
  const lg = document.getElementById('legend');
  const pl = zPlace(document.getElementById('mapSel').value);
  if (!pl) { lg.innerHTML = ''; return; }
  const nBox = pl.animals.reduce((s, a) => s + a.boxes.length, 0);
  let html = '<div style="color:#9ab;margin-bottom:2px">' + zMapName(pl.place) +
    ' · 猎物活动区 ' + pl.animals.length + ' 种 / ' + nBox + ' 框</div>';
  if (zoneSel.length) {
    html += zoneSel.map(k => {
      const a = pl.animals.find(x => x.key === k);
      return '<div class="row"><span class="chip" style="background:' + zColor(k) + '"></span>' +
        zAnim(k).zh + ' <span style="color:#8aa">' + (a ? a.boxes.length : 0) + ' 框</span></div>';
    }).join('');
  } else {
    html += '<div style="color:#789">点左侧猎物高亮其活动区（可多选）</div>';
  }
  lg.innerHTML = html;
  document.getElementById('stat').textContent =
    '猎物 ' + pl.animals.length + ' 种 / ' + nBox + ' 个框 · 已选 ' + zoneSel.length;
}

function toggleZone(k) {
  const i = zoneSel.indexOf(k);
  if (i >= 0) zoneSel.splice(i, 1); else zoneSel.push(k);
  renderZones(); buildZoneList(); buildZoneLegend();
}

/* 无背景图的地图：手动搭一个最小场景 */
function mountSynthetic(pl) {
  const o = zSynth(pl);
  app.map = o;
  app.active = [];
  app.marks = [];
  world.innerHTML = '';
  zoneLayer = null;
  zoneBoxes = [];
  const bd = document.createElement('div');
  bd.className = 'synthbg';
  bd.style.width = o.tw + 'px';
  bd.style.height = o.th + 'px';
  world.appendChild(bd);
  backImgEl = null;
  updateBack();
  fit();
}

function rebuildMapSel() {
  const s = document.getElementById('mapSel');
  const cur = +s.value;
  const ids = MODE === 'zone'
    ? ZDATA.places.map(p => p.place)
    : Object.keys(SCENES).map(Number);
  s.innerHTML = '';
  for (const id of ids) {
    const o = document.createElement('option');
    o.value = id;
    const nm = zMapName(id);
    o.textContent = '图' + id + ' ' + nm;
    s.appendChild(o);
  }
  s.value = ids.indexOf(cur) >= 0 ? cur : ids[0];
}

function applyMap() {
  const id = +document.getElementById('mapSel').value;
  if (MODE === 'zone') {
    const pl = zPlace(id);
    if (!pl) return;
    if (SCENES[id]) loadMap(id); else mountSynthetic(pl);
    renderZones(); buildZoneList(); buildZoneLegend();
  } else {
    if (!SCENES[id]) return;
    loadMap(id);
  }
}

function setMode(m) {
  if (MODE === m) return;
  MODE = m;
  document.getElementById('app').classList.toggle('tab-zone', m === 'zone');
  document.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === m));
  document.getElementById('allBtn').textContent = m === 'zone' ? '全选' : 'Top5';
  const hint = document.querySelector('#bar .hint'), sb = document.getElementById('sideBtn');
  if (hint) hint.textContent = m === 'zone'
    ? '滚轮/双指缩放 · 拖拽平移 · 悬停看框坐标 · 点左侧猎物高亮其活动区(可多选)'
    : '滚轮/双指缩放 · 拖拽平移 · 悬停或点圆点看详情 · 点左侧条目选物资(最多5种) · 双击放大';
  if (sb) sb.textContent = m === 'zone' ? '☰ 猎物' : '☰ 物资';
  if (m !== 'zone') zoneSel = [];
  rebuildMapSel();
  applyMap();
}

/* ---- 绑定（覆盖原有的事件处理） ---- */
document.querySelectorAll('#tabs button').forEach(b => { b.onclick = () => setMode(b.dataset.tab); });
document.getElementById('mapSel').onchange = applyMap;
document.getElementById('searchBox').oninput = () => { MODE === 'zone' ? buildZoneList() : buildList(); };
document.getElementById('allBtn').onclick = () => {
  if (MODE === 'zone') {
    const pl = zPlace(document.getElementById('mapSel').value);
    zoneSel = pl ? pl.animals.map(a => a.key) : [];
    renderZones(); buildZoneList(); buildZoneLegend();
  } else { app.active = topIds(MAXSEL); buildList(); refresh(); }
};
document.getElementById('noneBtn').onclick = () => {
  if (MODE === 'zone') {
    zoneSel = [];
    renderZones(); buildZoneList(); buildZoneLegend();
  } else { app.active = []; buildList(); refresh(); }
};
view.addEventListener('pointermove', e => {
  if (MODE !== 'zone') return;
  const el = e.target.closest && e.target.closest('.zbox');
  if (!el) return;
  tip.style.display = 'block';
  tip.innerHTML = el.dataset.tip;
  tip.style.left = (e.clientX + 14) + 'px';
  tip.style.top = (e.clientY + 12) + 'px';
});
view.addEventListener('click', e => {
  if (MODE !== 'zone') return;
  const el = e.target.closest && e.target.closest('.zbox');
  if (el) toggleZone(+el.dataset.z);
});
/*===ZONE_END===*/
"""


def patch(name):
    path = os.path.join(OUT, name)
    t = io.open(path, encoding="utf-8").read()
    orig = len(t)

    # 1) CSS
    t = re.sub(r'<style id="zoneStyle">[\s\S]*?</style>\n?', "", t)
    t = t.replace("</head>", CSS + "\n</head>", 1)

    # 2) Tab 栏
    t = re.sub(r'<span id="tabs">[\s\S]*?</span>', "", t, count=1)
    anchor = '<select id="mapSel"></select>'
    if anchor not in t:
        raise SystemExit("找不到锚点: " + anchor)
    t = t.replace(anchor, TABS + anchor, 1)

    # 3) JS 模块
    t = t.replace(".\n\n" + MARK_BEGIN, MARK_BEGIN)   # 清理历史误注入
    t = re.sub(re.escape(MARK_BEGIN) + r'[\s\S]*?' + re.escape(MARK_END) + r'\n?', "", t)
    js = JS.replace("__ZDATA__", jsondata)
    hook = "(async () => {\n  renderBackBtn();"
    if hook not in t:
        raise SystemExit("找不到初始化锚点")
    t = t.replace(hook, js + hook, 1)

    io.open(path, "w", encoding="utf-8").write(t)
    print("  %-14s %8d -> %8d 字符" % (name, orig, len(t)))


jsondata = io.open(DATA_MIN, encoding="utf-8").read().strip()
d = json.loads(jsondata)
print("数据: %d 种猎物 / %d 张地图 / %d 个框" % (
    len(d["animals"]), len(d["places"]),
    sum(len(a["boxes"]) for p in d["places"] for a in p["animals"])))
for n in TARGETS:
    patch(n)
print("完成")
