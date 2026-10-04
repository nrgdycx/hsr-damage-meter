# -*- coding: utf-8 -*-
"""
用**两个字体档**（default / yinlang999）分别读同一帧，判断实机到底在用哪种字体。

依据 `hud_profiles.py`：
  default    : box (260,2350,340,2876)  mode=glow（淡黄辉光）   模型 digit_cnn.onnx
  yinlang999 : box (250,2400,360,2870)  mode=cyan（青色）       模型 digit_cnn_yinlang999.onnx
               且登记了 actor_keys（按"当前行动者"切换）

所以"读不对"可能是：**用错了字体档**（拿 glow 去读青色像素字，或反之）。
本脚本把两个档各自的「裁剪 + 字形 + 读数」都摆出来，一次看清。
"""
# [P3 整理] 原路径：mvp/two_profiles_M.py（已移入 tools/，功能见 tools/README.md）
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
    ap.add_argument("--tries", type=int, default=25)
    args = ap.parse_args()

    from capture import Grabber, enable_dpi_awareness
    import hud_profiles as HP

    enable_dpi_awareness()
    g = Grabber()

    for i in range(int(args.delay), 0, -1):
        print("  %d 秒后抓屏…" % i, flush=True)
        time.sleep(1)

    picked = None
    for k in range(args.tries):
        full = g.grab_full() if hasattr(g, "grab_full") else None
        if full is None:
            import mss
            with mss.mss() as sct:
                full = np.asarray(sct.grab(sct.monitors[1]))[:, :, :3][:, :, ::-1]
        rgb = np.asarray(full)

        outs = {}
        for name in ("default", "yinlang999"):
            try:
                gs = HP.glyphs(name, rgb)
                path = HP.model_path(name) if hasattr(HP, "model_path") else None
                from hud_digits import HudOnnxReader
                prof = HP.PROFILES[name]
                reader = HudOnnxReader(path=prof["onnx"], check_fresh=False)
                res = reader.classify(gs)
                s = "".join(str(d) if c >= reader.conf_min else "?" for d, c in res)
                outs[name] = (s, gs, prof)
            except Exception as e:
                outs[name] = ("ERR:%s" % repr(e)[:40], [], HP.PROFILES.get(name, {}))
        # 只要有一个档切出 >=4 段就采用
        if max(len(v[1]) for v in outs.values()) >= 4:
            picked = (rgb, outs)
            break
        time.sleep(0.4)

    if picked is None:
        print("没抓到有数字的帧")
        return
    rgb, outs = picked

    print("\n=== 同一帧、两个字体档 ===")
    for name, (s, gs, prof) in outs.items():
        print("  %-12s mode=%-6s box=%s  切出 %2d 段  读出 %r"
              % (name, prof.get("mode"), prof.get("box"), len(gs), s))

    # 出图：每档一行（裁剪 + 字形）
    rows = []
    for name in ("default", "yinlang999"):
        s, gs, prof = outs[name]
        box = prof.get("box")
        y0, x0, y1, x1 = box
        crop = rgb[y0:y1, x0:x1]
        c = Image.fromarray(crop)
        tiles = []
        for i, item in enumerate(gs, 1):
            arr = np.squeeze(np.asarray(item[0], dtype=np.float32))
            if arr.size == 0:
                continue
            if arr.max() > 1.5:
                arr = arr / 255.0
            arr = np.clip(arr, 0, 1)
            tiles.append(Image.fromarray((arr * 255).astype(np.uint8)).resize(
                (arr.shape[1] * 4, arr.shape[0] * 4), Image.NEAREST))
        rows.append((name, s, c, tiles))

    Wm = 1100
    Hm = sum(r[2].size[1] + max((t.size[1] for t in r[3]), default=0) + 60 for r in rows) + 20
    sheet = Image.new("RGB", (Wm, Hm), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    y = 6
    for name, s, c, tiles in rows:
        d.text((6, y), "档=%s   读出 %r" % (name, s), font=font(20), fill=(255, 255, 0))
        y += 26
        sheet.paste(c, (6, y))
        y += c.size[1] + 6
        x = 6
        for t in tiles:
            sheet.paste(t, (x, y))
            x += t.size[0] + 10
        y += max((t.size[1] for t in tiles), default=0) + 16
    out = os.path.join(args.out, "M_two_profiles.png")
    sheet.save(out)
    print("已写出 %s %s" % (out, sheet.size))
    print("请对照屏幕：哪种档的裁剪/字形看起来对得上屏幕上的数字？")


if __name__ == "__main__":
    main()
