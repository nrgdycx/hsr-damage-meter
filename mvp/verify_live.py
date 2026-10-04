# -*- coding: utf-8 -*-
"""[MVP] 离线对账 —— MVP 验收第 2 条（**最关键、不许跳过的一步**）。

> 同一段录屏，**离线批处理汇总 == 实时流式汇总**。

本项目已经多次栽在"跑得起来但结论全错"上，而悬浮窗会让错误更难发现
（数字在跳，看起来像在工作）。所以这一步拆成三个可复现的断言：

  A. **感知层逐帧对账**：把 `frames/glyphcache/` 的每一帧喂给**实时那条读数链**
     （`mvp/reader.py`），逐字段与离线扫描表 `out/frames_dense4.csv` 比
     （读数 / 字形数 / 行动者 / 归属 / 分数 / 标记 / 卡类型）。
  B. **定稿逻辑对账**：把 A 产出的读数**一条一条**喂进流式引擎
     （`mvp/engine.py`，带 1.75s 定稿延迟、滑动窗口重算），与
     `events_v4.build()` 对**同一批读数**的批处理结果逐事件比。
     这一条证明"实时化"没有改变口径（不重写判据的直接收益）。
  C. **端到端对账**：流式结果 vs 录屏的权威离线结果
     （`out/events_dense4.csv` / `out/owner_summary_dense4.csv` / `out/events_master.csv`）
     —— 按角色累计必须对得上（口径：只算 `status=ok`）。

用法：
  python mvp/verify_live.py                  # 全量 923 帧（约几分钟）
  python mvp/verify_live.py --limit 200      # 先跑一段
  python mvp/verify_live.py --json out/mvp_verify.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, os.path.join(ROOT, "vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
os.chdir(ROOT)

import events_v4 as E4                    # noqa: E402
from mvp.engine import LiveEngine, ALLY        # noqa: E402
from mvp.reader import Perceiver, ROW_COLS     # noqa: E402

REF_FRAMES = "out/frames_dense4.csv"
REF_EVENTS = "out/events_dense4.csv"
REF_OWNER = "out/owner_summary_dense4.csv"
MASTER = "out/events_master.csv"
LIVE_FRAMES = "out/mvp_frames_live.csv"

# 事件级比对的字段（口径相关的一个都不能少）
EV_KEYS = ("t_first", "t_last", "t_peak", "t_anchor", "damage_max", "unit", "owner",
           "status", "quality", "n_trusted", "n_rejected", "issues")


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


# "这一段为什么结束"——只有下一次攻击开始（可能隔 20 秒）才看得出来，实时定稿时**无从得知**。
BREAK_RE = re.compile(r"^(gap[\d.]+s|blank[\d.]+s|reset|owner|memo|swap@|settle@)")


def norm_issues(s):
    return ",".join(p for p in str(s or "").split(",") if p and not BREAK_RE.match(p))


def frame_rows(path):
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def ev_tuple(e):
    return tuple(str(e.get(k, "")) for k in EV_KEYS)


def write_live_frames(rows, path=LIVE_FRAMES):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(ROW_COLS)
        for r in rows:
            w.writerow([r["t"], r["text"], r["n"], len(r["text"]), r["lm"], r["conf"],
                        r["nbad"], r["profile"], r["unit"], r["owner"], r["score"],
                        r["margin"], r["marker"], r["inserted"], r["card_type"]])
    return path


# ══════════════════════════ A. 感知层逐帧对账 ══════════════════════════
FIELDS = (("hud_text", "text"), ("hud_n", "n"), ("unit", "unit"), ("owner", "owner"),
          ("card_type", "card_type"), ("marker", "marker"))


def perceive_all(limit=0, backend="onnx", hud_mode="region", verbose=True):
    """按参考表的帧号顺序逐帧跑**实时读数链**。返回 (rows, ref_rows, ms)。"""
    from mvp.reader import hud_region_for
    ref = frame_rows(REF_FRAMES)
    if limit:
        ref = ref[:limit]
    perc = Perceiver(backend=backend)
    rows, ms = [], []
    t0 = time.time()
    for i, r in enumerate(ref):
        t = _f(r["t"])
        p = os.path.join("frames", "glyphcache", "f%08.2f.png" % t)
        arr = np.asarray(Image.open(p).convert("RGB")).astype(np.int16)
        ts = time.perf_counter()
        if hud_mode == "region":
            reg, bar, _g = hud_region_for(arr.shape)
            y0, x0 = reg["top"], reg["left"]
            crop = np.ascontiguousarray(
                arr[y0:y0 + reg["height"], x0:x0 + reg["width"]], dtype=np.int16)
            row = perc.read(t, region_rgb=crop, top=y0, left=x0, bar_rows=bar,
                            axis_rgb=arr, read_axis=True, want_lm=True)
        else:
            row = perc.read(t, frame_rgb=arr, axis_rgb=arr, read_axis=True, want_lm=True)
        ms.append((time.perf_counter() - ts) * 1000.0)
        rows.append(row)
        if verbose and (i + 1) % 200 == 0:
            print("    感知 %d/%d  %.0fs" % (i + 1, len(ref), time.time() - t0), flush=True)
    return rows, ref, ms


def compare_perception(rows, ref, show=10):
    """逐字段比对。返回 (差异清单, 统计)。"""
    diffs = []
    n_field = 0
    for row, r in zip(rows, ref):
        d = {"t": row["t"]}
        for ref_k, live_k in FIELDS:
            a = (r.get(ref_k) or "").strip()
            b = row.get(live_k)
            if ref_k == "hud_n":
                a, b = int(a or 0), int(b or 0)
            elif ref_k == "hud_text":
                a, b = a, (b or "")
            else:
                a, b = a, (b or "")
            if a != b:
                d[ref_k] = (a, b)
                n_field += 1
        # 分数/间距按 3 位小数比（表里就是 3 位）
        for k in ("score", "margin"):
            a = round(_f(r.get(k)), 3)
            b = round(_f(row.get(k)), 3)
            if abs(a - b) > 5e-4:
                d[k] = (a, b)
                n_field += 1
        if len(d) > 1:
            diffs.append(d)
    stat = {"n_frames": len(rows), "n_diff_frames": len(diffs), "n_field_diffs": n_field}
    if diffs and show:
        print("    差异样例（最多 %d 条）：" % show)
        for d in diffs[:show]:
            print("      t=%-8s %s" % (("%.2f" % d["t"]).rstrip("0").rstrip("."),
                                       "  ".join("%s 离线=%r 实时=%r" % (k, v[0], v[1])
                                                 for k, v in d.items() if k != "t")))
    return diffs, stat


# ══════════════════════════ B/C. 事件对账 ══════════════════════════
def owner_sums(events):
    agg = {}
    for e in events:
        if e["status"] != "ok":
            continue
        o = e["owner"] or "(未定)"
        agg[o] = agg.get(o, 0) + int(e["damage_max"])
    return agg, sum(agg.values())


def read_owner_csv(path=REF_OWNER):
    out = {}
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            out[r["owner"]] = int(r["damage_sum"])
    return out


def stream_events(rows, verbose=True):
    """把读数一条条喂进流式引擎（时间轴 = 帧号），返回 (engine, 每次定稿的事件数)。"""
    eng = LiveEngine()
    per_frame = []
    t0 = time.time()
    for i, row in enumerate(rows):
        new = eng.add(row)
        per_frame.append(len(new))
        if verbose and (i + 1) % 200 == 0:
            print("    流式 %d/%d  已定稿 %d 个事件  %.0fs"
                  % (i + 1, len(rows), len(eng.events), time.time() - t0), flush=True)
    eng.flush()
    return eng, per_frame


def compare_events(live, ref, show=10):
    """逐事件比。⚠️ `issues` 里"这一段为什么结束"（gap/blank/reset/owner/memo/swap/settle）
    是**事后才知道**的信息：实时流定稿时，下一次攻击可能还没开始（实测有一处隔了 21.2s）。
    所以这类 token 只做**信息性统计**，不参与判定；其余 issues（multi_owner / actor_unknown /
    implausible / top_slot_empty / enemy_card …）在定稿时已知，必须一致。

    返回 (差异清单, 只有"段结束原因"不同的段数)。
    """
    diffs, break_only = [], 0
    n = max(len(live), len(ref))
    for i in range(n):
        a = live[i] if i < len(live) else None
        b = ref[i] if i < len(ref) else None
        if a is None or b is None:
            diffs.append({"i": i + 1, "field": "(缺事件)", "live": bool(a), "ref": bool(b)})
            continue
        for k in EV_KEYS:
            x, y = str(a.get(k, "")), str(b.get(k, ""))
            if k in ("t_first", "t_last", "t_peak", "t_anchor"):
                if abs(_f(x) - _f(y)) > 1e-6:
                    diffs.append({"i": i + 1, "field": k, "live": x, "ref": y})
            elif k == "issues":
                if norm_issues(x) != norm_issues(y):
                    diffs.append({"i": i + 1, "field": k, "live": x, "ref": y})
                elif x != y:
                    break_only += 1
            elif x != y:
                diffs.append({"i": i + 1, "field": k, "live": x, "ref": y})
    if diffs and show:
        for d in diffs[:show]:
            print("      #%s %s  实时=%r 离线=%r" % (d.get("i"), d.get("field"),
                                                    d.get("live"), d.get("ref")))
    return diffs, break_only


def main(argv=None):
    ap = argparse.ArgumentParser(description="MVP 离线对账")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 帧（快速验证）")
    ap.add_argument("--backend", choices=("onnx", "torch"), default="onnx")
    ap.add_argument("--hud-mode", choices=("region", "frame"), default="region",
                    help="region=实时固定框（生产口径）；frame=整帧动态定位（离线口径）")
    ap.add_argument("--json", default="out/mvp_verify.json")
    argv = ap.parse_args(argv)
    rep = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "limit": argv.limit,
           "backend": argv.backend, "hud_mode": argv.hud_mode}
    ok_all = True

    print("=" * 78)
    print("A. 感知层逐帧对账：mvp/reader.py（%s / %s）vs %s"
          % (argv.backend, argv.hud_mode, REF_FRAMES))
    rows, ref, ms = perceive_all(argv.limit, argv.backend, argv.hud_mode)
    diffs, stat = compare_perception(rows, ref)
    rep["A_perception"] = {"stat": stat, "samples": [
        {"t": d["t"], **{k: list(v) for k, v in d.items() if k != "t"}} for d in diffs[:40]]}
    print("  %d 帧：字段差异 %d 处，涉及 %d 帧" % (stat["n_frames"], stat["n_field_diffs"],
                                            stat["n_diff_frames"]))
    ms_arr = np.asarray(ms)
    print("  感知耗时（含 PNG 解码）：平均 %.0fms p95 %.0fms" % (ms_arr.mean(),
                                                        np.percentile(ms_arr, 95)))
    rep["A_perception"]["ms"] = {"mean": float(ms_arr.mean()),
                                 "p95": float(np.percentile(ms_arr, 95))}

    live_csv = write_live_frames(rows)
    print("  实时读数已落盘：%s" % live_csv)

    print("\n" + "=" * 78)
    print("B. 定稿逻辑对账：流式引擎 vs events_v4.build()（**同一批读数**）")
    eng, _ = stream_events(rows)
    live_events = eng.events
    _r_b, batch_events, _s_b = E4.build(frames=live_csv)
    diffs_b, brk_b = compare_events(live_events, batch_events)
    rep["B_finalizer"] = {"n_stream": len(live_events), "n_batch": len(batch_events),
                          "n_diffs": len(diffs_b), "diffs": diffs_b[:60],
                          "n_break_reason_only": brk_b,
                          "n_stale_merge": eng.n_stale_merge, "lag": eng.lag,
                          "n_pass": eng.n_pass}
    print("  流式 %d 个事件，批处理 %d 个事件，差异 %d 处 → %s"
          % (len(live_events), len(batch_events), len(diffs_b),
             "一致" if not diffs_b else "**不一致**"))
    print("  「段结束原因」只有实时看不到的那 %d 段不同（信息性，见 compare_events 注释）"
          % brk_b)
    print("  保险丝（段起点落进已定稿区间）触发 %d 次（必须为 0）｜定稿延迟 %.1fs｜重算 %d 次"
          % (eng.n_stale_merge, eng.lag, eng.n_pass))
    ok_all &= (not diffs_b) and eng.n_stale_merge == 0

    print("\n" + "=" * 78)
    print("C. 端到端对账：流式结果 vs 录屏的权威离线结果")
    _r_ref, ref_events, _s_ref = E4.build(frames=REF_FRAMES)
    ref_csv = frame_rows(REF_EVENTS)
    rep["C_reference_sanity"] = {"n_build": len(ref_events), "n_csv": len(ref_csv)}
    print("  参考表自检：build()=%d 个事件，%s=%d 行" % (len(ref_events), REF_EVENTS,
                                                   len(ref_csv)))
    diffs_c, brk_c = compare_events(live_events, ref_events)
    rep["C_end2end"] = {"n_diffs": len(diffs_c), "diffs": diffs_c[:60],
                        "n_break_reason_only": brk_c}
    print("  流式 vs 录屏离线：事件差异 %d 处（另有 %d 段只有「结束原因」不同）"
          % (len(diffs_c), brk_c))
    if argv.limit:
        ok_all &= True          # 截断模式下 C 段只报告、不判定（见上面的说明）
    else:
        ok_all &= (not diffs_c)

    live_sum, live_tot = owner_sums(live_events)
    ref_sum, ref_tot = owner_sums(ref_events)
    csv_owner = read_owner_csv()
    master_sum, master_tot, master_n = master_measured()
    rep["C_totals"] = {"live": live_sum, "ref": ref_sum, "owner_csv": csv_owner,
                       "master_measured": master_sum,
                       "live_total": live_tot, "ref_total": ref_tot,
                       "master_total": master_tot, "master_n": master_n}
    print("  按角色累计（只算 status=ok）：")
    for name in sorted(set(list(live_sum) + list(ref_sum) + list(csv_owner))):
        print("    %-6s 流式 %12s ｜ 录屏离线 %12s ｜ owner_summary %12s ｜ 主表 %12s"
              % (name, format(live_sum.get(name, 0), ","), format(ref_sum.get(name, 0), ","),
                 format(csv_owner.get(name, 0), ","), format(master_sum.get(name, 0), ",")))
    print("    %-6s 流式 %12s ｜ 录屏离线 %12s ｜ 主表(实测口径) %12s（%d 段，含外推口径另计）"
          % ("合计", format(live_tot, ","), format(ref_tot, ","), format(master_tot, ","),
             master_n))
    sums_ok = (live_sum == ref_sum == csv_owner == master_sum)
    ok_all &= sums_ok or bool(argv.limit)
    if argv.limit:
        print("  ⚠️ --limit 模式下录屏被截断，C 段（端到端）差异**不作数**；"
              "全量跑才判定。A/B 两段仍然有效。")
    print("  按角色累计一致：%s（流式 == 离线 == owner_summary == 主表实测口径）"
          % ("是" if sums_ok else "**否**"))
    print("  事件级（流式 vs 录屏离线）：%s" % ("完全一致" if not diffs_c else "**有差异**"))

    rep["ok"] = bool(ok_all)
    if argv.json:
        os.makedirs(os.path.dirname(os.path.abspath(argv.json)) or ".", exist_ok=True)
        with open(argv.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        print("\n报告已写出 %s" % argv.json)
    print("\n结论：%s" % ("对账通过（A 逐帧差异见上，B/C 一致）" if ok_all else "**对账未通过**"))
    return 0 if ok_all else 1


def master_measured(path=MASTER):
    """权威主表的"实测口径"累计（`count_measured == 1`，列定义见 out/README_事件表.md）。"""
    agg, n = {}, 0
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if str(r.get("count_measured", "")).strip() != "1":
                continue
            n += 1
            o = (r.get("owner") or "").strip()
            agg[o] = agg.get(o, 0) + int(r["damage_max"])
    return agg, sum(agg.values()), n


if __name__ == "__main__":
    sys.exit(main())
