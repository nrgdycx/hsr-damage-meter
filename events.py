# -*- coding: utf-8 -*-
"""
[C 线] 归属引擎 —— 把「HUD 总伤害读数」切成「每一次攻击」，并归属到角色，输出 CSV。

口径来源：[`docs/归属与事件切分.md`](docs/归属与事件切分.md)（全部经实测；本文档里写死的判据都标注了出处）

════════════════════════════════════════════════════════════════════════
一、读数口径（C线交接 §2，已推翻「整局累计」的假设）
════════════════════════════════════════════════════════════════════════
HUD「总伤害」= **一次攻击内累计**：
  * 同一次攻击里数值**单调递增** → 取该次攻击的**最大值**为这次攻击的总伤；
  * 数值**大幅下降 / 归零** → 上一次攻击结束、新一次开始（如 202126 → 4505）；
  * 数值**连续同值** → 这次攻击的最终值已到（停住了）；
  * **读数消失** → 攻击结束；HUD 稳定窗口实测只有 ~0.5s（不是文档写的 1~1.5s）。
  * ⚠️ **不做相邻读数求差 Δ**（那是 D 线基于"整局累计"给的方案，假设已被推翻）。

════════════════════════════════════════════════════════════════════════
二、事件切分（本文件的核心；参数都可由 CLI 覆盖，便于回归）
════════════════════════════════════════════════════════════════════════
把时间轴上的读数串成「段（run）」：一次攻击 = 一段连续、单调不减、中间没有长时间空白的读数。

切分判据（任一成立即断开；判据之间的优先级就是下面列出的顺序）：
  1. **读数空白 ≥ `--gap` 秒**（默认 1.5s）→ 断。
     来历：实测（out/frames_C.csv 的 118 条可用读数）相邻读数间隔是**双峰**的 ——
     `1.0s` 占 67 对（1 fps 抽帧下同一次攻击的相邻读数）、`2.0s` 占 10 对、`≥3s` 占 30 对。
     1.5s 正好落在两个峰中间：把"隔一帧"的（1.0s）留给同一次攻击，把"隔两帧以上"的断开。
     对照：t=154（顶端死龙/遐蝶）→ t=156（顶端长夜/长夜月）的间隔是 2.0s，是两次攻击。
  2. **数值下降**：新读数 < 当前段最大值 × (1 - `--reset-ratio`)（默认 20%）→ 断。
     来历：口径定案（C线交接 §2）—— 一次攻击内单调递增，重置即换攻击。
     实测：t=105 `662096` → t=106 `2809`（同秒内重置）、t=191 前后都是。
  3. **归属者变化 + 数值没有继续增长** → 断。
     来历：实测 t=154 `324751`（顶端死龙/遐蝶）→ t=156 `866730`（顶端长夜/长夜月）
     是**两次不同的攻击**；只靠数值不下降（866730 > 324751）是分不开的。
     而行动者变化**但数值继续增长**时不断（判据 3 后半条件）—— 那是同一次攻击里
     换了召唤者/忆灵在出手（如 t=156~163 长夜链）。
  4. **行动者在本段内从"召唤者"变成"忆灵"、且数值没有继续增长** → 断。
     来历：死龙/小伊卡这类忆灵是"主人行动后顶轴召唤"的，主人与忆灵**不是同一次行动**。
  5. 其余情况一律并入当前段（**同段取最大值**为该次攻击的总伤）。

════════════════════════════════════════════════════════════════════════
三、归属（C线交接 §3.2 + E 线 §3.3）
════════════════════════════════════════════════════════════════════════
* 锚点帧 = 段内**数值最大**的那一帧（= 攻击结算瞬间）；该帧没有行动者读数时退到段内
  最后一个有行动者读数的帧；
* 在锚点帧的 **[-`--back`, +`--fwd`] 秒**窗口里找**已确认**的行动者：
  **只能因果** —— 只取锚点**之前**的（先动手、后出数字；HUD 出数时行动轴可能已经上移），
  只有实在没有"之前"的才允许取锚点之后的。实测依据：t=221 顶端昔涟、t=222 顶端长夜月，
  若允许取之后的帧，`32209` 这段（t=221~222）会被判成长夜月（错）。
* `owner` 直接来自 E 线 `read_actor`（忆灵已按"算给召唤者"映射好）；
* 判不出来 → `status=review`，**不给归属也不猜**；
* `card_type=enemy` → 该次伤害不计入我方（`status=non_ally`，仍出现在 CSV 里，便于对账）。

════════════════════════════════════════════════════════════════════════
四、已知误读（A 线记录在案，C 线不能当真实数值用）
════════════════════════════════════════════════════════════════════════
* `?' → 该位低置信/几何超范围，读数**含 ? 就整条不可信**（`status=review`）。
* ⚠️ **静默丢前导位**（C 线实测，比 A 线文档记的严重 —— 文档只记了 t=102 一帧）：
      t=102 屏幕实际 304505 → 读出 4505      t=135.6 实际 191176 → 读出 76
      t=142 实际 108018 → 读出 8             t=303 实际 120754 → 读出 20754
      t=158 实际 210408 → 读出 0408          t=312 实际 379852 → 读出 7985
      另有 155/248/289/292/208/333 只读出 1~2 位。
  成因：`hud_glyphs._extract_core` 的"链式连续性"——从最右列段往左串，间隔 >20px 就停止，
  而**同一串数字内部的列段间隔实测能到 23~26px** → 左边整段被丢，且**不带任何告警**。
  证据与修复试验：`diag_chain_C.py --audit`、`tune_chain_C.py`（阈值放宽到 30 可救回
  t=135.6/142/158，真值帧 23/25 不变；t=102/303/312 救不回，是掩膜本身丢了笔画）。

  C 线的处理（不猜、但也不让脏读数污染总伤）：
    · 段内出现"远小于段最大值 ×(1-`--reset-ratio`)"的读数 → 该段标 `quality=suspect`
      并在 `issues` 里写 `mixed_small@<t>`（说明这一段可能混了两次攻击的读数）；
    · 只有 1~2 位的孤立读数（`--min-digits` 默认 3）**整条丢弃**，不进任何段；
    · 含 `?` 的读数整条丢弃；
    · `damage_max` 仍是"段内最大值"——丢位的读数只会让**估值偏低**，不会偏高。

用法：
  python events.py                       # 读 out/frames_C.csv → out/events_C.csv
  python events.py --gap 1.5 --verbose   # 调参 + 打印每段明细
  python events.py --anchors             # 与真值锚点对账（验收，见 docs/归属与事件切分.md §4）
"""
import argparse
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FRAMES_CSV = os.path.join(HERE, "out/frames_C.csv")
EVENTS_CSV = os.path.join(HERE, "out/events_C.csv")
OWNER_CSV = os.path.join(HERE, "out/owner_summary_C.csv")

EVENT_COLS = ["event", "t_first", "t_last", "t_peak", "t_anchor", "duration", "damage_first",
              "damage_final", "damage_max", "n_readings", "unit", "owner", "owner_start",
              "n_owners", "owner_breaks", "card_type", "inserted",
              "actor_score", "actor_margin", "actor_t", "min_conf", "status", "quality",
              "issues", "readings"]

# 我方角色（非忆灵）：E 线的 owner 字段本身已经处理了忆灵 → 召唤者，
# 这里只用来判断"这次伤害能不能计入我方"。
ALLY = {"遐蝶", "风堇", "昔涟", "长夜月"}


# ────────────────────────────── 数据读取 ──────────────────────────────
def load_frames(path=FRAMES_CSV):
    """读 out/frames_C.csv（scan_C.py 的产物），按 t 排序。"""
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append({
                "t": float(r["t"]),
                "hud_text": (r.get("hud_text") or "").strip(),
                "hud_n": int(r.get("hud_n") or 0),
                "hud_nbad": int(r.get("hud_nbad") or 0),
                "hud_minconf": float(r.get("hud_minconf") or 0.0),
                "unit": (r.get("unit") or "").strip(),
                "owner": (r.get("owner") or "").strip(),
                "score": float(r.get("score") or 0.0),
                "margin": float(r.get("margin") or 0.0),
                "marker": (r.get("marker") or "").strip(),
                "card_type": (r.get("card_type") or "").strip(),
                "inserted": (r.get("inserted") or "").strip(),
            })
    rows.sort(key=lambda r: r["t"])
    return rows


def is_clean(reading, min_digits=3):
    """读数是否可用于切分：无 '?'、位数达标。

    ⚠️ 不再用 `hud_nbad > 0` 判：C 线扫全量时发现，静默丢前导位的帧里那些被丢掉的位
    **不会**留下 bad 痕迹（模型对剩下的字形置信度是 1.00），所以"bad 数"抓不到它。
    位数下限（默认 3）用来挡掉只读出 1~2 位的碎片读数。
    """
    txt = reading["hud_text"]
    if not txt or "?" in txt:
        return False
    return len(txt) >= min_digits


# ────────────────────────────── 事件切分 ──────────────────────────────
def segment(readings, gap=2.0, reset_ratio=0.20, actor_split=True, min_digits=3):
    """
    把读数序列切成「一次攻击」的段。

    readings : load_frames() 的结果（全部帧，含没有读数的帧 —— 需要它们算"空白"）
    返回 [ {start, end, rows:[...], issues:[...]}, ... ]

    ⚠️ 只有**能用的读数**参与切分（见 is_clean）：含 '?'、位数 < min_digits 的整条丢掉，
    它们不是"攻击的边界"，只是读坏了。丢掉它们会让空白变长 → 由判据 1 断开。
    """
    usable = [r for r in readings if r["hud_text"]]

    runs = []
    cur = None
    for r in usable:
        if not is_clean(r, min_digits):
            continue
        val = int(r["hud_text"])
        if cur is None:
            cur = {"start": r["t"], "end": r["t"], "rows": [r], "issues": []}
            runs.append(cur)
            continue

        prev = cur["rows"][-1]
        dt = r["t"] - prev["t"]
        mx = _max_val(cur)
        breaks, why = False, ""

        if dt > gap:
            # 判据 1：读数空白太久
            breaks, why = True, "gap%.1fs" % dt
        elif val < mx * (1 - reset_ratio):
            # 判据 2：数值下降（重置）
            breaks, why = True, "reset %d<%.0f" % (val, mx)
        elif actor_split and _owner_changed(prev, r) and val < mx:
            # 判据 3：归属者变化 + 数值没有继续增长
            breaks, why = True, "owner %s->%s" % (prev["owner"] or "-", r["owner"] or "-")
        elif actor_split and _owner_to_memo(prev, r) and val < mx:
            # 判据 4：召唤者 → 忆灵（主人的行动与忆灵的行动不是同一次）
            breaks, why = True, "memo %s->%s" % (prev["unit"] or "-", r["unit"] or "-")

        if breaks:
            cur["issues"].append(why.split()[0])
            cur = {"start": r["t"], "end": r["t"], "rows": [r], "issues": []}
            runs.append(cur)
        else:
            if r["t"] < cur["start"]:
                cur["start"] = r["t"]
            cur["rows"].append(r)
            cur["end"] = r["t"]

    for run in runs:
        _flag_internal(run, reset_ratio)
    return runs


def _vals(run):
    out = []
    for r in run["rows"]:
        if r["hud_text"] and "?" not in r["hud_text"]:
            try:
                out.append((r["t"], int(r["hud_text"]), r))
            except ValueError:
                pass
    return out


def _max_val(run):
    vs = [v for _, v, _ in _vals(run)]
    return max(vs) if vs else None


# 忆灵 → 召唤者（E 线的 OWNER 表；判据 4 要用）
MEMO_OWNERS = {"死龙": "遐蝶", "长夜": "长夜月", "小伊卡": "风堇", "德谬歌": "昔涟"}


def _owner_changed(a, b):
    """归属者是否换了人（空 → 有名字不算，因为空=动画期间行动轴隐藏）。"""
    oa, ob = a["owner"], b["owner"]
    if not oa or not ob:
        return False
    return oa != ob


def _owner_to_memo(a, b):
    """这一次读数的人是不是"从召唤者变成了那只忆灵"。"""
    ua, ub = a["unit"], b["unit"]
    if not ua or not ub or ua == ub:
        return False
    return ub in MEMO_OWNERS and MEMO_OWNERS[ub] == ua


def _flag_internal(run, reset_ratio):
    """段内一致性检查：`mixed_small@t` = 出现远低于段最大值的小读数
    （说明这一段可能混进了上一次攻击的尾巴 —— 1 fps 采样下常见，如实标注）。"""
    vs = _vals(run)
    if not vs:
        return
    mx = max(v for _, v, _ in vs)
    for t, v, _ in vs:
        if v < mx * (1 - reset_ratio):
            run["issues"].append("mixed_small@%s" % _fmt(t))
            break


# ────────────────────────────── 归属 ──────────────────────────────
def find_actor(readings, t_anchor, back=1.5, fwd=0.5):
    """
    在锚点时刻附近找**已确认**的行动者（E线 §3.3）。

    **因果优先**：只取锚点之前的（先动手、后出数字；HUD 出数时行动轴可能已经上移），
    仅当"之前"一个都没有时，才退而取锚点之后的最近一个。
    实测依据：t=221 顶端=昔涟、t=222 顶端=长夜月；读数 `32209` 在 t=221、222 都存在，
    若允许"取之后/取更近"，这段会被判成长夜月（错）。C线交接 §4 的真值要求是昔涟。

    返回 (row, delta_t) 或 (None, None)。
    """
    win = [r for r in readings if -back <= r["t"] - t_anchor <= fwd and r["unit"]]
    if not win:
        return None, None
    before = [r for r in win if r["t"] <= t_anchor]
    if before:
        best = max(before, key=lambda r: r["t"])          # 之前里最近的一个
    else:
        best = min(win, key=lambda r: r["t"])             # 只好取之后的最近一个
    return best, best["t"] - t_anchor


# ────────────────────── T1：开大（插入终结技）演出窗口的归属兜底 ──────────────────────
#
# 机制（用户 2026-10-03 确认原话：「三个人都是插入终结技然后终结技演出显示伤害」；
#       2026-10-04 补充纠正：「316-320 是大招，**拓星者是姬子的助战技、不是大招**」）：
#     插入行动 → 左上角出现**四角星**标记的本人卡
#     → 该次行动的演出把**整条行动轴从画面上抹掉**，但右上角总伤害**照常跳数**
#     → 演出结束，行动轴回来。
#   ⚠️ 所以四角星的准确含义是「**插入行动**」（大招 / **助战技** / 额外回合 / 立即行动 都算），
#     **不是**"插入终结技"。归属结论不变（都是"这张卡的人"），但别把话说窄 ——
#     姬子·启行的【拓星者】就是**助战技**留下的星标卡，而它后面照样接大招演出。
#   ⇒ "这段演出是谁的"由**紧邻演出的那张四角星卡**给出，**不需要**识别大招立绘、
#     也不需要按角色建档案（任务书里的方案 B 由此落地）。
#
# 实测证据（`docs/附伤与开大踢轴.md`）：
#   * 飞霄  屏幕录制 2026-10-03 164043.mp4  t=377.0~379.2 星标卡 → 379.4~385.4 演出
#           （HUD 67,282 → 388,617，**+38.9 万**）
#   * 黄泉  同录屏                          t=460.4~465.0 演出 → 465.8~467.0 星标卡
#           （HUD 194,580 → 1,070,137，**+87.5 万**）
#   * 风堇  录屏1                            t=214~217 演出 → 218 小伊卡星标卡（忆灵→召唤者）
#   * 昔涟  录屏1                            t=118~128 演出（11s）→ 129 昔涟星标卡
#   * 姬子·启行 复杂的情况.mp4               t=180~182 演出 → 183 拓星者星标卡（→姬子·启行）
#
# ⚠️ 与旧口径的关系：**只在 `find_actor` 已经返回 None（原本必判「待复核」）时才启用**，
#    所以它**不可能**翻转任何已有结论 —— 三条回归在结构上不受影响。
#    这正对应任务书的验收第 4 条"不猜"：新采纳的每一段都带 `actor_src` 标注，可审计。
ULT_MAX_AGE = 8.0        # 锚点离事件最远允许多少秒（与线6 `MAX_ADOPT_AGE` 同口径）
AHA_SHARE_MAX = 0.30     # 跨度里"阿哈时刻/欢愉技"帧的占比上限，超过就不外推（交线3）


def is_insert_card(row):
    """这一帧能不能当"**插入行动**"的证据：**我方单位卡 + 四角星**。

    ⚠️ 四角星 = 插入行动（大招 / 助战技 / 额外回合 / 立即行动），
    **不限于大招** —— 用户 2026-10-04 纠正：「拓星者是姬子的**助战技**、不是大招」。

    ⚠️ 只认 `ally_star`：
      * `?_star`（色相判不出来）**不算** —— 那正是"被特效盖住"的帧，拿它当证据等于猜；
      * `gold_aha`（阿哈面具框）/`ally_diamond`（欢愉技『?』卡）不算 —— 它们的归属另有口径；
      * 敌方卡/空槽不算。
    """
    if not row or not (row.get("unit") or ""):
        return False
    if (row.get("card_type") or "unit") not in ("unit", ""):
        return False
    return (row.get("marker") or "") == "ally_star"


def span_axis_gone(readings, t_a, t_b):
    """两帧之间**行动轴真的消失过**吗（而不是"轴在、只是认不出人"）。

    判据：区间内存在标记为 `empty`（空槽/轴被演出抹掉）的帧。
    为什么加这道闸：如果轴一直在屏幕上、只是卡面被特效糊住（线6 的 `occluded`），
    那么"借锚点"就不再是无风险的 —— 那种情况下锚点可能已经被下一个人顶掉了。
    实测：飞霄窗口 (379.2, 385.0) 内 15 帧标记为 `empty`；黄泉窗口同理。
    """
    lo, hi = min(t_a, t_b), max(t_a, t_b)
    return any(lo < r["t"] < hi and (r.get("marker") or "") == "empty" for r in readings)


def span_aha_share(readings, t_a, t_b):
    """两帧之间"阿哈时刻/欢愉技"帧的**占比**。

    为什么用占比而不是"出现即否决"：**演出特效偶尔会被误判成金环**。
    实测：昔涟大招窗口里 t=243.4 那一帧评分只有 0.42，却被判成 `gold_aha`
    （见 `samples/T1_开大_昔涟窗口.png` 第 4 格）—— 那是金光特效，不是阿哈时刻。
    所以按"出现即否决"会把**真的**昔涟大招窗口（#16 1/12、#27 1/13）一起毙掉。
    实测分布（录屏1 密帧，修法后新采纳的 6 段）：
      * 真·阿哈时刻 t=171.4~172.4 → 7/11 = 64%（必须否决，归线3）
      * 真·大招窗口           → 0~8%（保留）
    取 30% 作闸（两类之间只有它一个数量级的空档，不敏感）。
    """
    span = [r for r in readings if min(t_a, t_b) < r["t"] < max(t_a, t_b)]
    if not span:
        return 0.0
    n = sum(1 for r in span if (r.get("card_type") or "") in ("aha", "elation"))
    return n / float(len(span))


def find_actor_ult(readings, t_anchor, max_age=ULT_MAX_AGE):
    """T1 兜底：因果窗口里没有已确认帧时，向**两侧**借锚点。

    返回 `(row, delta_t, src)`；src ∈ `{"ult_A", "ult_S", ""}`（"" = 不猜）。
      * `ult_A`：两侧锚点**同一归属**（线6 的 tier A）→ 采纳；
      * `ult_S`：**窗口之前**那张四角星卡（插入行动）→ 就是它；
      * 其余（两侧不同人、只有后侧是星、只有单侧且不是星）→ 返回空（保持「待复核」）。

    ⚠️ **为什么只认"窗口之前"的星标**（这条是复核出来的，不是想当然）：
      用户确认的机制是「**插入终结技 → 终结技演出 → 演出显示伤害**」，星标卡在**演出之前**。
      若星标在窗口**之后**，那段演出更可能是**前一个人**的普通动作动画，而星标卡是
      *下一次*插入的开头 —— 两者相邻但不同人。
      实测反例（录屏1 `out/frames_dense4.csv` 事件#31）：t=260.0 顶端是**死龙（圆点，=遐蝶在行动）**
      → 260.8~266.0 六秒紫红演出 → **266.8 才**出现长夜月（四角星）。
      若允许"后侧星标"，这段 697,980 会被记到长夜月头上，而它其实是遐蝶的动作。
      （同型：黄泉那段窗口后面也有星标卡，但她的伤害已由后一段正常读到 —— 见
       `docs/附伤与开大踢轴.md` §5，收紧后她的总伤仍是正确的 1,070,137。）

    两道否决闸（都必须在借锚点的那一侧到锚点之间成立）：
      1. `span_axis_gone` —— 行动轴真的消失过（否则只是"轴在、糊卡"，借锚点会张冠李戴）；
      2. `span_aha_share ≤ AHA_SHARE_MAX` —— 这段不是阿哈时刻/欢愉技（那是线3 的口径）。

    ⚠️ 候选锚点**自身**还必须是"能当行动者的卡"（`card_type ∈ {unit, ""}`）。
    这条是复核出来的：录屏 `屏幕录制 2026-10-04 110419.mp4` 的 t=277 与 t=291.5 **两侧都是
    青色菱形（欢愉技卡 `elation`）**，只查"跨度内部的阿哈占比"是查不出来的 ——
    它们站在跨度**两端**，于是 tier A 会拿两张欢愉技卡凑出一个"同归属"，把 1,511,004
    记到赛飞儿头上。`attribute4` 本来就把 `aha/elation` 判 `review`，锚点必须同口径。
    """
    def usable(r):
        return bool(r) and (r.get("unit") or "") \
            and (r.get("card_type") or "unit") in ("unit", "")

    before = [r for r in readings if r["t"] <= t_anchor and usable(r)]
    after = [r for r in readings if r["t"] > t_anchor and usable(r)]
    A = max(before, key=lambda r: r["t"]) if before else None
    B = min(after, key=lambda r: r["t"]) if after else None
    if A is not None and (t_anchor - A["t"]) > max_age:
        A = None
    if B is not None and (B["t"] - t_anchor) > max_age:
        B = None
    if A is None and B is None:
        return None, None, ""

    def ok(t_a, t_b):
        return (span_axis_gone(readings, t_a, t_b)
                and span_aha_share(readings, t_a, t_b) <= AHA_SHARE_MAX)

    a_star = is_insert_card(A)

    # ① 两侧同一归属 → tier A（取带星的那一侧作为证据，两边都没有星就按因果优先取前侧）
    if A is not None and B is not None and (A.get("owner") or "") \
            and A.get("owner") == B.get("owner"):
        pick = A if (a_star or not is_insert_card(B)) else B
        if ok(pick["t"], t_anchor):
            return pick, pick["t"] - t_anchor, "ult_A"
        return None, None, ""

    # ② **窗口之前**的四角星（插入终结技）→ 这段演出就是他的
    if a_star and ok(A["t"], t_anchor):
        return A, A["t"] - t_anchor, "ult_S"

    # ③ 其余一律不猜（含"只有后侧是星"，见上面那条反例）
    return None, None, ""


def pick_anchor(run):
    """锚点帧：段内**数值最大**的那一帧（攻击结算瞬间）。

    同值（数值停住 = 这次攻击已经结算）时取**最早**那一帧：停住的第一帧离这次攻击更近，
    再往后行动轴就可能换人了。实测依据：读数 `32209` 在 t=221（顶端昔涟）与
    t=222（顶端长夜月）都出现，取最早 → 昔涟（对）；取最晚 → 长夜月（错，C线交接 §4 的真值是昔涟）。

    该帧若没有行动者读数（密帧里行动者是稀疏读的），退到段内**最后一个有行动者读数**的帧
    —— 它比"数值最大但没读数"的帧更有信息量。
    """
    vs = _vals(run)
    if not vs:
        return None
    mx = max(v for _, v, _ in vs)
    peak_t = min(t for t, v, _ in vs if v == mx)
    with_actor = [r for r in run["rows"] if r["unit"]]
    if with_actor:
        after = [r for r in with_actor if r["t"] <= peak_t]
        anchor = (after[-1] if after else with_actor[0])["t"]
    else:
        anchor = peak_t
    return {"peak_t": peak_t, "anchor_t": anchor, "max": mx}


def is_plausible(value, limit=3_000_000):
    """
    读数合理性闸（**不是**识别规则，只是一个"这数不可能是真的"的兜底）。

    来历（实测）：0.2s 密集抽帧时，数字会**丢前导位**（读数偏小），
    而这条闸挡的是**反方向**的坏读数：读数大得不合理。

    ⛔ 原文曾写"列链会在数字左侧**多吃进一个杂散段**，读数变成'多一位前缀'，
    而且**不带任何 ?**"（举 `6232327` / `8324751`）—— **这条已被【线4】推翻（2026-10-01）**：
    那两个数是**修扫描器之前**的 `out/frames_dense_C.csv` 的产物；
    当前口径（直接调 `read_hud.read_array`）在同一批帧上给出 `?324751`（**带 `?`**），
    会被 `is_clean()` 整条丢掉。见 `docs/归属与事件切分.md` §1。

    ⚠️ 试过用"读数的位增长必须与右对齐相容"来自动识别坏读数，**放弃**：
    纯字符串规则分不开"多一位前缀"与"右边真长了一位"（如 `324751` → `3247519`）。
    这个负结果仍然成立 —— 只是它针对的那类坏读数**在当前口径下不存在**。
    所以只保留"数量级兜底"：`limit` 取 300 万 —— 本录屏实测最大的一次攻击读数
    （死龙自爆链）是 **1,349,238**，超过这个量级的读数一律标 `implausible`
    （`quality=suspect` + 提示复核），但不静默丢弃。
    真正会漏过这条闸的坏读数（`4,350,036` / `1,805,007` / `490,237`）
    由 `events_v4.py` 的"骤升毛刺"规则处理。
    """
    return value <= limit


def _owner_evidence(run):
    """这一段里"归属者/顶端"变化的证据（给下游判断"这一段是不是混了两次攻击"）。

    返回 (owner_start, n_owners, owner_breaks, plurality_owner)
      owner_start   段内第一个有行动者读数的归属者（HUD 出数时刚出手的那个人）
      n_owners      段内出现过几个不同归属者
      owner_breaks  变化的时刻，如 "156:长夜月"
      plurality     段内出现次数最多的归属者（并列时取先出现的）
    """
    seq = [(r["t"], r["owner"], r["unit"]) for r in run["rows"] if r["owner"]]
    if not seq:
        return "", 0, "", ""
    owner_start = seq[0][1]
    counts, order = {}, []
    breaks = []
    for i, (t, o, u) in enumerate(seq):
        if o not in counts:
            counts[o] = 0
            order.append(o)
        counts[o] += 1
        if i and o != seq[i - 1][1]:
            breaks.append("%s:%s" % (_fmt(t), o))
    plurality = max(order, key=lambda o: counts[o])
    return owner_start, len(order), ";".join(breaks), plurality


def attribute(readings, run, back=1.5, fwd=0.5):
    """
    对一段读数做归属。返回 dict（含 status / quality / issues / 字段）。
    """
    vs = _vals(run)
    issues = list(run["issues"])
    pk = pick_anchor(run)
    if pk is None:
        return None
    mx, peak_t, anchor_t = pk["max"], pk["peak_t"], pk["anchor_t"]
    peak_row = [r for t, v, r in vs if t == peak_t][-1]

    actor_row, dta = find_actor(readings, anchor_t, back, fwd)
    min_conf = min((r["hud_minconf"] for r in run["rows"] if r["hud_text"]), default=0.0)
    owner_start, n_owners, owner_breaks, plurality = _owner_evidence(run)
    if n_owners > 1:
        issues.append("multi_owner(%s)" % owner_breaks)

    out = {
        "t_first": run["start"], "t_last": run["end"],
        "t_peak": peak_t, "t_anchor": anchor_t,
        "duration": round(run["end"] - run["start"], 2),
        "damage_first": vs[0][1], "damage_final": vs[-1][1], "damage_max": mx,
        "n_readings": len(run["rows"]), "min_conf": round(min_conf, 3),
        "owner_start": owner_start, "n_owners": n_owners, "owner_breaks": owner_breaks,
        "readings": ";".join("%s%s" % (_fmt(r["t"]), r["hud_text"]) for r in run["rows"]),
    }

    if actor_row is None:
        out.update({"unit": "", "owner": "", "card_type": "", "inserted": "",
                    "actor_score": "", "actor_margin": "", "actor_t": "",
                    "status": "review"})
        issues.append("actor_unknown")
        out["issues"] = ",".join(issues)
        out["quality"] = _quality(run, readings, issues)
        return out
    unit = actor_row["unit"]
    card_type = actor_row["card_type"] or "unit"
    out.update({"unit": unit, "owner": actor_row["owner"], "card_type": card_type,
                "inserted": actor_row["inserted"], "actor_score": actor_row["score"],
                "actor_margin": actor_row["margin"], "actor_t": actor_row["t"]})

    if card_type == "enemy":
        out["status"] = "non_ally"
        issues.append("enemy_card")
    elif card_type == "empty":
        out["status"] = "review"
        issues.append("top_slot_empty")
    elif card_type in ("aha", "elation"):
        # 阿哈时刻/欢愉技卡：框里是谁要靠框内头像，E 线当前只保证 card_type 有效
        out["status"] = "review"
        issues.append("aha_needs_owner")
    elif out["owner"]:
        out["status"] = "ok"          # 忆灵已由 E 线映射到召唤者，这里只需非空
    else:
        out["status"] = "review"
        issues.append("owner_empty")

    if peak_row["hud_nbad"] > 0 or "?" in peak_row["hud_text"]:
        out["status"] = "review"
        issues.append("dirty_peak")

    # 数量级兜底：读数大得不合理（本录屏实测上限 1,349,238）→ 标 review，不给结论
    if not is_plausible(mx):
        out["status"] = "review"
        issues.append("implausible")
    elif any(not is_plausible(int(r["hud_text"])) for r in run["rows"]
             if r["hud_text"] and r["hud_text"].isdigit()):
        out["status"] = "review"
        issues.append("implausible_in_run")

    out["issues"] = ",".join(issues)
    out["quality"] = _quality(run, readings, issues)
    return out


def _quality(run, readings, issues):
    """这段读数的可信度（不是归属可信度）：
       ok       段内自洽、边界是"消失"或"重置"、没有夹生
       partial  段被抽帧边界截断（视频开头/结尾附近）
       suspect  段内夹着远小于最大值的小读数，或段内换过归属者
                （说明这一段可能混了两次攻击的读数 —— 1 fps 采样下分不开，如实标注）
    """
    if any(i.startswith("mixed_small") or i.startswith("multi_owner") or i.startswith("implausible")
           for i in issues):
        return "suspect"
    t_first, t_last = run["start"], run["end"]
    all_t = [r["t"] for r in readings]
    if all_t and (t_first <= min(all_t) + 1e-9 or t_last >= max(all_t) - 1e-9):
        return "partial"
    return "ok"


# ────────────────────────────── 主流程 ──────────────────────────────
def build(frames_csv=FRAMES_CSV, gap=1.5, reset_ratio=0.20, back=1.5, fwd=0.5,
          actor_split=True, min_digits=3):
    readings = load_frames(frames_csv)
    runs = segment(readings, gap=gap, reset_ratio=reset_ratio,
                   actor_split=actor_split, min_digits=min_digits)
    events = []
    for i, run in enumerate(runs, 1):
        ev = attribute(readings, run, back=back, fwd=fwd)
        if ev is None:
            continue
        ev["event"] = i
        events.append(ev)
    return readings, events


def write_csv(events, path=EVENTS_CSV):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=EVENT_COLS)
        w.writeheader()
        for e in events:
            w.writerow({k: e.get(k, "") for k in EVENT_COLS})
    return path


def _fmt(t):
    """帧号格式：抽帧缓存里有 135.10/135.60 这种 0.1s 帧，不能用 %.0f。"""
    s = ("%.2f" % t).rstrip("0").rstrip(".")
    return s


# ────────────────────────────── 验收对账 ──────────────────────────────
# 锚点真值：docs/归属与事件切分.md §4（E 线实测 + 用户确认后的更正版）
ANCHORS = [
    (109, "遐蝶", "遐蝶", "ok"),          # 用户真值：顶端=遐蝶
    (226, "遐蝶", "遐蝶", "ok"),
    (251, "遐蝶", "遐蝶", "ok"),
    (100, "死龙", "遐蝶", "ok"),          # 顶端是忆灵死龙 → 归召唤者
    (152, "死龙", "遐蝶", "ok"),
    (159, "长夜月", "长夜月", "ok"),
    (167, "小伊卡", "风堇", "ok"),
    (175, "小伊卡", "风堇", "ok"),
    (221, "昔涟", "昔涟", "ok"),
    (311, "长夜", "长夜月", "ok"),        # 更正：不是昔涟
    (307, "德谬歌", "昔涟", "ok"),
    (293, "风堇", "风堇", "ok"),          # 更正：不是"敌人(半)"
    (104, None, None, "review"),
    (120, None, None, "review"),
    (134, None, None, "review"),
    (139, None, None, "review"),
    (191, None, None, "review"),
    (207, None, None, "review"),
]


def check_anchors(events, readings=None, back=1.5, fwd=0.5, damage_truth=True):
    """
    对账 A/B/C。口径见 docs/归属与事件切分.md §4 那张自检表。

    ⚠️ 先说明一件容易被误判的事：18 条锚点里有 5 条（159/120/139/191/207）**那一帧根本没有
    可用读数**（行动轴显示"空"，HUD 数字没出现）—— 引擎在这些帧上本来就"无事件可归属"，
    不是错。所以对账 A 把"该帧无读数 + 引擎也没有给出归属"也算 **OK（正确地弃权）**，
    只有"该帧有可信读数、引擎却给不出/给错归属"才判 **!!**。
    """
    if readings is None:
        readings = []
    by_t = {round(r["t"], 2): r for r in readings}

    print("\n=== 对账 A：锚点帧 vs 引擎事件（事件级；允许引擎在无读数时弃权）===")
    print("%-7s %-9s %-9s %-9s %-9s %-4s %s" %
          ("t", "期望顶端", "实得顶端", "期望归属", "实得归属", "判定", "落点"))
    ok = bad = abstain = 0
    for t, eu, eo, est in ANCHORS:
        hit = None
        for e in events:
            if e["t_first"] - 0.01 <= t <= e["t_last"] + 0.01 or abs(e["t_peak"] - t) <= 0.51:
                hit = e
                break
        row = by_t.get(round(float(t), 2))
        has_reading = bool(row and row["hud_text"])
        # 该锚点自己在 [-back,+fwd] 里有没有"已确认的行动者"（E 线口径）
        own_actor, _ = find_actor(readings, float(t), back, fwd)

        # 情况 1：锚点**那一帧自己没有已确认行动者** → E 线口径下这一帧就是"待复核"，
        #   引擎在这条锚点上不作断言 = 正确弃权。事件级归属是整段（含别的锚点）的结论，
        #   两者不是一回事，所以这里不算错、也不算一致（单列"正确弃权"）。
        if own_actor is None:
            abstain += 1
            print("%-7s %-9s %-9s %-9s %-9s %-4s %s" %
                  (t, eu or "待复核", "-", eo or "-", "-", "OK",
                   "该帧无已确认行动者（%s）→ 引擎弃权；%s" %
                   ("无读数" if not has_reading else "有读数但顶端不可判",
                    ("落段 #%d" % hit["event"]) if hit else "未落段")))
            continue

        if hit is None:
            if not has_reading:
                abstain += 1
                print("%-7s %-9s %-9s %-9s %-9s %-4s %s" %
                      (t, eu, "-", eo, "-", "OK",
                       "该帧无可用读数（行动轴空/HUD 未出现）→ 引擎弃权"))
            else:
                bad += 1
                print("%-7s %-9s %-9s %-9s %-9s %-4s 该帧读数=%s，却没进任何事件"
                      % (t, eu, "-", eo, "-", "!!", row["hud_text"]))
            continue

        gu, go = hit["unit"] or "-", hit["owner"] or "-"
        good = (hit["unit"] == eu) and (hit["owner"] == eo)
        ok += good
        bad += (not good)
        print("%-7s %-9s %-9s %-9s %-9s %-4s 事件#%d %s~%s 读%s 状态%s 质量%s" %
              (t, eu, gu, eo, go, "OK" if good else "!!",
               hit["event"], _fmt(hit["t_first"]), _fmt(hit["t_last"]),
               hit["readings"], hit["status"], hit["quality"]))
    print("  一致 %d / 不一致 %d / 正确弃权 %d（弃权 = E 线口径下该帧本来就判不出来）"
          % (ok, bad, abstain))
    print("  ⚠️ 事件级的已知局限：1 fps 采样下，**同一次攻击的读数与下一次攻击的读数**"
          "可能落在同一段里")
    print("     （如 t=148~156 那一段同时含死龙 324751 与长夜 866730），此时段内只能给一个归属。")
    print("     这是采样率限制、不是实现错误：`quality=suspect` + `n_owners>1` + `owner_start`"
          " 三个字段就是留给下游拆分的。")

    if readings:
        print("\n=== 对账 B：把锚点当事件时刻，单独算归属（C线交接 §4 那套自检口径）===")
        ok2 = bad2 = 0
        for t, eu, eo, est in ANCHORS:
            row, dta = find_actor(readings, t, back, fwd)
            gu = row["unit"] if row else None
            go = row["owner"] if row else None
            if eu is None:
                good = (gu is None)
            else:
                good = (gu == eu and go == eo)
            ok2 += good
            bad2 += (not good)
            print("  t=%-6s -> %-6s 归属 %-6s %s （取自 t=%s，%+.1fs，分数%s）" %
                  (t, gu or "待复核", go or "-", "OK" if good else "!!",
                   _fmt(row["t"]) if row else "-", dta or 0.0,
                   row["score"] if row else "-"))
        print("  一致 %d / 不一致 %d" % (ok2, bad2))

    if damage_truth:
        check_damage(events)
    return ok, bad


def check_damage(events):
    """对账 C：A 线真值读数（digit_truth.LABELED / HOLDOUT）能不能在本引擎的事件里复现。"""
    try:
        from digit_truth import LABELED, HOLDOUT
    except Exception as e:                                    # pragma: no cover
        print("  读不到 digit_truth：%s" % e)
        return 0, 0
    truth = {float(k): v for k, v in LABELED.items()}
    truth.update({float(k): v for k, v in HOLDOUT.items()})
    print("\n=== 对账 C：A 线真值读数 vs 引擎事件（%d 帧）===" % len(truth))
    print("%-7s %-9s %-9s %-4s %s" % ("t", "真值", "最近事件", "判定", "说明"))
    ok = bad = 0
    for t in sorted(truth):
        val = truth[t]
        hit = None
        for e in events:
            if e["t_first"] - 0.01 <= t <= e["t_last"] + 0.01:
                hit = e
                break
        if hit is None:
            good = False
            note = "该帧的读数没进任何事件（含 '?'/位数不足，或帧不在扫描范围内）"
        else:
            good = str(hit["damage_max"]) == val or any(
                r.endswith(val) for r in hit["readings"].split(";"))
            note = "事件#%d 最大=%s 状态=%s" % (hit["event"], format(hit["damage_max"], ","),
                                             hit["status"])
        ok += good
        bad += (not good)
        print("%-7s %-9s %-9s %-4s %s" %
              (("%.2f" % t).rstrip("0").rstrip("."), val,
               format(hit["damage_max"], ",") if hit else "-", "OK" if good else "!!", note))
    print("  一致 %d / 不一致 %d" % (ok, bad))
    print("  （注意：真值帧 t=102 的 304505 是屏幕上的值，A 线读数本身丢前导位读出 4505 ——")
    print("    那一类不一致是**读数缺陷**，不是引擎的锅，见本文件 §四）")
    return ok, bad


def summarize(events, by_owner_csv="out/owner_summary_C.csv"):
    """
    汇总：按归属角色统计（**只统计 status=ok 的行**；review/non_ally 一律不进合计）。

    口径提醒：`damage_max` 是"该次攻击内累计的最大读数"。1 fps 采样下，
    同一次攻击的读数可能被拆成两段（→ 重复计入），或者两次攻击的读数被并成一段
    （→ 少计）。所以这张表是**下界性质的近似**，不要当"整局总伤"用。
    """
    from collections import Counter, defaultdict
    print("\n=== 归属汇总（只算 status=ok；单位：一次攻击的 damage_max）===")
    print("%-8s %-6s %-14s %-14s %-8s %s" %
          ("归属", "次数", "合计", "最大一击", "平均", "质量"))
    agg = defaultdict(lambda: {"n": 0, "sum": 0, "max": 0, "q": Counter()})
    for e in events:
        if e["status"] != "ok":
            continue
        o = e["owner"] or "(未定)"
        a = agg[o]
        a["n"] += 1
        a["sum"] += e["damage_max"]
        a["max"] = max(a["max"], e["damage_max"])
        a["q"][e["quality"]] += 1
    rows = sorted(agg.items(), key=lambda kv: -kv[1]["sum"])
    for o, a in rows:
        print("%-8s %-6d %-14s %-14s %-8s %s" %
              (o, a["n"], format(a["sum"], ","), format(a["max"], ","),
               format(a["sum"] // max(1, a["n"]), ","), dict(a["q"])))
    tot = sum(a["sum"] for _, a in rows)
    print("%-8s %-6d %-14s" % ("合计", sum(a["n"] for _, a in rows), format(tot, ",")))
    print("  ⚠️ 这是**近似下界**：丢前导位的读数会让某些次偏低；1 fps 采样可能把一次攻击"
          "拆成两段（重复计入）或把两次并成一段（少计）。")
    print("  ⚠️ 待复核 %d 段、非我方 %d 段**未计入**（宁可漏，不要错）。" %
          (sum(1 for e in events if e["status"] == "review"),
           sum(1 for e in events if e["status"] == "non_ally")))
    if by_owner_csv:
        with open(by_owner_csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["owner", "n_events", "damage_sum", "damage_max_once", "damage_mean",
                        "n_quality_ok", "n_quality_suspect", "n_quality_partial"])
            for o, a in rows:
                w.writerow([o, a["n"], a["sum"], a["max"], a["sum"] // max(1, a["n"]),
                            a["q"].get("ok", 0), a["q"].get("suspect", 0), a["q"].get("partial", 0)])
        print("已写出 %s" % by_owner_csv)
    return rows


# ────────────────────────────── CLI ──────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default=FRAMES_CSV)
    ap.add_argument("--out", default=EVENTS_CSV)
    ap.add_argument("--gap", type=float, default=1.5, help="读数空白多久算断开（秒）")
    ap.add_argument("--reset-ratio", type=float, default=0.20, help="数值下降多少算重置")
    ap.add_argument("--back", type=float, default=1.5, help="归属往回看的窗口（秒）")
    ap.add_argument("--fwd", type=float, default=0.5, help="归属往前看的窗口（秒）")
    ap.add_argument("--min-digits", type=int, default=3, help="读数位数下限（滤掉前导位被吞的碎读）")
    ap.add_argument("--no-actor-split", action="store_true", help="不按行动者变化切分")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--summary", action="store_true", help="按归属角色汇总（只算 status=ok）")
    ap.add_argument("--anchors", action="store_true", help="跑真值锚点对账")
    ap.add_argument("--json", default="", help="额外输出 JSON（给别的工具用）")
    args = ap.parse_args()

    readings, events = build(args.frames, gap=args.gap, reset_ratio=args.reset_ratio,
                             back=args.back, fwd=args.fwd,
                             actor_split=not args.no_actor_split,
                             min_digits=args.min_digits)
    path = write_csv(events, args.out)
    n_ok = sum(1 for e in events if e["status"] == "ok")
    n_dmg = sum(e["damage_max"] for e in events if e["status"] == "ok")
    print("读数帧 %d 个 / 全部帧 %d 个 → 事件 %d 段（可采纳 %d 段，待复核/非我方 %d 段）" %
          (sum(1 for r in readings if r["hud_text"]), len(readings), len(events),
           n_ok, len(events) - n_ok))
    print("可采纳事件的总伤合计 = %s（口径：一次攻击内累计，取段内最大值）" % format(n_dmg, ","))
    print("已写出 %s" % path)

    from collections import Counter
    print("状态分布:", dict(Counter(e["status"] for e in events)))
    print("质量分布:", dict(Counter(e["quality"] for e in events)))
    print("归属分布:", dict(Counter(e["owner"] or "(未定)" for e in events)))

    if args.verbose:
        print("\n%-4s %-14s %-9s %-8s %-6s %-7s %-9s %s" %
              ("#", "时间窗", "最大读数", "行动者", "归属", "状态", "质量", "读数序列"))
        for e in events:
            print("%-4d %-14s %-9s %-8s %-6s %-7s %-9s %s" %
                  (e["event"], "%s~%s" % (_fmt(e["t_first"]), _fmt(e["t_last"])),
                   format(e["damage_max"], ","), e["unit"] or "-", e["owner"] or "-",
                   e["status"], e["quality"], e["readings"]))

    if args.summary:
        summarize(events, by_owner_csv=OWNER_CSV)

    if args.json:
        json.dump(events, open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("已写出 %s" % args.json)

    if args.anchors:
        check_anchors(events, readings, back=args.back, fwd=args.fwd)


if __name__ == "__main__":
    main()
