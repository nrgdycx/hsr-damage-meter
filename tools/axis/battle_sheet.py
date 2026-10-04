# -*- coding: utf-8 -*-
"""录屏采集到的卡面 → **按战斗场次**出指认表。

什么时候用它
------------
`harvest_characters.py` 走的是"按角色名分栏"，只有当卡面能与共享模板库对上
（实测分数 ≥1.45）时才有意义。若整段录屏都是**库里没有的新角色**（对库最高分
远低于 1.45），会出现两个问题：
  1. 输出的名字全是"最像谁"的误报；
  2. 跨战斗的自动归并不可靠 —— 行动卡是**动画元素**（滑入/放大），
     同一个人的卡会落在不同像素位置/缩放/背景下，实测同一个人跨战斗只有
     1.0~1.5 分，而"不同的人"能到 0.9~1.0，**两带重叠**（见交付文档 §13.4）。
但**同一场战斗内**同一个人的卡几乎相同（组内最低分中位 1.58~1.87），所以
"一场战斗 → 这一场里有几个稳定长相"是可靠的。这张表就是给用户按场次报名字用的。

用法
----
    python tools/axis/battle_sheet.py --team 我的队
    python tools/axis/battle_sheet.py --team 我的队 --hints "15=乱破,270=藿藿"

读 `frames/harvest_<队名>/cards/t%08.2f.png`（`harvest_characters.py` 的产物），
写 `samples/<队名>_按场次指认.png`。
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import axis_actor as T                      # noqa: E402
from harvest_characters import (art_of_card, feat_fft,   # noqa: E402
                                pair_score_shift, SHIFT_R)

ZOOM = 1.08
ZOOM_PEN = 0.03


def imread_u(p):
    try:
        return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
    except OSError:
        return None


def imwrite_u(p, img):
    ok, buf = cv2.imencode(".png", img)
    if ok:
        buf.tofile(p)


def zoom_art(art, z):
    """与 `axis_actor.feats_art` 的缩放逻辑逐字一致（放大后中心裁回原尺寸）。"""
    h, w = art.shape[:2]
    r = cv2.resize(art, (max(2, int(round(w * z))), max(2, int(round(h * z)))),
                   interpolation=cv2.INTER_AREA if z < 1 else cv2.INTER_LINEAR)
    if r.shape[0] >= h and r.shape[1] >= w:
        y0, x0 = (r.shape[0] - h) // 2, (r.shape[1] - w) // 2
        return r[y0:y0 + h, x0:x0 + w]
    return cv2.copyMakeBorder(r, 0, max(0, h - r.shape[0]), 0, max(0, w - r.shape[1]),
                              cv2.BORDER_REPLICATE)


def load_feats(cards_dir):
    """读卡 → (时刻, 特征1, 特征2, 文件名)。特征2 是放大态补偿用的。"""
    files = sorted(f for f in os.listdir(cards_dir) if f.endswith(".png"))
    ts, F1, F2, names = [], [], [], []
    for f in files:
        c = imread_u(os.path.join(cards_dir, f))
        if c is None:
            continue
        a = art_of_card(c)
        if a.size == 0:
            continue
        ts.append(float(f[1:9]))
        F1.append(T.feats(a))
        F2.append(T.feats(zoom_art(a, ZOOM)))
        names.append(f)
    return np.asarray(ts), F1, F2, names


def sim_matrix(F1, F2, cache=None):
    """相似度矩阵：**位移容忍**打分，取"原态/放大态"里的最好那个。

    ⚠️ 位移容忍是必须的：实测行动卡的**边框固定、框内头像会位移**
    （见 harvest_characters.SHIFT_R 的注释），位置敏感的点积会把同一个人拆成多组。

    `cache` 给了就把矩阵存/取到那个 npy（矩阵与 --gap/--cluster/--min 无关，
    所以改这几个参数重跑时能省掉 1~2 分钟）。
    """
    n = len(F1)
    if cache and os.path.exists(cache):
        M = np.load(cache)
        if M.shape == (n, n):
            print("  复用已算好的相似度矩阵 %s" % cache)
            return M
        print("  缓存的矩阵尺寸 %s 与当前 %d 张卡不符，重算" % (M.shape, n))
    FF1 = [feat_fft(f) for f in F1]
    FF2 = [feat_fft(f) for f in F2]
    M = np.eye(n, dtype=np.float32)
    for i in range(n):
        for j in range(i + 1, n):
            v = max(pair_score_shift(FF1[i], FF1[j]),
                    pair_score_shift(FF1[i], FF2[j]) - ZOOM_PEN,
                    pair_score_shift(FF2[i], FF1[j]) - ZOOM_PEN,
                    pair_score_shift(FF2[i], FF2[j]))
            M[i, j] = M[j, i] = v
        if (i + 1) % 200 == 0:
            print("    相似度 %d/%d" % (i + 1, n), flush=True)
    if cache:
        np.save(cache, M)
        print("  已缓存相似度矩阵 %s" % cache)
    return M


def segments(ts, gap):
    order = np.argsort(ts)
    segs, cur = [], [order[0]]
    for k in order[1:]:
        if ts[k] - ts[cur[-1]] > gap:
            segs.append(cur)
            cur = []
        cur.append(k)
    segs.append(cur)
    return segs


def cluster_within(seg, M, thr):
    """段内聚类：**全链**（要与组内**每个**成员都 ≥thr 才并入）。

    ⚠️ 不能用"单链"（只要跟**代表**够像就并）：实测第 7 场（t=511~534）里，
    单链把两个不同的人并成了一格 —— 该格内部最低分只有 **0.65**，而用户一眼就发现
    "少了个人"。全链会宁可多出一格（用户说一句"同上"即可），也不会**偷偷吞掉一个人**；
    对本项目的铁律（宁可漏不要错）来说，这个方向的错误代价小得多。
    """
    sub = M[np.ix_(seg, seg)]
    order = np.argsort(-sub.mean(axis=1))
    groups = []                       # 每组：段内下标列表
    for i in order:
        best, bj = -9.0, -1
        for j, g in enumerate(groups):
            sc = sub[i, g]
            if float(sc.min()) >= thr and float(sc.mean()) > best:
                best, bj = float(sc.mean()), j
        if bj >= 0:
            groups[bj].append(i)
        else:
            groups.append([i])
    assign = np.full(len(seg), -1)
    for j, g in enumerate(groups):
        for i in g:
            assign[i] = j
    g = {}
    for i, x in enumerate(assign):
        g.setdefault(x, []).append(seg[i])
    return list(g.values())


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(description="按战斗场次出卡面指认表")
    ap.add_argument("--team", required=True)
    ap.add_argument("--cards", default=None, help="默认 frames/harvest_<队名>/cards")
    # ⚠️ 这两个默认值都是**用户真值校出来的**（2026-10-03 第三段录屏 164043）：
    #   gap=6 会把**同一场战斗**（中间有停顿/阶段切换）切成两场 ——
    #     实测 t=433~459 与 t=466~469 被切开，用户指出"是一场"；
    #   min=5 会把**只出手几次**的角色整格丢掉 ——
    #     实测第十场云璃只有 4 张卡，被滤掉后用户一眼看出"少了一个云璃"。
    ap.add_argument("--gap", type=float, default=12.0,
                    help="超过这个间隔算换场（秒）；默认 12（6 会把有停顿的同一场切开）")
    ap.add_argument("--cluster", type=float, default=1.30, help="场次内同人阈值")
    ap.add_argument("--min", type=int, default=3,
                    help="只列 >=N 张的长相（默认 3；5 会丢掉出手次数少的角色）")
    ap.add_argument("--hints", default="", help='编队界面读到的名字，如 "15=乱破,270=藿藿"')
    ap.add_argument("--names", default=None,
                    help="已指认的 json（如 out/teams/rec1640_by_time.json）→ 把名字印在对应格上")
    args = ap.parse_args(argv)

    cdir = args.cards or os.path.join(ROOT, "frames", "harvest_%s" % args.team, "cards")
    if not os.path.isdir(cdir):
        raise SystemExit("找不到卡面目录：%s" % cdir)
    ts, F1, F2, names = load_feats(cdir)
    print("卡面 %d 张（来自 %s）" % (len(ts), cdir))
    cache = os.path.join(ROOT, "frames", "_bsheet_M_%s.npy" % args.team)
    M = sim_matrix(F1, F2, cache=cache)

    hints = []
    for kv in args.hints.split(","):
        if "=" in kv:
            a, b = kv.split("=", 1)
            try:
                hints.append((float(a), b.strip()))
            except ValueError:
                pass

    # 已指认的名字：从 rec*.json 读 [{name, id, t, n}]，按时刻贴到格上
    known = []
    if args.names and os.path.exists(args.names):
        with open(args.names, encoding="utf-8-sig") as f:   # 容忍 BOM（Windows 编辑器常加）
            nd = json.load(f)
        for b in nd.get("battles", []):
            for it in b.get("identities", []):
                nm, _cid, t, _n = it
                known.append((float(t), nm))
        known.sort()
        print("  已读入 %d 个已指认的名字（%s）" % (len(known), args.names))

    def name_of(t):
        best = None
        for tt, nm in known:
            dd = abs(tt - t)
            if dd <= 6.0 and (best is None or dd < best[0]):
                best = (dd, nm)
        return best[1] if best else ""

    segs = [s for s in segments(ts, args.gap) if len(s) >= 4]
    rows = []
    frags = []            # 被 --min 门槛滤掉的卡：(场次, 时刻, 文件名)
    for si, seg in enumerate(segs):
        allg = cluster_within(seg, M, args.cluster)
        items = [v for v in sorted(allg, key=lambda v: ts[min(v)]) if len(v) >= args.min]
        # ⚠️ 碎片**必须也铺出来**：用户实测就栽在这 —— 他只看到"另有 N 张碎片"
        #    这个数字却看不到内容，于是问"为什么少了一个人"；
        #    少的那个人（姬子·启行，t=140.8）当时就躺在碎片里。
        for v in allg:
            if len(v) < args.min:
                for i in v:
                    frags.append((si + 1, ts[i], names[i]))
        if not items:
            continue
        dropped = sorted((len(v) for v in allg if len(v) < args.min), reverse=True)
        rows.append((si + 1, ts[min(seg)], ts[max(seg)], len(seg), items, dropped))

    from PIL import Image, ImageDraw, ImageFont
    try:
        F = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 15)
        FB = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 19)
        FH = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 25)
    except OSError:
        F = FB = FH = ImageFont.load_default()

    tw, th, colw, maxcols = 170, 86, 176, 12
    W = 8 + 190 + maxcols * colw
    H = 96 + sum((th + 44) + (0 if len(it) <= maxcols else
                              ((len(it) - 1) // maxcols) * (th + 22)) for *_, it, _dr in rows) + 20
    frow = ((len(frags) + maxcols - 1) // maxcols) if frags else 0
    H += (frow * (th + 22) + 60) if frags else 0
    sheet = Image.new("RGB", (W, H), (10, 10, 10))
    d = ImageDraw.Draw(sheet)
    d.text((8, 6), "%s 按战斗场次指认表 —— 每格一张卡的代表，标了秒数" % args.team,
           font=FH, fill=(255, 235, 120))
    tip = ("名字已按指认印在卡片上（--names）；每格下方是 t=秒数 × 张数" if known else
           "只列每场成规模的长相（≥%d 张）。请按场次报名字，例：「第1场 t=54 = XXX」" % args.min)
    d.text((8, 40), tip, font=F, fill=(210, 210, 210))
    y = 70
    for si, t0, t1, nc, items, dropped in rows:
        lab = "第 %d 场\nt=%.0f~%.0f\n%d 张卡" % (si, t0, t1, nc)
        if dropped:
            lab += "\n（另有 %d 张碎片：%s）" % (sum(dropped),
                                          ",".join(str(d) for d in dropped[:4]))
        h = None
        for pt, nm in hints:
            if pt <= t0 + 5 and (h is None or pt > h[0]):
                h = (pt, nm)
        if h:
            lab += "\n编队界面(%d):\n%s" % h
        d.text((8, y + 8), lab, font=FB, fill=(150, 245, 170))
        for k, v in enumerate(items):
            r, c = divmod(k, maxcols)
            x, yy = 190 + c * colw, y + r * (th + 22)
            card = imread_u(os.path.join(cdir, names[v[0]]))
            if card is not None:
                big = cv2.resize(card, (tw, th), interpolation=cv2.INTER_LANCZOS4)
                sheet.paste(Image.fromarray(cv2.cvtColor(big, cv2.COLOR_BGR2RGB)), (x, yy))
            nm = name_of(ts[v[0]])
            if nm:
                # 名字印在卡片**内部下方**：画在卡片上方会压到上一场的标签
                d.rectangle([x, yy + th - 24, x + tw, yy + th], fill=(16, 60, 26))
                d.text((x + 4, yy + th - 22), nm, font=FB, fill=(180, 255, 200))
            d.text((x + 2, yy + th + 1), "t=%.0f×%d" % (ts[v[0]], len(v)), font=F,
                   fill=(200, 210, 255))
        y += (th + 44) + (0 if len(items) <= maxcols else
                          ((len(items) - 1) // maxcols) * (th + 22))

    if frags:
        y += 14
        d.text((8, y), "碎片（每场不足 %d 张的卡，上面各格里没有它们；请一并过一眼）" % args.min,
               font=FB, fill=(255, 190, 120))
        y += 28
        for k, (bn, t, fn) in enumerate(sorted(frags, key=lambda x: x[1])):
            r, c = divmod(k, maxcols)
            x, yy = 8 + c * colw, y + r * (th + 22)
            card = imread_u(os.path.join(cdir, fn))
            if card is not None:
                big = cv2.resize(card, (tw, th), interpolation=cv2.INTER_LANCZOS4)
                sheet.paste(Image.fromarray(cv2.cvtColor(big, cv2.COLOR_BGR2RGB)), (x, yy))
            d.text((x + 2, yy + th + 1), "第%d场 t=%.0f" % (bn, t), font=F, fill=(230, 200, 160))

    out = os.path.join(ROOT, "samples", "%s_按场次指认.png" % args.team)
    imwrite_u(out, np.array(sheet)[:, :, ::-1])
    print("已写出 %s  %s" % (out, sheet.size))
    for si, t0, t1, nc, items, dropped in rows:
        print("第%2d场 t=%5.0f~%5.0f 卡%3d → %d 格%s： %s"
              % (si, t0, t1, nc, len(items),
                 ("（碎片 %s）" % ",".join(str(d) for d in dropped)) if dropped else "",
                 " ".join("t=%.0f(×%d)" % (ts[v[0]], len(v)) for v in items)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
