# -*- coding: utf-8 -*-
"""
E 线：从任意录屏抽帧（本机 ffmpeg 是 Remotion 精简版：crop/fps 滤镜不可用，只能 -ss 定位）。
输出到 frames/glyphcache2_E/（命名与旧缓存一致，便于复用工具）。

用法：
  python axis_extract_E.py --times 10,60,120 --outdir frames/glyphcache2_E
  python axis_extract_E.py --step 1 --start 0 --end 383 --outdir frames/glyphcache2_E
"""
# [P3 整理] 原路径：axis_extract_E.py（已移入 tools/，功能见 tools/README.md）
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

FF = _req_ff()   # 见 ffmpeg_path.py（可用 HSR_FFMPEG 指定）
DEFAULT_VIDEO = "records/屏幕录制 2026-09-30 192031.mp4"


def grab(video, t, out_path):
    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        return True
    cmd = [FF, "-ss", "%.2f" % t, "-i", video, "-frames:v", "1", "-y", out_path]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0 and os.path.exists(out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default=DEFAULT_VIDEO)
    ap.add_argument("--outdir", default="frames/glyphcache2_E")
    ap.add_argument("--times", default="")
    ap.add_argument("--step", type=float, default=1.0)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=383.0)
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    if args.times:
        times = [float(x) for x in args.times.split(",") if x.strip()]
    else:
        n = int((args.end - args.start) / args.step) + 1
        times = [args.start + i * args.step for i in range(n)]
    ok = 0
    for t in times:
        p = os.path.join(args.outdir, "f%08.2f.png" % t)
        if grab(args.video, t, p):
            ok += 1
        else:
            print("  抽帧失败 t=%.2f" % t)
    print("完成：%d/%d 帧 -> %s" % (ok, len(times), args.outdir))


if __name__ == "__main__":
    main()
