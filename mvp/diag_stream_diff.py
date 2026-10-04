# -*- coding: utf-8 -*-
"""临时诊断：流式 vs 批处理，逐事件并排看差异（对齐用 = events_v4.build）。用完可删。"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import events_v4 as E4                     # noqa: E402
from mvp.engine import LiveEngine               # noqa: E402

LIVE = "out/mvp_frames_live.csv"
if len(sys.argv) > 1:                       # P1：也支持实机采集落下来的逐帧表
    LIVE = sys.argv[1]
KEYS = ("t_first", "t_last", "t_peak", "t_anchor", "damage_max", "unit", "owner",
        "status", "quality", "n_trusted", "n_rejected", "issues")


def main():
    read = E4.classify(E4.load(LIVE))
    E4.mark_rejects(read, reset_ratio=0.20)
    runs = E4.segment(read, gap=1.5, reset_ratio=0.20, actor_split=True,
                      plateau_break=3, absent_break=0.6)
    E4.expand_span(read, runs)
    batch = []
    for run in runs:
        ev = E4.attribute4(read, run, back=1.5, fwd=0.5)
        if ev:
            batch.append(ev)

    eng = LiveEngine()
    fired = []
    for row in read:
        for e in eng.add(row):
            fired.append((row["t"], dict(e)))
    for e in eng.flush():
        fired.append((read[-1]["t"], dict(e)))
    stream = [e for _, e in fired]

    print("流式 %d ｜ 批处理 %d ｜ 保险丝触发 %d 次" % (len(stream), len(batch),
                                                eng.n_stale_merge))
    print("\n%-3s %-16s %-16s %12s %-6s %-8s %-6s  %s"
          % ("#", "流式 t_first~t_last", "批 t_first~t_last", "damage", "owner", "status",
             "定稿now", "差异字段"))
    for i in range(max(len(stream), len(batch))):
        a = stream[i] if i < len(stream) else None
        b = batch[i] if i < len(batch) else None
        if a is None or b is None:
            print("%-3d %-16s %-16s %s" % (i + 1, "-" if a is None else "有",
                                           "-" if b is None else "有", "缺事件"))
            continue
        bad = [k for k in KEYS
               if (str(a.get(k, "")) != str(b.get(k, "")))]
        print("%-3d %-16s %-16s %12s %-6s %-8s %-6s  %s"
              % (i + 1, "%s~%s" % (a["t_first"], a["t_last"]),
                 "%s~%s" % (b["t_first"], b["t_last"]), a["damage_max"],
                 a["owner"] or "-", a["status"], fired[i][0],
                 ",".join("%s(流=%s 批=%s)" % (k, a.get(k), b.get(k)) for k in bad)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
