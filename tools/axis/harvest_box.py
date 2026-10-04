# -*- coding: utf-8 -*-
"""指定卡框采集：当某段剪辑是**缩放/位移过的**（黑边探测救不回来）时，
由人先用刻度尺图读出卡框，再用本脚本按这个框密采。

背景（用户 2026-10-03 的 `皮肤.mp4` 绯英段）：
  该段真正的行动卡在整帧 (205,325)-(404,425)（标准 199x100 尺寸、**纯位移**），
  而固定卡框 (82,78)-(281,178) 只截到一片粉色 ⇒ 标记判错、一张都采不到。
  用本脚本按实测框采：t=30.4~35.2 拿到 11 张干净卡。

用法：
    python tools/axis/harvest_box.py --video records/皮肤.mp4 --team 绯英 \
        --box 205,325,404,425 --t0 30.0 --t1 36.0 --step 0.2
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from harvest_characters import find_ffmpeg, imread_u, imwrite_u, CardHarvester   # noqa: E402


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--team", required=True)
    ap.add_argument("--box", required=True, help="x0,y0,x1,y1（整帧坐标，人眼读出）")
    ap.add_argument("--t0", type=float, default=0.0)
    ap.add_argument("--t1", type=float, default=None)
    ap.add_argument("--step", type=float, default=0.2)
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args(argv)

    x0, y0, x1, y1 = [int(v) for v in args.box.split(",")]
    outdir = args.outdir or os.path.join(ROOT, "frames", "harvest_%s" % args.team)
    cd = os.path.join(outdir, "cards")
    os.makedirs(cd, exist_ok=True)
    for f in os.listdir(cd):
        try:
            os.remove(os.path.join(cd, f))
        except OSError:
            pass

    ff = find_ffmpeg()
    hv = CardHarvester(args.video, ff, verbose=False)
    tmp = os.path.join(ROOT, "frames", "_box.png")
    t = args.t0
    kept, marks, skipped = [], {}, 0
    while args.t1 is None or t <= args.t1:
        import subprocess
        subprocess.run([ff, "-ss", "%.2f" % t, "-i", args.video, "-frames:v", "1", "-y", tmp],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        img = imread_u(tmp)
        if img is None:
            t += args.step
            continue
        card = img[y0:y1, x0:x1]
        if card.size == 0:
            skipped += 1
            t += args.step
            continue
        ok, col, grad = hv._card_ok(card)
        if ok:
            fn = "t%08.2f.png" % t
            imwrite_u(os.path.join(cd, fn), card)
            kept.append(round(t, 2))
        else:
            skipped += 1
        t += args.step
    try:
        os.remove(tmp)
    except OSError:
        pass
    with open(os.path.join(outdir, "buckets.json"), "w", encoding="utf-8") as f:
        json.dump(dict(video=args.video, mode="指定卡框采集", box=[x0, y0, x1, y1],
                       t0=args.t0, t1=args.t1, step=args.step,
                       scanned=int((args.t1 - args.t0) / args.step) + 1 if args.t1 else None,
                       kept=len(kept), skipped=skipped), f, ensure_ascii=False, indent=1)
    print("指定卡框 %s  采到 %d 张：%s" % ((x0, y0, x1, y1), len(kept), kept))
    print("已写出 %s" % cd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
