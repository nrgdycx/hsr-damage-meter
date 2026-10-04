# -*- coding: utf-8 -*-
"""
[C 线] 逐帧扫描（v2）：对每一帧同时读「HUD 总伤害读数（A 线）」与「行动轴顶端行动者（E 线）」，
落地成 out/frames_C.csv —— C 线事件引擎的唯一输入。

与 v1 的差别（都是跑完 v1、看过 255 帧结果之后加的）：
  1. **新增列** `hud_lm`（最左列段的绝对 x）与 `hud_len`（读出的位数）。
     来历：C 线实测发现 A 线读数会**静默丢前导位**（t=102 屏幕是 304505、读出 4505；
     t=135.6 是 191176、读出 76；t=303 是 120754、读出 20754），而且不带 '?'。
     ⚠️ 实测**不能**用"位数 + 最左段位置"判丢位：数字区的列段包含了大量碎片段
     （见 diag_chain_C.py --audit），leftmost 会落在碎片上，且不同字号的 advance 不一致
     （30px 与 46px 两档）。所以 `hud_lm` 只作**证据列**保留，判定交给事件引擎的序列规则。
  2. **行动者可以稀疏读**：行动轴是一整秒尺度变化的量，0.2s 密帧没必要每帧都跑 E 线
     （省 80% 时间）。默认每 `--actor-every 5` 帧读一次，另外在 `--actor-at` 指定的帧必读。
  3. 读数用 `--chain` 指定的列链阈值（默认 20 = A 线现状；30 能救回一部分丢位帧，
     见 diag_chain_C.py / tune_chain_C.py）。**不改 A 线模块**，只在本地替换常数。

用法：
  python scan_C2.py --dir frames/glyphcache --range 98,113 --out out/frames_dense_C.csv --actor-every 5
  python scan_C2.py --range 100,340 --out out/frames_C.csv --chain 20
"""
# [P3 整理] 原路径：scan_C2.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import csv
import glob
import os
import sys
import time
import types

import numpy as np
import torch
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hud_glyphs as HG  # noqa: E402
import read_hud  # noqa: E402
import axis_actor as T  # noqa: E402

COLS = ["t", "hud_text", "hud_n", "hud_len", "hud_lm", "hud_minconf", "hud_nbad", "hud_profile",
        "unit", "owner", "score", "margin", "marker", "inserted", "card_type"]

# 最左列段的参考 x（只作证据，不用于判定；实测碎片段会污染这个值）
HUD_LEFT_REF = 2350


def module_with_chain(chain):
    """把 hud_glyphs.py 的链式连续性阈值换掉，编译成新模块（默认 20 = 原样）。"""
    if chain == 20:
        return HG
    path = os.path.join(ROOT, "hud_glyphs.py")
    src = open(path, encoding="utf-8").read()
    old = "elif chain[-1][0] - r[1] - 1 <= 20:"
    new = "elif chain[-1][0] - r[1] - 1 <= %d:" % chain
    if old not in src:
        raise SystemExit("hud_glyphs.py 里没找到链式阈值那一行，--chain 不可用")
    mod = types.ModuleType("hud_glyphs_chain%d" % chain)
    mod.__dict__["__file__"] = path
    exec(compile(src.replace(old, new), path, "exec"), mod.__dict__)
    return mod


def glyph_leftmost(png, box=None):
    """最左列段的绝对 x（**证据列**：值偏大不等于丢位，因为数字区里有碎片段）。"""
    a = np.asarray(Image.open(png).convert("RGB")).astype(np.int16)
    y0, x0, y1, x1 = box or (HG.CY0, HG.CX0, HG.CY1, HG.CX1)
    m_seg, m_glyph, _ = HG._masks(a[y0:y1, x0:x1], "glow")
    ms = m_seg.copy()
    r0, r1 = max(0, HG.BAR_ROWS[0] - y0), min(ms.shape[0] - 1, HG.BAR_ROWS[1] - y0)
    ms[r0:r1 + 1, :] = False
    col = ms.any(axis=0)
    nz = np.where(col)[0]
    return int(nz.min() + x0) if len(nz) else -1


def scans(frame_dir, lo, hi, out, chain=20, actor_every=5, actor_at=(), calib=False, step=1.0):
    """
    step : 只扫"落在整数秒网格"上的帧（默认 1.0）。
           ⚠️ 必须显式给这个参数：`frames/glyphcache/` 里既有 1 fps 帧（f00100.00）
           也有事后补抽的 0.1/0.2s 帧（f00135.60、f00150.20…）。
           `--range 100,340` 会把它们全部扫进来（实测 913 帧），
           那样得到的表**不是** 1 fps 网格，事件切分口径就变了。
    """
    paths = []
    for p in sorted(glob.glob(os.path.join(frame_dir, "*.png"))):
        try:
            t = float(os.path.basename(p)[1:-4])
        except ValueError:
            continue
        if not (lo <= t <= hi):
            continue
        if step > 0:
            k = t / step
            if abs(k - round(k)) > 1e-6:      # 不在 step 网格上 → 跳过
                continue
        paths.append((t, p))
    if not paths:
        print("目录 %s 里没有 t∈[%s,%s] 且在 step=%s 网格上的帧" % (frame_dir, lo, hi, step))
        return 2

    mod = module_with_chain(chain)
    model = read_hud.load_model()
    bank = T.load_bank()
    rows = []
    t0 = time.time()
    for i, (t, p) in enumerate(paths):
        # ── A 线：HUD 读数 ──
        # ⚠️ 必须走 read_hud 的公开入口。曾经在这里自己写"切字形 + softmax + 0.55 阈值"，
        # 结果与 read_hud.read_array **在过渡帧上不一致**（实测 t=153.0：
        # 自己写的那套出 `8324751`，read_array 出 `?324751`；t=113.0：`810700` vs `?1070?`）。
        # 差异来自"取字形像素用的掩膜"（read_array 走 hud_profiles → glyph_mode="hybrid_s"）。
        # 教训记在这里：**不要在扫描器里复制识别逻辑**，否则两套口径会静默分叉。
        a = np.asarray(Image.open(p).convert("RGB")).astype(np.int16)
        if mod is HG:
            try:
                text, minconf, detail = read_hud.read_array(model, a, profile="default")
            except RuntimeError as e:
                # 演出/过场帧上 HUD 整块不在场，线7 从画面反推的框可能落到画面外
                # （T1 实测：大招窗口里出现过 box=(-9,2353,45,2880)）→ 记成"本帧无读数"。
                # ⚠️ 这是扫描器的健壮性兜底，**不是**识别口径：`read_hud.read_array` 本身没动。
                text, minconf, detail = "", 0.0, []
                if calib:
                    print("   t=%-8s HUD 不在场（%s）" % (("%.2f" % t), e), flush=True)
            n_glyphs = len(detail)
            nbad = sum(1 for r in detail if r["digit"] is None or r["conf"] < 0.55)
        else:                                    # --chain 变体：只能自己跑（改过链阈值）
            gs = mod.extract(a)
            n_glyphs, nbad = len(gs), 0
            if gs:
                x = torch.tensor(np.stack([v for v, _, _ in gs])[:, None], dtype=torch.float32)
                with torch.no_grad():
                    pr = torch.softmax(model(x), 1)
                cf, pd = pr.max(1)
                text = "".join(str(int(d)) if c >= 0.55 else "?"
                               for d, c in zip(pd.tolist(), cf.tolist()))
                minconf = float(min(cf.tolist()))
                nbad = sum(1 for c in cf.tolist() if c < 0.55)
            else:
                text, minconf = "", 0.0
        lm = glyph_leftmost(p) if text else -1

        # ── E 线：行动轴顶端（稀疏读；0.2s 密帧不必每帧都读）──
        do_actor = (i % max(1, actor_every) == 0) or (t in actor_at) or i == len(paths) - 1
        if do_actor:
            import cv2
            bgr = cv2.cvtColor(a.astype(np.uint8), cv2.COLOR_RGB2BGR)
            r = T.read_actor(bgr, bank)
            actor = (r["unit"] or "", r["owner"] or "", round(float(r["score"]), 3),
                     round(float(r["margin"]), 3), r["marker"] or "",
                     "" if r["inserted"] is None else int(r["inserted"]), r["card_type"] or "")
        else:
            actor = ("", "", "", "", "", "", "")

        rows.append([t, text, n_glyphs, len(text), lm, round(minconf, 3), nbad, "default", *actor])
        if calib:
            print("   t=%-8s 读出=%-9s 位数=%d 最左段x=%s" %
                  (("%.2f" % t).rstrip("0").rstrip("."), text or "(空)", len(text), lm), flush=True)
        if (i + 1) % 50 == 0 or i + 1 == len(paths):
            el = time.time() - t0
            print("  %4d/%d 帧  %.1fs  平均 %.0f ms/帧（剩余 %.0fs）" %
                  (i + 1, len(paths), el, el * 1000 / (i + 1), el / (i + 1) * (len(paths) - i - 1)),
                  flush=True)

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        w.writerows(rows)
    print("\n已写出 %s（%d 帧，%d 帧有读数）" %
          (out, len(rows), sum(1 for r in rows if r[1])))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="frames/glyphcache")
    ap.add_argument("--range", default="100,340")
    ap.add_argument("--out", default="out/frames_C.csv")
    ap.add_argument("--chain", type=int, default=20)
    ap.add_argument("--actor-every", type=int, default=1,
                    help="每 N 帧读一次行动轴（默认 1=每帧都读）。"
                         "1 fps 网格必须用 1：锚点帧那一帧没有行动者读数的话，"
                         "归属就只能借邻帧，实测会让对账从 10/0 掉到 1/9。"
                         "0.2s 密帧网格可以用 5 省时间（行动轴是秒级变化的量）。")
    ap.add_argument("--actor-at", default="", help="这些时刻一定读行动者，逗号分隔")
    ap.add_argument("--step", type=float, default=1.0,
                    help="只扫 step 秒网格上的帧（1.0=1 fps 网格；0.2=密帧网格；0=全部）")
    ap.add_argument("--calib", action="store_true", help="打印每帧的丢位判定")
    args = ap.parse_args()
    lo, hi = [float(x) for x in args.range.split(",")]
    at = tuple(float(x) for x in args.actor_at.split(",") if x.strip())
    return scans(args.dir, lo, hi, args.out, args.chain, args.actor_every, at, args.calib,
                 args.step)


if __name__ == "__main__":
    sys.exit(main())
