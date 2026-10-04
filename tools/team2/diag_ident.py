# -*- coding: utf-8 -*-
"""【线2】用**右侧队伍面板**（t≈0 显示，带名字）给顶端卡分组的身份做客观核对。

背景：录屏2 的队伍面板只在开场出现，但它是**唯一带名字**的画面：
       银狼 / 爻光 / 火花 / 真珠（见 samples/L2_team_panel.png）。
     把面板头像与顶端卡分组做 NCC 打分，得到一个「分组 × 角色」的分数矩阵，
     用来**核对人眼判断**（人眼是第一依据，这里只做交叉验证，冲突就报出来）。

用法：
  python -u diag_l2_ident.py                 # 打分矩阵 + 每个分组的最佳角色
  python -u diag_l2_ident.py --panel frames/team_M/d000.0.png
"""
# [P3 整理] 原路径：diag_l2_ident.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
sys.path.insert(0, HERE)

import axis_actor as T          # noqa: E402
import axis_actor_team2 as T2        # noqa: E402

PANEL = "frames/team_M/d000.0.png"
# 面板 4 行的**人物框**（M 线给的坐标，去掉右侧编号圆牌）
ROWS = [("银狼", 2600, 505, 2790, 660), ("爻光", 2600, 655, 2790, 810),
        ("火花", 2600, 795, 2790, 950), ("真珠", 2600, 935, 2790, 1090)]
CLUSTERS = "out/axis_clusters_L2.json"


def panel_faces(path=PANEL):
    """返回 {角色: 头像特征}（取每个面板行的**人脸那一块**）。"""
    im = np.asarray(Image.open(path).convert("RGB"))
    h, w = im.shape[:2]
    out = {}
    for name, x0, y0, x1, y1 in ROWS:
        y1 = min(y1, h)
        x1 = min(x1, w)
        sub = im[y0:y1, x0:x1]
        ih, iw = sub.shape[:2]
        # 人脸大致在人物框的上半部偏中：取 40%×55% 的中心块
        fx0, fx1 = int(iw * 0.28), int(iw * 0.72)
        fy0, fy1 = int(ih * 0.10), int(ih * 0.62)
        face = sub[fy0:fy1, fx0:fx1]
        out[name] = T.feats(face)
    return out


def cluster_reps():
    with open(CLUSTERS, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default=PANEL)
    args = ap.parse_args()
    faces = panel_faces(args.panel)
    print("面板头像模板：%s" % {k: v.shape for k, v in faces.items()})
    reps = cluster_reps()
    print("\n%-6s %-5s %-9s %s" % ("组", "n", "例帧", "与 4 个面板头像的相似度（高=像）"))
    best_rows = []
    for r in reps:
        p = os.path.join(T2.CROP_DIR, "t%08.2f_top.png" % r["rep"])
        img = cv2.imread(p, cv2.IMREAD_COLOR)
        if img is None:
            continue
        full = T2.as_full(img)
        art = T.top_art(full, T.scale_of(full.shape))
        f = T.feats(art)
        sc = {name: round(float((ff * f).mean()), 3) for name, ff in faces.items()}
        order = sorted(sc.items(), key=lambda kv: -kv[1])
        mark = "?" if (len(order) > 1 and order[0][1] - order[1][1] < 0.10) else " "
        print("%-6s %-5s %-9s %s   → %s%s(%.2f)"
              % ("组%d" % r["gid"], r["n"], T.fmt_t(r["rep"]),
                 " ".join("%s%.2f" % kv for kv in order), order[0][0], mark, order[0][1]))
        best_rows.append((r["gid"], order[0][0], order[0][1], r["markers"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
