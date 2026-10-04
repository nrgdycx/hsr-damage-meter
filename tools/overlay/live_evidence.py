# -*- coding: utf-8 -*-
"""
实机读数取证 —— 抓一帧，把「框裁出什么」+「切出的每个字形」全部放大落盘。

为什么需要：实机对照发现两种框都读不对（屏幕上 `73431`，读出 `7343`/`543438`…）。
必须看清**切出来的字形长什么样**，才能判断是"框错"还是"掩膜/字形提取错"还是"模型没见过这个渲染"。

⚠️ 标注一律画在图外留白，不叠在游戏画面上（本会话踩过的坑）。
"""
# [P3 整理] 原路径：mvp/live_evidence_M.py（已移入 tools/，功能见 tools/README.md）
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
    ap.add_argument("--out", default="samples")
    args = ap.parse_args()

    from capture import Grabber, enable_dpi_awareness
    from hud_digits import HudOnnxReader, extract_glyphs
    from mvp.reader import hud_region_for
    import geometry as SA

    enable_dpi_awareness()
    g = Grabber()
    reader = HudOnnxReader(check_fresh=False)
    REF = tuple(int(v) for v in SA.hud_geometry(shape=(1800, 2880))["bar_rows"])

    for i in range(int(args.delay), 0, -1):
        print("  %d 秒后抓屏…（切回游戏，屏幕上有总伤害数字）" % i, flush=True)
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
    h, w = int(reg["height"]), int(reg["width"])
    crop = rgb[t:t + h, l:l + w]

    glyphs = extract_glyphs(crop, top=t, left=l, bar_rows=bar)
    res = reader.classify(glyphs)
    read = "".join(str(d) if c >= reader.conf_min else "?" for d, c in res)
    print("框:", reg, " bar=", bar)
    print("切出 %d 段，读出 %r" % (len(glyphs), read))

    # 出两张图（都放图外留白）
    # ① 裁剪区原图（放大 2x）
    c1 = Image.fromarray(crop).resize((w * 2, h * 2), Image.LANCZOS)
    # ② 每个字形（照模型输入的样子：按自身峰值归一化后的灰度）放大
    tiles = []
    for i, item in enumerate(glyphs, 1):
        gt = item[0] if isinstance(item, (tuple, list)) else item
        arr = np.asarray(gt, dtype=np.float32)
        arr = np.squeeze(arr)
        if arr.size == 0:
            continue
        if arr.max() > 1.5:              # 若是 0~255 就归一化
            arr = arr / 255.0
        arr = np.clip(arr, 0, 1)
        im = Image.fromarray((arr * 255).astype(np.uint8)).resize(
            (arr.shape[1] * 5, arr.shape[0] * 5), Image.NEAREST)
        tiles.append((i, im, res[i - 1] if i - 1 < len(res) else (None, 0.0)))

    padh = 60
    Wm = max(c1.size[0], sum(t[1].size[0] for t in tiles) + 20 * max(1, len(tiles)))
    Hm = c1.size[1] + (max((t[1].size[1] for t in tiles), default=0)) + 60 + padh
    sheet = Image.new("RGB", (Wm + 16, Hm), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    d.text((6, 4), "① 框内原图（放大2x）  框=%s" % reg, font=font(19), fill=(255, 255, 0))
    sheet.paste(c1, (6, 30))
    y = 30 + c1.size[1] + 12
    d.text((6, y), "② 切出的每个字形（按峰值归一化，放大5x；红字=模型判定/置信）",
           font=font(19), fill=(0, 255, 200))
    x = 6
    for i, im, (dd, cc) in tiles:
        sheet.paste(im, (x, y + 28))
        d.text((x + 2, y + 28 + im.size[1] + 2), "#%d" % i, font=font(15), fill=(200, 200, 200))
        d.text((x + 2, y + 28 + im.size[1] + 20), "%s %.2f" % (dd, cc), font=font(15),
               fill=(255, 90, 90))
        x += im.size[0] + 16
    d.text((6, Hm - 30), "总读数 = %r   （请对照屏幕上的数字）" % read, font=font(20), fill=(255, 255, 0))
    out = os.path.join(args.out, "M_live_glyphs.png")
    sheet.save(out)
    print("已写出 %s %s" % (out, sheet.size))


if __name__ == "__main__":
    main()
