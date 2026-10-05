# -*- coding: utf-8 -*-
"""
[A 线] HUD 字形提取的唯一实现 —— 训练（digit_dataset.py）与推理（read_hud.py）都调这里。

为什么单独抽出：原来 digit_dataset.frame_glyphs() 与 read_hud.extract_glyphs() 是两份
复制粘贴的代码，铁律要求"改裁剪/掩膜必须同步"，靠人记很容易漂移。现在只有这一份。

模式（mode）：
  glow  : 只用淡黄辉光层（原有行为，B>=185）。缺点：数字的饱和黄笔画核心被掏空成洞。
  fill  : glow + 孔洞填充 → 实心剪影。
  union : glow ∪ 饱和黄核心，再填洞 → 完整剪影。
  core  : 只用饱和黄核心。
默认模式由 out/mask_exp_A.json 的实验结论决定（见 MASK_MODE）。
"""
import os

import cv2
import numpy as np

# ── 固定几何（绝对坐标；与 read_hud 的历史值一致，不要随手改）──
CY0, CY1 = 260, 340
CX0, CX1 = 2350, 2876
BAR_ROWS = (298, 310)      # 数字左侧细横线所在行带，分割时挖空以断开粘连
W_MAX = 52
H_MIN = 30
GW, GH = 24, 34            # 归一化尺寸

# ── 提取配置（A 线实测结论，改这里即全链路生效）──
# MASK_MODE  : 列分割用。辉光层最稳（25 帧里 23 全对 + 1 缺左1位，可用率 96%）；
#              若改用「核心∪辉光」做分割会掉到 68% —— 它把背景金线也吃进来，
#              金线与最左数字粘成超宽块，反而整段丢数字。
# GLYPH_MODE : 取字形像素用。现用掩膜 (B>=185) 只取淡黄辉光层，而数字笔画核心是
#              饱和黄 (B≈150)；某帧辉光一弱，笔画就被掏空 → 实测出错字形只有 23px 宽
#              （正常 29~33px），放大看是一堆碎片。改用核心∪辉光+填洞后笔画完整，
#              但必须去掉背景金线（否则它是超宽亮块，会变成"假字"）。
# EXPAND_MAX : 用完整字形掩膜向外扩的上限（px），找回被弱辉光切掉的边缘。
MASK_MODE = "glow"
GLYPH_MODE = "hybrid_s"
EXPAND_MAX = 3
STREAK_K = 80              # 长横条（UI 装饰金线）检测核宽：数字最宽 52，不会被误判为横条
# 有效性判定的自校准参数（见 _extract_core 里的详细来历）
MASS_MIN = 120.0           # 字形像素质量的绝对下限（实测真字形 ≥350、碎片 ≤93）
MASS_FRAC = 0.20           # 相对本串"明显是字"的中位质量
H_FRAC = 0.45              # 相对本串中位高度（同一串必然同字号）
RATIO_MIN = 0.22           # 宽高比下限（实测真字形 ≥0.26、碎片 ≤0.10）


def _fill_holes(b):
    """二值图孔洞填充：从边界 floodFill 背景，未被填到的就是内部孔洞。"""
    u = b.astype(np.uint8) * 255
    h, w = u.shape
    m = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(u, m, (0, 0), 255)
    holes = cv2.bitwise_not(u)
    return b | (holes > 0)


def _streak(m):
    """检出「又长又细的横条」= UI 装饰金线。数字单字最宽 52px，开运算核取 80 不会误伤。"""
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (STREAK_K, 1))
    return cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, k).astype(bool)


def locator_masks(c):
    """
    给「线7 动态定位」用的两种掩膜：淡黄辉光层 glow / 饱和黄核心 core。

    与 `_masks` 用**同一组阈值**（这里是唯一实现，`_masks` 反过来调它），
    理由和"提取只有一份实现"一样：定位看到的"哪里有数字"和真正被读的像素
    必须来自同一套阈值，否则会出现"框定在一个地方、字却切不出来"的鬼故事。
    """
    R, G, B = c[:, :, 0], c[:, :, 1], c[:, :, 2]
    glow = (R > 225) & (G > 225) & (B >= 185) & ((R - B) > 25)
    core = ((np.minimum(R, G) - B) > 45) & (R > 180)
    return glow, core


def _masks(c, mode):
    """
    返回 (m_seg, m_glyph, warm)：
      m_seg   —— 只用于【列分割】（决定每个字形的 x 范围）
      m_glyph —— 用于【取字形像素】（决定字形长什么样）
    对多数模式两者相同；hybrid 系列故意不同，理由见下。

    hybrid 的来历（两条实测证据拼起来的结论）：
      · 主会话实测：出错字形只有 23px 宽（正常 30~33px），放大后是一堆碎片
        → 字形在【提取阶段】就被切坏了，不是分类器的锅；
      · 本会话实测：现用掩膜 (B>=185) 只取【淡黄辉光层】，而数字的笔画核心是
        【饱和黄】(B≈150) —— 某帧辉光一弱，笔画就被掏空成洞。
    但直接用"核心∪辉光"做分割会失败（实测可用率只有 68%）：它把背景金线也吃进来，
    金线与最左数字粘成超宽块 → 反而丢数字。
    所以：**分割用辉光层（实测 96% 可用），取字形像素用核心∪辉光+填洞**。
    """
    R, G, B = c[:, :, 0], c[:, :, 1], c[:, :, 2]
    glow, core = locator_masks(c)
    warm = np.clip(np.minimum(R, G) - B, 0, 255).astype(np.float32)

    def with_warm(m):
        w = warm.copy()
        w[~m] = 0.0
        return w

    if mode == "glow":
        return glow, glow, with_warm(glow)
    if mode == "fill":
        m = _fill_holes(glow)
        w = np.where(m, np.maximum(warm, 60.0), 0.0).astype(np.float32)   # 补出来的洞给个下限亮度
        return m, m, w
    if mode == "union":
        m = _fill_holes(glow | core)
        w = np.where(m, np.maximum(warm, 60.0), 0.0).astype(np.float32)
        return m, m, w
    if mode in ("union_s", "union_sf"):
        m = _fill_holes(glow | core)
        m = m & ~_streak(m)
        if mode == "union_sf":
            m = _fill_holes(m)
        w = np.where(m, np.maximum(warm, 60.0), 0.0).astype(np.float32)
        return m, m, w
    if mode == "core":
        m = _fill_holes(core)
        return m, m, with_warm(m)
    if mode in ("hybrid", "hybrid_f", "hybrid_s"):
        m_glyph = _fill_holes(glow | core)
        if mode == "hybrid_s":
            m_glyph = m_glyph & ~_streak(m_glyph)      # 金线必须去掉：它是超宽亮块，会变成假字
        w = np.where(m_glyph, np.maximum(warm, 60.0), 0.0).astype(np.float32)
        return glow, m_glyph, w
    raise ValueError("unknown mode: %r" % mode)


def _extract_core(c, origin, mode, glyph_mode, expand, bar_rows=None):
    """
    c      : 已裁好的 HUD 区域 RGB（int16），形状 h×w×3
    origin : c[0,0] 在整帧里的绝对坐标 (y, x) —— BAR_ROWS 是绝对 y，必须靠它换算
    bar_rows : 装饰金线所在行带（绝对 y）。默认用参考标定的 BAR_ROWS；线7 起由
             `geometry.hud_geometry()['bar_rows']` **按实测字号**给出，
             换分辨率/换字号时金线也跟着走，不会再出现"挖空挖错行 → 金线把数字连成一块"。
    返回 [(gray float32 GH×GW, 像素宽 w, 像素高 h), ...]
    """
    m_seg, m_glyph, warm = _masks(c, mode)
    if glyph_mode and glyph_mode != mode:
        _, m_glyph, warm = _masks(c, glyph_mode)
    # 分割前把细横线所在行带挖空（用绝对坐标换算到本区域内的行号）；只作用于分割
    rows = BAR_ROWS if bar_rows is None else bar_rows
    ms = m_seg.copy()
    r0, r1 = max(0, rows[0] - origin[0]), min(m_seg.shape[0] - 1, rows[1] - origin[0])
    if r0 <= r1 and r0 < m_seg.shape[0]:
        ms[r0:r1 + 1, :] = False
    col = ms.any(axis=0)
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
        if merged and r[0] - merged[-1][1] - 1 < 3:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    # 链式连续性：只保留与最右字形连成一串的（隔 >20px 的算别的 UI 元素）
    chain = []
    for r in reversed(merged):
        if not chain:
            chain.append(r)
        elif chain[-1][0] - r[1] - 1 <= 20:
            chain.append(r)
        else:
            break
    merged = list(reversed(chain))

    out = []
    from PIL import Image
    W = m_glyph.shape[1]

    # ── 有效性判定：自校准，不再用固定阈值 ──
    # 来历（这条规则被固定阈值坑了三次）：
    #   · `H_MIN=42` 会误杀窄字形 "1"（辉光高只有 31~37）→ 改 30；
    #   · 后来 `t=112.4` 的真值 `107023` 里那个前导 "1" **辉光高只有 29**，
    #     差 1px 又被丢掉 → 整串读成 `07023`（少一位，10 万点误差）；
    #   · 而用"完整字形几何"判定又会误杀 16px 宽的窄 "4"（高度 54→61 把宽度下限抬到 18）。
    # 根因：**辉光掩膜对窄字形本来就不完整**，拿它的高宽做阈值必然在边界上翻车。
    # 新规则：同一串数字一定是同一字号，所以用**本串自身**做参照 ——
    #   · 参照质量/高度 = "明显是字"的 run（像素质量 ≥ 150）的中位数；
    #   · 收：宽度 ≤ W_MAX（挡粘连大块）、像素质量够、高度够、宽高比够。
    # 实测边界：真字形质量 ≥ 350、宽高比 ≥ 0.26；碎片质量 ≤ 93、宽高比 ≤ 0.10。
    cands = []
    for xa, xb in merged:
        m1 = m_glyph[:, xa:xb + 1]
        rows1 = np.where(m1.any(axis=1))[0]
        if len(rows1) == 0:
            continue
        cands.append({"xa": xa, "xb": xb, "w": xb - xa + 1,
                      "h": int(rows1[-1] - rows1[0] + 1), "mass": int(m1.sum())})
    if not cands:
        return []
    big = [c for c in cands if c["mass"] >= 150] or cands
    m_ref = float(np.median([c["mass"] for c in big]))
    h_ref = float(np.median([c["h"] for c in big]))
    mass_thr = max(MASS_MIN, MASS_FRAC * m_ref)
    h_thr = max(12.0, H_FRAC * h_ref)

    for c in cands:
        xa, xb = c["xa"], c["xb"]
        if c["w"] > W_MAX or c["mass"] < mass_thr or c["h"] < h_thr:
            continue
        if c["w"] < max(4, int(RATIO_MIN * c["h"])):
            continue
        # 通过判定后再用完整字形掩膜向外扩，找回被弱辉光切掉的边缘
        lo, hi = xa, xb
        for _ in range(expand):
            if lo - 1 >= 0 and m_glyph[:, lo - 1].any():
                lo -= 1
            else:
                break
        for _ in range(expand):
            if hi + 1 < W and m_glyph[:, hi + 1].any():
                hi += 1
            else:
                break
        w = hi - lo + 1
        rows = np.where(m_glyph[:, lo:hi + 1].any(axis=1))[0]
        if len(rows) == 0:
            continue
        sub = warm[rows[0]:rows[-1] + 1, lo:hi + 1]
        sub = sub / max(1.0, float(sub.max()))
        img = Image.fromarray((sub * 255).astype(np.uint8)).resize((GW, GH), Image.BILINEAR)
        out.append((np.asarray(img, dtype=np.float32) / 255.0, w, rows[-1] - rows[0] + 1))
    return out


def extract(a, mode=None, box=None, expand=None, glyph_mode=None, bar_rows=None, locate=True):
    """
    a   : 整帧 RGB（int16/uint8 均可），形状 H×W×3
    box : (y0, x0, y1, x1) 绝对坐标；None → **动态定位**（见下）
    expand : 用完整字形掩膜向外扩的上限（px）；None → 默认 EXPAND_MAX
    glyph_mode : 单独指定"取字形像素"的掩膜模式（默认 GLYPH_MODE）
    bar_rows : 装饰金线行带（绝对 y）；None → 与 box 一起由动态定位给出
    locate : box 为 None 时是否启用动态定位（False → 用参考标定的全局框）
    返回: [(gray float32 GH×GW, 像素宽 w, 像素高 h), ...]（已按 HUD 右对齐链过滤）

    说明：列分割用 m_seg（辉光层最稳），字形像素用 m_glyph（核心∪辉光最完整）。

    ⚠️ box=None 的含义自线7 起变了：**先按画面内容动态定位**（`geometry`），
    定位不出来（HUD 隐藏/读数在过渡动画里）才退回参考标定的全局框。
    显式传 box= 时行为与以前完全一致（老脚本/标定工具不受影响）。
    """
    mode = mode or MASK_MODE
    expand = EXPAND_MAX if expand is None else expand
    glyph_mode = GLYPH_MODE if glyph_mode is None else glyph_mode
    if box is None:
        if locate:
            import geometry as SA
            box, auto_bar = SA.hud_box_for_frame(a)
            if bar_rows is None:
                bar_rows = auto_bar
        else:
            box = (CY0, CX0, CY1, CX1)
    y0, x0, y1, x1 = box
    return _extract_core(np.asarray(a[y0:y1, x0:x1], dtype=np.int16), (y0, x0),
                         mode, glyph_mode, expand, bar_rows)


def extract_cropped(region, top=CY0, left=CX0, mode=None, glyph_mode=None, expand=None,
                    bar_rows=None):
    """
    给"已经裁好的 HUD 区域"用（实时线直接拿内存里的 ndarray，不想再裁一次）。

    存在的唯一理由：**消除复制粘贴**。原来 `hud_digits.extract_glyphs` 把掩膜/分割
    代码整段抄了一份，靠"改一处必须改两处"的纪律维持同步 —— A 线这轮改了掩膜，
    实时端就会静默地用旧掩膜读错数。现在两边都调这里，同步是结构上保证的。

    bar_rows：装饰金线行带（绝对 y）；实时线请传 `geometry` 算出的那组，
    否则换字号时挖空会挖错行（参考标定值只对参考字号成立）。
    """
    region = np.asarray(region, dtype=np.int16)
    return _extract_core(region, (top, left),
                         mode or MASK_MODE,
                         GLYPH_MODE if glyph_mode is None else glyph_mode,
                         EXPAND_MAX if expand is None else expand,
                         bar_rows)


# ══════════════════════════════════════════════════════════════════════════
# 第二种字体：像素方块字体（2026-09-30 录屏里出现）
#   实测特征：青绿填充 + 紫蓝描边；字号比常规字体更大（字高 49~94，常规 60~79）；
#             字距更宽（约 57px，常规 34~37）；背景常是亮蓝色，所以不能靠"亮"分离。
#   掩膜：M = (G>195) & ((G-R)>25) & ((G-B)>-45) —— 取青绿填充，实测背景被滤掉。
#   为什么单独一份实现而不是硬塞进 _extract_core：它的宽度上限/字距/归一化都不同，
#   塞进去要给 _extract_core 加一堆参数，反而让主线（已达标）承担回归风险。
# ══════════════════════════════════════════════════════════════════════════
CYAN_W_MAX = 80        # 实测单字宽 20~71（像素字体的 '2' 有过 71px 宽的单字）
CYAN_GAP = 24          # 实测相邻字形空隙 5~20（常规字体规则是 20）
CYAN_H_MIN = 40        # 实测真字形高 49~94；碎片高 8~34
CYAN_MASS_MIN = 300    # 实测真字形质量 600~2100；碎片 1~170
CYAN_ADVANCE = 59.0    # 实测字距（t=49: 相邻字形起点 2519/2578/2638/2696/2755/2814）
# ── 2026-10-05 新增（都是 线2 `hud_read_team2.extract_cyan2` 实测出来的数）──
CYAN_H_MAX = 118       # 超过它就不是这套字形（录屏2 t=200 的满屏蓝光块 h=148 → 必须拒）
CYAN_ADV_RATIO = 1.2   # 字距 ≈ 单字宽 × 1.2（t=100 实测 52→57；t=238 实测 45.5→60）
CYAN_SPLIT_MIN_RATIO = 1.6   # 只有 w ≥ 1.6×字距 才敢拆（单字最宽 71 = 1.2×adv → 永不误拆）
CYAN_EDGE_GUARD = 3    # 最左段贴住区域左界 → 框在切一个比框还大的东西（满屏特效）→ 不认


def _split_wide_off(runs):
    """
    **曾经尝试拆"粘连大块"，已停用** —— 留着这段是为了记住为什么不能拆。

    起因：像素字体的数字会粘连成 70~120px 的宽块，被宽度上限丢弃 → 整串少位。
    做法：宽度/字距 ≈ 该块里有几个字，在"理想切点附近 ink 最少的列"下刀。

    为什么停用（用户实测纠正）：`t=45` 的 71px 宽块**其实是一个单字 '2'**——
    像素字体的 '2' 中间那道细斜线让列质量只是从 44 降到 26（中位 29 的 0.90 倍），
    并不是空白；我的"取最小列"就在这个**没断开的地方**下刀，把一个 '2' 劈成两半，
    造出一个**假字**。用户读的是 `52576`（5 位），我却给出 6 段。
    真正的字间间隙列质量是 **0**（完全没墨）。

    结论：**宁可不拆**。
      · 不拆的代价 = 那一块被宽度上限丢弃 → 少位（右对齐仍能对齐左边，且多帧投票可能补上）；
      · 拆错的代价 = 在中间插一个假字 → **它右边所有位的标签全部错位**，而且会被当成训练样本。
    后者危险得多。所以现在把单字宽度上限放宽到 CYAN_W_MAX=80 来"接住"偏宽的单字，
    而宽于 80 的块（真粘连）直接交给上层判"这段不可信"（见 train_pixel_A 的右缘检查）。

    ⚠️ 2026-10-05 补充：上面那次教训**不是"不能拆"，而是"切点判据不能只看列质量"**。
    `_split_runs_conservative()` 换了两条更严的门：
      ① **只有 w ≥ 1.6×字距 才拆**（单字最宽 71 = 1.2×字距 → 永远不会被误拆）；
      ② 切点用**更严的亮青掩膜**（`_cyan_narrow_mask`）找"局部墨最少的列"，
         单字内部那道细斜线在严掩膜下会整列消失 → 不再在字中间下刀。
    """
    return runs


# ══════════════════════════════════════════════════════════════════════════
# 2026-10-05：把 线2（`hud_read_team2.extract_cyan2`）里**能用的**那套分割移植进来。
#
# 为什么必须移植（实测三张用户确认真值的像素帧，实时链路 vs 线2）：
#   t=100 `506286`：实时 **3 段**（应 6）        ／ 线2 **6 段** ✓
#   t=200 `2052321`：实时被**蓝云**连成 1~7 段烂块 ／ 线2 **7 段** ✓
#   t=238 `123692`：实时 6 段但**字高被截顶**    ／ 线2 6 段 ✓
# 差别只有四件事，这里逐条照搬（**掩膜口径不动**：`strict=False` 仍走 `cyan_mask`，
# 与训练分布一致；训练/推理因此仍然同源）：
#   ① 列分割用**收紧掩膜**（`G-B > 8`）挡住整片蓝云背景（t=200）；
#   ② 整串钉在**同一条行带**上（`_dominant_row_band`）—— 数字下方那条 UI 条带
#      会让"每段各自取最大行块"选错（t=100 字高 51→95，字形图变成条带）；
#   ③ 粘连宽块**保守拆分**（`_split_runs_conservative`，见上面 `_split_wide_off` 的补充）；
#   ④ 拆不动的超宽块**占位**（返回 `gray=None`）而不是静默丢弃 —— 下游必须出 `?`，
#      于是这一帧会被判"待复核"而不是给出一个**位数偏少的错数**。
# ══════════════════════════════════════════════════════════════════════════

def _cyan_seg_mask(c):
    """**列分割**用的青色掩膜：在 `cyan_mask` 上收紧一条 `G > B`。

    为什么必须收紧：录屏2 `t=200` 的整幅画面是一片亮蓝云（背景实测 (168,210,253)：
    `G=210>195`、`G-R=42>25`、`G-B=-43>-45` → **穿过了原掩膜**）→ 分割出一个 734px 宽的
    巨块，整帧读数报废。数字的填充色实测是 (162,255,222)（`G-B=+33`），所以加一条
    `G-B > 8` 就能既保住数字、又挡掉蓝背景。
    ⚠️ 取字形像素仍可用原口径（`cyan_mask` + 填洞），保证与训练时的字形分布一致。
    """
    R, G, B = c[:, :, 0], c[:, :, 1], c[:, :, 2]
    return (G > 195) & ((G - R) > 25) & ((G - B) > 8)


def _cyan_narrow_mask(c):
    """更严的青色掩膜：只留亮青核心。用于**找切点**（越大越容易分开相邻字）。"""
    R, G, B = c[:, :, 0], c[:, :, 1], c[:, :, 2]
    return ((G - R) > 60) & (G > 200)


def _runs_from_col(col, merge_px=3):
    """列投影 → 连通列段（间隔 < merge_px 的并起来）。"""
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


def _dominant_row_band(m, xa, xb):
    """整串文字所在的行带 = 该 x 范围内**质量最大**的行连通块。

    为什么需要它（t=100 实测）：像素体数字的下方还有一条 UI 条带（区域行 111~147），
    按"每个列段各自取最大行块"会让中间那一段选中下方条带，字高从 51 变成 95、
    字形图变成条带 → 读错/丢字。整串文字一定是**同一行带**，用全局行带就把它钉死了。
    """
    row_any = m[:, xa:xb + 1].any(axis=1)
    blocks = _row_blocks(row_any)
    if not blocks:
        return None
    return max(blocks, key=lambda b: int(m[b[0]:b[1] + 1, xa:xb + 1].sum()))


def _split_runs_conservative(runs, m_narrow, adv, min_ratio=None):
    """把**明显**是多字粘连的宽块切开（切点 = 严掩膜下局部墨最少的列）。

    与已停用的 `_split_wide_off` 的区别（见它的补充说明）：门槛更严、切点更可靠。
    """
    min_ratio = CYAN_SPLIT_MIN_RATIO if min_ratio is None else float(min_ratio)
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
        # 去重后按顺序切；切点不够就退回等分点 —— 保证**刚好切成 k 段**
        cuts = sorted(set(c for c in cuts if xa + 2 < c < xb - 2))
        if len(cuts) < k - 1:
            cuts = sorted(set([xa + int(round(i * w / float(k))) for i in range(1, k)]))
        prev = xa
        for cc in cuts:
            out.append([prev, cc - 1])
            prev = cc
        out.append([prev, xb])
    return out


def extract_cyan(region, top=0, left=0, strict=False):
    """
    像素字体（银狼999 强普那种）的字形提取。

    返回 [(gray float32 GH×GW, 像素宽 w, 像素高 h), ...]，右对齐链过滤，语义同 extract。
    **`gray is None` = 占位**：那一块是拆不动的超宽粘连块 → 调用方必须出 `?`
    （宁可让这一帧"待复核"，也不能给出一个**位数偏少**的错数）。

    `strict=True` 用收紧掩膜（挡蓝云背景，t=200 那种画面）；
    默认 `strict=False` 用 A 线原掩膜（与训练分布一致）。
    字形灰度用**填洞后的二值形状**（该字体是实心方块字，内部偶有暗像素）——
    比给"青绿强度"更干净，也避免描边/辉光干扰。
    """
    from PIL import Image
    c = np.asarray(region, dtype=np.int16)
    m_seg = _cyan_seg_mask(c) if strict else cyan_mask(c)
    m_fill = _fill_holes(m_seg)
    merged = _runs_from_col(m_seg.any(axis=0))
    if not merged:
        return []

    # 字距估计：用"看起来像单字"的段宽中位数 × adv_ratio
    single = [r[1] - r[0] + 1 for r in merged
              if CYAN_W_MAX * 0.5 <= (r[1] - r[0] + 1) <= CYAN_W_MAX]
    adv = float(np.median(single)) * CYAN_ADV_RATIO if single else float(CYAN_ADVANCE)
    adv = max(CYAN_ADVANCE * 0.7, min(CYAN_ADVANCE * 1.6, adv))
    merged = _split_runs_conservative(merged, _cyan_narrow_mask(c), adv)

    # 链式连续性：从最右字形往左串（挡住左边的特效/UI 亮块）
    chain = []
    for r in reversed(merged):
        if not chain:
            chain.append(r)
        elif chain[-1][0] - r[1] - 1 <= CYAN_GAP:
            chain.append(r)
        else:
            break
    merged = list(reversed(chain))
    # 满屏特效块（如 t=200 的整片蓝光）会把整段连成一个巨块：贴住区域左界
    # = 说明框在切一块比框还大的东西，不可能是"总伤害数字" → 整帧不认。
    if merged and merged[0][0] <= CYAN_EDGE_GUARD:
        return []

    band = _dominant_row_band(m_fill, merged[0][0], merged[-1][1]) if merged else None
    out = []
    for xa, xb in merged:
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
        if w > CYAN_W_MAX:
            # 拆不动/拆了还是太宽 → **占位**（下游出 '?'），不要静默丢弃
            out.append((None, w, int(h)))
            continue
        if h < CYAN_H_MIN or h > CYAN_H_MAX or mass < CYAN_MASS_MIN:
            continue
        if w < max(6, int(0.20 * h)):
            continue
        sub = m_fill[r0:r1 + 1, xa:xb + 1]
        g = sub.astype(np.float32)
        img = Image.fromarray((g * 255).astype(np.uint8)).resize((GW, GH), Image.BILINEAR)
        out.append((np.asarray(img, dtype=np.float32) / 255.0, w, int(h)))
    return out


def cyan_mask(c):
    """像素字体的掩膜（青绿填充）。⚠️ 它是**取字形像素**的口径（与训练分布一致）；
    列分割另有收紧口径 `_cyan_seg_mask`（挡蓝云背景），见 `extract_cyan`。"""
    R, G, B = c[:, :, 0], c[:, :, 1], c[:, :, 2]
    return (G > 195) & ((G - R) > 25) & ((G - B) > -45)

