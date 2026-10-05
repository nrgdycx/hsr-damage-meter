# -*- coding: utf-8 -*-
"""
[线4] 事件表时间分辨率 —— 「密帧 + 两侧锚点校验」的归属引擎。

════════════════════════════════════════════════════════════════════════
0. 这条线要解决什么（以及原计划里哪个前提是错的）
════════════════════════════════════════════════════════════════════════
`docs/项目项目总交接` 的【线4】任务是：C 线的事件表用 1 fps 网格，有些"一次攻击"会与相邻的
合并/拆分；要求**密集采样 + 用两侧稳定的 1 fps 读数做锚点校验**，把"多一位前缀"的过渡帧
识别出来丢弃，把事件切分做得更细。

⚠️ **先纠正一个前提**（本文档的实测结论，证据在 §1）：
C 线交付 §3.2 说"0.2s 密帧会**静默多读一位**（`324751`→`8324751`）且**不带 `?`**" ——
那是拿**修扫描器之前**的产物（`out/frames_dense_C.csv`）得出的结论。
用**当前**口径（`scan_C2.py` 直接调 `read_hud.read_array`）重扫同一批帧，
那些"多一位前缀"的帧**全部带 `?`**（`?324751`、`?40185`、`?248752`），
C 线的 `is_clean()` 本来就会把它们整条丢掉。→ 密帧**并不会**静默多读一位。

**密帧真正的危险是相反的：丢前导位（读数偏小）**，而且它同时存在于 1 fps 网格上
（C 线 §4 已记录 t=102/158/303/312 等），表现为：
  · 读数变成上一次攻击的**碎片**（`0408` / `349238` / `20754` / `24403` …）
    → 看起来像"数值下降 = 新一次攻击"，于是**凭空造出一条假事件**，
      而且 `status=ok`、伤害值荒谬地小（408 / 280 / 670 / 24403 …）；
  · 或者同一次攻击被拆成两段。

本引擎的做法（**只做有证据的事**）：
  ① 把每条读数分级：`absent`（HUD 真不存在）/ `flagged`（带 `?` 或位数不足）/
     `raw`（干净读数）；
  ② 对 `raw` 再做两道**客观**剔除（§3）：
       · **R1 碎片**：读数是 ±1.5s 内另一条更长读数的**真子串**，且两者之间 HUD 没长时间消失
         （`0408 ⊂ 210408`、`349238 ⊂ 1349238`、`20754 ⊂ 120754` …）；
       · **R2 毛刺**：读数与**两侧非碎片邻居**都严重不连续（骤降 / 骤升），
         且它自己**没有形成 ≥0.4s 的稳定平台**（真攻击开始后会停住，毛刺不会）；
     被剔除的读数**不参与数值、也不触发"重置"切分**，但记录在 `rejected` 列里可审计；
  ③ 在**可信读数**上切分（判据沿用 C 线 §3.1：空白 ≥1.5s / 数值下降 / 归属者变化 /
     召唤者→忆灵），但**空白判据的时长按密帧的 0.2s 网格重新标定**（§4.2）；
  ④ 归属沿用 E 线口径，但锚点改为**"取段内最大值所在、且有已确认行动者的最早一帧"**
     （比 C 线"先取最早的峰值帧、再回退到它之前最后一帧有行动者的帧"更贴合"数字结算那一刻谁在顶轴"，
      见 §5）。

════════════════════════════════════════════════════════════════════════
1. 为什么可以信任密帧（复现命令）
════════════════════════════════════════════════════════════════════════
  python -u scan_C2.py --dir frames/glyphcache --range 98,340 --step 0 \
         --out out/frames_dense4.csv --actor-every 1        # 923 帧，当前口径
  python -u diag_dense_4.py --frames out/frames_dense4.csv --grid out/frames_C.csv
    → "共同整数秒帧 240 个：读数相同 240，不同 0"
      即密帧表与 1 fps 表**在整数秒上逐帧同源**（旧表是 122 个共同时刻里 5 个不同）。

════════════════════════════════════════════════════════════════════════
2. 密帧的三种"HUD 不在场"
════════════════════════════════════════════════════════════════════════
  · `hud_n == 0`（真空白）：**最强**的边界证据 —— 攻击结束、HUD 被清掉。密帧能把
    "空白有多长"从这个录屏的 1.0s 粒度压到 0.2s 粒度（实测空段时长谱：0.0/0.2/0.3/0.4/0.6/0.8/1.0/…）。
  · `flagged`（有字形但读数不可信）：**HUD 在场**，只是这一帧读不准 → 不能当空白用。
  · `raw` 里的碎片/毛刺：**HUD 在场且显示的是别的东西**（上一次攻击的大数）→ 更不能当边界。

════════════════════════════════════════════════════════════════════════
3. 剔除规则的确切定义（都可关：`--no-reject` 用于对照实验）
════════════════════════════════════════════════════════════════════════
R1 **碎片**（substring）：raw 帧 i 与 raw 帧 j，若
     · |t_i − t_j| ≤ `--frag-win`（默认 1.5s），
     · `text_i` 是 `text_j` 的**真子串**（j 的位数更多），
     · i 与 j 之间**最长连续空白 < `--frag-absent`**（默认 0.8s，即 HUD 没有真正清屏），
   则 i 是碎片。
   实测命中：`0408⊂210408`(t=158)、`809⊂2809`(162.8)、`280⊂2809`(163)、`670⊂27670`(179)、
   `349238⊂1349238`(278)、`24403⊂124403`(297)、`20754⊂120754`(303)、`25684/125684⊂1125684`(324)、
   `9195⊂319195`(197.2)、`2096⊂662096`(105.2)、`0318⊂290318`(248.6)、`55900/25590⊂255900`(241)、
   `6054⊂60542`(250.6)、`667⊂77667`(244.6)、`059/5059⊂225059`(245.6/246.4)、`3183/857/5857⊂…`(176/183)…

R2 **毛刺**（glitch）：raw 帧 i（未被 R1 剔除），令
     L = 之前最近的**非碎片** raw 帧（|Δt| ≤ `--glitch-win`，默认 0.6s，且中间无空白）
     R = 之后最近的**非碎片** raw 帧（同上）
     · 两者都有，且 `v_i < min(v_L,v_R) × (1−reset_ratio)` → **骤降**；
     · 两者都有，且 `v_i > max(v_L,v_R) × --spike-ratio`（默认 4.0）→ **骤升**；
     · 且 **i 所在的"同值连续块"长度 < `--min-plateau`（默认 3）**
       —— 真攻击的读数会停住（≥0.4s 同值），毛刺不会；这一条用来保护"小数值的真攻击"
       （t=106 的 `2809` 会连着 3 帧以上，而 t=324 的 `25686` 只在 1~2 帧上跳）。
   实测命中：`4350036`(258.2)、`1805007`(271.4)、`490237`(314.8)、`89490`(317.4)、
   `9602`(259.2)、`1471`(149.6)、`00773`(99.4)、`07808`(99.8)、`494`(134.3)、`5492`(101.8)、
   `00633`(271.8)、`11684`(324.0)、`25686`(325.2)、`7985`(312.0)…

════════════════════════════════════════════════════════════════════════
4. 切分判据（在**可信**读数上）
════════════════════════════════════════════════════════════════════════
4.1 时间密度是**混合**的：`frames/glyphcache/` 里只有 10 个窗口是 0.2s 密帧
    （98-112 / 130-142 / 146-166 / 170-184 / 190-200 / 216-230 / 238-254 / 255-280 /
      283-313 / 314-326），窗口外只有 1 fps 帧。所以本引擎**不做"密帧专用"的常数假设**，
    空白判据用**两侧读数的时间差** `dt`，并按下面重新标定。
4.2 `dt` 分布（可信读数，全部 923 帧）：
      · 密帧窗口内同一次攻击的相邻读数 = **0.2s**（碎片被剔除后会出现 0.4~0.8s 的跳）
      · 跨窗口 / 1 fps 网格 = **1.0s**
      · 实测"同一次攻击内部也有 HUD 眨眼"：`150.2~150.4`（0.4s）、`246.6~247.2`（0.6s）
        —— 但后者之后数值**下降**了（225059→125698），所以靠判据 4.4 断开，不靠空白。
      ⇒ `--gap`（硬空白）保持 C 线的 **1.5s**（这是"肯定换了一次攻击"的量级，
        且保护了 C 线已经切开的 t=172→174.6 那类 2.6s 空白）；
        0.4~1.5s 的空白**不单独构成边界**，要配合数值判据。
4.3 数值判据：新读数 < 段内最大可信值 × (1−`--reset-ratio`20%) → 断（重置）。
4.4 归属者变化 + 数值没有继续增长 → 断；召唤者→忆灵同理（沿用 C 线，未改口径）。

════════════════════════════════════════════════════════════════════════
5. 锚点（`pick_anchor4`）与 C 线的差别
════════════════════════════════════════════════════════════════════════
C 线：`peak_t` = 段内最大值**最早**出现的那一帧；再退到 `peak_t` 之前**最后一个**有行动者的帧。
本引擎：在**"可信读数等于段最大值"**的帧里，取**最早的有已确认行动者**的那一帧。
差别只在"最大值横跨一段平台"时体现：
  · 读数 `866730` 的平台是 t=154.4~156.0，而 t=154.4~155.4 顶端是**读不出来的**
    （E 线分数 <0.9），最新能确认"长夜/长夜月"的帧是 155.6。
    C 线口径（1 fps 下 866730 只出现在 156.0）取到 156.0 → 对；
    若把 C 线口径直接用在本引擎的密帧平台上，`peak_t` 会变成 154.4 → 会借到 151.4 的**死龙**
    → **归属错**。新口径取"最大值帧里有行动者的最早一帧" = 155.6 → 长夜月 → 对。
  · 读数 `32209` 的平台是 t=221.0~222.2，顶端在 221.0~221.2 是**昔涟**、
    221.8 以后是**长夜月**（C线交接 §4 的真值是昔涟）。新口径取最早的 221.0 → 昔涟 → 对。
 两个方向都能兼顾，这是新口径的实测依据。

用法：
  python -u events_v4.py                                   # 读 out/frames_dense4.csv → out/events_dense4.csv
  python -u events_v4.py --anchors --truth --compare --summary
  python -u events_v4.py --no-reject --compare              # 关掉剔除（对照：证明剔除是必要的）
  python -u events_v4.py --verbose                          # 逐段明细
"""
import argparse
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import events as C  # noqa: E402  复用 find_actor / ANCHORS / ALLY / _fmt

FRAMES = os.path.join(HERE, "out/frames_dense4.csv")
EVENTS = os.path.join(HERE, "out/events_dense4.csv")
EVENTS_C = os.path.join(HERE, "out/events_C.csv")
OWNER_CSV = os.path.join(HERE, "out/owner_summary_dense4.csv")

# 在 C 线的字段基础上**只增不改**，下游按 C 的列名读依然可用
EVENT_COLS = C.EVENT_COLS + [
    "actor_src",        # T1：行动者的来源 —— `read`(直接读到) / `ult_S`(借演出侧的四角星卡)
                        #     / `ult_A`(借两侧同归属锚点) / ""(没借到=待复核)
    "t_res",            # 该段的边界分辨率：0.2s（段内/段边有密帧）/ 1s
    "n_frames",         # 落在段时间窗里的全部帧数（含被剔除/空白的帧）
    "n_trusted",        # 参与取值/切分的可信读数条数
    "n_rejected",       # 被剔除的读数条数
    "reject_kinds",     # 被剔除的原因统计，如 "frag:sub:158=0408⊂210408; glitch:dip:324.0=11684"
    "rejected",         # 被剔除的读数原文（可审计）
    "t_trusted_span",   # 可信读数的时间跨度
    "pairs",            # 可信读数的机器可读形式 "t:text|t:text|…"（严格验收用，避免 t+text 拼接歧义）
    "split_candidates", # 段内被"证据不足"压下来的疑似边界（不冒充结论）
]

ALLY = C.ALLY
MIN_DIGITS = 3


# ────────────────────────────── 载入 / 分级 ──────────────────────────────
def load(path=FRAMES):
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                t = float(r["t"])
            except (TypeError, ValueError):
                continue
            rows.append({
                "t": t,
                "text": (r.get("hud_text") or "").strip(),
                "n": int(r.get("hud_n") or 0),
                "conf": float(r.get("hud_minconf") or 0.0),
                "unit": (r.get("unit") or "").strip(),
                "owner": (r.get("owner") or "").strip(),
                "score": float(r.get("score") or 0.0),
                "margin": float(r.get("margin") or 0.0),
                "marker": (r.get("marker") or "").strip(),
                "inserted": (r.get("inserted") or "").strip(),
                "card_type": (r.get("card_type") or "").strip(),
                "grade": "",        # absent / flagged / raw
                "reject": "",       # 空 = 可信；否则是剔除原因
            })
    rows.sort(key=lambda r: r["t"])
    return rows


def classify(rows, min_digits=MIN_DIGITS):
    """三分类。⚠️ `flagged` ≠ 空白：HUD 在场，只是这一帧读不准。"""
    for r in rows:
        if r["n"] == 0 and not r["text"]:
            r["grade"] = "absent"
        elif not r["text"] or "?" in r["text"] or len(r["text"]) < min_digits:
            r["grade"] = "flagged"
        else:
            r["grade"] = "raw"
    return rows


def value(r):
    """可信值：raw 且未被剔除。其余一律 None（不参与取值、也不触发重置切分）。"""
    if r["grade"] != "raw" or r["reject"]:
        return None
    try:
        return int(r["text"])
    except ValueError:
        return None


def absent_run(rows):
    """每帧所属的"连续空白块"长度（秒，用跨度算）。

    返回 list，与 rows 等长：[块内起始索引, 块内结束索引, 跨度秒] 或 None。
    """
    info = [None] * len(rows)
    i = 0
    while i < len(rows):
        if rows[i]["grade"] == "absent":
            j = i
            while j + 1 < len(rows) and rows[j + 1]["grade"] == "absent":
                j += 1
            span = rows[j]["t"] - rows[i]["t"]
            for k in range(i, j + 1):
                info[k] = (i, j, span)
            i = j + 1
        else:
            i += 1
    return info


def max_absent_between(rows, absent, i, j):
    """rows[i] 与 rows[j] 之间（不含两端）最长连续空白块的跨度。"""
    a, b = (i, j) if i < j else (j, i)
    best = 0.0
    k = a + 1
    while k < b:
        info = absent[k]
        if info is not None:
            best = max(best, info[2])
            k = info[1] + 1
        else:
            k += 1
    return best


def same_block(rows, i, max_dt=1.05):
    """i 所在的"同值连续块"：连续行、文本相同、相邻间隔 ≤ max_dt。返回长度。"""
    a, b = block_range(rows, i, max_dt)
    return b - a + 1


def block_range(rows, i, max_dt=1.05):
    txt = rows[i]["text"]
    a = i
    while a - 1 >= 0 and rows[a - 1]["text"] == txt and rows[a]["t"] - rows[a - 1]["t"] <= max_dt:
        a -= 1
    b = i
    while (b + 1 < len(rows) and rows[b + 1]["text"] == txt
           and rows[b + 1]["t"] - rows[b]["t"] <= max_dt):
        b += 1
    return a, b


def value_run_window(rows, i, back=0.2, fwd=0.8):
    """r 的值在 [t−back, t+fwd] 里出现了几帧（**不含 ABSENT 帧**；flagged 帧允许穿过 ——
    密帧实测一个稳定值中间会夹 1~2 帧读数坏掉的帧，如 `866730` 在 154.8/155.0 是 `0?`）。

    ⚠️ 不能用 `same_block()` 来代替：`same_block` 要求"逐帧连续同值"，
    而 154.4~156.0 那个 `866730` 平台被 154.8/155.0 两帧 `0?` 切成了 2+6，
    真正"结算住"的那个 6 帧平台反而读不到 r=154.4 这一帧。两种语义各有用处：
      · `same_block`  → 毛刺判据（要求"逐帧停住"，严）
      · 本函数        → 判据 5（要求"这个值在这个窗口里反复出现且没清过屏"，稍宽）
    """
    return len(value_partners(rows, i, back, fwd))


def value_partners(rows, i, back=0.2, fwd=1.6, max_absent=0.6):
    """与 rows[i] 同值、且在 [t−back, t+fwd] 内、中间没有 ≥max_absent 的空白的帧。"""
    t, txt = rows[i]["t"], rows[i]["text"]
    out, cum, k = [], 0.0, i
    # 向前
    k = i
    while k - 1 >= 0 and rows[i]["t"] - rows[k - 1]["t"] <= back + 1e-9:
        k -= 1
        if rows[k]["text"] == txt and rows[k]["grade"] != "absent":
            out.append(rows[k])
    # 向后
    k = i
    while k + 1 < len(rows) and rows[k + 1]["t"] - rows[i]["t"] <= fwd + 1e-9:
        if rows[k + 1]["grade"] == "absent":
            cum += rows[k + 1]["t"] - rows[k]["t"]
            if cum >= max_absent:
                break
        else:
            if rows[k + 1]["text"] == txt:
                out.append(rows[k + 1])
        k += 1
    return out


def unique_owner(rows_):
    """一组帧里**唯一**的已确认归属者；0 个或 ≥2 个都返回 None（="说不清"）。"""
    os_ = {r["owner"] for r in rows_ if r["owner"]}
    return os_.pop() if len(os_) == 1 else None


def owner_with_support(rows_, min_support=2):
    """唯一、且**至少 min_support 帧**都确认过的归属者。

    为什么要"支撑帧数"：E 线在动画期间会偶发单帧误判。实测 t=197.8~199.0 的 `674271`
    平台里只有 t=199.0 一帧报了"风堇"（其余帧 action 轴读不出来），
    如果拿它当"这次攻击换人了"，判据 5 就会把死龙自爆链 `319195 → 674271`
    误切成两段，`674271` 的归属还会从遐蝶变成风堇。要求 ≥2 帧就把这一条挡住了
    （真正的换人如 t=154.4 的 `866730` → 长夜/长夜月 有 155.6/155.8/156.0 三帧）。
    """
    counts = {}
    for r in rows_:
        if r["owner"]:
            counts[r["owner"]] = counts.get(r["owner"], 0) + 1
    if len(counts) != 1:
        return None
    o, n = next(iter(counts.items()))
    return o if n >= min_support else None


def block_rows(rows, i, max_dt=1.05):
    """i 所在的"同值连续块"的帧（逐帧同值且相邻间隔 ≤ max_dt）。"""
    a, b = block_range(rows, i, max_dt)
    return rows[a:b + 1]


# ────────────────────────────── 剔除 ──────────────────────────────
def mark_rejects(rows, frag_win=1.5, frag_absent=0.8, glitch_win=0.6, reset_ratio=0.20,
                 spike_ratio=4.0, min_plateau=3, flicker_win=1.5, glitch_absent=0.6):
    """R1 碎片 + R2 毛刺 + R3 闪回。就地写 `reject` 字段，返回统计。

    `glitch_absent`：毛刺判据的护栏时长。两侧邻居之间**只有短空白（< 0.6s）**时仍然判毛刺
    —— 实测 t=314.8 的 `490237`（骤升 8.6 倍）后面紧跟的 t=315.0 是空帧，
    早期版本用"中间只要有任何空白就跳过"的护栏，把这条坏读数放了过去，
    结果它单独成了一段、还是 `status=ok`。
    """
    absent = absent_run(rows)
    raw = [i for i, r in enumerate(rows) if r["grade"] == "raw"]
    stat = {"sub": 0, "small": 0, "dip": 0, "spike": 0, "flicker": 0}

    # ── R3 闪回（flicker）：一个"刚才出现过的大值"闪一下又掉下去 ──
    # 来历（实测）：t=218.8~219.2 屏上 `157333`（小伊卡），t=219.8~220.2 屏上 `57333`（昔涟，
    # 是新的一次攻击），t=220.4 又读到 `157333` 然后 220.6 掉到 `17986`。
    # 那个 220.4 的 `157333` 既不是碎片（不是子串）、也不满足毛刺（4 倍阈值内），
    # 但它是**已经消失过的旧值**，会把它后面的小数值段吞掉。
    # 判据：值 = 之前 `flicker_win` 内出现过、现在又出现；紧跟着的可信读数**掉下去**；
    #       且它自己没停住（同值帧数 < min_plateau）。
    # ⚠️ 必须**先跑 R3 再跑 R1**：`220.4` 那个闪回值 `157333` 本身也是 `57333` 的容器，
    #    如果它还留在候选里，R1 会把 `57333` 误判成它的丢位碎片（实测踩过）。
    for pos, i in enumerate(raw):
        if rows[i]["reject"]:
            continue
        later = [k for k in raw[pos + 1:] if rows[k]["t"] - rows[i]["t"] <= glitch_win]
        if not later:
            continue
        nxt = rows[later[0]]
        if int(nxt["text"]) >= int(rows[i]["text"]) * (1 - reset_ratio):
            continue                           # 后面没有掉下去 → 不是闪回
        if max_absent_between(rows, absent, i, later[0]) > 0:
            continue
        if same_block(rows, i) >= min_plateau:
            continue
        earlier = [k for k in raw[:pos]
                   if 0 < rows[i]["t"] - rows[k]["t"] <= flicker_win
                   and rows[k]["text"] == rows[i]["text"] and not rows[k]["reject"]]
        if not earlier:
            continue
        # 必须是"值消失过又回来"：两次出现之间要有**别的**可信读数。
        # ⚠️ 三条都不能少（都踩过）：
        #    · 中间那条必须是 `raw`（空帧/带 '?' 的帧不算"画面变过"，
        #      否则 `674271`@198.6→199.0、`379852`@311.4→311.8 这种被空帧隔开的平台会被误杀）；
        #    · 值必须真的不同；
        #    · 中间那个值不能是**本值自己的丢位残片**（`857 ⊂ 225857`，
        #      否则 `225857`@183.0→183.4 会被误杀）。
        if not any(rows[k]["grade"] == "raw" and not rows[k]["reject"]
                   and rows[k]["text"] != rows[i]["text"]
                   and not (rows[k]["text"] in rows[i]["text"] and same_block(rows, k) < 2)
                   for k in range(earlier[-1] + 1, i)):
            continue
        rows[i]["reject"] = "glitch:flicker %s 复现@%s（首次 %s）" % (
            rows[i]["text"], C._fmt(rows[i]["t"]), C._fmt(rows[earlier[-1]]["t"]))
        stat["flicker"] += 1

    # ── R1a 子串碎片（先跑：它能把 `4505⊂304505` 这种"假小值"先清掉，
    #              后面 R2 的邻居才不会被它带偏）──
    # ⚠️ 容器 j 必须是**未被剔除**的读数。
    for i in raw:
        if rows[i]["reject"]:
            continue
        ti, vi = rows[i]["t"], rows[i]["text"]
        for j in raw:
            if i == j or rows[j]["reject"]:
                continue
            tj, vj = rows[j]["t"], rows[j]["text"]
            if abs(tj - ti) > frag_win or len(vj) <= len(vi):
                continue
            if max_absent_between(rows, absent, i, j) >= frag_absent:
                continue                       # 中间 HUD 清过屏 → 是两次攻击，不是碎片
            if vi not in vj:                   # 真子串（保留前导 0，所以比字符串不比数值）
                continue
            # 护栏（实测必需）：丢位是**同一次攻击内**发生的事，两侧的行动者要么相同、
            # 要么读不出来。若两侧各自都有唯一的已确认归属者、而且**不是同一个人**，
            # 那就是两次攻击的巧合（实测：小伊卡 `157333` 之后的昔涟 `57333`
            # 恰好是它的子串，不加这条护栏就会把 C 线 #26 那次真攻击吃掉）。
            fo = unique_owner(block_rows(rows, i))
            co = unique_owner(block_rows(rows, j))
            if fo and co and fo != co:
                continue
            rows[i]["reject"] = "frag:sub %s⊂%s@%s" % (vi, vj, C._fmt(tj))
            stat["sub"] += 1
            break

    # ── R2 毛刺：邻居只看"当前还没被剔除"的 raw 帧 ──
    # ⚠️ **必须分两遍**：先判骤降、刷新候选，再判骤升。
    #    实测教训：`t=99.4 00773` / `t=99.8 07808` 是两条骤降毛刺，
    #    如果骤升判据和骤降判据在同一遍里跑，`t=99.6 87391`（真正的滚动值）
    #    会因为邻居是那两条坏读数而被判成"骤升" —— 一次误杀一个真读数。
    for mode in ("dip", "spike"):
        good = [i for i, r in enumerate(rows) if r["grade"] == "raw" and not r["reject"]]
        for pos, i in enumerate(good):
            if rows[i]["reject"]:
                continue
            L = good[pos - 1] if pos > 0 else None
            R = good[pos + 1] if pos + 1 < len(good) else None
            if L is None or R is None:
                continue
            if rows[i]["t"] - rows[L]["t"] > glitch_win or rows[R]["t"] - rows[i]["t"] > glitch_win:
                continue
            if max_absent_between(rows, absent, L, i) >= glitch_absent or \
                    max_absent_between(rows, absent, i, R) >= glitch_absent:
                continue                       # 中间真清过屏 → 可能是真的新攻击，不判毛刺
            v = int(rows[i]["text"])
            vL, vR = int(rows[L]["text"]), int(rows[R]["text"])
            if same_block(rows, i) >= min_plateau:
                continue                       # 自己停住了 → 是小数值的真攻击（如 t=106 的 2809）
            if mode == "dip" and v < min(vL, vR) * (1 - reset_ratio):
                rows[i]["reject"] = "glitch:dip %s<%s|%s" % (rows[i]["text"], rows[L]["text"],
                                                             rows[R]["text"])
                stat["dip"] += 1
            elif mode == "spike" and v > max(vL, vR) * spike_ratio:
                rows[i]["reject"] = "glitch:spike %s>%s|%s" % (rows[i]["text"], rows[L]["text"],
                                                               rows[R]["text"])
                stat["spike"] += 1

    # ── R1b 量级碎片（最后跑：此时骤升/骤降的坏读数已经剔除，
    #               不会再被当成"容器"，见 t=314.8 `490237` 把 `15096/25160` 当残片那次的教训）──
    good = [i for i, r in enumerate(rows) if r["grade"] == "raw" and not r["reject"]]
    for i in good:
        vi = rows[i]["text"]
        for j in good:
            if i == j:
                continue
            vj = rows[j]["text"]
            if abs(rows[j]["t"] - rows[i]["t"]) > frag_win or len(vj) <= len(vi):
                continue
            if max_absent_between(rows, absent, i, j) >= frag_absent:
                continue
            try:
                a, b = int(vi), int(vj)
            except ValueError:
                continue
            if a * 10 <= b and same_block(rows, i) < min_plateau:
                # 量级差 10 倍以上 + 位数更少 + 自己没停住 → 是上一次那个大数的丢位残片
                rows[i]["reject"] = "frag:small %s≪%s@%s" % (vi, vj, C._fmt(rows[j]["t"]))
                stat["small"] += 1
                break
    return stat


# ────────────────────────────── 切分 ──────────────────────────────
def expand_span(rows, runs, slack=1.0, cum_absent=0.4):
    """把每段的 `start`/`end` 扩到"这一段 HUD 实际还在屏上"的范围。

    为什么要扩：切分只在**可信读数**之间做，但"读数被剔除（碎片/毛刺）"或"flagged"的帧
    **HUD 是在场的**，它们属于这一次攻击的时间跨度。不扩的话会出现这种情况：
      · t=302.0 读到真值 `120754`（可信）、t=302.6~303.0 读到 `20754`（碎片被剔除），
        段的时间跨度停在 302.0 —— 于是"A 线真值 t=303 落在哪个段"就对不上了。
    扩的边界（三条，都不能越界）：
      · 不允许越过**上一段/下一段的第一条可信读数**；
      · 连续空白累计不超过 `cum_absent`（0.4s —— 实测这个值刚好把两件事分开：
        t=302.2~302.4 那 0.4s 空白之后 HUD 又出现了同一串数字的碎片，
        属于同一次攻击；而 t=158.8~161.2 那 2.4s 空白之后是另一次攻击，不能吞进来）；
      · 单步间隔 ≤0.4s。
    """
    idx = {id(r): k for k, r in enumerate(rows)}
    firsts = [idx[id(run["rows"][0])] for run in runs]
    lasts = [idx[id(run["rows"][-1])] for run in runs]
    for n, run in enumerate(runs):
        a, b = firsts[n], lasts[n]
        lo_bound = lasts[n - 1] if n > 0 else -1
        hi_bound = firsts[n + 1] if n + 1 < len(runs) else len(rows)
        # 向左
        k, cum = a, 0.0
        while k - 1 > lo_bound and rows[k]["t"] - rows[k - 1]["t"] <= 0.4 + 1e-9:
            if rows[k - 1]["grade"] == "absent":
                cum += rows[k]["t"] - rows[k - 1]["t"]
                if cum > cum_absent + 1e-9:
                    break
            k -= 1
        new_a = k
        # 向右
        k, cum = b, 0.0
        while k + 1 < hi_bound and rows[k + 1]["t"] - rows[k]["t"] <= 0.4 + 1e-9:
            if rows[k + 1]["grade"] == "absent":
                cum += rows[k + 1]["t"] - rows[k]["t"]
                if cum > cum_absent + 1e-9:
                    break
            k += 1
        new_b = k
        run["i0"], run["i1"] = new_a, new_b
        run["start"], run["end"] = rows[new_a]["t"], rows[new_b]["t"]
    return runs


def segment(rows, gap=1.5, reset_ratio=0.20, actor_split=True, plateau_break=3,
            absent_break=0.6, absent=None):
    """在**可信读数**上切分。返回 [{"start","end","rows","issues","candidates"}, ...]。

    与 C 线 `events.segment` 的差别有三处（都在模块头部说明了实测依据）：
      1. `dt ≥ gap`（1.5s）**无条件**断开（与 C 线同口径）。
      2. 新增**判据 0「HUD 真清屏」**：两条可信读数之间只要存在一段 **≥ `absent_break`（0.6s）
         的连续空白**，就断开（也不管数值有没有继续涨）。
         为什么要它：C 线的 1 fps 网格上"隔一帧"天然就是 2.0s 空白，所以 C 的 `gap=1.5`
         同时承担了"隔一帧就断"和"清屏就断"两件事；密帧下这两件事必须分开 ——
         实测 `150.2~150.4`（0.4s 空白，数值 168488→232327 继续涨）是**同一次攻击内部的眨眼**
         （断开会把死龙长链切碎），而 `107.6~108.4`（0.8s 空白，数值 2809→48076 继续涨）
         是**两次攻击**（C 线 #3/#4 本来就是分段的，不该被密帧合并）。
         0.6s 正好落在 0.4 与 0.8 之间。
      3. 新增**判据 5「双平台/双归属者」**：见 `_double_plateau()`。C 线的判据 3
         「归属者变化 + 数值没有继续增长」在密帧下会漏掉一种真实的换人：
         **数值继续增长、但换的是另一个人的攻击**
         （实测 t=154.0 `324751`@死龙/遐蝶 → t=154.4 `866730`@长夜/长夜月，
          1 fps 下这两帧隔了 2.0s 所以被 C 的空白判据切开了，密帧下只隔 0.4s）。
    """
    if absent is None:
        absent = absent_run(rows)
    idx = {id(r): k for k, r in enumerate(rows)}
    vals = [r for r in rows if value(r) is not None]
    runs, cur = [], None
    for r in vals:
        if cur is None:
            cur = {"start": r["t"], "end": r["t"], "rows": [r], "issues": [], "candidates": []}
            runs.append(cur)
            continue
        prev = cur["rows"][-1]
        dt = r["t"] - prev["t"]
        mx = max(value(x) for x in cur["rows"])
        v = value(r)
        blk = max_absent_between(rows, absent, idx[id(prev)], idx[id(r)])
        breaks, why = False, ""
        if dt >= gap:
            breaks, why = True, "gap%.1fs" % dt
        elif blk >= absent_break:
            breaks, why = True, "blank%.1fs" % blk
        elif v < mx * (1 - reset_ratio):
            breaks, why = True, "reset %d<%.0f" % (v, mx)
        elif actor_split and _owner_changed(prev, r) and v < mx:
            breaks, why = True, "owner %s->%s" % (prev["owner"] or "-", r["owner"] or "-")
        elif actor_split and _owner_to_memo(prev, r) and v < mx:
            breaks, why = True, "memo %s->%s" % (prev["unit"] or "-", r["unit"] or "-")
        elif actor_split and v > mx and _double_plateau(rows, cur, r, mx, plateau_break):
            breaks, why = True, "swap@%s" % C._fmt(r["t"])
        elif _plateau_pair(rows, cur, r, mx, plateau_break, absent, idx):
            breaks, why = True, "settle@%s" % C._fmt(r["t"])
        if breaks:
            cur["issues"].append(why.split()[0])
            cur = {"start": r["t"], "end": r["t"], "rows": [r], "issues": [], "candidates": []}
            runs.append(cur)
        else:
            cur["rows"].append(r)
            cur["end"] = r["t"]
    return runs


def _plateau_pair(rows, cur, r, mx, plateau_break, absent, idx):
    """判据 6「相邻双稳定平台」：一次攻击的读数会**结算住**（同一个值连续 ≥0.4s）。
    所以如果画面在短时间内出现了**两个各自结算住的、值不同的**读数，那就是两次攻击 ——
    即使后一个比前一个大（C 线的判据 2 只看"下降"、判据 3 看"归属者变化 + 不涨"，都抓不到）。

    四条同时成立才断（每一条都在实测里挡掉过误切）：
      · 左边那个值在段内形成了 ≥`plateau_break` 帧的稳定平台，且就在 r 之前 ≤1.0s，
        并且**左边那个平台有已确认归属者**（这一条把 C 线 #22 的
        `319195`(顶端读不出来) → `674271` 挡在外面：那一次是死龙自爆链在滚动，
        切开反而会把 674271 的归属丢成"待复核"）；
      · 右边 r 的值**与左边不同**、且自己也被旁证（`value_partners` ≥ `plateau_break` 帧）
        —— 同值不算（不加这条，`2809` 被自己的一条丢位碎片 `809` 隔开时会被误切成两段）；
      · 两侧**没有共同的已确认归属者**（不加这条，C 线 #49 的
        `75129`(昔涟) → `407772`(昔涟) 和 #34 的
        `60542`（平台内先昔涟后遐蝶）→ `336448`（遐蝶）都会被误切，锚点 t=251 就废了）；
      · 两者之间**确实变过**：HUD 空缺 ≥0.2s，或夹了一条被剔除的丢位读数
        （不加这条，死龙自爆链 `904004`(平台) → `1349238` 会被误切成两段）。
    """
    if value(r) == mx:
        return False
    i = idx[id(r)]
    partners = value_partners(rows, i)
    if len(partners) + 1 < plateau_break:
        return False
    p2_owner = {x["owner"] for x in [r] + partners if x["owner"]}
    left = [x for x in cur["rows"] if value(x) == mx and x["t"] >= r["t"] - 1.0]
    if len(left) < plateau_break:
        return False
    p1_owner = {x["owner"] for x in left if x["owner"]}
    if not owner_with_support(left):
        return False
    if p1_owner & p2_owner:
        return False
    j0 = idx[id(left[-1])]
    if max_absent_between(rows, absent, j0, i) >= 0.2:
        return True
    return any(rows[k]["reject"] for k in range(j0 + 1, i))


def _double_plateau(rows, cur, r, mx, plateau_break):
    """判据 5：新读数的稳定平台 vs 当前段最大值的平台的"唯一归属者"是否不同。

    "新平台的归属者"取法：**画面上是这个值的那些帧**（允许中间夹 flagged 帧，
    但不允许中间清过屏 ≥0.6s）里的唯一归属者。
    实测依据：`866730` 从 154.4 就在屏上，但顶端要到 155.6 才被 E 线确认是长夜/长夜月；
    若只看 r 那一刻 ±0.2s，会得到"无人"而漏判。
    """
    i = next((k for k, x in enumerate(rows) if x is r), None)
    if i is None:
        return False
    partners = value_partners(rows, i)
    if len(partners) + 1 < plateau_break:
        return False
    new_owner = owner_with_support([r] + partners)
    if not new_owner:
        return False
    peak_rows = [x for x in cur["rows"] if value(x) == mx]
    peak_owner = owner_with_support(peak_rows)
    if not peak_owner:
        return False
    return new_owner != peak_owner


MEMO_OWNERS = C.MEMO_OWNERS


def _owner_changed(a, b):
    return C._owner_changed(a, b)


def _owner_to_memo(a, b):
    return C._owner_to_memo(a, b)


# ────────────────────────────── 锚点 / 归属 ──────────────────────────────
def pick_anchor4(run):
    """段内**可信读数**的最大值；返回 {max, peak_t, anchor_t}。

    口径**与 C 线一致**（这一条是实测后改回来的，见下）：
      · `peak_t` = 段内最大值**最早**出现的那一帧；
      · `anchor_t` = `peak_t` 之前**最后一个**有已确认行动者的帧；之前一个都没有就取之后第一个；
        再没有就退回 `peak_t` 本身。

    ⚠️ 曾经改成"取**等于段最大值的帧里**最早的有行动者的那一帧"，在密帧上**会出错**：
      · 好处确实有：`866730` 的平台是 154.4~156.0，154.4~155.4 顶端读不出来，
        "最早的有行动者的最大值帧" = 155.6 → 长夜/长夜月（对）；
      · 但 `1349238`（死龙自爆）在 t=278.6 又出现了一次、那一刻顶端是**长夜月**
        （那是下一次攻击的显示回声），新口径会取到 278.6 → 归属变成长夜月（**错**，
        C 线真值是遐蝶）。
    C 的旧口径为什么两者都对：判据 5/6 已经把"换人的新平台"切成了**新段**，
    新段里"peak_t 之前"没有旧人的帧 → 只好取之后第一个 = 155.6 → 长夜月（对）；
    而 `1349238` 那一段起点是 270.2、段内 274.0 有"死龙/遐蝶" → 取到 274.0（对）。
    """
    vals = [(r["t"], value(r), r) for r in run["rows"] if value(r) is not None]
    if not vals:
        return None
    mx = max(v for _, v, _ in vals)
    peak_t = min(t for t, v, _ in vals if v == mx)
    with_actor = [r for r in run["rows"] if r["unit"]]
    if with_actor:
        before = [r for r in with_actor if r["t"] <= peak_t]
        anchor_t = (before[-1] if before else with_actor[0])["t"]
    else:
        anchor_t = peak_t
    return {"max": mx, "peak_t": peak_t, "anchor_t": anchor_t}


def _reject_summary(rows_):
    """统计一组帧里被剔除的读数。⚠️ 必须传**段时间跨度内的全部帧**，
    不能传 `run["rows"]` —— 后者只装可信读数，被剔除的帧根本不在里面。"""
    kinds, detail = {}, []
    for r in rows_:
        if not r["reject"]:
            continue
        k = r["reject"].split()[0]
        kinds[k] = kinds.get(k, 0) + 1
        detail.append("%s=%s[%s]" % (C._fmt(r["t"]), r["text"], r["reject"]))
    return kinds, "; ".join(detail)


def attribute4(readings, run, back=1.5, fwd=0.5, ult_window=True, ult_max_age=None):
    """给一段读数定归属。

    `ult_window`（T1，默认开）：因果窗口 `[-back, +fwd]` 里**没有**已确认行动者时，
    再向两侧借锚点，处理"**插入行动（大招/助战技）** → 全屏演出把整条行动轴抹掉"的窗口
    （黄泉/飞霄/姬子·启行 等长演出；机制与实测见 `events.find_actor_ult`）。
    ⚠️ 它**只在原本必判「待复核」的地方生效**，不会翻转任何已有结论。
    """
    vals = [(r["t"], value(r), r) for r in run["rows"] if value(r) is not None]
    issues = list(run["issues"])
    pk = pick_anchor4(run)
    if pk is None:
        return None
    mx, peak_t, anchor_t = pk["max"], pk["peak_t"], pk["anchor_t"]
    actor_row, dta = C.find_actor(readings, anchor_t, back, fwd)
    actor_src = "read" if actor_row is not None else ""
    if actor_row is None and ult_window:
        actor_row, dta, actor_src = C.find_actor_ult(
            readings, anchor_t,
            max_age=C.ULT_MAX_AGE if ult_max_age is None else ult_max_age)
    all_rows = [r for r in readings if run["start"] - 1e-9 <= r["t"] <= run["end"] + 1e-9]
    min_conf = min((r["conf"] for r in all_rows if r["text"]), default=0.0)
    owner_start, n_owners, owner_breaks, plurality = C._owner_evidence(run)
    if n_owners > 1:
        issues.append("multi_owner(%s)" % owner_breaks)
    kinds, detail = _reject_summary(all_rows)
    n_frag = sum(n for k, n in kinds.items() if k.startswith("frag"))

    out = {
        "t_first": run["start"], "t_last": run["end"],
        "t_peak": peak_t, "t_anchor": anchor_t,
        "duration": round(run["end"] - run["start"], 2),
        "damage_first": vals[0][1] if vals else "",
        "damage_final": vals[-1][1] if vals else "",
        "damage_max": mx,
        "n_readings": len(run["rows"]),
        "min_conf": round(min_conf, 3),
        "owner_start": owner_start, "n_owners": n_owners, "owner_breaks": owner_breaks,
        "readings": ";".join("%s%s" % (C._fmt(t), r["text"]) for t, v, r in vals),
        "pairs": "|".join("%s:%s" % (C._fmt(t), r["text"]) for t, v, r in vals),
        "t_res": "0.2s" if any(abs(r["t"] - round(r["t"])) > 1e-6 for r in all_rows) else "1s",
        "n_frames": len(all_rows),
        "n_trusted": len(vals),
        "n_rejected": sum(kinds.values()),
        "n_frag": n_frag,
        "reject_kinds": ";".join("%s×%d" % (k, n) for k, n in sorted(kinds.items())),
        "rejected": detail,
        "t_trusted_span": ("%s~%s" % (C._fmt(vals[0][0]), C._fmt(vals[-1][0]))) if vals else "",
        "split_candidates": ";".join(run.get("candidates", [])),
    }

    if actor_row is None:
        out.update({"unit": "", "owner": "", "card_type": "", "inserted": "",
                    "actor_score": "", "actor_margin": "", "actor_t": "",
                    "actor_src": "", "status": "review"})
        issues.append("actor_unknown")
        out["issues"] = ",".join(issues)
        out["quality"] = _quality(run, readings, issues, out)
        return out

    out.update({"unit": actor_row["unit"], "owner": actor_row["owner"],
                "card_type": actor_row["card_type"] or "unit",
                "inserted": actor_row["inserted"], "actor_score": actor_row["score"],
                "actor_margin": actor_row["margin"], "actor_t": actor_row["t"],
                "actor_src": actor_src})
    if actor_src.startswith("ult_"):
        # T1：这一段的行动者不是"直接读到的"，而是从演出两侧的锚点借来的 → 记明来源
        issues.append("ult_window_%s" % actor_src.split("_", 1)[1])

    if out["card_type"] in ("enemy", "enemy_buff"):
        # `enemy_buff` = **红兔（敌方场地效果 / 敌方给我方的 buff）** → 归敌方机制、不计入我方伤害。
        # 2026-10-05 补（与 events.py 同步）：原来没有这个分支 → owner 为空 → 记成 `review`。
        # 数值一样（review 也不进分子/分母），但语义不对：不该显示成"待复核（拿不准）"。
        out["status"] = "non_ally"
        issues.append("enemy_buff_card" if out["card_type"] == "enemy_buff" else "enemy_card")
    elif out["card_type"] == "empty":
        out["status"] = "review"
        issues.append("top_slot_empty")
    elif out["card_type"] in ("aha", "elation", "blindbox"):
        # 同 events.py：T2 认出 owner 才采纳，认不出仍 review（2026-10-05 修）
        if out.get("owner"):
            out["status"] = "ok"
            issues.append("owner_from_t2")
        else:
            out["status"] = "review"
            issues.append("aha_needs_owner")
    elif out["owner"]:
        out["status"] = "ok"
    else:
        out["status"] = "review"
        issues.append("owner_empty")

    if not C.is_plausible(mx):
        out["status"] = "review"
        issues.append("implausible")
    elif any(not C.is_plausible(value(r)) for r in run["rows"] if value(r) is not None):
        out["status"] = "review"
        issues.append("implausible_in_run")

    out["issues"] = ",".join(issues)
    out["quality"] = _quality(run, readings, issues, out)
    return out


def _quality(run, readings, issues, out):
    """段的可信度（"这个结论有多硬"，不是"读数有多干净"）：

       ok       边界是"清屏/重置/换人"三者之一，且**峰值有旁证**（同一个数在段内被读到 ≥2 次，
                或那条读数本来就在 1 fps 整数秒网格上）
       partial  段被扫描边界截断（视频开头/结尾附近）
       suspect  ★ 以下任一：段内换过归属者（`multi_owner`，说明可能混了两次攻击）、
                读数量级不合理、或**峰值只有孤证**（只读到 1 次且不在 1 fps 网格上）——
                孤证的峰值可能就是一次没读准的滚动中间值。

    ⚠️ "段内夹了被剔除的读数"**不算** suspect：那些读数正是本引擎剔掉的噪声，
    它们的存在只说明这一段的原始读数更脏，不说明结论不硬（剔了多少如实记在 `n_rejected`）。
    """
    if any(i.startswith("multi_owner") or i.startswith("implausible") for i in issues):
        return "suspect"
    vals = [(r["t"], value(r)) for r in run["rows"] if value(r) is not None]
    if vals:
        mx = max(v for _, v in vals)
        reps = [t for t, v in vals if v == mx]
        on_grid = any(abs(t - round(t)) < 1e-6 for t in reps)
        if len(reps) < 2 and not on_grid:
            return "suspect"
    t_first, t_last = run["start"], run["end"]
    all_t = [r["t"] for r in readings]
    if all_t and (t_first <= min(all_t) + 1e-9 or t_last >= max(all_t) - 1e-9):
        return "partial"
    return "ok"


# ────────────────────────────── 主流程 ──────────────────────────────
def build(frames=FRAMES, gap=1.5, reset_ratio=0.20, back=1.5, fwd=0.5, actor_split=True,
          reject=True, plateau_break=3, absent_break=0.6,
          ult_window=True, ult_max_age=None, **kw):
    readings = classify(load(frames))
    stat = {"sub": 0, "small": 0, "dip": 0, "spike": 0, "flicker": 0}
    if reject:
        stat = mark_rejects(readings, reset_ratio=reset_ratio, **kw)
    runs = segment(readings, gap=gap, reset_ratio=reset_ratio, actor_split=actor_split,
                   plateau_break=plateau_break, absent_break=absent_break)
    expand_span(readings, runs)
    # 段内"被剔除的读数"标成疑似边界候选，让下游知道这里可能还有一次攻击
    for run in runs:
        rej = [r for r in readings
               if run["start"] - 1e-9 <= r["t"] <= run["end"] + 1e-9
               and r["reject"].startswith("frag")]
        if rej:
            run["candidates"] = ["maybe_split@%s(%s)" % (C._fmt(r["t"]), r["text"]) for r in rej]
    events = []
    for i, run in enumerate(runs, 1):
        ev = attribute4(readings, run, back=back, fwd=fwd,
                        ult_window=ult_window, ult_max_age=ult_max_age)
        if ev is None:
            continue
        ev["event"] = i
        events.append(ev)
    return readings, events, stat


def write_csv(events, path=EVENTS):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=EVENT_COLS)
        w.writeheader()
        for e in events:
            w.writerow({k: e.get(k, "") for k in EVENT_COLS})
    return path


# ────────────────────────────── 验收 A：A 线真值（严格口径）──────────────────────────────
def check_truth(events, show=True):
    """
    A 线 25 帧真值读数是否能在事件表里**复现**。

    ⚠️ 这里用**严格口径**：真值必须作为该段里**某一条完整读数**出现。
    C 线 `check_damage` 用的是 `r.endswith(val)`，而 `readings` 是 `"t"+"text"` 拼起来的，
    所以 `"103304505".endswith("304505")` 也成立 —— 那会把"读数里恰好以真值结尾"也算通过，
    口径偏松。本函数两种都报，但**以严格口径为准**。
    """
    from digit_truth import LABELED, HOLDOUT
    truth = {float(k): v for k, v in LABELED.items()}
    truth.update({float(k): v for k, v in HOLDOUT.items()})
    if show:
        print("\n=== 验收 A：A 线真值读数复现（%d 帧，严格口径 = 必须是段内一条完整读数）===" % len(truth))
        print("%-7s %-9s %-9s %-4s %s" % ("t", "真值", "落段最大", "判定", "说明"))
    strict_ok = strict_bad = loose_ok = 0
    bad_list = []
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
            exact = any(p.rsplit(":", 1)[-1] == val for p in (hit.get("pairs") or "").split("|") if p)
            loose = val in (hit["readings"] or "")
            good = exact
            note = "事件#%d 最大=%s 状态=%s %s" % (
                hit["event"], format(int(hit["damage_max"]), ","), hit["status"],
                "" if exact else ("（仅宽松口径通过：读数字符串里含该真值）" if loose else ""))
        strict_ok += good
        loose_ok += (good or (hit is not None and val in (hit["readings"] or "")))
        strict_bad += (not good)
        if not good:
            bad_list.append((t, val, note))
        if show:
            print("%-7s %-9s %-9s %-4s %s" %
                  (("%.2f" % t).rstrip("0").rstrip("."), val,
                   format(int(hit["damage_max"]), ",") if hit else "-",
                   "OK" if good else "!!", note))
    if show:
        print("  严格一致 %d / 不一致 %d     （宽松口径 %d/%d，C 线用的是宽松口径）"
              % (strict_ok, strict_bad, loose_ok, len(truth)))
    return strict_ok, strict_bad, bad_list


def _prefix_is_time(x, val):
    """`x` = `时间串` + `读数`；检查去掉尾部 `val` 之后剩下的确实是一个时间串。"""
    head = x[:len(x) - len(val)]
    if not head:
        return False
    try:
        float(head)
        return True
    except ValueError:
        return False


# ────────────────────────────── 验收 B：锚点 ──────────────────────────────
def check_anchors(events, readings, back=1.5, fwd=0.5, grid=None):
    """验收 B：锚点对账（事件级，口径同 C 线 `check_anchors`）。

    ⚠️ 一处必须说清的口径：C 线的锚点表里那 6 条「待复核」是**"1 fps 那一帧判不出来"**
    的意思（实测 t=104/134 那几帧正好落在特效遮住行动轴的时段）。
    本引擎有密帧，"最近 1.5s 内的已确认行动者"往往能借到邻帧 —— 如果拿密帧去判"这一帧
    能不能判"，这 6 条就自动变成"能判"，于是拿旧的期望去比就**必然报错**，那是不公平比较。
    所以：**"该帧能否判"这一步用 1 fps 网格（`footnote`），事件级归属用本引擎的事件表**。
    `grid` 不给就退回用本引擎的读数（结果会偏松/偏严，已在输出里注明）。
    """
    src = grid if grid is not None else readings
    print("\n=== 验收 B：锚点对账（事件级；「该帧能否判」用 %s）===" %
          ("1 fps 网格（与 C 线同信息集）" if grid is not None else "密帧（偏松，仅参考）"))
    print("%-7s %-9s %-9s %-9s %-9s %-4s %s" %
          ("t", "期望顶端", "实得顶端", "期望归属", "实得归属", "判定", "落点"))
    ok = bad = abstain = 0
    bads = []
    for t, eu, eo, est in C.ANCHORS:
        hit = None
        for e in events:
            if e["t_first"] - 0.01 <= t <= e["t_last"] + 0.01 or abs(e["t_peak"] - t) <= 0.51:
                hit = e
                break
        row = {round(r["t"], 2): r for r in src}.get(round(float(t), 2))
        has_reading = bool(row and row["grade"] == "raw")
        own_actor, _ = C.find_actor(src, float(t), back, fwd)
        if own_actor is None:
            abstain += 1
            print("%-7s %-9s %-9s %-9s %-9s %-4s %s" %
                  (t, eu or "待复核", "-", eo or "-", "-", "OK",
                   "该帧无已确认行动者（%s）→ 引擎弃权；%s" %
                   ("无读数" if not has_reading else "有读数但顶端不可判",
                    ("落段 #%d" % hit["event"]) if hit else "未落段")))
            continue
        if hit is None:
            abstain += (not has_reading)
            if not has_reading:
                print("%-7s %-9s %-9s %-9s %-9s %-4s %s" %
                      (t, eu, "-", eo, "-", "OK", "该帧无可用读数 → 引擎弃权"))
            else:
                bad += 1
                bads.append((t, "该帧有读数却没进任何事件"))
                print("%-7s %-9s %-9s %-9s %-9s %-4s 该帧读数=%s，却没进任何事件"
                      % (t, eu, "-", eo, "-", "!!", row["text"]))
            continue
        gu, go = hit["unit"] or "-", hit["owner"] or "-"
        good = (hit["unit"] == eu) and (hit["owner"] == eo)
        ok += good
        bad += (not good)
        if not good:
            bads.append((t, "期望 %s/%s 实得 %s/%s" % (eu, eo, gu, go)))
        print("%-7s %-9s %-9s %-9s %-9s %-4s 事件#%d %s~%s 读%s 状态%s 质量%s" %
              (t, eu, gu, eo, go, "OK" if good else "!!", hit["event"],
               C._fmt(hit["t_first"]), C._fmt(hit["t_last"]), hit["readings"],
               hit["status"], hit["quality"]))
    print("  一致 %d / 不一致 %d / 正确弃权 %d" % (ok, bad, abstain))
    return ok, bad, abstain, bads


# ────────────────────────────── 验收 C：与 C 线事件表逐条对账 ──────────────────────────────
def rejected_values(events):
    """从各段的 `rejected` 文本里解析出被剔除的读数（数值集合）。

    `rejected` 的条目形如 `158=0408[frag:sub 0408⊂210408@157]` —— `=` 后面是原始读数文本
    （可能带前导 0），转成 int 便于与 C 线的 damage_max 比。
    """
    out = set()
    for e in events:
        for item in (e.get("rejected") or "").split("; "):
            if "=" not in item:
                continue
            txt = item.split("=", 1)[1].split("[", 1)[0].strip()
            if txt.isdigit():
                out.add(int(txt))
    return out


def compare_with_C(events, path=EVENTS_C):
    """与 C 线事件表逐条对账。四类处置：

      `keep`     数值与 C 相同
      `sub`      C 段的峰值读数**仍然可信**，只是落在本引擎一个更大的段里
                 （= C 把一次攻击拆成了两段，或 C 的峰值读数与相邻读数本来就是同一次攻击）
      `rejected` C 段的那条峰值读数被本引擎判为**丢位碎片/毛刺** → C 的数值是读数缺陷，不是一次攻击
      `gone`     找不到对应的段（应当为 0；不为 0 就是丢攻击）

    另外单列**本引擎新增的段**：与任何 C 段的时间范围都不重叠的那些。
    """
    print("\n=== 验收 C：与 C 线事件表逐条对账 ===")
    with open(path, encoding="utf-8-sig") as f:
        crows = list(csv.DictReader(f))
    c_events = []
    for r in crows:
        c_events.append({
            "event": int(r["event"]),
            "t_first": float(r["t_first"]), "t_last": float(r["t_last"]),
            "t_peak": float(r["t_peak"]), "damage_max": int(r["damage_max"]),
            "unit": r["unit"], "owner": r["owner"], "status": r["status"],
            "quality": r["quality"], "readings": r["readings"],
        })
    print("  C 线事件 %d 段；本引擎 %d 段" % (len(c_events), len(events)))

    tally = {"keep": 0, "sub": 0, "rejected": 0, "gone": 0}
    rej_vals = rejected_values(events)
    rows_out = []
    for ce in c_events:
        hit = None
        for e in events:
            if e["t_first"] - 0.01 <= ce["t_peak"] <= e["t_last"] + 0.01:
                hit = e
                break
        if hit is None:
            st = "gone"
            note = "该峰值帧附近没有任何本引擎的段"
        elif int(hit["damage_max"]) == int(ce["damage_max"]):
            st, note = "keep", ""
        else:
            # C 的那条读数还在不在？可信读数里找得到 → sub；出现在 rejected 里 → rejected
            val = str(ce["damage_max"])
            trusted = [p.rsplit(":", 1)[-1] for p in (hit.get("pairs") or "").split("|") if p]
            if val in trusted:
                st = "sub"
                note = "C 的读数可信，本引擎这一个段把它和相邻读数并成了一次攻击"
            elif int(ce["damage_max"]) in rej_vals:
                st = "rejected"
                note = "C 的峰值读数被判为丢位碎片/毛刺 → 数值改用本段的可信峰值"
            else:
                st = "sub"
                note = "C 的读数未出现在本段（可能被并入更早/更晚的段）"
        tally[st] += 1
        rows_out.append((st, ce, hit, note))

    print("\n  %-9s %-15s %-10s %-7s | %-15s %-10s %-7s %s" %
          ("处置", "C 段(时间)", "C 值", "C 状", "线4 段(时间)", "线4 值", "线4 状", "说明"))
    for st, ce, e, note in rows_out:
        print("  %-9s %-15s %-10s %-7s | %-15s %-10s %-7s %s" %
              (st, "%s~%s" % (C._fmt(ce["t_first"]), C._fmt(ce["t_last"])),
               format(ce["damage_max"], ","), ce["status"],
               ("%s~%s" % (C._fmt(e["t_first"]), C._fmt(e["t_last"]))) if e else "-",
               format(int(e["damage_max"]), ",") if e else "-",
               e["status"] if e else "-", note))

    news = [e for e in events
            if not any(ce["t_first"] - 0.51 <= e["t_peak"] <= ce["t_last"] + 0.51
                       for ce in c_events)]
    print("\n  C 段处置：keep %d / sub %d / rejected %d / gone %d"
          % (tally["keep"], tally["sub"], tally["rejected"], tally["gone"]))
    print("  ⭐ 本引擎新增、且与任何 C 段都不重叠的段：%d" % len(news))
    for e in news:
        print("     #%d %s~%s 峰值 %s@%s %s/%s 状态=%s 读数=%s" %
              (e["event"], C._fmt(e["t_first"]), C._fmt(e["t_last"]),
               format(int(e["damage_max"]), ","), C._fmt(e["t_peak"]),
               e["unit"] or "-", e["owner"] or "-", e["status"], e["readings"]))
    # 「没有丢攻击」的两种硬检查
    uncovered = [ce["event"] for ce in c_events
                 if not any(e["t_first"] - 1.0 <= ce["t_peak"] <= e["t_last"] + 1.0
                            for e in events)]
    lost_vals = []
    all_trusted = set()
    for e in events:
        all_trusted |= {p.rsplit(":", 1)[-1] for p in (e.get("pairs") or "").split("|") if p}
    for ce in c_events:
        v = int(ce["damage_max"])
        if str(v) not in all_trusted and v not in rej_vals:
            lost_vals.append((ce["event"], v))
    print("  ⭐ 硬检查 1「C 的每一段都还有落点」：未覆盖 %d 段 %s"
          % (len(uncovered), uncovered or ""))
    print("  ⭐ 硬检查 2「C 的每个峰值要么仍可信、要么已被明确剔除为丢位」："
          "两种都不是的有 %d 个 %s" % (len(lost_vals), lost_vals or ""))
    return {"keep": tally["keep"], "sub": tally["sub"], "rejected": tally["rejected"],
            "gone": tally["gone"], "new": len(news), "uncovered": uncovered,
            "lost_values": lost_vals}


def summarize(events, path=OWNER_CSV):
    from collections import Counter, defaultdict
    print("\n=== 归属汇总（只算 status=ok）===")
    print("%-8s %-6s %-14s %-14s %-8s %s" % ("归属", "次数", "合计", "最大一击", "平均", "质量"))
    agg = defaultdict(lambda: {"n": 0, "sum": 0, "max": 0, "q": Counter()})
    for e in events:
        if e["status"] != "ok":
            continue
        a = agg[e["owner"] or "(未定)"]
        a["n"] += 1
        a["sum"] += int(e["damage_max"])
        a["max"] = max(a["max"], int(e["damage_max"]))
        a["q"][e["quality"]] += 1
    rows = sorted(agg.items(), key=lambda kv: -kv[1]["sum"])
    for o, a in rows:
        print("%-8s %-6d %-14s %-14s %-8s %s" %
              (o, a["n"], format(a["sum"], ","), format(a["max"], ","),
               format(a["sum"] // max(1, a["n"]), ","), dict(a["q"])))
    print("%-8s %-6d %-14s" % ("合计", sum(a["n"] for _, a in rows),
                               format(sum(a["sum"] for _, a in rows), ",")))
    if path:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["owner", "n_events", "damage_sum", "damage_max_once", "damage_mean",
                        "n_quality_ok", "n_quality_suspect", "n_quality_partial"])
            for o, a in rows:
                w.writerow([o, a["n"], a["sum"], a["max"], a["sum"] // max(1, a["n"]),
                            a["q"].get("ok", 0), a["q"].get("suspect", 0), a["q"].get("partial", 0)])
        print("已写出 %s" % path)


# ────────────────────────────── CLI ──────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default=FRAMES)
    ap.add_argument("--out", default=EVENTS)
    ap.add_argument("--gap", type=float, default=1.5, help="硬空白：≥ 这个秒数无条件断开")
    ap.add_argument("--reset-ratio", type=float, default=0.20)
    ap.add_argument("--back", type=float, default=1.5)
    ap.add_argument("--fwd", type=float, default=0.5)
    ap.add_argument("--frag-win", type=float, default=1.5)
    ap.add_argument("--frag-absent", type=float, default=0.8)
    ap.add_argument("--glitch-win", type=float, default=0.6)
    ap.add_argument("--spike-ratio", type=float, default=4.0)
    ap.add_argument("--min-plateau", type=int, default=3,
                    help="毛刺判据的豁免门槛：同值连续帧数 ≥ 这个值就不判毛刺")
    ap.add_argument("--plateau-break", type=int, default=3,
                    help="判据 5（双平台/双归属者）要求新值至少停住这么多帧")
    ap.add_argument("--absent-break", type=float, default=0.6,
                    help="判据 0：两条可信读数之间出现这么长的连续空白就无条件断开")
    ap.add_argument("--flicker-win", type=float, default=1.5,
                    help="R3 闪回：多早之前出现过的旧值再出现算闪回")
    ap.add_argument("--glitch-absent", type=float, default=0.6,
                    help="R2 毛刺的护栏：两侧邻居之间空白 ≥ 这个秒数才放弃判毛刺")
    ap.add_argument("--no-reject", action="store_true", help="关掉碎片/毛刺剔除（对照实验）")
    ap.add_argument("--no-actor-split", action="store_true")
    ap.add_argument("--anchors", action="store_true")
    ap.add_argument("--truth", action="store_true", help="A 线真值严格复现")
    ap.add_argument("--compare", action="store_true", help="与 out/events_C.csv 逐条对账")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    readings, events, stat = build(
        args.frames, gap=args.gap, reset_ratio=args.reset_ratio, back=args.back, fwd=args.fwd,
        actor_split=not args.no_actor_split, reject=not args.no_reject,
        frag_win=args.frag_win, frag_absent=args.frag_absent, glitch_win=args.glitch_win,
        spike_ratio=args.spike_ratio, min_plateau=args.min_plateau,
        plateau_break=args.plateau_break, absent_break=args.absent_break,
        flicker_win=args.flicker_win, glitch_absent=args.glitch_absent)

    print("帧 %d 个（raw %d / flagged %d / absent %d）；剔除：子串碎片 %d、量级碎片 %d、"
          "骤降毛刺 %d、骤升毛刺 %d、闪回 %d" %
          (len(readings), sum(1 for r in readings if r["grade"] == "raw"),
           sum(1 for r in readings if r["grade"] == "flagged"),
           sum(1 for r in readings if r["grade"] == "absent"),
           stat["sub"], stat["small"], stat["dip"], stat["spike"], stat["flicker"]))
    path = write_csv(events, args.out)
    n_ok = sum(1 for e in events if e["status"] == "ok")
    n_dmg = sum(int(e["damage_max"]) for e in events if e["status"] == "ok")
    print("可信读数 → 事件 %d 段（可采纳 %d / 待复核+非我方 %d）" %
          (len(events), n_ok, len(events) - n_ok))
    print("可采纳事件总伤合计 = %s" % format(n_dmg, ","))
    print("已写出 %s" % path)
    from collections import Counter
    print("状态分布:", dict(Counter(e["status"] for e in events)))
    print("质量分布:", dict(Counter(e["quality"] for e in events)))
    print("边界分辨率:", dict(Counter(e["t_res"] for e in events)))
    print("归属分布:", dict(Counter(e["owner"] or "(未定)" for e in events)))

    if args.verbose:
        print("\n%-4s %-15s %-10s %-8s %-6s %-7s %-9s %-8s %s" %
              ("#", "时间窗", "最大读数", "行动者", "归属", "状态", "质量", "分辨率", "读数/剔除"))
        for e in events:
            print("%-4d %-15s %-10s %-8s %-6s %-7s %-9s %-8s %s%s" %
                  (e["event"], "%s~%s" % (C._fmt(e["t_first"]), C._fmt(e["t_last"])),
                   format(int(e["damage_max"]), ","), e["unit"] or "-", e["owner"] or "-",
                   e["status"], e["quality"], e["t_res"], e["readings"],
                   ("  ⊘" + e["rejected"]) if e["rejected"] else ""))

    if args.anchors:
        grid = classify(load(os.path.join(HERE, "out/frames_C.csv"))) if os.path.exists(
            os.path.join(HERE, "out/frames_C.csv")) else None
        check_anchors(events, readings, back=args.back, fwd=args.fwd, grid=grid)
    if args.truth:
        check_truth(events)
    if args.compare:
        compare_with_C(events)
    if args.summary:
        summarize(events)
    if args.json:
        json.dump(events, open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("已写出 %s" % args.json)


if __name__ == "__main__":
    main()
