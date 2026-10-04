# -*- coding: utf-8 -*-
"""临时诊断：某一时间窗内，流式引擎冻住的 reject vs 批处理的 reject。用完可删。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import events_v4 as E4                     # noqa: E402
from mvp.engine import LiveEngine               # noqa: E402

LIVE = "out/mvp_frames_live.csv"
LO, HI = 254.0, 266.0


def main():
    # 批处理
    batch = E4.classify(E4.load(LIVE))
    E4.mark_rejects(batch, reset_ratio=0.20)

    # 流式
    stream = E4.classify(E4.load(LIVE))
    eng = LiveEngine()
    for row in stream:
        eng.add(row)
    for e in eng.flush():
        pass

    print("%-8s %-10s %-8s %-40s %-40s" % ("t", "text", "grade", "批 reject", "流 reject"))
    for b, s in zip(batch, stream):
        if not (LO <= b["t"] <= HI):
            continue
        mark = "  ←不一致" if b["reject"] != s["reject"] else ""
        print("%-8s %-10s %-8s %-40s %-40s%s"
              % (b["t"], b["text"] or "(空)", b["grade"], b["reject"] or "-",
                 s["reject"] or "-", mark))
    return 0


if __name__ == "__main__":
    sys.exit(main())
