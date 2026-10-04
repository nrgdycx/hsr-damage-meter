# -*- coding: utf-8 -*-
"""
判断实机读数是「框不对」还是「用错字体模型」。

背景（用户提问）：MVP 加载的是**常规字体**模型 `digit_cnn.onnx`，
而项目里有第二个模型 `digit_cnn_yinlang999.onnx`（像素方块字体专用）。
所以要分清：
  A. 框不对 → 切出的字形本身就残缺/错位
  B. 字体模型不对 → 字形是对的，但模型不认识这种字体

做法：
  1. 抓一帧（带倒计时），用**当前框**切字形；
  2. 对**同一批字形**分别用两个模型分类；
  3. 同时用 `hud_profiles` 的几何守门判断"字形尺寸是否符合某档字体"；
  4. 把字形图 + 两模型判定一起出图，供用户对照屏幕。
"""
# [P3 整理] 原路径：mvp/two_models_M.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def font(sz):
    for p in ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/arialbd.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            continue
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=14.0)
    ap.add_argument("--out", default="samples")
    args = ap.parse_args()

    from capture import Grabber, enable_dpi_awareness
    from hud_digits import HudOnnxReader, extract_glyphs
    from mvp.reader import hud_region_for
    import hud_profiles as HP
    import geometry as SA

    enable_dpi_awareness()
    g = Grabber()
    REF = tuple(int(v) for v in SA.hud_geometry(shape=(1800, 2880))["bar_rows"])

    # 两个模型
    r_default = HudOnnxReader(path="out/digit_cnn.onnx", check_fresh=False)
    r_pixel = HudOnnxReader(path="out/digit_cnn_yinlang999.onnx", check_fresh=False)

    # 各档字体的几何守门范围
    print("=== hud_profiles 登记的字体档 ===")
    for name in HP.PROFILES:
        try:
            info = HP.PROFILES[name]
            print("  %-12s %s" % (name, info.get("label", "")))
        except Exception:
            print("  %-12s ?" % name)

    for i in range(int(args.delay), 0, -1):
        print("  %d 秒后抓屏…" % i, flush=True)
        time.sleep(1)

    full = g.grab_full() if hasattr(g, "grab_full") else None
    if full is None:
        import mss
        with mss.mss() as sct:
            full = np.asarray(sct.grab(sct.monitors[1]))[:, :, :3][:, :, ::-1]
    rgb = np.asarray(full)
    H, W = rgb.shape[:2]
    reg, bar, geom = hud_region_for((H, W))
    t, l = int(reg["top"]), int(reg["left"])
    crop = rgb[t:t + int(reg["height"]), l:l + int(reg["width"])]

    glyphs = extract_glyphs(crop, top=t, left=l, bar_rows=bar)
    print("\n框:", reg, " bar=", bar, " 切出 %d 段" % len(glyphs))

    def read_with(reader):
        res = reader.classify(glyphs)
        s = "".join(str(d) if c >= reader.conf_min else "?" for d, c in res)
        return s, res

    sA, resA = read_with(r_default)
    sB, resB = read_with(r_pixel)
    print("  常规字体模型 → %r" % sA)
    print("  像素字体模型 → %r" % sB)

    # 几何守门：每段字形的 高/宽/宽高比 是否落在各档范围内
    print("\n各段字形几何（vs 各档守门范围）:")
    hdr = "  #  宽x高    比例  "
    for name in HP.PROFILES:
        hdr += "%-14s" % name
    print(hdr)
    for i, item in enumerate(glyphs, 1):
        gt, gw, gh = item[0], item[1], item[2]
        ratio = gw / max(1, gh)
        row = "  %-3d %3dx%-3d  %.2f  " % (i, gw, gh, ratio)
        for name in HP.PROFILES:
            try:
                ok = HP.geom_ok(name, gw, gh)
            except Exception:
                ok = None
            row += "%-14s" % ("OK" if ok else ("no" if ok is False else "?"))
        print(row)

    # 出图：框内原图 + 每段字形 + 两模型判定
    c1 = Image.fromarray(crop).resize((crop.shape[1] * 2, crop.shape[0] * 2), Image.LANCZOS)
    tiles = []
    for i, item in enumerate(glyphs, 1):
        arr = np.squeeze(np.asarray(item[0], dtype=np.float32))
        if arr.size == 0:
            continue
        if arr.max() > 1.5:
            arr = arr / 255.0
        arr = np.clip(arr, 0, 1)
        im = Image.fromarray((arr * 255).astype(np.uint8)).resize(
            (arr.shape[1] * 5, arr.shape[0] * 5), Image.NEAREST)
        tiles.append((i, im))
    pad = 150
    Wm = max(c1.size[0], sum(x[1].size[0] + 16 for x in tiles) + 12)
    Hm = c1.size[1] + (max((x[1].size[1] for x in tiles), default=0)) + pad + 40
    sheet = Image.new("RGB", (Wm + 16, Hm), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    d.text((6, 4), "① 框内原图（放大2x）  %s" % reg, font=font(19), fill=(255, 255, 0))
    sheet.paste(c1, (6, 30))
    y = 30 + c1.size[1] + 10
    d.text((6, y), "② 切出的字形（放大5x）", font=font(19), fill=(0, 255, 200))
    x = 6
    for i, im in tiles:
        sheet.paste(im, (x, y + 26))
        ra = resA[i - 1] if i - 1 < len(resA) else (None, 0.0)
        rb = resB[i - 1] if i - 1 < len(resB) else (None, 0.0)
        d.text((x, y + 26 + im.size[1] + 2), "#%d" % i, font=font(15), fill=(200, 200, 200))
        d.text((x, y + 26 + im.size[1] + 18), "常规:%s%.2f" % ra, font=font(14), fill=(255, 120, 120))
        d.text((x, y + 26 + im.size[1] + 34), "像素:%s%.2f" % rb, font=font(14), fill=(120, 200, 255))
        x += im.size[0] + 16
    d.text((6, Hm - 56), "常规字体模型读数 = %r" % sA, font=font(20), fill=(255, 120, 120))
    d.text((6, Hm - 32), "像素字体模型读数 = %r" % sB, font=font(20), fill=(120, 200, 255))
    out = os.path.join(args.out, "M_two_models.png")
    sheet.save(out)
    print("\n已写出 %s %s" % (out, sheet.size))
    print("请对照屏幕上的数字，判断：哪个模型对 / 还是两个都不对（那就是框或字形提取的问题）")


if __name__ == "__main__":
    main()
