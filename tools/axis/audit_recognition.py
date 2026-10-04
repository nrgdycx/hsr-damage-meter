# -*- coding: utf-8 -*-
"""识别审计：扫一段录屏（1fps），按**左标记类型 / 卡类型**统计识别结果。

回答用户 4 个问题里的两个：
  * 召唤物：忆灵在行动轴上会不会被认出来 / 被弃权 / 被认错
  * 欢愉队：阿哈时刻(gold_aha → card_type=aha) 与 欢愉技卡(ally_diamond → elation) 上表现如何
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from ffmpeg_path import require_ffmpeg as _req_ff
import json
import os
import subprocess
import sys
from collections import defaultdict

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import axis_actor as T      # noqa: E402

FF = _req_ff()   # 见 ffmpeg_path.py（可用 HSR_FFMPEG 指定）
VID = os.path.join(ROOT, "records", "屏幕录制 2026-10-03 123200.mp4")
TMP = os.path.join(ROOT, "frames", "_audit.png")
TRUTH = os.path.join(ROOT, "out", "teams", "rec1003_by_time.json")

with np.load(T.BANK_PATH) as z:
    units = list(z.files)
print("库内 %d 个条目；忆灵条目：%s"
      % (len(units), [k for k in units if k in ("死龙", "长夜", "小伊卡", "德谬歌")]))

truth = {}
if os.path.exists(TRUTH):
    d = json.load(open(TRUTH, encoding="utf-8"))
    for nm, ts in d.get("characters", {}).items():
        for t in ts:
            truth[round(float(t), 1)] = nm

stat = defaultdict(lambda: [0, 0, 0, 0, 0])       # 帧/有结论/判对/弃权/判错
samples = defaultdict(list)
t = 0.0
while t <= 432.0:
    subprocess.run([FF, "-ss", "%.2f" % t, "-i", VID, "-frames:v", "1", "-y", TMP],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    img = cv2.imdecode(np.fromfile(TMP, dtype=np.uint8), cv2.IMREAD_COLOR)
    t0, t = t, t + 1.0
    if img is None:
        continue
    r = T.read_actor(img)
    key = "%s/%s" % (r.get("marker"), r.get("card_type"))
    st = stat[key]
    st[0] += 1
    if r.get("card_type") in ("enemy", "empty"):
        continue
    st[1] += 1
    want = truth.get(round(t0, 1))
    if r.get("unit") is None:
        st[3] += 1
        if len(samples[key]) < 5:
            samples[key].append((t0, "弃权", want, r.get("raw"), r.get("score"), r.get("margin")))
    elif want and r["unit"] != want:
        st[4] += 1
        if len(samples[key]) < 5:
            samples[key].append((t0, r["unit"], want, r.get("raw"), r.get("score"), r.get("margin")))
    else:
        st[2] += 1

print("\n%-26s %6s %6s %6s %6s %6s" % ("标记/卡类型", "帧数", "有结论", "判对", "弃权", "判错"))
for k in sorted(stat, key=lambda x: -stat[x][1]):
    a, b, c, d, e = stat[k]
    if b == 0:
        continue
    print("%-26s %6d %6d %6d %6d %6d" % (k, a, b, c, d, e))

print("\n弃权/判错样例（时刻 / 判成 / 真值 / 原始top1 / 分 / 间距）：")
for k, ss in sorted(samples.items()):
    for x in ss:
        print("  %-24s t=%-7.1f %-10s 真值=%-10s raw=%-10s %.3f %.3f"
              % (k, x[0], x[1], x[2], x[3], x[4] or 0, x[5] or 0))
try:
    os.remove(TMP)
except OSError:
    pass
