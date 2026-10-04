# -*- coding: utf-8 -*-
"""
[C 线 / 给 A 线的证据] 前导位静默丢失的取证与修复试验。

现象（C 线在跑事件切分时发现，比 A 线文档记的更严重）：
  A 线文档只记了 `t=102 → 4505`（记作"3+0 粘连成 75px 宽块被丢弃"），
  但逐帧扫 249 帧发现**多帧系统性丢前导位**，而且读数本身不带 '?'，是"自信的错"：
      t=102   屏幕实际 304505 → 读出 4505
      t=135.6 屏幕实际 191176 → 读出 76
      t=142   屏幕实际 108018 → 读出 8      （上一帧 141 读 108018 是对的）
      t=303   屏幕实际 120754 → 读出 20754
      t=158   屏幕实际 210408 → 读出 0408
      t=312   屏幕实际 379852 → 读出 7985
      t=155/248/289/292/208/333 → 只有 1~2 位

根因（读 hud_glyphs._extract_core 得出，并用本脚本量化）：
  列分割后有一条「**链式连续性**」规则——从最右段往左串，相邻段间隔 >20px 就停止。
  数字与左侧 UI 元素（或与被特效切碎的辉光）之间只要出现 >20px 的空隙，
  左边所有字形就被整段丢掉 → 读数少位，且**没有任何告警**。

本脚本做两件事：
  1. `--audit`  量化每一帧的列段间隔，指出"链在哪里断的、断掉了几段"；
  2. `--fix`    把链式阈值放大后重读，看能不能把前导位找回来（用 A 线真值帧验证）。
     放大到 40px 实测能把大部分帧的前导位找回；但**放大有代价**：可能把邻近的
     其它 UI 元素（金色细线等）也吃进来。所以这里只出证据，不改 A 线模块。

用法：
  python diag_chain_C.py --audit 102 135.6 142 303 158 312 106 141
  python diag_chain_C.py --fix 40
"""
# [P3 整理] 原路径：diag_chain_C.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hud_glyphs as HG  # noqa: E402
import read_hud  # noqa: E402

FRAME = "frames/glyphcache/f%08.2f.png"


def segs_of(a, box=None):
    """返回 [(xa, xb, w, h, mass)] —— 与 hud_glyphs 列分割同源（辉光掩膜 + 挖空横线带）。"""
    y0, x0, y1, x1 = box or (HG.CY0, HG.CX0, HG.CY1, HG.CX1)
    c = np.asarray(a[y0:y1, x0:x1], dtype=np.int16)
    m_seg, m_glyph, _ = HG._masks(c, "glow")
    ms = m_seg.copy()
    r0, r1 = max(0, HG.BAR_ROWS[0] - y0), min(ms.shape[0] - 1, HG.BAR_ROWS[1] - y0)
    ms[r0:r1 + 1, :] = False
    col = ms.any(axis=0)
    runs, s = [], None
    for x in range(len(col)):
        if col[x] and s is None:
            s = x
        elif not col[x] and s is not None:
            runs.append([s, x - 1]); s = None
    if s is not None:
        runs.append([s, len(col) - 1])
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] - 1 < 3:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    out = []
    for xa, xb in merged:
        m1 = m_glyph[:, xa:xb + 1]
        rows1 = np.where(m1.any(axis=1))[0]
        if len(rows1) == 0:
            continue
        out.append((xa + x0, xb + x0, xb - xa + 1, int(rows1[-1] - rows1[0] + 1), int(m1.sum())))
    return out


def audit(times, chain=20, box=None):
    print("=== 列段审计（chain 阈值 %d：与最右段间隔 >%dpx 的段会被整段丢掉）===" % (chain, chain))
    for t in times:
        p = FRAME % t
        if not os.path.exists(p):
            print("  t=%-7s 无缓存帧" % t)
            continue
        a = np.asarray(Image.open(p).convert("RGB")).astype(np.int16)
        segs = segs_of(a, box)
        if not segs:
            print("  t=%-7s 没有列段" % t)
            continue
        # 从右往左做链
        chain_segs = [segs[-1]]
        cut = None
        for s in reversed(segs[:-1]):
            if chain_segs[-1][0] - s[1] - 1 <= chain:
                chain_segs.append(s)
            else:
                cut = (s, chain_segs[-1]); break
        gaps = [segs[i + 1][0] - segs[i][1] - 1 for i in range(len(segs) - 1)]
        print("  t=%-7s 段数=%-2d 间隔=%s  链保留=%d段  断点=%s" %
              (t, len(segs), gaps, len(chain_segs),
               ("段(x=%d..%d) 与 段(x=%d..%d) 间隔 %dpx" % (cut[0][0], cut[0][1], cut[1][0], cut[1][1],
                cut[1][0] - cut[0][1] - 1)) if cut else "无（全串连上）"))


def fix_scan(chain, truth=None):
    """把链式阈值放大后重读，与真值对照。chain 直接改 hud_glyphs 的模块级行为：
    这里用 monkeypatch 的方式替换 _extract_core 里的常数（不改文件）。"""
    import types
    src = open(os.path.join(ROOT, "hud_glyphs.py"),
               encoding="utf-8").read()
    src2 = src.replace("elif chain[-1][0] - r[1] - 1 <= 20:", "elif chain[-1][0] - r[1] - 1 <= %d:" % chain)
    assert src2 != src, "没找到链式阈值那一行（hud_glyphs.py 变了吗？）"
    mod = types.ModuleType("hud_glyphs_chain%d" % chain)
    mod.__dict__["__file__"] = os.path.join(ROOT, "hud_glyphs.py")
    exec(compile(src2, "hud_glyphs_chain%d" % chain, "exec"), mod.__dict__)

    model = read_hud.load_model()
    print("\n=== 把链式阈值放大到 %dpx 后重读 ===" % chain)
    truth = truth or {}
    times = sorted(set(list(truth) + [102, 106, 135.6, 142, 303, 158, 312, 155, 248, 289, 292, 208,
                                      333, 100, 104, 105, 109, 134, 152, 167, 195, 226, 251, 275,
                                      284, 311, 317, 321, 267, 302, 249, 135, 141, 178, 241]))
    ok = bad = 0
    for t in times:
        p = FRAME % t
        if not os.path.exists(p):
            continue
        a = np.asarray(Image.open(p).convert("RGB")).astype(np.int16)
        gs = mod.extract(a)
        x = __import__("torch").tensor(np.stack([v for v, _, _ in gs])[:, None], dtype=__import__("torch").float32)
        with __import__("torch").no_grad():
            pr = __import__("torch").softmax(model(x), 1)
        cf, pd = pr.max(1)
        txt = "".join(str(int(d)) if c >= 0.55 else "?" for d, c in zip(pd.tolist(), cf.tolist()))
        note = ""
        if t in truth:
            good = (txt == truth[t])
            ok += good; bad += (not good)
            note = "  真值 %s  %s" % (truth[t], "OK" if good else "!!")
        base = ""
        try:
            b = read_hud.read_frame(model, p)[0]
            base = "（原阈值读出 %s）" % (b or "空")
        except Exception:
            pass
        print("  t=%-7s n=%-2d 读出=%-9s%s%s" % (t, len(gs), txt or "(空)", note, base))
    if truth:
        print("  真值帧一致 %d / 不一致 %d" % (ok, bad))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", nargs="*", type=float, default=None)
    ap.add_argument("--chain", type=int, default=20)
    ap.add_argument("--fix", type=int, default=0)
    args = ap.parse_args()

    if args.audit:
        audit(args.audit, args.chain)
    if args.fix:
        from digit_truth import LABELED, HOLDOUT
        tr = {}
        tr.update({float(k): v for k, v in LABELED.items()})
        tr.update({float(k): v for k, v in HOLDOUT.items()})
        fix_scan(args.fix, tr)


if __name__ == "__main__":
    main()
