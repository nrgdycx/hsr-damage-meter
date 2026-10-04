# -*- coding: utf-8 -*-
"""拼贴视频专用采集：**按块探黑边 + 高帧率一次解码**。

为什么需要（用户 2026-10-03 指出）：
  * `皮肤.mp4` 是"一段遐蝶 / 一段绯英 / 一段风堇"的**拼贴**，每段黑边不同
    ⇒ 整段只探一次黑边的快通道会错位（实测只采到 9 张）；
  * 而逐帧 seek 通道虽然对，但 0.5 秒一帧的**间隔太长**：快剪里卡面只出现很短时间，
    好时刻被跳过（遐蝶段只留下 2 张）⇒ 必须**密采**（本脚本默认 10 fps）。

做法：把视频切成 chunk 秒的块，每块单独探黑边，再用快通道一次解码该块的高帧率帧，
最后把各块结果合并成一份 cards 目录（时间 = 块起点 + 帧序/fps）。

用法：
    python tools/axis/harvest_montage.py --video "records/皮肤.mp4" --team 皮肤10fps \
        --fps 10 --chunk 6
"""
import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from harvest_characters import CardHarvester, find_ffmpeg, imwrite_u   # noqa: E402


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(description="拼贴视频：分块探黑边 + 密采")
    ap.add_argument("--video", required=True)
    ap.add_argument("--team", required=True)
    ap.add_argument("--fps", type=float, default=10.0, help="采样帧率（密采）")
    ap.add_argument("--chunk", type=float, default=6.0, help="每块秒数（块内黑边相同）")
    ap.add_argument("--outdir", default=None)
    args = ap.parse_args(argv)

    outdir = args.outdir or os.path.join(ROOT, "frames", "harvest_%s" % args.team)
    ff = find_ffmpeg()
    h = CardHarvester(args.video, ff, verbose=False)
    dur = h.dur or 0.0
    print("录屏 %s  %dx%d  时长 %.0fs  →  分块 %.0fs，每块 %.0f fps"
          % (os.path.basename(args.video), h.fw, h.fh, dur, args.chunk, args.fps))

    cards, marks, scanned, skipped, bars = [], {}, 0, 0, []
    t0 = 0.0
    while t0 < dur:
        t1 = min(dur, t0 + args.chunk)
        bar = h.probe_bar_range(t0, t1)
        bars.append((round(t0, 1), bar))
        got, st = h.run_fast(outdir, fps=args.fps, t0=t0, t1=t1, save_cards=False, bar=bar)
        cards += got
        scanned += st["scanned"]
        skipped += st["skipped"]
        for k, v in st["markers"].items():
            marks[k] = marks.get(k, 0) + v
        print("  块 %.0f~%.0fs  黑边上%d/左%d  扫 %d 帧 → 采 %d 张（累计 %d）"
              % (t0, t1, bar[1], bar[0], st["scanned"], len(got), len(cards)))
        t0 = t1

    cd = os.path.join(outdir, "cards")
    os.makedirs(cd, exist_ok=True)
    for f in os.listdir(cd):
        try:
            os.remove(os.path.join(cd, f))
        except OSError:
            pass
    for c in cards:
        imwrite_u(os.path.join(cd, "t%08.2f.png" % c["t"]), c["card"])
    with open(os.path.join(outdir, "buckets.json"), "w", encoding="utf-8") as f:
        json.dump(dict(video=args.video, mode="montage-密采", fps=args.fps,
                       chunk=args.chunk, bars=bars, scanned=scanned,
                       kept=len(cards), skipped=skipped, markers=marks), f,
                  ensure_ascii=False, indent=1)
    print("\n合计：扫 %d 帧 / 采到卡面 %d 张 / 跳过 %d" % (scanned, len(cards), skipped))
    print("标记分布：%s" % {k: v for k, v in sorted(marks.items(), key=lambda kv: -kv[1])})
    print("各块黑边：%s" % bars)
    print("已写出 %s" % cd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
