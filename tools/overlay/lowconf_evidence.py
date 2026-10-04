# -*- coding: utf-8 -*-
"""
实机低置信取证 —— 循环抓屏，直到读出"有字形但全是 ?"的帧，把字形出图。

用于回答：**为什么每一位都低于置信阈值？**
  · 字形被切碎/错位？（提取问题）
  · 字形完整但模型没见过这种渲染？（模型/字体档问题）
"""
# [P3 整理] 原路径：mvp/lowconf_evidence_M.py（已移入 tools/，功能见 tools/README.md）
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
    ap.add_argument("--delay", type=float, default=15.0)
    ap.add_argument("--tries", type=int, default=120)
    ap.add_argument("--out", default="samples")
    args = ap.parse_args()

    from capture import Grabber, enable_dpi_awareness
    import hud_profiles as HP
    from hud_digits import HudOnnxReader

    enable_dpi_awareness()
    g = Grabber()
    prof = HP.PROFILES["default"]
    reader = HudOnnxReader(path=prof["onnx"], check_fresh=False)

    for i in range(int(args.delay), 0, -1):
        print("  %d 秒后抓屏…（切回游戏并保持有总伤害数字）" % i, flush=True)
        time.sleep(1)

    for k in range(args.tries):
        full = g.grab_screen()
        if full is None:
            time.sleep(0.3)
            continue
        rgb = np.asarray(full)
        try:
            box, bar = HP.box_for("default", rgb)
        except Exception:
            time.sleep(0.3)
            continue
        y0, x0, y1, x1 = box
        region = rgb[y0:y1, x0:x1]
        try:
            gs = HP.glyphs_cropped("default", region, y0, x0, bar_rows=bar)
        except Exception:
            gs = []
        if len(gs) < 4:
            time.sleep(0.25)
            continue
        res = reader.classify(gs)
        s = "".join(str(d) if c >= reader.conf_min else "?" for d, c in res)
        nbad = sum(1 for d, c in res if c < reader.conf_min)
        if nbad < len(res):
            print("抓到可读帧（没用到，继续找全 ? 的）t=%d" % k)
        # 采用第一个"有字形"的帧
        print("\n框=(%d,%d,%d,%d) bar_rows=%s  切出 %d 段  读出 %r  低置信位 %d"
              % (y0, x0, y1, x1, bar, len(gs), s, nbad))
        for i2, (d, c) in enumerate(res, 1):
            print("   #%d  判定=%s  置信=%.3f  宽x高=%dx%d"
                  % (i2, d, c, int(gs[i2 - 1][1]), int(gs[i2 - 1][2])))

        # 出图
        c1 = Image.fromarray(region)
        c1 = c1.resize((c1.size[0] * 2, c1.size[1] * 2), Image.LANCZOS)
        tiles = []
        for i2, item in enumerate(gs, 1):
            arr = np.squeeze(np.asarray(item[0], dtype=np.float32))
            if arr.size == 0:
                continue
            if arr.max() > 1.5:
                arr = arr / 255.0
            arr = np.clip(arr, 0, 1)
            tiles.append(Image.fromarray((arr * 255).astype(np.uint8)).resize(
                (arr.shape[1] * 5, arr.shape[0] * 5), Image.NEAREST))
        pad = 130
        Wm = max(c1.size[0], sum(t.size[0] + 16 for t in tiles) + 12)
        Hm = c1.size[1] + max((t.size[1] for t in tiles), default=0) + pad + 40
        sheet = Image.new("RGB", (Wm + 16, Hm), (18, 18, 18))
        d = ImageDraw.Draw(sheet)
        d.text((6, 4), "① 框内原图（2x）  框=(%d,%d,%d,%d)" % (y0, x0, y1, x1),
               font=font(19), fill=(255, 255, 0))
        sheet.paste(c1, (6, 30))
        y = 30 + c1.size[1] + 10
        d.text((6, y), "② 切出的字形（5x）  判定/置信", font=font(19), fill=(0, 255, 200))
        x = 6
        for i2, t in enumerate(tiles, 1):
            sheet.paste(t, (x, y + 26))
            dd, cc = res[i2 - 1] if i2 - 1 < len(res) else (None, 0.0)
            d.text((x, y + 26 + t.size[1] + 2), "#%d" % i2, font=font(15), fill=(200, 200, 200))
            d.text((x, y + 26 + t.size[1] + 18), "%s %.2f" % (dd, cc), font=font(15),
                   fill=(255, 200, 80))
            x += t.size[0] + 16
        d.text((6, Hm - 28), "读数 = %r   低置信 %d/%d   （请对照屏幕）" % (s, nbad, len(res)),
               font=font(20), fill=(255, 255, 0))
        out = os.path.join(args.out, "M_live_lowconf.png")
        sheet.save(out)
        print("已写出 %s %s" % (out, sheet.size))
        return

    print("没抓到有字形的帧")


if __name__ == "__main__":
    main()
