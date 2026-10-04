# -*- coding: utf-8 -*-
"""
[本对话专用 · 只读诊断] 用用户提供的 13 帧真值，定案 Q1 的失败机制。

真值（用户 2026-XX 读数，见 docs/用户口径与铁律.md）：
    t=26 → 140130      t=29 → 286055      t=30 → 279947      t=31 → 279947
    t=35 → 100291      t=64 → 空          t=100 → 506286     t=110 → 空
    t=150 → 空         t=200 → 空         t=238 → 2052321   t=300 → 123692
    t=340 → 1371940（偏暗，疑似入场/退场过渡）

要回答的三个问题（对应 Q1 的三种候选原因）：
  1. 真值几位 vs 模型读出几位 → 是"整位丢"还是"单字误判"？
  2. 被丢的那一位，它的墨迹是否**落在裁剪框之外**（框太窄）？
     还是在框内、但没被收进字形链（链阈值/掩膜问题）？
  3. 失败是否集中在银狼强普的像素体帧（验证 Q3 的猜想）？

**本脚本不修改任何上游文件**（只读 frames/ 里已缓存的帧）。
用法：python -u diag_user_truth.py
"""
# [P3 整理] 原路径：diag_user_truth.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import os
import sys

import numpy as np
from PIL import Image

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
sys.path.insert(0, HERE)

import hud_glyphs as HG          # noqa: E402
import read_hud                  # noqa: E402

# 用户真值（None = 用户写"看不清/空"）
TRUTH = {26: "140130", 29: "286055", 30: "279947", 31: "279947", 35: "100291",
         64: None, 100: "506286", 110: None, 150: None, 200: None,
         238: "2052321", 300: "123692", 340: "1371940"}

FRAME_DIR = "frames/hud2_M"
DEFAULT_BOX = (HG.CY0, HG.CX0, HG.CY1, HG.CX1)   # (260,2350,340,2876)

# 框变体：左界向左放宽（测"框太窄"）；高度放宽（测"字号变大"）
BOXES = [
    ("上游默认 (260,2350,340,2876)", (260, 2350, 340, 2876)),
    ("左界 -60  (260,2290,340,2876)", (260, 2290, 340, 2876)),
    ("左界 -150 (260,2200,340,2876)", (260, 2200, 340, 2876)),
    ("左界 -250 (260,2100,340,2876)", (260, 2100, 340, 2876)),
    ("上下放宽 (240,2200,366,2876)", (240, 2200, 366, 2876)),
]
CHAINS = [20, 30, 40, 50, 60, 80]


def col_runs(a, box):
    """按 _extract_core 的口径（辉光层分割 + 挖空 BAR_ROWS + 3px 并段）返回列段（绝对 x）。"""
    y0, x0, y1, x1 = box
    c = np.asarray(a[y0:y1, x0:x1], dtype=np.int16)
    m_seg, _, _ = HG._masks(c, HG.MASK_MODE)
    ms = m_seg.copy()
    r0, r1 = max(0, HG.BAR_ROWS[0] - y0), min(ms.shape[0] - 1, HG.BAR_ROWS[1] - y0)
    if r0 <= r1 and r0 < ms.shape[0]:
        ms[r0:r1 + 1, :] = False
    col = ms.any(axis=0)
    runs, s = [], None
    for x in range(len(col)):
        if col[x] and s is None:
            s = x
        elif not col[x] and s is not None:
            runs.append([s, x - 1])
            s = None
    if s is not None:
        runs.append([s, len(col) - 1])
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] - 1 < 3:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [[s + x0, e + x0] for s, e in merged]      # 转成绝对 x


def chain_runs(merged, chain_px):
    """复刻 _extract_core 的链式规则：从最右往左，间隔 > chain_px 就断开。"""
    ch = []
    for r in reversed(merged):
        if not ch:
            ch.append(r)
        elif ch[-1][0] - r[1] - 1 <= chain_px:
            ch.append(r)
        else:
            break
    return list(reversed(ch))


def read_with(a, model, box, chain_px):
    """给定框 + 链阈值读数（用 scan_chain.module_with_chain 临时替换阈值，不改上游）。"""
    import torch
    _ev = os.path.join(_r, "tools", "events")     # [P3] scan_C2.py 已改名 scan_chain.py
    if _ev not in sys.path:
        sys.path.insert(0, _ev)
    import scan_chain as scan_C2  # noqa: E402  （P3 改名：scan_C2.py → scan_chain.py）
    mod = scan_C2.module_with_chain(chain_px)
    gs = mod.extract(a, box=box)
    if not gs:
        return "", 0
    x = torch.tensor(np.stack([v for v, _, _ in gs])[:, None], dtype=torch.float32)
    with torch.no_grad():
        pr = torch.softmax(model(x), 1)
    cf, pd = pr.max(1)
    return "".join(str(int(d)) if c >= 0.55 else "?" for d, c in zip(pd.tolist(), cf.tolist())), len(gs)


def main():
    model = read_hud.load_model()
    frames = {}
    for t in sorted(TRUTH):
        p = os.path.join(FRAME_DIR, "t%08.2f.png" % t)
        if os.path.exists(p):
            frames[t] = np.asarray(Image.open(p).convert("RGB"))
        else:
            print("  缺帧 %s" % p)

    # ── A. 位数对账 + 墨迹范围（默认框）──
    print("=" * 100)
    print("A. 位数对账（上游默认框 %s，链 20）—— 真值几位 vs 读出几位" % (DEFAULT_BOX,))
    print("%-6s %-10s %-8s %-8s %-8s %s" % ("t", "用户真值", "真值位", "读出", "读出位", "判定"))
    for t, truth in sorted(TRUTH.items()):
        if t not in frames:
            continue
        txt, n = read_with(frames[t], model, DEFAULT_BOX, 20)
        nt, nr = (len(truth) if truth else 0), len(txt)
        if truth is None:
            verdict = "真值未知（用户看不清/空）" + ("；模型也空" if nr == 0 else "；模型给出 %s ← 需存疑" % txt)
        elif nr == 0:
            verdict = "模型空 ← 整串失败"
        elif nt == nr:
            verdict = "位数一致" + ("且完全相同 [OK]" if txt == truth else "但内容不同 [X]")
        elif nt > nr:
            verdict = "模型**少 %d 位** ← 丢位" % (nt - nr)
        else:
            verdict = "模型**多 %d 位** ← 假字/粘连" % (nr - nt)
        print("%-6s %-10s %-8s %-8s %-8s %s" % (t, truth or "(空)", nt, txt or "(空)", nr, verdict))

    # ── B. 墨迹范围 vs 框边界（框太窄的判据）──
    print("\n" + "=" * 100)
    print("B. 墨迹范围 vs 框左界 —— 被丢的那一位是否真的在框外？")
    print("   框左界 CX0=%d。若最左墨迹**紧贴框左界（相差 ≤3px）**，说明框在切字。" % HG.CX0)
    print("%-6s %-10s %-10s %-10s %s" % ("t", "真值", "最左墨迹x", "距框左界", "最右墨迹x / 段数（框内）"))
    for t, truth in sorted(TRUTH.items()):
        if t not in frames:
            continue
        merged = col_runs(frames[t], DEFAULT_BOX)
        if not merged:
            print("%-6s %-10s %-10s %-10s %s" % (t, truth or "(空)", "-", "-", "框内无墨迹"))
            continue
        left_most = merged[0][0]
        right_most = merged[-1][1]
        print("%-6s %-10s %-10s %-10s %s" % (t, truth or "(空)", left_most, left_most - HG.CX0,
                                             "%d / %d 段" % (right_most, len(merged))))

    # ── C. 框 × 链 扫描（找能对上真值的组合）──
    print("\n" + "=" * 100)
    print("C. 框 × 链阈值 扫描（[MATCH] = 与真值完全一致）")
    for label, box in BOXES:
        print("\n  ── %s ──" % label)
        print("     %-6s %-10s %s" % ("t", "真值", "  ".join("链%-3d" % c for c in CHAINS)))
        for t, truth in sorted(TRUTH.items()):
            if t not in frames:
                continue
            cells = []
            for c in CHAINS:
                txt, n = read_with(frames[t], model, box, c)
                s = txt or "(空)"
                if truth and txt == truth:
                    s = "[MATCH]" + s
                cells.append("%-8s" % s)
            print("     %-6s %-10s %s" % (t, truth or "(空)", "  ".join(cells)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
