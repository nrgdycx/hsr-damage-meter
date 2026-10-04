# -*- coding: utf-8 -*-
"""T1：开大（插入终结技）演出窗口的归属兜底 —— **自检 + 前后对比**。

机制（用户 2026-10-03 确认原话：「三个人都是插入终结技然后终结技演出显示伤害」；
      2026-10-04 补充纠正：「316-320 是大招，**拓星者是姬子的助战技、不是大招**」）：
    **插入行动** → 左上角出现**四角星**标记的本人卡
    → 该次行动的演出把**整条行动轴从画面消失**，但右上角总伤害**照常跳数**
    → 演出结束行动轴回来。
⚠️ 四角星 = **插入行动**（大招 / **助战技** / 额外回合 / 立即行动），**不限于大招**。
所以"这段演出是谁的"由**紧邻演出的那张四角星卡**给出，不需要识别大招立绘。

规则实现只有一个地方：`events.find_actor_ult`
（由 `events_v4.attribute4` 在 `find_actor` 返回 None 时调用；
 实时链路 `mvp/engine.py` 走同一个函数，所以离线和实时口径天然一致）。

本脚本只做两件事：
  * `--selftest`   用**合成数据**把规则的 6 条边界钉死（含 3 条否决闸）；
  * `--compare`    在真实帧表上量"修法前 vs 修法后"：事件归属差异 + 覆盖率。

用法：
  python -u tools/events/t1_ult_window.py --selftest
  python -u tools/events/t1_ult_window.py --compare out/frames_dense4.csv
  python -u tools/events/t1_ult_window.py --compare out/t1_feixiao.csv
"""
# [P3 整理] 与 tools/ 下其他脚本同一套 bootstrap：让脚本在 tools/ 里也能找到仓库根
import os as _os, sys as _sys  # noqa: E401
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import argparse
import sys

import events_v4 as E4
import events as C


def R(t, unit="", owner="", marker="", card_type="unit"):
    """合成一帧读数。字段与 `out/frames_dense4.csv` 载入后的一致。"""
    return {"t": float(t), "unit": unit, "owner": owner, "marker": marker,
            "card_type": card_type, "score": 1.0, "margin": 1.0, "inserted": "",
            "text": "123", "n": 3, "conf": 1.0, "grade": "raw", "reject": ""}


def _gap(t0, t1, step=0.2, **kw):
    """造一段"轴被演出抹掉"的帧（`marker=empty`，`card_type=empty`）。

    ⚠️ `span_axis_gone` 判的是 **marker**，不是 card_type —— 两者都要给，
    否则测试数据自己就不满足"轴消失"的前提（第一版漏了 marker，自检当场报错）。
    """
    kw.setdefault("marker", "empty")
    kw.setdefault("card_type", "empty")
    out, t = [], t0
    while t <= t1 + 1e-9:
        out.append(R(t, **kw))
        t += step
    return out


# ────────────────────────── 自检：6 条边界 ──────────────────────────
CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


@case("① 星标在窗口**之前** → 采纳（飞霄型，实测 rec1640 t=379.4~385.4）")
def _c1():
    rd = ([R(377.0, "飞霄", "飞霄", "ally_star")]
          + _gap(377.6, 380.0, card_type="empty")
          + _gap(380.2, 385.4, 0.4, card_type="empty")
          + [R(386.0, "那刻夏", "那刻夏", "ally_dot")])
    row, dt, src = C.find_actor_ult(rd, 385.0)
    assert row and row["unit"] == "飞霄" and src == "ult_S", (row, src)
    return "→ 飞霄 / ult_S（借到 t=377.0，Δ=%.1fs）" % dt


@case("② 星标在窗口**之后** → 不采纳（反例：录屏1 #31，那其实是前一个人的动作）")
def _c2():
    rd = ([R(260.0, "死龙", "遐蝶", "ally_dot")]
          + _gap(260.8, 266.0, 0.4, card_type="empty")
          + [R(266.8, "长夜月", "长夜月", "ally_star")])
    row, _, src = C.find_actor_ult(rd, 264.0)
    assert row is None and src == "", (row, src)
    return "→ 不采纳（前锚点 死龙/遐蝶 不是星、两侧不同人）"


@case("③ 跨度里大半是阿哈时刻 → 不采纳（交线3；实测录屏1 t=171.4~172.4 是 7/11）")
def _c3():
    rd = ([R(167.0, "小伊卡", "风堇", "ally_star")]
          + _gap(167.4, 168.2, 0.4, card_type="empty")
          + [R(168.6 + 0.4 * i, "小伊卡", "风堇", "gold_aha", "aha") for i in range(7)]
          + [R(172.0, "", "", "empty", "empty")])
    row, _, src = C.find_actor_ult(rd, 172.0)
    assert row is None and src == "", (row, src)
    share = C.span_aha_share(rd, 167.0, 172.0)
    assert share > C.AHA_SHARE_MAX, share
    return "→ 不采纳（阿哈占比 %.0f%% > %.0f%%）" % (100 * share, 100 * C.AHA_SHARE_MAX)


@case("④ 两侧锚点同一归属 → 采纳（tier A，实测录屏1 #5/#27 昔涟）")
def _c4():
    rd = ([R(129.0, "昔涟", "昔涟", "ally_star")]
          + _gap(129.4, 134.6, 0.4, card_type="empty")
          + [R(135.0, "昔涟", "昔涟", "ally_dot")])
    row, _, src = C.find_actor_ult(rd, 134.0)
    assert row and row["owner"] == "昔涟" and src == "ult_A", (row, src)
    return "→ 昔涟 / ult_A"


@case("⑤ 跨度里**没有空槽**（轴在、只是糊卡）→ 不采纳")
def _c5():
    rd = ([R(100.0, "遐蝶", "遐蝶", "ally_dot")]
          + [R(101.0, "", "", "?_dot", "unit"), R(102.0, "", "", "?_dot", "unit")]
          + [R(103.0, "遐蝶", "遐蝶", "ally_dot")])
    row, _, src = C.find_actor_ult(rd, 102.5)
    assert row is None and src == "", (row, src)
    return "→ 不采纳（span 里没有 marker=empty 的帧）"


@case("⑥ 锚点离事件超过 max_age(8s) → 不采纳")
def _c6():
    rd = ([R(100.0, "飞霄", "飞霄", "ally_star")]
          + _gap(100.4, 118.8, 0.4, card_type="empty")
          + [R(120.0, "那刻夏", "那刻夏", "ally_dot")])
    row, _, src = C.find_actor_ult(rd, 119.0)
    assert row is None and src == "", (row, src)
    return "→ 不采纳（前锚点 19s 外、后锚点不是星）"


@case("⑦ 两侧锚点都是**欢愉技卡**(elation) → 不采纳（锚点自身必须是 unit 卡）")
def _c7():
    # 实测：屏幕录制 2026-10-04 110419.mp4 t=277 与 t=291.5 两张都是青色菱形欢愉技卡，
    # 只查"跨度内部的阿哈占比"查不出来（它们站在跨度**两端**）。
    rd = ([R(276.0, "赛飞儿", "赛飞儿", "ally_diamond", "elation")]
          + _gap(277.5, 290.5, 0.5, card_type="empty")
          + [R(291.5, "赛飞儿", "赛飞儿", "ally_diamond", "elation")])
    row, _, src = C.find_actor_ult(rd, 283.5)
    assert row is None and src == "", (row, src)
    return "→ 不采纳（两张欢愉技卡不构成 tier A 锚点）"


def selftest():
    bad = 0
    print("=== T1 规则自检（%d 条）===" % len(CASES))
    print("    ULT_MAX_AGE=%.1fs  AHA_SHARE_MAX=%.0f%%" % (C.ULT_MAX_AGE, 100 * C.AHA_SHARE_MAX))
    for name, fn in CASES:
        try:
            print("  OK  %s\n      %s" % (name, fn()))
        except AssertionError as e:
            bad += 1
            print("  !!  %s\n      %s" % (name, e))
    print("自检 %s（%d/%d）" % ("通过" if not bad else "不通过", len(CASES) - bad, len(CASES)))
    return 1 if bad else 0


# ────────────────────────── 前后对比 ──────────────────────────
def compare(frames):
    print("=== T1 前后对比：%s ===" % frames)
    got = {}
    for flag in (False, True):
        readings, events, _ = E4.build(frames=frames, ult_window=flag)
        got[flag] = (readings, events)
        tot = sum(int(e["damage_max"]) for e in events if e["status"] == "ok")
        print("  ult_window=%-5s 事件 %d  ok %d  review %d  可采纳总伤 %s"
              % (flag, len(events),
                 sum(1 for e in events if e["status"] == "ok"),
                 sum(1 for e in events if e["status"] == "review"), format(tot, ",")))

    a = {e["event"]: e for e in got[False][1]}
    b = {e["event"]: e for e in got[True][1]}
    print("  --- 新采纳的事件 ---")
    n = 0
    for k in sorted(set(a) | set(b)):
        x, y = a.get(k), b.get(k)
        if not x or not y:
            continue
        if (x["unit"], x["owner"], x["status"]) != (y["unit"], y["owner"], y["status"]):
            n += 1
            print("    #%-3d %7.1f~%-7.1f dmg=%-10s review → %s/%s  src=%s"
                  % (k, x["t_first"], x["t_last"], x["damage_max"],
                     y["unit"] or "-", y["owner"] or "-", y.get("actor_src") or "-"))
    if not n:
        print("    （无）")

    readings = got[True][0]
    raw = [r for r in readings if r["grade"] == "raw"]
    print("  --- 覆盖率（能挂到已确认行动者的可信读数帧）---")
    for flag in (False, True):
        c = 0
        for r in raw:
            ok, _ = C.find_actor(readings, r["t"], 1.5, 0.5)
            if ok is None and flag:
                ok, _, _ = C.find_actor_ult(readings, r["t"])
            if ok is not None:
                c += 1
        print("    ult_window=%-5s  %d/%d = %.1f%%"
              % (flag, c, len(raw), 100.0 * c / max(1, len(raw))))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--compare", default="", help="帧表 CSV（如 out/frames_dense4.csv）")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.compare:
        return compare(args.compare)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
