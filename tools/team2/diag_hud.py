# -*- coding: utf-8 -*-
"""【线2】录屏2 HUD 读数的**验收**（用用户 13 格真值）+ 参数定标（只读，不改上游）。

真值来源：`docs/用户口径与铁律.md` Q1（用户逐帧读数）。
⚠️ **时刻已按 `docs/用户口径与铁律.md` 的更正重新钉正**（用户 2026-10-01 的回答把 t=200/238/300/340
   四格写串了一位，而 `samples/请看_录屏2_HUD待读.png` 这张图里每格的帧号是画在图上、可核对的）：
     图上 t=200 → `2052321`（像素体）、t=238 → `123692`（像素体）、
     t=300 → `1371940`（常规体）、t=340 → `835070`（偏暗的过渡帧）。

用法：
  python -u diag_l2_hud.py             # 验收：13 格真值逐条判定（双字体管线）
  python -u diag_l2_hud.py --single    # 只看常规体那一路（复盘"为什么以前读不出来"）
  python -u diag_l2_hud.py --font      # 统计每格两套字体各自能不能读（字体判别的证据）
"""
# [P3 整理] 原路径：diag_l2_hud.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import os
import sys

import numpy as np
from PIL import Image

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
sys.path.insert(0, HERE)

import hud_read_team2 as H      # noqa: E402

FULL_DIR = "frames/hud2_M"

# 用户真值（None = 用户明确说是过渡动画、屏幕上没有稳定数字）
TRUTH = {26: "140130", 29: "286055", 30: "279947", 31: "279947", 35: "100291",
         64: None, 100: "506286", 110: None, 150: None,
         200: "2052321", 238: "123692", 300: "1371940", 340: "835070"}
# 上面四格是**更正后**的时刻（原 用户口径与铁律.md 记作 200空/238=2052321/300=123692/340=1371940）
CORRECTED = {200, 238, 300, 340}


def load_full(t):
    p = os.path.join(FULL_DIR, "t%08.2f.png" % t)
    if not os.path.exists(p):
        return None
    return np.asarray(Image.open(p).convert("RGB"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--single", action="store_true", help="只跑常规体那一路")
    ap.add_argument("--font", action="store_true", help="列出每格两套字体各自的读数")
    ap.add_argument("--l7box", action="store_true",
                    help="改用线7（geometry.hud_geometry）算出的动态框，而不是本线的写死框")
    args = ap.parse_args()
    model = H.load_model()
    model_pixel = None if args.single else H.load_pixel_model()
    l7 = None
    if args.l7box:
        import geometry as S
        l7 = S

    ok = abstain = wrong = missing = 0
    print("== 录屏2 HUD 读数验收（13 格用户真值）%s ==" % ("【用线7 动态框】" if args.l7box else ""))
    print("%-6s %-11s %-11s %-6s %-8s %s" % ("t", "用户真值", "读出", "字体", "判定", "备注"))
    for t in sorted(TRUTH):
        a = load_full(t)
        if a is None:
            print("%-6s %-11s %s" % (t, TRUTH[t] or "(空)", "缺帧"))
            missing += 1
            continue
        y0, x0, y1, x1 = H.HUD_REGION
        if l7 is not None:
            y0, x0, y1, x1 = l7.hud_geometry(a)["box"]
        y1, x1 = min(y1, a.shape[0]), min(x1, a.shape[1])
        region = a[y0:y1, x0:x1]
        if args.single:
            r = H.read_region(model, region, origin=(y0, x0))
            row = {"text": r["text"], "verdict": r["verdict"], "font": "default",
                   "default": r, "pixel": {"text": "", "verdict": "-"}}
        else:
            row = H.read_dual(region, origin=(y0, x0), model=model, model_pixel=model_pixel)
        exp = TRUTH[t]
        if row["verdict"] == "ok" and exp and row["text"] == exp:
            verdict, ok = "✓ 命中", ok + 1
        elif row["verdict"] in ("空", "待复核"):
            verdict, abstain = "○ 安全弃权", abstain + 1
        elif exp is None and row["verdict"] == "空":
            verdict, abstain = "○ 安全弃权", abstain + 1
        else:
            verdict, wrong = "✗ 错", wrong + 1
        note = []
        if t in CORRECTED:
            note.append("（时刻已按图上帧号更正）")
        if exp is None:
            note.append("（真值是空/过渡）")
        if args.font:
            note.append("常规体=%s 像素体=%s" % (row.get("default", {}).get("text") or "-",
                                            row.get("pixel", {}).get("text") or "-"))
        print("%-6s %-11s %-11s %-6s %-8s %s"
              % (t, exp or "(空)", row["text"] or "(空)", row.get("font", "-"), verdict,
                 " ".join(note)))
    print("\n小计：命中 %d / 安全弃权 %d / **错 %d** / 缺帧 %d（共 %d 格）"
          % (ok, abstain, wrong, missing, len(TRUTH)))
    print("说明：'安全弃权'= 判「空」或「待复核」，即**不给错数**（项目口径：宁可漏，不要错）")
    return 0 if wrong == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
