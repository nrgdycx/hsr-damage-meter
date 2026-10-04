# -*- coding: utf-8 -*-
"""扫整段录屏的**行动轴顶端卡**，不落盘（抽一帧 → 读 → 删）。

为什么需要它：`tools/axis/extract.py` 会把帧留在磁盘上（2880×1800 的 PNG ≈ 5~8 MB/帧），
整段 6 分钟的录屏按 2s 抽就是 1 GB+。**定位"哪一段值得细看"**这件事不需要保留帧 ——
所以这里用临时文件抽一帧、读完就删。

用法：
  python -u tools/axis/scan_video.py --video "records/xxx.mp4" --step 2 --start 0 --end 373
  python -u tools/axis/scan_video.py --video "records/xxx.mp4" --step 0.2 --start 300 --end 320

输出：
  * CSV（`--out`，默认按视频名生成）列：t, unit, owner, marker, card_type, score, margin
  * 控制台打印"轴**整段不可读**"的时间段摘要（T1 要找的就是这些段）
"""

import os as _os, sys as _sys  # noqa: E401
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from ffmpeg_path import find_ffmpeg as _find_ffmpeg   # 共享解析器（见 ffmpeg_path.py）
_FF_FALLBACK_1 = _find_ffmpeg() or ""   # 兜底：本机已知位置（没有 local 配置时为 None）
from tools_bootstrap import *  # noqa: E402,F401,F403

import argparse
import csv
import os
import re
import subprocess
import sys
import tempfile
import time

import numpy as np
import cv2

import axis_actor as T

FFMPEG = (os.environ.get("FFMPEG") or
          _FF_FALLBACK_1)
# ⚠️ 用 ASCII 临时目录：`cv2.imread` 打不开含中文的路径（本项目踩过），
#    所以统一走 np.fromfile + cv2.imdecode。
TMP = os.path.join(tempfile.gettempdir(), "t1_scan")


def grab(video, t):
    """抽一帧到临时文件并读成 BGR ndarray；读完由调用方删。"""
    os.makedirs(TMP, exist_ok=True)
    p = os.path.join(TMP, "f%08.2f.png" % t)
    r = subprocess.run([FFMPEG, "-ss", "%.2f" % t, "-i", video, "-frames:v", "1", "-y", p],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if r.returncode != 0 or not os.path.exists(p):
        return None, None
    img = cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)
    try:
        os.remove(p)
    except OSError:
        pass
    return img, p


def default_out(video):
    base = re.sub(r"[^\w\-]+", "_", os.path.splitext(os.path.basename(video))[0]).strip("_")
    return "out/scan_%s.csv" % base


# 与 `out/frames_dense4.csv` 同列，可直接喂 `events_v4.load/build`
FRAME_COLS = ["t", "hud_text", "hud_n", "hud_len", "hud_lm", "hud_minconf", "hud_nbad",
              "hud_profile", "unit", "owner", "score", "margin", "marker", "inserted",
              "card_type"]


def hud_read(model, img_bgr):
    """读 HUD。走 `read_hud.read_array` 这个**公开入口**（不复制识别逻辑）。

    ⚠️ 演出帧上 HUD 整块不在场，线7 反推的框会落到画面外（实测 `box=(-20,1811,…)`），
    `hud_profiles.glyphs` 会抛 RuntimeError —— 那种帧记成"本帧无读数"。
    与 `tools/events/scan_chain.py` 里那道兜底是同一个理由、同一处理。
    """
    import read_hud
    a = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB).astype(np.int16)
    try:
        text, minconf, detail = read_hud.read_array(model, a, profile="default")
    except RuntimeError:
        return "", 0, 0.0, 0
    nbad = sum(1 for r in detail if r["digit"] is None or r["conf"] < 0.55)
    return text, len(detail), float(minconf), nbad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=0.0, help="0 = 一直扫到抽帧失败为止")
    ap.add_argument("--step", type=float, default=2.0)
    ap.add_argument("--out", default="")
    ap.add_argument("--frames-out", default="",
                    help="额外写一张**事件引擎可吃**的帧表（同 out/frames_dense4.csv 的列）")
    ap.add_argument("--hud", action="store_true", help="同时读 HUD（--frames-out 会自动开）")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    out = args.out or default_out(args.video)
    want_hud = args.hud or bool(args.frames_out)
    bank = T.load_bank()
    model = None
    if want_hud:
        import read_hud
        model = read_hud.load_model()
    rows, frows = [], []
    t = args.start
    t0 = time.time()
    fails = 0
    while True:
        if args.end and t > args.end + 1e-9:
            break
        img, _ = grab(args.video, t)
        if img is None:
            fails += 1
            if fails >= 3:          # 连续 3 帧抽不到 = 到尾了
                break
            t = round(t + args.step, 2)
            continue
        fails = 0
        r = T.read_actor(img, bank)
        rows.append({"t": t, "unit": r["unit"] or "", "owner": r["owner"] or "",
                     "marker": r["marker"] or "", "card_type": r["card_type"] or "",
                     "score": round(float(r["score"]), 3),
                     "margin": round(float(r["margin"]), 3)})
        if want_hud:
            text, ng, minconf, nbad = hud_read(model, img)
            frows.append({"t": t, "hud_text": text, "hud_n": ng, "hud_len": len(text),
                          "hud_lm": "", "hud_minconf": round(minconf, 3), "hud_nbad": nbad,
                          "hud_profile": "default", "unit": r["unit"] or "",
                          "owner": r["owner"] or "", "score": round(float(r["score"]), 3),
                          "margin": round(float(r["margin"]), 3), "marker": r["marker"] or "",
                          "inserted": "" if r["inserted"] is None else int(r["inserted"]),
                          "card_type": r["card_type"] or ""})
        if not args.quiet and len(rows) % 25 == 0:
            el = time.time() - t0
            print("  %5.1fs / %d 帧  %.0f ms/帧" % (t, len(rows), el * 1000 / len(rows)), flush=True)
        t = round(t + args.step, 2)

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["t", "unit", "owner", "marker", "card_type",
                                          "score", "margin"])
        w.writeheader()
        w.writerows(rows)
    print("\n已写出 %s（%d 帧，step=%.2fs）" % (out, len(rows), args.step))
    if frows:
        with open(args.frames_out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=FRAME_COLS)
            w.writeheader()
            w.writerows(frows)
        print("已写出 %s（%d 帧，可直接喂 events_v4）" % (args.frames_out, len(frows)))

    # ── 摘要：轴整段不可读的段 + 出现过的人 ──
    runs, cur = [], None
    for r in rows:
        if not r["unit"]:
            cur = [r["t"], r["t"]] if cur is None else [cur[0], r["t"]]
        else:
            if cur is not None:
                runs.append(cur)
                cur = None
    if cur is not None:
        runs.append(cur)
    print("\n=== 轴不可读段（≥2 个采样点）===")
    for a, b in runs:
        if b - a < args.step * 1.5:
            continue
        ia = [i for i, r in enumerate(rows) if r["t"] == a][0]
        ib = [i for i, r in enumerate(rows) if r["t"] == b][0]
        f = rows[ia - 1] if ia > 0 else None
        k = rows[ib + 1] if ib + 1 < len(rows) else None
        def s(x):
            if not x or not x["unit"]:
                return "-"
            return "%s(%s)" % (x["unit"], x["marker"])
        print("  %7.1f~%-7.1f  %5.1fs ｜ 前 %-22s ｜ 后 %-22s"
              % (a, b, b - a, s(f), s(k)))
    seen = {}
    for r in rows:
        if r["unit"]:
            seen[r["owner"] or r["unit"]] = seen.get(r["owner"] or r["unit"], 0) + 1
    print("\n=== 认出的归属（帧数）===\n  %s" % seen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
