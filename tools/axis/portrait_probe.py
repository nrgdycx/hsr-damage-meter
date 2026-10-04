# -*- coding: utf-8 -*-
"""
把 `btdsh/raw/image/character_portrait/<id>.png`（大立绘）裁一块，和
画面里挖的行动轴模板对比 —— 判断"卡上那块是不是立绘的某个裁剪"。

动机：官方小头像（128×128 icon/avatar）与画面模板 NCC 只有 0.1~0.37 → 不同源。
但大立绘可能是**同一张原图**，只是裁剪区域不同 → 若如此，可用自动对位（模板匹配）
从立绘里**自动生成**行动轴模板，从而摆脱"每支队伍都要手工挖模板"。

用法：
    python tools/axis/portrait_probe.py
产物：
    samples/portrait_vs_template.png
"""

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
PORTRAIT = os.path.join(RAW, "image", "character_portrait")
AVATAR = os.path.join(RAW, "icon", "avatar")
OUT = os.path.join(ROOT, "samples", "portrait_vs_template.png")

CASES = [("遐蝶", "1407"), ("风堇", "1409"), ("银狼", "1506"), ("真珠", "1503")]
CELL = 192


def to_bgr(feat_ch0):
    g = np.clip(feat_ch0, 0, 1)
    return cv2.cvtColor((g * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)


def best_match(portrait_bgr, tmpl_gray48x72):
    """
    在立绘里滑窗找"最像该模板"的位置（多尺度），返回 (分数, 裁剪图)。
    用灰度做，够用（只为判断"是不是同一张原图"）。
    """
    ph, pw = portrait_bgr.shape[:2]
    pg = cv2.cvtColor(portrait_bgr, cv2.COLOR_BGR2GRAY)
    # ⚠️ matchTemplate 要求同类型：模板的灰度是 0~1 的 float → 转成 uint8
    tmpl = np.clip(tmpl_gray48x72, 0, 1)
    tmpl = (tmpl * 255).astype(np.uint8)
    th, tw = tmpl.shape                     # 48 x 72
    best = (-2.0, None, None)
    for scale in (1.0, 1.4, 1.9, 2.6, 3.6):
        tw2, th2 = int(tw * scale), int(th * scale)
        if tw2 >= pw or th2 >= ph:
            continue
        t = cv2.resize(tmpl, (tw2, th2), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(pg, t, cv2.TM_CCOEFF_NORMED)
        _, mx, _, ml = cv2.minMaxLoc(res)
        if mx > best[0]:
            crop = portrait_bgr[ml[1]:ml[1] + th2, ml[0]:ml[0] + tw2]
            best = (float(mx), crop, scale)
    return best


def main():
    bank = np.load(os.path.join(ROOT, "out", "axis_top_bank_E.npz"), allow_pickle=True)
    names = {}
    p = os.path.join(ROOT, "StarRailRes-index_min", "index_min", "cn", "characters.json")
    if os.path.exists(p):
        d = json.load(open(p, encoding="utf-8"))
        names = {str(v.get("id")): v.get("name") for v in d.values() if isinstance(v, dict)}

    rows = []
    for cn, cid in CASES:
        if cn not in bank.files:
            continue
        mat = bank[cn][0]
        tmpl_gray = np.clip(mat[0], 0, 1)
        screen = to_bgr(mat[0])
        pp = os.path.join(PORTRAIT, "%s.png" % cid)
        ap = os.path.join(AVATAR, "%s.png" % cid)
        portrait = cv2.imread(pp, cv2.IMREAD_COLOR) if os.path.exists(pp) else None
        avatar = cv2.imread(ap, cv2.IMREAD_COLOR) if os.path.exists(ap) else None
        score, crop, scale = (-1.0, None, None)
        if portrait is not None:
            score, crop, scale = best_match(portrait, tmpl_gray)
        rows.append((cn, cid, avatar, portrait, crop, score, scale))
        print("%-6s ID=%-5s 立绘最相似处 NCC=%.3f (scale=%s)  头像=%s 立绘=%s"
              % (cn, cid, score, scale,
                 "有" if avatar is not None else "无",
                 "有" if portrait is not None else "无"))

    # 出图：三列 —— 官方头像 / 立绘里最像的裁剪 / 画面模板
    cols = 3
    W = 8 + cols * (CELL + 8)
    H = 34 + len(rows) * (CELL + 36)
    canvas = np.full((H, W, 3), (28, 28, 34), np.uint8)
    heads = ["official avatar", "portrait best-match crop", "screen template"]

    def put(img, x, y):
        if img is None:
            cv2.rectangle(canvas, (x, y), (x + CELL, y + CELL), (90, 60, 60), 1)
            return
        canvas[y:y + CELL, x:x + CELL] = cv2.resize(img, (CELL, CELL), interpolation=cv2.INTER_AREA)

    for j, htxt in enumerate(heads):
        cv2.putText(canvas, htxt, (8 + j * (CELL + 8), 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 220, 255), 1, cv2.LINE_AA)

    for i, (cn, cid, avatar, portrait, crop, score, scale) in enumerate(rows):
        y = 34 + i * (CELL + 36)
        put(avatar, 8, y)
        put(crop, 8 + CELL + 8, y)
        put(to_bgr(bank[cn][0][0]), 8 + 2 * (CELL + 8), y)
        cv2.putText(canvas, "%s (ID %s)  bestNCC=%.2f" % (cn, cid, score),
                    (8, y + CELL + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 230, 130), 1,
                    cv2.LINE_AA)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    cv2.imwrite(OUT, canvas)
    print("\n已写出:", OUT, canvas.shape)


if __name__ == "__main__":
    main()
