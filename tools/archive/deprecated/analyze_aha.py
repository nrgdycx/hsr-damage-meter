# -*- coding: utf-8 -*-
"""【线2】用「阿哈时刻里各成员的欢愉技结算值」反推**欢愉度的相对关系**。

原理（见 `docs/录屏2欢愉队.md` §7.9）：
    欢愉伤害 = 7535.107 × 倍率 × [1+5×好活/(好活+240)] × (1+欢愉度) × (1+增笑) × 暴击 × 防御 × 抗性 × …
同一个阿哈时刻内，`好活/增笑/防御/抗性/易伤/减伤` 对四个人**完全相同** → 约掉：

    甲伤害 / 乙伤害 ≈ (甲倍率 × (1+甲欢愉度)) / (乙倍率 × (1+乙欢愉度))

于是：**同段内两个成员的结算值 + 台账倍率 → 直接给出 (1+欢愉度) 之比**，不需要面板数值。

本脚本做三件事：
  1. 从密帧（0.2s）里读 HUD，按"**稳定段**"挑出结算值（防碎片：位数、量级、连续性）；
  2. 同一时刻用顶端卡的**头像**认出这段是哪个成员在放欢愉技（阿哈卡的头像区可被单位库匹配）；
  3. 输出每个成员的观测值 + 两两比值 → 推断 (1+欢愉度) 之比。

用法：
  python -u analyze_L2_aha.py                # 报告 + out/L2_aha.json
  python -u analyze_L2_aha.py --dump         # 连每帧明细一起打印（诊断用）
"""
# [P3 整理] 原路径：analyze_L2_aha.py（已移入 tools/，功能见 tools/README.md）
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

import numpy as np

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
sys.path.insert(0, HERE)

import axis_actor as T          # noqa: E402
import axis_actor_team2 as T2        # noqa: E402
import hud_read_team2 as H        # noqa: E402

# 阿哈时段（1fps 的 card_type=aha 聚合，见 out/axis_actors_L2.csv）
AHA_SEGS = [(20, 33), (63, 78), (106, 119), (159, 192), (217, 230), (288, 321), (334, 341)]

# 四个人**欢愉技**的合计倍率（满级，来自 out/skills_L2.json / 台账）
#   火花 150120：群攻 0.625% + 20 次 ×0.3125%      → 0.625 + 20×0.3125 = 6.875
#   爻光 150220：群攻 1.25%  + 5 次 ×0.25%          → 1.25  + 5×0.25   = 2.5
#   银狼 150621：6 次 ×1.125%                       → 6.75
#   真珠 150320：不直接出伤（给全队下一次攻击 +0.5%）→ 无独立结算值
ELATION_MULT = {"火花": 6.875, "爻光": 2.5, "银狼": 6.75}
PEARL_NOTE = "真珠的欢愉技（150320）本身不出伤，是给全队下一次攻击 +0.5% —— 不会出现在阿哈结算里"

# 阿哈卡上的**成员头像框**（绝对坐标；左边是皇冠+数字，右边那条是队列里的下一位，都要排除）
AHA_ART = (152, 70, 248, 182)

# 防碎片参数
MIN_DIGITS = 4          # 结算值至少 4 位（实测 5~7 位；碎片常见 1~2 位）
MIN_FRAC_OF_MEDIAN = 0.2   # 量级太离谱的直接丢
SPAN_GAP = 0.45         # 允许中间缺 1~2 帧（0.2s/帧）
SPAN_MIN_FRAMES = 3     # 稳定段至少 3 帧 = 0.6s


def aha_feats(crop):
    """阿哈卡上的**成员头像**特征（用 AHA_ART 框，而不是单位卡的 TOP_ART 框）。

    为什么单独一个框：阿哈卡左半是"皇冠+数字"、右边那条是队列里的下一位，
    真正的成员头像在中间（实测 x≈152~248、y≈70~182）。拿单位卡的框去套，
    会把数字与队列一起卷进特征 → 分数虚低、间距极小（实测 火花 0.53 / 间距 0.04）。
    """
    full = T2.as_full(crop)
    s = T.scale_of(full.shape)
    x0, y0, x1, y1 = [int(round(v * s)) for v in AHA_ART]
    return T.feats(full[y0:y1, x0:x1])


def aha_patch(crop):
    """裁出阿哈卡的成员头像（出图用）。"""
    import cv2
    full = T2.as_full(crop)
    s = T.scale_of(full.shape)
    x0, y0, x1, y1 = [int(round(v * s)) for v in AHA_ART]
    return cv2.cvtColor(full[y0:y1, x0:x1], cv2.COLOR_BGR2RGB)


def cluster_aha(frames, thr=0.80):
    """把阿哈段所有密帧的头像特征**完全连接聚类**。返回 (items, groups)。"""
    items = []
    for t in sorted(frames):
        if not in_aha(t):
            continue
        crop = T2.load_crop(frames[t][1])
        items.append((t, crop, aha_feats(crop)))
    n = len(items)
    if n < 4:
        return items, []
    W = T.W_GRAY + T.W_GRAD + T.W_COLOR
    S = np.eye(n, dtype=np.float32)
    for i in range(n):
        for j in range(i + 1, n):
            S[i, j] = S[j, i] = float(W * (items[i][2] * items[j][2]).mean())
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
    return items, members


def aha_sheet(items, members, path="samples/L2_aha_portraits.png", scale=1.4, per_group=4):
    """每个聚类组出一行图（代表 + 几个成员），供人工认脸定标。"""
    from PIL import Image, ImageDraw, ImageFont

    def font(sz):
        for p in ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/arialbd.ttf"):
            try:
                return ImageFont.truetype(p, sz)
            except OSError:
                pass
        return ImageFont.load_default()

    rows = []
    for gi, g in enumerate(members):
        ts = [items[i][0] for i in g]
        show = ts[:per_group]
        row = []
        for t in show:
            pil = Image.fromarray(aha_patch(T2.load_crop(t)))
            pil = pil.resize((int(pil.width * scale), int(pil.height * scale)), Image.LANCZOS)
            cell = Image.new("RGB", (pil.width, pil.height + 20), (20, 20, 20))
            cell.paste(pil, (0, 0))
            ImageDraw.Draw(cell).text((3, pil.height + 2), "t=%s" % T.fmt_t(t), font=font(13),
                                      fill=(255, 235, 120))
            row.append(cell)
        if row:
            rows.append((gi + 1, len(ts), row))
    if not rows:
        return None
    cw = max(sum(cell.width + 6 for cell in row) + 120 for _, _, row in rows)
    rh = max(cell.height for _, _, row in rows for cell in row) + 8
    sheet = Image.new("RGB", (cw, 30 + len(rows) * rh), (10, 10, 10))
    d = ImageDraw.Draw(sheet)
    d.text((6, 6), "【线2】阿哈卡成员头像聚类 —— 请对每组说：银狼 / 爻光 / 火花 / 真珠 / 看不清",
           font=font(18), fill=(255, 235, 120))
    for i, (gid, n, row) in enumerate(rows):
        d.text((6, 34 + i * rh + 20), "组%d\nn=%d" % (gid, n), font=font(16), fill=(120, 230, 255))
        x = 110
        for c in row:
            sheet.paste(c, (x, 30 + i * rh))
            x += c.width + 6
    sheet.save(path)
    print("已写出 %s（%dx%d，共 %d 组）" % (path, sheet.width, sheet.height, len(rows)))
    return path


def dense_frames():
    """→ {t: (hud_path, top_path)}"""
    out = {}
    for p in glob.glob(os.path.join(T2.CROP_DIR, "*_hud.png")):
        t = float(os.path.basename(p)[1:9])
        top = p.replace("_hud.png", "_top.png")
        if os.path.exists(top):
            out[t] = (p, top)
    return out


def in_aha(t):
    return any(a - 0.5 <= t <= b + 0.5 for a, b in AHA_SEGS)


def read_all(frames, model, model_pixel, portrait_of=None):
    rows = []
    portrait_of = portrait_of or {}
    for t in sorted(frames):
        if not in_aha(t):
            continue
        hud_p, top_p = frames[t]
        r = H.read_crop_dual(hud_p, model=model, model_pixel=model_pixel)
        text = r["text"] if r["verdict"] == "ok" else ""
        crop = T2.load_crop(top_p)
        # 头像身份：优先用**人工认脸定标过的聚类标签**（rel=round(t,2)），
        # 没有标签时才退回"用单位库直接匹配"（实测间距小，仅作参考）
        unit, score, second = portrait_of.get(round(t, 2)), None, None
        if unit is None:
            sc = T2.match(T2.load_bank(), crop)
            rank = sorted(sc.items(), key=lambda kv: -kv[1][0])
            score, second = rank[0][1][0], (rank[1][1][0] if len(rank) > 1 else -9)
            unit = rank[0][0] if score - second >= 0.20 else None
        mk = T2.marker_of(crop)[0]
        rows.append({"t": round(t, 2), "text": text, "verdict": r["verdict"],
                     "font": r["font"], "portrait": unit, "pscore": score,
                     "psecond": second, "marker": mk})
    return rows


def stable_spans(rows):
    """把逐帧读数切成"稳定段"（同一串数字连续出现 ≥0.6s），并做防碎片过滤。"""
    vals = [r for r in rows if r["text"]]
    if not vals:
        return []
    med = float(np.median([len(r["text"]) for r in vals]))
    spans = []
    cur = None
    for r in vals:
        if len(r["text"]) < MIN_DIGITS:
            continue                     # 碎片（1~3 位）直接丢
        if cur and r["text"] == cur["text"] and r["t"] - cur["t1"] <= SPAN_GAP:
            cur["t1"] = r["t"]
            cur["n"] += 1
            cur["portraits"].append(r["portrait"])
        else:
            if cur:
                spans.append(cur)
            cur = {"text": r["text"], "t0": r["t"], "t1": r["t"], "n": 1,
                   "portraits": [r["portrait"]], "font": r["font"]}
    if cur:
        spans.append(cur)
    # 量级过滤：同一段里数值应当同量级（用全部段的位数中位数做参照）
    nums = [int(s["text"]) for s in spans if s["text"].isdigit()]
    mag = float(np.median(nums)) if nums else 0.0
    kept = []
    for s in spans:
        if not s["text"].isdigit():
            continue
        if s["n"] < SPAN_MIN_FRAMES:
            continue
        if mag and int(s["text"]) < MIN_FRAC_OF_MEDIAN * mag:
            continue
        ps = [p for p in s["portraits"] if p]
        s["portrait"] = max(set(ps), key=ps.count) if ps else None
        kept.append(s)
    return kept


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--cluster", action="store_true", help="先聚类阿哈头像并出图（人工认脸定标）")
    ap.add_argument("--thr", type=float, default=0.80, help="阿哈头像聚类阈值")
    ap.add_argument("--labels", default="out/L2_aha_labels.json",
                    help="阿哈头像聚类的组→成员标签（人工认脸后写进去）")
    ap.add_argument("--json", default="out/L2_aha.json")
    args = ap.parse_args()
    frames = dense_frames()
    dense = [t for t in frames if in_aha(t)]
    print("阿哈时段密帧：%d 张" % len(dense))
    if len(dense) < 50:
        raise SystemExit("密帧太少（%d）——先跑 axis_extract_team2.py --step 0.2 抽阿哈段" % len(dense))
    model = H.load_model()
    model_pixel = H.load_pixel_model()

    if args.cluster:
        items, members = cluster_aha(frames, args.thr)
        print("阿哈头像聚类：%d 组（阈值 %.2f）" % (len(members), args.thr))
        for gi, g in enumerate(members):
            ts = sorted(items[i][0] for i in g)
            print("  组%-2d n=%-4d 例 t=%-7s 时间：%s" % (gi + 1, len(g), T.fmt_t(ts[0]),
                                                        ", ".join(T.fmt_t(x) for x in ts[:10])))
        aha_sheet(items, members)
        json.dump({"thr": args.thr,
                   "groups": {str(gi + 1): sorted(items[i][0] for i in g)
                              for gi, g in enumerate(members)}},
                  open("out/L2_aha_clusters.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("已写出 out/L2_aha_clusters.json（认脸后把 组→成员 写进 %s）" % args.labels)
        return 0

    labels = {}
    if os.path.exists(args.labels):
        labels = json.load(open(args.labels, encoding="utf-8"))
    portrait_of = {}
    if labels:
        clus = json.load(open("out/L2_aha_clusters.json", encoding="utf-8"))["groups"]
        for gid, ts in clus.items():
            who = labels.get(gid)
            for t in ts:
                portrait_of[round(float(t), 2)] = who

    rows = read_all(frames, model, model_pixel, portrait_of)
    spans = stable_spans(rows)
    print("可读帧 %d / 密帧 %d；稳定段 %d 个" % (sum(1 for r in rows if r["text"]), len(rows), len(spans)))

    print("\n== 稳定段（结算值，≥0.6s）==")
    print("%-8s %-8s %-11s %-4s %-8s %-8s %s" % ("t0", "t1", "值", "帧", "时长", "头像", "分数"))
    for s in spans:
        print("%-8s %-8s %-11s %-4d %-8s %-8s %s"
              % (s["t0"], s["t1"], s["text"], s["n"], "%.1fs" % (s["t1"] - s["t0"] + 0.2),
                 s.get("portrait") or "?", s["font"]))

    print("\n== 按成员归拢（头像识别）==")
    by_unit = {}
    for s in spans:
        by_unit.setdefault(s.get("portrait") or "未知", []).append(s)
    for u, ss in sorted(by_unit.items(), key=lambda kv: -len(kv[1])):
        vals = [int(s["text"]) for s in ss if s["text"].isdigit()]
        print("  %-6s %d 段  值：%s" % (u, len(ss), vals))

    print("\n== (1+欢愉度) 之比（同一阿哈段内两两比较）==")
    ratios = []
    for a, b in AHA_SEGS:
        seg = [s for s in spans if a - 0.5 <= s["t0"] <= b + 0.5 and s.get("portrait") in ELATION_MULT]
        for i in range(len(seg)):
            for j in range(i + 1, len(seg)):
                s1, s2 = seg[i], seg[j]
                if s1["portrait"] == s2["portrait"]:
                    continue
                m1, m2 = ELATION_MULT[s1["portrait"]], ELATION_MULT[s2["portrait"]]
                d1, d2 = int(s1["text"]), int(s2["text"])
                if d2 == 0:
                    continue
                r = (d1 / m1) / (d2 / m2)
                ratios.append({"seg": [a, b], "who1": s1["portrait"], "who2": s2["portrait"],
                               "d1": d1, "d2": d2, "m1": m1, "m2": m2, "ratio": round(r, 3),
                               "t1": s1["t0"], "t2": s2["t0"]})
                print("  段 %s：%-4s %-8d ÷倍率%.3f  vs  %-4s %-8d ÷倍率%.3f  →  (1+欢愉度)比 = %.3f"
                      % ("%g~%g" % (a, b), s1["portrait"], d1, m1, s2["portrait"], d2, m2, r))
    if not ratios:
        print("  （本批没有同一段内「两个不同成员」的稳定段 —— 见下面的下一步）")

    if args.dump:
        print("\n== 逐帧明细 ==")
        for r in rows:
            print("  t=%-7s %-11s %-6s 头像=%-6s(%.2f/%.2f) 标记=%s"
                  % (r["t"], r["text"] or "-", r["verdict"], r["portrait"] or "?",
                     r["pscore"], r["psecond"] if r["psecond"] is not None else -9, r["marker"]))

    out = {"spans": spans, "ratios": ratios, "by_unit": {k: [s["text"] for s in v]
                                                        for k, v in by_unit.items()},
           "elation_mult": ELATION_MULT, "pearl_note": PEARL_NOTE,
           "rows": rows if args.dump else None}
    json.dump(out, open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已写出 %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
