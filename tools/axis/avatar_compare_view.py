# -*- coding: utf-8 -*-
"""
出对比图：**官方头像** vs 游戏画面里挖的**行动轴卡头像**。

背景：`official_avatar_probe.py` 用 NCC 判定"不同源"（官方头像 × 画面模板 max 0.37，
与"跨角色"同量级）。本脚本把两者并排画出来，让人眼直接确认——
比数字更可靠（本项目在数字解读上栽过多次）。

用法：
    python tools/axis/avatar_compare_view.py
产物：
    samples/官方头像_vs_画面模板.png
"""

import io
import json
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for _p in (ROOT, os.path.join(ROOT, "vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

RAW = r"D:\project\btdsh\raw"
AVATAR_DIR = os.path.join(RAW, "icon", "avatar")
# ⚠️ cv2.imwrite 不支持中文路径（会静默失败）→ 用 ASCII 文件名
OUT = os.path.join(ROOT, "samples", "avatar_vs_screen_templates.png")

# 想对比的角色（画面模板库里的中文名）
PAIRS = [
    ("遐蝶", "1407"), ("风堇", "1409"), ("昔涟", "1415"), ("长夜月", "1413"),
    ("银狼", "1006"), ("火花", "1501"), ("爻光", "1502"), ("真珠", "1503"),
]

# 画面模板是 4 通道特征，第 0 通道是灰度 —— 直接可视化它
CELL = 144          # 每格显示尺寸
PAD = 8
BG = (28, 28, 34)


def to_bgr_from_feat(feat_ch0):
    """把模板的灰度通道（0~1, 48x72）还原成可看的 BGR。"""
    g = np.clip(feat_ch0, 0, 1)
    g8 = (g * 255).astype(np.uint8)
    return cv2.cvtColor(g8, cv2.COLOR_GRAY2BGR)


def main():
    bank = np.load(os.path.join(ROOT, "out", "axis_top_bank_E.npz"), allow_pickle=True)
    names = {}
    p = os.path.join(ROOT, "StarRailRes-index_min", "index_min", "cn", "characters.json")
    if os.path.exists(p):
        d = json.load(io.open(p, encoding="utf-8"))
        names = {str(v.get("id")): v.get("name") for v in d.values() if isinstance(v, dict)}

    rows = []
    for cn, cid in PAIRS:
        if cn not in bank.files:
            continue
        # 画面模板：取第 0 个（保存下来的就是原样）
        mat = bank[cn][0]                     # (4,48,72)
        screen = to_bgr_from_feat(mat[0])
        # 官方头像
        off = None
        ap = os.path.join(AVATAR_DIR, "%s.png" % cid)
        if os.path.exists(ap):
            off = cv2.imread(ap, cv2.IMREAD_COLOR)
        rows.append((cn, cid, off, screen))

    if not rows:
        print("没有可对比的数据")
        return

    cols = 2
    W = PAD + cols * (CELL + PAD)
    H = PAD + len(rows) * (CELL + 34 + PAD)
    canvas = np.full((H, W, 3), BG, np.uint8)

    def put(img, x, y, w=CELL, h=CELL):
        if img is None:
            cv2.rectangle(canvas, (x, y), (x + w, y + h), (90, 60, 60), 1)
            cv2.putText(canvas, "N/A", (x + 38, y + h // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (160, 160, 200), 1, cv2.LINE_AA)
            return
        r = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
        canvas[y:y + h, x:x + w] = r

    for i, (cn, cid, off, screen) in enumerate(rows):
        y = PAD + i * (CELL + 34 + PAD)
        x1 = PAD
        x2 = PAD + CELL + PAD
        put(off, x1, y + 28)
        put(screen, x2, y + 28)
        # 标签（画在留白上，不遮图）
        cv2.putText(canvas, "%s (ID %s)" % (cn, cid), (x1, y + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (120, 230, 255), 1, cv2.LINE_AA)
        cv2.putText(canvas, "screen template", (x2, y + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (140, 255, 160), 1, cv2.LINE_AA)
        cv2.rectangle(canvas, (x1, y + 28), (x1 + CELL, y + 28 + CELL), (70, 70, 90), 1)
        cv2.rectangle(canvas, (x2, y + 28), (x2 + CELL, y + 28 + CELL), (70, 70, 90), 1)

    # 抬头
    head = np.full((30, W, 3), (16, 16, 22), np.uint8)
    cv2.putText(head, "left = official avatar (btdsh/raw/icon/avatar)   right = mined from screen",
                (PAD, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (235, 235, 245), 1, cv2.LINE_AA)
    canvas = np.vstack([head, canvas])

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    cv2.imwrite(OUT, canvas)
    print("已写出:", OUT, canvas.shape)


if __name__ == "__main__":
    main()
