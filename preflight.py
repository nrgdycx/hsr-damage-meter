# -*- coding: utf-8 -*-
'''
实机测试前的**前置检查**：确认这次跑所需的东西都在、且是新鲜的。

为什么需要：我出过两次同类事故 ——
  ① 清理发布时误删了 `out/frames_dense4.csv` 等**权威输入**（回归直接跑不了）；
  ② 打包漏了 `tools/team2/`（盲盒/阿哈认脸在 exe 里不存在）。
都是在"以为没事"的情况下发生的。所以实机前先自查一遍。
'''

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vendor"))

EXE = os.path.join(ROOT, "dist", "HSR伤害统计", "HSR伤害统计.exe")

#: 运行/回归必需的资源（缺一个就不是"能不能跑"的问题，而是"结果对不对"）
MUST = [
    ("HUD 常规字体模型",      "out/digit_cnn.onnx"),
    ("HUD 常规字体外部权重",   "out/digit_cnn.onnx.data"),
    ("HUD 像素字体模型",      "out/digit_cnn_yinlang999.onnx"),
    ("HUD 像素字体外部权重",   "out/digit_cnn_yinlang999.onnx.data"),
    ("ONNX/PT 等价性探针",    "out/digit_cnn.probe.npz"),
    # ⭐ 2026-10-05：像素体**也要有自己的探针** —— 原来只有常规字体那份，
    #    于是给像素体做 ONNX/.pt 检查时拿的是**别人的探针** → 必然误报"不等价"。
    ("像素字体等价性探针",     "out/digit_cnn_yinlang999.probe.npz"),
    ("行动轴模板库（共享）",   "out/axis_top_bank_E.npz"),
    ("行动轴模板库（录屏2）",  "out/axis_top_bank_E2.npz"),
    ("左侧标记模板库",        "out/axis_marker_bank_E.npz"),
    ("阿哈认脸模板库",        "out/t2_aha_bank.npz"),
    # ⭐⭐ 2026-10-05 二轮：T2 判定的数据文件。这几条以前**一条都没在清单里** ——
    #    于是"盲盒模板库没进 exe"这种漏项 preflight 抓不到（用户报过两次盲盒不记录）。
    ("阿哈认脸标签",          "out/t2_aha_labels.json"),
    ("阿哈时刻时间线",        "out/t2_aha_timeline.json"),
    ("盲盒/红兔卡面模板库",    "out/t2_card_bank.npz"),
    ("忆灵归属覆盖表",        "out/teams/owners.json"),
    ("事件表权威输入",        "out/frames_dense4.csv"),
    ("1fps 基线输入",         "out/frames_C.csv"),
    ("归属汇总基线",          "out/owner_summary_C.csv"),
    ("实机自检帧",            "out/real_frames/live_2880x1800_73431_q88.jpg"),
    ("T2 盲盒/卡面判定",      "tools/team2/card_kind_t2.py"),
    ("T2 阿哈认脸",           "tools/team2/aha_member.py"),
    ("T2 附伤展示口径",       "tools/team2/live_hook.py"),
    ("ffmpeg 解析器",         "ffmpeg_path.py"),
]

#: exe 里必须也在的东西
EXE_MUST = [
    "_internal/out/digit_cnn.onnx",
    "_internal/out/digit_cnn_yinlang999.onnx",
    "_internal/out/axis_top_bank_E.npz",
    "_internal/out/t2_aha_bank.npz",
    # ⭐ 2026-10-05 二轮：这三样缺了就是"盲盒/阿哈/忆灵归属静默失效"，必须进 exe 核对
    "_internal/out/t2_card_bank.npz",
    "_internal/out/teams/owners.json",
    "_internal/out/digit_cnn_yinlang999.probe.npz",
    "_internal/tools/team2/card_kind_t2.py",
    "_internal/tools/team2/aha_member.py",
]


def main():
    print("=" * 76)
    print("① 仓库资源")
    print("-" * 76)
    bad = []
    for name, rel in MUST:
        p = os.path.join(ROOT, rel)
        ok = os.path.exists(p)
        if not ok:
            bad.append(rel)
        sz = ""
        if ok and os.path.isfile(p):
            sz = "%8.0f KB" % (os.path.getsize(p) / 1024)
        print("   %s %-22s %s  %s" % ("✓" if ok else "✗", name, sz, rel))

    print()
    print("=" * 76)
    print("② exe 与包内资源")
    print("-" * 76)
    if not os.path.exists(EXE):
        print("   ✗ exe 不存在：%s" % EXE)
    else:
        import time
        print("   ✓ exe  %s  （%.1f MB，%s）"
              % (os.path.relpath(EXE, ROOT), os.path.getsize(EXE) / 1e6,
                 time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(EXE)))))
    for rel in EXE_MUST:
        p = os.path.join(ROOT, "dist", "HSR伤害统计", rel.replace("/", os.sep))
        ok = os.path.exists(p)
        if not ok:
            bad.append("exe:" + rel)
        print("   %s %s" % ("✓" if ok else "✗", rel))

    print()
    print("=" * 76)
    print("③ 标定文件（有旧的就要留意：框可能过期）")
    print("-" * 76)
    for rel in ("out/live_calib.json",
                os.path.join("dist", "HSR伤害统计", "out", "live_calib.json")):
        p = os.path.join(ROOT, rel)
        print("   %s %s" % ("存在（可考虑删掉重标）" if os.path.exists(p) else "无（正常）", rel))

    print()
    print("=" * 76)
    print("结论：" + ("✅ 前置就绪，可以实机" if not bad else "⚠️ 缺 %d 项：%s"
                     % (len(bad), bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
