# -*- coding: utf-8 -*-
"""B 线：实时读取循环（"边打边读"的最小可用形态）。

    python live_B.py --seconds 20              # 实时打印 HUD 读数 + 每段耗时
    python live_B.py --seconds 20 --dump-axis samples/axis_live   # 顺手把行动轴裁图落盘给 E 线用

给出的是**接口**，不是最终统计：
  * `LiveHud.poll()` -> 抓一帧 HUD 并读数（抓屏 8ms + 推理 0.2ms 量级）；
  * `LiveHud.read_stream(hz)` -> 生成器，其他线（C 线事件切分 / 归属）直接消费；
  * 本脚本只把"连续相同的读数"合成一段打印出来，**不做归属**（归属是 C 线的事）。

性能设计（实测依据）：
  * 抓 HUD 526x80 约 8.3ms（BitBlt 本身有 ~7~8ms 固定开销，与区域大小关系不大）；
  * 抓行动轴 280x1250 约 13~17ms —— 行动轴变化慢，**没必要每帧抓**，
    默认每 5 帧抓一次（--axis-every），摊薄到每帧 ~3ms。
"""
from __future__ import annotations
# [P3 整理] 原路径：live_B.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import argparse
import os
import sys
import time

import numpy as np

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "vendor"))
os.chdir(HERE)


class LiveHud:
    def __init__(self, axis_every=5, dump_axis=None):
        from capture import AXIS_REGION, HUD_REGION, Grabber
        from hud_digits import HudOnnxReader

        self.g = Grabber()
        self.reader = HudOnnxReader()
        self.HUD_REGION, self.AXIS_REGION = HUD_REGION, AXIS_REGION
        self.axis_every = max(1, axis_every)
        self.dump_axis = dump_axis
        self.n = 0
        self.axis_paths = []
        if dump_axis:
            os.makedirs(dump_axis, exist_ok=True)

    def close(self):
        self.g.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def poll(self):
        """抓一帧 + 读数。返回 dict（含耗时与本次行动轴裁图路径，若有）。"""
        t0 = time.perf_counter()
        hud = self.g.grab_rgb(self.HUD_REGION)
        t1 = time.perf_counter()
        text, conf, res = self.reader.read_region(hud, top=self.HUD_REGION["top"])
        t2 = time.perf_counter()
        axis_png = None
        if self.n % self.axis_every == 0:
            from PIL import Image

            axis = self.g.grab_rgb(self.AXIS_REGION)
            if self.dump_axis:
                axis_png = os.path.join(self.dump_axis, "axis_%06d.png" % self.n)
                Image.fromarray(axis).save(axis_png)
                self.axis_paths.append(axis_png)
        t3 = time.perf_counter()
        self.n += 1
        return {"t": t3, "text": text, "conf": conf, "n_glyph": len(res),
                "grab_ms": (t1 - t0) * 1000, "read_ms": (t2 - t1) * 1000,
                "axis_ms": (t3 - t2) * 1000, "axis_png": axis_png}

    def read_stream(self, hz=None):
        """生成器：按 hz 节奏不断 yield poll() 的结果（hz=None 表示全速）。"""
        while True:
            r = self.poll()
            yield r
            if hz:
                nxt = r["t"] + 1.0 / hz
                dt = nxt - time.perf_counter()
                if dt > 0:
                    time.sleep(dt)


def main(argv=None):
    ap = argparse.ArgumentParser(description="B 线实时读取演示")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--hz", type=float, default=0.0, help="轮询频率上限（0=全速）")
    ap.add_argument("--axis-every", type=int, default=5, help="每 N 帧抓一次行动轴")
    ap.add_argument("--dump-axis", default=None, help="把行动轴裁图存到这个目录（给 E 线）")
    a = ap.parse_args(argv)

    print("实时读取 %g 秒（Ctrl+C 可提前结束）…" % a.seconds)
    t_start = time.perf_counter()
    t_end = t_start + a.seconds
    seg = {"text": None, "t0": 0.0, "n": 0, "conf": 1.0, "ms": []}
    ms = {"grab": [], "read": [], "e2e": [], "axis": []}

    def flush():
        if seg["text"]:
            print("   %6.2fs  读数 %-14s 最低置信 %.2f  %d 帧  (段内平均 %.1fms/帧)"
                  % (seg["t0"] - t_start, seg["text"], seg["conf"], seg["n"],
                     float(np.mean(seg["ms"])) if seg["ms"] else 0.0))

    try:
        with LiveHud(axis_every=a.axis_every, dump_axis=a.dump_axis) as lh:
            for r in lh.read_stream(a.hz or None):
                e2e = r["grab_ms"] + r["read_ms"]
                ms["grab"].append(r["grab_ms"])
                ms["read"].append(r["read_ms"])
                ms["e2e"].append(e2e)
                if r["axis_ms"]:
                    ms["axis"].append(r["axis_ms"])
                # 把连续相同的读数合成一段（"值稳定窗口"）
                if r["text"] and r["text"] == seg["text"]:
                    seg["n"] += 1
                    seg["conf"] = min(seg["conf"], r["conf"])
                    seg["ms"].append(e2e)
                else:
                    flush()
                    seg = {"text": r["text"] or None, "t0": r["t"], "n": 1 if r["text"] else 0,
                           "conf": r["conf"], "ms": [e2e] if r["text"] else []}
                if time.perf_counter() >= t_end:
                    break
            flush()
    except KeyboardInterrupt:
        print("\n已中断。")
    n = max(1, len(ms["e2e"]))
    print("\n共 %d 帧：" % n)
    for k, label in (("grab", "抓 HUD"), ("read", "掩膜+分割+ONNX"), ("e2e", "抓屏+推理"),
                     ("axis", "抓行动轴")):
        if ms[k]:
            arr = np.asarray(ms[k])
            print("   %-16s 平均 %6.2fms  p95 %6.2fms  最大 %6.2fms" % (label, arr.mean(), np.percentile(arr, 95), arr.max()))
    if a.dump_axis:
        print("   行动轴裁图 %d 张 -> %s" % (len(os.listdir(a.dump_axis)), a.dump_axis))
    return 0


if __name__ == "__main__":
    sys.exit(main())
