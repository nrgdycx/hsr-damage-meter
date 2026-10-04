# -*- coding: utf-8 -*-
"""【线2】录屏2 的 HUD 总伤害读数器（按 `docs/HUD数字读取.md` §5 的六步修法）。

⛔ **不修改任何上游共享文件**（`hud_glyphs.py` / `read_hud.py` 归 线7 与 A 线）——
   本模块只**复用** `hud_glyphs` 的掩膜原语与 A 线模型，自己实现带参数的提取与组装。

与上游 `hud_glyphs.extract` 的四处差别（都是录屏2 实测问题）：
  1. **框按 12 位放宽**：`(2100,226)-(2876,374)`；上游 `CX0=2350` 只够约 9 位，
     且 t=26 的最左墨迹**正好压在框左界上**（被切）。
  2. **链条阈值自适应**：上游硬编码 20px，而录屏2 串内间隔中位远大于它 → 断链 → 丢左侧位。
     这里用「本串自身相邻段的间隔中位数 × 1.8」定阈值（下限 24，上限 120）。
  3. **超宽块不再静默丢弃**：上游把 `W_MAX=52` 以上的块直接扔掉 → **少位且无告警**。
     这里改成**占位 `?`**（按 `宽/字距` 估几个字），位数不错位，下游一看 `?` 就标待复核。
     ⚠️ 不硬拆粘连块：`hud_glyphs._split_wide_off` 的注释记着"切错比不切更糟"
     （会在中间插假字、右侧全部错位）。
  4. **不可见帧判据**：字高中位 < 训练下限的一半 → 直接判「空」，
     **禁止**用碎片拼出数字（t=100 的 `880066`、t=300 的 `413?19400` 就是这种假字）。

用法：
    import hud_read_team2 as H
    model = H.load_model()
    r = H.read_crop(model, "frames/axis2_L2/t00026.00_hud.png")
    # {'text': '140130', 'verdict': 'ok'|'待复核'|'空', 'glyphs': [...], 'meta': {...}}
    python hud_read_team2.py 26 29 30 31 35 100     # 命令行单帧读数
"""
import json
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, HERE)

import hud_glyphs as HG          # noqa: E402  复用掩膜原语（不改它）
import axis_extract_team2 as AX     # noqa: E402  裁剪框定义与它保持一致

# 录屏2 的 HUD 框，绝对坐标 = (y0, x0, y1, x1)（与 hud_glyphs / read_hud 的口径一致）。
# ⚠️ `axis_extract_team2.REGIONS` 用的是裁剪口径 (x0, y0, x1, y1)，**顺序不同**，这里显式转换，
#    免得两套口径混用（第一版就是这么错了一次：拿 (2100,226) 当 y0,x0 → 切出空区域）。
_x0, _y0, _x1, _y1 = AX.REGIONS["hud"]
HUD_REGION = (_y0, _x0, _y1, _x1)          # (226, 2100, 374, 2876)

# ── 默认参数 ──
CFG = {
    "seg_mode": "glow",        # 列分割用的掩膜（录屏1 实测辉光层最稳）
    "glyph_mode": "hybrid_s",  # 取字形像素用的掩膜（核心∪辉光+填洞，去掉装饰金线）
    "chain": "auto",           # 链条阈值：auto = clamp(1.8×间隔中位, 24, 120)
    "chain_lo": 24,
    "chain_hi": 120,
    "w_max": 70,               # 单字宽度上限（录屏2 实测单字 43~46）
    "mass_min": 120.0,
    "mass_frac": 0.20,
    "h_frac": 0.45,
    "ratio_min": 0.22,
    "dens_min": 5.0,           # 墨迹密度下限 mass/宽（真数字 ≥10；背景光带 0.8）
    "expand": 3,
    "invis_h": 15.0,           # H_MIN=30 的一半：字高中位低于它就判「空」
    "invis_mass": 60.0,        # 整串墨迹质量下限（碎片拼凑的帧质量极低）
    "placeholders": True,      # 超宽/低质块 → 占位 '?'（保持位数对齐）
    # 「一个字形其实是两个字粘在一起」的兜底判据（实测标定，见 read_region 注释）：
    #   宽度比 = 最宽字 / 字宽中位；填充率 = 笔迹像素 / (宽×高)
    #   实测：亮光带粘进数字的 t=26 是 1.33 / 0.31；正常帧最高也只到 1.36 / 0.51。
    "w_ratio_max": 1.30,
    "fill_min": 0.40,
    "bar_rows": HG.BAR_ROWS,
}


def _runs_from_col(col, merge_px=3):
    runs, s = [], None
    for x in range(len(col)):
        if col[x] and s is None:
            s = x
        elif not col[x] and s is not None:
            runs.append([s, x - 1])
            s = None
    if s is not None:
        runs.append([s, len(col) - 1])
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] - 1 < merge_px:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return merged


def _gaps(runs):
    return [runs[i + 1][0] - runs[i][1] - 1 for i in range(len(runs) - 1)]


def _auto_chain(merged, cfg):
    """自适应链条阈值：用**看起来像单字**的那些段的间隔中位数 × 1.8。

    为什么不用"全部间隔的中位数"：框左边常有零散 UI 亮块，它们与数字之间的间隔很大，
    会把中位数抬上去 → 阈值过大 → 把左边无关的亮块也串进来。
    """
    if cfg.get("chain") not in (None, "auto"):
        return int(cfg["chain"])
    w_max = cfg["w_max"]
    idx = [i for i in range(len(merged) - 1)
           if (merged[i][1] - merged[i][0] + 1) <= w_max
           and (merged[i + 1][1] - merged[i + 1][0] + 1) <= w_max]
    g = _gaps(merged)
    sample = [g[i] for i in idx] or g
    if not sample:
        return cfg["chain_lo"]
    med = float(np.median(sample))
    return int(min(cfg["chain_hi"], max(cfg["chain_lo"], round(1.8 * med))))


def _row_blocks(row_any):
    """把"某一列范围里有墨的行"切成连通块 → [[r0, r1], ...]。"""
    blocks, s = [], None
    for y in range(len(row_any)):
        if row_any[y] and s is None:
            s = y
        elif not row_any[y] and s is not None:
            blocks.append([s, y - 1])
            s = None
    if s is not None:
        blocks.append([s, len(row_any) - 1])
    return blocks


def _run_stats(m_glyph, xa, xb):
    """某列段的统计量，**只取质量最大的行连通块**。

    为什么必须这样：录屏2 的数字正上方有一个黄色的「总伤害」标签，列投影分割只看列，
    标签会被并进数字的列范围里 —— 实测把字高从 93 抬到 **138**，字形图里混进标签 →
    分类器读错。标签与数字在行方向是**断开的**，所以取最大行连通块即可自校准地分开。
    """
    m1 = m_glyph[:, xa:xb + 1]
    row_any = m1.any(axis=1)
    blocks = _row_blocks(row_any)
    if not blocks:
        return None
    best, best_mass = None, -1
    for r0, r1 in blocks:
        mass = int(m1[r0:r1 + 1].sum())
        if mass > best_mass or (mass == best_mass and best and (r1 - r0) > (best[1] - best[0])):
            best, best_mass = (r0, r1), mass
    r0, r1 = best
    return {"xa": xa, "xb": xb, "w": xb - xa + 1, "r0": r0, "r1": r1,
            "h": int(r1 - r0 + 1), "mass": int(best_mass)}


def extract2(region, origin, cfg=None):
    """从**已裁好的 HUD 区域**取字形。返回 (items, meta)。

    items: [{"kind": "digit"|"gap", "gray": float32 GH×GW|None, "w","h","xa","xb","mass"}]
           `kind="gap"` = **超宽粘连块**占位（组装时输出 '?'），保持位数不错位。
    """
    cfg = dict(CFG, **(cfg or {}))
    c = np.asarray(region, dtype=np.int16)
    if c.ndim != 3 or c.shape[0] < 8 or c.shape[1] < 8:
        raise ValueError("HUD 区域太小/是空的：形状 %s（检查坐标顺序：(y0,x0,y1,x1)）" % (c.shape,))
    m_seg, m_glyph, warm = HG._masks(c, cfg["seg_mode"])
    if cfg["glyph_mode"] and cfg["glyph_mode"] != cfg["seg_mode"]:
        _, m_glyph, warm = HG._masks(c, cfg["glyph_mode"])

    # 分割前挖空"左侧细横线"所在行带（只作用于分割）
    ms = m_seg.copy()
    r0 = max(0, cfg["bar_rows"][0] - origin[0])
    r1 = min(ms.shape[0] - 1, cfg["bar_rows"][1] - origin[0])
    if r0 <= r1 and r0 < ms.shape[0]:
        ms[r0:r1 + 1, :] = False
    merged = _runs_from_col(ms.any(axis=0))
    if not merged:
        return [], {"n_runs": 0, "chain": None, "invisible": True, "reason": "框内无墨迹"}

    chain = _auto_chain(merged, cfg)
    linked = []
    for r in reversed(merged):
        if not linked:
            linked.append(r)
        elif linked[-1][0] - r[1] - 1 <= chain:
            linked.append(r)
        else:
            break
    linked = list(reversed(linked))

    from PIL import Image
    W = m_glyph.shape[1]
    cands = []
    for xa, xb in linked:
        st = _run_stats(m_glyph, xa, xb)
        if st is not None:
            cands.append(st)
    if not cands:
        return [], {"n_runs": len(merged), "chain": chain, "invisible": True, "reason": "链内无有效段"}

    # 密度闸：真实的数字笔画密实（实测 mass/宽 ≥ 10），而背景光带/辉光是"又宽又虚"
    # （录屏2 t=26 实测：172px 宽的光带 mass 只有 137 → 密度 0.8）。不设这道闸，
    # 放宽框后左边的光带会被当成"超宽块"塞进来（变成一串假 '?'）。
    d_min = cfg["dens_min"]
    cands = [x for x in cands if x["w"] <= 2 or x["mass"] >= d_min * x["w"]]
    if not cands:
        return [], {"n_runs": len(merged), "chain": chain, "invisible": True,
                    "reason": "链内所有段都被密度闸滤掉（只有弥散光效，没有笔画）",
                    "n_items": 0, "n_digits": 0, "h_med": 0.0, "mass": 0.0, "adv": None}

    big = [x for x in cands if x["mass"] >= 150] or cands
    m_ref = float(np.median([x["mass"] for x in big]))
    h_ref = float(np.median([x["h"] for x in big]))
    mass_thr = max(cfg["mass_min"], cfg["mass_frac"] * m_ref)
    h_thr = max(12.0, cfg["h_frac"] * h_ref)

    # 字距（advance）估计：用**合格单字的起点差**中位数（比"宽度中位数"稳，
    # 因为宽度会被粘连块带偏）；不足两个时退化为宽度中位数。
    ok_runs = [x for x in cands
               if x["w"] <= cfg["w_max"] and x["mass"] >= mass_thr and x["h"] >= h_thr]
    adv = float(np.median([x["w"] for x in big])) if big else 45.0
    if len(ok_runs) >= 2:
        d = np.diff(sorted(x["xa"] for x in ok_runs))
        d = d[d > 0.45 * adv]
        if len(d):
            adv = float(np.median(d))

    items = []
    for x in cands:
        xa, xb = x["xa"], x["xb"]
        good = (x["w"] <= cfg["w_max"] and x["mass"] >= mass_thr and x["h"] >= h_thr
                and x["w"] >= max(4, int(cfg["ratio_min"] * x["h"])))
        if not good:
            # 只有**超宽粘连块**才占位（真实存在但切不出来 → 位数会错位，必须标出来）；
            # 细碎块（宽度/质量不够）是掩膜碎屑，直接丢，不要造 '?' 噪声。
            if cfg["placeholders"] and x["w"] > cfg["w_max"]:
                n = int(max(1, round(x["w"] / max(1.0, adv))))
                items.append({"kind": "gap", "n": n, "w": x["w"], "h": x["h"],
                              "mass": x["mass"], "xa": xa, "xb": xb, "gray": None})
            continue
        lo, hi = xa, xb
        for _ in range(cfg["expand"]):
            if lo - 1 >= 0 and m_glyph[:, lo - 1].any():
                lo -= 1
            else:
                break
        for _ in range(cfg["expand"]):
            if hi + 1 < W and m_glyph[:, hi + 1].any():
                hi += 1
            else:
                break
        rr0 = max(0, x["r0"] - cfg["expand"])
        rr1 = min(m_glyph.shape[0] - 1, x["r1"] + cfg["expand"])
        # 只在**同一个行连通块**内上下扩，避免扩到「总伤害」标签上
        rows_any = m_glyph[:, lo:hi + 1].any(axis=1)
        blk = [b for b in _row_blocks(rows_any) if b[0] <= x["r1"] and b[1] >= x["r0"]]
        if blk:
            rr0, rr1 = max(0, blk[0][0]), min(m_glyph.shape[0] - 1, blk[-1][1])
        sub = warm[rr0:rr1 + 1, lo:hi + 1]
        sub = sub / max(1.0, float(sub.max()))
        img = Image.fromarray((sub * 255).astype(np.uint8)).resize((HG.GW, HG.GH), Image.BILINEAR)
        items.append({"kind": "digit", "gray": np.asarray(img, dtype=np.float32) / 255.0,
                      "w": hi - lo + 1, "h": int(rr1 - rr0 + 1),
                      "mass": x["mass"], "xa": lo, "xb": hi})

    hs = [x["h"] for x in items]
    mass_tot = float(sum(x["mass"] for x in items))
    h_med = float(np.median(hs)) if hs else 0.0
    # 字形宽度的一致性：同一串数字的字宽只该有"窄 1"这一种例外。
    # ⚠️ t=26 实测：一束亮光带与最左那个 "1" 粘成一个 66px 宽的块（单字正常 45~54），
    # 分类器把它读成 "3" → **自信地给错数**。宽/中位 > 1.35 的读数一律降级为待复核。
    dw = [x["w"] for x in items if x["kind"] == "digit"]
    w_med = float(np.median(dw)) if dw else 0.0
    w_ratio = (max(dw) / w_med) if (dw and w_med > 0) else 1.0
    fills = [x["mass"] / float(max(1, x["w"] * x["h"]))
             for x in items if x["kind"] == "digit"]
    fill_min = float(min(fills)) if fills else 0.0
    invisible = (not items) or h_med < cfg["invis_h"] or mass_tot < cfg["invis_mass"]
    meta = {"n_runs": len(merged), "n_linked": len(linked), "n_items": len(items),
            "n_digits": sum(1 for x in items if x["kind"] == "digit"),
            "chain": chain, "adv": round(adv, 1), "h_med": h_med, "mass": mass_tot,
            "w_med": w_med, "w_ratio": round(w_ratio, 3), "fill_min": round(fill_min, 3),
            "runs": [{"xa": m[0], "xb": m[1], "w": m[1] - m[0] + 1} for m in merged],
            "linked": [[m[0], m[1]] for m in linked],
            "cands": cands,
            "invisible": bool(invisible),
            "reason": ("字高中位 %.0f < %.0f 或墨迹质量 %.0f < %.0f（HUD 不可见/极暗）"
                       % (h_med, cfg["invis_h"], mass_tot, cfg["invis_mass"])) if invisible else ""}
    return items, meta


def load_model(profile="default"):
    import read_hud
    return read_hud.load_model(profile)


# ══════════════════════════════════════════════════════════════════════════
# 第二种字体（像素方块体）：**录屏2 里它不只出现在"银狼强普"，而是常态出现**
#   实测：录屏2 t=100 读 `506286`、t=238 读 `123692` 都是像素体。
#   A 线已有该字体的档案（`hud_profiles.PROFILES["yinlang999"]`，分类器已训练），
#   但它的裁剪框是给录屏1 标的 `(250,2400,360,2870)`；录屏2 的像素体字距更大，
#   这里用我们自己按 12 位放开的框，并用**同一套掩膜口径**（青绿填充，`hud_glyphs.cyan_mask`）。
# ══════════════════════════════════════════════════════════════════════════
CYAN_CFG = {
    "w_max": 80,        # 实测像素体单字宽 20~71
    "h_min": 40,        # 真字形高 49~94；碎片 8~34
    "h_max": 118,       # 超过它就不是这套字形（t=200 的满屏蓝光块 h=148 → 必须拒）
    "mass_min": 300,    # 真字形质量 600~2100；碎片 1~170
    "ratio_min": 0.20,
    "gap": 24,          # 实测相邻字形空隙 5~20
    "adv": 59.0,        # 实测字距
    "adv_ratio": 1.2,   # 字距 ≈ 单字宽 × 1.2（t=100 实测 52→57；t=238 实测 45.5→60）
    "invis_h": 40.0,
    "invis_mass": 300.0,
    "placeholders": True,
    # 粘连块的**保守切分**（只对像素体开）。上游 `hud_glyphs._split_wide_off` 记着"宁可不拆"，
    # 那次教训是"把一个 71px 宽的单字 '2' 劈成两半"—— 那时 adv=59 → 71/59=1.20。
    # 这里只在 **w ≥ 1.6×adv** 时才动手（单字最宽 71 = 1.2×adv，绝不会被切），
    # 且切点在本块内**墨迹最少的列**（真字间隙的列墨迹≈0），不是"理想位置"硬下刀。
    "split_wide": True,
    "split_min_ratio": 1.6,
    # 左边界贴框 = 区域被切（满屏特效块）→ 整帧不认这套字体
    "edge_guard": 3,
}


def _narrow_cyan(c):
    """更严的青色掩膜：只留亮青核心。用于**找切点**（越大越容易分开相邻字）。"""
    R, G, B = c[:, :, 0], c[:, :, 1], c[:, :, 2]
    return ((G - R) > 60) & (G > 200)


def _seg_cyan(c):
    """**列分割**用的青色掩膜：在 A 线 `cyan_mask` 上收紧一条 `G > B`。

    为什么必须收紧：录屏2 t=200 的整幅画面是一片亮蓝云（背景实测 (168,210,253)：
    `G=210>195`、`G-R=42>25`、`G-B=-43>-45` → **穿过了原掩膜**）→ 分割出一个 734px 宽的
    巨块，整帧读数报废。数字的填充色实测是 (162,255,222)（`G-B=+33`），所以加一条
    `G-B > 8` 就能既保住数字、又挡掉蓝背景。
    ⚠️ 取字形像素仍用 A 线原口径（`cyan_mask` + 填洞），保证与训练时的字形分布一致。
    """
    R, G, B = c[:, :, 0], c[:, :, 1], c[:, :, 2]
    return (G > 195) & ((G - R) > 25) & ((G - B) > 8)


def _split_runs(runs, m_narrow, adv, min_ratio=1.6):
    """把明显是多字粘连的宽块切开（切点 = 局部墨迹最少的列）。返回新的 run 列表。"""
    out = []
    for xa, xb in runs:
        w = xb - xa + 1
        k = int(round(w / max(1.0, adv)))
        if k < 2 or w < min_ratio * adv:
            out.append([xa, xb])
            continue
        cuts = []
        for i in range(1, k):
            ideal = xa + int(round(i * w / float(k)))
            half = max(2, int(round(0.25 * w / k)))
            lo, hi = max(xa + 2, ideal - half), min(xb - 2, ideal + half)
            if hi <= lo:
                cuts.append(ideal)
                continue
            col = m_narrow[:, lo:hi + 1].sum(axis=0)
            cuts.append(lo + int(np.argmin(col)))
        # 去重后按顺序切；若切点数不足 k-1（去重吃掉），退回等分点 —— 保证**切成 k 段**
        cuts = sorted(set(c for c in cuts if xa + 2 < c < xb - 2))
        if len(cuts) < k - 1:
            cuts = sorted(set([xa + int(round(i * w / float(k))) for i in range(1, k)]))
        prev = xa
        for cc in cuts:
            out.append([prev, cc - 1])
            prev = cc
        out.append([prev, xb])
    return out


def _dominant_row_band(m, xa, xb):
    """整串文字所在的行带 = 该 x 范围内**质量最大**的行连通块。

    为什么需要它（t=100 实测）：像素体数字的下方还有一条 UI 条带（区域行 111~147），
    按"每个列段各自取最大行块"会让中间那一段（x=2648~2740）选中下方条带，
    字高从 51 变成 95、字形图变成条带 → 读错/丢字。
    整串文字一定是**同一行带**，用全局行带就把它钉死了。
    """
    row_any = m[:, xa:xb + 1].any(axis=1)
    blocks = _row_blocks(row_any)
    if not blocks:
        return None
    return max(blocks, key=lambda b: int(m[b[0]:b[1] + 1, xa:xb + 1].sum()))


def extract_cyan2(region, cfg=None):
    """像素体字形提取（与 `hud_glyphs.extract_cyan` 同掩膜口径，但**超宽块会占位**）。

    上游 `extract_cyan` 把 >80px 的粘连块**静默丢弃** → 读数少位且无告警；
    这里改成占 `?`（估几个字），下游一看 `?` 就标待复核。
    """
    cfg = dict(CYAN_CFG, **(cfg or {}))
    c = np.asarray(region, dtype=np.int16)
    if c.ndim != 3 or c.shape[0] < 8 or c.shape[1] < 8:
        raise ValueError("HUD 区域太小/是空的：形状 %s" % (c.shape,))
    # 两套**自洽**的口径，各跑一遍（见 read_region_pixel 的说明）：
    #   strict=True  → 分割与取字形都用收紧掩膜（挡蓝云背景，t=200 用）
    #   strict=False → 分割与取字形都用 A 线原掩膜（与训练分布一致，t=45~144 用）
    if cfg.get("strict", True):
        m_seg = _seg_cyan(c)
        m_fill = HG._fill_holes(m_seg)
    else:
        m_seg = HG.cyan_mask(c)
        m_fill = HG._fill_holes(m_seg)
    merged = _runs_from_col(m_seg.any(axis=0))
    if not merged:
        return [], {"n_runs": 0, "invisible": True, "reason": "框内无像素体青绿墨迹"}

    # 字距估计：先用"看起来像单字"的段宽中位数 × adv_ratio（像素体实测 单字宽45 / 字距60）
    single = [r[1] - r[0] + 1 for r in merged
              if (r[1] - r[0] + 1) <= cfg["w_max"] and (r[1] - r[0] + 1) >= 0.5 * cfg["w_max"]]
    adv = float(np.median(single)) * cfg["adv_ratio"] if single else float(cfg["adv"])
    adv = max(float(cfg["adv"]) * 0.7, min(float(cfg["adv"]) * 1.6, adv))
    if cfg.get("split_wide"):
        merged = _split_runs(merged, _narrow_cyan(c), adv, cfg["split_min_ratio"])
    linked = []
    for r in reversed(merged):
        if not linked:
            linked.append(r)
        elif linked[-1][0] - r[1] - 1 <= cfg["gap"]:
            linked.append(r)
        else:
            break
    linked = list(reversed(linked))

    from PIL import Image
    items = []
    # ⚠️ 满屏特效块（如 t=200 的整片蓝光）会把整段连成一个巨块：
    #    贴住区域左界 = 说明框在切一块比框还大的东西，不可能是"总伤害数字"。
    clipped = bool(linked) and linked[0][0] <= cfg["edge_guard"]
    band = _dominant_row_band(m_fill, linked[0][0], linked[-1][1]) if linked else None
    for xa, xb in linked:
        if band is None:
            break
        b0, b1 = band
        sub_band = m_fill[b0:b1 + 1, xa:xb + 1]
        rows = np.where(sub_band.any(axis=1))[0]
        if len(rows) == 0:
            continue
        r0, r1 = int(rows[0]) + b0, int(rows[-1]) + b0
        w = xb - xa + 1
        h = r1 - r0 + 1
        mass = int(m_fill[r0:r1 + 1, xa:xb + 1].sum())
        good = (not clipped and w <= cfg["w_max"] and cfg["h_min"] <= h <= cfg["h_max"]
                and mass >= cfg["mass_min"] and w >= max(6, int(cfg["ratio_min"] * h)))
        if not good:
            if cfg["placeholders"] and w > cfg["w_max"] and not clipped:
                items.append({"kind": "gap", "n": int(max(1, round(w / cfg["adv"]))),
                              "w": w, "h": h, "mass": mass, "xa": xa, "xb": xb, "gray": None})
            continue
        sub = m_fill[r0:r1 + 1, xa:xb + 1]
        g = sub.astype(np.float32)
        img = Image.fromarray((g * 255).astype(np.uint8)).resize((HG.GW, HG.GH), Image.BILINEAR)
        items.append({"kind": "digit", "gray": np.asarray(img, dtype=np.float32) / 255.0,
                      "w": w, "h": h, "mass": mass, "xa": xa, "xb": xb})
    hs = [x["h"] for x in items]
    h_med = float(np.median(hs)) if hs else 0.0
    mass_tot = float(sum(x["mass"] for x in items))
    invisible = (not items) or h_med < cfg["invis_h"] or mass_tot < cfg["invis_mass"]
    meta = {"n_items": len(items), "n_digits": sum(1 for x in items if x["kind"] == "digit"),
            "h_med": h_med, "mass": mass_tot, "invisible": bool(invisible), "clipped": clipped,
            "adv": round(adv, 1),
            "reason": "" if not invisible else
                      "像素体字形不足（字高中位 %.0f / 质量 %.0f）" % (h_med, mass_tot)}
    return items, meta


def _classify_items(model, items, conf_min=0.55):
    """把 items（digit/gap）组成读数串。返回 (text, conf_min, 低位数)。"""
    import torch
    digits = [x for x in items if x["kind"] == "digit"]
    chars, lows, confs = [], 0, []
    if digits:
        x = torch.tensor(np.stack([d["gray"] for d in digits])[:, None], dtype=torch.float32)
        with torch.no_grad():
            p = torch.softmax(model(x), 1)
        cf, pd = p.max(1)
        it = iter(zip(pd.tolist(), cf.tolist()))
    else:
        it = iter(())
    for item in items:
        if item["kind"] == "gap":
            chars.append("?" * item["n"])
            lows += item["n"]
            continue
        d, c = next(it)
        confs.append(c)
        if c >= conf_min:
            chars.append(str(int(d)))
        else:
            chars.append("?")
            lows += 1
    return "".join(chars), (min(confs) if confs else 0.0), lows


def read_region(model, region, origin=HUD_REGION[:2], cfg=None, conf_min=0.55):
    """常规字体读数（见模块头）。"""
    c = dict(CFG, **(cfg or {}))
    items, meta = extract2(region, origin, c)
    if meta["invisible"]:
        return {"text": "", "verdict": "空", "conf": 0.0, "items": items, "meta": meta, "font": "default"}
    text, conf, lows = _classify_items(model, items, conf_min)
    verdict = "ok" if text and "?" not in text else "待复核"
    why = "" if verdict == "ok" else "读数含 '?'"
    # 「一个字形其实是两个字粘在一起」的兜底：宽度比大 **且** 填充率低，
    # 说明这一块是"笔迹 + 弥散光效"的并集（实测 t=26：1.33 / 0.31，被读成 3 → 自信地错）。
    if (verdict == "ok" and meta["w_ratio"] > c["w_ratio_max"]
            and meta["fill_min"] < c["fill_min"]):
        verdict = "待复核"
        why = ("疑似光效与数字粘连（最宽字/字宽中位=%.2f > %.2f 且最低填充率=%.2f < %.2f）→ "
               "不把它当结论" % (meta["w_ratio"], c["w_ratio_max"], meta["fill_min"], c["fill_min"]))
    return {"text": text, "verdict": verdict, "conf": conf, "low": lows, "reason": why,
            "items": items, "meta": meta, "font": "default"}


def _cyan_variant(model_pixel, region, cfg, conf_min, strict):
    c = dict(cfg or {})
    c["strict"] = strict
    items, meta = extract_cyan2(region, c)
    meta["strict"] = strict
    r = {"text": "", "verdict": "空", "conf": 0.0, "items": items, "meta": meta,
         "font": "pixel", "variant": ("pixel_strict" if strict else "pixel_raw")}
    if meta["invisible"]:
        return r
    text, conf, lows = _classify_items(model_pixel, items, conf_min)
    r.update({"text": text, "conf": conf, "low": lows,
              "verdict": "ok" if text and "?" not in text else "待复核"})
    return r


def read_region_pixel(model_pixel, region, cfg=None, conf_min=0.55):
    """像素体读数。

    ⚠️ 要跑**两个变体**并裁决，原因是"取字形像素的掩膜"在录屏2 里两头不讨好：
      * 用 A 线原掩膜（`cyan_mask`，允许 G-B ≥ -45）：t=45/46/53/57 等帧与训练分布一致、读得准，
        但 t=200 那种**整幅蓝云**的画面上，背景会与数字连成实心块 → 认成 000…；
      * 用收紧掩膜（G-B > 8）：t=200 干净，但上面那些帧的字形边缘被削 → 个别字读错。
    两个变体都跑、只在"有且只有一个完整"或"两个相同"时给结论，其余标待复核。
    """
    a = _cyan_variant(model_pixel, region, cfg, conf_min, True)    # 收紧口径（挡蓝云背景）
    b = _cyan_variant(model_pixel, region, cfg, conf_min, False)   # A 线原口径（与训练分布一致）
    raw_bad = b["meta"].get("clipped") or b["verdict"] == "空"
    if not raw_bad:
        out = dict(b)
        note = []
        if a["verdict"] == "ok" and a["text"] != b["text"]:
            note.append("收紧口径读作 %s（本帧原口径贴框=%s，故采信原口径）"
                        % (a["text"], bool(b["meta"].get("clipped"))))
        if b["verdict"] != "ok":
            # 原口径不完整时才去试收紧口径
            if a["verdict"] == "ok":
                out = dict(a)
                out["how"] = "原口径不完整（%s）→ 采用收紧口径" % (b["text"] or "空")
                return out
            out["how"] = "像素体原口径不完整（%s）" % (b["text"] or "空")
            return out
        out["how"] = "；".join(note) or "像素体原口径给出完整读数"
        return out
    # 原口径报废（贴框 / 不可见）→ 只用收紧口径
    if a["verdict"] == "ok":
        out = dict(a)
        out["how"] = ("像素体原口径在本帧报废（%s）→ 采用收紧口径"
                      % ("贴住区域左界（疑似满屏特效）" if b["meta"].get("clipped") else "不可见"))
        return out
    if a["verdict"] == "待复核" or not b["meta"].get("invisible"):
        out = dict(a)
        out.update({"text": "", "verdict": "待复核", "conf": 0.0})
        out["how"] = ("像素体原口径报废（贴框=%s），收紧口径也不完整（%s）——不猜"
                      % (bool(b["meta"].get("clipped")), a["text"] or "空"))
        return out
    out = dict(a)
    out["how"] = a["meta"].get("reason") or "像素体无墨迹"
    return out


def load_pixel_model():
    """像素体分类器（A 线档案 `yinlang999`，已训练：留一帧 94.6%，见 hud_profiles）。"""
    import hud_profiles as HP
    from train_digit_cnn import load_any_pt
    return load_any_pt(HP.require_ready("yinlang999")["model"])


def read_dual(region, origin=HUD_REGION[:2], model=None, model_pixel=None,
              cfg=None, cfg_pixel=None, conf_min=0.55, hint=None):
    """**两套字体各读一遍再裁决**（录屏2 必须这样：两种字体在同一个录屏里交替出现）。

    hint：行动者提示（'银狼' → 倾向像素体）。只是投票的加分项，**不作为唯一依据** ——
    因为"银狼在动"不等于"当前这个数是像素体渲染的"（上一次攻击留下的常规体数字也还在屏幕上）。

    裁决口径（宁可标待复核，不给错数）：
      * 只有一套给出**无 '?'** 的读数 → 采纳它，记 font；
      * 两套都给出无 '?' 的读数且**相同** → 采纳；
      * 两套都给出但**不同** → 判待复核（conflict），把两个候选都留给下游/人工；
      * 两套都带 '?' → 待复核，取位数更全的那个（仅作参考，不给结论）。
    """
    if model is None:
        model = load_model()
    if model_pixel is None:
        model_pixel = load_pixel_model()
    d = read_region(model, region, origin, cfg, conf_min)
    p = read_region_pixel(model_pixel, region, cfg_pixel, conf_min)
    ok_d, ok_p = d["verdict"] == "ok", p["verdict"] == "ok"
    out = {"default": d, "pixel": p, "hint": hint}
    if ok_d and not ok_p:
        out.update({"text": d["text"], "verdict": "ok", "font": "default",
                    "conf": d["conf"], "how": "只有常规体给出完整读数"})
    elif ok_p and not ok_d:
        out.update({"text": p["text"], "verdict": "ok", "font": "pixel",
                    "conf": p["conf"], "how": "只有像素体给出完整读数"})
    elif ok_d and ok_p:
        if d["text"] == p["text"]:
            out.update({"text": d["text"], "verdict": "ok", "font": "both",
                        "conf": max(d["conf"], p["conf"]), "how": "两套字体读数一致"})
        else:
            out.update({"text": "", "verdict": "待复核", "font": "conflict", "conf": 0.0,
                        "how": "两套字体给出不同数（常规体 %s / 像素体 %s）——不猜"
                               % (d["text"], p["text"])})
    else:
        # 都不完整：给一个"信息量最大"的参考，但结论仍是待复核（**不能降级成"空"**：
        # "空"表示屏幕上没有数字，而这里是有东西但读不准，两者对下游的含义完全不同）。
        cands = [x for x in (d, p) if x["text"]]
        pend = [x for x in (d, p) if x["verdict"] == "待复核"]
        if not cands and not pend:
            out.update({"text": "", "verdict": "空", "font": "none", "conf": 0.0,
                        "how": "两套字体都没切出字形（HUD 不可见）"})
        else:
            best = max(cands, key=lambda x: (x["meta"].get("n_digits", 0), -x["text"].count("?"))
                       ) if cands else None
            ref = best or pend[0]
            out.update({"text": "", "verdict": "待复核", "font": ref["font"], "conf": 0.0,
                        "cand": (best or {}).get("text", ""),
                        "how": "两套字体都不完整（常规体 %s / 像素体 %s）"
                               % (d["text"] or "-", p["text"] or "-")})
    return out


def read_crop(model, path, cfg=None, conf_min=0.55):
    """读 `frames/axis2_L2/tXXXX_hud.png`（区域已裁好，原点固定）。"""
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(path)
    region = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return read_region(model, region, origin=HUD_REGION[:2], cfg=cfg, conf_min=conf_min)


def read_crop_dual(path, model=None, model_pixel=None, cfg=None, cfg_pixel=None, hint=None):
    """读已裁好的小块，**两套字体一起裁**（录屏2 的正式入口）。"""
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(path)
    region = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return read_dual(region, origin=HUD_REGION[:2], model=model, model_pixel=model_pixel,
                     cfg=cfg, cfg_pixel=cfg_pixel, hint=hint)


def read_full_dual(full_rgb, model=None, model_pixel=None, cfg=None, cfg_pixel=None, hint=None):
    """整帧（H×W×3 RGB）→ 双字体读数。"""
    y0, x0, y1, x1 = HUD_REGION
    y1, x1 = min(y1, full_rgb.shape[0]), min(x1, full_rgb.shape[1])
    return read_dual(full_rgb[y0:y1, x0:x1], origin=(y0, x0), model=model,
                     model_pixel=model_pixel, cfg=cfg, cfg_pixel=cfg_pixel, hint=hint)


def _cli():
    import argparse
    ap = argparse.ArgumentParser(description="录屏2 HUD 读数（线2）")
    ap.add_argument("times", nargs="*", type=float)
    ap.add_argument("--dir", default="frames/axis2_L2")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--single", action="store_true", help="只跑常规体那一路（诊断用）")
    ap.add_argument("--cfg", default="", help="JSON 覆盖参数，如 {\"chain\":40}")
    args = ap.parse_args()
    cfg = json.loads(args.cfg) if args.cfg else None
    model = load_model()
    model_pixel = None if args.single else load_pixel_model()
    times = args.times or [26, 29, 30, 31, 35, 64, 100, 110, 150, 200, 238, 300, 340]
    out = []
    for t in times:
        p = os.path.join(args.dir, "t%08.2f_hud.png" % t)
        if not os.path.exists(p):
            print("t=%-6s 缺帧 %s" % (t, p))
            continue
        if args.single:
            r = read_crop(model, p, cfg=cfg)
            row = {"t": t, "text": r["text"], "verdict": r["verdict"], "font": "default",
                   "conf": r["conf"], "how": "", "meta": r["meta"]}
        else:
            r = read_crop_dual(p, model=model, model_pixel=model_pixel, cfg=cfg)
            row = {"t": t, "text": r["text"], "verdict": r["verdict"], "font": r["font"],
                   "conf": r["conf"], "how": r.get("how", ""),
                   "meta": {k: r["default"]["meta"].get(k) for k in
                            ("n_digits", "chain", "adv", "h_med", "invisible")},
                   "pixel": {k: r["pixel"]["meta"].get(k) for k in ("n_digits", "h_med")}}
        out.append(row)
        if not args.json:
            print("t=%-6s %-11s %-6s 字体%-9s 置信%.2f  %s"
                  % (t, row["text"] or "(空)", row["verdict"], row["font"], row["conf"], row["how"]))
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
