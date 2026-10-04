# -*- coding: utf-8 -*-
"""
[A 线] 端到端自检：行动者 → 字体档案 → 读数。

给 E 线看的就是这条链：同一个界面下，行动者不同 → 走不同字体档案；
选错档案时 n_glyphs=0（切不出字），正是"字体切换"的可观测信号。

用法: python test_actor_A.py
"""
# [P3 整理] 原路径：test_actor_A.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from ffmpeg_path import require_ffmpeg as _req_ff
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import os
import subprocess
import sys

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
sys.path.insert(0, HERE)
import hud_profiles as HP  # noqa
from read_hud import read_for_actor  # noqa

PIX = [(45, "52576"), (46, "111391"), (48, "474099"), (53, "76912"), (55, "286969"),
       (96, "109046"), (98, "343829"), (124, "8858"), (130, "301696"),
       (131, "540227"), (144, "317595")]
NORM = [(134, "47794"), (152, "324751")]

VIDEO3 = os.path.join(HERE, "records", "屏幕录制 2026-09-30 192031.mp4")
FFMPEG = _req_ff()   # 见 ffmpeg_path.py（可用 HSR_FFMPEG 指定）
FCACHE = os.path.join(HERE, "frames", "full3_A")


def pix_frame(t):
    """按需抽整帧 —— 临时缓存已清理，这里随时重建（约 0.6s/帧）。"""
    p = os.path.join(FCACHE, "f%08.2f.png" % t)
    if not os.path.exists(p):
        os.makedirs(FCACHE, exist_ok=True)
        subprocess.run([FFMPEG, "-ss", "%.3f" % t, "-i", VIDEO3, "-frames:v", "1", "-y", p],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p if os.path.exists(p) else None


def main():
    print("=== 像素字体帧 + 行动者=狼尊（档案 yinlang999）===")
    ok = 0
    for t, want in PIX:
        p = pix_frame(t)
        if not p:
            continue
        r = read_for_actor(p, actor="狼尊")
        good = r["text"] == want
        ok += good
        print("   t=%-5s 期望 %-8s 读出 %-8s %-4s verdict=%-4s n_glyphs=%s" % (
            t, want, r["text"], "OK" if good else "BAD", r["verdict"], r["n_glyphs"]))
    print("   整串正确 %d/%d" % (ok, len(PIX)))

    print("\n=== 同一批像素字体帧 + 行动者=遐蝶（错选常规档案）===")
    t = PIX[0][0]
    r = read_for_actor(pix_frame(t), actor="遐蝶")
    print("   t=%-5s verdict=%s text=%r profile=%s n_glyphs=%s" % (
        t, r["verdict"], r["text"], r["profile"], r["n_glyphs"]))
    print("   → 常规档案在像素字体帧上切不出字（n_glyphs=0），这就是字体切换的可观测信号")

    print("\n=== 常规字体帧 + 常规行动者（回归）===")
    for t, want in NORM:
        p = os.path.join(HERE, "frames", "glyphcache", "f%08.2f.png" % t)
        r = read_for_actor(p, actor="遐蝶")
        print("   t=%-5s 期望 %-8s 读出 %-8s verdict=%s" % (t, want, r["text"], r["verdict"]))

    print("\n=== 档案状态 ===")
    for name, p in HP.PROFILES.items():
        print("   %-10s ready=%-5s mode=%-5s label=%s" % (
            name, p["ready"], p["mode"], p["label"]))


if __name__ == "__main__":
    main()
