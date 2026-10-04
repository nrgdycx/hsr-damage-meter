# -*- coding: utf-8 -*-
"""
[C 线] 密帧抽取：HUD 数值窗口只有 ~0.5s，1 fps 抽帧会把「一次攻击的读数」和
「下一次攻击的读数」混在同一秒里。要定事件边界，必须有 0.2s 级别的帧。

只抽**有信息的窗口**（默认是实测出过读数/行动者确认的那几段），避免整片重抽
（1 fps 抽 240 帧已经 ~3 分钟，30 fps 整片要几小时）。

产物进 frames/glyphcache（与 1 fps 帧同目录同名规则 f%08.2f.png），
已存在的帧不重抽 → 可以分批补。

用法：
  python densify_C.py --step 0.2 --windows 98,112 130,142
  python densify_C.py --step 0.2 --auto        # 用实测的默认窗口表
"""
# [P3 整理] 原路径：densify_C.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from ffmpeg_path import require_ffmpeg as _req_ff
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import os
import subprocess
import sys

FF = _req_ff()   # 见 ffmpeg_path.py（可用 HSR_FFMPEG 指定）
VIDEO = "records/屏幕录制 2026-09-29 174931.mp4"
CACHE = "frames/glyphcache"

# 实测出来的"有信息"窗口（见 docs/归属与事件切分.md §2 与 out/frames_C.csv）：
#   * 每次读数出现/跳变的前后都是事件边界候选
#   * 覆盖：死龙自爆链、长夜、小伊卡、遐蝶、德谬歌、读数重置点
AUTO_WINDOWS = [
    (98, 113),      # 121418 -> 202126 -> 重置 -> 304505 -> 662096 -> 重置（口径定案的关键段）
    (130, 142),     # 47794 / 191176 与 76 的错位（t=135.6 疑似被裁掉前导位）
    (146, 166),     # 死龙 324751 停留 + 长夜 866730 异常值
    (170, 184),     # 阿哈时刻段 + 昔涟 27670
    (190, 200),     # 死龙 319195 -> 674271
    (216, 230),     # 小伊卡 157333 / 昔涟 32209 / 长夜 155897 / 遐蝶 49065
    (238, 254),     # 255900 / 290318 / 60542 / 336448
    (255, 280),     # 死龙长链 35301 -> 904004 -> 1349238
    (283, 313),     # 阿哈 + 小伊卡 272343 + 风堇 120754 + 德谬歌 407772 + 长夜 379852
    (314, 326),     # 死龙 50321 -> 272488 -> 936482 -> 1125684 -> 重置
]


def grab(t, out_path):
    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        return True
    cmd = [FF, "-ss", "%.2f" % t, "-i", VIDEO, "-frames:v", "1", "-y", out_path]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0 and os.path.exists(out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default=VIDEO)
    ap.add_argument("--outdir", default=CACHE)
    ap.add_argument("--step", type=float, default=0.2)
    ap.add_argument("--windows", default="", help="如 98,112 130,142")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--start", type=float, default=None)
    ap.add_argument("--end", type=float, default=None)
    args = ap.parse_args()

    if args.windows:
        wins = []
        for w in args.windows.split():
            a, b = w.split(",")
            wins.append((float(a), float(b)))
    elif args.start is not None and args.end is not None:
        wins = [(args.start, args.end)]
    else:
        wins = AUTO_WINDOWS

    os.makedirs(args.outdir, exist_ok=True)
    times = []
    for a, b in wins:
        n = int(round((b - a) / args.step)) + 1
        for i in range(n):
            t = round(a + i * args.step, 4)
            if t <= b + 1e-9:
                times.append(t)
    times = sorted(set(times))
    print("窗口 %d 段，共 %d 个时刻（step=%.2fs）→ %s" % (len(wins), len(times), args.step, args.outdir))
    ok = skip = fail = 0
    for i, t in enumerate(times):
        p = os.path.join(args.outdir, "f%08.2f.png" % t)
        if os.path.exists(p) and os.path.getsize(p) > 0:
            skip += 1
            continue
        if grab(t, p):
            ok += 1
        else:
            fail += 1
            print("  抽帧失败 t=%.2f" % t)
        if (i + 1) % 100 == 0 or i + 1 == len(times):
            print("  %d/%d（新抽 %d，已存在 %d，失败 %d）" % (i + 1, len(times), ok, skip, fail), flush=True)
    print("完成：新抽 %d，已存在 %d，失败 %d" % (ok, skip, fail))
    return 0


if __name__ == "__main__":
    sys.exit(main())
