# -*- coding: utf-8 -*-
"""【T2】录屏2 事件表 + 附伤拆分落地。

做法：
  1. 把 `out/frames_L2.csv`（HUD 读数）与 `out/axis_actors_L2.csv`（顶端卡）按时刻对齐；
  2. **复用 C 线的切分函数** `events.segment()`（只读，不改）切成"一次攻击"；
  3. 每段取峰值读数当锚点，用 `card_kind_t2` 细化顶端卡（盲盒/欢愉技/敌方buff），
     再用 `split_add_damage` 给出归属分解（精确 / 估算区间）；
  4. 出 `out/L2_split.csv` + 覆盖率前后对比。

用法： python -u tools/team2/events_l2.py
"""
import os as _os
import sys as _sys
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import csv
import json
import os
import sys

HERE = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if not _os.path.isdir(_os.path.join(HERE, "out")):
    HERE = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import events as E                     # noqa: E402  只读复用切分函数
from tools.team2 import card_kind_t2 as CK     # noqa: E402
from tools.team2 import aha_member as AHA      # noqa: E402  T2：阿哈时刻按参演编号归属
from tools.team2.split_add_damage import (split_attack, weigh, actor_candidates,   # noqa: E402
                                          load_catalog, load_owners)

TEAM = ["火花", "爻光", "真珠", "银狼LV.999"]
FRAMES = _os.path.join(HERE, "out/frames_L2.csv")
ACTORS = _os.path.join(HERE, "out/axis_actors_L2.csv")
OUT = _os.path.join(HERE, "out/L2_split.csv")
_TL = None


def aha_timeline():
    """阿哈时刻的成员时间轴（没有就现建一次）。"""
    global _TL
    if _TL is None:
        p = _os.path.join(HERE, "out/t2_aha_timeline.json")
        if _os.path.isfile(p):
            _TL = json.load(open(p, encoding="utf-8"))["runs"]
        else:
            _TL, _ = AHA.build(team=tuple(TEAM))
    return _TL


def aha_owner_at(t, lookback=1.2, lead=1.5):
    """阿哈时刻：**认脸**定人（用户 2026-10-04：框里的人不是定的，必须认脸）。

    ① t 落在某段里 → 那段的成员；
    ② t 在某段结束后 `lookback` 秒内 → 结算滞后，算刚结束那位；
    ③ t 在某段开始前 `lead` 秒内 → 阿哈段边界被 1s 网格切掉 → 算该段。
    认不出/没覆盖 → None（**不猜**）。
    """
    tl = aha_labeled()          # 懒加载（第一次调用时才建/认脸）
    if not tl:
        return None
    for r in tl:
        if r["member"] and r["t0"] - 1e-6 <= t <= r["t1"] + 1e-6:
            return r
    best = None
    for r in tl:
        if r["member"] and -0.2 <= t - r["t1"] <= lookback:
            if best is None or r["t1"] > best["t1"]:
                best = r
    if best is not None:
        return best
    for r in tl:
        if r["member"] and -0.2 <= r["t0"] - t <= lead:
            return r
    return None


_AHA_LABELED = [None]


def aha_labeled():
    """43 段的身份时间轴（认脸；用户标注优先）。进程内缓存。"""
    if _AHA_LABELED[0] is None:
        _AHA_LABELED[0] = AHA.timeline_labeled()
    return _AHA_LABELED[0]


def load_rows():
    fr = {}
    with open(FRAMES, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            fr[round(float(r["t"]), 2)] = r
    ac = {}
    with open(ACTORS, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            ac[round(float(r["t"]), 2)] = r
    rows = []
    for t in sorted(set(fr) | set(ac)):
        f, a = fr.get(t, {}), ac.get(t, {})
        rows.append({"t": t, "hud_text": (f.get("text") or "").strip(),
                     "hud_n": 0, "hud_nbad": 0, "hud_minconf": float(f.get("conf") or 0),
                     "unit": (a.get("unit") or "").strip(), "owner": (a.get("owner") or "").strip(),
                     "score": float(a.get("score") or 0), "margin": float(a.get("margin") or 0),
                     "marker": (a.get("marker") or "").strip(),
                     "card_type": (a.get("card_type") or "").strip(),
                     "inserted": (a.get("inserted") or "").strip(),
                     "font": (f.get("font") or "").strip(), "verdict": (f.get("verdict") or "").strip()})
    return rows


def t2_card(t):
    """带 T2 细化的顶端卡（盲盒 / 敌方buff / 欢愉技 / 单位）。"""
    try:
        return CK.read_actor_t2(float(t))
    except Exception as e:                     # noqa: BLE001
        return {"card_type": "", "unit": "", "owner": "", "t2_kind": None, "err": str(e)}


def find_actor_rows(rows, t_anchor, back=1.5, fwd=0.5):
    """因果窗口 [-back, +fwd] 内找顶端卡：优先取**锚点之前**最近一次已确认的单位卡。

    与 C 线 `find_actor` 同口径（HUD 出数在打完之后 → 行动者只能取之前的帧）。
    另：T2 的盲盒/敌方buff 卡优先（它们本身就是归属证据）。
    """
    cand = [r for r in rows if t_anchor - back <= r["t"] <= t_anchor + fwd]
    for r in cand:                                   # ① 盲盒 / 敌方buff：直接就是结论
        k = t2_card(r["t"])
        if k.get("t2_kind") in ("blindbox", "enemy_buff"):
            return r, k
    before = [r for r in cand if r["t"] <= t_anchor and (r["unit"] or r["card_type"] in ("aha",))]
    before.sort(key=lambda r: -r["t"])
    for r in before:                                 # ② 锚点之前最近的已确认单位
        k = t2_card(r["t"])
        if k.get("unit") or k.get("card_type") in ("elation", "aha"):
            return r, k
    after = [r for r in cand if r["t"] > t_anchor]
    after.sort(key=lambda r: r["t"])
    for r in after:                                  # ③ 之后最近（兜底）
        k = t2_card(r["t"])
        if k.get("unit"):
            return r, k
    # ④ T1 兜底：大招全屏演出把行动轴抹掉 → 借"演出前的四角星卡"（复用 C 线实现，只读）
    try:
        row, d, src = E.find_actor_ult(rows, t_anchor)
        if row is not None and row.get("unit"):
            return row, t2_card(row["t"])
    except Exception:                                # noqa: BLE001
        pass
    return (cand[-1] if cand else None), {}


def split_event(ev, rows, catalog, owners):
    """一段事件 → 归属分解。锚点 = 段内峰值读数那一帧；行动者取因果窗口内最近的卡。"""
    best = None
    for r in ev["rows"]:
        txt = r["hud_text"]
        if txt and "?" not in txt and txt.isdigit():
            if best is None or int(txt) > int(best["hud_text"]):
                best = r
    anchor = best or ev["rows"][-1]
    t = anchor["t"]
    src_row, card = find_actor_rows(rows, t)
    ct, unit = card.get("card_type"), card.get("unit")
    t_card = src_row["t"] if src_row is not None else t
    if card.get("t2_kind") == "blindbox":
        return dict(t=t, kind="blindbox", text="银狼LV.999", mark="精确", actor_t=t_card,
                    why="顶轴 t=%g 是【头号补给盲盒】的卡 → 整段归银狼LV.999" % t_card, card=card)
    if card.get("t2_kind") == "enemy_buff":
        return dict(t=t, kind="enemy_buff", text="（不计入）", mark="不计入", actor_t=t_card,
                    why="敌方给我方的 buff 卡 → 不计入我方伤害", card=card)
    if ct in ("unit", "elation") and unit:
        if unit in owners:                     # 忆灵/召唤物
            return dict(t=t, kind="summon", text=owners[unit], mark="精确", actor_t=t_card,
                        why="顶轴 t=%g 是召唤物「%s」→ 归召唤者 %s" % (t_card, unit, owners[unit]),
                        card=card)
        res = split_attack(unit, TEAM, catalog, owners)
        w = weigh(res, actor_cands=actor_candidates(unit))
        parts = [x for x in w["parts"] if not x.get("owner_body") and x.get("share_lo") is not None]
        body = next((x for x in w["parts"] if x.get("owner_body") and x.get("share_lo") is not None),
                    None)
        txt = " + ".join("%s %.0f%%~%.0f%%" % (x["owner"], 100 * x["share_lo"], 100 * x["share_hi"])
                         for x in parts) if parts else "（无外源附伤）"
        if body:
            txt = "%s：%.0f%%~%.0f%% ｜ 附伤：%s" % (unit, 100 * body["share_lo"],
                                                    100 * body["share_hi"], txt)
        return dict(t=t, kind="attack", text=txt, mark=w["mark"], actor_t=t_card,
                    why="行动者=顶轴 t=%g（因果窗口内最近）｜ %s" % (t_card, w.get("note") or ""),
                    card=card)
    # ⑤ 阿哈时刻：⛔ 不能靠参演编号顺序推（用户 2026-10-04 否决）→ **认脸**定人。
    #    认脸库用用户标注的 27 段建，段级留一验证 27/27 = 100%；认不出就如实标"认不出"，不猜。
    if ct == "aha":
        r = aha_owner_at(t)
        if r is not None:
            tag = r["member"] + (("·" + r["form"]) if r.get("form") else "")
            how = "用户标注" if r["how"] == "user-label" else "认脸(票%.2f)" % r.get("vote", 0)
            return dict(t=t, kind="aha", text=r["member"], mark="认脸", actor_t=t_card,
                        why="阿哈时刻 t=%g 框里是 %s（%s）" % (t, tag, how), card=card)
        return dict(t=t, kind="aha_unknown", text="", mark="无归属", actor_t=t_card,
                    why="阿哈时刻 t=%g：认脸没给出结论（不猜）" % t, card=card)
    return dict(t=t, kind="none", text="", mark="无归属", actor_t=t_card,
                why="因果窗口内没有可归属的卡（t=%g：%s）" % (t_card, ct or "空"), card=card)


def main():
    rows = load_rows()
    catalog, owners = load_catalog(), load_owners()
    evs = E.segment(rows, gap=1.5, reset_ratio=0.20)
    out, stat = [], {}
    base_ok = 0
    for i, ev in enumerate(evs, 1):
        s = split_event(ev, rows, catalog, owners)
        stat[s["mark"]] = stat.get(s["mark"], 0) + 1
        stat[s["kind"]] = stat.get(s["kind"], 0) + 1
        # 基线（现状口径）：只有锚点那张卡本身是已确认的**单位**卡才算得上
        arow = next((r for r in ev["rows"] if r["t"] == s["t"]), ev["rows"][-1])
        base = bool(arow.get("unit")) and (arow.get("card_type") == "unit")
        base_ok += 1 if base else 0
        out.append(dict(idx=i, t0=ev["start"], t1=ev["end"], n=len(ev["rows"]),
                        peak=(max((int(r["hud_text"]) for r in ev["rows"]
                                   if r["hud_text"].isdigit()), default=0)),
                        base="单位卡" if base else "无",
                        **{k: v for k, v in s.items() if k != "card"}))
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["idx", "t0", "t1", "n", "peak", "t", "actor_t",
                                          "kind", "mark", "base", "text", "why"])
        w.writeheader()
        for r in out:
            w.writerow(r)

    print("录屏2 事件表（复用 C 线切分，gap=1.5s）")
    print("  段数：%d ｜ 段内有读数的段：%d" % (len(evs), sum(1 for r in out if r["peak"])))
    print("  归属标记分布：%s" % json.dumps({k: v for k, v in stat.items()
                                             if k in ("精确", "估算", "估算(区间)", "不计入", "无归属")},
                                            ensure_ascii=False))
    print("  类型分布：%s" % json.dumps({k: v for k, v in stat.items()
                                         if k in ("blindbox", "enemy_buff", "summon", "attack",
                                                  "aha", "none")},
                                        ensure_ascii=False))
    named = sum(1 for r in out if r["kind"] in ("blindbox", "summon", "attack", "aha"))
    print("  **能给出归属的段：%d/%d = %.1f%%**" % (named, len(out), 100.0 * named / max(1, len(out))))
    print("  （基线口径：锚点那张卡本身是已确认单位卡 → %d/%d = %.1f%%）"
          % (base_ok, len(out), 100.0 * base_ok / max(1, len(out))))
    print("  T2 新增归属：盲盒 %d 段、阿哈时刻 %d 段、敌方buff %d 段"
          % (stat.get("blindbox", 0), stat.get("aha", 0), stat.get("enemy_buff", 0)))
    aha_members = {}
    for r in out:
        if r["kind"] == "aha":
            aha_members[r["text"]] = aha_members.get(r["text"], 0) + 1
    if aha_members:
        print("     阿哈段归属分布：%s" % json.dumps(aha_members, ensure_ascii=False))
    reasons = {}
    for r in out:
        if r["kind"] in ("none", "aha_unknown"):
            tag = r["why"].rsplit("：", 1)[-1].rstrip("）")
            tag = tag.split("（")[0][:26]
            reasons[tag] = reasons.get(tag, 0) + 1
    if reasons:
        print("  无归属的 %d 段，按窗口内卡的种类：" % sum(reasons.values()))
        for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print("     %-12s %d 段" % (k, v))
    print("\n前 12 段：")
    for r in out[:12]:
        print("  #%-3d t=%-6s~%-6s 峰值=%-9s %-10s %-11s %s"
              % (r["idx"], r["t0"], r["t1"], r["peak"], r["kind"], r["mark"], r["text"][:60]))
    print("\n已写出 %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
