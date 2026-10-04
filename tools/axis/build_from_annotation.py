# -*- coding: utf-8 -*-
"""把"按场次指认"（battle_sheet 的产物 + 用户填的名字）建成模板库条目。

流程（与 harvest_characters / battle_sheet 同一套口径）
------------------------------------------------------
  1. 读 `frames/harvest_<队名>/cards/t%08.2f.png`
  2. 按 --gap 切战斗段；段内**全链**聚类（不许偷偷并人）
  3. 每组的代表时刻 → 对齐到 `--names`（`out/teams/*_by_time.json` 的 identities[时刻]）
  4. 每个身份做**最远点采样**选 ≤--max-frames 帧（比等间隔取样覆盖面更好）
  5. 特征按 `T.ZOOMS`（两态，与库内既有条目同口径）→ `axis_onboard.merge_banks` 并入共享库

为什么每个身份只取少量模板
--------------------------
模板越多，实时匹配越慢（整帧预算是 <100 ms，当前 517 张模板约 21 ms）。
而同一场战斗里同一角色的卡几乎逐像素相同 —— 取 10 张的覆盖面已足够，多取只拖慢实时。
选帧用最远点采样而不是等间隔：等间隔可能反复取到同一状态。

用法
----
    python tools/axis/build_from_annotation.py --team rec1003_1640 \
        --names out/teams/rec1640_by_time.json [--max-frames 10] [--dry-run] [--eval]
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import axis_actor as T                      # noqa: E402
from harvest_characters import art_of_card, feat_fft, pair_score_shift   # noqa: E402
from battle_sheet import cluster_within as bs_cluster, ZOOM_PEN          # noqa: E402
import axis_onboard                          # noqa: E402

GAP = 12.0
CLUSTER_THR = 1.30
MIN_GROUP = 3
SPLIT_THR = 1.60        # 混合物拆分的门槛：对"别的身份"的卡达到这个分就改判过去


def imread_u(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def feats_of_art(art, z):
    """与 `axis_onboard.feats_of_art` 同口径（缩放态缩放逻辑照抄 `T.feats_art`）。"""
    if z != 1.0:
        h, w = art.shape[:2]
        r = cv2.resize(art, (max(2, int(round(w * z))), max(2, int(round(h * z)))),
                       interpolation=cv2.INTER_AREA if z < 1 else cv2.INTER_LINEAR)
        if r.shape[0] >= h and r.shape[1] >= w:
            y0, x0 = (r.shape[0] - h) // 2, (r.shape[1] - w) // 2
            r = r[y0:y0 + h, x0:x0 + w]
        else:
            r = cv2.copyMakeBorder(r, 0, max(0, h - r.shape[0]), 0, max(0, w - r.shape[1]),
                                   cv2.BORDER_REPLICATE)
        art = r
    return T.feats(art)


def load_cards(cdir):
    ts, names = [], []
    for f in sorted(os.listdir(cdir)):
        if f.endswith(".png"):
            ts.append(float(f[1:9]))
            names.append(f)
    return list(ts), names


def segments(ts, gap):
    order = np.argsort(ts)
    segs, cur = [], [order[0]]
    for k in order[1:]:
        if ts[k] - ts[cur[-1]] > gap:
            segs.append(cur)
            cur = []
        cur.append(k)
    segs.append(cur)
    return [s for s in segs if len(s) >= 4]


def cluster_within(seg, M, thr):
    sub = M[np.ix_(seg, seg)]
    order = np.argsort(-sub.mean(axis=1))
    groups = []
    for i in order:
        best, bj = -9.0, -1
        for j, g in enumerate(groups):
            sc = sub[i, g]
            if float(sc.min()) >= thr and float(sc.mean()) > best:
                best, bj = float(sc.mean()), j
        (groups[bj].append(i) if bj >= 0 else groups.append([i]))
    return [[seg[i] for i in g] for g in groups]


def farthest_point(arts, k):
    """最远点采样：在 ≤k 的预算下尽量覆盖不同的状态。返回下标。"""
    n = len(arts)
    if n <= k:
        return list(range(n))
    F = [T.feats(a).ravel() for a in arts]
    F = np.asarray(F, np.float32)
    F = F / np.maximum(1e-6, np.linalg.norm(F, axis=1, keepdims=True))
    S = F @ F.T
    sel = [int(np.argmax(S.mean(axis=1)))]
    while len(sel) < k:
        far = S[:, sel].max(axis=1)
        far[sel] = 9.9
        sel.append(int(np.argmin(far)))
    return sorted(sel)


def split_mixed(ts, names, cdir, assign, segs_all, by_battle, thr):
    """同一场里，某组的卡若对**别的组**的卡明显更像（≥thr），就改判到那个组。

    只在"该场的分组数 == 指认数"的前提下工作（此时每组的身份已知）。
    返回被改判的卡数。
    """
    moved = 0
    for si, seg in enumerate(segs_all):
        units_here = {}
        for i in seg:
            if i in assign:
                units_here.setdefault(assign[i], []).append(i)
        if len(units_here) < 2:
            continue
        # 每张卡的特征（原态）只算一次
        feats = {}
        for i in seg:
            if i in assign:
                feats[i] = T.feats(art_of_card(imread_u(os.path.join(cdir, names[i]))))
        for unit, idxs in list(units_here.items()):
            others = [(u, v) for u, v in units_here.items() if u != unit]
            for i in list(idxs):
                # 对"别的身份"的最高分（各身份取若干张代表就够，避免 O(n²)）
                best_u, best_v = None, -9.0
                for u, v in others:
                    for j in v[:30]:
                        sc = T.pair_score(feats[i], feats[j])
                        if sc > best_v:
                            best_v, best_u = sc, u
                if best_u and best_v >= thr:
                    assign[i] = best_u
                    idxs.remove(i)
                    moved += 1
    return moved


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(description="按场次指认 → 建模板库条目")
    ap.add_argument("--team", required=True)
    ap.add_argument("--names", required=True, help="out/teams/*_by_time.json")
    ap.add_argument("--cards", default=None)
    ap.add_argument("--bank", default=None)
    ap.add_argument("--max-frames", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--eval", action="store_true", help="建库后跑留出帧评估（诚实口径）")
    args = ap.parse_args(argv)

    cdir = args.cards or os.path.join(ROOT, "frames", "harvest_%s" % args.team, "cards")
    bank_path = args.bank or T.BANK_PATH
    ts, names = load_cards(cdir)
    print("卡面 %d 张（%s）\n模板库 %s" % (len(ts), cdir, bank_path))

    with open(args.names, encoding="utf-8-sig") as f:
        nd = json.load(f)
    # identities 的第 5 个元素（若有）= **库条目名**：同一角色的多个形态写同一个条目名，
    # 库里并成一条（"局内多形态"就靠它表达，不再靠字符串后缀去猜）。
    by_battle = []
    for b in nd["battles"]:
        by_battle.append([(it[0], it[4] if len(it) > 4 and it[4] else it[0])
                          for it in b.get("identities", [])])
    print("已指认 %d 场 / %d 条身份（%s）"
          % (len(by_battle), sum(len(x) for x in by_battle), args.names))

    # ⚠️ 组↔身份的对应必须用**与 battle_sheet 同一套排序**：
    #    组按"最早时刻"排序、过滤掉 <MIN_GROUP 的碎片，然后与该场的身份**按顺序**一一对应。
    #    （曾用"组内第一个成员的时刻"去就近匹配 —— 那个成员不是按时间排的，
    #      实测 8 组 / 250 张卡对不上身份，只建出 27 个条目。）
    assign = {}
    frag = 0
    segs_all = segments(ts, GAP)
    if len(segs_all) != len(by_battle):
        print("  ！战斗段数 %d 与指认场数 %d 不一致，请核对 --gap"
              % (len(segs_all), len(by_battle)))
    for si, seg in enumerate(segs_all):
        arts = [art_of_card(imread_u(os.path.join(cdir, names[i]))) for i in seg]
        FF1 = [feat_fft(T.feats(a)) for a in arts]
        FF2 = [feat_fft(feats_of_art(a, T.ZOOMS[1])) for a in arts]
        n = len(seg)
        M = np.eye(n, dtype=np.float32)
        for i in range(n):
            for j in range(i + 1, n):
                # ⚠️ 必须与 battle_sheet.sim_matrix **完全同口径**（含放大态补偿），
                #    否则分组数与出表时不一致 → 名字会错位。
                v = max(pair_score_shift(FF1[i], FF1[j]),
                        pair_score_shift(FF1[i], FF2[j]) - ZOOM_PEN,
                        pair_score_shift(FF2[i], FF1[j]) - ZOOM_PEN,
                        pair_score_shift(FF2[i], FF2[j]))
                M[i, j] = M[j, i] = v
        allg = bs_cluster(list(range(n)), M, CLUSTER_THR)
        good = [g for g in allg if len(g) >= MIN_GROUP]
        good.sort(key=lambda g: min(ts[seg[i]] for i in g))
        frag += sum(len(g) for g in allg if len(g) < MIN_GROUP)
        names_here = by_battle[si] if si < len(by_battle) else []
        if len(good) == len(names_here):
            for g, (disp, unit) in zip(good, names_here):
                for i in g:
                    assign[seg[i]] = unit
        else:
            # 兜底：用**时间包含**法（不依赖数量一致），并明确告警
            print("  ！第%d场：分组 %d 个 vs 指认 %d 个 —— 改用时间包含法对应"
                  % (si + 1, len(good), len(names_here)))
            for (disp, unit), t_json in zip(names_here,
                                  [float(it[2]) for it in nd["battles"][si]["identities"]]):
                cand = []
                for g in good:
                    lo = min(ts[seg[i]] for i in g)
                    hi = max(ts[seg[i]] for i in g)
                    if lo - 1.0 <= t_json <= hi + 1.0:
                        cand.append(g)
                if not cand:
                    g = min(good, key=lambda g: abs(
                        (min(ts[seg[i]] for i in g) + max(ts[seg[i]] for i in g)) / 2 - t_json))
                    print("      「%s」(t=%.0f) 不在任何组的时间范围内 → 就近取组" % (disp, t_json))
                else:
                    g = max(cand, key=len)
                for i in g:
                    assign[seg[i]] = unit
    print("已归属 %d 张；未归属（碎片）%d 张" % (len(assign), len(ts) - len(assign)))

    # ── 修"混合物格"：同一场里，某组的卡若对**别的组**的卡更像（≥SPLIT_THR），就搬过去 ──
    # 实测第 7 场最后一格是「金闪闪 + 杰帕德」混在一起（两者都是金发，complete linkage
    # 分不开），结果金闪闪条目的模板里混进了杰帕德的卡 → 留出帧全弃权。
    moved = split_mixed(ts, names, cdir, assign, segs_all, by_battle, SPLIT_THR)
    if moved:
        print("  混合物修正：搬走 %d 张" % moved)

    # ── 碎片：按 JSON `fragments` 的**时间顺序**逐张对位（与出表同一套排序）──
    #    特殊值：「（不入库）」= 不是角色（场地效果等）；「（自动匹配）」= 拿库内已有条目认。
    #    ⚠️ 这张表原来只报"另有 N 张碎片"不显示内容，用户据此问过"为什么少了姬子·启行" ——
    #       少的人就躺在碎片里，所以碎片必须能逐张落名字。
    # ── 显式按时刻指定的卡（不依赖碎片顺序）──
    # 用途：被质量闸误杀、事后补进 cards 目录的卡（例：龙灵 t=309.x）。
    # 加了卡会改变聚类，所以**不能**靠"往 fragments 末尾追加名字"来对位（实测会把名字贴到别的卡上）。
    for t_extra, unit_extra in (nd.get("extra_cards") or []):
        k = int(np.argmin([abs(x - float(t_extra)) for x in ts]))
        if abs(ts[k] - float(t_extra)) <= 0.25:
            assign[k] = unit_extra
            print("    指定 t=%.1f → 「%s」" % (ts[k], unit_extra))
        else:
            print("    ！extra_cards t=%.1f 找不到对应卡（最近 %.1f）" % (t_extra, ts[k]))

    unknown_left = []
    flist = nd.get("fragments") or []
    bank_now = None
    W4 = np.array([T.W_GRAY, T.W_GRAD, T.W_COLOR / 2, T.W_COLOR / 2], np.float32)

    def auto_match(i):
        """拿**库内已有条目**认这张卡（阈值/间距与实时一致，认不出返回 None）。"""
        nonlocal bank_now
        if bank_now is None:
            with np.load(bank_path) as z:
                bank_now = {k: z[k] for k in z.files}
        art = art_of_card(imread_u(os.path.join(cdir, names[i])))
        f1 = T.feats(art)
        f2 = feats_of_art(art, T.ZOOMS[1])
        sc = {}
        for u, mats in bank_now.items():
            best = -9.0
            for m in mats:
                for ff in (f1, f2):
                    best = max(best, float(W4[0] * (m[0] * ff[0]).mean()
                                           + W4[1] * (m[1] * ff[1]).mean()
                                           + W4[2] * (m[2] * ff[2]).mean()
                                           + W4[3] * (m[3] * ff[3]).mean()))
            sc[u] = best
        rank = sorted(sc.items(), key=lambda kv: -kv[1])
        top, val = rank[0]
        gap = val - rank[1][1]
        return (top, val, gap) if (val >= 1.45 and gap >= 0.45) else (None, val, gap)

    # ⚠️ 用**时刻**指定碎片，不用顺序：加了卡会改变贪心聚类的顺序，
    #    顺序法实测把「龙灵」贴到了 t=262 的灰发角色上（污染了一整个条目）。
    for item in flist:
        t_want, nm = float(item[0]), item[1]
        k = int(np.argmin([abs(x - t_want) for x in ts]))
        if abs(ts[k] - t_want) > 0.25:
            print("    ！fragments t=%.1f 找不到对应卡（最近 %.1f）" % (t_want, ts[k]))
            continue
        if nm == "（不入库）":
            print("    碎片 t=%.1f → 不入库（用户标注：不是角色）" % ts[k])
            continue
        if nm == "（自动匹配）":
            top, val, gap = auto_match(k)
            if top:
                assign[k] = top
                print("    碎片 t=%.1f → 自动匹配「%s」(%.2f 间距%.2f)" % (ts[k], top, val, gap))
            else:
                unknown_left.append((float(ts[k]), "?", round(val, 3), round(gap, 3)))
            continue
        assign[k] = nm
        print("    碎片 t=%.1f → 「%s」" % (ts[k], nm))

    # 其余**所有**未归属的卡：一律自动匹配（认不出就报出来，不静默吞掉）
    for i in range(len(ts)):
        if i in assign:
            continue
        top, val, gap = auto_match(i)
        if top:
            assign[i] = top
            print("    未归属 t=%.1f → 自动匹配「%s」(%.2f 间距%.2f)" % (ts[i], top, val, gap))
        else:
            unknown_left.append((float(ts[i]), "?", round(val, 3), round(gap, 3)))
    if unknown_left:
        print("  ⚠ 认不出的碎片（时刻/最像谁/分/间距）：")
        for t, u, v, g in unknown_left:
            print("    t=%-7.1f 最像 %-14s %.3f 间距 %.3f" % (t, u, v, g))

    # 归属落盘（可追溯：哪张卡进了哪个条目、哪些被选成模板）
    try:
        unit_cards = {}
        for i in sorted(assign):
            unit_cards.setdefault(assign[i], []).append(round(float(ts[i]), 2))
        dump = os.path.join(ROOT, "out", "teams", "%s_assign.json" % args.team)
        with open(dump, "w", encoding="utf-8") as f:
            json.dump({"_note": "卡面时刻 → 库条目（建库时的真实归属，可追溯）",
                       "units": unit_cards}, f, ensure_ascii=False, indent=1)
        print("  归属明细已写出 %s" % dump)
    except OSError as e:
        print("  ！归属明细写出失败：%s" % e)

    # 每个身份：最远点采样 + 两态特征
    arts, per_ident = {}, {}
    for i in sorted(assign):
        nm = assign[i]
        per_ident.setdefault(nm, []).append(i)
    for nm, idxs in sorted(per_ident.items()):
        # 「（不入库）」这类"不是角色"的格子（场地效果卡等）：只登记、不建库
        if nm.startswith("（"):
            print("  %s：%d 张卡只登记不入库（用户标注/自动匹配判定不是角色）" % (nm, len(idxs)))
            continue
        A = [art_of_card(imread_u(os.path.join(cdir, names[i]))) for i in idxs]
        keep = farthest_point(A, args.max_frames)
        arts[nm] = [A[k] for k in keep]
        per_ident[nm] = [idxs[k] for k in keep]        # 记录选了哪些帧（供评估排除）
    print("将建立 %d 个条目" % len(arts))

    new_banks = {}
    for nm, A in arts.items():
        mats = [feats_of_art(a, z) for a in A for z in T.ZOOMS]
        new_banks[nm] = np.stack(mats).astype(np.float32)
    for nm in sorted(new_banks, key=lambda x: -len(per_ident[x])):
        print("  %-18s 卡 %3d 张 → 取 %2d 帧 → 模板 %d 张"
              % (nm, len([1 for i in assign if assign[i] == nm]),
                 len(per_ident[nm]), new_banks[nm].shape[0]))

    if args.dry_run:
        print("\n--dry-run：没有写库")
        return 0

    # 幂等：先把这些条目的旧模板清空再追加（重跑不会翻倍）
    trim = {nm: 0 for nm in new_banks}
    merged, report = axis_onboard.merge_banks(bank_path, new_banks, trim_to=trim)
    np.savez_compressed(bank_path, **merged)
    T._BANK_CACHE.pop(bank_path, None)
    print("\n已写出 %s" % bank_path)
    print("  库内条目 %d → %d；本次新增/替换 %d 个"
          % (len(report["old"]), len(merged), len(new_banks)))
    tot = sum(v.shape[0] for v in merged.values())
    print("  模板总数 %d 张（其中本次 %d 张）"
          % (tot, sum(v.shape[0] for v in new_banks.values())))

    if args.eval:
        do_eval(cdir, names, assign, per_ident, merged)
    return 0


def do_eval(cdir, names, assign, per_ident, bank):
    """诚实口径：只看**没被选为模板**的那些帧，逐帧对全库打分。"""
    W4 = np.array([T.W_GRAY, T.W_GRAD, T.W_COLOR / 2, T.W_COLOR / 2], np.float32)
    units = list(bank)
    used = {i for idxs in per_ident.values() for i in idxs}
    held = [i for i in sorted(assign) if i not in used]
    print("\n=== 留出帧评估（%d 张，全库 %d 个条目）===" % (len(held), len(units)))
    ok = wrong = abst = 0
    wrong_list = []
    per = {}
    for i in held:
        card = imread_u(os.path.join(cdir, names[i]))
        art = art_of_card(card)
        f = T.feats(art)
        f2 = feats_of_art(art, T.ZOOMS[1])
        sc = {}
        for u, mats in bank.items():
            best = -9.0
            for m in mats:
                for ff in (f, f2):
                    v = float((W4[0] * (m[0] * ff[0]).mean() + W4[1] * (m[1] * ff[1]).mean()
                               + W4[2] * (m[2] * ff[2]).mean() + W4[3] * (m[3] * ff[3]).mean()))
                    best = max(best, v)
            sc[u] = best
        rank = sorted(sc.items(), key=lambda kv: -kv[1])
        top, val = rank[0]
        gap = val - rank[1][1]
        truth = assign[i]
        d = per.setdefault(truth, [0, 0, 0])
        if top == truth and val >= 0.90 and gap >= 0.45:
            ok += 1
            d[0] += 1
        elif top != truth and val >= 0.90 and gap >= 0.45:
            wrong += 1
            d[1] += 1
            wrong_list.append((float(names[i][1:9]), truth, top, round(val, 3), round(gap, 3)))
        else:
            abst += 1
            d[2] += 1
    tot = len(held)
    print("  认对 %d / 认错 %d / 弃权 %d  （%.1f%% 认对，错判 %d）"
          % (ok, wrong, abst, 100.0 * ok / max(1, tot), wrong))
    print("  逐角色：")
    for u in sorted(per, key=lambda x: per[x][0] - per[x][1]):
        a, b, c = per[u]
        print("    %-18s 对 %3d 错 %2d 弃 %2d" % (u, a, b, c))
    if wrong_list:
        print("  ⚠ 错判明细（时刻/真值/被判成/分/间距）：")
        for w in wrong_list[:20]:
            print("    t=%-7.1f %-16s → %-16s %.3f %.3f" % w)


if __name__ == "__main__":
    sys.exit(main())
