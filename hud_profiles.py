# -*- coding: utf-8 -*-
"""
[A 线] HUD 字体档案（profile）—— 支持"总伤 HUD 不止一种字体"。

背景（用户 2026-09-30 提出）：**银狼999 的总伤数字不是常规字体**。
一种字体 = 一套「区域 + 掩膜 + 分类器 + 几何范围」，不能共用：
  * 字体不同 → 字形形状不同 → 必须有自己的分类器（拿常规字体的分类器去认，
    它会给出**自信但错误**的答案，比标"待复核"危险得多）；
  * 字号/位置可能不同 → 裁剪框与掩膜模式可能要重标定。

本文件把"一种字体"需要的东西集中登记，新增字体时**只加一条档案**，
不改 read_hud / hud_glyphs 的代码。

⚠️ 新增字体的前提是**素材**（能看清数字的原始像素）。最小可用素材 = **一张截图**
（甚至不用录屏）：只要数字像素清楚，就能切字形、让用户读数、训一个小分类器。
"""
import os

import numpy as np

from mvp.resource import resource as _res   # 打包专项：模型/数据集路径按 exe 位置解析

# 几何守门：字形像素高/宽/宽高比落在该范围内才算"我认识的这种字体"。
# 实测（2026-09-30，140 个字形 / 25 帧，当前字体）：高 60~79、宽 22~52、宽高比 0.32~0.83。
# 这里给足余量：只用来抓"明显不是这套字形"（换字体/换分辨率/区域跑偏），
# 不能靠它分辨"同尺寸的另一种字体"——那种情况要靠低置信 + 多帧不稳定来兜（见 read_hud.vote_frames_checked）。
DEFAULT_GEOM = {"h": (50, 95), "w": (14, 60), "ratio": (0.22, 1.05)}

PROFILES = {
    "default": {
        "label": "崩铁常规总伤 HUD 字体",
        "box": (260, 2350, 340, 2876),     # (y0, x0, y1, x1) **参考标定值**（2876×1798）
        "locate": True,                    # True → 换分辨率/换字号时按画面动态定位（线7）
        "mode": "glow",                    # 列分割用的掩膜
        "glyph_mode": "hybrid_s",          # 取字形像素用的掩膜
        "expand": 3,
        "model": "out/digit_cnn.pt",
        "dataset": "out/digit_dataset.npz",
        "onnx": "out/digit_cnn.onnx",
        "geom": DEFAULT_GEOM,
        "ready": True,
    },
    # ── 像素方块字体：**只在银狼999 的强化普攻（强普）出现**（用户 2026-09-30 确认）──
    # 素材已到：`records/屏幕录制 2026-09-30 192031.mp4`（6分22秒，2870×1800）里
    # 多个时间段都有它（实测 t≈48 / 96 / 144 / 240 / 272 …）。
    # 已标定：区域、掩膜（青绿填充）、几何范围。
    # **尚未做**：让用户读数 → 训练它自己的分类器 → 验收。
    "yinlang999": {
        "label": "银狼999 总伤字体（像素方块字体）",
        # ⚠️ 2026-10-05 改框：原框 (250,2400,360,2870) 是**录屏1 标**的，太窄太矮：
        #    * 像素体数字实测在 **y 224~341 / x 2042~2869**，原框上边 250 会把字顶切掉
        #      → 实时链路读到**截顶的字形**（t=45 字高 53 vs 训练时 66、t=238 首字 43 vs 49）；
        #    * 12 位口径需要 ≈670px 宽（见 用户口径与铁律 Q7），原框只有 470px。
        #    换成 线2 验过的框（`hud_read_team2.HUD_REGION`，770×148）：
        #    它同时**容得下实机 +25px 的偏移**（录屏1 实测偏差 → 数字会更靠下）。
        #    ⚠️ 别再往上/下扩：实测把上界放到 200 会让蓝云进列分割、把相邻字**粘成 67px 宽块**。
        "box": (226, 2100, 374, 2876),
        # 这套字体是**青绿**掩膜，线7 的"黄色墨迹"定位器对它不适用 → 关掉动态定位，
        # 用上面这条标定框（要适配它得另写一套掩膜定位，不在线7 范围）。
        "locate": False,
        "mode": "cyan",                  # 青绿填充掩膜，见 hud_glyphs.extract_cyan
        "glyph_mode": "cyan",
        "expand": 0,
        "model": "out/digit_cnn_yinlang999.pt",
        "dataset": "out/digit_dataset_yinlang999.npz",
        "onnx": "out/digit_cnn_yinlang999.onnx",
        # 实测：真字形高 47~94、宽 20~71；碎片高 8~34、质量 ≤170（用 h/mass 两条闸挡）。
        # ⚠️ 2026-10-05：宽高比上限 1.10 **太紧** —— t=100（真值 506286）里合法的
        #    `6` = 58×49 = **1.18**、`2` = 57×51 = 1.12 都被判成"坏字形" →
        #    实时链路读出 `50??86`（而分类器逐位全对！线2 不做这道几何闸，所以它读得对）。
        #    按实测放宽到 1.35（留 ~15% 余量）；挡"换字体/区域跑偏"仍靠 w≤80、h≤118。
        "geom": {"h": (40, 100), "w": (18, 80), "ratio": (0.20, 1.35)},
        "ready": True,
        "note": "分类器已训练（74 样本 / 14 帧；留一帧 70/74 = 94.6%；集成 14/15 整串）。"
                "已知：真粘连块（>80px）不拆、整块丢弃 → 该帧读数会少位，"
                "训练侧用'右缘检查'拒绝这类帧（见 train_pixel_A.py）",
        "actor_keys": ["银狼LV.999", "银狼999", "狼尊", "yinlang999", "999", "silverwolf999"],
    },
}

# ── 档案里的文件路径统一解析（打包专项）─────────────────────────────────────
# 原来写的是 "out/digit_cnn.pt" 这种**相对当前工作目录**的路径；双击 exe 时工作目录
# 可能是桌面/任意地方 → 读不到模型。这里一次性换成 `mvp.resource.resource()` 解析出的
# 绝对路径（源码模式下解析结果 = 原来的 <仓库根>/out/... ，行为不变）。
for _prof in PROFILES.values():
    for _k in ("model", "dataset", "onnx"):
        if _prof.get(_k):
            _prof[_k] = _res(_prof[_k])

# ── 行动者 → 字体档案 的映射（**与 E 线配合的关键**）──
# 用户 2026-09-30 明确：像素风数字**只在银狼999 的强化普攻**出现。
# 所以不需要从图像里猜字体 —— 让行动轴判"当前行动者是谁"，直接选档案：
#   行动轴顶端 = 银狼999/狼尊 → 用 yinlang999 档案
#   其它                       → 用 default 档案
# 这比任何图像启发式都可靠：行动者身份是 E 线已经要交付的东西。
def profile_for_actor(actor):
    """
    由"当前行动者"选字体档案。

    actor 可以是字符串（角色名/别名，大小写与空格不敏感）或 None。
    未知/None → "default"（常规字体）。这是 A 线与 E 线的衔接点：
    E 线给出行动轴顶端是谁，A 线据此选档案，不需要图像侧猜字体。
    """
    if not actor:
        return "default"
    key = str(actor).strip().lower().replace(" ", "")
    for name, p in PROFILES.items():
        for k in p.get("actor_keys", []):
            if key == k.lower() or k.lower() in key:
                return name
    return "default"


def get(name="default"):
    if name not in PROFILES:
        raise KeyError("未知字体档案 %r；可选: %s" % (name, sorted(PROFILES)))
    return PROFILES[name]


def is_ready(name="default"):
    return bool(get(name).get("ready"))


def require_ready(name="default"):
    """要求"能读数"：既有标定好的区域/掩膜，也训练好了自己的分类器。"""
    p = get(name)
    if not p.get("ready"):
        raise RuntimeError(
            "字体档案 %r 还不能读数（%s）。它需要自己的分类器，"
            "不能用常规字体模型硬认——见 HUD数字读取.md" % (name, p.get("note", "")))
    return p


def require_calibrated(name="default"):
    """要求"区域/掩膜已标定"（允许分类器还没训练）—— 切字形、出读数图用这个。"""
    p = get(name)
    if not p.get("box"):
        raise RuntimeError("字体档案 %r 尚未标定区域（box）" % name)
    return p


def box_for(name="default", frame=None):
    """
    取该档案的裁剪框，返回 (box, bar_rows)。

    frame : 整帧（RGB）时 → **按画面动态定位**（线7）。这样换分辨率/换字号时框跟着走，
            不再依赖写死的 2350/260；定位不出来（HUD 隐藏、读数在过渡动画里）会自动
            退回档案里的参考标定 box，行为与改动前一致。
            frame=None → 直接用参考标定 box（老脚本、标定工具用这条）。

    哪些档案走动态定位：只有"黄色常规字体"这类（`mode != 'cyan'` 且 `locate=True`）。
    像素字体（银狼999）是青绿掩膜，需要它自己的定位器，线7 不动。
    """
    p = require_calibrated(name)
    if frame is not None and p.get("locate") and p.get("mode") != "cyan":
        import geometry as SA
        g = SA.hud_geometry(frame)
        return tuple(g["box"]), tuple(g["bar_rows"])
    return tuple(p["box"]), None


def glyphs(name, frame_array, **over):
    """按档案切字形。frame_array 必须是**整帧**（已经裁好的区域请用 glyphs_cropped）。

    `strict`（只对像素体有意义）会透传给 `glyphs_cropped`。
    """
    p = require_calibrated(name)
    strict = over.pop("strict", False)
    if "box" in over:
        box, bar_rows = over["box"], over.get("bar_rows")
    else:
        box, bar_rows = box_for(name, frame_array)
    y0, x0, y1, x1 = box
    region = np.asarray(frame_array[y0:y1, x0:x1], dtype=np.int16)
    if region.size == 0:
        raise RuntimeError(
            "在图上取不到档案 %r 的区域 %s（图尺寸 %s×%s）："
            "如果传进来的是**已裁好的区域**，请用 glyphs_cropped(profile, region, top, left)"
            % (name, (y0, x0, y1, x1), frame_array.shape[1], frame_array.shape[0]))
    return glyphs_cropped(name, region, y0, x0, bar_rows=bar_rows, strict=strict)


def glyphs_cropped(name, region, top, left, bar_rows=None, strict=False):
    """给"已经裁好的区域"用（实时线）。按档案的 mode 分派到对应实现。

    `strict`：只对**像素体**有意义 —— 用收紧掩膜（挡录屏2 t=200 那种整片蓝云背景）。
    两个口径**都要试**（见 `mvp/reader.py` 的像素体兜底）：默认口径与训练分布一致，
    收紧口径只有在默认口径不可用时才采信。
    """
    import hud_glyphs as HG
    p = require_calibrated(name)
    if p["mode"] == "cyan":
        return HG.extract_cyan(region, top=top, left=left, strict=strict)
    return HG.extract_cropped(region, top=top, left=left,
                              mode=p["mode"], glyph_mode=p["glyph_mode"], expand=p["expand"],
                              bar_rows=bar_rows)


def geom_ok(name, w, h):
    """几何守门：返回 (是否在范围内, 说明)。档案没登记几何范围时一律放行。"""
    g = get(name).get("geom")
    if not g:
        return True, ""
    if not (g["h"][0] <= h <= g["h"][1]):
        return False, "字形高 %d 不在该字体观测范围 %s 内" % (h, g["h"])
    if not (g["w"][0] <= w <= g["w"][1]):
        return False, "字形宽 %d 不在该字体观测范围 %s 内" % (w, g["w"])
    r = w / max(1.0, float(h))
    if not (g["ratio"][0] <= r <= g["ratio"][1]):
        return False, "字形宽高比 %.2f 不在该字体观测范围 %s 内" % (r, g["ratio"])
    return True, ""


def model_path(name="default"):
    p = require_ready(name)
    return p["model"] if os.path.exists(p["model"]) else None
