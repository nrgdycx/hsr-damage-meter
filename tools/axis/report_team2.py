# -*- coding: utf-8 -*-
"""【线2】录屏2 单位识别器的评估：**留一帧交叉验证** + 阈值/间距标定 + 负向零误报。

口径（照 E 线 `axis_report_E.py`，并遵守项目铁律"只用从未参与判定的帧"）：
  * 留一帧：每次把**这一帧**从模板库里拿掉，再让它去分类 —— 同一角色的**其它帧**仍在库里，
    所以这是"对新人脸"的估计（E 线也是这个口径，便于横向比较）。
  * 负向帧：人工核对过的**非我方单位**帧（敌人/空槽/阿哈面具框/欢愉技卡/未定身份的小组），
    它们与单位库的最高分必须低于阈值，否则就是误报。
  * 阈值扫描：给出 (分数阈值, 与第二名分差阈值) 网格上的"正确数 / 误报数"。

用法：
  python -u axis_report_L2.py                 # 完整报告
  python -u axis_report_L2.py --json out/L2_eval.json
"""
# [P3 整理] 原路径：axis_report_L2.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import glob
import json
import os
import sys

import cv2
import numpy as np

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
sys.path.insert(0, HERE)

import axis_actor as T          # noqa: E402
import axis_actor_team2 as T2        # noqa: E402


def load_labels(path=T2.LABELS_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def all_ally_frames():
    """frames/axis2_L2 里所有"左标记=我方"的帧号（含未定身份的小组）。"""
    out = []
    for p in sorted(glob.glob(os.path.join(T2.CROP_DIR, "*_top.png"))):
        t = float(os.path.basename(p)[1:9])
        try:
            mk = T2.marker_of(T2.load_crop(t))[0]
        except Exception:                       # noqa: BLE001
            continue
        if mk.startswith("ally"):
            out.append(t)
    return out


def leave_one_out(labels):
    """留一帧：返回 [(t, 真值, 预测 or None, 分数, 间距, 次名)]"""
    rows = []
    for unit in T2.UNITS:
        for t in labels.get(unit, []):
            bank = {}
            for u2 in T2.UNITS:
                mats = []
                for t2 in labels.get(u2, []):
                    if float(t2) == float(t):
                        continue
                    c = T2.load_crop(t2)
                    for z in T.ZOOMS:
                        mats.append(T2.feats_top_zoom(c, z))
                if mats:
                    bank[u2] = np.stack(mats)
            r = T2.read_actor(t, bank)
            rows.append({"t": float(t), "truth": unit, "pred": r["unit"],
                         "score": r["score"], "margin": r["margin"],
                         "second": sorted(r["scores"].items(), key=lambda kv: -kv[1])[1][0],
                         "card_type": r["card_type"]})
    return rows


def negatives(labels, bank):
    """负向帧（非单位卡）与单位库的最高分。"""
    neg = []
    for k, ts in (labels.get("_pending") or {}).items():
        for t in ts:
            try:
                r = T2.read_actor(t, bank)
            except FileNotFoundError:
                continue
            neg.append({"t": float(t), "group": k, "score": r["score"], "margin": r["margin"],
                        "best": r["raw"], "marker": r["marker"], "card_type": r["card_type"],
                        "accepted": r["unit"] is not None})
    # 另外把"非我方"帧（敌人/空/阿哈/欢愉技）也算进来
    for p in sorted(glob.glob(os.path.join(T2.CROP_DIR, "*_top.png"))):
        t = float(os.path.basename(p)[1:9])
        try:
            c = T2.load_crop(t)
            mk = T2.marker_of(c)[0]
        except Exception:                       # noqa: BLE001
            continue
        if mk.startswith("ally") or mk == "empty":
            continue
        r = T2.read_actor(t, bank)
        neg.append({"t": t, "group": "marker=%s" % mk, "score": r["score"],
                    "margin": r["margin"], "best": r["raw"], "marker": mk,
                    "card_type": r["card_type"], "accepted": r["unit"] is not None})
    return neg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    ap.add_argument("--no-neg", action="store_true")
    args = ap.parse_args()
    labels = load_labels()
    bank = T2.load_bank()
    print("模板库 %s：%s（共 %d 帧 × %d 缩放态）"
          % (T2.BANK_PATH, {u: m.shape[0] // len(T.ZOOMS) for u, m in bank.items()},
             sum(m.shape[0] for m in bank.values()) // len(T.ZOOMS), len(T.ZOOMS)))

    rows = leave_one_out(labels)
    n_all = len(rows)
    per = {}
    for r in rows:
        d = per.setdefault(r["truth"], {"n": 0, "ok": 0})
        d["n"] += 1
        d["ok"] += (r["pred"] == r["truth"])
    print("\n== 留一帧交叉验证（阈值 %.2f / 间距 %.2f，即当前模块默认）==" % (T2.THR, T2.MIN_MARGIN))
    for u in T2.UNITS:
        d = per.get(u, {"n": 0, "ok": 0})
        print("  %-4s  %2d/%2d  %s" % (u, d["ok"], d["n"],
                                       "%.1f%%" % (100.0 * d["ok"] / d["n"]) if d["n"] else "-"))
    ok = sum(d["ok"] for d in per.values())
    print("  合计  %d/%d = %.1f%%" % (ok, n_all, 100.0 * ok / n_all))
    recall = [r for r in rows if r["pred"] is not None]
    print("  给出结论的帧里正确率：%d/%d = %.1f%%"
          % (sum(1 for r in recall if r["pred"] == r["truth"]), len(recall),
             100.0 * sum(1 for r in recall if r["pred"] == r["truth"]) / max(1, len(recall))))
    conf = {}
    for r in rows:
        if r["pred"] is not None and r["pred"] != r["truth"]:
            conf[(r["truth"], r["pred"])] = conf.get((r["truth"], r["pred"]), 0) + 1
    if conf:
        print("  混淆（真值→预测）：%s" % {"%s→%s" % k: v for k, v in conf.items()})

    # 阈值 × 间距 网格
    print("\n== 阈值网格（左上=分数阈值，括号内=该阈值下'给结论帧数/其中正确数'）==")
    print("        " + "".join("mar=%.2f   " % m for m in (0.30, 0.45, 0.60)))
    for thr in (0.70, 0.80, 0.85, 0.90, 0.95, 1.00):
        cells = []
        for mar in (0.30, 0.45, 0.60):
            acc = sum(1 for r in rows if r["pred"] == r["truth"]
                      and r["score"] >= thr and r["margin"] >= mar)
            got = sum(1 for r in rows if r["score"] >= thr and r["margin"] >= mar)
            cells.append("%2d/%-2d     " % (acc, got))
        print("  %.2f  %s" % (thr, "".join(cells)))

    res = {"per_unit": per, "loo_ok": ok, "loo_n": n_all,
           "thresholds": {"THR": T2.THR, "MIN_MARGIN": T2.MIN_MARGIN}}
    if not args.no_neg:
        neg = negatives(labels, bank)
        mx = max(neg, key=lambda x: x["score"]) if neg else None
        print("\n== 负向（非单位卡）%d 帧 ==" % len(neg))
        if mx:
            print("  最高分：%.2f（t=%s，%s，判为 %s）" % (mx["score"], T.fmt_t(mx["t"]),
                                                        mx["group"], mx.get("best")))
            top = sorted(neg, key=lambda x: -x["score"])[:8]
            for x in top:
                print("    %.2f  t=%-7s %-18s 判为 %-5s 标记%-14s 类型%s"
                      % (x["score"], T.fmt_t(x["t"]), x["group"], x["best"], x["marker"],
                         x["card_type"]))
            over = [x for x in neg if x["accepted"]]
            print("  **管线最终采纳的负向帧**：%d 个%s" % (len(over),
                                                     "（应为 0）" if over else "  ✓ 零误报"))
            for x in over:
                print("     !! t=%s %s → 判为 %s（分数%.2f 间距%.2f 标记%s）"
                      % (T.fmt_t(x["t"]), x["group"], x["best"], x["score"], x["margin"],
                         x["marker"]))
        res["neg_max"] = mx["score"] if mx else None
        res["neg_n"] = len(neg)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({**res, "rows": rows}, f, ensure_ascii=False, indent=1)
        print("\n已写出 %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
