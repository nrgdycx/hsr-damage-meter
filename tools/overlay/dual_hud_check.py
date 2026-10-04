# -*- coding: utf-8 -*-
"""
实机 HUD 读数对照 —— 同一画面，用**三对 (框, bar_rows)** 各读一次，连裁剪图一起落盘。

⚠️【P1 更正 2026-10-02】本脚本原来对照的是"模型框"与"墨迹框 + **固定** bar_rows"，
并写着"墨迹自适应绝不能平移 bar_rows"。那条结论在**全分辨率实机帧**上是**错的**
（它当时依据的墨迹框本身把列取错了）。实测（`tools/overlay/live_box_check.py`）：

    墨迹框 + 墨迹 bar → `73431` ✅     墨迹框 + 模型 bar → `??343` ❌
    模型框 + 模型 bar → `?????` ❌     模型框 + 墨迹 bar → `?????` ❌

⇒ **框与 bar_rows 必须同源成对**。所以这里改成三对一起读，谁也不特殊照顾：
    A 模型框 + 模型 bar   （进战前启动时的回退路径）
    B 墨迹框 + 墨迹 bar   （P1 的方案：都用画面证据）
    C 墨迹框 + 模型 bar   （旧文档主张，留作反面对照）

用图（游戏在前台、屏幕上能看到总伤害数字；**独占全屏时截图里不会有悬浮窗，但游戏画面能抓到**）：

    python tools/overlay/dual_hud_check.py --delay 10 --shots 3

倒计时里切回游戏；到点自动抓 N 张，每张出图并把三对读数与"是否可信"列在终端。
"""
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))       # 同目录：hud_box.py

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from hud_box import ink_box              # P3 之前是 mvp/hud_box_M.py，搬家后 import 断了

OUT = "samples"


def font(sz):
    for p in ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/arialbd.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            continue
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=10.0)
    ap.add_argument("--shots", type=int, default=3)
    ap.add_argument("--gap", type=float, default=2.0, help="每张之间间隔秒")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    from capture import Grabber, enable_dpi_awareness
    enable_dpi_awareness()
    g = Grabber()

    from mvp.reader import Perceiver, hud_region_for, read_is_reliable

    perc = Perceiver(backend="onnx")

    def read_with(rgb, region, bar_rows, tag):
        """走**实时同一条路径**（含几何守门）读一次：返回 (读数, 段数, 是否可信)。"""
        top, left = int(region["top"]), int(region["left"])
        crop = np.ascontiguousarray(
            rgb[top:top + int(region["height"]), left:left + int(region["width"])], dtype=np.int16)
        row = perc.read(0.0, region_rgb=crop, top=top, left=left, bar_rows=bar_rows,
                        read_axis=False)
        ok = read_is_reliable(row)
        print("  %-6s %s  bar=%-11s 切出 %d 段  读出 %-9r  nbad=%d  可信=%s"
              % (tag, region, tuple(int(v) for v in bar_rows), row["n"], row["text"],
                 row["nbad"], "是" if ok else "否"))
        return row, ok

    os.makedirs(args.out, exist_ok=True)
    for i in range(int(args.delay), 0, -1):
        print("  %d 秒后抓屏…（现在切回游戏）" % i, flush=True)
        time.sleep(1)

    for shot in range(1, int(args.shots) + 1):
        full = g.grab_full() if hasattr(g, "grab_full") else None
        if full is None:
            import mss
            with mss.mss() as sct:
                full = np.asarray(sct.grab(sct.monitors[1]))[:, :, :3][:, :, ::-1]
        rgb = np.asarray(full)
        H, W = rgb.shape[0], rgb.shape[1]

        # A. 模型框 + 模型 bar（进战前启动的回退路径）
        regA, barA, geomA = hud_region_for((H, W))
        # B. 墨迹框 + 墨迹 bar（P1 方案：都用画面证据）
        regB, barB, geomB = ink_box(rgb, shape=(H, W))
        # C. 墨迹框 + 模型 bar（旧文档主张）
        regC, barC = regB, barA

        print("\n--- 第 %d 张（%dx%d）---" % (shot, W, H))
        rA, okA = read_with(rgb, regA, barA, "A模型")
        rB, okB = read_with(rgb, regB, barB, "B墨迹")
        rC, okC = read_with(rgb, regC, barC, "C错配")
        print("     (墨迹框 src=%s shift=%s 检出墨迹 y=%s)"
              % (geomB.get("src"), geomB.get("shift"), geomB.get("ink_y")))

        # 出图：把框画在整屏缩略图上（标注放图外留白，不叠在游戏画面上）
        k = 1500.0 / W
        thumb = Image.fromarray(rgb).resize((int(W * k), int(H * k)), Image.LANCZOS)
        pad = 76
        sheet0 = Image.new("RGB", (thumb.size[0], thumb.size[1] + pad), (16, 16, 16))
        sheet0.paste(thumb, (0, 0))
        d = ImageDraw.Draw(sheet0)
        for reg, lab, col in ((regA, "A 模型框 → %r  %s" % (rA["text"], "可信" if okA else "不可信"),
                               (255, 90, 90)),
                              (regB, "B 墨迹框 → %r  %s" % (rB["text"], "可信" if okB else "不可信"),
                               (90, 255, 90))):
            l, t = int(reg["left"] * k), int(reg["top"] * k)
            d.rectangle([l, t, l + int(reg["width"] * k), t + int(reg["height"] * k)],
                        outline=col, width=3)
        d.text((6, thumb.size[1] + 6), "A 模型框 → %r（%s）   %s"
               % (rA["text"], "可信" if okA else "不可信", regA), font=font(17), fill=(255, 90, 90))
        d.text((6, thumb.size[1] + 28), "B 墨迹框 → %r（%s）   %s"
               % (rB["text"], "可信" if okB else "不可信", regB), font=font(17), fill=(90, 255, 90))
        d.text((6, thumb.size[1] + 50), "C 墨迹框+模型 bar → %r（%s）"
               % (rC["text"], "可信" if okC else "不可信"), font=font(17), fill=(255, 255, 90))
        sheet0.save(os.path.join(args.out, "M_dual_full_%d.png" % shot))

        def crop_img(reg):
            t, l = int(reg["top"]), int(reg["left"])
            c = Image.fromarray(rgb[t:t + int(reg["height"]), l:l + int(reg["width"])])
            return c.resize((c.size[0] * 2, c.size[1] * 2), Image.LANCZOS)

        cA, cB, cC = crop_img(regA), crop_img(regB), crop_img(regC)
        wmax = max(cA.size[0], cB.size[0], cC.size[0]) + 12
        sheet = Image.new("RGB", (wmax, cA.size[1] + cB.size[1] + cC.size[1] + 96), (18, 18, 18))
        dd = ImageDraw.Draw(sheet)
        y = 4
        for c, lab, col in ((cA, "A 模型框 → %r（%s）" % (rA["text"], "可信" if okA else "不可信"),
                             (255, 90, 90)),
                            (cB, "B 墨迹框 → %r（%s）" % (rB["text"], "可信" if okB else "不可信"),
                             (90, 255, 90)),
                            (cC, "C 墨迹框+模型 bar → %r（%s）" % (rC["text"], "可信" if okC else "不可信"),
                             (255, 255, 90))):
            dd.text((6, y), lab, font=font(20), fill=col)
            sheet.paste(c, (6, y + 24))
            y += 24 + c.size[1] + 6
        sheet.save(os.path.join(args.out, "M_dual_crop_%d.png" % shot))
        print("  出图: %s/M_dual_full_%d.png  %s/M_dual_crop_%d.png"
              % (args.out, shot, args.out, shot))

        if shot < int(args.shots):
            time.sleep(args.gap)

    print("\n请对照屏幕上的数字，告我 A / B / C 哪一对读对了（B 是 P1 的方案，A 是回退路径）。")


if __name__ == "__main__":
    main()
