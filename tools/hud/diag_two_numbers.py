# -*- coding: utf-8 -*-
"""[本对话专用 · 只读] 验一个可疑点：t=300 的帧里是不是同时有两个数（中心数字 + 右上 HUD）。

我的框×链扫描里，t=300 在"上下放宽 (240,2200,366,2876)"下读出了 1371940，
而 1371940 是用户给 t=340 的真值 → 怀疑 t=300 屏幕上**同时**存在两个数字：
  · 阿哈/欢愉技结算时，屏幕正中心也会显示一个总伤（用户 Q6 说过）；
  · 右上角是逐次技结算的 HUD。
若成立：线2 的框必须**限定在右上角 HUD**，不能把中心数字一起框进来。

用法：python -u diag_two_numbers.py
"""
# [P3 整理] 原路径：diag_two_numbers.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
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

import hud_glyphs as HG   # noqa: E402
import read_hud           # noqa: E402

FRAME_DIR = "frames/hud2_M"
BAND = (240, 366)          # HUD 所在纵向高度带


def read_box(a, model, box):
    import torch
    gs = HG.extract(a, box=box)
    if not gs:
        return None, 0
    x = torch.tensor(np.stack([v for v, _, _ in gs])[:, None], dtype=torch.float32)
    res = read_hud.classify(model, [(x[i:i + 1], gs[i][1], gs[i][2]) for i in range(len(gs))])
    txt = "".join("?" if d is None else str(d) for d, _ in res)
    return txt, len(gs)


def scan_frame(t, model):
    p = os.path.join(FRAME_DIR, "t%08.2f.png" % t)
    if not os.path.exists(p):
        print("  t=%s 缺帧" % t)
        return
    a = np.asarray(Image.open(p).convert("RGB"))
    H, W = a.shape[:2]
    print("\n" + "=" * 96)
    print("t=%s  帧尺寸 %dx%d" % (int(t), W, H))
    # 整幅宽度切成 6 片，每片单独找"成串数字"（链式右对齐规则依然生效）
    for i in range(6):
        x0, x1 = int(W * i / 6), int(W * (i + 1) / 6)
        txt, n = read_box(a, model, (BAND[0], x0, BAND[1], x1))
        print("   片%d x[%4d,%4d]  %s" % (i, x0, x1, ("切出 %d 个 → %s" % (n, txt)) if n else "无字形"))
    # 直接问两个可疑区域
    for label, box in (("右上 HUD 区 (240,2100,366,2876)", (240, 2100, 366, 2876)),
                       ("画面中央带 (240,1000,366,1900)", (240, 1000, 366, 1900))):
        txt, n = read_box(a, model, box)
        print("   %-34s %s" % (label, ("切出 %d 个 → %s" % (n, txt)) if n else "无字形"))


def main():
    model = read_hud.load_model()
    for t in (238, 300, 340):
        scan_frame(t, model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
