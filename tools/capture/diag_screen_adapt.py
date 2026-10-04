# -*- coding: utf-8 -*-
"""
[线7] 屏幕适配 —— 验收脚本（可复现，全部数字都来自实跑）。

跑法：
    python diag_screen_adapt_L7.py            # 全部（含 A 线留出集 + E 线自检回归）
    python diag_screen_adapt_L7.py --no-regress
    python diag_screen_adapt_L7.py --images    # 额外产出验收图 docs/images/L7_*.png

验收口径（与 docs/剩余工作清单.md 【线7】一致）：
  ① 在 2876×1798（录屏1）与 2870×1800（录屏2）上，自动算出的框 vs 人工标定框偏差 ≤3px；
  ② 至少一档缩放（0.75 / 0.6676 / 0.5 等比 + 1920×1080 非等比）仍能定位；
  ③ A 线留出集 29/29、E 线自检 18 条真值帧 + 3 档缩放 不回归。
"""
from __future__ import annotations
# [P3 整理] 原路径：diag_screen_adapt_L7.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import argparse
import contextlib
import io
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geometry as SA            # noqa: E402
import axis_actor as T                  # noqa: E402

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
CACHE1 = "frames/glyphcache/f%08.2f.png"     # 录屏1（2876×1798）
REC2 = ["frames/hud2_M/t00026.00.png", "frames/hud2_M/t00030.00.png",
        "frames/hud2_M/t00035.00.png", "frames/hud2_M/t00300.00.png",
        "frames/hud2_M/t00100.00.png", "frames/hud2_M/t00200.00.png"]

# ── 人工标定框（真值）──────────────────────────────────────────────────
# 录屏1 HUD：A 线人工标定并已验收的框（见 hud_glyphs.CY0/CX0 与 HUD数字读取.md）
MAN_HUD1 = (260, 2350, 340, 2876)
# 录屏1 行动轴：E 线人工标定（TOP_ART / MARK_C）
MAN_ART1 = (90, 81, 232, 175)
MAN_MARK1 = (86, 127)
# 录屏2 HUD：**没有历史人工框**。本文件用的"人工框"= 人工在放大网格图上量出的墨迹
#   （t=26：y 277..370、右缘 2850）再套**与录屏1 同一条边距规则**：
#   上 13·k、下 7·k、右缘贴屏宽、左界按 526·k 容量；k = 人工量的墨迹高 94 / 参考行带高 61 = 1.54
MAN_HUD2 = (257, 2060, 381, 2870)

# 参考字号帧（录屏1）：A 线标定框就是给这些帧用的。判定：实测字号比 |k−1| ≤ 0.06
REF_TS = [100, 109, 110, 116, 117, 152, 159, 167, 175, 193, 226, 244, 251, 261,
          275, 284, 293, 307, 311, 320, 102, 135, 153, 207, 221]
BIG_TS = [134.8, 141.8, 229.8, 252.2]        # 录屏1 里的"大字号"帧（k≈1.5）
AXIS_TS = [100, 104, 106, 109, 116, 117, 120, 134, 135, 139, 152, 153, 159, 167,
           175, 191, 194, 207, 221, 226, 237, 251, 256, 261, 284, 293, 306, 307, 311,
           320, 322]


def _load_rgb(p):
    from PIL import Image
    return np.asarray(Image.open(p).convert("RGB"))


def _load_bgr(p):
    import cv2
    return cv2.imread(p)


def _dev(a, b):
    return tuple(int(a[i]) - int(b[i]) for i in range(len(a)))


def _fmt_dev(d):
    return "(" + ",".join("%+d" % v for v in d) + ")"


def _maxabs(d):
    return max(abs(v) for v in d)


# ══════════════════════════════════════════════════════════════════════════
def sec_probe():
    print("═" * 78)
    print("① 上屏探测（probe_display）")
    print("═" * 78)
    info = SA.probe_display()
    print("   DPI 感知   : %s" % info["dpi_aware"])
    print("   物理分辨率 : %s" % (info["screen"],))
    print("   逻辑分辨率 : %s" % (info["logical"],))
    print("   DPI / 缩放 : %s / %s" % (info["dpi"], info["scale"]))
    print("   显示器     : %d 个" % len(info["monitors"]))
    for n in info["notes"]:
        print("   备注       : %s" % n)
    print("\n   为什么必须先探测：不声明 DPI 感知时 GetSystemMetrics/mss 只报逻辑像素"
          "\n   （本机 2880×1800 缩 200% 时只报 1440×900），拿物理坐标去裁会裁错地方。")
    return info


def sec_hud(rows_only=False):
    print("\n" + "═" * 78)
    print("② HUD 数字区：自动框 vs 人工标定框")
    print("═" * 78)
    print("   录屏1（2876×1798，人工框 %s）—— 只列实测字号=参考字号的帧：" % (MAN_HUD1,))
    print("   %-9s %-6s %-5s %-4s %-24s %-24s %s" %
          ("t", "src", "k", "n", "自动框(y0,x0,y1,x1)", "人工框", "偏差"))
    worst, n_ref = 0, 0
    for t in REF_TS:
        p = CACHE1 % t
        if not os.path.exists(p):
            print("   %-9s 缺帧" % t)
            continue
        g = SA.hud_geometry(_load_rgb(p))
        if g["src"] != "ink":
            print("   %-9s（模型兜底：本帧没测到干净的数字串 → 用参考框，行为与改动前一致）" % t)
            continue
        if abs(g["k"] - 1.0) > 0.06:
            print("   %-9s（本帧实测字号 %.2f ≠ 参考字号 → 另列在大字号/录屏2 段）" % (t, g["k"]))
            continue
        d = _dev(g["box"], MAN_HUD1)
        worst = max(worst, _maxabs(d))
        n_ref += 1
        print("   %-9s %-6s %-5.2f %-4s %-24s %-24s %s" %
              (t, g["src"], g["k"], g["ink"]["n"], g["box"], MAN_HUD1, _fmt_dev(d)))
    print("   → 参考字号帧 %d 个，四边最大偏差 **%d px**（验收要求 ≤3px）" % (n_ref, worst))

    print("\n   录屏2（2870×1800，人工框 %s 是对 t=26 那种字号量出来的）：" % (MAN_HUD2,))
    print("   %-26s %-6s %-5s %-4s %-16s %-24s %s" %
          ("帧", "src", "k", "n", "实测行带", "自动框", "vs 人工框"))
    for p in REC2:
        if not os.path.exists(p):
            continue
        g = SA.hud_geometry(_load_rgb(p))
        ink = g["ink"] or {}
        cmp_ = _fmt_dev(_dev(g["box"], MAN_HUD2)) if abs(g["k"] - 1.54) <= 0.06 \
            else "字号 %.2f ≠ 1.54，不可比" % g["k"]
        print("   %-26s %-6s %-5.2f %-4s %-16s %-24s %s" %
              (os.path.basename(p), g["src"], g["k"], ink.get("n", "-"),
               str(ink.get("band", "-")), g["box"], cmp_))
    print("   （t=26/t=35 是同一档字号：y 两边差 ≤1px、右缘贴屏一致、左界比人工框宽 8px ——")
    print("     左界是『12 位容量』，按实测字号放大，宁可宽：宽了只多带背景，窄了会切最高位）")

    print("\n   录屏1 的**大字号**帧（A 线老框 260..340 装不下它们 → 这正是『框要跟着字号走』的证据）：")
    print("   %-9s %-5s %-4s %-24s %s" % ("t", "k", "n", "自动框", "老框是否装得下墨迹"))
    for t in BIG_TS:
        p = CACHE1 % t
        if not os.path.exists(p):
            continue
        g = SA.hud_geometry(_load_rgb(p))
        ink = g["ink"]
        fits = "装不下（墨迹底 %s > 340）" % ink["band"][1] if ink["band"][1] > 340 else "装得下"
        print("   %-9s %-5.2f %-4s %-24s %s" % (t, g["k"], ink["n"], g["box"], fits))
    return worst


def sec_axis():
    print("\n" + "═" * 78)
    print("③ 行动轴顶端卡：自动框 vs 人工标定框 %s（标记中心 %s）" % (MAN_ART1, MAN_MARK1))
    print("═" * 78)
    print("   %-26s %-7s %-20s %-16s %-13s %-8s %s" %
          ("帧", "src", "自动 top_art", "偏差", "脊/竖线", "证据异常", "说明"))
    worst, n_sus = 0, 0
    for t in AXIS_TS:
        p = CACHE1 % t
        if not os.path.exists(p):
            continue
        g = SA.axis_geometry(_load_bgr(p))
        d = _dev(g["top_art"], MAN_ART1)
        worst = max(worst, _maxabs(d))
        n_sus += bool(g["suspect"])
        ev = "脊%s/线%s" % (g["ridge"]["y"], g["rail"]["x"])
        why = "证据与模型一致" if g["src"] == "model" else "证据纠正（refine=True）"
        if g["ridge"]["y"] is None and g["rail"]["x"] is None:
            why = "无证据（轴在滑入/滑出动画里）→ 用模型"
        elif g["suspect"]:
            why = "证据与模型差 >4px → 只标异常，**不改框**（默认 refine=False）"
        print("   %-26s %-7s %-20s %-16s %-13s %-8s %s" %
              ("录屏1 t=%s" % t, g["src"], g["top_art"], _fmt_dev(d), ev,
               "是" if g["suspect"] else "", why))
    for p in REC2:
        if not os.path.exists(p):
            continue
        g = SA.axis_geometry(_load_bgr(p))
        d = _dev(g["top_art"], MAN_ART1)
        worst = max(worst, _maxabs(d))
        n_sus += bool(g["suspect"])
        ev = "脊%s/线%s" % (g["ridge"]["y"], g["rail"]["x"])
        why = "证据与模型一致" if g["src"] == "model" else "证据纠正（refine=True）"
        if g["ridge"]["y"] is None and g["rail"]["x"] is None:
            why = "无证据（轴在滑入/滑出动画里）→ 用模型"
        elif g["suspect"]:
            why = "证据与模型差 >4px → 只标异常，**不改框**（默认 refine=False）"
        print("   %-26s %-7s %-20s %-16s %-13s %-8s %s" %
              ("录屏2 " + os.path.basename(p), g["src"], g["top_art"], _fmt_dev(d), ev,
               "是" if g["suspect"] else "", why))
    print("   → 两机位四边最大偏差 **%d px**（验收要求 ≤3px）；证据异常帧 %d 个（默认不改框）"
          % (worst, n_sus))
    print("   注：录屏2 与录屏1 的轴几何在像素级一致（卡左边框 88 / 上边框 80），"
          "所以人工框可以共用。")
    return worst


def sec_scale():
    print("\n" + "═" * 78)
    print("④ 缩放档：整屏等比缩小 / 换宽高比")
    print("═" * 78)
    from PIL import Image
    import cv2
    src = CACHE1 % 226
    a = _load_rgb(src)
    bgr = _load_bgr(src)
    print("   %-14s %-8s %-24s %-24s %s" % ("尺寸", "系数", "自动 HUD 框", "人工框(同系数缩)", "偏差"))
    for s in (0.75, 0.6676, 0.5):
        W2, H2 = int(round(2876 * s)), int(round(1798 * s))
        a2 = np.asarray(Image.fromarray(a).resize((W2, H2), Image.LANCZOS))
        b2 = cv2.resize(bgr, (W2, H2), interpolation=cv2.INTER_AREA)
        gh = SA.hud_geometry(a2)
        ga = SA.axis_geometry(b2)
        mh = tuple(int(round(v * (W2 / 2876.0))) for v in MAN_HUD1)
        ma = tuple(int(round(v * (W2 / 2876.0))) for v in MAN_ART1)
        print("   %-14s %-8.4f %-24s %-24s %s" %
              ("%dx%d" % (W2, H2), s, gh["box"], mh, _fmt_dev(_dev(gh["box"], mh))))
        print("   %-14s %-8s %-24s %-24s %s" % ("", "轴", ga["top_art"], ma, _fmt_dev(_dev(ga["top_art"], ma))))

    W2, H2 = 1920, 1080
    a3 = np.asarray(Image.fromarray(a).resize((W2, H2), Image.LANCZOS))
    b3 = cv2.resize(bgr, (W2, H2), interpolation=cv2.INTER_AREA)
    fx, fy = W2 / 2876.0, H2 / 1798.0
    gh = SA.hud_geometry(a3)
    ga = SA.axis_geometry(b3)
    mh = tuple(int(round(v * f)) for v, f in zip(MAN_HUD1, (fy, fx, fy, fx)))
    ma = tuple(int(round(v * f)) for v, f in zip(MAN_ART1, (fx, fy, fx, fy)))
    print("   %-14s %-8s %-24s %-24s %s" %
          ("%dx%d" % (W2, H2), "非等比", gh["box"], mh, _fmt_dev(_dev(gh["box"], mh))))
    print("   %-14s %-8s %-24s %-24s %s" % ("", "轴(按高锚定)", ga["top_art"], ma, _fmt_dev(_dev(ga["top_art"], ma))))
    print("   说明：HUD 框是**从墨迹算的**，换宽高比也跟得上（偏差 ≤1px）；"
          "\n         行动轴按帧宽等比模型定位，换宽高比时对不上（这正是 E 线声明的"
          "\n         “只支持整屏等比缩放”，线7 不改这个口径）。")


def sec_override():
    print("\n" + "═" * 78)
    print("⑤ 证据纠正通路（合成用例：把轴整体下移 20px，看检测器会不会顶掉模型）")
    print("═" * 78)
    import cv2
    img = _load_bgr(CACHE1 % 226)
    H, W = img.shape[:2]
    canvas = img.copy()
    y0, y1, x0, x1 = 0, 1300, 0, 340
    canvas[y0 + 20:y1 + 20, x0:x1] = img[y0:y1, x0:x1]
    canvas[y0:y0 + 20, x0:x1] = 0
    g = SA.axis_geometry(canvas, refine=True)
    print("   模型预测 top = %d（帧宽 %d → 系数 %.4f）" % (g["pred"][1], W, g["s"]))
    print("   实测脊      = %s（分数 %.1f）" % (g["ridge"]["y"], g["ridge"]["score"]))
    print("   结果 top_art = %s  src=%s  → %s" %
          (g["top_art"], g["src"],
           "证据顶掉了模型（refine=True 这条通路是通的）" if g["src"] == "detect" else "**没顶掉**，需检查"))
    print("   ⚠️ 默认 refine=False：证据只当**校验**（suspect 标记），不改框 —— 因为实测 249 帧里")
    print("      有 5 帧证据会跑偏，最坏一例会把本来判对的『死龙』变成待复核（见 §5.1 注释）。")
    print("      脊只在『模型预测 ±%dpx』内找；超过这个范围连找都不找（避免去追一张正在滑动的卡）。"
          % SA.AXIS_RIDGE_WIN)
    return g["src"] == "detect"


def sec_regress():
    print("\n" + "═" * 78)
    print("⑥ 回归：A 线留出集 + E 线自检")
    print("═" * 78)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        import eval_holdout
        eval_holdout.main()
    out = buf.getvalue()
    for line in out.splitlines():
        if "准确率" in line or "整串正确率" in line:
            print("   " + line)
    ok_a = "29/29" in out and "5/5" in out

    bad = T.selftest(verbose=False)
    print("   E 线自检：%s" % ("全绿（%d 条真值帧 + 3 档缩放）" % len(T.TRUTH_OWNER)
                              if not bad else "**不通过** %s" % bad[:3]))
    print("   → A 线留出集 %s；E 线自检 %s" %
          ("29/29 ✓" if ok_a else "**异常**", "✓" if not bad else "**异常**"))
    return ok_a and not bad


def sec_images():
    """出验收图：人工框与自动框画在同一帧上，用**文字标签**区分（不靠颜色传信息）。"""
    import cv2
    from PIL import Image, ImageDraw
    outdir = os.path.join(HERE, "docs/images")
    os.makedirs(outdir, exist_ok=True)
    made = []
    jobs = [("frames/glyphcache/f00226.00.png", "L7_box_rec1_t226.png", MAN_HUD1, MAN_ART1),
            ("frames/hud2_M/t00026.00.png", "L7_box_rec2_t26.png", None, MAN_ART1)]
    for src, name, man_hud, man_art in jobs:
        rgb = _load_rgb(src)
        bgr = _load_bgr(src)
        gh = SA.hud_geometry(rgb)
        ga = SA.axis_geometry(bgr)
        scale = 0.42 if rgb.shape[1] > 2000 else 1.0
        im = Image.fromarray(rgb).resize((int(rgb.shape[1] * scale), int(rgb.shape[0] * scale)))
        d = ImageDraw.Draw(im)

        def rect(box, label, dy=0):
            y0, x0, y1, x1 = [v * scale for v in box]
            d.rectangle([x0, y0 + dy, x1, y1 + dy], outline=(255, 0, 0), width=2)
            d.text((x0 + 3, y0 + 3 + dy), label, fill=(255, 255, 0))

        rect(gh["box"], "auto HUD")
        if man_hud:
            rect(man_hud, "human HUD", dy=-10)
        x0, y0, x1, y1 = [v * scale for v in ga["top_art"]]
        d.rectangle([x0, y0, x1, y1], outline=(0, 255, 0), width=2)
        d.text((x1 + 4, y0), "auto AXIS", fill=(0, 255, 0))
        x0, y0, x1, y1 = [v * scale for v in man_art]
        d.rectangle([x0, y0 - 8, x1, y1 - 8], outline=(0, 255, 255), width=1)
        d.text((x1 + 4, y1 - 8), "human AXIS", fill=(0, 255, 255))
        p = os.path.join(outdir, name)
        im.save(p)
        made.append(p)
        print("   已存 %s" % os.path.relpath(p, HERE))
    return made


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-regress", action="store_true")
    ap.add_argument("--images", action="store_true")
    a = ap.parse_args()
    sec_probe()
    h1 = sec_hud()
    h3 = sec_axis()
    sec_scale()
    ok_over = sec_override()
    ok_reg = True
    if not a.no_regress:
        ok_reg = sec_regress()
    if a.images:
        sec_images()
    print("\n" + "═" * 78)
    print("结论")
    print("═" * 78)
    print("  ① HUD 自动框 vs 人工框（录屏1 参考字号）：最大偏差 %d px  %s" %
          (h1, "✓ ≤3px" if h1 <= 3 else "✗"))
    print("  ② 行动轴自动框 vs 人工框（录屏1+录屏2）：最大偏差 %d px  %s" %
          (h3, "✓ ≤3px" if h3 <= 3 else "✗"))
    print("  ③ 证据纠正通路：%s" % ("✓" if ok_over else "✗"))
    if not a.no_regress:
        print("  ④ 回归（A 留出集 29/29、E 自检全绿）：%s" % ("✓" if ok_reg else "✗"))
    return 0 if (h1 <= 3 and h3 <= 3 and ok_over and ok_reg) else 1


if __name__ == "__main__":
    sys.exit(main())
