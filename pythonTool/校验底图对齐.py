# -*- coding: utf-8 -*-
r"""校验『底图 + prm』是否对得上：把物资点按网页同一套公式映射成像素，
再统计它们落在底图上的位置是否合理。只读，不改任何数据。

用法：
    python pythonTool/校验底图对齐.py             # 全部地图
    python pythonTool/校验底图对齐.py 15          # 只看图15

判读：
    图外     —— 点被画到画布外面，说明 prm 太小或整体偏移；出现即需修正。
    边带3%   —— 落在图像最外圈的点占比，偏高说明 prm 留白过大（图被压小）。
    最亮10%  —— 落在底图最亮那一档像素（羊皮纸空白/浅滩）上的点占比，
                官方 prm 的图通常在 0~12%，明显更高说明 prm 偏了。

参照：14 张 official 图实测 图外 0、(边带) 0~1.2%、(最亮) 0~11.2%。
"""
import io
import json
import os
import struct
import sys
import zlib

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


class _MiniPNG(object):
    """没有 Pillow 时的兜底解码器（8bit RGBA/RGB、非隔行——本目录底图全是 RGBA）。"""

    def __init__(self, path):
        b = open(path, "rb").read()
        if b[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("不是 PNG：%s" % path)
        self.size = struct.unpack(">II", b[16:24])
        ct, depth, inter = b[25], b[24], b[28]
        if depth != 8 or inter != 0 or ct not in (2, 6):
            raise ValueError("兜底解码器只支持 8bit RGB/RGBA 非隔行：%s" % path)
        self.bpp = 4 if ct == 6 else 3
        i, idat = 8, []
        while i < len(b):
            ln = struct.unpack(">I", b[i:i + 4])[0]
            typ = b[i + 4:i + 8]
            if typ == b"IDAT":
                idat.append(b[i + 8:i + 8 + ln])
            elif typ == b"IEND":
                break
            i += 12 + ln
        self._load(zlib.decompress(b"".join(idat)))

    def _load(self, raw):
        w, h, bpp = self.size[0], self.size[1], self.bpp
        stride = w * bpp
        self.rows, prev, pos = [], bytearray(stride), 0
        for _ in range(h):
            f = raw[pos]; pos += 1
            line = bytearray(raw[pos:pos + stride]); pos += stride
            if f == 1:
                for x in range(bpp, stride):
                    line[x] = (line[x] + line[x - bpp]) & 0xFF
            elif f == 2:
                for x in range(stride):
                    line[x] = (line[x] + prev[x]) & 0xFF
            elif f == 3:
                for x in range(stride):
                    a = line[x - bpp] if x >= bpp else 0
                    line[x] = (line[x] + ((a + prev[x]) >> 1)) & 0xFF
            elif f == 4:
                for x in range(stride):
                    a = line[x - bpp] if x >= bpp else 0
                    c = prev[x - bpp] if x >= bpp else 0
                    pa, pb, pc = abs(prev[x] - c), abs(a - c), abs(a + prev[x] - 2 * c)
                    pr = a if (pa <= pb and pa <= pc) else (prev[x] if pb <= pc else c)
                    line[x] = (line[x] + pr) & 0xFF
            self.rows.append(line)
            prev = line

    def load(self):
        w, h, bpp, rows = self.size[0], self.size[1], self.bpp, self.rows

        def px(x, y):
            o = x * bpp
            return (rows[y][o], rows[y][o + 1], rows[y][o + 2])
        return px


try:
    from PIL import Image
except ImportError:                     # 没装 pillow 也能跑
    Image = None


def open_image(path):
    if Image is not None:
        im = Image.open(path).convert("RGB")
        return im.size, (lambda x, y: im.getpixel((x, y)))
    im = _MiniPNG(path)
    return im.size, im.load()

OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(OUT, "data", "物资位置.json")


def check(p):
    w, h, l, r, t, b = p["prm"]
    tw, th = p["tw"], p["th"]
    size, px = open_image(os.path.join(OUT, p["bg"]))
    if size != (tw, th):
        # 底图像素与 tw/th 不一致：只提示，取色仍按 tw/th 比例裁到边缘内
        print("  （提示：%s 实际 %s，与 tw/th %s 不一致）" % (p["bg"], size, (tw, th)))
    fx = lambda x: (x - l) / (r - l) * tw
    fy = lambda z: (t - z) / (t - b) * th
    pts = [(fx(rw[1]), fy(rw[2])) for rw in p["rows"]]
    n = len(pts)
    outside = sum(1 for x, y in pts if not (0 <= x < tw and 0 <= y < th))
    mx, my = tw * 0.03, th * 0.03
    edge = sum(1 for x, y in pts if x < mx or x > tw - mx or y < my or y > th - my)

    lum = []
    for y in range(0, th, 2):
        for x in range(0, tw, 2):
            rr, gg, bb = px(x, y)
            lum.append((rr + gg + bb) / 3.0)
    lum.sort()
    thr = lum[int(len(lum) * 0.90)]
    bright = 0
    for x, y in pts:
        xi, yi = int(x), int(y)
        if 0 <= xi < tw and 0 <= yi < th:
            rr, gg, bb = px(xi, yi)
            if (rr + gg + bb) / 3.0 > thr:
                bright += 1
    return n, outside, edge * 100.0 / n, bright * 100.0 / n


def main():
    want = {int(a) for a in sys.argv[1:] if a.isdigit()}
    D = json.load(open(DATA, encoding="utf-8"))
    print("%-4s %-14s %6s %6s %9s %9s  %s" % ("图", "名称", "点数", "图外", "边带3%", "最亮10%", "判读"))
    for p in D["places"]:
        lv = p["level"]
        if want and lv not in want:
            continue
        if not p["rows"] or not p["bg"]:
            print("%-4d %-14s %6d %6s %9s %9s  无底图或无点位，跳过" % (lv, p["name"], len(p.get("rows") or []), "-", "-", "-"))
            continue
        n, o, e, br = check(p)
        tips = []
        if o:
            tips.append("有 %d 点出界→检查 prm" % o)
        if e > 2:
            tips.append("留白偏大")
        if br > 15:
            tips.append("疑似偏移")
        print("%-4d %-14s %6d %6d %8.1f%% %8.1f%%  %s" % (lv, p["name"], n, o, e, br, " ".join(tips) or "ok"))


if __name__ == "__main__":
    main()
