# -*- coding: utf-8 -*-
"""
E 线：左标记（圆点 / 四角星）识别。
用户观察：**四角星 = 插入行动轴的行动**（额外回合/插队），圆点 = 按行动值正常排队。

第 1 步（本脚本 --sheet）：把已核对的 71 个顶端卡帧的标记区拼成图，人工标注圆点/星形，
                         存到 out/axis_marker_labels_E.json（作为标记分类器的真值）。
用法：
  python axis_marker_E.py --sheet          # 出标注图 samples/E_marker_sheet.png
  python axis_marker_E.py --eval           # 用已标注的真值评估标记分类器
  python axis_marker_E.py --dump 226       # 打印单帧标记区的 ASCII 特征
"""
# [P3 整理] 原路径：axis_marker_E.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import json
import math
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import axis_actor as T

FRAME = "frames/glyphcache/f%08.2f.png"
LABEL_JSON = "out/axis_marker_labels_E.json"
NEG_FRAMES = [120, 130, 240, 290, 300, 320, 170, 190, 210, 230, 288]     # 空槽 / 敌人


def font(sz):
    for f in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(f, sz)
        except Exception:
            continue
    return ImageFont.load_default()


def patch(img, cx=86, cy=127, r=30, s=None):
    """取标记区方块。"""
    if s is None:
        s = T.scale_of(img.shape)
    cx, cy, r = int(round(cx * s)), int(round(cy * s)), int(round(r * s))
    return img[cy - r:cy + r, cx - r:cx + r]


# ---------------------------------------------------------------- 分类器
def marker_shape(img, s=None):
    """返回 (类型, 特征dict)。类型：empty/dot/star/diamond/unknown + 我方圆点/我方星形…"""
    if s is None:
        s = T.scale_of(img.shape)
    p = patch(img, s=s)
    if p.size == 0:
        return "unknown", {}
    hsv = cv2.cvtColor(p, cv2.COLOR_BGR2HSV)
    S = hsv[:, :, 1].astype(np.float32)
    V = hsv[:, :, 2].astype(np.float32)
    h, w = S.shape
    yy, xx = np.mgrid[0:h, 0:w]
    cy, cx = h / 2.0, w / 2.0
    rad = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    score = S * (V / 255.0)
    # 局部背景：环带 24~30px 的中位数
    outer = (rad >= 24 * s) & (rad <= 30 * s)
    bg = float(np.median(score[outer])) if outer.any() else 0.0
    # 标记 = 明显高于局部背景的高饱和像素
    thr = max(90.0, bg * 1.6)
    m = ((score > thr) & (rad <= 20 * s)).astype(np.uint8)
    area = int(m.sum())
    disc = rad <= 8 * s
    ann = (rad >= 11 * s) & (rad <= 18 * s)
    core = int(m[disc].sum())
    arms = int(m[ann].sum())
    # 边缘能量（判断"有没有卡"：没有卡时整块是平滑背景）
    g = cv2.cvtColor(p, cv2.COLOR_BGR2GRAY)
    edge = float(np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)).mean())
    hue = float(np.median(hsv[:, :, 0][m.astype(bool)])) if area > 0 else -1
    feat = dict(area=area, core=core, arms=arms, bg=round(bg, 1), edge=round(edge, 1),
                hue=round(hue, 1), core_ratio=round(core / max(1, area), 2))
    if area < 20:
        return "none", feat
    if area > 0.55 * math.pi * (20 * s) ** 2 and edge < 6:
        return "empty", feat                      # 整块饱和 + 没有边缘 = 背景
    side = "ally" if 60 <= hue <= 130 else ("enemy" if (hue <= 25 or hue >= 155) else "?")
    if arms > 0.55 * max(1, core) and arms > 60 * s * s:
        shape = "star"
    else:
        shape = "dot"
    return "%s_%s" % (side, shape), feat


def marker_patch(img, s=None, r=30):
    """取标记区方块（默认 60x60，中心 (86,127)）。"""
    if s is None:
        s = T.scale_of(img.shape)
    cx, cy, r = int(round(86 * s)), int(round(127 * s)), int(round(r * s))
    return img[cy - r:cy + r, cx - r:cx + r]


def marker_bank(r=30):
    """从人工标注的 82 个样本建"标记模板库"：{dot/star/enemy/empty: [(t, feats)]}"""
    grouped = json.load(open(LABEL_JSON, encoding="utf-8"))
    bank = {}
    for lab, ts in grouped.items():
        if lab.startswith("_") or lab == "occluded":
            continue
        for t in ts:
            img = cv2.imread(FRAME % float(t), cv2.IMREAD_COLOR)
            bank.setdefault(lab, []).append((float(t), T.feats(marker_patch(img, r=r))))
    return bank


def marker_match(img, bank, r=30):
    """返回 {类别: 最高分}。"""
    f = T.feats(marker_patch(img, r=r))
    return {lab: max(T.pair_score(f, x[1]) for x in items) for lab, items in bank.items()}


def eval_template(r=30):
    bank = marker_bank(r)
    grouped = json.load(open(LABEL_JSON, encoding="utf-8"))
    truth = {}
    for lab, ts in grouped.items():
        if lab.startswith("_"):
            continue
        for t in ts:
            truth[float(t)] = lab
    conf = {}
    bad = []
    n = ok = 0
    for t, exp in sorted(truth.items()):
        if exp == "occluded":
            continue
        img = cv2.imread(FRAME % float(t), cv2.IMREAD_COLOR)
        sc = {}
        for lab, items in bank.items():
            keep = [x[1] for x in items if x[0] != t]
            if not keep:
                continue
            f = T.feats(marker_patch(img, r=r))
            sc[lab] = max(T.pair_score(f, k) for k in keep)
        pred = max(sc.items(), key=lambda kv: kv[1])[0] if sc else "?"
        n += 1
        ok += (pred == exp)
        conf[(exp, pred)] = conf.get((exp, pred), 0) + 1
        if pred != exp:
            bad.append((t, exp, pred, round(sc[pred], 2)))
    print("标记模板法（patch %dx%d）留一帧准确率 %.1f%% (%d/%d)" %
          (2 * r, 2 * r, ok * 100.0 / n, ok, n))
    for (e, p), v in sorted(conf.items()):
        print("   真值%-8s 判成%-8s %d" % (e, p, v))
    if bad:
        print("   错例：" + "  ".join("t%s %s->%s(%.2f)" % (T.fmt_t(t), e, p, s)
                                     for t, e, p, s in bad))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", action="store_true")
    ap.add_argument("--eval", action="store_true")
    ap.add_argument("--eval-template", type=int, default=None, metavar="R",
                    help="用人工标注样本做模板，留一帧评估标记分类（R=半边长，如 22/30）")
    ap.add_argument("--sheet2", default="", help="第二个录屏的帧号清单，出标注图")
    ap.add_argument("--dir2", default="frames/glyphcache2_E")
    ap.add_argument("--dump", default="")
    args = ap.parse_args()

    if args.sheet2:
        import glob as _glob
        items = []
        for chunk in args.sheet2.split(";"):
            for x in chunk.replace("=", ":").split(":")[-1].split(","):
                if x.strip():
                    items.append(float(x))
        panels = []
        for t in items:
            p = os.path.join(args.dir2, "f%08.2f.png" % t)
            if not os.path.exists(p):
                continue
            img = Image.open(p).convert("RGB").crop((56, 97, 116, 157))
            im = img.resize((132, 132), Image.LANCZOS)
            cv = Image.new("RGB", (im.width, im.height + 20), (0, 0, 0))
            cv.paste(im, (0, 20))
            ImageDraw.Draw(cv).text((2, 3), "t%s" % T.fmt_t(t), font=font(13), fill=(255, 255, 255))
            panels.append(cv)
        cols = 10
        rn = (len(panels) + cols - 1) // cols
        pw, ph = panels[0].size
        sheet = Image.new("RGB", (cols * pw + (cols + 1) * 4, rn * ph + (rn + 1) * 4), (25, 25, 25))
        for i, pn in enumerate(panels):
            r_, c_ = divmod(i, cols)
            sheet.paste(pn, (4 + c_ * (pw + 4), 4 + r_ * (ph + 4)))
        sheet.save("samples/E_marker_sheet2.png")
        print("已写出 samples/E_marker_sheet2.png %s（%d 个标记）" % (sheet.size, len(panels)))
        return

    if args.eval_template:
        eval_template(args.eval_template)
        return

    if args.dump:
        for t in [float(x) for x in args.dump.split(",")]:
            img = cv2.imread(FRAME % t, cv2.IMREAD_COLOR)
            kind, feat = marker_shape(img)
            print("t=%-6s %-10s %s" % (T.fmt_t(t), kind, feat))
        return

    if args.sheet:
        lab = json.load(open(T.LABELS_PATH, encoding="utf-8"))
        items = []
        for unit, ts in lab.items():
            if unit.startswith("_"):
                continue
            for t in ts:
                items.append((float(t), unit))
        for t in NEG_FRAMES:
            items.append((float(t), "非我方"))
        items.sort()
        panels = []
        for t, unit in items:
            img = Image.open(FRAME % t).convert("RGB").crop((56, 97, 116, 157))
            im = img.resize((im_w := 132, 132), Image.LANCZOS)
            cv = Image.new("RGB", (im.width, im.height + 20), (0, 0, 0))
            cv.paste(im, (0, 20))
            d = ImageDraw.Draw(cv)
            d.text((2, 3), "t%s %s" % (T.fmt_t(t), unit[:2]), font=font(13), fill=(255, 255, 255))
            panels.append(cv)
        cols = 10
        rn = (len(panels) + cols - 1) // cols
        pw, ph = panels[0].size
        sheet = Image.new("RGB", (cols * pw + (cols + 1) * 4, rn * ph + (rn + 1) * 4), (25, 25, 25))
        for i, pn in enumerate(panels):
            r_, c_ = divmod(i, cols)
            sheet.paste(pn, (4 + c_ * (pw + 4), 4 + r_ * (ph + 4)))
        sheet.save("samples/E_marker_sheet.png")
        print("已写出 samples/E_marker_sheet.png %s（%d 个标记；请人工标注 圆点/星形）" %
              (sheet.size, len(panels)))
        return

    if args.eval:
        if not os.path.exists(LABEL_JSON):
            print("还没有 %s，先跑 --sheet 看图标注" % LABEL_JSON)
            return
        grouped = json.load(open(LABEL_JSON, encoding="utf-8"))
        truth = {}
        for lab, ts in grouped.items():
            if lab.startswith("_"):
                continue
            for t in ts:
                truth[float(t)] = lab
        conf = {}
        bad = []
        for t, exp in sorted(truth.items()):
            img = cv2.imread(FRAME % t, cv2.IMREAD_COLOR)
            kind, feat = marker_shape(img)
            got = kind.split("_")[-1] if "_" in kind else kind
            if got == "diamond":
                got = "dot"                       # 敌方菱形也算"有点"
            if exp in ("enemy", "empty", "occluded"):
                okk = (got in ("empty", "none")) if exp == "empty" else \
                      ("enemy" in kind if exp == "enemy" else True)
            else:
                okk = (got == exp) and ("enemy" not in kind)
            conf[(exp, got)] = conf.get((exp, got), 0) + 1
            if not okk:
                bad.append((t, exp, kind, feat))
        n = len(truth)
        ok = n - len(bad)
        print("标记类型准确率（按语义判对）%.1f%% (%d/%d)" % (ok * 100.0 / n, ok, n))
        print("混淆：")
        for (e, g), v in sorted(conf.items()):
            print("   真值%-10s 判成%-10s %d" % (e, g, v))
        if bad:
            print("错例：")
            for t, e, k, feat in bad:
                print("   t=%-6s 真值%-10s 判成%-10s %s" % (T.fmt_t(t), e, k, feat))


if __name__ == "__main__":
    main()
