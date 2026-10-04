# -*- coding: utf-8 -*-
"""临时诊断：跟踪流式引擎在 t=255~260 的每一次重算看到了什么。用完可删。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import events_v4 as E4                     # noqa: E402
from mvp.engine import LiveEngine               # noqa: E402

LIVE = "out/mvp_frames_live.csv"
LO, HI = 255.0, 259.0


def main():
    rows = E4.classify(E4.load(LIVE))
    eng = LiveEngine()

    def trace(now, runs, new_events):
        if not (LO <= now <= HI):
            return
        print("── pass now=%-6s  work t=[%s..%s]  %d 段" %
              (now, eng.work[0]["t"] if eng.work else "-",
               eng.work[-1]["t"] if eng.work else "-", len(runs)))
        for i, r in enumerate(runs):
            vals = [E4.value(x) for x in r["rows"]]
            print("     run%d %-9s~%-9s 可信%2d  max=%-9s issues=%s%s"
                  % (i, r["start"], r["end"], len(r["rows"]),
                     max(v for v in vals if v is not None) if any(v is not None for v in vals) else "-",
                     r.get("issues"), "  ←本次定稿" if any(e is not None and
                                                          e.get("t_first") is not None and
                                                          abs(e["t_first"] - r["start"]) < 1e-9
                                                          for e in new_events) else ""))
        if new_events:
            print("     ★ 定稿 %d 个：%s" % (len(new_events),
                                          [(e["event"], e["t_first"], e["t_last"],
                                            e["damage_max"], e["owner"]) for e in new_events]))

    eng.trace = trace
    for row in rows:
        eng.add(row)
    eng.trace = None
    for e in eng.flush():
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
