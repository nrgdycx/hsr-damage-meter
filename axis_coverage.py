# -*- coding: utf-8 -*-
"""
线6：录屏1 覆盖率提升 —— 逐帧诊断 + 相邻帧外推（hold-last）。

做三件事：
  1) 逐帧算一个**与识别器无关**的"行动轴是否可见"信号（队列区竖边密度），
     用来把"轴被动画隐藏"和"轴在、但顶端卡判不出来"分开（这两件事原来都只体现为 card_type=empty）。
  2) 复用 E 线 `axis_actor.read_actor` 的判定，把每一帧归入有限个状态
     （read/enemy/aha/elation/hold/none），其中 hold = 用**上一个已确认帧**外推，**必须带标记**。
  3) 输出 `out/axis_actors_L6.csv`（覆盖 `out/axis_actors_E.csv` 的全部列 + 外推列），
     并给出覆盖率统计（外推前/后，按帧 + 按 C 线事件）。

铁律：外推值一律 `source=hold` + `hold_age`（追了多少秒），不冒充确定值。

用法：
    python axis_coverage.py --scan        # 扫 100~339 逐帧，出 CSV + 统计
    python axis_coverage.py --stats       # 只读已有 CSV 出统计
    python axis_coverage.py --frame 171   # 单帧诊断（含可见性信号）
"""
import argparse
import csv
import json
import os
import sys

import cv2
import numpy as np

import axis_actor as T

HERE = os.path.dirname(os.path.abspath(__file__))

FRAME = os.path.join(HERE, "frames/glyphcache/f%08.2f.png")
OUT_CSV = os.path.join(HERE, "out/axis_actors_L6.csv")
EVENTS_C = os.path.join(HERE, "out/events_C.csv")

T0, T1 = 100, 339                      # 录屏1 的 1 fps 整数秒网格（frames/glyphcache 里 t=98~339）
# 外推采纳上限：超过这个秒数的外推一律标"待复核"（实测尾巴段 319-339 最长追到 20s，太远）
MAX_ADOPT_AGE = 8.0
# ── 定案（《剩余工作清单.md》【线6】尾巴 1）────────────────────────────
# **只采 tier A**（前后锚点都是我方且同一人），**不采 tier B**（两侧都是我方但段内换人）。
# 依据：模拟遮挡回测 A=97.1%(33/34) vs B=46.4%(13/28)；人工抽样 A=10/10、B=3/6。
# tier C（至少一侧不是我方）证据冲突（回测 91.7% 而人工 2/8）→ 只作 `低可信` 提供，默认不采纳。
# 想改口径用 `--tier-policy A,B,C`，或在 `verdict()` 的返回值上自行过滤。
ADOPT_TIERS = ("A",)

# ---- 行动轴可见性信号 -------------------------------------------------------
# 区域 = 行动轴"队列"部分（顶端卡以下的整列），参考坐标 2876x1798。
# 轴可见时这一列是十几张带边框的卡片 → 竖边（Sobel x）非常强；
# 轴被隐藏时这里是战斗画面（左侧多为天空/背景），几乎是平滑的。
QUEUE_RECT = (66, 210, 300, 1250)
VIS_THR = 20.0        # 阈值标定见 axis_hold_eval_L6.py（人工核对样本的混淆矩阵）


def queue_feat(img, s=None):
    """队列区的可见性特征：竖边均值 / 横边均值 / 对比度 / 亮度。"""
    if s is None:
        s = T.scale_of(img.shape)
    x0, y0, x1, y1 = T._rect(QUEUE_RECT, s)
    r = img[y0:y1, x0:x1]
    g = cv2.cvtColor(r, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gx = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3))
    gy = np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
    return {"edge_v": float(gx.mean()), "edge_h": float(gy.mean()),
            "std": float(g.std()), "val": float(g.mean())}


def axis_visible(img, s=None, thr=VIS_THR):
    f = queue_feat(img, s)
    return f["edge_v"] >= thr, f


# ---- 逐帧状态机 -------------------------------------------------------------
ENEMY_MARKERS = ("enemy_dot", "enemy_star", "enemy_diamond")
KINDS_STATE = ("read", "enemy", "aha", "elation")


def classify_frame(t, bank=None):
    """单帧 → 诊断 dict（不涉及外推）。"""
    img = T.load_frame(t)
    s = T.scale_of(img.shape)
    r = T.read_actor(img, bank)
    vis, feat = axis_visible(img, s)
    mk = r["marker"]
    if r["unit"]:
        state = "read"
    elif mk == "gold_aha" or r["card_type"] == "aha":
        state = "aha"
    elif mk == "ally_diamond" or r["card_type"] == "elation":
        state = "elation"
    elif mk in ENEMY_MARKERS or r["card_type"] == "enemy":
        state = "enemy"
    elif not vis:
        state = "hidden"                 # 行动轴整列不可见（动画/演出）
    elif r["card_type"] == "unit":
        state = "occluded"               # 轴在、顶端是我方单位卡，但被特效盖住判不出来
    else:
        state = "blank"                  # 轴在、顶端槽空/过渡
    return {"t": t, "state": state, "vis": int(vis), "unit": r["unit"] or "",
            "owner": r["owner"] or "", "raw": r["raw"], "score": r["score"],
            "margin": r["margin"], "marker": mk, "card_type": r["card_type"],
            "inserted": "" if r["inserted"] is None else int(r["inserted"]),
            "reject": r["reject"] or "", **feat}


def extrapolate(rows, max_hold=None):
    """就地给每行补 `source/unit_out/owner_out/alt_owner/hold_age/anchored/tier`。

    规则（保守；"宁可漏，不要错"）：
      * 已确认帧 → source=read，直接用识别结果（确定值）。
      * 敌方卡 / 阿哈卡 / 欢愉技卡 → source=enemy / aha / elation（"顶端不是我方单位"这件事本身是确定的）。
      * hidden / occluded / blank（轴不可见 / 顶端卡被特效盖住 / 空槽）→
        用**上一次已知状态**外推（read→hold；enemy/aha/elation 同理顺延，
        ⚠️ 关键：上一次已知状态是**敌方**时不能顺延我方 —— 敌方行动的动画一样会把整条轴藏起来）。
        `hold_age` = 距该锚点秒数；`anchored` = 后方还有一个已知状态帧。
      * 前方完全没有已知状态 → source=none。
      * max_hold 给了就只外推 hold_age <= max_hold 的帧，超出的 source=none（age 仍记录）。
      * `owner_out` = 前锚点（hold-last，对应"这段动画是谁在打"）；
        `alt_owner` = 前后锚点里时间更近的那个（对应"此刻顶端是谁"，仅供对照）。
      * `tier`：A=前后锚点都是 read 且同一人；B=前后都是 read 但换人；C=只有单侧锚点。
    """
    known = None                     # (t, kind, unit, owner) 最近一次"已知状态"
    prev_read = None                 # (t, owner) 最近一次**我方已确认**帧
    for r in rows:
        if r["state"] == "read":
            r.update(source="read", unit_out=r["unit"], owner_out=r["owner"], alt_owner=r["owner"],
                     hold_age=0.0, anchored=True, tier="read")
            known = (r["t"], "read", r["unit"], r["owner"])
            prev_read = (r["t"], r["owner"])
            r["_P"] = known
            continue
        k = {"enemy": "enemy", "aha": "aha", "elation": "elation"}.get(r["state"])
        if k:
            r.update(source=k, unit_out="", owner_out="", alt_owner="", hold_age="",
                     anchored="", tier=k)
            known = (r["t"], k, "", "")
            r["_P"] = known
            r["_PREAD"] = prev_read
            continue
        # 左标记明确是**我方**（青点/青星）→ "顶端站的是我方单位"这件事本身是确定的，
        # 只是认不出是谁。此时**不能**因为前面出现过敌方卡就顺延成敌方
        # （实测 t=108/257/284：前面是敌方/阿哈锚点，但顶端就是一张我方卡）。
        if r["marker"] in ("ally_dot", "ally_star"):
            if prev_read is None:
                r.update(source="none", unit_out="", owner_out="", alt_owner="", hold_age="",
                         anchored="", tier="none")
            else:
                age = round(r["t"] - prev_read[0], 3)
                r.update(source="hold", unit_out="", owner_out=prev_read[1], alt_owner=prev_read[1],
                         hold_age=age, anchored="", tier="C")
                known = (r["t"], "read", "", prev_read[1])
            r["_P"] = known
            r["_PREAD"] = prev_read
            continue
        if known is None:
            r.update(source="none", unit_out="", owner_out="", alt_owner="", hold_age="",
                     anchored="", tier="none")
            r["_P"] = None
            r["_PREAD"] = prev_read
            continue
        age = round(r["t"] - known[0], 3)
        if max_hold is not None and age > max_hold:
            r.update(source="none", unit_out="", owner_out="", alt_owner="", hold_age=age,
                     anchored="", tier="too_old")
            r["_P"] = known
            r["_PREAD"] = prev_read
            continue
        r.update(source="hold" if known[1] == "read" else known[1],
                 unit_out=known[2], owner_out=known[3], alt_owner=known[3],
                 hold_age=age, anchored="", tier="C")
        r["_P"] = known                 # 前锚点（锚点不更新：连续外推都追同一个）
        r["_PREAD"] = prev_read
    # 第二趟（逆序）：后锚点 → anchored / tier(A/B/C) / alt_owner
    #   A = 前锚点与后锚点都是 read 且同一 owner；B = 两侧都是 read 但换人；C = 至少一侧不是 read
    nxt_known = None
    nxt_read = None
    for r in reversed(rows):
        if r.get("source") in ("read", "enemy", "aha", "elation") and r["state"] in KINDS_STATE:
            nxt_known = r
            if r["state"] == "read":
                nxt_read = r
            continue
        P = r.pop("_P", None)
        PR = r.pop("_PREAD", None)
        r["anchored"] = nxt_read is not None
        if r["source"] == "hold" and P and P[1] == "read" and nxt_known is not None \
                and nxt_known["state"] == "read":
            r["tier"] = "A" if P[3] == nxt_known["owner_out"] else "B"
        else:
            r["tier"] = "C"
        # alt_owner = 前后**我方**锚点里时间更近的那个
        best = None
        if PR:
            best = (r["t"] - PR[0], PR[1])
        if nxt_read is not None:
            d = nxt_read["t"] - r["t"]
            if best is None or d < best[0]:
                best = (d, nxt_read["owner_out"])
        if best:
            r["alt_owner"] = best[1]
    return rows


COLS = ["t", "state", "source", "tier", "verdict", "unit", "owner", "unit_out", "owner_out",
        "alt_owner", "hold_age", "anchored", "vis", "score", "margin", "marker", "card_type",
        "inserted", "reject", "raw", "edge_v", "edge_h", "std", "val"]


def verdict(r):
    """推荐采纳口径（依据 axis_hold_eval_L6.py 的分层回测 + 人工抽样）。"""
    s, tier = r["source"], r["tier"]
    if s == "read":
        return "确定"
    if s == "hold":
        try:
            age = float(r["hold_age"])
        except (TypeError, ValueError):
            age = 0.0
        if age > MAX_ADOPT_AGE:
            return "待复核(外推>%gs)" % MAX_ADOPT_AGE
        if tier == "A":
            return "采纳(外推A)"
        if tier == "C" and "C" in ADOPT_TIERS:
            return "采纳(外推C)"
        if tier == "C":
            return "低可信(外推C)"
        if tier == "B" and "B" in ADOPT_TIERS:
            return "低可信(外推B换人)"
        return "待复核(外推B换人)"
    if s == "enemy":
        return "非我方"
    if s == "aha":
        return "待复核(阿哈)"
    if s == "elation":
        return "待复核(欢愉技卡)"
    return "无"


ADOPTED = ("确定", "采纳(外推A)", "采纳(外推C)", "低可信(外推B换人)")


def is_adopted(r, loose=False):
    """该帧的归属能不能直接被下游当行动者用。

    loose=False（定案口径）：只有 `确定` 与 `采纳(外推A)`。
    loose=True：再算上 `低可信(外推C)`（覆盖率更高，但准确率证据冲突）。
    """
    v = r.get("verdict") or verdict(r)
    if v in ("确定", "采纳(外推A)"):
        return True
    return loose and v == "低可信(外推C)"


# ---- 并表：把线6 的外推列挂到事件表上（《剩余工作清单.md》【线6】尾巴 2）------
L6_COLS = ["l6_t", "l6_dt", "l6_verdict", "l6_source", "l6_tier", "l6_owner", "l6_age",
           "l6_alt_owner", "l6_adopted", "l6_adopted_loose", "l6_agrees", "l6_fills"]


def nearest_row(rows_by_t, ts, t, tol=1.0):
    """1 fps 网格上离 t 最近的那一帧（平局取靠前的；超过 tol 秒算取不到）。"""
    if not ts:
        return None
    import bisect
    i = bisect.bisect_left(ts, t)
    cand = [x for x in (ts[max(0, i - 1):i + 1]) if abs(x - t) <= tol + 1e-9]
    if not cand:
        return None
    cand.sort(key=lambda x: (abs(x - t), x))
    return rows_by_t[cand[0]]


def join_events(events_path, out_path=None, rows=None, tol=1.0):
    """把线6 的 `source/tier/hold_age/alt_owner/verdict` 挂到事件表（线4 或 C 的表）上。

    对齐方式：取事件自己的**归属帧** `actor_t`（没有就退到 `t_anchor`），
    在 1 fps 网格上找**最近的那一帧**，把该帧的线6 结果写成 `l6_*` 列。

    * `l6_owner`：该帧我方归属（敌/阿哈/无 → 空）
    * `l6_adopted`：**定案口径**是否采纳（`确定` 或 `tier A`）；`l6_adopted_loose` 再算上 tier C
    * `l6_agrees`：基表 `owner` 与 `l6_owner` 是否一致（基表没有行动者时为 1）
    * `l6_fills`：基表**没有**行动者、而线6 给出了（外推）→ 这就是线6 给主表加的值
    """
    if rows is None:
        rows = load_rows()
    rows_by_t = {r["t"]: r for r in rows}
    ts = sorted(rows_by_t)
    with open(events_path, encoding="utf-8-sig") as f:
        evs = list(csv.DictReader(f))
    out_rows = []
    n_none = n_base = n_agree = n_fill = n_extrap = 0
    for e in evs:
        rec = dict(e)
        try:
            base_t = float(e.get("actor_t") or e.get("t_anchor"))
        except (TypeError, ValueError):
            base_t = None
        base_owner = (e.get("owner") or "").strip()
        if base_owner:
            n_base += 1
        r = nearest_row(rows_by_t, ts, base_t, tol) if base_t is not None else None
        if r is None:
            n_none += 1
            rec.update({k: "" for k in L6_COLS})
            out_rows.append(rec)
            continue
        ad = is_adopted(r)
        adl = is_adopted(r, loose=True)
        agree = (r["owner_out"] == base_owner) if base_owner and r["owner_out"] else (not base_owner)
        fill = bool(r["owner_out"]) and not base_owner
        n_agree += agree
        n_fill += fill
        n_extrap += (r["source"] == "hold")
        rec.update(l6_t=r["t"], l6_dt=round(r["t"] - base_t, 2), l6_verdict=r["verdict"],
                   l6_source=r["source"],
                   l6_tier=r["tier"], l6_owner=r["owner_out"], l6_age=r["hold_age"],
                   l6_alt_owner=r["alt_owner"], l6_adopted=int(ad), l6_adopted_loose=int(adl),
                   l6_agrees=int(agree), l6_fills=int(fill))
        out_rows.append(rec)
    if out_path:
        cols = list(evs[0].keys()) + L6_COLS
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for rec in out_rows:
                w.writerow({k: rec.get(k, "") for k in cols})
    n = len(evs)
    print("%s（%d 条事件）→ 线6 并表：基表有行动者 %d；与线6 一致 %d (%.1f%%)；"
          "线6 补上空缺 %d 条；其中外推得来的 %d 条；取不到帧 %d"
          % (os.path.basename(events_path), n, n_base, n_agree, 100.0 * n_agree / max(1, n),
             n_fill, n_extrap, n_none))
    return out_rows


def scan(t0=T0, t1=T1, bank=None):
    if bank is None:
        bank = T.load_bank()
    rows = []
    for t in range(t0, t1 + 1):
        p = FRAME % float(t)
        if not os.path.exists(p):
            continue
        rows.append(classify_frame(float(t), bank))
    extrapolate(rows)
    for r in rows:
        r["verdict"] = verdict(r)
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in COLS})
    return rows


def load_rows(path=OUT_CSV):
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["t"] = float(r["t"])
        r["vis"] = int(r["vis"])
        r["anchored"] = str(r.get("anchored", "")).strip().lower() in ("true", "1")
        if r["hold_age"] not in ("", None):
            r["hold_age"] = float(r["hold_age"])
    return rows


def stats(rows, events_path=EVENTS_C):
    n = len(rows)
    import collections
    st = collections.Counter(r["state"] for r in rows)
    src = collections.Counter(r["source"] for r in rows)
    tier = collections.Counter(r["tier"] for r in rows if r["source"] == "hold")
    read = sum(1 for r in rows if r["source"] == "read")
    hold = sum(1 for r in rows if r["source"] == "hold")
    enemy_hold = sum(1 for r in rows if r["source"] == "enemy" and r["state"] != "enemy")
    print("帧数 %d（t=%g~%g）" % (n, rows[0]["t"], rows[-1]["t"]))
    print("状态：" + "  ".join("%s=%d" % kv for kv in sorted(st.items())))
    print("来源：" + "  ".join("%s=%d" % kv for kv in sorted(src.items()))
          + "（其中 enemy 里 %d 帧是外推的敌方动画）" % enemy_hold)
    print("外推层级：" + "  ".join("%s=%d" % kv for kv in sorted(tier.items())))
    print("覆盖率：识别 %.1f%% → 识别+外推 %.1f%%（+%.1f 个百分点，外推 %d 帧）"
          % (100.0 * read / n, 100.0 * (read + hold) / n, 100.0 * hold / n, hold))
    # 外推年龄分布
    ages = [r["hold_age"] for r in rows if r["source"] == "hold"]
    if ages:
        ages = sorted(ages)
        print("外推年龄：中位 %.1fs，最长 %.1fs；<=2s %d 帧，<=3s %d 帧，<=5s %d 帧"
              % (ages[len(ages) // 2], ages[-1],
                 sum(1 for a in ages if a <= 2), sum(1 for a in ages if a <= 3),
                 sum(1 for a in ages if a <= 5)))
    unb = sum(1 for r in rows if r["source"] == "hold" and not r["anchored"])
    print("无后向锚点的外推（尾巴）：%d 帧" % unb)
    # 按推荐口径统计
    vd = collections.Counter(verdict(r) for r in rows)
    print("推荐口径：" + "  ".join("%s=%d" % kv for kv in sorted(vd.items())))
    strict = vd["确定"] + vd["采纳(外推A)"]
    loose = strict + vd["低可信(外推C)"]
    print("覆盖率（我方行动者）：只算确定值 %.1f%% → 确定+A %.1f%% → 确定+A+C %.1f%%"
          % (100.0 * vd["确定"] / n, 100.0 * strict / n, 100.0 * loose / n))
    print("              全部外推（含 B）%.1f%%；非我方（敌/阿哈）%.1f%%"
          % (100.0 * (loose + vd["待复核(外推B换人)"]) / n,
             100.0 * (vd["非我方"] + vd["待复核(阿哈)"] + vd["待复核(欢愉技卡)"]) / n))
    # 事件级
    if events_path and os.path.exists(events_path):
        with open(events_path, encoding="utf-8-sig") as f:
            evs = list(csv.DictReader(f))
        m = {r["t"]: r for r in rows}
        cov_read = cov_all = 0
        detail = []
        for e in evs:
            ta = float(e["t_anchor"])
            # 事件锚点那一帧 + [-1.5s, +0.5s] 窗口内最近的 read / hold 帧（C 线的取法）
            best = None
            for tt in sorted((x for x in m if ta - 1.5 <= x <= ta + 0.5),
                             key=lambda x: (abs(x - ta), 0 if x <= ta else 1)):
                best = m[tt]
                if best["source"] in ("read", "hold"):
                    break
            s = best["source"] if best else "none"
            cov_all += s in ("read", "hold")
            cov_read += s == "read"
            detail.append((e["event"], ta, s, best["unit_out"] if best else ""))
        n_ev = len(evs)
        print("C 线事件 %d 条：锚点窗口内**识别**可得 %d (%.1f%%) → 识别+外推 %d (%.1f%%)"
              % (n_ev, cov_read, 100.0 * cov_read / n_ev, cov_all, 100.0 * cov_all / n_ev))
        miss = [d for d in detail if d[2] not in ("read", "hold")]
        if miss:
            print("  仍无行动者的事件：" + ", ".join("e%s@t%s[%s]" % (d[0], d[1], d[2]) for d in miss))
    return {"n": n, "read": read, "hold": hold}


def _cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--frame", type=float, default=None)
    ap.add_argument("--max-hold", type=float, default=None)
    ap.add_argument("--join", default=None, help="把线6 外推列并到这张事件表上（如 out/events_dense4.csv）")
    ap.add_argument("--out", default=None, help="并表输出路径")
    ap.add_argument("--tier-policy", default=None, help="采纳的 tier，如 A 或 A,B,C（默认 A）")
    args = ap.parse_args()
    if args.tier_policy is not None:
        global ADOPT_TIERS
        ADOPT_TIERS = tuple(x.strip().upper() for x in args.tier_policy.split(",") if x.strip())
    if args.join:
        out = args.out or (os.path.splitext(args.join)[0] + "_L6.csv")
        join_events(args.join, out_path=out)
        return 0
    if args.frame is not None:
        r = classify_frame(args.frame)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    if args.scan:
        rows = scan()
        if args.max_hold is not None:
            extrapolate(rows, max_hold=args.max_hold)
        stats(rows)
        return 0
    stats(load_rows())
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
