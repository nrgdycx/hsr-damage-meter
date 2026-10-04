# -*- coding: utf-8 -*-
"""
P1 离线回归：**实机帧上"选哪一对 (框, bar_rows)"决定读得对不对**。

为什么要有这个脚本
------------------
用户实测"数字动都不动一下，一直是待复核"，根因就是**框与金线行带不成对**：
`docs/行动轴识别.md` §2/§3 曾下结论"墨迹自适应绝不能平移 bar_rows、
要用模型的 bar"—— 那条结论在**全分辨率实机帧**上是**错的**（它当时依据的墨迹框
本身就取错了列，见下）。本脚本把四种组合逐条测出来，作为 P1 的回归证据。

实测（`samples/M_full_now.png`，2880×1800，屏幕上真值 `73431`；用户当时报的数），
下面是**走实时路径（含几何守门）**的读数：

    组合                                       结果
    ─────────────────────────────────────────  ──────────────────────
    墨迹框 (285,2353,365,2880) + 墨迹 bar       `73431`  可信  ✅
      (323,335)（线7 定位给的那一对，**成对**）
    墨迹框 + 模型 bar (298,310)                 `??343`  nbad=2  ❌
    模型框 (260,2353,340,2880) + 模型 bar       `?????`  nbad=5  ❌
    模型框 + 墨迹 bar                           `?????`  nbad=5  ❌

**结论**：框与 bar_rows 必须**同源成对**，只有"两样都来自画面证据"的那一对读得对；
本机实机画面比录屏低约 25px，所以进战前启动时（画面还没数字 → 没有墨迹 → 退回模型
那一对）会读出 `?????`。

`?????` 是**非空**的 —— 这就是"永不重定位"的机关：
`ScreenSource.note_hud_result` 旧写法只看"文本非空"，于是以为读到了。
P1 的修法见 `mvp/reader.read_is_reliable`（非空 **且** 无 `?` **且** nbad=0），
本脚本同时断言"这条修法判据在这一帧上确实一个真一个假"。

素材
----
* 首选 `samples/M_full_now.png`（全分辨率原图，8MB，**不进 git**：samples/ 已 ignore）；
* 否则用 `out/real_frames/live_2880x1800_73431_q88.jpg`（**入库**的 JPEG q=88 副本，
  逐条复验过读数与 PNG 完全一致）。
* 两个都不在 → 打印"跳过"并返回 0（别人 clone 下来没素材时不算失败）。

复现：`python tools/overlay/live_box_check.py`（退出码 0 = 通过）
"""
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import os
import sys

import numpy as np

TRUTH = "73431"                    # 屏幕上当时的数字（用户核对过，见 docs/剩余工作清单.md）
CANDIDATES = ("samples/M_full_now.png",
              "out/real_frames/live_2880x1800_73431_q88.jpg")


def _load():
    for p in CANDIDATES:
        if os.path.exists(p):
            from PIL import Image
            return p, np.asarray(Image.open(p).convert("RGB"))
    return None, None


def main():
    import geometry as SA
    from mvp.reader import Perceiver, hud_region_for, read_is_reliable

    path, frame = _load()
    if frame is None:
        print("跳过：找不到实机帧素材（%s）。" % " 或 ".join(CANDIDATES))
        print("  说明：samples/ 不进 git；入库副本见 out/real_frames/。")
        return 0
    if frame.shape[:2] != (1800, 2880):
        print("跳过：%s 不是全分辨率实机帧（%s）—— 缩放过的图不能用来判定框。"
              % (path, frame.shape[:2]))
        return 0

    print("素材：%s  %dx%d" % (path, frame.shape[1], frame.shape[0]))
    # span_guard=True = 实机那条路径（真值帧必须能过这道闸：它的 段宽/墨迹跨度 ≈ 0.41）
    P = Perceiver(backend="onnx", span_guard=True)

    def read_box(box, bar, tag):
        y0, x0, y1, x1 = (int(v) for v in box)
        crop = np.ascontiguousarray(frame[y0:y1, x0:x1], dtype=np.int16)
        row = P.read(0.0, region_rgb=crop, top=y0, left=x0, bar_rows=tuple(int(v) for v in bar),
                     read_axis=False)
        ok = read_is_reliable(row)
        print("  %-30s box=%-24s bar=%-12s → %-8r n=%d nbad=%d 可信=%s"
              % (tag, str(tuple(int(v) for v in box)), str(tuple(int(v) for v in bar)),
                 row["text"], row["n"], row["nbad"], "是" if ok else "否"))
        return row, ok

    print("\n=== ① 实时路径（画面有数字 → 线7 墨迹定位；框与 bar 必须同源）===")
    reg, bar, geom = hud_region_for(frame.shape, use_ink=True, frame_rgb=frame)
    box_live = (reg["top"], reg["left"], reg["top"] + reg["height"], reg["left"] + reg["width"])
    row_live = P.read(0.0, region_rgb=np.ascontiguousarray(
        frame[box_live[0]:box_live[2], box_live[1]:box_live[3]], dtype=np.int16),
        top=box_live[0], left=box_live[1], bar_rows=bar, read_axis=False)
    ok_live = read_is_reliable(row_live)
    print("  hud_region_for → src=%s box=%s bar=%s" % (geom.get("src"), box_live, bar))
    print("  读数 %r n=%d nbad=%d 可信=%s" % (row_live["text"], row_live["n"],
                                            row_live["nbad"], "是" if ok_live else "否"))

    print("\n=== ② 反面对照：框与 bar 不成对 / 退回模型那一对 ===")
    g_model = SA.hud_geometry(shape=(frame.shape[0], frame.shape[1]))
    box_m, bar_m = tuple(int(v) for v in g_model["box"]), tuple(int(v) for v in g_model["bar_rows"])
    row_inkbox_modelbar, ok_im = read_box(box_live, bar_m, "墨迹框 + 模型 bar（错配）")
    row_modelpair, ok_mm = read_box(box_m, bar_m, "模型框 + 模型 bar（回退）")
    read_box(box_m, bar, "模型框 + 墨迹 bar（错配）")

    print("\n=== 断言 ===")
    bad = []
    if not (ok_live and row_live["text"] == TRUTH):
        bad.append("实时路径应当读出真值 %r，实得 %r（可信=%s）" % (TRUTH, row_live["text"], ok_live))
    if tuple(int(v) for v in box_live) != tuple(int(v) for v in geom["box"]) or \
            tuple(int(v) for v in bar) != tuple(int(v) for v in geom["bar_rows"]):
        bad.append("框与 bar_rows 必须同源：hud_region_for 返回的与 hud_geometry 的不一致")
    if ok_mm:
        bad.append("模型那一对在实机帧上不该被当成可信读数（它正是「永不重定位」的机关）")
    if not row_modelpair["text"]:
        bad.append("模型那一对预期给出非空的占位串（`?????`），实得空 —— 断言前提变了，请复核")
    if ok_im or row_inkbox_modelbar["text"] == TRUTH:
        bad.append("错配（墨迹框 + 模型 bar）不该读出真值 %r" % TRUTH)

    for b in bad:
        print("  ✗ %s" % b)
    if bad:
        print("\nlive_box_check **未通过**（%d 条）" % len(bad))
        return 1
    print("  ✓ 实时路径（成对）读出真值 %r，可信=是" % TRUTH)
    print("  ✓ 框与 bar_rows 同源")
    print("  ✓ 模型那一对给出非空但**不可信**的 %r → `read_is_reliable` 判否 → 会触发重定位"
          % row_modelpair["text"])
    print("  ✓ 错配（墨迹框 + 模型 bar）读不出真值 %r" % TRUTH)
    print("\nlive_box_check 通过：框与金线行带必须同源成对（详见文件头）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
