# -*- coding: utf-8 -*-
"""【线2】从录屏2 抽帧并**只保留需要的两块区域**（整帧 7MB → 两块合计 ~200KB）。

为什么要裁：E 线当初整帧抽 419 张 = 1.93 GB，随后被删；本脚本一次 ffmpeg 调用同时裁出
  * top —— 行动轴顶端槽（含左标记），给单位识别用
  * hud —— 右上角总伤害数字区（按 12 位口径放宽，见 docs/HUD数字读取.md §7）
两块区域都是**固定像素坐标**（录屏2 = 2870×1800，与参考 2876×1798 只差 0.2%，坐标通用）。

用法：
  python axis_extract_team2.py --times 13,14,18,20,26            # 指定时刻
  python axis_extract_team2.py --step 1 --start 0 --end 380       # 1 fps 全片
  python axis_extract_team2.py --times 26 --full                  # 额外存整帧（人工看图用）

⚠️ 本机 ffmpeg 是 Remotion 精简版：crop/fps 滤镜不可用，只能 `-ss` 定位 + 输出整帧，
   所以"裁"这一步用 cv2 做。
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from ffmpeg_path import require_ffmpeg as _req_ff
import argparse
import os
import subprocess

import cv2

HERE = os.path.dirname(os.path.abspath(__file__))

FF = _req_ff()   # 见 ffmpeg_path.py（可用 HSR_FFMPEG 指定）
VIDEO2 = os.path.join(HERE, "records/屏幕录制 2026-09-30 192031.mp4")
OUTDIR_DEFAULT = os.path.join(HERE, "frames/axis2_L2")

# (x0, y0, x1, y1) —— 录屏2 的固定像素坐标
REGIONS = {
    # 顶端槽 (66,66)-(300,195) + 左标记中心 (86,127)，四周留 26px 余量便于看图
    "top": (40, 50, 322, 217),
    # HUD 总伤害：右对齐，左界放宽到 2100（12 位口径），上下放宽容纳字高 max 126
    "hud": (2100, 226, 2876, 374),
}


def grab_full(video, t, out_path):
    """ffmpeg 抽一整帧（已存在则跳过）。"""
    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        return True
    cmd = [FF, "-ss", "%.2f" % t, "-i", video, "-frames:v", "1", "-y", out_path]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0


def stem(t):
    return "t%08.2f" % float(t)


def extract(video, t, outdir, regions=("top", "hud"), full=False):
    """抽 t 时刻的帧并裁出 regions。返回 True/False。"""
    os.makedirs(outdir, exist_ok=True)
    paths = {r: os.path.join(outdir, "%s_%s.png" % (stem(t), r)) for r in regions}
    need = [r for r, p in paths.items() if not os.path.exists(p)]
    if full:
        fp = os.path.join(outdir, "%s_full.png" % stem(t))
        if not os.path.exists(fp):
            need.append("_full")
    if not need:
        return True
    tmp = os.path.join(outdir, "_tmp_frame.png")
    if not grab_full(video, t, tmp):
        return False
    img = cv2.imread(tmp, cv2.IMREAD_COLOR)
    if img is None:
        return False
    for r in need:
        if r == "_full":
            cv2.imwrite(os.path.join(outdir, "%s_full.png" % stem(t)), img)
            continue
        x0, y0, x1, y1 = REGIONS[r]
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(img.shape[1], x1), min(img.shape[0], y1)
        if x1 - x0 < 4 or y1 - y0 < 4:
            raise SystemExit("裁剪区域 %s 落在帧外：帧尺寸 %s" % (r, img.shape[:2]))
        cv2.imwrite(paths[r], img[y0:y1, x0:x1])
    try:
        os.remove(tmp)
    except OSError:
        pass
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", default=VIDEO2)
    ap.add_argument("--outdir", default=OUTDIR_DEFAULT)
    ap.add_argument("--times", default="")
    ap.add_argument("--step", type=float, default=1.0)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=380.0)
    ap.add_argument("--full", action="store_true", help="额外保存整帧（人工看图/量几何用）")
    args = ap.parse_args()
    if args.times:
        times = [float(x) for x in args.times.split(",") if x.strip()]
    else:
        n = int(round((args.end - args.start) / args.step)) + 1
        times = [args.start + i * args.step for i in range(n)]
    ok, fail = 0, []
    for t in times:
        if extract(args.video, t, args.outdir, full=args.full):
            ok += 1
        else:
            fail.append(t)
    print("完成：%d/%d -> %s" % (ok, len(times), args.outdir))
    if fail:
        print("  失败时刻：%s" % fail[:20])


if __name__ == "__main__":
    main()
