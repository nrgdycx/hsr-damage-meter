# -*- coding: utf-8 -*-
"""
正式可行性验证：**官方角色图能不能替代"从画面挖模板"？**

## 已确认的前提（不要重查）
1. `btdsh/raw/icon/character/<id>.png` = 官方角色图（**这才是之前 `char_vs_official.png`
   用的源**；`icon/avatar/` 是另一种小图标，不合适）。
2. 已有的 `samples/char_vs_official.png` 目视显示：**画面卡面与官方图是同一张画、同一姿势**，
   只是**取景/裁切不同**（画面卡更放大）。
3. 已有实测（`official_avatar_probe.py`）：把 `icon/avatar/` 归一化后与画面模板比，
   NCC 只有 0.10~0.37 → **不能直接用**（但那是错的源 + 未对齐取景）。

## 本脚本要回答的问题
  **对 `icon/character/` 做"缩放 + 平移"对齐后，能不能在当前的判据下认对？**

做法：对每个已知角色，
  · 取官方图，按 72:48 的宽高比裁一块（可调 zoom / 偏移）；
  · 生成 4 通道特征（与 `axis_actor` 同口径）；
  · 与**所有角色**的画面模板比，看该角色是否排第一、分差多少；
  · 报告"官方模板能否过 0.90 分 + 0.45 分差"两道闸。

用法：
    python tools/axis/official_template_feasibility.py
"""

import json
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for _p in (ROOT, os.path.join(ROOT, "vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

RAW = r"D:\project\btdsh\raw"
ICON_CHAR = os.path.join(RAW, "icon", "character")

# 与 axis_actor 同口径：72x48、四通道
GW, GH = 72, 48


def feats(bgr):
    small = cv2.resize(bgr, (GW, GH), interpolation=cv2.INTER_AREA)
    g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    mag = mag / (mag.max() + 1e-6)
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32)
    a = (lab[:, :, 1] - 128.0) / 128.0
    b = (lab[:, :, 2] - 128.0) / 128.0
    return np.stack([g, mag, a, b]).astype(np.float32)


def ncc_weighted(f1, f2, w=(1.0, 0.6, 0.3, 0.3)):
    tot, ws = 0.0, 0.0
    for i in range(4):
        x = f1[i].ravel().astype(np.float64)
        y = f2[i].ravel().astype(np.float64)
        x = x - x.mean()
        y = y - y.mean()
        d = np.linalg.norm(x) * np.linalg.norm(y)
        if d < 1e-9:
            continue
        tot += w[i] * float(np.dot(x, y) / d)
        ws += w[i]
    return tot / max(ws, 1e-9)


def crop_72x48(img, zoom, cx, cy):
    """按 72:48 的宽高比从 img 里取一块。zoom=1 → 取整图高度。"""
    h, w = img.shape[:2]
    bh = h / zoom
    bw = bh * (GW / float(GH))
    if bw > w:
        bw = w
        bh = bw * (GH / float(GW))
    x0 = int(np.clip(cx * w - bw / 2, 0, max(0, w - bw)))
    y0 = int(np.clip(cy * h - bh / 2, 0, max(0, h - bh)))
    return img[y0:y0 + int(bh), x0:x0 + int(bw)]


def main():
    names = {}
    p = os.path.join(ROOT, "StarRailRes-index_min", "index_min", "cn", "characters.json")
    if os.path.exists(p):
        d = json.load(open(p, encoding="utf-8"))
        names = {str(v.get("id")): v.get("name") for v in d.values() if isinstance(v, dict)}

    bank = np.load(os.path.join(ROOT, "out", "axis_top_bank_E.npz"), allow_pickle=True)
    chars = [k for k in bank.files]
    print("模板库角色:", chars)
    print()

    # 官方图是否存在
    ids = {}
    for k in chars:
        hit = [cid for cid, nm in names.items() if nm == k]
        if hit:
            ids[k] = hit[0]
    print("能在 index 里找到 ID 的:", {k: v for k, v in ids.items()})
    print("找不到的（忆灵等）:", [k for k in chars if k not in ids])
    print()

    have = {}
    for k, cid in ids.items():
        f = os.path.join(ICON_CHAR, "%s.png" % cid)
        if os.path.exists(f):
            have[k] = cv2.imread(f, cv2.IMREAD_COLOR)
    print("有官方图的角色:", list(have.keys()))
    if not have:
        print("❌ 没有可用官方图，无法验证")
        return
    print()

    # 网格搜索 zoom / 中心，找让"官方模板 vs 自己角色模板"平均分最高的组合
    print("=== 网格搜索对齐参数（目标：让官方图更像自己的画面模板）===")
    best = None
    for zoom in (1.0, 1.25, 1.5, 2.0):
        for cy in (0.30, 0.38, 0.46):
            scores = []
            for k, img in have.items():
                c = crop_72x48(img, zoom, 0.5, cy)
                if c.size == 0:
                    continue
                fo = feats(c)
                m = bank[k]
                n = min(12, m.shape[0])
                scores.append(max(ncc_weighted(fo, m[i]) for i in range(n)))
            if scores:
                avg = float(np.mean(scores))
                if best is None or avg > best[0]:
                    best = (avg, zoom, cy)
                print("  zoom=%.2f cy=%.2f → 自己角色平均分 %.3f (n=%d)" % (zoom, cy, avg, len(scores)))

    print()
    print("最佳参数: 平均分 %.3f  zoom=%.2f  cy=%.2f" % best)
    avg, zoom, cy = best

    # 用最佳参数做"判别力"测试：官方模板能否认出自己的角色
    print()
    print("=== 判别力测试（官方模板 × 全部画面模板）===")
    print("%-8s %8s %8s %8s  %s" % ("角色", "自己最高", "他人最高", "分差", "结果"))
    ok = 0
    tot = 0
    for k, img in have.items():
        c = crop_72x48(img, zoom, 0.5, cy)
        fo = feats(c)
        self_s = max(ncc_weighted(fo, bank[k][i]) for i in range(min(12, bank[k].shape[0])))
        other = -2.0
        for k2 in chars:
            if k2 == k:
                continue
            m2 = bank[k2]
            s = max(ncc_weighted(fo, m2[i]) for i in range(min(12, m2.shape[0])))
            other = max(other, s)
        margin = self_s - other
        good = (self_s >= 0.90) and (margin >= 0.45)
        ok += 1 if good else 0
        tot += 1
        print("%-8s %8.3f %8.3f %8.3f  %s" % (k, self_s, other, margin,
                                              "✅ 过闸" if good else "❌ 不过闸"))
    print()
    print("过闸 %d / %d" % (ok, tot))
    if ok == tot:
        print("✅ 结论：官方角色图**可以**替代画面挖模板 → 任意队伍适配可变成"
              "「查 ID → 取官方图 → 生成模板」")
    elif ok >= tot * 0.6:
        print("⚠️ 结论：官方图**部分可用** → 可作冷启动/兜底，再叠加少量画面模板")
    else:
        print("❌ 结论：官方图**不能**直接替代 → 仍需从画面挖模板"
              "（但可用于「同一张画、取景不同」时的候选排序）")


if __name__ == "__main__":
    main()
