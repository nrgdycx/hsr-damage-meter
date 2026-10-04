# -*- coding: utf-8 -*-
"""
E 线：共用的真值数据（正向模板标签 + 人工核对过的负向帧）。

* 正向：out/axis_top_labels_E.json，68→71 帧，全部人工看图核对
* 负向：**人工核对确认不是我方单位**的帧（敌人 / 空槽 / 动画过渡 / 背景）
  注意不要把真单位混进负向集，否则会虚高"负向最高分"、把阈值带偏（第一版踩过这个坑）。
"""
import json
import os

import cv2

import axis_actor as T

FRAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frames/glyphcache/f%08.2f.png")

NEG = [103, 104, 111, 113, 118, 120, 126, 130, 133, 134, 135, 139, 142, 144, 147,
       153, 155, 158, 168, 170, 171, 172, 173, 179, 181, 183, 187, 189, 190, 191,
       196, 198, 204, 207, 208, 209, 210, 212, 216, 227, 230, 231, 235, 240, 244,
       248, 253, 254, 263, 266, 270, 276, 281, 282, 288, 290, 291, 297, 299, 300,
       305, 312, 313, 320, 325, 330, 335, 339]


def labels():
    d = json.load(open(T.LABELS_PATH, encoding="utf-8"))
    return {k: [float(x) for x in v] for k, v in d.items() if not k.startswith("_")}


def art(t):
    img = cv2.imread(FRAME % t, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(FRAME % t)
    return T.top_art(img)


def feats_of(t):
    return T.feats(art(t))
