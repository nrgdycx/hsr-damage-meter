# -*- coding: utf-8 -*-
"""在指定窗口内**不限标记**地把卡框铺开，用来找被采集门槛漏掉的召唤物。

背景：harvest 只收左标记为 ally_* 的帧；召唤物的标记若不是 ally_*（或标记本身就识别不出），
它会被静默跳过。这里把窗口内每一帧的卡框都铺出来（含标记类型），由人眼定位。

用法：python tools/axis/scan_window.py 复杂情况 255 320 龙灵
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
TEAM = sys.argv[1] if len(sys.argv) > 1 else "复杂情况"
T0 = float(sys.argv[2]) if len(sys.argv) > 2 else 255.0
T1 = float(sys.argv[3]) if len(sys.argv) > 3 else 320.0
TAG = sys.argv[4] if len(sys.argv) > 4 else "window"
VID = os.path.join(ROOT, "records", sys.argv[5] if len(sys.argv) > 5 else "%s.mp4" % TEAM)
# ⚠️ 临时名必须 ASCII：ffmpeg 写不了中文路径（本项目经典坑，harvester 也是这么绕的）
TMP = os.path.join(ROOT, "frames", "_scan_%d.png" % (abs(hash(TAG)) % 100000))
CARD = (82, 78, 281, 178)

items = []
t = T0
while t <= T1:
    subprocess.run([FF, "-ss", "%.2f" % t, "-i", VID, "-frames:v", "1", "-y", TMP],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    img = cv2.imdecode(np.fromfile(TMP, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is not None:
        img, _bar = T.crop_letterbox(img)      # 与采集/识别同口径：先裁黑边
        s = img.shape[1] / float(T.REF_W)
        mk = T.marker_feat(img, s=s)[0]
        x0, y0, x1, y1 = [int(round(v * s)) for v in CARD]
        items.append((t, img[y0:y1, x0:x1], mk))
    t += 0.6

from PIL import Image, ImageDraw, ImageFont       # noqa: E402
try:
    FT = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 24)
    F = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 14)
except OSError:
    FT = F = ImageFont.load_default()

TW, TH, PER = 200, 100, 10
rows = (len(items) + PER - 1) // PER
sheet = Image.new("RGB", (20 + PER * (TW + 5), 46 + rows * (TH + 28)), (10, 10, 10))
d = ImageDraw.Draw(sheet)
d.text((16, 8), "%s  t=%.0f~%.0f：每 0.6 秒一帧（**不限标记**）——找「%s」"
       % (TEAM, T0, T1, TAG), font=FT, fill=(255, 235, 120))
for k, (t, img, mk) in enumerate(items):
    r, c = divmod(k, PER)
    x, y = 16 + c * (TW + 5), 46 + r * (TH + 28)
    big = cv2.resize(img, (TW, TH), interpolation=cv2.INTER_LANCZOS4)
    sheet.paste(Image.fromarray(cv2.cvtColor(big, cv2.COLOR_BGR2RGB)), (x, y))
    col = (200, 255, 200) if mk.startswith("ally") else (255, 200, 160)
    d.text((x + 2, y + TH + 2), "%.1f %s" % (t, mk), font=F, fill=col)
out = os.path.join(ROOT, "samples", "扫描_%s_%.0f_%.0f.png" % (TAG, T0, T1))
ok, buf = cv2.imencode(".png", np.array(sheet)[:, :, ::-1])
buf.tofile(out)
mk_cnt = {}
for _t, _i, mk in items:
    mk_cnt[mk] = mk_cnt.get(mk, 0) + 1
print("已写出 %s  %s  （%d 帧）" % (out, sheet.size, len(items)))
print("标记分布：%s" % {k: v for k, v in sorted(mk_cnt.items(), key=lambda kv: -kv[1])})
try:
    os.remove(TMP)
except OSError:
    pass
