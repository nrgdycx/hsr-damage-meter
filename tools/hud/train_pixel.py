# -*- coding: utf-8 -*-
"""
[A 线] 训练"像素方块字体"（银狼999 强普）的独立分类器。

与常规字体的区别：
  · 提取走 hud_profiles 的 `yinlang999` 档案（青绿掩膜 + 它自己的几何阈值）；
  · 数据集/权重都独立（out/digit_dataset_yinlang999.npz、out/digit_cnn_yinlang999.pt）；
  · 标签来自用户读图（digit_truth.LABELED_PIXEL）。

产出：数据集 + 集成权重 + ONNX + 留一帧交叉验证 + 逐帧/逐位明细。
"""
# [P3 整理] 原路径：train_pixel_A.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
# ⚠️ 2026-10-05 修：`from ffmpeg_path import ...` **必须放在 bootstrap 之后**。
#    `tools_bootstrap` 才会把**仓库根**插进 sys.path（见 tools/README.md §3）；
#    放在它前面时 `<仓库>/tools` 是当前插入项，而 `ffmpeg_path.py` 在仓库根 →
#    `ModuleNotFoundError: No module named 'ffmpeg_path'`（本脚本自 P3 搬家后就跑不起来）。
#    同类隐患还有十几个 tools/ 脚本，见 docs/交接_待办与最新状态.md 的"已知坏路径"。
from ffmpeg_path import require_ffmpeg as _req_ff  # noqa: E402
import json
import os
import subprocess
import sys

import numpy as np
import torch

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
sys.path.insert(0, HERE)
import hud_glyphs as HG  # noqa
import hud_profiles as HP  # noqa
from digit_truth import LABELED_PIXEL  # noqa
from train_digit_cnn import (train_one, train_ensemble, predict, GW, GH,  # noqa
                             save_ensemble, OPSET)

FFMPEG = _req_ff()   # 见 ffmpeg_path.py（可用 HSR_FFMPEG 指定）
VIDEO = "records/屏幕录制 2026-09-30 192031.mp4"
FCACHE = "frames/full3_A"
MODEL = "out/digit_cnn_yinlang999.pt"
DATASET = "out/digit_dataset_yinlang999.npz"
ONNX = "out/digit_cnn_yinlang999.onnx"


def full_frame(t):
    p = os.path.join(FCACHE, "f%08.2f.png" % t)
    if not os.path.exists(p):
        os.makedirs(FCACHE, exist_ok=True)
        subprocess.run([FFMPEG, "-ss", "%.3f" % t, "-i", VIDEO, "-frames:v", "1", "-y", p],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p if os.path.exists(p) else None


def build(verbose=True):
    from PIL import Image
    X, y, meta, rep = [], [], [], []
    for t, val in sorted(LABELED_PIXEL.items()):
        p = full_frame(t)
        if not p:
            rep.append("t=%s 抽帧失败" % t)
            continue
        a = np.asarray(Image.open(p).convert("RGB")).astype(np.int16)
        gs = HP.glyphs("yinlang999", a)
        # 安全闸：右端若有"真粘连块"被整块丢弃，剩下的字形靠右对齐贴标签会**整体错位**
        # （实测 t=133：120px 块被丢，读出的 5 段其实是左边 5 位而非最后 5 位）。
        # 判据：最右字形的右缘要贴近像素字体的固定右缘（实测 ≈2869）。
        if gs:
            right = None
            try:
                from PIL import Image as _I
                sub = a[250:360, 2400:2870]
                import hud_glyphs as _HG
                m = _HG._fill_holes(_HG.cyan_mask(sub))
                cols = np.where(m.any(axis=0))[0]
                right = 2400 + int(cols[-1]) if len(cols) else None
            except Exception:
                right = None
            missing = (2870 - right) if right is not None else 0
            if missing > 20:
                rep.append("t=%-6s %-8s 右缘缺 %dpx（右侧有被丢弃的粘连块）→ 弃用，避免标签错位"
                           % (t, val, missing))
                continue
        if len(gs) == 0 or len(gs) > len(val) or len(gs) < len(val) - 1:
            rep.append("t=%-6s %-8s 切出 %d 段 / %d 位 → 弃用" % (t, val, len(gs), len(val)))
            continue
        # ⚠️ 2026-10-05：`extract_cyan` 现在会给"拆不动的超宽粘连块"**占位**（gray=None）。
        # 占位块的位数是估计值 → 靠右对齐贴标签会**整体错位** → 这一帧整帧弃用（宁可不训）。
        if any(g[0] is None for g in gs):
            rep.append("t=%-6s %-8s 含占位块（拆不动的粘连块）→ 弃用，避免标签错位" % (t, val))
            continue
        lab = val[-len(gs):]
        for i, (v, w, h) in enumerate(gs):
            X.append(v)
            y.append(int(lab[i]))
            meta.append({"t": t, "pos": i, "digit": lab[i], "w": w, "h": h})
        rep.append("t=%-6s %-8s → 收 %d 个字%s" % (
            t, val, len(gs), "" if len(gs) == len(val) else "（缺左 %d 位）" % (len(val) - len(gs))))
    X = np.stack(X)[:, None, :, :] if X else np.zeros((0, 1, GH, GW), np.float32)
    y = np.array(y, np.int64)
    np.savez_compressed(DATASET, X=X, y=y, meta=np.array([json.dumps(m) for m in meta]))
    if verbose:
        for r in rep:
            print("   ", r)
        cnt = np.bincount(y, minlength=10) if len(y) else np.zeros(10, int)
        print("   样本 %d  标签分布 %s" % (len(y), {k: int(v) for k, v in enumerate(cnt) if v}))
        scarce = [k for k in range(10) if 0 < cnt[k] < 3]
        if scarce:
            print("   ⚠️ 样本过少的数字（<3）：%s —— 形近字最容易在这几个上翻车" % scarce)
    return X, y, meta


def main():
    print("=== 1) 构建像素字体数据集（档案 yinlang999）===")
    X, y, meta = build()
    if len(y) == 0:
        print("没有样本，退出")
        return
    frames = sorted(set(m["t"] for m in meta))

    print("\n=== 2) 留一帧交叉验证（同一帧不跨训练/测试集）===")
    tot = ok = 0
    for held in frames:
        te = np.array([i for i, m in enumerate(meta) if m["t"] == held])
        tr = np.array([i for i, m in enumerate(meta) if m["t"] != held])
        if len(tr) == 0:
            continue
        m1 = train_one(X[tr], y[tr], epochs=260, bs=64, seed=int(held))
        p = predict(m1, X[te])
        hit = int((p == y[te]).sum())
        tot += len(te)
        ok += hit
        print("   留出 t=%-7s %d/%d  %s" % (
            held, hit, len(te),
            "".join("[ok]" if a == b else "[%d->%d]" % (b, a) for a, b in zip(p, y[te]))), flush=True)
    print("   逐字准确率（留一帧）: %d/%d = %.1f%%" % (ok, tot, ok / tot * 100))

    print("\n=== 3) 训练最终集成（9 成员）并导出 ===", flush=True)
    ens = train_ensemble(X, y, n=9, epochs=400, bs=64, seed0=7)
    print("   训练集自检 %.1f%%（仅参考）" % (float((predict(ens, X) == y).mean()) * 100))
    torch.save({"members": [m.state_dict() for m in ens.members], "gw": GW, "gh": GH}, MODEL)
    print("   已保存", MODEL)
    try:
        torch.onnx.export(ens, torch.zeros(1, 1, GH, GW), ONNX, input_names=["img"],
                          output_names=["logits"],
                          dynamic_axes={"img": {0: "n"}, "logits": {0: "n"}}, opset_version=OPSET)
        print("   已导出", ONNX)
    except Exception as e:
        print("   ONNX 导出失败:", repr(e)[:120])

    print("\n=== 4) 逐帧读数复核（用刚训好的集成）===")
    from PIL import Image
    good = 0
    for t, val in sorted(LABELED_PIXEL.items()):
        p = full_frame(t)
        a = np.asarray(Image.open(p).convert("RGB")).astype(np.int16)
        gs = HP.glyphs("yinlang999", a)
        if not gs:
            print("   t=%-7s 切不出字形" % t)
            continue
        if any(g[0] is None for g in gs):
            print("   t=%-7s 含占位块（拆不动的粘连块）→ 这一帧不判（应是待复核）" % t)
            continue
        x = torch.tensor(np.stack([v for v, _, _ in gs])[:, None], dtype=torch.float32)
        with torch.no_grad():
            pr = ens(x).argmax(1).numpy()
        read = "".join(str(int(d)) for d in pr)
        okk = read == val
        good += okk
        print("   t=%-7s 期望 %-8s 读出 %-8s %s  段数 %d" % (t, val, read, "✓" if okk else "✗", len(gs)))
    print("   整串正确 %d/%d" % (good, len(LABELED_PIXEL)))


if __name__ == "__main__":
    main()
