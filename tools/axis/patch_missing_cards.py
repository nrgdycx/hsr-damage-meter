# -*- coding: utf-8 -*-
"""把"被质量闸误杀"的召唤物卡补进采集目录（用与 harvest 相同的卡框与命名）。

已经确认的一个案例：**龙灵**（丹恒•腾荒的召唤物，t=309.0~309.8）
—— 金龙是一大片平滑金色，梯度只有 6.9~10.6，被旧的 GRAD_MIN=12 丢掉。
harvest_characters.py 已把闸门放到 6.5；这里把历史上漏掉的几张补进
frames/harvest_复杂情况/cards/，命名沿用 t%08.2f.png。
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from ffmpeg_path import require_ffmpeg as _req_ff
import os
import subprocess
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import axis_actor as T      # noqa: E402

FF = _req_ff()   # 见 ffmpeg_path.py（可用 HSR_FFMPEG 指定）
VID = os.path.join(ROOT, "records", "复杂的情况.mp4")
CDIR = os.path.join(ROOT, "frames", "harvest_复杂情况", "cards")
TMP = os.path.join(ROOT, "frames", "_patch.png")
CARD = (82, 78, 281, 178)
TIMES = [309.0, 309.2, 309.4, 309.6, 309.8]

added = 0
for t in TIMES:
    subprocess.run([FF, "-ss", "%.2f" % t, "-i", VID, "-frames:v", "1", "-y", TMP],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    img = cv2.imdecode(np.fromfile(TMP, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        print("t=%.1f 取帧失败" % t)
        continue
    s = img.shape[1] / float(T.REF_W)
    x0, y0, x1, y1 = [int(round(v * s)) for v in CARD]
    card = img[y0:y1, x0:x1]
    out = os.path.join(CDIR, "t%08.2f.png" % t)
    ok, buf = cv2.imencode(".png", card)
    if ok:
        buf.tofile(out)
        added += 1
        print("已补 t=%.1f → %s" % (t, os.path.basename(out)))
try:
    os.remove(TMP)
except OSError:
    pass
print("补充 %d 张；现在 cards 目录共 %d 张"
      % (added, len([f for f in os.listdir(CDIR) if f.endswith(".png")])))
