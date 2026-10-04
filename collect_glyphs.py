# -*- coding: utf-8 -*-
"""
字形样本收集 + 聚类 —— 为「高准确率数字分类器」准备带标签的训练数据。

为什么走这条路（前面几轮的结论）：
  * VLM 会编数字；RapidOCR 对这套美术字不稳；手工二值 XOR 匹配只能到 50~70%。
  * 要求是【实时】（边打边读）→ 必须纯本地方案 → 需要一个真正可靠的本地分类器。
  * 分类器要可靠，就需要大量带标签的字形；而标签只需人工认一次（每类认一个）。

流程：抽帧 → 淡黄掩膜 → 列分割 → 字形归一化(灰度 20x28) → 聚类 →
      出「每簇代表字形」拼图交给用户认领 → 认领后即可训练/生成原型。
"""

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from ffmpeg_path import require_ffmpeg as _req_ff
import glob
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image

FFMPEG = _req_ff()   # 见 ffmpeg_path.py（可用 HSR_FFMPEG 指定）
VIDEO = "records/屏幕录制 2026-09-29 174931.mp4"
HUD_BOX = (2400, 190, 2876, 350)     # 左,上,右,下
BAND = (72, 155)                     # 行带（相对裁剪框）
GW, GH = 20, 28                      # 归一化尺寸
CACHE = "frames/glyphcache"


def frame(t):
    """抽帧并缓存（避免重复 seek 大文件）。"""
    p = os.path.join(CACHE, "f%08.2f.png" % t)
    if not os.path.exists(p):
        os.makedirs(CACHE, exist_ok=True)
        subprocess.run([FFMPEG, "-ss", str(t), "-i", VIDEO, "-frames:v", "1", "-y", p],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p if os.path.exists(p) else None


def instance(png):
    """
    返回该帧的 (字形向量列表, 每字形的像素宽)。
    字形向量：灰度（黄度）归一化到 GW x GH、按自身峰值做相对阈值后的 0~1 浮点图。
    """
    im = Image.open(png).convert("RGB").crop(HUD_BOX)
    a = np.asarray(im, dtype=np.int16)
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    y0, y1 = BAND
    m = (R > 225) & (G > 225) & (B >= 185) & ((R - B) > 25)
    m[:y0, :] = False
    m[y1 + 1:, :] = False
    if not m.any():
        return [], []
    # 黄度：笔画核心高、辉光低
    inten = np.clip(np.minimum(R, G) - B, 0, 63).astype(np.float32)
    inten[~m] = 0
    colcol = m.any(axis=0)
    xs = np.where(colcol)[0]
    # 列分割（间隙合并）
    runs, s = [], None
    for x in range(len(colcol)):
        if colcol[x] and s is None:
            s = x
        elif not colcol[x] and s is not None:
            runs.append([s, x - 1])
            s = None
    if s is not None:
        runs.append([s, len(colcol) - 1])
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] - 1 < 3:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    vecs, widths = [], []
    for x0, x1 in merged:
        w = x1 - x0 + 1
        if not (6 <= w <= 48):
            continue
        sub = inten[y0:y1 + 1, x0:x1 + 1]
        mx = sub.max()
        if mx <= 6:
            continue
        core = sub > mx * 0.5
        if core.sum() < 12:
            continue
        rr = np.where(core.any(axis=1))[0]
        cc = np.where(core.any(axis=0))[0]
        sub = sub[rr[0]:rr[-1] + 1, cc[0]:cc[-1] + 1]
        img = Image.fromarray(sub.astype(np.uint8)).resize((GW, GH), Image.BILINEAR)
        v = np.asarray(img, dtype=np.float32)
        v = v / (v.max() or 1)
        vecs.append(v.ravel())
        widths.append(w)
    return vecs, widths


def collect(times):
    out = []
    for t in times:
        png = frame(t)
        if not png:
            continue
        vecs, ws = instance(png)
        for v, w in zip(vecs, ws):
            out.append({"t": t, "w": w, "v": v})
    return out


def cluster(samples, k=14, iters=25, seed=0):
    """k-means（numpy 实现），返回每簇原型与成员索引。"""
    X = np.stack([s["v"] for s in samples])
    rng = np.random.default_rng(seed)
    cent = X[rng.choice(len(X), size=min(k, len(X)), replace=False)]
    for _ in range(iters):
        d = ((X[:, None, :] - cent[None, :, :]) ** 2).sum(axis=2)
        lab = d.argmin(axis=1)
        for j in range(len(cent)):
            sel = X[lab == j]
            if len(sel):
                cent[j] = sel.mean(axis=0)
    groups = [{"center": cent[j], "idx": np.where(lab == j)[0].tolist()} for j in range(len(cent))]
    groups.sort(key=lambda g: -len(g["idx"]))
    return groups


def main():
    times = [t for t in range(100, 340, 1)]        # 先跑 100~340 秒，够抽样
    print("抽帧中（共 %d 个时间点，已缓存的不重复抽）..." % len(times))
    samples = collect(times)
    print("收集到字形实例: %d 个" % len(samples))
    if len(samples) < 50:
        print("样本太少，检查掩膜/分割参数")
        return
    groups = cluster(samples, k=14)
    print("聚成 %d 簇；各簇样本数: %s" % (len(groups), [len(g["idx"]) for g in groups]))

    # 出认领图：簇原型放大 + 簇号 + 样本数
    from PIL import ImageDraw, ImageFont
    cw, ch = 100, 150
    n = len(groups)
    sheet = Image.new("RGB", (cw * n, ch + 70), (0, 0, 0))
    d = ImageDraw.Draw(sheet)
    f = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 30)
    fs = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 18)
    for i, g in enumerate(groups):
        img = Image.fromarray((g["center"].reshape(GH, GW) * 255).astype(np.uint8))
        img = img.convert("RGB").resize((cw - 20, ch - 50), Image.NEAREST)
        sheet.paste(img, (i * cw + 10, 44))
        d.text((i * cw + 22, 6), "C%d" % i, font=f, fill=(255, 90, 90))
        d.text((i * cw + 10, ch + 8), "n=%d" % len(g["idx"]), font=fs, fill=(160, 160, 160))
    sheet.save("samples/请看_认领字形.png")
    print("已写出 samples/请看_认领字形.png")

    json.dump({"n": len(samples),
               "groups": [{"id": i, "n": len(g["idx"]),
                           "ex": [(samples[j]["t"], samples[j]["w"]) for j in g["idx"][:6]]}
                          for i, g in enumerate(groups)]},
              open("out/glyph_groups.json", "w"), ensure_ascii=False, indent=1)
    print("已写出 out/glyph_groups.json")


if __name__ == "__main__":
    main()
