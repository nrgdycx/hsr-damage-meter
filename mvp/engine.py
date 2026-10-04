# -*- coding: utf-8 -*-
"""[MVP] 流式事件引擎：读数流 → 事件 → 按角色累计。

设计原则（一条就够）：**口径不许漂移，所以不重写判据。**
本模块的切分/归属/剔除**直接调用** `events_v4.py` 的函数
（`classify` / `mark_rejects` / `segment` / `expand_span` / `attribute4`），
不复制任何一行判据 —— 离线批处理与实时流因此**结构上同口径**。

实时化要解决的三件事
--------------------
1. **没有"整段录像"**：只能看已经到手的帧。
   → 维护一个滑动窗口，窗口内定期重算切分，**只把"已经定稿"的段吐出来**。
2. **未来的帧会改变过去的判据吗？** 会，但**只影响 1.6 秒以内**
   （实测：碎片判据 `frag_win=1.5`、`value_partners` 前向 `fwd=1.6`、
   毛刺判据 `glitch_win=0.6`）。所以：
   → **定稿延迟 `lag=2.4s`**：只定稿"段的末端（含被剔除/空帧扩边后）至少 2.4s 以前"的段。
     为什么不是"最后一条可信读数 + 一点点"：剔除判据会**级联**
     （R1b 量级碎片依赖 R2 毛刺的结论，而 R2 要等后面 0.6s 的读数），
     上界 = frag_win(1.5) + glitch_win(0.6) = 2.1s。实测用 1.75s 会出错（见下）。
3. **浮点/边界效应**：窗口左边缘缺少左侧上下文，会把判据算歪。
   → 三个同心范围（**数值来历见下**）：
       · `SEG_KEEP=20s`  参与切分的行（切分是线性的，便宜）
       · `REJ_KEEP=8s`   参与剔除判据的行（判据只看向左右 1.5s，8s 足够）
       · `REJ_CLEAR=4.5s` 真正**重新计算** reject 的行
         （外面的行保留上一次的结果 —— 那些结果就是"最终值"，因为上下文早已齐了）
       · 比 `REJ_RESTORE=6.0s` 更老的行在本次重算后**恢复**原值
         （它们在窗口左边缘，左侧上下文被截断，重算结果不作数）

⚠️ 定稿延迟 = **画面落后约 2.4 秒**（不是处理延迟）。这是"口径与离线完全一致"
换来的代价，已写进 `docs/实时链路与悬浮窗.md` 的"已知限制"。处理延迟本身远低于 100ms。

实测踩过的两个坑（都在 `docs/实时链路与悬浮窗.md` 记了账）：
  1. 定稿延迟按"最后一条可信读数"算（1.75s）→ t=256.8~258.0 被 `4350036` 当容器误剔，
     段被提前定稿切成两截 → 遐蝶多算 121,030（重复计入）；
  2. 切分窗口裁进"上一个已定稿段" → 两段之间的断开判据消失、被并成一段 → 再次重复计入。
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import events_v4 as E4      # noqa: E402
import events as C       # noqa: E402
import mvp.av_reader as AVR      # noqa: E402

# ⚠️ **不再硬编码队伍名单**（2026-10-05 用户实机反馈）。
#
# 原来写的是 MVP 队伍（遐蝶/风堇/昔涟/长夜月），后果是：
#   换欢愉队（银狼/爻光/火花/真珠）测试时，悬浮窗上**永远挂着那 4 个幽灵行**
#   （0 伤害、0%），而欢愉队自己的角色一个都不显示。
#
# 现在 `rows` **只放真正有伤害的归属**（见 `totals()`）；
# 想让没出手的角色也占位，用 `roster_hint=(...)` 显式传（默认不占位）。
ALLY: tuple = ()          # 兼容旧导入；仅作"额外占位名单"，默认为空

SEG_KEEP = 20.0        # 参与切分的行保留时长
REJ_KEEP = 8.0         # 参与剔除判据的行保留时长
REJ_CLEAR = 4.5        # 重新计算 reject 的行（对齐"冻结/重算/恢复"三段）
REJ_RESTORE = 6.0      # 比这更老的行，重算结果作废、恢复原值
# 定稿延迟：**判据的"未来上下文"最长有多远**，实测比最初估的 1.75s 更长 ——
# 剔除规则会级联：R1b「量级碎片」拿一条**还没被 R2 判成毛刺**的大数当容器，
# 把真读数误剔（实测 t=256.8~258.0 被 `4350036` 当容器剔掉）；
# 而 R2 要等它**后面 0.6s 内**再出现一条读数才会判它是骤升毛刺。
# ⇒ 级联上界 = frag_win(1.5) + glitch_win(0.6) = 2.1s，取 2.4s 留余量。
# ⚠️ 这就是"画面落后约 2.4 秒"的来源（不是处理延迟）。
LAG = 2.4
MIN_INTERVAL = 0.2     # 最短重算间隔（5Hz）—— 定稿时间粒度


class LiveEngine:
    """把一条条读数喂进来，吐出**已定稿**的事件与按角色累计。"""

    def __init__(self, lag=LAG, gap=1.5, reset_ratio=0.20, back=1.5, fwd=0.5,
                 actor_split=True, plateau_break=3, absent_break=0.6, reject=True,
                 min_interval=MIN_INTERVAL, ally=ALLY, seg_keep=SEG_KEEP,
                 rej_keep=REJ_KEEP, rej_clear=REJ_CLEAR, rej_restore=REJ_RESTORE,
                 ult_window=True, ult_max_age=None, roster_hint=None):
        self.lag = lag
        self.gap = gap
        self.reset_ratio = reset_ratio
        self.back, self.fwd = back, fwd
        self.actor_split = actor_split
        self.plateau_break = plateau_break
        self.absent_break = absent_break
        self.reject = reject
        self.min_interval = min_interval
        self.ally = tuple(ally)
        #: 想让"还没出手的角色"也占一行时显式传进来；默认**不占位**
        #: （旧行为是硬编码 MVP 队伍，换队伍后会冒出幽灵行）
        self.roster_hint = tuple(roster_hint or ())
        self.seg_keep, self.rej_keep = seg_keep, rej_keep
        self.rej_clear, self.rej_restore = rej_clear, rej_restore
        # T1：开大（插入终结技）演出窗口的归属兜底 —— 见 events.find_actor_ult
        self.ult_window = ult_window
        self.ult_max_age = ult_max_age

        self.rows = []            # **全部**读数（attribute4 / _quality 要全局时间范围）
        self.work = []            # 参与切分的尾部窗口（与 rows 共享同一批 dict 对象）
        self.events = []          # 已定稿事件（顺序 = 事件号）
        self.n_pass = 0
        self.n_stale_merge = 0    # 保险丝触发次数（正常应恒为 0）
        self.last_pass_t = None
        self._last_final_t = None       # 最后一条已定稿"可信读数"的 t
        self._last_final_first_t = None  # 最后一段已定稿的**第一条**可信读数的 t
        self._pending_from = None     # 第一个未定稿段的起点（用于决定能裁到哪里）
        self._open_run = None         # 当前未定稿段（给悬浮窗显示"当前是谁在打"）
        self._open_ev = None
        self.trace = None             # 可选调试钩子：trace(now, runs, new_events)

    # ────────────────────────── 主入口 ──────────────────────────
    def add(self, row):
        """喂一条读数。返回本次新定稿的事件列表（通常为空）。"""
        self.rows.append(row)
        self.work.append(row)
        return self._pass(row["t"], force=False)

    def flush(self):
        """收尾：把剩下的段全部定稿（离开对局时调用一次）。"""
        if not self.rows:
            return []
        return self._pass(self.rows[-1]["t"], force=True)

    # ────────────────────────── 一次重算 ──────────────────────────
    def _pass(self, now, force=False):
        if not force and self.last_pass_t is not None \
                and now - self.last_pass_t < self.min_interval:
            return []
        self.last_pass_t = now
        self.n_pass += 1

        # ① 剔除（**自己的窗口**：判据只看左右 1.5s，8s 足够）
        #    与切分窗口分开的理由：切分窗口会被"上一个已定稿段"挤短，
        #    而 reject 判据需要完整的 ±1.5s 上下文，否则窗口左缘的行会被算歪。
        if self.reject:
            rej_rows = [r for r in self.rows if r["t"] >= now - self.rej_keep]
            saved = {id(r): r["reject"] for r in rej_rows if r["t"] < now - self.rej_restore}
            E4.classify(rej_rows)
            for r in rej_rows:
                if r["t"] >= now - self.rej_clear:
                    r["reject"] = ""
            E4.mark_rejects(rej_rows, reset_ratio=self.reset_ratio)
            for r in rej_rows:
                if id(r) in saved:             # 窗口左缘上下文被截断 → 恢复既有结论
                    r["reject"] = saved[id(r)]

        # ② 切分窗口：**必须整段保留"上一个已定稿段"**（否则它与当前段的断开判据
        #    会因缺左侧上下文而消失 → 两段被并成一段 → 重复计入）。
        #    实测踩过：修这条之前多出 1 个事件、遐蝶多算 121,030（见 docs/实时链路与悬浮窗.md）。
        keep_from = now - self.seg_keep
        if self._last_final_first_t is not None:
            keep_from = min(keep_from, self._last_final_first_t - 2.0)
        if self._pending_from is not None:
            keep_from = min(keep_from, self._pending_from - 3.0)
        if self.work and self.work[0]["t"] < keep_from:
            self.work = [r for r in self.work if r["t"] >= keep_from]

        E4.classify(self.work)
        runs = E4.segment(self.work, gap=self.gap, reset_ratio=self.reset_ratio,
                          actor_split=self.actor_split,
                          plateau_break=self.plateau_break,
                          absent_break=self.absent_break)
        E4.expand_span(self.work, runs)
        for run in runs:
            rej = [r for r in self.work
                   if run["start"] - 1e-9 <= r["t"] <= run["end"] + 1e-9
                   and r["reject"].startswith("frag")]
            if rej:
                run["candidates"] = ["maybe_split@%s(%s)" % (C._fmt(r["t"]), r["text"])
                                     for r in rej]

        # ③ 定稿：只吐"最后一条可信读数 ≥ lag 秒以前"的段
        new_events, open_run = [], None
        for run in runs:
            first_t = run["rows"][0]["t"]
            last_t = run["rows"][-1]["t"]
            if self._last_final_t is not None and last_t <= self._last_final_t + 1e-9:
                continue                       # 属于已定稿的段（窗口左缘的残段）
            if self._last_final_t is not None and first_t <= self._last_final_t + 1e-9:
                # 保险丝：段起点落在已定稿区间里（= 与已定稿段并在一起了）。
                # 正常路径不会走到这里（② 保证了上下文完整）；真走到就**不猜**，
                # 只记数、等下一轮重算（绝不重复计入，也不静默丢数）。
                self.n_stale_merge += 1
                continue
            if not force and (now - run["end"]) < self.lag:
                open_run = run                 # 还没定稿 —— 它后面的段更晚，必然也没定稿
                break
            ev = E4.attribute4(self.rows, run, back=self.back, fwd=self.fwd,
                               ult_window=self.ult_window, ult_max_age=self.ult_max_age)
            if ev is None:
                continue
            ev["event"] = len(self.events) + 1
            # T2（附伤分离）：给事件挂拆分结论。**只加不改** —— 不动 totals() 的口径，
            # 所以 P1 的 verify_live 对账不受影响。见 tools/team2/live_hook.py
            try:
                from tools.team2.live_hook import annotate_event
                ev["t2"] = annotate_event(ev, self.ally)
            except Exception:                       # noqa: BLE001  附伤层坏了不影响主链路
                ev["t2"] = None
            self.events.append(ev)
            self._maybe_merge_tail()
            new_events.append(ev)
            self._last_final_t = last_t
            self._last_final_first_t = first_t

        # ⑤ 记录"当前这一段"给悬浮窗用（不算进合计）
        self._open_run = open_run
        self._open_ev = None
        if open_run is not None:
            try:
                self._open_ev = E4.attribute4(self.rows, open_run,
                                              back=self.back, fwd=self.fwd,
                                              ult_window=self.ult_window,
                                              ult_max_age=self.ult_max_age)
            except Exception:
                self._open_ev = None
        # 下一个未定稿段的起点（决定 work 能裁到哪里）
        self._pending_from = open_run["start"] if open_run is not None else None
        if self.trace is not None:            # 调试钩子（默认 None，不参与生产路径）
            self.trace(now, runs, new_events)
        return new_events

    #: 「同一次攻击被切成多段」的合并窗口（秒）。
    #: 用户 2026-10-05 反馈：「狼尊的强普是分阶段累计加的，你重复计数了，
    #: 比如动画会显示 20->30->40，要记录的是 40 而不是 90」。
    #: 强普/大招的伤害是**分阶段累加**的，读数一级一级往上跳（20→30→40）；
    #: 这种**单调递增**如果中间被切了一刀，就变成多个事件、**逐段相加 = 重复计数**。
    MERGE_GAP = 2.5          # 后一段起点距前一段终点多近才算"同一击"
    MERGE_MIN_RATIO = 0.60   # 后一段最大值 ≥ 前一段 ×这个比例（递增/持平）
    MERGE_FLOOR = 200_000    # 两段都 ≥ 这个量级才合并（防小额误并）

    def _maybe_merge_tail(self):
        """把"同一次攻击被切成多段"的尾部事件合并掉（见 `MERGE_GAP` 的说明）。

        判据（全部满足才并）：
          * `owner` 相同且非空
          * 后一段起点 − 前一段终点 ≤ `MERGE_GAP`
          * 两段的 `damage_max` 都 ≥ `MERGE_FLOOR`（量级够大，排除小额噪声）
          * 后一段 ≥ 前一段 × `MERGE_MIN_RATIO`（**递增或基本持平** —— 正是"分阶段累加"）
          * 前一段不是 `non_ally` / 敌方

        合并语义：**保留后一段**（它的 `damage_max` 就是那次攻击的当前累计值，
        也是我们唯一该记的数）；把前一段标 `merged_into` 后**从事件表移除**。
        —— 这正是用户要的"记 40 而不是 20+30+40"。

        ⚠️ 只在"值在涨"时并：**跌下去**（新一击从小数重新开始）正是原 reset 判据，
        那种情况两段的比值会远低于 `MERGE_MIN_RATIO`，不会被并。
        """
        if len(self.events) < 2:
            return
        a = self.events[-2]
        b = self.events[-1]
        try:
            if a.get("status") == "non_ally" or b.get("status") == "non_ally":
                return
            oa, ob = (a.get("owner") or ""), (b.get("owner") or "")
            if not oa or oa != ob:
                return
            da = int(a.get("damage_max") or 0)
            db = int(b.get("damage_max") or 0)
            if da < self.MERGE_FLOOR or db < self.MERGE_FLOOR:
                return
            if db < da * self.MERGE_MIN_RATIO:
                return
            ta = float(a.get("t_last") or a.get("t_anchor") or 0.0)
            tb = float(b.get("t_first") or b.get("t_anchor") or 0.0)
            if tb - ta > self.MERGE_GAP:
                return
        except Exception:                                # noqa: BLE001
            return
        # 合并：保留 b（更大的那个值），a 标掉并移除
        b["merged_from"] = (b.get("merged_from") or []) + [a.get("event")]
        b["merged_n"] = int(b.get("merged_n") or 0) + 1 + int(a.get("merged_n") or 0)
        b["t_first"] = min(float(a.get("t_first") or tb),
                           float(b.get("t_first") or tb))
        b["issues"] = ",".join(filter(None, [b.get("issues"),
                                             "merged_accum"]))
        self.events.pop(-2)
        for i, e in enumerate(self.events, 1):           # 事件号重排
            e["event"] = i
        self.n_merged = getattr(self, "n_merged", 0) + 1

    # ────────────────────────── 汇总 ──────────────────────────
    def totals(self):
        """按归属累计（**口径 = `events.summarize`：只算 `status == ok`**）。

        ⚠️ `review`（待复核）与 `non_ally`（敌方）**不进分子也不进分母** ——
        MVP 验收第 5 条："判不出来不猜"。所以占比的分母是"归属确定的事件"。
        """
        agg = {}
        for e in self.events:
            if e["status"] != "ok":
                continue
            o = e["owner"] or "(未定)"
            a = agg.setdefault(o, {"n": 0, "damage": 0})
            a["n"] += 1
            a["damage"] += int(e["damage_max"])
        total = sum(a["damage"] for a in agg.values())
        rows = []
        for o, a in agg.items():
            rows.append({"owner": o, "n": a["n"], "damage": a["damage"],
                         "pct": (100.0 * a["damage"] / total) if total else 0.0})
        rows.sort(key=lambda r: -r["damage"])
        # ⚠️ 只显示**真正有伤害的归属**（2026-10-05 改）。
        #
        # 原来这里会按 hardcode 的队伍名单补 0 伤害的占位行，导致换队伍后
        # 悬浮窗上一直挂着旧队伍的 4 个幽灵（用户实测反馈：
        # 「为什么那个悬浮窗在我测欢愉角色的时候还写着遐蝶、风堇啥的」）。
        # 现在若要占位，必须用 roster_hint 显式传。
        for name in self.roster_hint:
            if not any(r["owner"] == name for r in rows):
                rows.append({"owner": name, "n": 0, "damage": 0, "pct": 0.0})
        return rows, total

    # ────────────────────────── T2 附伤分离（展示用）──────────────────────────
    def t2_rows(self):
        """把估算出的附伤份额从行动者挪到来源名下的**展示口径**（记 `估算`）。

        ⚠️ 与 `totals()` 并行存在，不覆盖它 —— 基线口径要保持可对账。
        """
        try:
            from tools.team2.live_hook import adjust_rows
            rows, _ = self.totals()
            return adjust_rows(self.events, rows)
        except Exception:                           # noqa: BLE001
            return None

    def t2_line(self):
        """悬浮窗脚注：最近带附伤的事件（不出现「待复核」字样）。"""
        try:
            from tools.team2.live_hook import state_line
            return state_line(self.events)
        except Exception:                           # noqa: BLE001
            return ""

    def current_actor(self, window=1.5):
        """「当前是谁在打」。

        优先用**未定稿那一段**的锚点归属（正在打的这次攻击）；
        没有就退到"最近 window 秒内**已确认**的行动者"；
        🆕 **T1 开大窗口**：再退到"最后看到的是一张**四角星（插入行动）**的我方卡、
        且此后整条行动轴都消失（离现在 ≤ `ult_max_age` 秒）" —— 那就是这个人正在开大。
        机制（用户 2026-10-03 确认 / 2026-10-04 补充）：**插入行动 → 该次行动的演出 → 演出期间显示伤害**；
        演出把整条行动轴从画面上抹掉，所以「当前行动」只能由演出前那张星标卡给出。
        ⚠️ 四角星 = **插入行动**（大招 / **助战技** / 额外回合），**不限于大招**
        （用户 2026-10-04：「拓星者是姬子的**助战技**、不是大招」）—— 归属结论一样，都是"这张卡的人"。
        ⚠️ 只认四角星：若最后一张我方卡是普通圆点，就**不借**（那可能已经换人了）。
        再没有 → `None`（悬浮窗显示"待复核"，**不显示上一个已知的人** —— 那是猜）。
        """
        if self._open_ev and self._open_ev.get("status") == "ok":
            return {"owner": self._open_ev["owner"], "unit": self._open_ev.get("unit") or "",
                    "src": "open_event"}
        if not self.rows:
            return None
        now = self.rows[-1]["t"]
        for r in reversed(self.rows):
            if now - r["t"] > window:
                break
            if r["unit"]:
                return {"owner": r["owner"] or r["unit"], "unit": r["unit"], "src": "recent_frame"}
        max_age = C.ULT_MAX_AGE if self.ult_max_age is None else self.ult_max_age
        for r in reversed(self.rows):
            if now - r["t"] > max_age:
                break
            if r["unit"]:
                if C.is_insert_card(r) and C.span_axis_gone(self.rows, r["t"], now):
                    return {"owner": r["owner"] or r["unit"], "unit": r["unit"],
                            "src": "ult_window"}
                break
        return None

    def state(self, av_total=None, debug=False):
        """给悬浮窗/终端的一份完整状态。"""
        rows, total = self.totals()
        cur = self.current_actor()
        n_review = sum(1 for e in self.events if e["status"] == "review")
        n_non_ally = sum(1 for e in self.events if e["status"] == "non_ally")
        d = AVR.dps(total, av_total)
        st = {
            "rows": rows, "total": total, "n_events": len(self.events),
            "n_review": n_review, "n_non_ally": n_non_ally,
            "actor": cur, "actor_owner": (cur or {}).get("owner"),
            "actor_unit": (cur or {}).get("unit", ""),
            "actor_src": (cur or {}).get("src"),
            "open_event": self._open_ev,
            "dps": d, "dps_line": AVR.format_dps(d, av_total),
            "last_t": self.rows[-1]["t"] if self.rows else None,
            "lag": self.lag, "n_pass": self.n_pass,
            "n_stale_merge": self.n_stale_merge,
            # T2：附伤分离（展示用；基线 totals() 不动）
            "t2_rows": self.t2_rows(),
            "t2_line": self.t2_line(),
        }
        if debug:
            st["debug"] = "事件 %d（待复核 %d / 敌方 %d）  重算 %d 次  覆盖 t≤%.1fs" % (
                st["n_events"], n_review, n_non_ally, self.n_pass, st["last_t"] or 0.0)
        return st


def _selftest():
    """自检（不碰屏幕）：假读数流跑一遍，检查累计口径与"判不出来不猜"。"""
    eng = LiveEngine()
    # 两次攻击：t=0~1.0 遐蝶（值涨到 1000），空白 2.0s，t=3~4 风堇（值涨到 500）
    def feed(t, text, n, owner, unit):
        return {"t": t, "text": text, "n": n, "conf": 0.9, "unit": unit, "owner": owner,
                "score": 1.9, "margin": 1.5, "marker": "ally_dot", "inserted": "0",
                "card_type": "unit", "grade": "", "reject": ""}
    seq = [(0.0, "400"), (0.2, "700"), (0.4, "1000"), (0.6, "1000"), (1.0, "1000")]
    for t, txt in seq:
        eng.add(feed(t, txt, len(txt), "遐蝶", "遐蝶"))
    for t in (1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.4):
        eng.add(feed(t, "", 0, "", ""))
    for t, txt in ((3.0, "200"), (3.2, "500"), (3.4, "500")):
        eng.add(feed(t, txt, len(txt), "风堇", "小伊卡"))
    for t in (3.6, 3.8, 4.0, 4.2):
        eng.add(feed(t, "", 0, "", ""))
    eng.flush()
    rows, total = eng.totals()
    d = {r["owner"]: r["damage"] for r in rows}
    print("  事件数 %d，合计 %d，按角色 %s" % (len(eng.events), total, d))
    assert d.get("遐蝶") == 1000, d
    assert d.get("风堇") == 500, d
    assert total == 1500, total
    # 待复核不猜：只给"识别不出"的帧
    eng2 = LiveEngine()
    for t in (0.0, 0.2, 0.4):
        eng2.add({"t": t, "text": "123", "n": 3, "conf": 0.9, "unit": "", "owner": "",
                  "score": 0.5, "margin": 0.1, "marker": "?_dot", "inserted": "",
                  "card_type": "unit", "grade": "", "reject": ""})
    eng2.flush()
    assert all(e["status"] == "review" for e in eng2.events), eng2.events
    assert eng2.totals()[1] == 0, "待复核不许进合计"
    assert eng2.current_actor() is None, "判不出来时不许回退到'上一个人'"
    print("engine 自检通过：口径=只算 status=ok；判不出来不进合计、不猜")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
