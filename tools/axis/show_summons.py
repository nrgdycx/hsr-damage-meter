# -*- coding: utf-8 -*-
"""这轮认出的**召唤物/忆灵**一览：每个一行，放它自己的卡面样本。

来源：复杂情况_by_time.json 的 identities + fragments（用户逐格指认）。
选卡方式：以指认时刻为参考，扫该窗口内"与参考卡同一个人"（位移容忍分 ≥1.5）的卡。
"""
import io
import json
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "axis"))
import axis_actor as T      # noqa: E402
from harvest_characters import art_of_card, feat_fft, pair_score_shift   # noqa: E402

CDIR = os.path.join(ROOT, "frames", "harvest_复杂情况", "cards")
FILES = sorted(f for f in os.listdir(CDIR) if f.endswith(".png"))
TS = [float(f[1:9]) for f in FILES]
CACHE = {}


def imread_u(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def fft_of(k):
    if k not in CACHE:
        CACHE[k] = feat_fft(T.feats(art_of_card(imread_u(os.path.join(CDIR, FILES[k])))))
    return CACHE[k]


# 所有队伍的归属明细 → {条目: [(队伍, 时刻), ...]}；每队一个采集目录
ASSIGN, CARDS_OF = {}, {}
for tname in ("复杂情况", "补充2"):
    fp = os.path.join(ROOT, "out", "teams", "%s_assign.json" % tname)
    if not os.path.exists(fp):
        continue
    for u, ts_ in json.load(io.open(fp, encoding="utf-8"))["units"].items():
        ASSIGN.setdefault(u, []).extend([(tname, t) for t in ts_])
    CARDS_OF[tname] = os.path.join(ROOT, "frames", "harvest_%s" % tname, "cards")


def samples(unit, n=6):
    """按**建库时的真实归属**取这个条目的卡（不再靠"离某个时刻最近"猜 —— 那会把
    托帕的卡当成账账的，实测踩过）。"""
    times = ASSIGN.get(unit, [])
    if not times:
        return []
    step = max(1, len(times) / float(n))
    pick = [times[int(i * step)] for i in range(min(n, len(times)))]
    out = []
    for team, t in pick:
        cd = CARDS_OF[team]
        fs = sorted(f for f in os.listdir(cd) if f.endswith(".png"))
        k = int(np.argmin([abs(float(f[1:9]) - t) for f in fs]))
        out.append((float(fs[k][1:9]), imread_u(os.path.join(cd, fs[k]))))
    return out


SUMMONS = [
    ("神君", "景元的召唤物", None, 8),
    ("账账", "托帕的召唤物（含强化形态，亮一点）", None, 10),
    ("迷迷", "记忆主（开拓者·记忆）的忆灵", None, 29),
    ("衣匠", "阿格莱雅的忆灵", None, 2),
    ("晴空乐手", "知更鸟·晴歌的忆灵（官方名；共 3 个：贝茜/啾米/派丁）", None, 1),
    ("拓星者", "姬子·启行的助战技（可看作召唤物）", None, 5),
    ("龙灵", "丹恒•腾荒（盾丹）的召唤物 —— 金龙", None, 5),
    ("浮元", "灵砂的召唤物 —— 粉色兔子（补充2）", None, 11),
]

from PIL import Image, ImageDraw, ImageFont       # noqa: E402
try:
    FT = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 28)
    FB = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 20)
    F = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 15)
except OSError:
    FT = FB = F = ImageFont.load_default()

TW, TH, PER, GAP = 230, 115, 6, 8
rows = []
for name, owner, trefs, ntpl in SUMMONS:
    cards = samples(name)
    # 去重（同一时刻只留一张）
    seen, uniq = set(), []
    for t, im in cards:
        if round(t, 1) in seen:
            continue
        seen.add(round(t, 1))
        uniq.append((t, im))
    rows.append((name, owner, uniq[:PER], ntpl))

W = 24 + PER * (TW + GAP)
H = 64 + sum(48 + TH + 26 for _r in rows) + 70
sheet = Image.new("RGB", (W, H), (10, 10, 10))
d = ImageDraw.Draw(sheet)
d.text((16, 8), "这轮认出的召唤物 / 忆灵（库里已入库，按「属于谁」记归属）", font=FT,
       fill=(255, 235, 120))
y = 52
for name, owner, cards, ntpl in rows:
    d.text((16, y), "%s  —— %s    （库内 %d 张模板）" % (name, owner, ntpl), font=FB,
           fill=(150, 245, 170))
    y += 30
    x = 16
    for t, im in cards:
        if im is not None:
            big = cv2.resize(im, (TW, TH), interpolation=cv2.INTER_LANCZOS4)
            sheet.paste(Image.fromarray(cv2.cvtColor(big, cv2.COLOR_BGR2RGB)), (x, y))
        d.text((x + 2, y + TH + 2), "t=%.1f" % t, font=F, fill=(215, 215, 215))
        x += TW + GAP
    y += TH + 26
d.text((16, y + 6), "另有更早（录屏1）入库的 4 个忆灵：死龙(遐蝶) 32 张 / 长夜(长夜月) 22 张 / "
                    "小伊卡(风堇) 32 张 / 德谬歌(昔涟) 4 张 —— 源图不在工作区，未附图",
       font=FB, fill=(255, 200, 150))
out = os.path.join(ROOT, "samples", "召唤物一览.png")
ok, buf = cv2.imencode(".png", np.array(sheet)[:, :, ::-1])
buf.tofile(out)
print("已写出", out, sheet.size)
for name, owner, cards, ntpl in rows:
    print("  %-8s %-28s 样本 %d 张（模板 %d）" % (name, owner, len(cards), ntpl))
