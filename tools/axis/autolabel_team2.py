# -*- coding: utf-8 -*-
"""【线2】把录屏2 的顶端卡**自动分组**，出「指认图」让用户把每组标成 银狼/爻光/火花/真珠。

为什么要分组而不是逐帧问用户：录屏2 里同一角色会出现几十次，逐帧指认是纯浪费用户时间；
分组后用户只需回答"组1=谁、组2=谁…"（E 线当初也是先出候选再人工核对）。

聚类口径：**完全连接**（两组之间**所有**帧两两相似度都 ≥ 阈值才合并）——
录屏2 的角色卡在"卡面缩放态"上不同，所以两帧相似度取 4 种缩放组合的最大值。

用法：
  python -u axis_autolabel_L2.py --thr 0.80          # 聚类 + 出图（samples/L2_clusters_*.png）
  python -u axis_autolabel_L2.py --thr 0.80 --no-img # 只看文字摘要
"""
# [P3 整理] 原路径：axis_autolabel_L2.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import glob
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
sys.path.insert(0, HERE)

import axis_actor as T          # noqa: E402
import axis_actor_team2 as T2        # noqa: E402

SAMPLES = os.path.join(HERE, "samples")
OUT = os.path.join(HERE, "out")


def font(sz):
    for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/arial.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz)
            except OSError:
                pass
    return ImageFont.load_default()


def scan(crop_dir=T2.CROP_DIR, only="all"):
    """→ [(t, crop, 特征列表(每缩放态一个), marker)]；only 按左标记筛（all/ally/aha/enemy）"""
    items = []
    for p in sorted(glob.glob(os.path.join(crop_dir, "*_top.png"))):
        t = float(os.path.basename(p)[1:9])
        c = cv2.imread(p, cv2.IMREAD_COLOR)
        if c is None:
            continue
        try:
            mk = T2.marker_of(c)[0]
        except Exception:                              # noqa: BLE001
            mk = "?"
        if only == "ally" and not mk.startswith("ally"):
            continue
        if only in ("aha", "enemy", "empty", "elation") and not mk.startswith(only):
            continue
        fs = [T2.feats_top_zoom(c, z) for z in T.ZOOMS]
        items.append((t, c, fs, mk))
    return items


def sim_matrix(items):
    """两帧相似度 = 4 种缩放组合里 pair_score 的最大值。"""
    n = len(items)
    S = np.eye(n, dtype=np.float32)
    for i in range(n):
        for j in range(i + 1, n):
            best = max(T.pair_score(a, b) for a in items[i][2] for b in items[j][2])
            S[i, j] = S[j, i] = best
    return S


def cluster_complete(S, thr):
    """完全连接层次聚类：只合并"两组之间最小相似度 ≥ thr"的对。"""
    n = len(S)
    members = [[i] for i in range(n)]
    while len(members) > 1:
        best, pair = -9.0, None
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                m = float(S[np.ix_(members[a], members[b])].min())
                if m > best:
                    best, pair = m, (a, b)
        if best < thr:
            break
        a, b = pair
        members[a] = members[a] + members[b]
        members.pop(b)
    members.sort(key=lambda g: -len(g))
    return members


def art_of(crop):
    full = T2.as_full(crop)
    return T.top_art(full, T.scale_of(full.shape))


def draw_cell(crop, caption, scale=2.0, grid=True):
    art = art_of(crop)
    h, w = art.shape[:2]
    img = Image.fromarray(cv2.cvtColor(art, cv2.COLOR_BGR2RGB)).resize(
        (int(w * scale), int(h * scale)), Image.LANCZOS)
    pad = 26
    canvas = Image.new("RGB", (img.width, img.height + pad), (24, 24, 24))
    canvas.paste(img, (0, 0))
    d = ImageDraw.Draw(canvas)
    if grid:
        f = font(11)
        for x in range(0, w + 1, 10):
            xx = int(x * scale)
            d.line([(xx, 0), (xx, img.height)], fill=(90, 90, 90) if x % 50 else (150, 150, 150))
            if x % 50 == 0:
                d.text((xx + 2, 2), str(x), font=f, fill=(230, 230, 230))
        for y in range(0, h + 1, 10):
            yy = int(y * scale)
            d.line([(0, yy), (img.width, yy)], fill=(90, 90, 90) if y % 50 else (150, 150, 150))
            if y % 50 == 0:
                d.text((2, yy + 1), str(y), font=f, fill=(230, 230, 230))
    d.text((3, img.height + 5), caption, font=font(15), fill=(255, 255, 255))
    return canvas


def sheet(entries, path, title, cols=3, scale=2.0):
    cells = [draw_cell(c, cap, scale) for c, cap in entries]
    if not cells:
        return None
    cw = max(c.width for c in cells) + 8
    ch = max(c.height for c in cells) + 8
    rows = (len(cells) + cols - 1) // cols
    head = 34
    W = cols * cw
    H = head + rows * ch
    canvas = Image.new("RGB", (W, H), (10, 10, 10))
    d = ImageDraw.Draw(canvas)
    d.text((6, 6), title, font=font(20), fill=(255, 235, 120))
    for i, c in enumerate(cells):
        r, col = divmod(i, cols)
        canvas.paste(c, (col * cw + 4, head + r * ch + 4))
    canvas.save(path)
    print("  图已写出 %s（%dx%d）" % (path, W, H))
    return path


def members_sheet(reps, path, title, per_row=4, scale=1.25, groups_per_page=6):
    """每个组一行：组号 + 若干成员帧（含"最不像"的那几个）——让用户能认出这组是谁。

    为什么给多个成员：同一角色在录屏2 里会因**光照/特效/卡面缩放**看起来不同，
    只给一张代表图，用户可能把"同一个人的两种光照"当成两个人。
    """
    pages = []
    for start in range(0, len(reps), groups_per_page):
        chunk = reps[start:start + groups_per_page]
        rows = []
        for r in chunk:
            tiles = []
            # 代表 + 组内最不像的 3 个（顺便暴露"这组其实混了两个人"）
            order = [r["rep"]] + [t for t in r.get("dissimilar", [])][:per_row - 1]
            caps = ["组%d 例 t=%s" % (r["gid"], T.fmt_t(order[0]))] + \
                   ["t=%s" % T.fmt_t(t) for t in order[1:]]
            for t, cap in zip(order, caps):
                p = os.path.join(T2.CROP_DIR, "t%08.2f_top.png" % t)
                img = cv2.imread(p, cv2.IMREAD_COLOR)
                if img is None:
                    continue
                pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)).resize(
                    (int(img.shape[1] * scale), int(img.shape[0] * scale)), Image.LANCZOS)
                pad = 24
                cell = Image.new("RGB", (pil.width, pil.height + pad), (24, 24, 24))
                cell.paste(pil, (0, 0))
                ImageDraw.Draw(cell).text((3, pil.height + 4), cap, font=font(14),
                                          fill=(255, 255, 255))
                tiles.append(cell)
            if tiles:
                rows.append((r, tiles))
        if not rows:
            continue
        cw = max(t.width for _, ts in rows for t in ts) + 6
        rh = max(t.height for _, ts in rows for t in ts) + 6
        W = max(sum(t.width + 6 for t in ts) + 150 for _, ts in rows)
        head = 30
        canvas = Image.new("RGB", (W, head + len(rows) * rh), (10, 10, 10))
        d = ImageDraw.Draw(canvas)
        d.text((6, 5), title + ("（第 %d 批）" % (len(pages) + 1)),
               font=font(19), fill=(255, 235, 120))
        for i, (r, ts) in enumerate(rows):
            x = 130
            for t in ts:
                canvas.paste(t, (x, head + i * rh + 3))
                x += t.width + 6
            d.text((6, head + i * rh + 20),
                   "组%d\nn=%d" % (r["gid"], r["n"]), font=font(18), fill=(120, 230, 255))
        out = path if len(reps) <= groups_per_page else path.replace(".png", "_p%d.png" % (len(pages) + 1))
        canvas.save(out)
        print("  成员图已写出 %s（%dx%d）" % (out, canvas.width, canvas.height))
        pages.append(out)
    return pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=T2.CROP_DIR)
    ap.add_argument("--thr", type=float, default=0.80)
    ap.add_argument("--cols", type=int, default=3)
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--max-clusters", type=int, default=12)
    ap.add_argument("--only", default="all", choices=["all", "ally", "aha", "enemy", "empty", "elation"],
                    help="只聚类某一类左标记的帧（找队伍 4 人用 ally）")
    ap.add_argument("--sweep", default="", help="扫多个阈值，如 0.8,0.9,1.0,1.1，只报分组数与大小")
    ap.add_argument("--no-img", action="store_true")
    args = ap.parse_args()

    items = scan(args.dir, args.only)
    if not items:
        raise SystemExit("没有找到小块：先跑 `python axis_extract_team2.py --step 1 --start 0 --end 380`")
    print("扫到 %d 帧（%s，筛选=%s）" % (len(items), args.dir, args.only))
    S = sim_matrix(items)
    if args.sweep:
        for thr in [float(x) for x in args.sweep.split(",") if x.strip()]:
            gs = cluster_complete(S, thr)
            print("  阈值 %.2f → %2d 组：%s" % (thr, len(gs), [len(g) for g in gs]))
        return 0
    groups = cluster_complete(S, args.thr)

    lines = ["聚类：阈值 %.2f，共 %d 组（%d 帧）" % (args.thr, len(groups), len(items))]
    reps = []
    for gi, g in enumerate(groups):
        ts = [items[i][0] for i in g]
        mks = {}
        for i in g:
            mks[items[i][3]] = mks.get(items[i][3], 0) + 1
        # 代表 = 与组内其他帧平均相似度最高者；最不像的成员 = 平均相似度最低者
        if len(g) == 1:                       # 单帧组：没有组内相似度可言
            rep_i = worst_i = g[0]
            rep_sim = worst_sim = -1.0
            dissimilar = []
        else:
            sub = S[np.ix_(g, g)].copy()
            np.fill_diagonal(sub, np.nan)
            avg = np.nanmean(sub, axis=1)
            rep_i = g[int(np.nanargmax(avg))]
            worst_i = g[int(np.nanargmin(avg))]
            rep_sim = float(np.nanmax(avg))
            worst_sim = float(np.nanmin(avg))
            # 最不像代表的几个成员（暴露"这组混了两个人"）
            diss = [g[k] for k in np.argsort(avg)[:4]]
            dissimilar = [items[k][0] for k in diss if items[k][0] != items[rep_i][0]][:3]
        lines.append("  组%-2d n=%-4d 例 t=%-7s 标记=%-22s 组内最差成员 t=%-7s（与组内相似度 %.2f）"
                     % (gi + 1, len(ts), T.fmt_t(items[rep_i][0]), str(mks),
                        T.fmt_t(items[worst_i][0]), worst_sim))
        lines.append("        帧号：%s" % ", ".join(T.fmt_t(x) for x in sorted(ts)))
        reps.append({"gid": gi + 1, "n": len(ts), "times": sorted(ts), "markers": mks,
                     "rep": items[rep_i][0], "worst": items[worst_i][0],
                     "worst_sim": round(worst_sim, 3), "rep_sim": round(rep_sim, 3),
                     "dissimilar": dissimilar,
                     "crop": items[rep_i][1], "worst_crop": items[worst_i][1]})
    txt = "\n".join(lines)
    print(txt)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "L2_clusters.txt"), "w", encoding="utf-8") as f:
        f.write(txt + "\n")
    with open(os.path.join(OUT, "axis_clusters_L2.json"), "w", encoding="utf-8") as f:
        json.dump([{k: v for k, v in r.items() if not k.endswith("crop")} for r in reps],
                  f, ensure_ascii=False, indent=1)

    if not args.no_img:
        os.makedirs(SAMPLES, exist_ok=True)
        top = reps[:args.max_clusters]
        sheet([(r["crop"], "组%d  n=%d  例 t=%s" % (r["gid"], r["n"], T.fmt_t(r["rep"])))
               for r in top],
              os.path.join(SAMPLES, "L2_clusters_top.png"),
              "录屏2 顶端卡自动分组（阈值 %.2f）——请逐组指认：银狼 / 爻光 / 火花 / 真珠 / 其它" % args.thr,
              args.cols, args.scale)
        sheet([(r["worst_crop"], "组%d 最不像成员 t=%s（相似度%.2f）" % (r["gid"], T.fmt_t(r["worst"]), r["worst_sim"]))
               for r in top],
              os.path.join(SAMPLES, "L2_clusters_worst.png"),
              "每组「最不像成员」——用来发现某组其实混了两个角色（若这格看着像另一个角色，请告知）",
              args.cols, args.scale)
        members_sheet(reps, os.path.join(SAMPLES, "L2_members.png"),
                      "逐组核对：每组给出代表 + 组内最不像的几个成员（%s，阈值 %.2f）"
                      % (args.only, args.thr))
    return 0


if __name__ == "__main__":
    sys.exit(main())
