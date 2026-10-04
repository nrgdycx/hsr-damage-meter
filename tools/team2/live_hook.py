# -*- coding: utf-8 -*-
"""【T2】实时/离线**附伤分离**的挂钩层（悬浮窗用）。

设计原则：**只加不改**。
  * 不动 `mvp/engine.py` 的 `totals()`（口径与 P1 的 `verify_live` 对账都建立在它上面）；
  * 只给每个事件挂一个 `ev["t2"]`，并额外提供 `adjust_rows()` —— 把估算出的附伤份额
    从"行动者"挪到"倍率所有者"名下（**展示用**，标 `估算`，不覆盖基线口径）。

口径见 docs/附伤与开大踢轴.md；用户 2026-10-04 定案：
  * 归属 = 倍率所有者；召唤物/盲盒按顶端卡归召唤者；
  * 「原伤害/总伤害 X%」= 独立乘区，跟行动者；
  * 界面**不出现"待复核"**；判不了就写"—"，依据留在 `why` 里。
"""
import os as _os
import sys as _sys
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

from tools.team2.split_add_damage import (load_catalog, load_owners, split_attack,  # noqa: E402
                                          weigh, actor_candidates)

DEFAULT_TEAM = ("火花", "爻光", "真珠", "银狼LV.999")


def annotate_event(ev, team=None):
    """给一个事件算附伤拆分（返回 dict 或 None）。事件里已有的信息：owner / unit / card_type。"""
    if not ev:
        return None
    team = list(team or DEFAULT_TEAM)
    owners = load_owners()
    cat = load_catalog()
    ct = (ev.get("card_type") or "").strip()
    unit = (ev.get("unit") or "").strip()
    owner = (ev.get("owner") or "").strip()

    if ct == "blindbox" or unit == "银狼LV.999盲盒":
        return {"text": "银狼LV.999", "mark": "精确", "whole_owner": "银狼LV.999",
                "why": "顶轴是【头号补给盲盒】的卡 → 整段归银狼LV.999", "parts": []}
    if ct == "enemy_buff":
        return {"text": "（不计入）", "mark": "不计入", "why": "敌方给我方的 buff 卡 → 不计入我方伤害",
                "parts": []}
    # 阿哈时刻：`mvp/reader.py` 已经**认脸**把 `unit` 填成框里那个人 → 整段归他
    # （用户 2026-10-04：框里的人不是定的，必须认脸；认不出/不是角色时 unit 为空 → 不猜）
    if ct == "aha":
        if unit:
            return {"text": unit, "mark": "认脸(整段)", "whole_owner": unit, "parts": [],
                    "why": "顶轴是阿哈面具框，认脸判出框里是 %s → 整段归他" % unit}
        return None
    if unit and unit in owners:
        return {"text": owners[unit], "mark": "精确",
                "why": "顶轴是召唤物「%s」→ 归召唤者 %s" % (unit, owners[unit]), "parts": []}
    if not owner:
        return None

    res = split_attack(owner, team, cat, owners)
    w = weigh(res, actor_cands=actor_candidates(owner))
    parts = [x for x in w["parts"] if not x.get("owner_body") and x.get("share_lo") is not None]
    body = next((x for x in w["parts"] if x.get("owner_body") and x.get("share_lo") is not None),
                None)
    if not parts:
        return {"text": "", "mark": "无附伤", "why": "本次攻击没有「我方目标施放攻击后」型附伤来源",
                "parts": []}
    return {"text": " ＋ ".join("%s %.0f%%~%.0f%%" % (p["owner"], 100 * p["share_lo"],
                                                     100 * p["share_hi"]) for p in parts),
            "mark": w["mark"], "why": w.get("note") or "",
            "parts": [{"owner": p["owner"], "lo": p["share_lo"], "hi": p["share_hi"]} for p in parts],
            "body": ({"owner": owner, "lo": body["share_lo"], "hi": body["share_hi"]}
                     if body else None),
            "missing": w.get("missing") or []}


def adjust_rows(events, rows=None):
    """展示用：把附伤份额的**中点**从行动者挪到来源名下，返回新的占比行。

    只是展示口径（记 `估算`），**不参与** P1 的 `totals()` 对账。
    """
    move = {}
    for e in events or []:
        t2 = e.get("t2") or {}
        dmg = int(e.get("damage_max") or 0)
        if not dmg:
            continue
        actor = e.get("owner") or ""
        # ① 整段归属（阿哈时刻认脸 / 盲盒 / 召唤物）——**不受 status=ok 限制**：
        #    阿哈段在基线口径里是 review（线3 的老口径），但 T2 已经能认脸给出归属。
        if t2.get("whole_owner"):
            o = t2["whole_owner"]
            if actor == o:
                continue
            if actor:
                move[actor] = move.get(actor, 0.0) - dmg
            move[o] = move.get(o, 0.0) + dmg
            continue
        # ② 同一次攻击里的附伤拆分（只在基线算数的段上做）
        if e.get("status") != "ok" or not t2.get("parts"):
            continue
        for p in t2["parts"]:
            mid = 0.5 * (p["lo"] + p["hi"])
            mv = dmg * mid
            if actor:
                move[actor] = move.get(actor, 0.0) - mv
            move[p["owner"]] = move.get(p["owner"], 0.0) + mv
    if not move:
        return rows
    # ⚠️ 基线行里可能**没有**某个主人（例如阿哈段认脸认得的人，在基线口径里从没算过数）
    #    → 这些必须补一行，否则"挪过去"的钱会凭空消失。
    by_owner = {r["owner"]: dict(r) for r in (rows or [])}
    for o in move:
        if o not in by_owner:
            by_owner[o] = {"owner": o, "damage": 0, "n": 0, "pct": 0.0}
    out = []
    for o, r in by_owner.items():
        d = r["damage"] + move.get(o, 0.0)
        out.append(dict(r, damage=int(round(d)), pct=None))
    tot = sum(r["damage"] for r in out) or 1
    for r in out:
        r["pct"] = 100.0 * r["damage"] / tot
    out.sort(key=lambda r: -r["damage"])
    return out


def state_line(events, limit=2):
    """悬浮窗脚注：最近几条带附伤的事件（**不出现"待复核"字样**）。"""
    hits = [e for e in (events or []) if (e.get("t2") or {}).get("parts")]
    if not hits:
        return ""
    out = []
    for e in hits[-limit:]:
        t2 = e["t2"]
        out.append("t=%s %s → 附伤 %s（%s）" % (e.get("t_last") or e.get("t_anchor") or "?",
                                                e.get("owner") or "—", t2["text"], t2["mark"]))
    return " ｜ ".join(out)
