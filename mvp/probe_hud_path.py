# -*- coding: utf-8 -*-
"""[MVP 前置探针] 实时 HUD 读数路径 vs 离线扫描路径，逐帧比读数。

为什么要有这个探针（不许跳过）：
  离线表 `out/frames_dense4.csv` 是 `scan_C2.py` 用 **torch + 每帧动态定位**
  （`read_hud.read_array` → `hud_profiles.glyphs` → `geometry.hud_box_for_frame`）扫出来的；
  实时链路用的是 **ONNX + 开机标定一次的固定框**（`hud_digits.HudOnnxReader`）。
  两者**不是同一条代码路径**。MVP 的验收第 3 条要求"实时汇总 == 离线汇总"，
  所以必须先量清楚这两条路径在真实帧上到底差多少，再决定实时侧用哪条路。

本探针只做测量、不改任何东西。输出每个变体的差异计数与样例。

用法：
  python mvp/probe_hud_path.py            # 全部 923 帧
  python mvp/probe_hud_path.py --limit 120
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vendor"))
os.chdir(ROOT)

import hud_glyphs as HG          # noqa: E402
import hud_profiles as HP        # noqa: E402
import read_hud                  # noqa: E402
from hud_digits import HudOnnxReader  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default="out/frames_dense4.csv")
    ap.add_argument("--dir", default="frames/glyphcache")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    rows = list(csv.DictReader(open(a.frames, encoding="utf-8-sig")))
    if a.limit:
        rows = rows[:a.limit]
    model = read_hud.load_model()
    onnx = HudOnnxReader()
    import torch

    def torch_read(gs, conf_min=0.55):
        if not gs:
            return "", 0.0, 0
        x = torch.tensor(np.stack([v for v, _, _ in gs])[:, None], dtype=torch.float32)
        with torch.no_grad():
            pr = torch.softmax(model(x), 1)
        cf, pd = pr.max(1)
        chars = []
        for (v, w, h), d, c in zip(gs, pd.tolist(), cf.tolist()):
            ok, _ = HP.geom_ok("default", w, h)
            chars.append(str(int(d)) if (ok and c >= conf_min) else "?")
        return "".join(chars), float(min(cf.tolist())), len(gs)

    def onnx_read(gs, conf_min=0.55):
        res = onnx.classify(gs)
        chars, mins = [], 1.0
        for (v, w, h), (d, c) in zip(gs, res):
            ok, _ = HP.geom_ok("default", w, h)
            chars.append(str(d) if (ok and c >= conf_min) else "?")
            mins = min(mins, c)
        return "".join(chars), (mins if res else 0.0), len(gs)

    stats = {k: {"n": 0, "diff": 0, "samples": []} for k in
             ("torch_dyn", "torch_fixed", "onnx_dyn", "onnx_fixed")}
    t_dyn = []
    t0 = time.time()
    for i, r in enumerate(rows):
        t = float(r["t"])
        p = os.path.join(a.dir, "f%08.2f.png" % t)
        if not os.path.exists(p):
            continue
        arr = np.asarray(Image.open(p).convert("RGB")).astype(np.int16)
        off = (r["hud_text"] or "").strip()

        # 动态定位的框 + 金线行带（离线路径用的那一组）
        ts = time.perf_counter()
        box, bar = HP.box_for("default", arr)
        t_dyn.append((time.perf_counter() - ts) * 1000)
        y0, x0, y1, x1 = box
        dyn_region = np.asarray(arr[y0:y1, x0:x1], dtype=np.int16)
        gs_dyn = HP.glyphs_cropped("default", dyn_region, y0, x0, bar_rows=bar)
        # 固定框（实时路径用的那一组：hud_digits.REGION_HUD / BAR_ROWS）
        fx_region = np.asarray(arr[HG.CY0:HG.CY1, HG.CX0:HG.CX1], dtype=np.int16)
        gs_fx = HP.glyphs_cropped("default", fx_region, HG.CY0, HG.CX0, bar_rows=HG.BAR_ROWS)

        got = {
            "torch_dyn": torch_read(gs_dyn)[0],
            "torch_fixed": torch_read(gs_fx)[0],
            "onnx_dyn": onnx_read(gs_dyn)[0],
            "onnx_fixed": onnx_read(gs_fx)[0],
        }
        for k, v in got.items():
            s = stats[k]
            s["n"] += 1
            if v != off:
                s["diff"] += 1
                if len(s["samples"]) < 12:
                    s["samples"].append((t, off, v, tuple(box), tuple(bar or ())))
        for k in ("torch_dyn", "onnx_dyn"):
            if got[k] != off and len(stats[k]["samples"]) < 12:
                pass
        if (i + 1) % 100 == 0:
            print("  %d/%d  %.0fs" % (i + 1, len(rows), time.time() - t0), flush=True)

    print("\n=== 逐帧读数 vs 离线表（%d 帧）===" % stats["torch_dyn"]["n"])
    for k in ("torch_dyn", "onnx_dyn", "torch_fixed", "onnx_fixed"):
        s = stats[k]
        print("  %-12s 不同 %3d / %3d" % (k, s["diff"], s["n"]))
    for k in ("onnx_dyn", "torch_fixed", "onnx_fixed"):
        s = stats[k]
        if s["samples"]:
            print("\n  [%s] 差异样例：" % k)
            for t, off, v, box, bar in s["samples"]:
                print("    t=%-8s 离线=%-10s 本径=%-10s box=%s bar=%s"
                      % (("%.2f" % t).rstrip("0").rstrip("."), off or "(空)", v or "(空)", box, bar))
    dt = np.asarray(t_dyn)
    print("\n动态定位单帧耗时：平均 %.2fms 中位 %.2fms p95 %.2fms 最大 %.2fms"
          % (dt.mean(), np.percentile(dt, 50), np.percentile(dt, 95), dt.max()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
