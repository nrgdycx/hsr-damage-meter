# -*- coding: utf-8 -*-
"""
字形数据集构建 —— 把「整串数字」（人工确认过的）拆成带标签的单个字形。

依据（都经过实测+用户确认）：
  * HUD 总伤害是【淡黄】(B>=185)，遮挡的伤害飘字是【饱和黄】(B≈125~180) → 阈值能分离；
  * 掩膜用 (R,G>225) & (B>=185) & (R-B>25) 时，列分割能切对大多数帧；
  * 数字左边有一条固定位置的细横线，用「宽<=52 且 高>=45」过滤掉；
  * 条数 == 位数 的帧才可用于建集（否则说明切错了，跳过）。

产物：out/digit_dataset.npz （X: N×1×GH×GW 的灰度字形；y: 0~9 标签；meta: 来源帧）
"""

import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect_glyphs import frame  # noqa: E402
import hud_glyphs  # noqa: E402

# ── 固定的提取参数（唯一实现在 hud_glyphs.py，训练与推理共用，不会漂移）──
CY0, CY1 = hud_glyphs.CY0, hud_glyphs.CY1
CX0, CX1 = hud_glyphs.CX0, hud_glyphs.CX1
GW, GH = hud_glyphs.GW, hud_glyphs.GH
W_MIN, W_MAX = 6, hud_glyphs.W_MAX
H_MIN = hud_glyphs.H_MIN
BAR_ROWS = hud_glyphs.BAR_ROWS
TEMPLATE_FILE = "out/digit_dataset.npz"
# 额外样本（不是用户现读的，而是"与用户已确认帧高度相似"的邻近帧；见 harvest_A.py）
EXTRA_FILE = "out/harvest_A.json"

# 已人工确认数值的帧 —— 真值唯一来源是 digit_truth.py（用户读图确认）
from digit_truth import LABELED, HOLDOUT, near_holdout  # noqa: E402


def frame_glyphs(t, verbose=False):
    """返回该帧切出的字形列表 [(gray 0~1 矩阵, 像素宽, 像素高)]（共用 hud_glyphs 实现）。"""
    a = np.asarray(Image.open(frame(float(t))).convert("RGB")).astype(np.int16)
    return hud_glyphs.extract(a)


def build(labeled=None, save=True):
    labeled = labeled or LABELED
    X, y, meta = [], [], []
    report = []
    for t, value in labeled.items():
        gs = frame_glyphs(t)
        # HUD 数字是【右对齐】的：左边缺字/多出碎块不应影响右边标签的对应关系，
        # 所以按最右边开始对齐，而不是从左往右硬套。
        # 但缺得太多（≥2 位）时无法判断缺的是左边还是右边，宁可不收，避免贴错标签
        # （实测 t=100/t=102 就是这样：6 位数只切出 3~4 段，硬套会把标签贴到错误的字上）。
        if len(gs) == 0 or len(gs) > len(value) or len(gs) < len(value) - 1:
            report.append("t=%s 切出 %d 段 / 位数 %d → 弃用（缺位无法确定）" % (t, len(gs), len(value)))
            continue
        labels = value[-len(gs):]
        for i, (v, w, h) in enumerate(gs):
            X.append(v)
            y.append(int(labels[i]))
            meta.append({"t": t, "pos": i, "digit": labels[i]})
        note = "" if len(gs) == len(value) else "（左起 %d 位未切到，按右对齐补）" % (len(value) - len(gs))
        report.append("t=%s %s → 收 %d 个字 %s" % (t, value, len(gs), note))
    X = np.stack(X)[:, None, :, :] if X else np.zeros((0, 1, GH, GW), np.float32)
    y = np.array(y, np.int64)
    if save:
        np.savez_compressed(TEMPLATE_FILE, X=X, y=y,
                            meta=np.array([json.dumps(m) for m in meta]))
    return X, y, meta, report


if __name__ == "__main__":
    X, y, meta, rep = build()
    print("构建报告:")
    for r in rep:
        print("   ", r)
    print("\n样本数 %d，标签分布 %s" % (len(y), dict(zip(*np.unique(y, return_counts=True)))))
    print("缺少的数字:", "".join(c for c in "0123456789" if int(c) not in set(y.tolist())))
    print("写出:", TEMPLATE_FILE, " X.shape =", X.shape)
    # 自检：同数字不同帧的字形应相似
    print("\n同类相似度自检（同数字的字形两两平均差，越小越一致）:")
    for d in sorted(set(y.tolist())):
        idx = np.where(y == d)[0]
        if len(idx) < 2:
            print("   %d: 只有 %d 个样本" % (d, len(idx)))
            continue
        ds = [float(np.abs(X[a] - X[b]).mean()) for i, a in enumerate(idx) for b in idx[i + 1:]]
        print("   %d: n=%d 平均差 %.3f (最大 %.3f)" % (d, len(idx), sum(ds) / len(ds), max(ds)))
