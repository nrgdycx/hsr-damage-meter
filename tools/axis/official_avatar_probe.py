# -*- coding: utf-8 -*-
"""
关键可行性实验：**官方头像素材能不能当行动轴模板用？**

背景（2026-10-02）：
  * 项目现有做法 = 从**游戏画面**里挖模板（`out/axis_top_bank_E*.npz`），每支新队伍都要重挖。
  * 刚发现 `D:/project/btdsh/raw/icon/avatar/` 有 **313 张官方角色头像 128×128 RGBA**。
  * 如果官方头像 == 行动轴卡上那块头像（同源），就能**不用挖模板**：
    拿 ID→名字表 + 官方头像直接建库 → **任意队伍适配变成"查表"**。

本脚本做三件事：
  1. 把已知角色的**现有模板**（从画面挖的）与**官方头像**做 NCC 对比；
  2. 用官方头像当"单模板"去匹配该角色的所有画面模板，看分数分布；
  3. 给出结论：能否用官方头像替代/补充现有模板。

用法：
    python tools/axis/official_avatar_probe.py
"""

import io
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
AVATAR_DIR = os.path.join(RAW, "icon", "avatar")
INDEX = os.path.join(RAW, "index", "en")


def feats(bgr):
    """复刻 axis_actor 的特征：72x48 的 灰度/梯度/Lab a/Lab b 四通道。"""
    small = cv2.resize(bgr, (72, 48), interpolation=cv2.INTER_AREA)
    g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    mag = mag / (mag.max() + 1e-6)
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32)
    a = (lab[:, :, 1] - 128.0) / 128.0
    b = (lab[:, :, 2] - 128.0) / 128.0
    return np.stack([g, mag, a, b])


def ncc(f1, f2, w=(1.0, 0.6, 0.3, 0.3)):
    """与 axis_actor 同口径的加权 NCC（逐通道）。"""
    tot, ws = 0.0, 0.0
    for i in range(4):
        x = f1[i].ravel().astype(np.float64)
        y = f2[i].ravel().astype(np.float64)
        x = x - x.mean()
        y = y - y.mean()
        d = (np.linalg.norm(x) * np.linalg.norm(y))
        if d < 1e-9:
            continue
        tot += w[i] * float(np.dot(x, y) / d)
        ws += w[i]
    return tot / max(ws, 1e-9)


def load_name_map():
    """ID → 中文名。

    ⚠️ 两个数据源都要查（本项目栽过"只查一个源就下结论"的坑）。
    ⚠️ 另注：tdsh/raw/icon/avatar/ 与 icon/character/ **都不是行动轴卡面的同源图** ——
       更彻底的证据（穷尽 5061 个 PNG + 逐像素变换搜索）见
       docs/任意队伍适配.md §11；本脚本的结论与之独立吻合。
      · `StarRailRes-index_min/index_min/cn/characters.json` —— **中文名**（主源）
      · `btdsh/raw/index/en/characters.json` —— 英文名（兜底）
    """
    out = {}
    cands = [
        os.path.join(ROOT, "StarRailRes-index_min", "index_min", "cn", "characters.json"),
        os.path.join(RAW, "index", "en", "characters.json"),
        os.path.join(RAW, "index", "characters.json"),
    ]
    for p in cands:
        if not os.path.exists(p):
            continue
        try:
            d = json.load(io.open(p, encoding="utf-8"))
            for k, v in d.items():
                if isinstance(v, dict) and v.get("name"):
                    out.setdefault(str(v.get("id", k)), v["name"])
        except Exception:
            pass
    return out


def main():
    import axis_actor as T

    bank = np.load(os.path.join(ROOT, "out", "axis_top_bank_E.npz"), allow_pickle=True)
    print("现有模板库（从画面挖）:", list(bank.files))
    print()

    names = load_name_map()
    print("index 里的 ID→名字 条目数:", len(names))
    print()

    # 官方头像清单
    avs = sorted(f for f in os.listdir(AVATAR_DIR) if f.endswith(".png"))
    print("官方头像数:", len(avs))
    print()

    # 对每个已知角色：官方头像 vs 该角色所有画面模板
    print("=== 官方头像 × 画面模板 的 NCC（同口径加权）===")
    print("%-10s %-8s %8s %8s %8s   %s" % ("角色", "官方图", "最高", "中位", "最低", "判定"))
    for name in bank.files:
        mats = bank[name]                      # (N,4,48,72)
        # 找官方头像：用 ID→名字 反查
        cand = [cid for cid, nm in names.items() if nm == name]
        if not cand:
            print("%-10s %-8s %8s %8s %8s   %s" % (name, "-", "-", "-", "-", "index 里没这个名字"))
            continue
        cid = cand[0]
        p = os.path.join(AVATAR_DIR, "%s.png" % cid)
        if not os.path.exists(p):
            print("%-10s %-8s %8s %8s %8s   %s" % (name, cid, "-", "-", "-", "无该 ID 的头像图"))
            continue
        bgr = cv2.imread(p, cv2.IMREAD_COLOR)
        if bgr is None:
            print("%-10s %-8s %8s %8s %8s   %s" % (name, cid, "-", "-", "-", "读图失败"))
            continue
        fo = feats(bgr)
        scores = [ncc(fo, mats[i]) for i in range(mats.shape[0])]
        scores = np.array(scores)
        hi, med, lo = scores.max(), float(np.median(scores)), scores.min()
        verdict = "✅ 同源（可直接当模板）" if hi >= 0.90 else (
            "⚠️ 部分相似（需域适配）" if hi >= 0.70 else "❌ 不同源")
        print("%-10s %-8s %8.3f %8.3f %8.3f   %s" % (name, cid, hi, med, lo, verdict))

    print()
    print("=== 反向：官方头像 vs 别的角色的模板（应显著更低，验证判别力）===")
    for name in list(bank.files)[:3]:
        mats = bank[name]
        cand = [cid for cid, nm in names.items() if nm == name]
        if not cand:
            continue
        p = os.path.join(AVATAR_DIR, "%s.png" % cand[0])
        if not os.path.exists(p):
            continue
        bgr = cv2.imread(p, cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        fo = feats(bgr)
        row = []
        for other in bank.files:
            if other == name:
                continue
            om = bank[other]
            s = max(ncc(fo, om[i]) for i in range(om.shape[0]))
            row.append((other, s))
        row.sort(key=lambda x: -x[1])
        print("  %s 的官方头像 vs 其它角色:" % name,
              ", ".join("%s=%.2f" % (a, b) for a, b in row[:4]))


if __name__ == "__main__":
    main()
