# -*- coding: utf-8 -*-
"""
E 线：给用户看的确认图（忆灵身份 + 两帧存疑的顶端卡）。
只写文字标签，不用颜色编码；尺寸控制在屏幕内。
"""
# [P3 整理] 原路径：axis_ask_E.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import os

import cv2
from PIL import Image, ImageDraw, ImageFont

FRAME = "frames/glyphcache/f%08.2f.png"
OUT = "samples/E_ask_user.png"


def font(sz):
    for f in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(f, sz)
        except Exception:
            continue
    return ImageFont.load_default()


def panel(t, rect, scale, label, sub="", size=None):
    img = Image.open(FRAME % t).convert("RGB").crop(rect)
    if size:
        img = img.resize(size, Image.LANCZOS)
    else:
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    cv = Image.new("RGB", (img.width, img.height + 48), (0, 0, 0))
    cv.paste(img, (0, 48))
    d = ImageDraw.Draw(cv)
    d.text((4, 3), label, font=font(19), fill=(255, 255, 255))
    if sub:
        d.text((4, 25), sub, font=font(18), fill=(210, 210, 210))
    return cv


def row(panels, gap=8):
    w = sum(p.width for p in panels) + gap * (len(panels) + 1)
    h = max(p.height for p in panels) + 2 * gap
    sheet = Image.new("RGB", (w, h), (25, 25, 25))
    x = gap
    for p in panels:
        sheet.paste(p, (x, gap))
        x += p.width + gap
    return sheet


def main():
    top = (66, 66, 300, 195)
    r1 = row([
        panel(150, top, 1.5, "A  t=150.0 顶端", "龙头，带青色圆点标记"),
        panel(160, top, 1.5, "B  t=160.0 顶端", "红色水母，带青色圆点标记"),
        panel(167, top, 1.5, "C  t=167.0 顶端", "白粉色小兽+金冠，带青色四角星"),
        panel(307, top, 1.5, "D  t=307.0 顶端", "粉发背影+大蝴蝶结，带青色四角星"),
    ])
    r2 = row([
        panel(226, top, 1.5, "E  t=226.0 顶端", "对照：用户标注的 遐蝶"),
        panel(164, top, 1.5, "F  t=164.0 顶端", "对照：队列中的 风堇（t=226 槽6）"),
        panel(220, top, 1.5, "G  t=220.0 顶端", "对照：队列中的 昔涟（t=226 槽8）"),
        panel(159, top, 1.5, "H  t=159.0 顶端", "对照：队列中的 长夜月（t=226 槽9）"),
    ])
    ax = (55, 50, 320, 1120)
    r3 = row([
        panel(152, ax, 0, "存疑1  t=152.0", "顶端 = 龙头",
              size=(205, 828)),
        panel(311, ax, 0, "存疑2  t=311.0", "顶端 = 红水母",
              size=(205, 828)),
    ])
    W = max(r1.width, r2.width, r3.width)
    H = r1.height + r2.height + r3.height + 8
    sheet = Image.new("RGB", (W, H), (25, 25, 25))
    y = 0
    for r in (r1, r2, r3):
        sheet.paste(r, (0, y))
        y += r.height
    sheet.save(OUT)
    print("已写出 %s %s  ABS %s" % (OUT, sheet.size, os.path.abspath(OUT)))


if __name__ == "__main__":
    main()
