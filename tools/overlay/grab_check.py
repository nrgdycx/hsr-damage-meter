# -*- coding: utf-8 -*-
"""
抓屏验证（带倒计时）—— 给你时间切回游戏再抓。

为什么需要倒计时：在本终端一执行命令，焦点就离开游戏了，
mss 抓的是**当前前台窗口**，所以会抓到聊天界面而不是游戏。

用法：
    python mvp/grab_check_M.py --delay 8

执行后立刻用 Alt+Tab / 点任务栏切回游戏，倒计时结束后自动抓屏。
"""
# [P3 整理] 原路径：mvp/grab_check_M.py（已移入 tools/，功能见 tools/README.md）
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

OUT = "samples"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=8.0, help="倒计时秒数（切回游戏用）")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    from capture import Grabber, enable_dpi_awareness
    from mvp.reader import hud_region_for, axis_region_for

    enable_dpi_awareness()
    g = Grabber()

    for i in range(int(args.delay), 0, -1):
        print("  %d 秒后抓屏…（现在切回游戏！）" % i, flush=True)
        time.sleep(1)

    full = g.grab_full() if hasattr(g, "grab_full") else None
    if full is None:
        import mss
        with mss.mss() as sct:
            full = np.asarray(sct.grab(sct.monitors[1]))[:, :, :3][:, :, ::-1]

    H, W = np.shape(full)[0], np.shape(full)[1]
    print("抓到整屏 (H,W):", H, W)

    # 判断是不是抓到了游戏：看右上角有没有黄色墨迹
    a = np.asarray(full).astype(np.int16)
    reg = a[150:600, 2200:2880]
    r, gg, b = reg[:, :, 0], reg[:, :, 1], reg[:, :, 2]
    yellow = int(((r > 200) & (gg > 185) & ((r - b) > 25)).sum())
    purple = int(((b > r) & (b > 120) & (gg < r)).sum())
    print("右上角黄色像素 %d / 紫色像素 %d" % (yellow, purple))
    if yellow < 50 and purple < 5000:
        print("⚠️ 看起来不是游戏画面（可能还是抓到了别的窗口）")

    hud_model = hud_region_for((H, W))
    axis_model = axis_region_for((H, W))
    hud_ink = hud_region_for((H, W), use_ink=True, frame_rgb=full)
    axis_ink = axis_region_for((H, W), use_ink=True, frame_rgb=full)

    hud_region, bar_rows, hud_geom = hud_ink
    axis_region, axis_geom, screen_geom = axis_ink
    print("\nHUD 区 model:", hud_model[0], "src=", hud_model[2].get("src"))
    print("HUD 区 ink  :", hud_region, "src=", hud_geom.get("src"), "k=", hud_geom.get("k"))
    print("轴 区 model:", axis_model[0])
    print("轴 区 ink  :", axis_region)

    def crop(region):
        l, t = int(region["left"]), int(region["top"])
        w, h = int(region["width"]), int(region["height"])
        return full[max(0, t):t + h, max(0, l):l + w]

    os.makedirs(args.out, exist_ok=True)
    hud_img, axis_img = crop(hud_region), crop(axis_region)
    from PIL import Image, ImageDraw, ImageFont

    def font(sz):
        for p in ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/arialbd.ttf"):
            try:
                return ImageFont.truetype(p, sz)
            except Exception:
                continue
        return ImageFont.load_default()

    Image.fromarray(hud_img).resize(
        (hud_img.shape[1] * 2, hud_img.shape[0] * 2), Image.LANCZOS
    ).save(os.path.join(args.out, "M_grab_hud.png"))
    Image.fromarray(axis_img).save(os.path.join(args.out, "M_grab_axis.png"))

    k = min(1.0, 1400 / W)
    small = Image.fromarray(full).resize((int(W * k), int(H * k)), Image.LANCZOS)
    d = ImageDraw.Draw(small)
    for region, label, col in ((hud_region, "HUD", (255, 0, 0)),
                               (axis_region, "AXIS", (0, 255, 0))):
        l, t = int(region["left"] * k), int(region["top"] * k)
        d.rectangle([l, t, l + int(region["width"] * k), t + int(region["height"] * k)],
                    outline=col, width=3)
        d.text((l + 4, max(0, t - 18)), label, font=font(18), fill=col)
    small.save(os.path.join(args.out, "M_grab_full.png"))

    print("\n已写出 %s/M_grab_full.png（红框 HUD / 绿框 轴）" % args.out)
    print("       %s/M_grab_hud.png  %s/M_grab_axis.png" % (args.out, args.out))


if __name__ == "__main__":
    main()
