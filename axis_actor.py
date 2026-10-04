# -*- coding: utf-8 -*-
"""
E 线：行动轴顶端卡识别器（正式模块）。

思路（与已废弃的旧滑窗方案 `action_axis_reader.py` 的区别；该文件已在整理时删除）：
  * 顶端槽**位置固定**（实测像素级稳定，见 axis_probe_E.py Q1）：
      头像区 = (90,81)-(232,175)；左标记中心 = (86,127)
    → 不需要全图滑窗模板匹配，直接从固定框取头像做分类
  * 分类 = 「同类多模板 + 灰度NCC + 0.6×梯度NCC + 0.3×色度NCC」取最大，
    模板全部来自**人工看图核对过**的帧（out/axis_top_labels_E.json，71 帧）
  * 忆灵按归属映射到召唤者（口径：忆灵伤害算给召唤者）
  * 两道闸：分数 ≥ THR，且与第二名分差 ≥ MIN_MARGIN；否则返回 None（"待复核"，宁可漏不要错）
  * 传入帧尺寸不等于参考分辨率 2876x1798 时，按宽度**等比缩放坐标**（支持整屏缩放的抓屏）

实测指标（axis_report_E.py，留一帧口径）：
  * 8 个单位类准确率 **97.2% (69/71)**；分数 ≥0.90 的帧里正确率 **100%**
  * 68 个"非我方"帧（敌人/空/动画过渡，人工核对）最高分 0.88 → 阈值 0.90 无误报
  * 单帧推理 **0.8~1.5 ms**（图在内存里）

对外接口：
    bank = load_bank()                      # 进程内缓存，实时循环里反复调用不读盘
    r = read_actor("frames/glyphcache/f00226.00.png", bank)
    r -> {"unit": "遐蝶"|None, "owner": "遐蝶"|None, "score": 1.90, "margin": 0.87,
          "kind": "ally"|"ally_memo"|"unknown", "marker": "ally_dot", "scores": {...}}
    r = read_window(list_of_frames, bank, min_votes=3)   # 30fps 窗口投票

命令行：
    python axis_actor.py --selftest        # 真值帧 18 条 + 分辨率 0.5x/0.75x/1.5x 自检
    python axis_actor.py 226 109 311       # 单帧判定
    python axis_actor.py 226 --json        # JSON 输出（给别的会话）
    python axis_actor.py --build           # 重建模板库
"""
import json
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from mvp.resource import resource as _res  # noqa: E402  （打包专项：按 exe 位置解析资源）

FRAME = os.path.join(HERE, "frames/glyphcache/f%08.2f.png")
# 参考坐标系（录屏 2876×1798）——**只作标定基准**。线7 起坐标由 `geometry` 算出：
#   · 传入整帧时：按画面里测出的"卡上边框脊 / 面板左缘竖线"定位（模型先验 + 证据纠正）；
#   · 只给尺寸（或显式传 s）时：按帧宽等比缩放这套参考值（老行为，缩放自检仍走这条）。
REF_W, REF_H = 2876, 1798
TOP_ART = (90, 81, 232, 175)
MARK_C = (86, 127)
MARK_R = 19
LABELS_PATH = _res("out/axis_top_labels_E.json")
BANK_PATH = _res("out/axis_top_bank_E.npz")

import geometry as SA  # noqa: E402  （线7：屏幕适配 / 动态定位）

# 忆灵 → 召唤者（交接文档 用户口径与铁律.md 已确认口径）
OWNER = {"死龙": "遐蝶", "长夜": "长夜月", "小伊卡": "风堇", "德谬歌": "昔涟"}


def _load_owner_overrides():
    """用 `out/teams/owners.json` 覆盖/补充忆灵归属（onboarding 登记新队伍的忆灵用）。

    为什么留这个口子：上面那 4 条是**队伍1 已确认的口径**，不能动；但换一支带记忆命途的
    队伍时会有新的忆灵（"谁召唤的"只有用户知道）。既然 onboarding 的宗旨是"角色名来自
    数据而不是代码"，忆灵归属同理 —— 数据文件存在就以其为准，不存在则用上面的默认值。
    加载失败一律**静默退回默认值**（这是识别器的核心路径，绝不因为一个可选文件把识别搞崩）。
    """
    try:
        p = _res("out/teams/owners.json")
        if p and os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                out = dict(OWNER)
                out.update({k: v for k, v in d.items() if not str(k).startswith("_")})
                return out
    except Exception:                                       # noqa: BLE001
        pass
    return dict(OWNER)


OWNER = _load_owner_overrides()
MEMO = set(OWNER)
CHARACTERS = ["遐蝶", "风堇", "昔涟", "长夜月"]
UNIT_NAMES = CHARACTERS + ["死龙", "长夜", "小伊卡", "德谬歌"]

# 分类阈值：axis_tune_E.py 扫出来的（71 正向帧留一帧 + 68 人工核对过的负向帧）
#   灰度+0.6梯度+0.3色度 → 留一帧 97.2%，零误报阈值 0.89，接受帧内正确率 100%
#   取 0.90 留一点余量；两个留一帧错例（t=241 白带遮挡 0.78、t=148 白屏洗白 0.32）都落在阈值下 → 判"待复核"
THR = 0.90
# 与第二名的分差下限：过渡/滑动中的卡两类分数几乎相同（axis_borderline_E.py 实测：
# 分数过阈值的帧里，间距 0.23/0.31/0.34 三帧是过渡帧，紧接着跳到 0.59，之后都 >=0.77）
MIN_MARGIN = 0.45


def _norm(a):
    a = a.astype(np.float32)
    return (a - a.mean()) / max(1e-3, float(a.std()))


def feats(bgr):
    """一个块 → 4 张 72x48 归一化特征图：灰度 / 梯度幅值 / Lab 的 a、b 通道。

    加 a、b 色度通道是实测结论（axis_tune_E.py）：留一帧 93.0% → 97.2%，
    且"零误报阈值"下接受帧的正确率 98% → 100%（角色发色/背景色是很强的判别信息）。
    """
    small = cv2.resize(bgr, (72, 48), interpolation=cv2.INTER_AREA)
    g = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32)
    return np.stack([_norm(g), _norm(cv2.magnitude(gx, gy)),
                     _norm(lab[:, :, 1]), _norm(lab[:, :, 2])])


W_GRAY, W_GRAD, W_COLOR = 1.0, 0.6, 0.3
# 模板库缩放增强：顶端卡有两种渲染——"普通态"和"放大态"（实测差 **1.08 倍 + 位移 (4,2)px**，
# 见 axis_scale_check_E.py；用户观察：放大态对应四角星标记 = 插入行动轴的行动）。
# 每个模板都存两份（1.0 与 1.08），匹配时放大版打 0.03 折扣防假阳性。
# 效果：留一帧不变（97.2%），但覆盖率 94%→96%，负向最高分不变（0.89）。
ZOOMS = (1.0, 1.08)
ZOOM_PEN = (0.0, 0.03)


def scale_of(shape):
    """帧尺寸 → 坐标缩放系数（以宽度为准；参考分辨率 2876x1798）。"""
    w = shape[1]
    return w / float(REF_W)


def crop_letterbox(bgr, thr=8.0, std_thr=4.0, min_bar=4, step=4):
    """**自动裁掉上下/左右黑边**（信箱/邮筒边），返回 (裁后图, (x0,y0,x1,y1))。

    为什么需要：用户 2026-10-03 给的 `水砂视频.mp4` 是 2880×1798，但**上下各加了黑边**
    （上 90px / 下 88px），真实游戏内容是 2880×1620（16:9）。不裁的话卡框会整体偏 90px，
    采集全废。裁掉后**旧素材的卡框坐标正好落在顶端卡上**（已用刻度尺图核对）。

    实现取巧处：为了不给实时链路加负担，先在 **1/step 降采样**上看行/列亮度剖面
    （2880×1798 → 720×450，约 0.3 ms），只有确实存在黑边才真的裁剪。

    ⚠️ `min_bar` 的单位是**降采样后的行/列数**（`min_bar=4` → 实际 ≥16px）：
    **每一侧**单独判，细边按"没有黑边"处理（见下面"细黑边不算黑边"的说明）。
    """
    h, w = bgr.shape[:2]
    small = bgr[::step, ::step]
    g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
    # 判据用「**纯黑且方差近 0**」而不是"亮度低"——真实信箱边是渲染出来的纯黑，
    # 而暗场景/纯色背景会骗过亮度判据（用户 2026-10-03 的皮肤演示视频实测：
    # 亮度判据得到 92/16/248/56 乱跳，方差判据才稳定）。
    mrow, srow = g.mean(axis=1), g.std(axis=1)
    mcol, scol = g.mean(axis=0), g.std(axis=0)
    is_bar_r = (mrow < thr) & (srow < std_thr)
    is_bar_c = (mcol < thr) & (scol < std_thr)
    n_r, n_c = len(is_bar_r), len(is_bar_c)
    top = 0
    while top < n_r and is_bar_r[top]:
        top += 1
    bot = 0
    while bot < n_r and is_bar_r[n_r - 1 - bot]:
        bot += 1
    left = 0
    while left < n_c and is_bar_c[left]:
        left += 1
    right = 0
    while right < n_c and is_bar_c[n_c - 1 - right]:
        right += 1
    # ⚠️⚠️ 2026-10-05 修：**细黑边不算黑边**（按每一侧单独判，原来只看"四侧全小"才不裁）。
    #
    # 原来的逻辑：只要**任意一侧**出现 ≥min_bar 的黑边就整体裁剪。
    # 后果：暗场景/转场时画面边上一圈 8~12px 的暗条会被当成信箱边 →
    #   ① 自己定位那条路（`geom=None`）：几何是**裁后**按模型算的，模型假定内容顶在图上边，
    #      于是卡框整体偏掉几个像素 → 认得出的卡变成"待复核"。
    #      实测：`axis_actor --selftest` 里**唯一**那条红点 t=159 就是这么来的
    #      （期望长夜月，实得待复核 分数1.25/间距0.23）。
    #   ② 调用方给了 geom 那条路：更糟（图原点变了、几何没变）→ 见 `read_actor` 的说明。
    # 实测把"细边"按侧忽略后（1427 张真实整屏帧）：
    #   * "整帧自定位"与"轴区域+局部几何"两条路的一致数 **1408/1427 → 1426/1427**；
    #   * `axis_actor --selftest` 红点 **1 → 0**。
    # 真正的信箱边是 80~90px 量级（见上面用户素材），远大于 min_bar*step = 16px。
    if top < min_bar:                       # ⚠️ 见下面"细黑边不算黑边"的说明
        top = 0
    if bot < min_bar:
        bot = 0
    if left < min_bar:
        left = 0
    if right < min_bar:
        right = 0
    if top == 0 and bot == 0 and left == 0 and right == 0:
        return bgr, (0, 0, w, h)
    y0, y1 = min(top * step, h), max(top * step + 1, h - bot * step)
    x0, x1 = min(left * step, w), max(left * step + 1, w - right * step)
    y1, x1 = min(y1, h), min(x1, w)
    # 全黑帧（转场淡入淡出的纯黑画面）会把整幅判成黑边 → 裁出空图（cv2.resize 崩过）。
    # 这时**原样返回**：反正标记/卡面都不会过闸。
    if y1 - y0 < 64 or x1 - x0 < 64:
        return bgr, (0, 0, w, h)
    return bgr[y0:y1, x0:x1].copy(), (x0, y0, x1, y1)


def geom_for(img, s=None):
    """
    一帧 → 行动轴几何（`geometry.axis_geometry` 的薄封装）。

    返回 {'top_art','mark_c','mark_r','card','left','top','s','src','rail','ridge'}。
    `src='detect'` 表示画面证据与模型预测相差 >4px、以证据为准（换分辨率时才会出现）；
    `src='model'` 表示证据与模型一致或找不到证据（轴在滑入滑出动画里）→ 用模型值。
    """
    return SA.axis_geometry(img, s=s)


def _rect(rect, s):
    x0, y0, x1, y1 = rect
    return (int(round(x0 * s)), int(round(y0 * s)), int(round(x1 * s)), int(round(y1 * s)))


def top_art(bgr, s=None, geom=None):
    """裁出顶端卡头像区。

    s=None → **动态定位**（线7）：按画面测出的卡边框算，不再是写死的 (90,81)-(232,175)。
    s=数值 → 按参考框等比缩放（旧调用/缩放自检走这条，行为不变）。
    """
    if s is None:
        g = geom if geom is not None else geom_for(bgr)
        x0, y0, x1, y1 = g["top_art"]
    else:
        x0, y0, x1, y1 = _rect(TOP_ART, s)
    if bgr.shape[0] < y1 or bgr.shape[1] < x1:
        raise ValueError("帧尺寸 %s 太小，连顶端卡区域都放不下（参考分辨率 %dx%d）"
                         % (bgr.shape[:2], REF_H, REF_W))
    return bgr[y0:y1, x0:x1]


def feats_art(img, s_res=None, s_zoom=1.0, geom=None):
    """顶端卡特征（s_res=分辨率缩放；s_zoom=卡面放大态缩放，1.08 对应"放大态"渲染）。"""
    art = top_art(img, s_res, geom=geom)
    if s_zoom != 1.0:
        h, w = art.shape[:2]
        z = cv2.resize(art, (max(2, int(round(w * s_zoom))), max(2, int(round(h * s_zoom)))),
                       interpolation=cv2.INTER_AREA if s_zoom < 1 else cv2.INTER_LINEAR)
        if z.shape[0] >= h and z.shape[1] >= w:
            y0, x0 = (z.shape[0] - h) // 2, (z.shape[1] - w) // 2
            z = z[y0:y0 + h, x0:x0 + w]
        else:
            z = cv2.copyMakeBorder(z, 0, max(0, h - z.shape[0]), 0, max(0, w - z.shape[1]),
                                   cv2.BORDER_REPLICATE)
        art = z
    return feats(art)


MARKER_LABELS_PATH = _res("out/axis_marker_labels_E.json")
MARKER_BANK_PATH = _res("out/axis_marker_bank_E.npz")
MARKER_DIR1 = "frames/glyphcache"          # 第一个录屏
MARKER_DIR2 = "frames/glyphcache2_E"       # 第二个录屏（欢愉/阿哈时刻）
_MARKER_BANK = {}
_MARKER_MATS = {}


def marker_patch(bgr, s=None, r=30, geom=None):
    """左标记区方块（中心 (86,127)）。

    s=None → 动态定位（线7）：中心/半径按测出的卡边框算；s=数值 → 参考值等比缩放。
    """
    if s is None:
        g = geom if geom is not None else geom_for(bgr)
        cx, cy = g["mark_c"]
        rr = int(round(r * (g["mark_r"] / float(MARK_R))))
    else:
        cx, cy, rr = int(round(MARK_C[0] * s)), int(round(MARK_C[1] * s)), int(round(r * s))
    return bgr[max(0, cy - rr):cy + rr, max(0, cx - rr):cx + rr]


def marker_samples():
    """产出 (形状类别, 帧目录, 帧号)。`v2_xxx` 前缀 = 第二个录屏（frames/glyphcache2_E）。"""
    grouped = json.load(open(MARKER_LABELS_PATH, encoding="utf-8"))
    for lab, ts in grouped.items():
        if lab.startswith("_") or lab == "occluded":
            continue
        dir2 = lab.startswith("v2_")
        cls = lab[3:] if dir2 else lab
        d = MARKER_DIR2 if dir2 else MARKER_DIR1
        for t in ts:
            yield cls, d, float(t)


def build_marker_bank(out_path=MARKER_BANK_PATH):
    """把人工标注的标记样本抽成特征存 npz（否则首次调用要读几十张 7MB PNG，约 5 秒）。

    标签文件里 `v2_xxx` 前缀的样本来自第二个录屏（`MARKER_DIR2`）；缺任何一帧就**放弃重建**
    （不覆盖已有 npz），避免把模板库悄悄建残。
    """
    out = {}
    missing = []
    for cls, d, t in marker_samples():
        p = os.path.join(HERE, d, "f%08.2f.png" % t)
        img = cv2.imread(p, cv2.IMREAD_COLOR)
        if img is None:
            missing.append("%s t=%s" % (d, fmt_t(t)))
            continue
        out.setdefault(cls, []).append(feats(marker_patch(img, scale_of(img.shape))))
    if missing:
        raise SystemExit("缺 %d 张标记样本帧（%s）；第二个录屏的帧用 "
                         "`python axis_extract_E.py --step 1 --start 0 --end 382 "
                         "--outdir frames/glyphcache2_E` 重新抽，已放弃覆盖 %s"
                         % (len(missing), missing[:6], out_path))
    out = {k: np.stack(v) for k, v in out.items()}
    np.savez_compressed(out_path, **out)
    _MARKER_BANK.clear()
    _MARKER_MATS.clear()
    for k, v in out.items():
        _MARKER_BANK[k] = [(None, v[i]) for i in range(v.shape[0])]
        _MARKER_MATS[k] = v
    print("标记模板库已写出 %s：%s" % (out_path, {k: v.shape[0] for k, v in out.items()}))
    return _MARKER_BANK


def _marker_bank():
    """从**模板库 npz**（不在时按人工标注重建）：{dot/star/…: [(帧号, 特征)]}（懒加载 + 缓存）。

    ⚠️ 判断顺序**必须先看 npz**（打包专项踩到的坑）：npz 是**运行期**产物，标注 json 只是
    **建库时的输入**。原来先查标注 json，exe 里没带上那个 json 就直接 `return {}`
    → 标记模板库**静默变空**（不报错、只是 marker 字段全空），已进包的 npz 白带了。
    """
    if _MARKER_BANK:
        return _MARKER_BANK
    if not os.path.exists(MARKER_BANK_PATH):
        if not os.path.exists(MARKER_LABELS_PATH):
            return {}
        return build_marker_bank()
    z = np.load(MARKER_BANK_PATH)
    for lab in z.files:
        arr = z[lab]
        _MARKER_BANK[lab] = [(None, arr[i]) for i in range(arr.shape[0])]
        _MARKER_MATS[lab] = arr
    return _MARKER_BANK


def marker_scores(bgr, bank=None, s=1.0, mats=None, geom=None):
    """各标记类别（dot/star/enemy/empty）的最高分。

    bank/mats 可传自定义（评估用留一帧）；默认用模块缓存的模板矩阵（避免每次 np.stack）。
    geom 给了 → 标记区按动态定位取（线7）。
    """
    if mats is None:
        if bank is None:
            _marker_bank()
            mats = _MARKER_MATS
        else:
            mats = {lab: np.stack([x[1] for x in items]) for lab, items in bank.items()}
    f = feats(marker_patch(bgr, None if geom is not None else s, geom=geom))
    out = {}
    for lab, m in mats.items():
        v = (W_GRAY * (m[:, 0] * f[0]).mean(axis=(1, 2))
             + W_GRAD * (m[:, 1] * f[1]).mean(axis=(1, 2))
             + W_COLOR * ((m[:, 2] * f[2]).mean(axis=(1, 2))
                          + (m[:, 3] * f[3]).mean(axis=(1, 2))) / 2)
        out[lab] = float(v.max())
    return out


def marker_feat(bgr, s=None, bank=None, geom=None):
    """左标记：返回 (类型, 分数, 色相)。类型 = "<颜色>_<形状>"。

    形状（用户观察 + 两个录屏核对）：
      dot     圆点 = 按行动值排队的**正常行动**
      star    四角星 = **插入行动轴的行动**（立即行动/额外回合/欢愉技插入）
      diamond 菱形 = **机制/技能卡**（欢愉技『?』卡、敌方机制卡）
      aha     阿哈时刻卡的标记 = 金色圆环 + 环里**脉动**的四角星（是**一个**字符，不是两种状态；
              星明暗脉动 → 有时只看见环、有时只看见星，见 samples/E2_aha_glyph.png）
    颜色：ally(青) / enemy(红) / gold(金=阿哈时刻)

    样本：两个录屏共 127 个手工核对过的标记（axis_marker_E.py --sheet / --sheet2 出图标注）。
    形状不是归属判定依据，只是附注；`read_actor` 的 `inserted` / `card_type` 由它给出。
    """
    bank = _marker_bank() if bank is None else bank
    if not bank:
        return "none", 0.0, None
    if s is None:                       # 线7：s 不给就按画面动态定位，拿到实测缩放系数
        geom = geom if geom is not None else geom_for(bgr)
        s = geom["s"]
    sc = marker_scores(bgr, bank, s, geom=geom)
    # 色相只看**标记自身**（中心 r<=7 的圆盘），否则会被卡面的红/青背景带偏
    # （例：死龙的卡背是红色光晕，若统计整块会把青色圆点判成敌方）
    p = marker_patch(bgr, None if geom is not None else s, r=10, geom=geom)
    hsv = cv2.cvtColor(p, cv2.COLOR_BGR2HSV)
    h, w = hsv.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    disc = ((yy - h / 2.0) ** 2 + (xx - w / 2.0) ** 2) <= (7 * s) ** 2
    S = hsv[:, :, 1].astype(np.int32)
    V = hsv[:, :, 2].astype(np.int32)
    m = disc & (S > 120) & (V > 120)
    hue = float(np.median(hsv[:, :, 0][m])) if m.any() else -1.0

    # 形状用**全局最高分**定（实测：形状模板分数区分度很好，
    # 而色相分不开"阿哈金"与"敌方红"——两者色相都在 0~15，所以颜色只用于命名，不用于选形状）
    lab, best = max(sc.items(), key=lambda kv: kv[1])
    if lab == "empty":
        return "empty", round(best, 2), hue
    if lab == "aha":
        # 阿哈时刻卡的标记是**一个**字符：金色圆环 + 环里脉动的四角星
        # （0.2s 逐帧实测：形状始终是"环套星"，只是星在明暗脉动 → 有时只看见环。
        #  所以不要再分成 ring / star 两类，见 samples/E2_aha_glyph.png）
        return "gold_aha", round(best, 2), hue
    if lab.startswith("enemy"):
        return lab, round(best, 2), hue
    shape = lab if lab in ("dot", "star", "diamond") else "dot"
    side = "ally" if 60 <= hue <= 130 else ("enemy" if 0 <= hue <= 25 or hue >= 155 else "?")
    return "%s_%s" % (side, shape), round(best, 2), hue


def _frame_path(t, prefix=FRAME):
    if isinstance(t, str):
        return t
    return FRAME % float(t)


def load_frame(src):
    """src 可以是：np.ndarray(BGR) / 图片路径 / 帧号(如 226 或 226.0)。"""
    if isinstance(src, np.ndarray):
        img = src
    elif hasattr(src, "convert"):                    # PIL.Image
        import numpy as _np
        img = cv2.cvtColor(_np.asarray(src.convert("RGB")), cv2.COLOR_RGB2BGR)
    else:
        p = src if isinstance(src, str) and os.path.exists(src) else _frame_path(src)
        img = cv2.imread(p, cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(p)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return img


def build_bank(labels_path=LABELS_PATH, out_path=BANK_PATH):
    """按真值标签建模板库。每个模板帧存 len(ZOOMS) 行（普通态 + 放大态），顺序固定。

    缺任何一帧就**放弃重建**（不覆盖已有 npz），避免把模板库悄悄建残。
    """
    labels = json.load(open(labels_path, encoding="utf-8"))
    units, mats = [], []
    missing = []
    for unit, ts in labels.items():
        if unit not in UNIT_NAMES:
            continue
        fs = []
        for t in ts:
            img = cv2.imread(_frame_path(t), cv2.IMREAD_COLOR)
            if img is None:
                missing.append(t)
                continue
            for z in ZOOMS:
                # ⚠️ 模板库**固定用参考框**（s_res=参考缩放系数）：模板是 E 线 97.2% 指标的
                # 根基，改模板框 = 改指标，不属线7 范围。推理侧走动态定位；两者在参考
                # 分辨率上算出的框完全一致（见 docs/行动轴识别.md §5 的逐帧对照）。
                fs.append(feats_art(img, s_res=scale_of(img.shape), s_zoom=z))
        if not fs:
            continue
        units.append(unit)
        mats.append(np.stack(fs))          # (n*len(ZOOMS), 4, 48, 72)
    if missing:
        raise SystemExit("缺 %d 张真值帧（%s）；先抽帧再重建，已放弃覆盖 %s"
                         % (len(missing), missing[:8], out_path))
    banks = {u: m for u, m in zip(units, mats)}
    np.savez_compressed(out_path, **banks)
    _BANK_CACHE[out_path] = banks          # 重建后立刻生效，避免同进程里继续用旧库
    print("模板库已写出 %s：%s（共 %d 帧 × %d 个缩放态）" %
          (out_path, {u: m.shape[0] // len(ZOOMS) for u, m in banks.items()},
           sum(m.shape[0] for m in banks.values()) // len(ZOOMS), len(ZOOMS)))
    return banks


_BANK_CACHE = {}          # 模板库进程内缓存（load_bank 读、build_bank 写）


def load_bank(path=BANK_PATH, cache=True):
    """读模板库（默认进程内缓存，实时循环里反复调用不会重复读盘）。"""
    if cache and path in _BANK_CACHE:
        return _BANK_CACHE[path]
    if not os.path.exists(path):
        if getattr(sys, "frozen", False):
            # 打包后没有标注 json / 原始帧 → 重建必然失败，给一条能看懂的报错
            raise FileNotFoundError(
                "行动轴模板库缺失：%s（打包时没带上，检查 hud_pack.spec 的 datas）" % path)
        banks = build_bank(out_path=path)
    else:
        z = np.load(path)
        banks = {k: z[k] for k in z.files}
    if cache:
        _BANK_CACHE[path] = banks
    return banks


# ── 向量化匹配（数学与原来的逐单位循环**完全等价**）──
# 原来每个单位各做 4 次归约，开销随**单位数**增长：库到 98 条目 / 2188 模板时
# 单帧 71.9 ms，已把 100 ms 预算吃掉七成（要收齐 100+ 角色就不够）。
# 改成：所有模板拼成一个大矩阵（缓存一次），一帧只做**一次矩阵乘**，再按单位取最大值。
#   分数 = Σ_c W_c·mean(m_c·f_c) − zoom折扣 = dot(√W⊙m, √W⊙f)/3456 − pen（权重折进两边）
_WEIGHTS = np.array([W_GRAY, W_GRAD, W_COLOR / 2, W_COLOR / 2], np.float32)
_SW = np.sqrt(_WEIGHTS)[:, None, None]
_FLAT_CACHE = {}


def _flat_bank(bank):
    """把所有模板拼成 (N, 4*48*72) 大矩阵 + 每单位起止下标（带缓存）。"""
    key = (tuple(sorted(bank)), sum(m.shape[0] for m in bank.values()))
    hit = _FLAT_CACHE.get(key)
    if hit is not None:
        return hit
    units = sorted(bank)
    mats = np.concatenate([bank[u] for u in units], axis=0).astype(np.float32)
    flat = (mats * _SW).reshape(mats.shape[0], -1)
    pen = np.array([ZOOM_PEN[i % len(ZOOMS)] for i in range(mats.shape[0])], np.float32)
    starts = np.cumsum([0] + [bank[u].shape[0] for u in units])
    out = (flat, pen, starts, units)
    _FLAT_CACHE.clear()
    _FLAT_CACHE[key] = out
    return out


def match(bank, img, s=None, geom=None):
    """返回 {单位: (该类最高分, 该类次高分)}。

    分数 = 灰度NCC + 0.6×梯度NCC + 0.3×色度NCC（同类多模板取最大，模板含普通态/放大态）；
    理论上限 = 1 + 0.6 + 0.3 = 1.9（模板打自己、且是最佳缩放态时）。
    geom 给了 → 头像区按动态定位取（线7）。
    """
    if s is None and geom is None:
        s = scale_of(img.shape)
    f = feats_art(img, s if geom is None else None, geom=geom)
    flat, pen, starts, units = _flat_bank(bank)
    sc = flat @ (f * _SW).reshape(-1) / 3456.0 - pen
    out = {}
    for k, unit in enumerate(units):
        seg = sc[starts[k]:starts[k + 1]]
        if seg.size > 1:
            out[unit] = (float(seg.max()), float(np.partition(seg, -2)[-2]))
        else:
            out[unit] = (float(seg[0]), -1.0)
    return out


def pair_score(f1, f2):
    """两个特征块之间的加权 NCC 分（对上面 match 用的同一套权重）。"""
    ch = float((f1[0] * f2[0]).mean())
    gr = float((f1[1] * f2[1]).mean())
    co = (float((f1[2] * f2[2]).mean()) + float((f1[3] * f2[3]).mean())) / 2
    return W_GRAY * ch + W_GRAD * gr + W_COLOR * co


def read_actor(src, bank=None, thr=THR, min_margin=MIN_MARGIN, geom=None):
    """读一帧的当前行动者。返回 dict（无法判定时 unit=None）。

    thr        分数阈值（低于它一律"待复核"）
    min_margin 与第二名的分差下限（过渡/滑动中的卡往往两类分数几乎相同 → 拒绝）
    geom       预先算好的几何（线7）。实时线请用标定那一帧的结果传进来，省掉每帧的
               灰度转换 + 边缘扫描；缺省时按本帧现算。
    """
    if bank is None:
        bank = load_bank()
    img = load_frame(src)
    # ⚠️⚠️ 2026-10-05 修 —— 这是用户实机"闪退"的**真正根因**（交接文档 §2.1）。
    #
    # 裁黑边（信箱边）**只能在"自己定位"时做**：那时 `geom` 是从裁后的图上算的，
    # 图和几何同一个坐标系。
    #
    # 而**调用方给了 `geom`** 时，那张图**已经是裁好的区域**（实时抓的是 `capture.AXIS_REGION`
    # 那条 x60~340 的轴区域），`geom` 用的就是**这个区域自己的坐标系**。
    # 此时再"按画面裁黑边"，图的原点变了、`geom` 却没跟着变 ⇒ **卡框整体错位**。
    # 实测（1427 张真实整屏帧）：**188 帧**的轴区域会被裁，后果两种——
    #   * 轻：本来 1.90 分认得出的卡变成"待复核"（**65 帧**，如 f00109 本该认出遐蝶）；
    #   * 重：卡框比图还大 → `top_art` 抛 ValueError → 采集进程被干掉
    #     （用户看到的闪退，报错形如「帧尺寸 (88, 280) 太小」——`(88,280)` 就是**裁后**的图）。
    # 注意 `crop_letterbox` 的判据是"纯黑且方差近 0"，暗场景/转场很容易骗过它 →
    # 这在实机上是**常态**，不是罕见边界。
    if geom is None:
        img, _bar = crop_letterbox(img)     # 整帧输入：先裁黑边，几何就在裁后的图上算
        geom = geom_for(img)
    s = geom["s"]
    sc = match(bank, img, s, geom=geom)
    rank = sorted(sc.items(), key=lambda kv: -kv[1][0])
    unit, (best, _) = rank[0]
    second = rank[1][1][0] if len(rank) > 1 else -1.0
    margin = best - second
    mk, mscore, hue = marker_feat(img, s, geom=geom)
    ok = best >= thr and (min_margin is None or margin >= min_margin)
    # 卡片类型：阿哈时刻面具框 / 欢愉技卡 / 我方单位 / 敌方
    if mk == "gold_aha":
        card_type = "aha"
    elif mk == "ally_diamond":
        card_type = "elation"
    elif mk.startswith("enemy"):
        card_type = "enemy"
    elif mk == "empty":
        card_type = "empty"
    else:
        card_type = "unit"
    return {
        "unit": unit if ok else None,
        "raw": unit,
        "score": round(best, 3),
        "margin": round(margin, 3),
        "owner": OWNER.get(unit, unit) if ok else None,
        "kind": ("ally_memo" if unit in MEMO else "ally") if ok else "unknown",
        "marker": mk,
        # 四角星（青色）= 插入行动轴的行动（额外回合/立即行动/欢愉技插入）；
        # 只对我方单位卡有意义，阿哈/欢愉技/敌方/空槽一律 None
        "inserted": (mk in ("ally_star", "enemy_star")) if card_type in ("unit", "enemy") else None,
        "card_type": card_type,
        "marker_score": mscore,
        "reject": None if ok else ("low_score" if best < thr else "low_margin"),
        "scores": {k: round(v[0], 3) for k, v in rank},
    }


def read_window(srcs, bank=None, thr=THR, min_margin=MIN_MARGIN, min_votes=1):
    """多帧投票：给一段帧（同一次攻击期间）判定行动者。

    实时抓屏（30fps）时，一次攻击的 HUD 会停留 1~1.5 秒 → 用 30~45 帧投票比单帧稳得多。
    返回 {"unit","owner","votes","n","score","detail"}；无有效票时 unit=None。
    """
    if bank is None:
        bank = load_bank()
    tally = {}
    detail = []
    for s in srcs:
        try:
            r = read_actor(s, bank, thr, min_margin)
        except FileNotFoundError:
            continue
        detail.append(r)
        if r["unit"]:
            d = tally.setdefault(r["unit"], {"votes": 0, "score": 0.0})
            d["votes"] += 1
            d["score"] += r["score"]
    if not tally:
        return {"unit": None, "owner": None, "votes": 0, "n": len(detail),
                "score": 0.0, "detail": detail}
    unit, d = max(tally.items(), key=lambda kv: (kv[1]["votes"], kv[1]["score"]))
    ok = d["votes"] >= min_votes
    return {"unit": unit if ok else None, "owner": (OWNER.get(unit, unit) if ok else None),
            "votes": d["votes"], "n": len(detail), "score": round(d["score"], 2),
            "tally": {k: v["votes"] for k, v in sorted(tally.items(), key=lambda kv: -kv[1]["votes"])},
            "detail": detail}


# 验收真值：《用户口径与铁律.md》记录的用户真值 + E 线实测更正（见 行动轴识别.md 第 6 节）
#   152 文档记「长夜月」→ 实测顶端是死龙，归属遐蝶（用户："先龙后长夜"）
#   311 文档记「昔涟」  → 实测顶端是长夜，归属长夜月（用户："311 是长夜"）
#   293 文档记「敌人(半)」→ 实测该帧顶端是风堇滑入（"敌人(半)"是 t=288）
#   None = 该帧顶端不是我方（敌人 / 空槽）
TRUTH_OWNER = {
    226: "遐蝶", 109: "遐蝶", 251: "遐蝶", 100: "遐蝶", 152: "遐蝶",
    159: "长夜月", 167: "风堇", 175: "风堇", 221: "昔涟", 311: "长夜月",
    307: "昔涟", 293: "风堇",
    191: None, 207: None, 104: None, 120: None, 134: None, 139: None,
}


def selftest(verbose=True):
    """自检：真值帧逐条核对 + 分辨率缩放鲁棒性。返回不一致清单（空 = 通过）。"""
    bank = load_bank()
    bad = []
    for t, exp in sorted(TRUTH_OWNER.items()):
        try:
            r = read_actor(t, bank)
        except FileNotFoundError:
            bad.append("t=%s 缺帧" % t)
            continue
        got = r["owner"]
        if got != exp:
            bad.append("t=%s 期望%s 实得%s（分数%.2f 间距%.2f）"
                       % (t, exp or "非我方", got or "待复核", r["score"], r["margin"]))
        elif verbose:
            print("  OK  t=%-5s -> %-6s (顶端 %-5s 分数%.2f)" %
                  (t, got, r["raw"], r["score"]))
    img = load_frame(226)
    for s in (0.5, 0.75, 1.5):
        try:
            r = read_actor(cv2.resize(img, None, fx=s, fy=s, interpolation=
                                      cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR), bank)
        except Exception as e:                       # noqa: BLE001
            bad.append("缩放 %.2fx 报错: %s" % (s, e))
            continue
        if r["owner"] != "遐蝶":
            bad.append("缩放 %.2fx 判成 %s（期望遐蝶）" % (s, r["owner"] or "待复核"))
        elif verbose:
            print("  OK  缩放%.2fx -> %s（分数%.2f）" % (s, r["owner"], r["score"]))
    return bad


def fmt_t(t):
    """帧号格式化：抽帧缓存里有 135.1~135.9 这种 0.1s 帧，用 %.0f 会打印成同一个数字。"""
    t = float(t)
    return ("%d" % t) if abs(t - round(t)) < 1e-6 else ("%.1f" % t)


def _cli():
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="行动轴顶端卡识别（E 线）")
    ap.add_argument("frames", nargs="*", help="帧号，如 226 109.5；也可传图片路径")
    ap.add_argument("--build", action="store_true", help="从真值标签重建模板库")
    ap.add_argument("--selftest", action="store_true", help="真值帧 + 分辨率缩放自检")
    ap.add_argument("--json", action="store_true", help="输出 JSON（给别的会话调用）")
    ap.add_argument("--bank", default=BANK_PATH)
    args = ap.parse_args()
    if args.build:
        build_bank(out_path=args.bank)
        return 0
    bank = load_bank(args.bank)
    if args.selftest:
        print("模板库 %s：%s" % (args.bank, {u: m.shape[0] for u, m in bank.items()}))
        bad = selftest()
        if bad:
            print("\n自检不通过（%d 条）：" % len(bad))
            for b in bad:
                print("  ! " + b)
            return 1
        print("\n自检通过：真值帧 %d 条 + 分辨率缩放 3 档 全部一致" % len(TRUTH_OWNER))
        return 0
    tests = args.frames or ["226", "109", "251", "100", "152", "159", "167", "175",
                            "221", "311", "307", "191", "207", "293", "104", "120",
                            "134", "139"]
    out = []
    for t in tests:
        try:
            src = t if not str(t).replace(".", "").isdigit() else float(t)
            r = read_actor(src, bank)
        except FileNotFoundError as e:
            print("找不到帧/文件：%s" % e)
            continue
        out.append((t, r))
        if not args.json:
            print("%-28s 顶端=%-6s 归属=%-6s 分数%.2f 间距%.2f 标记%-10s %s" %
                  ("t=%s" % t, r["unit"] or "待复核", r["owner"] or "-",
                   r["score"], r["margin"], r["marker"],
                   "| " + str(r["scores"]) if len(tests) <= 8 else ""))
    if args.json:
        print(json.dumps([r for _, r in out], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli())
