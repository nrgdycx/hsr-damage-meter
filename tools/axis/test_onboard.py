# -*- coding: utf-8 -*-
"""onboarding 流水线的自检（`axis_onboard.py` 的回归测试）。

为什么必须有这个文件：模板库是"静默污染"最危险的资产 —— 裁剪框错几行，程序不报错、
只是分数普遍偏低、然后一堆帧变成「待复核」，很难查回根因。**本项目就踩过一次**：
`art_of_crop` 把基准系坐标直接当裁块内坐标用，漏减裁块原点 (40,50)，
ROI 上移 50 行、底部被截 8 行，特征 max|diff| ≈ 9（识别分数会整体塌下来）。

本自检把口径钉死：**同一个角色帧，经 onboarding 的裁块路径算出的特征，
必须与既有验证过的模块（`axis_actor_team2` 的裁块路径）逐位一致。**

用法：python tools/axis/test_onboard.py
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(HERE))

import axis_onboard as O      # noqa: E402
import axis_actor as T        # noqa: E402
import axis_actor_team2 as T2      # noqa: E402

# 队伍2 的裁块缓存（frames/axis2_L2）：已有真值标签，作为口径基准
BASE_W = 2870
PROBE_T = (12, 13, 44, 148, 247, 205, 322)
TOL = 1e-4


def test_crop_coordinate_space():
    """裁块坐标系：onboarding 的特征必须与 E2 模块逐位一致。"""
    bad = []
    for t in PROBE_T:
        a = T2.feats_top_zoom(T2.load_crop(t), 1.0)
        crop = O._load_crop("team2", t, BASE_W)
        if crop is None:
            bad.append("t=%s 读不到裁块" % t)
            continue
        art = O.art_of_crop(crop, BASE_W)
        # 1) 头像区尺寸必须等于参考框在基准宽度下的尺寸
        s = BASE_W / float(T.REF_W)
        exp = (int(round((T.TOP_ART[3] - T.TOP_ART[1]) * s)),
               int(round((T.TOP_ART[2] - T.TOP_ART[0]) * s)))
        if art.shape[:2] != exp:
            bad.append("t=%s 头像区尺寸 %s ≠ 期望 %s（裁块原点没减对？）"
                       % (t, art.shape[:2], exp))
        for z in T.ZOOMS:
            ref = T2.feats_top_zoom(T2.load_crop(t), z)
            got = O.feats_of_art(art, z)
            d = float(np.abs(ref - got).max())
            if d > TOL:
                bad.append("t=%s zoom=%.2f 特征差 %.2e > %.0e" % (t, z, d, TOL))
    return bad


def test_marker_geometry():
    """标记区：onboarding 拼出的画布必须让既有标记库认出我方标记。"""
    bad = []
    for t, exp in ((148, "ally"), (247, "ally"), (44, "ally")):
        crop = O._load_crop("team2", t, BASE_W)
        if crop is None:
            bad.append("t=%s 读不到裁块" % t)
            continue
        full = O._canvas_of(crop, BASE_W)
        got = T.marker_feat(full, s=BASE_W / float(T.REF_W))[0]
        if not got.startswith(exp):
            bad.append("t=%s 标记判成 %s（期望 %s*）" % (t, got, exp))
    return bad


def test_bank_shape_contract():
    """模板库契约：每类 (n*len(ZOOMS), 4, 48, 72)，否则实时匹配会静默算错。"""
    bad = []
    with np.load(T.BANK_PATH) as z:
        for k in z.files:
            arr = z[k]
            if arr.ndim != 4 or arr.shape[1:] != (4, 48, 72):
                bad.append("%s 形状 %s 不符 (n*%d, 4, 48, 72)"
                           % (k, arr.shape, len(T.ZOOMS)))
            elif arr.shape[0] % len(T.ZOOMS):
                bad.append("%s 模板数 %d 不是 %d 的整数倍" % (k, arr.shape[0], len(T.ZOOMS)))
    return bad


def main():
    tests = [("裁块坐标系（防模板静默污染）", test_crop_coordinate_space),
             ("标记几何", test_marker_geometry),
             ("模板库形状契约", test_bank_shape_contract)]
    allbad = []
    for name, fn in tests:
        try:
            bad = fn()
        except Exception as e:                                  # noqa: BLE001
            bad = ["%s: %s" % (type(e).__name__, e)]
        if bad:
            allbad += ["[%s] %s" % (name, b) for b in bad]
            print("  FAIL %s" % name)
            for b in bad:
                print("       ! %s" % b)
        else:
            print("  OK   %s" % name)
    if allbad:
        print("\n自检不通过（%d 条）" % len(allbad))
        return 1
    print("\n自检通过：onboarding 与既有识别流水线口径一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
