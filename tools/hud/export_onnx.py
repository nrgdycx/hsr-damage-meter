# -*- coding: utf-8 -*-
"""B 线：把 `out/digit_cnn.pt` 重新导出成实时推理用的 `out/digit_cnn.onnx`。

**为什么需要这个脚本（本会话发现的真实缺陷）**：
    out/digit_cnn.onnx   2026-09-30 10:50:25
    out/digit_cnn.pt     2026-09-30 11:11:59   ← 比 ONNX 晚 21 分钟
  ONNX 是**旧的**：用同一批字形分别喂两个模型，logits 明显不同（有的字位置
  甚至直接给出不同数字，如 t=105 的 4↔6、0↔9），而 torch 端在那几个字形上
  本来就是 0.52/0.48 这种近似平票 —— 拿旧 ONNX 做实时推理，等于在用另一个模型。

  `read_hud.py`（离线）用 .pt，实时用 .onnx ⇒ 两边必须是同一次训练的产物。

用法：
    python export_onnx_B.py            # 导出 + 自校验（对全部缓存帧字形比对 torch/onnx）
    python export_onnx_B.py --check    # 只自校验，不导出
"""
from __future__ import annotations
# [P3 整理] 原路径：export_onnx_B.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import argparse
import glob
import hashlib
import json
import os
import sys
import time

import numpy as np

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
os.chdir(HERE)
sys.path.insert(0, HERE)

MODEL_PT = "out/digit_cnn.pt"
MODEL_ONNX = "out/digit_cnn.onnx"
META = "out/digit_cnn.onnx.meta.json"
CACHE = os.path.join(HERE, "frames", "glyphcache")
# A 线改为交付**集成**模型后，opset 17 会触发 onnxscript 的版本回退并报
# AssertionError（axes_input_to_attribute），18 原生支持，实测与 torch 端 argmax 全一致。
OPSET = 18


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def build_models():
    from train_digit_cnn import load_any_pt

    m = load_any_pt(MODEL_PT)
    from hud_digits import HudOnnxReader

    return m, HudOnnxReader()


def do_export():
    import torch
    from train_digit_cnn import GH, GW, load_any_pt

    m = load_any_pt(MODEL_PT)
    for p in (MODEL_ONNX, MODEL_ONNX + ".data"):
        if os.path.exists(p):
            os.remove(p)
    try:
        torch.onnx.export(m, torch.zeros(1, 1, GH, GW), MODEL_ONNX,
                          input_names=["img"], output_names=["logits"],
                          dynamic_axes={"img": {0: "n"}, "logits": {0: "n"}}, opset_version=OPSET)
    except Exception as e:
        print("新版导出器失败（%s），改试 dynamo=False" % repr(e)[:100])
        torch.onnx.export(m, torch.zeros(1, 1, GH, GW), MODEL_ONNX,
                          input_names=["img"], output_names=["logits"],
                          dynamic_axes={"img": {0: "n"}, "logits": {0: "n"}},
                          opset_version=OPSET, dynamo=False)
    write_meta()
    print("已导出 %s（%.1f KB）+ %s" % (MODEL_ONNX, os.path.getsize(MODEL_ONNX) / 1024, META))


def compare_all(frames=0, verbose=True):
    """对全部缓存帧的字形，比对 torch 与 onnx 的 argmax 是否一致。"""
    import torch
    from PIL import Image
    from hud_digits import CY0, CY1, CX0, CX1, extract_glyphs

    tm, reader = build_models()
    fs = sorted(glob.glob(os.path.join(CACHE, "f*.png")))
    if frames:
        fs = fs[:frames]
    tot = same = 0
    nframe_bad = 0
    worst = 0.0
    for p in fs:
        a = np.asarray(Image.open(p).convert("RGB"))
        gl = extract_glyphs(a[CY0:CY1, CX0:CX1])
        if not gl:
            continue
        x = np.stack([g[0] for g in gl])[:, None].astype(np.float32)
        with torch.no_grad():
            tp = torch.softmax(tm(torch.tensor(x)), 1).numpy()
        logits = reader.sess.run(None, {reader.input: x})[0]
        e = np.exp(logits - logits.max(1, keepdims=True))
        op = e / e.sum(1, keepdims=True)
        bad = int((tp.argmax(1) != op.argmax(1)).sum())
        nframe_bad += bad > 0
        same += len(gl) - bad
        tot += len(gl)
        worst = max(worst, float(np.abs(tp - op).max()))
    print("torch vs onnx：argmax 一致 %d/%d 个字形（%d 帧里有 %d 帧存在不一致；最大概率差 %.4f）"
          % (same, tot, len(fs), nframe_bad, worst))
    return same, tot, worst


def write_meta(note="由 export_onnx_B.py 导出"):
    meta = {"pt_sha256": sha256(MODEL_PT),
            "pt_mtime": os.path.getmtime(MODEL_PT),
            "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": note}
    with open(META, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


def make_probe(max_glyphs=16):
    """
    生成探针：从缓存帧里取若干**真实字形**，记录它们在本 .pt 下的 logits。

    有了它，`hud_digits.check_model_freshness` 就能只加载 ONNX（不 import torch）
    判断"这份 ONNX 跟 .pt 是不是同一个模型"——因为实测发现**换个导出方式**
    （opset/dynamo/外部权重）就能造出权重同源但 argmax 不一致的 ONNX。
    """
    import torch
    from PIL import Image
    from hud_digits import CY0, CY1, CX0, CX1, PROBE, extract_glyphs
    from train_digit_cnn import load_any_pt

    tm = load_any_pt(MODEL_PT)

    fs = sorted(glob.glob(os.path.join(CACHE, "f*.png")))
    step = max(1, len(fs) // 40)
    picked, digits_seen = [], set()
    for p in fs[::step]:
        a = np.asarray(Image.open(p).convert("RGB"))
        for v, w, h in extract_glyphs(a[CY0:CY1, CX0:CX1]):
            picked.append(v)
        if len(picked) >= max_glyphs:
            break
    X = np.stack(picked[:max_glyphs])[:, None].astype(np.float32)
    with torch.no_grad():
        Y = tm(torch.tensor(X)).numpy().astype(np.float32)
    np.savez_compressed(PROBE, X=X, Y=Y, pt_sha256=sha256(MODEL_PT))
    digits_seen = sorted(set(int(i) for i in Y.argmax(1)))
    print("已生成探针 %s（%d 个真实字形，覆盖数字 %s）" % (PROBE, len(X), digits_seen))
    return PROBE


def stale_info():
    """用探针（不 import torch）判断当前 ONNX 与 .pt 是否等价。"""
    import onnxruntime as ort

    from hud_digits import check_model_freshness

    if not os.path.exists(MODEL_ONNX):
        return check_model_freshness(MODEL_ONNX)
    so = ort.SessionOptions()
    so.intra_op_num_threads = 1
    so.inter_op_num_threads = 1
    sess = ort.InferenceSession(MODEL_ONNX, so, providers=["CPUExecutionProvider"])
    return check_model_freshness(MODEL_ONNX, sess=sess)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="只自校验不导出；若 argmax 全一致则顺手更新哈希记录（.onnx 不动）")
    ap.add_argument("--frames", type=int, default=0, help="自校验只用前 N 帧（0=全部）")
    a = ap.parse_args(argv)

    if not a.check:
        print("导出前：.pt 时间 %s" % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(MODEL_PT))))
        if os.path.exists(MODEL_ONNX):
            print("        .onnx 时间 %s" % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(MODEL_ONNX))))
        print("── 导出前的 torch/onnx 一致性 ──")
        compare_all(a.frames)
        do_export()
        print("── 导出后的一致性 ──")
        compare_all(a.frames)
        make_probe()
        print("ONNX 与 .pt 同源:", stale_info())
    else:
        if os.path.exists(MODEL_ONNX):
            print("现有 .onnx 时间 %s（请勿同时重训，否则结论只对当下这份权重有效）"
                  % time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(MODEL_ONNX))))
        print("── torch(.pt) vs onnx 一致性 ──")
        same, tot, worst = compare_all(a.frames)
        if tot and same == tot:
            write_meta("由 export_onnx_B.py --check 验证 argmax 全一致后记录（.onnx 本身是 train_digit_cnn.py 导出的）")
            make_probe()
            print("argmax 全一致 -> 已更新哈希记录与探针")
        else:
            print("存在不一致（%d/%d 一致，最大概率差 %.3f）-> **不要**只更新记录，"
                  "请跑 `python export_onnx_B.py` 重新导出。" % (same, tot, worst))
        print("ONNX 与 .pt 同源:", stale_info())
    return 0


if __name__ == "__main__":
    sys.exit(main())
