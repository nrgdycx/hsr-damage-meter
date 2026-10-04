# -*- coding: utf-8 -*-
"""
[线7] 屏幕适配 —— 分辨率/DPI 探测 + **从画面里动态算出两块区域的坐标**。

为什么要有这个文件（用户 2026-10-01 答复 Q2）：
    用户原话：「先做能在我的电脑上用的，我的习惯是固定全屏，然后留下能改进的空间」。
    本轮**只对"本机固定全屏"负责**，但要：
      · 上屏先探测（真实分辨率 + DPI 缩放，避免 B 线踩过的"逻辑像素"坑）；
      · 定位逻辑与坐标**解耦**（结构上不许把 2876×1798 写死）；
      · 留出换分辨率/换宽高比的扩展点（不投入验证）。

三条设计原则（都是从实测来的，别随手改）
---------------------------------------------------------------
1. **不写死绝对坐标**：所有 box 由「帧尺寸 + 画面证据」算出。参考标定值
   （2876×1798 下的 2350/260/88/80 …）只在函数里作为**换算基准**出现，
   不再作为裁剪坐标直接使用。
2. **模型先验 + 证据纠正**（预测-校验，而不是全图搜索）：
   · 先按帧尺寸算出模型预测位置；
   · 再用画面证据（HUD 墨迹 / 行动轴卡上边框脊）去**校验**；
   · 证据与模型相差 ≤ `*_SNAP_PX` 时**采信模型**（逐帧抖动 ≤3px，而 E 线
     实测对 ±3px 位移免疫、±4px 开始翻车，见 docs/行动轴识别.md §5）；
     相差更大时**采信证据**（说明模型的分辨率假设不对，这才是适配真正生效的场合）。
3. **判不出来就退回模型**：画面里找不到证据（HUD 隐藏 / 行动轴在滑入滑出动画里）
   → 用模型预测值。这样"动画帧"的行为与改动前完全一致（E 线本来就该在这些帧判待复核）。

⚠️ 关于"不要用比例坐标"：本文件确实用到 `s = 帧宽 / 参考帧宽`，但它只是**模型先验**，
   真正决定框位置的是画面里测出来的墨迹/卡边框；而且"模型 vs 证据"不一致时以证据为准。
   （统筹会话提过的 `(0.8171*W, 0.1446*H)` 那种纯比例方案才是错的。）

对外接口（给 A 线 / E 线 / B 线 / 线5 用）
---------------------------------------------------------------
    import geometry as SA

    # ① 上屏探测（实时线开跑前调一次）
    SA.probe_display()            # {'screen':(2880,1800), 'dpi':192, 'scale':2.0, ...}

    # ② HUD 数字区（rgb 整帧）—— 取代 hud_glyphs.CX0/CY0 那套常量
    g = SA.hud_geometry(rgb)      # {'box':(y0,x0,y1,x1), 'bar_rows':(a,b), 'k':字号比, 'src':...}

    # ③ 行动轴顶端卡（bgr 整帧）—— 取代 axis_actor.TOP_ART / MARK_C
    a = SA.axis_geometry(bgr)     # {'top_art':(x0,y0,x1,y1), 'mark_c':(x,y), 'mark_r':19, 'card':(...)}

    # ④ 实时线：从一张整屏图算出两块小区域（取代 capture 的硬编码 REGIONS）
    SA.live_regions(rgb_screen)   # {'hud':{left,top,width,height}, 'axis':{...}}

只给形状（没有像素）时也能用：`SA.hud_geometry(shape=(H, W))` 退回模型预测。
"""
from __future__ import annotations

import os

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

# ══════════════════════════════════════════════════════════════════════════
# 0. 参考标定（**只做换算基准**，不是裁剪坐标）
#    来源：录屏1 `records/屏幕录制 2026-09-29 174931.mp4`（2876×1798），
#    由 A 线（HUD）与 E 线（行动轴）各自人工标定并已验收：
#      · HUD 框 (y 260..340, x 2350..2876)：数字墨迹 y 273..334、右缘 x≈2853
#      · 行动轴顶端卡：卡左边框 x=88、卡上边框 y=80 → 头像区 (90,81)-(232,175)
# ══════════════════════════════════════════════════════════════════════════
REF_W, REF_H = 2876, 1798

# ── HUD（总伤害数字）──────────────────────────────────────────────────────
HUD_WIN_Y = (0.00, 0.32)      # 搜索窗（占帧高比例）：右上角那条带
HUD_WIN_X = (0.60, 1.00)      # 搜索窗（占帧宽比例）
HUD_BAND_H_REF = 61.0         # 参考字号"核心行带"高度（录屏1 实测 61，20 帧 61±1）
HUD_ROW_MIN_FRAC = 0.02       # 行阈值 = 帧宽 × 0.02（≈58px）：把光晕尾/淡金线裁掉
HUD_PAD_TOP = 13.0            # 框上界 = 行带顶 − 13·k  （260 = 273 − 13）
HUD_PAD_BOT = 7.0             # 框下界 = 行带底 + 7·k   （340 = 333 + 7）
HUD_PAD_R = 23.0              # 框右界 = 墨迹右 + 23·k（贴屏右缘时直接用屏宽）
HUD_BOX_H = 80.0              # 框高（参考字号）
HUD_CAP_W = 526.0             # 12 位容量宽度（参考字号）→ 按 k 放大，且**不小于**参考容量
BAR_OFF_TOP, BAR_OFF_BOT = 25.0, 37.0   # 装饰金线行带（相对行带顶；298/310 = 273+25/273+37）
HUD_MIN_K, HUD_MAX_K = 0.6, 2.6         # 字号比合理区间（超出即判"这不是稳定读数"）
HUD_K_SNAP = 0.05             # |k−1| ≤ 0.05 视为"参考字号"（行带 ±1px 是测量噪声）
HUD_RIGHT_SNAP = 70.0         # 行带右缘离屏右缘多近才算"右对齐的 HUD"（参考字号 px）
HUD_CHAIN_GAP = 30.0          # 同串数字相邻字形的最大空隙（参考字号 px，按 k 缩放）
HUD_ASPECT = (0.15, 1.75)     # 单字宽高比区间（挡掉"总伤害"底下那条金色横条 w/h≈6）

# ── 行动轴顶端卡 ─────────────────────────────────────────────────────────
AXIS_LEFT_REF, AXIS_TOP_REF = 88, 80    # 卡边框（人工标定）
AXIS_CARD_W, AXIS_CARD_H = 195, 95      # 卡尺寸（人工标定；卡右下边框不是稳定脊，见 §5）
AXIS_ART_INSET = (2, 1, 142, 94)        # 头像区 = 卡左上 + inset → (90,81)-(232,175)
MARK_OFF = (-2, 47)                     # 左标记中心 = 卡左上 + offset → (86,127)
MARK_R_REF = 19
AXIS_RAIL_DX = -33                      # 轴面板左缘那条竖线 x = 卡左边框 − 33（实测 55）
AXIS_RIDGE_THR = 8.0                    # 卡上边框"脊"的分数下限（实测真卡 ≥8.5、背景 ≤2）
AXIS_RIDGE_WIN = 25                     # 脊搜索半径（px，相对模型预测）：模型偏差超过它就纠正不了
AXIS_SNAP_PX = 4.0                      # 模型/证据相差 ≤4px 时采信模型（避免逐帧抖动）
AXIS_RAIL_FRAC = 0.5                    # 竖线"像线"的行占比阈值（实测轴在时 ≥0.50）


# ══════════════════════════════════════════════════════════════════════════
# 1. 上屏探测：真实分辨率 + DPI 缩放
# ══════════════════════════════════════════════════════════════════════════
_DPI_DONE = False


def enable_dpi_awareness() -> bool:
    """让本进程按**物理像素**看屏幕（复用 B 线的实现，避免两处漂移）。"""
    global _DPI_DONE
    if _DPI_DONE:
        return True
    try:
        from capture import enable_dpi_awareness as _f
        _DPI_DONE = bool(_f())
    except Exception:                                     # noqa: BLE001
        try:
            import ctypes
            _DPI_DONE = bool(ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)))
        except Exception:                                 # noqa: BLE001
            _DPI_DONE = False
    return _DPI_DONE


def probe_display(use_mss: bool = True) -> dict:
    """
    上屏探测：返回实际分辨率、DPI 缩放与显示器列表。

    ⚠️ 必须在**创建任何抓屏对象之前**调用（内部已声明 DPI 感知）。B 线的教训：
    不声明 DPI 感知时 GetSystemMetrics 与 mss 都只报逻辑像素（如 1440×900），
    用物理坐标（如 x=2350）去裁就会裁错地方。
    """
    out = {"dpi_aware": False, "dpi": None, "scale": None, "screen": None,
           "logical": None, "monitors": [], "notes": []}
    logical = None
    try:
        import ctypes
        u = ctypes.windll.user32
        logical = (int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1)))
    except Exception as e:                                # noqa: BLE001
        out["notes"].append("取逻辑分辨率失败：%s" % e)

    out["dpi_aware"] = enable_dpi_awareness()

    try:
        import ctypes
        u = ctypes.windll.user32
        sw, sh = int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1))
        out["screen"] = (sw, sh)
        try:
            dpi = int(u.GetDpiForSystem())
        except Exception:                                 # noqa: BLE001
            g = ctypes.windll.gdi32
            dpi = int(g.GetDeviceCaps(u.GetDC(0), 88))     # LOGPIXELSX
        out["dpi"] = dpi
        out["scale"] = round(dpi / 96.0, 3)
        out["logical"] = logical
        if not out["dpi_aware"]:
            out["notes"].append("DPI 感知声明失败 → 上面这个分辨率可能只是逻辑像素")
        elif logical and logical != (sw, sh):
            out["notes"].append("逻辑 %s → 物理 %s（缩放 %.0f%%），已按物理像素工作"
                                % (logical, out["screen"], 100.0 * (out["scale"] or 1.0)))
    except Exception as e:                                # noqa: BLE001
        out["notes"].append("取物理分辨率/DPI 失败：%s" % e)

    if use_mss:
        try:
            import sys
            sys.path.insert(0, os.path.join(HERE, "vendor"))
            import mss
            cls = getattr(mss, "MSS", None) or mss.mss
            with cls() as sct:
                out["monitors"] = [dict(m) for m in sct.monitors]
        except Exception as e:                            # noqa: BLE001
            out["notes"].append("mss 显示器列表取不到（不影响离线使用）：%s" % e)
    return out


# ══════════════════════════════════════════════════════════════════════════
# 2. HUD（总伤害数字）：从"墨迹"反推裁剪框
# ══════════════════════════════════════════════════════════════════════════
def _as_rgb(frame, order="rgb"):
    """统一成 RGB int16 数组。order='bgr' 时做一次通道翻转。"""
    a = np.asarray(frame)
    if a.ndim == 2:
        a = np.stack([a] * 3, -1)
    a = a[:, :, :3].astype(np.int16)
    if order.lower() == "bgr":
        a = a[:, :, ::-1].copy()
    return a


def _streak(m, ker_w):
    """又长又细的横条（UI 装饰金线）：它会把整串数字连成一块，定位前先剔掉。"""
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (max(5, int(ker_w)), 1))
    return cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, k).astype(bool)


def hud_ink(rgb) -> dict | None:
    """
    在右上角找到「总伤害数字」这一串墨迹。返回 dict 或 None（找不到 → 上层退回模型）。

    做法（**行带 + 列链**，每一步都是被实测逼出来的）：
      1. 搜索窗 = 右上角一条带（与分辨率无关的先验：HUD 锚在屏幕右上角）；
      2. 掩膜 = 淡黄辉光 ∪ 饱和黄核心（`hud_glyphs.locator_masks`，与提取同源）；
      3. **行带**：按行统计墨迹像素，取 ≥ 帧宽×0.02 的行（实测这个阈值正好裁掉
         光晕尾巴与淡金线：录屏1 常规字号稳定得到 61px 高的行带）；
         —— 为什么不用连通块：装饰金线会**横穿**数字，把每个字切成上下两半，
         连通块方法会切碎（实测 t=141.8 只链到 4 个字、字号估成 0.93）；
      4. 保留"右对齐"的行带（右缘距屏右缘 ≤70px）且字号比在 [0.6, 2.6] 内的候选，
         取墨迹最多的那条（数字串的墨迹远多于飘字/特效能形成的条带）；
      5. **列链**：行带内按列取段、从最右一段向左链式合并（空隙 ≤ 30k）→ 得到整串的
         左右缘与单字宽高比，用于交叉校验（末位是 '1' 时右缘偏窄，所以右缘另有贴屏规则）。
    """
    import hud_glyphs as HG

    a = _as_rgb(rgb, "rgb")
    H, W = a.shape[:2]
    s = W / float(REF_W)
    ywin = max(1, int(HUD_WIN_Y[1] * H))
    x0 = int(HUD_WIN_X[0] * W)
    c = a[0:ywin, x0:W]

    glow, core = HG.locator_masks(c)
    m = glow | core
    rowsum = m.sum(axis=1)
    thr = max(6.0, HUD_ROW_MIN_FRAC * W)
    idx = np.where(rowsum >= thr)[0]
    if len(idx) == 0:
        return None

    bands, st, prev = [], idx[0], idx[0]
    for r in idx[1:]:
        if r - prev <= 6:
            prev = r
        else:
            bands.append((int(st), int(prev)))
            st = prev = r
    bands.append((int(st), int(prev)))

    best = None
    for (b0, b1) in bands:
        h = b1 - b0 + 1
        k = h / HUD_BAND_H_REF
        if h < 24 * s or not (HUD_MIN_K <= k / max(s, 1e-6) <= HUD_MAX_K):
            continue
        sub = m[b0:b1 + 1]
        cols = np.where(sub.any(axis=0))[0]
        if len(cols) == 0:
            continue
        ink_x0, ink_x1 = int(cols.min()) + x0, int(cols.max()) + x0
        if W - ink_x1 > HUD_RIGHT_SNAP * max(s, 1.0):
            continue                                  # 不贴右缘 → 不是 HUD 数字串
        ink = int(sub.sum())
        if best is None or ink > best["ink"]:
            best = {"band": (b0 + 0, b1 + 0), "k": k, "ink": ink,
                    "x0": ink_x0, "x1": ink_x1, "h": h}
    if best is None:
        return None

    b0, b1 = best["band"]
    # ── 列链：行带内按列分段，从最右一段向左串（HUD 右对齐，最右一段必属数字串）──
    sub = m[b0:b1 + 1]
    col = sub.any(axis=0)
    runs, s0 = [], None
    for x in range(len(col)):
        if col[x] and s0 is None:
            s0 = x
        elif not col[x] and s0 is not None:
            runs.append([s0, x - 1])
            s0 = None
    if s0 is not None:
        runs.append([s0, len(col) - 1])
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] - 1 < 3:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    chain, gap_max = [], HUD_CHAIN_GAP * max(0.5, best["k"])
    for r in reversed(merged):
        w = r[1] - r[0] + 1
        if not chain:
            chain.append(r)
        elif chain[0][0] - r[1] - 1 <= gap_max:
            chain.insert(0, r)
        else:
            break
    # 单字宽高比过滤：金线残段/糊成一团的亮块（w/h 远超单字）不算字。
    # 若一段都不剩 → 这块不是 HUD 数字串 → 退回模型（宁可退，不要乱动）
    chain = [r for r in chain
             if HUD_ASPECT[0] <= (r[1] - r[0] + 1) / float(best["h"]) <= HUD_ASPECT[1]]
    if not chain:
        return None

    xs = min(r[0] for r in chain) + x0
    xe = max(r[1] for r in chain) + x0
    hl = [r[1] - r[0] + 1 for r in chain]
    return {"band": (b0, b1), "h": best["h"],
            "k": best["k"], "n": len(chain), "ink": best["ink"],
            "x0": xs, "x1": xe,
            "ink_x1": best["x1"], "med_run_w": float(np.median(hl)) if hl else 0.0,
            "runs": [(r[0] + x0, r[1] + x0) for r in chain]}


def hud_geometry(rgb=None, shape=None) -> dict:
    """
    HUD 数字区的动态坐标。

    rgb   : 整帧（RGB；BGR 请先翻转，或用 `geometry(frame, order="bgr")`）
    shape : (H, W) —— 只给尺寸时退回模型预测（没有画面证据可校验）

    返回 {'box':(y0,x0,y1,x1), 'bar_rows':(a,b), 'k':字号比, 'src':'ink'|'model', 'ink':...}
      · box 右缘锚定**数字墨迹右缘**（HUD 数字右对齐），再按字号比放大"12 位容量"宽度；
      · bar_rows 是"装饰金线行带"，要传给 `hud_glyphs.extract(bar_rows=...)`：
        分割前挖空这几行，才能把金线与最左数字断开（线4/线A 都栽在这上面过）。
    """
    if rgb is None:
        H, W = int(shape[0]), int(shape[1])
        s = W / float(REF_W)
        x1 = W
        x0 = max(0, int(round(x1 - HUD_CAP_W * s)))
        y0 = int(round(260 * s))
        y1 = int(round(y0 + HUD_BOX_H * s))
        return {"box": (y0, x0, y1, x1), "bar_rows": (int(round(298 * s)), int(round(310 * s))),
                "k": round(s, 3), "src": "model", "size": (H, W), "ink": None}

    H, W = np.asarray(rgb).shape[:2]
    ink = hud_ink(rgb)
    if not ink:
        return hud_geometry(shape=(H, W))
    # 参考字号判定：行带高 ±1px 是测量噪声，不是字号变化 → 落在这条带里的一律当参考字号
    # （否则 x0 会随 ±1px 抖动 ±9px；实测就是这么抖的）。超出则按实测字号等比放大。
    s = W / float(REF_W)
    k_raw = ink["k"]
    k = s if abs(k_raw - s) <= HUD_K_SNAP * max(s, 1e-6) else k_raw
    b0, b1 = ink["band"]
    y0 = int(round(b0 - HUD_PAD_TOP * k))
    y1 = int(round(b1 + HUD_PAD_BOT * k))
    # 右缘：末位是 '1' 时墨迹右缘会偏窄（实测 2845 vs 2853），所以"贴着屏右缘"的数字串
    # 一律锚到屏右缘（HUD 是右对齐的，屏右缘才是与分辨率无关的那个锚）。
    if W - ink["ink_x1"] <= HUD_RIGHT_SNAP * max(1.0, s):
        x1 = W
    else:
        x1 = int(min(W, round(ink["ink_x1"] + HUD_PAD_R * k)))
    # 容量：按实测字号放大，但**不小于"分辨率期望字号"的容量** —— 宁可宽一点：
    # 宽了只是多带点背景，窄了会切掉最高位（录屏2 就是被窄框切掉最高位的，
    # 见 docs/HUD数字读取.md）
    x0 = int(max(0, round(x1 - HUD_CAP_W * max(k, s))))
    bar = (int(round(b0 + BAR_OFF_TOP * k)), int(round(b0 + BAR_OFF_BOT * k)))
    return {"box": (y0, x0, y1, x1), "bar_rows": bar, "k": round(k, 4), "src": "ink",
            "size": (H, W), "ink": ink}


def hud_box_for_frame(rgb):
    """A 线用的便捷入口：返回 (box, bar_rows)。"""
    g = hud_geometry(rgb)
    return g["box"], g["bar_rows"]


# ══════════════════════════════════════════════════════════════════════════
# 3. 行动轴顶端卡
# ══════════════════════════════════════════════════════════════════════════
def _gray_bgr(bgr):
    a = np.asarray(bgr)
    if a.ndim == 2:
        return a.astype(np.float32)
    a = a[:, :, :3]
    if a.dtype != np.uint8:               # cvtColor 只吃 uint8（int16 会报 Unsupported depth）
        a = np.clip(a, 0, 255).astype(np.uint8)
    return cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32)


def axis_ridge_top(g, pred_top, pred_left, s):
    """
    找"顶端卡的上边框"：一条横跨卡面的亮线，比它上方/下方各 9px 都亮。

    实测（录屏1 23 帧 + 录屏2 4 帧）：真卡上边框给出 78~80 的脊峰（分数 8.8~108），
    框外背景/标题栏 ≤2、且标题栏那条线在 y≈52 不落在预测窗内。
    """
    x0 = int(pred_left + 8)
    x1 = int(min(g.shape[1] - 1, pred_left + 150))
    off = max(2, int(round(9 * s)))        # 比较距离随缩放走：整屏缩小时边框线只有 1px，
    ylo = max(off + 1, int(round(pred_top - AXIS_RIDGE_WIN)))   # 固定 ±9 会把脊信号中位掉
    yhi = int(round(pred_top + AXIS_RIDGE_WIN))                 # （实测 s=0.667 时 54→2）
    best = (0.0, None)
    for y in range(ylo, yhi + 1):
        band = g[y, x0:x1]
        d = np.minimum(band - g[y - off, x0:x1], band - g[y + off, x0:x1])
        sc = float(np.median(d))
        if sc >= AXIS_RIDGE_THR and (best[1] is None or y < best[1]):
            best = (sc, y)                 # 取**最上面**那个过阈值的脊
    if best[1] is None:
        return None, 0.0
    return best[1], best[0]


def axis_rail(g, pred_left, s=1.0):
    """找轴面板左缘那条竖线（实测 x=55 = 卡左边框−33；面板隐藏时它消失）。"""
    nb = max(2, int(round(4 * s)))
    best = (None, 0.0)
    for x in range(max(nb + 1, int(pred_left - 45 * max(s, 1.0))), int(pred_left - 24 * max(s, 1.0))):
        col = g[:, x]
        d = col - (g[:, max(0, x - nb)] + g[:, min(g.shape[1] - 1, x + nb)]) / 2.0
        frac = float((d[:1300] > 12).mean())
        if frac > best[1]:
            best = (x, frac)
    return best if best[1] >= AXIS_RAIL_FRAC else (None, best[1])


def axis_geometry(bgr=None, shape=None, s=None, refine=False) -> dict:
    """
    行动轴顶端卡（当前行动者所在槽）的动态坐标。

    bgr   : 整帧 BGR（cv2）
    shape : (H, W) —— 只有尺寸时用模型
    s     : 分辨率系数（默认 帧宽/参考帧宽）
    refine: **是否让画面证据顶掉模型**（默认 False）。

    ⚠️ 为什么默认不顶：实测在 249 帧里有 5 帧（t=194/237/256/306/322，都是轴在滑动/被亮特效盖住
    的帧）证据会跑偏。最坏的一例 t=194：卡上方有一条亮特效带，脊检测器把它当成"卡上边框"
    （分数 20 > 卡自己那条边框的 3），于是框上移 22px，把一次**本来判对的『死龙』**变成待复核
    → 会改掉 E 线的 CSV、进而可能动到线4/线8 的事件表。本线的验收不含"改 E 线行为"，
    所以默认只把证据当**校验**（`suspect=True` 标出来），要纠正得显式 `refine=True`。

    返回 {'top_art':(x0,y0,x1,y1), 'mark_c':(x,y), 'mark_r':r, 'card':(l,t,r,b),
          'left':.., 'top':.., 'src':'detect'|'model', 'suspect':bool,
          'rail':{...}, 'ridge':{...}, 'pred':(left,top)}
    """
    if bgr is None:
        H, W = int(shape[0]), int(shape[1])
        g = None
    else:
        g = _gray_bgr(bgr)
        H, W = g.shape[:2]
    if s is None:
        s = W / float(REF_W)

    pred_left = AXIS_LEFT_REF * s
    pred_top = AXIS_TOP_REF * s
    left, top = pred_left, pred_top
    rail = ridge = None
    src = "model"
    suspect = False

    if g is not None:
        rx, rfrac = axis_rail(g, pred_left, s)
        rail = {"x": rx, "frac": round(rfrac, 3)}
        ry, rscore = axis_ridge_top(g, pred_top, pred_left, s)
        ridge = {"y": ry, "score": round(rscore, 2)}
        if ry is not None and abs(ry + 1.0 - pred_top) > AXIS_SNAP_PX:
            suspect = True
        if rx is not None and abs(rx + abs(AXIS_RAIL_DX) * s - pred_left) > AXIS_SNAP_PX:
            suspect = True
        if refine:
            if ry is not None:
                cand = ry + 1.0                # 脊峰实测比人工标定线高 1px
                if abs(cand - pred_top) > AXIS_SNAP_PX:
                    top, src = cand, "detect"  # 证据与模型差得多 → 模型的分辨率假设不对
            if rx is not None:
                cl = rx + abs(AXIS_RAIL_DX) * s
                if abs(cl - pred_left) > AXIS_SNAP_PX:
                    left, src = cl, "detect"

    art = (int(round(left + AXIS_ART_INSET[0] * s)), int(round(top + AXIS_ART_INSET[1] * s)),
           int(round(left + (AXIS_ART_INSET[0] + AXIS_ART_INSET[2]) * s)),
           int(round(top + (AXIS_ART_INSET[1] + AXIS_ART_INSET[3]) * s)))
    mark = (int(round(left + MARK_OFF[0] * s)), int(round(top + MARK_OFF[1] * s)))
    card = (int(round(left)), int(round(top)),
            int(round(left + AXIS_CARD_W * s)), int(round(top + AXIS_CARD_H * s)))
    if g is not None:
        if art[2] > W or art[3] > H or art[0] < 0 or art[1] < 0:
            raise ValueError("帧尺寸 %dx%d 太小，放不下顶端卡区域 %s（参考 %dx%d）"
                             % (W, H, art, REF_W, REF_H))
    return {"top_art": art, "mark_c": mark, "mark_r": int(round(MARK_R_REF * s)),
            "card": card, "left": int(round(left)), "top": int(round(top)),
            "s": round(s, 4), "src": src, "suspect": suspect, "refine": bool(refine),
            "rail": rail, "ridge": ridge,
            "pred": (int(round(pred_left)), int(round(pred_top)))}


# ══════════════════════════════════════════════════════════════════════════
# 4. 统一入口 + 实时线区域
# ══════════════════════════════════════════════════════════════════════════
def geometry(frame, order="rgb") -> dict:
    """一帧 → 两块区域的全部坐标。order='bgr' 时输入的通道顺序是 BGR。"""
    a = _as_rgb(frame, order)          # 统一成 RGB 再分发（HUD 用 RGB，行动轴用 BGR）
    bgr = np.ascontiguousarray(a[:, :, ::-1]) if order != "bgr" else np.asarray(frame)[:, :, :3]
    return {"size": a.shape[:2], "hud": hud_geometry(a), "axis": axis_geometry(bgr)}


def _to_bgr(frame):
    a = np.asarray(frame)
    if a.ndim == 2:
        return cv2.cvtColor(a, cv2.COLOR_GRAY2BGR)
    return np.ascontiguousarray(a[:, :, :3][:, :, ::-1])


def live_regions(rgb_screen, pad_axis_bottom=None) -> dict:
    """
    实时线用：给一张**整屏** RGB 图（一次全屏抓屏），算出两块小区域矩形。

    产出的 dict 直接能喂 mss / `capture.Grabber.grab_rgb`。
    这就是"上屏先探测"的落地：先抓一张全屏 → 定位 → 之后只抓这两块小区域。
    """
    a = _as_rgb(rgb_screen, "rgb")
    H, W = a.shape[:2]
    ax_bottom = pad_axis_bottom if pad_axis_bottom is not None else int(round(0.70 * H))
    g = hud_geometry(a)
    ax = axis_geometry(_to_bgr(a))
    y0, x0, y1, x1 = g["box"]
    hud = {"left": int(x0), "top": int(y0), "width": int(max(1, x1 - x0)),
           "height": int(max(1, y1 - y0))}
    l, t, r, b = ax["card"]
    # 实时线要抓的"行动轴列"：左到卡左 −28（含左标记），右到卡右 +57。
    # 这两个余量就是参考区域 (60,0,280,1250) 相对卡框 (88..283) 的余量，取同值以免
    # 换分辨率后有人依赖的区域被悄悄缩小。
    axis_left = int(max(0, l - 28))
    axis = {"left": axis_left, "top": 0,
            "width": int(min(W, r + 57) - axis_left),
            "height": int(min(H, ax_bottom))}
    return {"hud": hud, "axis": axis, "hud_geometry": g, "axis_geometry": ax}


def scale_of(shape) -> float:
    """帧尺寸 → 分辨率系数（与 axis_actor.scale_of 同口径，保留给旧调用）。"""
    return np.asarray(shape)[1] / float(REF_W)


if __name__ == "__main__":
    import json
    print("上屏探测：")
    print(json.dumps(probe_display(), ensure_ascii=False, indent=1))
