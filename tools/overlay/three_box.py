# -*- coding: utf-8 -*-
"""
出干净的对照图：把「模型框 / 墨迹框 / 实测墨迹」三者画在同一张抓屏上，
并把两个框的裁剪并排放在下方，供用户一眼判断谁对。

⚠️ 约定（本会话踩过的坑）：**自己画的标注放在图外留白区，不叠在游戏画面上**，
否则连自己都会把标注当成游戏内容。
"""
# [P3 整理] 原路径：mvp/three_box_M.py（已移入 tools/，功能见 tools/README.md）
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))        # 同目录：hud_box.py

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from hud_box import ink_box              # P3 之前是 mvp/hud_box_M.py，搬家后 import 断了


def font(sz):
    for p in ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/arialbd.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            continue
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=0.0)
    ap.add_argument("--tries", type=int, default=40)
    ap.add_argument("--out", default="samples/M_three_box.png")
    args = ap.parse_args()

    from capture import Grabber, enable_dpi_awareness
    from mvp.reader import hud_region_for

    enable_dpi_awareness()
    g = Grabber()

    for i in range(int(args.delay), 0, -1):
        print("  %d 秒后抓屏…" % i, flush=True)
        time.sleep(1)

    best = None
    for k in range(args.tries):
        full = g.grab_full() if hasattr(g, "grab_full") else None
        if full is None:
            import mss
            with mss.mss() as sct:
                full = np.asarray(sct.grab(sct.monitors[1]))[:, :, :3][:, :, ::-1]
        rgb = np.asarray(full)
        H, W = rgb.shape[:2]
        rA, _, _ = hud_region_for((H, W))
        rB, _, geomB = ink_box(rgb, shape=(H, W))
        # 只要"确实测到墨迹"的帧
        if geomB.get("src") == "ink-mvp" and geomB.get("ink_y"):
            best = (rgb, rA, rB, geomB)
            break
        time.sleep(0.3)

    if best is None:
        print("没抓到带墨迹的帧")
        return
    rgb, rA, rB, geomB = best
    H, W = rgb.shape[:2]
    ink_y = geomB["ink_y"]

    # 上半：整屏（**不叠任何标注**），下方留白画图例
    k = 1400.0 / W
    scene = Image.fromarray(rgb).resize((int(W * k), int(H * k)), Image.LANCZOS)
    pad = 92
    sheet = Image.new("RGB", (scene.size[0], scene.size[1] + pad), (16, 16, 16))
    sheet.paste(scene, (0, 0))
    d = ImageDraw.Draw(sheet)
    # 标注画在"留白区"，并用线段指向框（不覆盖画面内容）
    y = scene.size[1] + 6
    d.text((6, y), "A 模型框  y %d~%d  (top=%d, 高%d)" % (rA["top"], rA["top"] + rA["height"], rA["top"], rA["height"]),
           font=font(17), fill=(255, 90, 90))
    d.text((6, y + 22), "B 墨迹框  y %d~%d  (top=%d, 高%d)" % (rB["top"], rB["top"] + rB["height"], rB["top"], rB["height"]),
           font=font(17), fill=(90, 255, 90))
    d.text((6, y + 44), "实测墨迹  y %d~%d  （数字真正的上下边界）" % (ink_y[0], ink_y[1]),
           font=font(17), fill=(255, 255, 90))
    # 在画面右缘画三条短刻度线指示三个 y
    for yy, col in ((rA["top"], (255, 90, 90)), (rA["top"] + rA["height"], (255, 90, 90)),
                    (rB["top"], (90, 255, 90)), (rB["top"] + rB["height"], (90, 255, 90)),
                    (ink_y[0], (255, 255, 90)), (ink_y[1], (255, 255, 90))):
        sy = int(yy * k)
        d.line([(scene.size[0] - 40, sy), (scene.size[0] - 1, sy)], fill=col, width=3)
    sheet.save(args.out)
    print("已写出 %s %s" % (args.out, sheet.size))
    print("  A 模型框 y %d~%d" % (rA["top"], rA["top"] + rA["height"]))
    print("  B 墨迹框 y %d~%d" % (rB["top"], rB["top"] + rB["height"]))
    print("  实测墨迹 y %d~%d" % (ink_y[0], ink_y[1]))

    # 另存两张裁剪（放大），不带任何标注
    for tag, r in (("A", rA), ("B", rB)):
        t, l = int(r["top"]), int(r["left"])
        c = rgb[t:t + int(r["height"]), l:l + int(r["width"])]
        im = Image.fromarray(c)
        im = im.resize((im.size[0] * 2, im.size[1] * 2), Image.LANCZOS)
        im.save("samples/M_crop_%s.png" % tag)
        print("  裁剪图 samples/M_crop_%s.png %s" % (tag, im.size))


if __name__ == "__main__":
    main()
