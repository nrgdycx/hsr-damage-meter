# -*- coding: utf-8 -*-
"""
E 线：分析第二个录屏（欢愉/阿哈时刻）里的「行动轴顶端卡」。

做三件事：
  1) 对每帧跑模块的标记分类（圆点/四角星/敌方/空），统计分布
  2) 把顶端卡**头像**聚类（不看身份，只看像不像同一张卡），
     再看同一簇里是否既有圆点帧又有四角星帧 → 验证"星形只是同单位的另一种状态"
  3) 打印时间轴，标出阿哈时刻卡（顶端被面具框占据）出现的时段
"""
# [P3 整理] 原路径：axis_aha_E.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import glob
import json
import os

import cv2
import numpy as np

import axis_actor as T

DIR2 = "frames/glyphcache2_E"
NCC_SAME = 1.60          # 同簇阈值（同图 1.9；不同图一般 <1.2）


def frames():
    out = []
    for p in sorted(glob.glob(os.path.join(DIR2, "*.png"))):
        try:
            t = float(os.path.basename(p)[1:-4])
        except ValueError:
            continue
        out.append((t, p))
    return out


def main():
    bank = T.load_bank()
    rows = []
    for t, p in frames():
        img = cv2.imread(p, cv2.IMREAD_COLOR)
        if img is None:
            continue
        s = T.scale_of(img.shape)
        f = T.feats_art(img, s)
        mk, mscore, hue = T.marker_feat(img, s)
        sc = T.match(bank, img, s)
        unit, (best, _) = max(sc.items(), key=lambda kv: kv[1][0])
        rows.append(dict(t=t, f=f, mk=mk, mscore=mscore, hue=hue,
                         unit=unit if best >= T.THR else None, score=round(best, 2)))
    print("共 %d 帧；标记分布：%s" % (len(rows), _count(r["mk"] for r in rows)))

    # 聚类顶端头像（只看像不像）
    clusters = []
    for r in rows:
        placed = False
        for c in clusters:
            if T.pair_score(r["f"], c["rep"]) >= NCC_SAME:
                c["ts"].append(r["t"])
                c["mks"].append(r["mk"])
                placed = True
                break
        if not placed:
            clusters.append(dict(rep=r["f"], rep_t=r["t"], ts=[r["t"]], mks=[r["mk"]]))
    clusters.sort(key=lambda c: -len(c["ts"]))
    print("\n头像聚类（共 %d 簇，列 >=2 帧的；★=同一簇里既有圆点又有四角星）：" % len(clusters))
    for i, c in enumerate(clusters):
        if len(c["ts"]) < 2:
            continue
        both = ("ally_dot" in c["mks"] and "ally_star" in c["mks"])
        if not both and len(c["ts"]) < 4:
            continue
        print("  簇%-2d 帧数%-4d %s" % (i, len(c["ts"]),
                                    "★既有圆点又有星" if both else ""))
        print("        帧: %s" % " ".join(T.fmt_t(x) for x in c["ts"][:24]))
        print("        标记: %s" % " ".join("%s:%s" % (T.fmt_t(t), m)
                                        for t, m in zip(c["ts"][:24], c["mks"][:24])))

    json.dump([dict(t=r["t"], mk=r["mk"], mscore=r["mscore"], unit=r["unit"], score=r["score"])
               for r in rows],
              open("out/axis2_E.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已写出 out/axis2_E.json")

    # 时间轴（每行 30 帧）
    ab = {"ally_dot": "·", "ally_star": "★", "enemy_dot": "敌", "enemy_star": "敌",
          "empty": "空", "none": "?"}
    print("\n时间轴（·圆点 ★四角星 敌 空）")
    for i in range(0, len(rows), 40):
        chunk = rows[i:i + 40]
        print("t=%-4s %s" % (T.fmt_t(chunk[0]["t"]),
                             "".join(ab.get(r["mk"], "?") for r in chunk)))


def _count(xs):
    from collections import Counter
    return dict(Counter(xs))


if __name__ == "__main__":
    main()
