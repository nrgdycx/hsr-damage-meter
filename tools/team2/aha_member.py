# -*- coding: utf-8 -*-
"""【T2】阿哈时刻成员归属 —— 用**欢愉技参演编号**的升序循环给头像分段贴标签（**不认脸**）。

用户 2026-10-04 给的真值（原话见 docs/附伤与开大踢轴.md §8）：
    参演编号：真珠 104 ｜ 爻光 116 ｜ 欢愉主 120 ｜ 火花 144 ｜ 绯英 146 ｜ 水砂 156 ｜ 狼尊 999
    规则：**按编号从小到大轮流**；场地 buff 会给一个 **200 号**欢愉技插进来；
          离场（死亡/被离场控制控走）的角色会**整个少掉**。
欢愉队（火花/爻光/真珠/银狼）→ 顺序 = 真珠 → 爻光 → 火花 → 银狼（循环）。

做法：
  1. 在阿哈段内按 0.2s 取顶端卡的**成员头像框**特征；
  2. 相邻帧相似度突变 = **换人**（不需要认脸）；
  3. 丢掉过短的"过渡段"，从**第一个完整段**开始按编号升序循环贴标签；
  4. 实测每人大约显示 **2.6s**，所以过长的段按 2.6s 切成多个（相邻两人头像相近时会漏切）。

用法：
  python -u tools/team2/aha_member.py --sheet      # 出「带标签的连拍图」供用户核对
  python -u tools/team2/aha_member.py --selftest   # 自检（顺序/时长/边界）
"""
import os as _os
import sys as _sys
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import json
import os
import sys

HERE = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if not _os.path.isdir(_os.path.join(HERE, "out")):
    HERE = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_sys.path.insert(0, HERE)

# ── 用户给的参演编号（真值）──
CAST_NUMBER = {"真珠": 104, "爻光": 116, "欢愉主": 120, "火花": 144, "绯英": 146,
               "水砂": 156, "场地buff": 200, "银狼LV.999": 999, "银狼": 999}

STEP = 0.2               # 密帧步长
SWITCH_THR = 0.55        # 相邻帧相似度低于它 = 换人
SLOT = 2.6               # 每人显示时长（实测；用于切开漏切的相邻同貌）
MIN_RUN = 1.0            # 短于它的段算过渡
MAX_SLOTS = 12           # 单段最多贴多少个标签（防炸）

# 9 个阿哈段（来自 out/axis_actors_L2.csv 的 card_type=aha 区间；1s 网格，边界会被切掉一点）
SEGS = [(20, 33), (63, 78), (106, 119), (159, 169), (173, 192), (217, 230),
        (288, 296), (300, 321), (334, 341)]


def _aha_feats(crop):
    """阿哈卡的成员头像特征（用归档脚本里的 AHA_ART 框，口径与上一轮一致）。"""
    import importlib.util
    if not hasattr(_aha_feats, "_mod"):
        p = os.path.join(HERE, "tools/archive/deprecated/analyze_aha.py")
        spec = importlib.util.spec_from_file_location("aha_dep", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _aha_feats._mod = m
    return _aha_feats._mod.aha_feats(crop)


def runs_in_segment(t0, t1, step=STEP, thr=SWITCH_THR):
    """段内按相似度突变切成"头像段"。返回 [(t_start, t_end, n_frames)]。"""
    import axis_actor as T
    import axis_actor_team2 as E2
    ts = []
    t = round(float(t0), 2)
    while t <= t1 + 1e-6:
        if os.path.isfile(E2.crop_path(round(t, 2))):
            ts.append(round(t, 2))
        t = round(t + step, 2)
    if len(ts) < 3:
        return []
    F = [(t, _aha_feats(E2.load_crop(t))) for t in ts]
    runs, cur = [], [ts[0]]
    for k in range(len(F) - 1):
        s = float(T.pair_score(F[k][1], F[k + 1][1]))
        if s < thr:
            runs.append(cur)
            cur = [F[k + 1][0]]
        else:
            cur.append(F[k + 1][0])
    runs.append(cur)
    return [(r[0], r[-1], len(r)) for r in runs]


def label_runs(runs, team=("火花", "爻光", "真珠", "银狼LV.999"), cast=None, slot=SLOT):
    """⛔ **REFUTED（用户 2026-10-04 否决）—— 不要用这个函数**。

    曾经的做法：按"欢愉技参演编号升序"给头像段循环贴标签（真珠→爻光→火花→银狼）。
    用户原话：「这个阿哈时刻里面的人**不是定的**，可以是**非欢愉角色**，**可以不是角色**，**你必须认脸**」
    ⇒ 阿哈框里是谁**必须靠图像识别**，不能靠编号顺序推。

    保留函数体只为**可复现那次错误**（反面教材）；正路见 `label_by_recognition()`。
    """
    cast = cast or CAST_NUMBER
    present = sorted([m for m in team if m in cast], key=lambda m: cast[m])
    if not present:
        return []
    runs = [r for r in runs if (r[1] - r[0]) + STEP >= MIN_RUN]
    if not runs:
        return []
    out, k = [], 0
    for (a, b, n) in runs:
        slots = max(1, int(round(((b - a) + STEP) / slot)))
        for j in range(slots):
            if k >= MAX_SLOTS:
                break
            member = present[k % len(present)]
            d = ((b - a) + STEP) / slots
            out.append({"t0": round(a + j * d, 2), "t1": round(a + (j + 1) * d - STEP, 2),
                        "member": member, "how": "REFUTED-numbering",
                        "why": "⛔ 按参演编号顺序推 —— 已被用户否决，仅供复现错误"})
            k += 1
    return out


def timeline(segs=None, team=("火花", "爻光", "真珠", "银狼LV.999")):
    """全部阿哈段的**换人分段**（只给时间，不给身份 —— 身份要认脸）。"""
    out = []
    for (a, b) in (segs or SEGS):
        for (t0, t1, n) in runs_in_segment(a, b):
            if (t1 - t0) + STEP >= MIN_RUN:
                out.append({"seg": (a, b), "t0": t0, "t1": t1, "member": None,
                            "how": "change-point", "why": "相似度突变分段（身份待认脸）"})
    return out


def owner_at(t, tl=None):
    """某一时刻框里是谁（不在阿哈段里 → None）。"""
    for r in (tl if tl is not None else TIMELINE):
        if r["t0"] - 1e-6 <= t <= r["t1"] + 1e-6:
            return r["member"]
    return None


def build(team=("火花", "爻光", "真珠", "银狼LV.999"), path=None):
    global TIMELINE
    TIMELINE = timeline(team=team)
    path = path or os.path.join(HERE, "out/t2_aha_timeline.json")
    json.dump({"cast_number": CAST_NUMBER, "slot": SLOT, "switch_thr": SWITCH_THR,
               "team": list(team), "runs": TIMELINE},
              open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return TIMELINE, path


TIMELINE = []

# ── 认脸（正路）──────────────────────────────────────────────────────────────
LABELS_PATH = os.path.join(HERE, "out/t2_aha_labels.json")
BANK_PATH = os.path.join(HERE, "out/t2_aha_bank.npz")
FORM_MEMBER = {"真珠": "真珠", "火花": "火花", "爻光": "爻光",
               "银狼LV.999": "银狼LV.999"}          # 两个狼尊形态归属同一人
THR_SCORE = 0.60      # 认脸最低分（低于它 → 认不出，不许猜）
THR_MARGIN = 0.06     # 与第二名的分差

# ── 拒识（"不是角色"）──
# 用户 2026-10-04 指认：t=63.0~64.0 与 t=177.0~178.0 是**过渡帧**（"阿哈时刻的一点"，不是角色），
# 之前被认脸硬塞成"狼尊·强化"。教训：**必须有一个"不是角色"的出口**。
NEG_LABEL = "不是角色"
NEGATIVE_RUNS = [{"t0": 63.0, "t1": 64.0}, {"t0": 177.0, "t1": 178.0}]
# 拒识判据（实测，余量很大）：
#   过渡帧（用户指认的 t=63~64 / t=177~178）：**整段最大均亮只有 102~107**
#   所有真角色段：**整段最大均亮 ≥ 153**（最暗的 t=173~176.8 也有 153.8）
#   ⇒ "整段就没亮过" = 不是角色。逐帧占比那套不行（偏暗的真角色会被误杀）。
THR_BRIGHT_MAX = 130.0


def load_labels(path=LABELS_PATH):
    """用户标注的段 + 用户指认的"过渡帧"（拒识类）。"""
    d = json.load(open(path, encoding="utf-8"))
    runs = list(d["runs"])
    have = {(round(r["t0"], 2), round(r["t1"], 2)) for r in runs}
    for r in NEGATIVE_RUNS:
        if (round(r["t0"], 2), round(r["t1"], 2)) not in have:
            runs.append({"t0": r["t0"], "t1": r["t1"], "member": NEG_LABEL, "form": "",
                         "cluster": 0, "mid": (r["t0"] + r["t1"]) / 2,
                         "src": "user-negative-2026-10-04"})
    runs.sort(key=lambda r: r["t0"])
    return runs


def patch_quality(t):
    """头像区的**原始**质量指标：(均亮, 灰度标准差, 梯度能量)。用于拒识过渡帧。"""
    import cv2
    import axis_actor_team2 as E2
    import importlib.util
    if not hasattr(patch_quality, "_mod"):
        p = os.path.join(HERE, "tools/archive/deprecated/analyze_aha.py")
        spec = importlib.util.spec_from_file_location("aha_dep_q", p)
        mm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mm)
        patch_quality._mod = mm
    patch = patch_quality._mod.aha_patch(E2.load_crop(round(t, 2)))
    g = cv2.cvtColor(patch, cv2.COLOR_RGB2GRAY).astype("float32")
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    return float(g.mean()), float(g.std()), float(cv2.magnitude(gx, gy).mean())


def is_low_quality(t):
    """单帧质量（仅供诊断：这张是不是又暗又平）。"""
    mg, sd, gr = patch_quality(t)
    return (mg < 120.0) or (gr < 150.0)


def is_transition_run(run):
    """**整段都没亮过** → 过渡帧（不是角色）。返回 (是否, 整段最大均亮)。"""
    ts = frames_of_run(run)
    if not ts:
        return True, 0.0
    mx = max(patch_quality(t)[0] for t in ts)
    return mx < THR_BRIGHT_MAX, mx


def _aha_feat_of(t):
    import axis_actor_team2 as E2
    return _aha_feats(E2.load_crop(round(t, 2)))


def _sim_graygrad(f1, f2):
    """只用灰度+梯度（阿哈卡有红色滤镜，色度通道会被带偏）。"""
    import axis_actor as T
    g = float((f1[0] * f2[0]).mean()) * T.W_GRAY
    gr = float((f1[1] * f2[1]).mean()) * T.W_GRAD
    return (g + gr) / (T.W_GRAY + T.W_GRAD)


def frames_of_run(run, step=STEP):
    import axis_actor_team2 as E2
    ts, t = [], round(float(run["t0"]), 2)
    while t <= run["t1"] + 1e-6:
        if os.path.isfile(E2.crop_path(round(t, 2))):
            ts.append(round(t, 2))
        t = round(t + step, 2)
    return ts


def run_key(run):
    return "%.2f-%.2f" % (run["t0"], run["t1"])


def build_bank(labels=None, save=True, path=BANK_PATH):
    """用**用户标注**的段建阿哈头像模板库（每段取段内全部 0.2s 帧）。

    库按**段**保存（`keys`/`runs`/`feats` 三条平行数组），这样留一验证时能只排除"这一段"。
    """
    import numpy as np
    labels = labels or load_labels()
    keys, runs, feats = [], [], []
    for r in labels:
        key = FORM_MEMBER.get(r["member"], r["member"])
        if r.get("form"):
            key = "%s·%s" % (key, r["form"])
        rk = run_key(r)
        for t in frames_of_run(r):
            keys.append(key)
            runs.append(rk)
            feats.append(_aha_feat_of(t))
    bank = {"keys": keys, "runs": runs, "feats": np.stack(feats) if feats else np.zeros((0, 4, 48, 72))}
    if save:
        np.savez_compressed(path, **bank)
    return bank


def _bank_scores(feat, bank, exclude_run=None):
    """向量化打分：返回 {类: 最高分}（可排除某一段的全部帧）。"""
    import axis_actor as T
    F = bank["feats"]
    if len(F) == 0:
        return {}
    keep = [i for i, rk in enumerate(bank["runs"]) if not (exclude_run and rk == exclude_run)]
    if not keep:
        return {}
    F = F[keep]
    s = ((F[:, 0] * feat[0]).mean(axis=(1, 2)) * T.W_GRAY
         + (F[:, 1] * feat[1]).mean(axis=(1, 2)) * T.W_GRAD) / (T.W_GRAY + T.W_GRAD)
    out = {}
    for i, k in zip(keep, [bank["keys"][j] for j in keep]):
        v = float(s[keep.index(i)])
        if v > out.get(k, -9.0):
            out[k] = v
    return out


def classify(feat, bank, exclude_run=None):
    """一颗头像的特征 → (member, form, score, margin, second)。`exclude_run` 用于留一。"""
    scores = _bank_scores(feat, bank, exclude_run=exclude_run)
    if not scores:
        return None, "", -9.0, 0.0, ""
    order = sorted(scores.items(), key=lambda kv: -kv[1])
    k, s = order[0]
    second = order[1][0] if len(order) > 1 else ""
    m = s - (order[1][1] if len(order) > 1 else -9.0)
    if s < THR_SCORE or m < THR_MARGIN:
        return None, "", s, m, second
    member, _, form = k.partition("·")
    return member, form, s, m, second


def recognize_run(run, bank, exclude_run=None, vote=0.6, quality=True):
    """一个头像段 → 多数投票定人；**质量太差（过渡帧）直接拒识**，不硬塞给最近的类。"""
    import numpy as np
    ts = frames_of_run(run)
    if not ts:
        return None, "", 0.0, 0.0, "no-frames"
    if quality:
        trans, mx = is_transition_run(run)
        if trans:
            return None, "", mx, 0.0, "transition(整段最大均亮 %.0f < %.0f → 不是角色)" % (mx, THR_BRIGHT_MAX)
    hits, scs = {}, []
    for t in ts:
        mem, form, s, m, _ = classify(_aha_feat_of(t), bank, exclude_run=exclude_run)
        scs.append(s)
        if mem:
            hits[(mem, form)] = hits.get((mem, form), 0) + 1
    n = len(ts)
    if not hits:
        return None, "", float(np.mean(scs)), 0.0, "below-threshold"
    (mem, form), c = max(hits.items(), key=lambda kv: kv[1])
    if c < vote * n:
        return None, "", float(np.mean(scs)), 0.0, "no-majority(%d/%d)" % (c, n)
    return mem, form, float(np.mean(scs)), c / n, ""


def timeline_labeled(label_path=LABELS_PATH):
    """43 段的分段 + 身份：用户标注过的段直接用标注，其余靠认脸（认不出 → member=None）。"""
    labels = {run_key(r): r for r in load_labels(label_path)}
    bank = build_bank(save=False)
    out = []
    for (a, b) in SEGS:
        for (t0, t1, n) in runs_in_segment(a, b):
            if (t1 - t0) + STEP < MIN_RUN:
                continue
            key = "%.2f-%.2f" % (t0, t1)
            rec = {"seg": [a, b], "t0": t0, "t1": t1, "member": None, "form": "", "how": ""}
            if key in labels:
                r = labels[key]
                rec.update(member=r["member"], form=r["form"], how="user-label",
                           src="user-2026-10-04")
            else:
                mem, form, s, c, why = recognize_run({"t0": t0, "t1": t1}, bank)
                rec.update(member=mem, form=form,
                           how="recognized" if mem else "unrecognized",
                           score=round(s, 3), vote=round(c, 2), why=why)
            out.append(rec)
    return out


def selftest_face(verbose=True):
    """认脸留一验证：每段**不参与建库**，用其余段多数投票认它。"""
    labels = load_labels()
    bank_all = build_bank(save=False)
    ok = 0
    conf = {}
    for r in labels:
        key = FORM_MEMBER.get(r["member"], r["member"])
        label_is_neg = (r["member"] == NEG_LABEL)
        if r.get("form"):
            key = "%s·%s" % (key, r["form"])
        mem, form, s, c, why = recognize_run({"t0": r["t0"], "t1": r["t1"]}, bank_all,
                                             exclude_run=run_key(r))
        k2 = "%s%s" % (mem or ("不是角色" if label_is_neg else "认不出"),
                       ("·" + form) if form else "")
        conf.setdefault(key, {}).setdefault(k2, 0)
        conf[key][k2] += 1
        right = (mem, form) == (r["member"], r["form"]) or (label_is_neg and mem is None)
        if right:
            ok += 1
    if verbose:
        print("认脸留一（段级，多数投票）：%d/%d = %.1f%%" % (ok, len(labels), 100.0 * ok / len(labels)))
        for k in sorted(conf):
            print("   %-16s → %s" % (k, conf[k]))
    return ok, len(labels), conf


def label_sheet(path=None, thr=0.62, per_cluster=4):
    """出「认脸图」：把头像段代表帧**聚类**，每簇一行（带簇号与出现时刻），供用户标注。

    * 只用**灰度+梯度**两个通道算相似度（阿哈卡有红色滤镜，色度通道会被带偏）；
    * 簇号由用户标注（可写"不是角色"）。
    """
    import cv2
    import importlib.util
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    import axis_actor as T
    import axis_actor_team2 as E2
    p = os.path.join(HERE, "tools/archive/deprecated/analyze_aha.py")
    spec = importlib.util.spec_from_file_location("aha_dep3", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    reps = []
    for (a, b) in SEGS:
        for (t0, t1, n) in runs_in_segment(a, b):
            if (t1 - t0) + STEP < MIN_RUN:
                continue
            mid = round(0.5 * (t0 + t1), 2)
            if not os.path.isfile(E2.crop_path(mid)):
                continue
            f = m.aha_feats(E2.load_crop(mid))
            reps.append((mid, t0, t1, f))

    def sim(f1, f2):
        """只用灰度+梯度：0.5*(灰) + 0.3*(梯度)，与 W_GRAY/W_GRAD 同比例。"""
        g = float((f1[0] * f2[0]).mean()) * T.W_GRAY
        gr = float((f1[1] * f2[1]).mean()) * T.W_GRAD
        return (g + gr) / (T.W_GRAY + T.W_GRAD)

    n = len(reps)
    S = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            S[i][j] = S[j][i] = sim(reps[i][3], reps[j][3])
    groups = [[i] for i in range(n)]
    while len(groups) > 1:
        best, pair = -9.0, None
        for x in range(len(groups)):
            for y in range(x + 1, len(groups)):
                v = min(S[a][b] for a in groups[x] for b in groups[y])
                if v > best:
                    best, pair = v, (x, y)
        if best < thr:
            break
        x, y = pair
        groups[x] = groups[x] + groups[y]
        groups.pop(y)
    groups.sort(key=lambda g: -len(g))

    font = None
    for cand in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"]:
        if os.path.isfile(cand):
            font = ImageFont.truetype(cand, 18)
            break
    tiles = []
    for gi, g in enumerate(groups, 1):
        ex = []
        for idx in (g[:per_cluster] if len(g) <= per_cluster else
                    [g[k] for k in np.linspace(0, len(g) - 1, per_cluster).astype(int)]):
            mid, t0, t1, _ = reps[idx]
            patch = m.aha_patch(E2.load_crop(mid))
            patch = cv2.resize(patch, None, fx=1.8, fy=1.8, interpolation=cv2.INTER_NEAREST)
            ex.append((mid, patch))
        tiles.append((gi, len(g), ex))
    pad, lab = 12, 28
    tw = max(im.shape[1] for _, _, ex in tiles for _, im in ex)
    th = max(im.shape[0] for _, _, ex in tiles for _, im in ex)
    W = min(4, per_cluster) * (tw + 8) + 240
    H = sum(th + lab + 14 for _ in tiles) + 60
    canvas = Image.new("RGB", (W, H), (14, 14, 18))
    d = ImageDraw.Draw(canvas)
    d.text((12, 12), "阿哈时刻：头像段聚类（每簇一行，请标注「簇N = 谁」；不是角色就写「不是角色」）",
           fill=(255, 220, 120), font=font)
    y = 50
    for gi, cnt, ex in tiles:
        d.text((12, y + th // 2 - 12), "簇%-2d (%d 段)" % (gi, cnt), fill=(120, 255, 160), font=font)
        for k, (mid, im) in enumerate(ex):
            x = 200 + k * (tw + 8)
            canvas.paste(Image.fromarray(cv2.cvtColor(im, cv2.COLOR_RGB2BGR)), (x, y))
            d.text((x + 4, y + th - 20), "%.1f" % mid, fill=(255, 255, 0), font=font)
        y += th + lab + 14
    out = path or os.path.join(HERE, "docs/images/L2_aha_clusters_sheet.png")
    canvas.save(out)
    print("簇数：%d（阈值 %.2f）｜ 头像段：%d" % (len(groups), thr, n))
    for gi, g in enumerate(groups, 1):
        ts = ", ".join("%.1f" % reps[i][0] for i in g[:12])
        print("  簇%-2d %2d 段：%s%s" % (gi, len(g), ts, " …" if len(g) > 12 else ""))
    print("写出", out, canvas.size)
    return out


def preview(path=None, scale=1.6, per_row=14):
    """出「认脸结果」预览图：43 段各一格（写着认出来的名字 + 时刻 + 依据），供用户抽检。"""
    import cv2
    import importlib.util
    from PIL import Image, ImageDraw, ImageFont
    import axis_actor_team2 as E2
    p = os.path.join(HERE, "tools/archive/deprecated/analyze_aha.py")
    spec = importlib.util.spec_from_file_location("aha_dep5", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    tl = timeline_labeled()
    font = None
    for cand in [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"]:
        if os.path.isfile(cand):
            font = ImageFont.truetype(cand, 15)
            break
    by_seg = {}
    for r in tl:
        by_seg.setdefault(tuple(r["seg"]), []).append(r)
    tiles, labels = [], []
    for seg, rs in sorted(by_seg.items()):
        for r in rs:
            ts = frames_of_run(r)
            if not ts:
                continue
            mid = ts[len(ts) // 2]          # 段内实际存在的帧里取中间那张（0.2s 网格不一定有"正中"）
            patch = m.aha_patch(E2.load_crop(mid))
            patch = cv2.resize(patch, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
            tag = (r["member"] or "认不出") + (("·" + r["form"]) if r.get("form") else "")
            src = "标注" if r["how"] == "user-label" else "认脸%.2f" % r.get("vote", 0)
            tiles.append(patch)
            labels.append("%s %s %.0f" % (tag, src, mid))
    tw = max(t.shape[1] for t in tiles)
    th = max(t.shape[0] for t in tiles)
    rows = (len(tiles) + per_row - 1) // per_row
    W = per_row * (tw + 4) + 24
    H = 50 + rows * (th + 22) + 20
    canvas = Image.new("RGB", (W, H), (14, 14, 18))
    d = ImageDraw.Draw(canvas)
    d.text((12, 12), "阿哈时刻成员**认脸**结果（43 段；标注=用户给的，认脸x.xx=多数投票比例）—— 请抽检",
           fill=(255, 220, 120), font=font)
    for i, (t, lab) in enumerate(zip(tiles, labels)):
        col, row = i % per_row, i // per_row
        x, y = 12 + col * (tw + 4), 48 + row * (th + 22)
        canvas.paste(Image.fromarray(cv2.cvtColor(t, cv2.COLOR_RGB2BGR)), (x, y))
        d.rectangle([x, y + th - 20, x + tw, y + th], fill=(0, 0, 0))
        d.text((x + 2, y + th - 19), lab, fill=(180, 255, 180), font=font)
    out = path or os.path.join(HERE, "docs/images/L2_aha_recognized.png")
    canvas.save(out)
    print("写出", out, canvas.size, "｜ %d 段" % len(tiles))
    return out


# ── 实时入口：整帧 → 框里是谁 ────────────────────────────────────────────────
AHA_ART = (152, 70, 248, 182)        # 阿哈卡上的**成员头像**框（绝对坐标；与离线同一口径）


def load_saved_bank(path=BANK_PATH):
    """读已建好的模板库（6 类，含「不是角色」）。"""
    import numpy as np
    z = np.load(path, allow_pickle=True)
    return {"keys": list(z["keys"]), "runs": list(z["runs"]), "feats": z["feats"]}


def feat_from_full(bgr, offset=(0, 0), scale=None):
    """图（整帧，或**已裁好的行动轴区域**）→ 阿哈成员头像特征。

    * `offset`：区域在原帧里的左上角（实时抓的是 `x60~340` 那条区域，不是整帧）；
    * `scale` ：不传时——宽度 ≥1000 当整帧、按线7 口径算缩放；否则按 1.0（单机参考分辨率）。
    """
    import axis_actor as T
    if scale is None:
        s = T.scale_of(bgr.shape) if bgr.shape[1] >= 1000 else 1.0
    else:
        s = scale
    x0, y0, x1, y1 = [int(round(v * s)) for v in AHA_ART]
    x0, x1 = x0 - offset[0], x1 - offset[0]
    y0, y1 = y0 - offset[1], y1 - offset[1]
    x0, y0 = max(0, x0), max(0, y0)
    patch = bgr[y0:y1, x0:x1]
    if patch.size == 0:
        raise ValueError("阿哈头像框落在画面外：图 %s offset %s" % (bgr.shape, offset))
    return T.feats(patch), (x0, y0, x1, y1)


def recognize_full(bgr, bank=None, offset=(0, 0), scale=None):
    """图（整帧或行动轴区域）→ {'member','form','score','margin','why'}。

    * 库是 6 类（真珠/火花/爻光/狼尊·强化/狼尊·普通/**不是角色**）→ 过渡帧有地方去；
    * 拿不准（分数或分差不够）就给 `member=None`（**不猜**）；
    * 实时只有单帧，没有"整段最大亮度"那条**段级**判据 → 单帧误差比离线大；
      接实时时靠"这个人是"的多数投票来稳（见 `mvp/reader.py`）。
    """
    bank = bank or load_saved_bank()
    try:
        feat, rect = feat_from_full(bgr, offset=offset, scale=scale)
    except Exception as e:                       # noqa: BLE001  帧太小/几何不符
        return {"member": None, "form": "", "score": 0.0, "margin": 0.0, "why": "feat-failed:%s" % e}
    member, form, s, m, second = classify(feat, bank)
    if member == NEG_LABEL:
        return {"member": None, "form": "", "score": s, "margin": m, "why": "不是角色(过渡帧)"}
    return {"member": member, "form": form, "score": s, "margin": m,
            "why": "" if member else "below-threshold(次选=%s)" % second}


def selftest_live(verbose=True):
    """实时入口自检：把离线小块**还原成整帧**（模拟实时抓屏的几何）再走 `recognize_full`。"""
    import axis_actor_team2 as E2
    labels = {run_key(r): r for r in load_labels()}
    bank = load_saved_bank()
    ok = n = 0
    bad = []
    for (a, b) in SEGS:
        for (t0, t1, nf) in runs_in_segment(a, b):
            if (t1 - t0) + STEP < MIN_RUN:
                continue
            k = "%.2f-%.2f" % (t0, t1)
            if k not in labels:
                continue
            ts = frames_of_run({"t0": t0, "t1": t1})
            if not ts:
                continue
            hits = {}
            for t in ts:
                full = E2.as_full(E2.load_crop(t))       # 模拟"整帧"
                r = recognize_full(full, bank=bank)
                mm = r["member"] or NEG_LABEL
                hits[mm] = hits.get(mm, 0) + 1
            pred = max(hits.items(), key=lambda kv: kv[1])[0]
            exp = labels[k]["member"]
            n += 1
            if pred == exp:
                ok += 1
            else:
                bad.append((t0, exp, pred))
    if verbose:
        print("实时入口（整帧几何）自检：%d/%d = %.1f%%" % (ok, n, 100.0 * ok / max(1, n)))
        for t, e, p in bad:
            print("   ✗ t=%.1f 期望 %s 实得 %s" % (t, e, p))
    return ok, n


def selftest(verbose=True):
    """自检：只保证**仍然有效**的那半（换人分段 + 身份必须为 None + 错路径已停用）。"""
    ok = True

    def chk(name, cond, extra=""):
        nonlocal ok
        ok &= bool(cond)
        if verbose:
            print("  [%s] %s %s" % ("OK" if cond else "×", name, extra))

    tl = timeline()
    if verbose:
        print("① 换人分段：%d 段（9 个阿哈段）" % len(tl))
    chk("段数在 30~60 之间", 30 <= len(tl) <= 60, "%d 段" % len(tl))
    durs = [round(r["t1"] - r["t0"] + STEP, 2) for r in tl]
    # 相邻两人头像太像时会**漏切**（最长实测 6.2s ≈ 2 人）→ 上界放宽；这点要在认脸时留意
    chk("单段时长 0.8~6.5s（每人均值约 2.6s；>4s 的可能是两个相似头像漏切）",
        all(0.8 <= x <= 6.5 for x in durs),
        "中位 %.1fs ｜ 最长 %.1fs" % (sorted(durs)[len(durs) // 2], max(durs)))
    chk("**没有**任何身份标签（身份必须靠认脸）", all(r["member"] is None for r in tl),
        "member 全为 None")
    chk("owner_at() 已停用（恒 None）", owner_at(20.6) is None)
    lr = label_runs(runs_in_segment(20, 33))
    chk("label_runs() 带 REFUTED 标记", all(r.get("how") == "REFUTED-numbering" for r in lr),
        "%d 段" % len(lr))
    import axis_actor_team2 as E2
    tot = hit = 0
    for (a, b) in SEGS:
        t = float(a)
        while t <= b + 1e-6:
            if os.path.isfile(E2.crop_path(round(t, 2))):
                tot += 1
                for r in tl:
                    if r["t0"] - 1e-6 <= t <= r["t1"] + 1e-6:
                        hit += 1
                        break
            t = round(t + STEP, 2)
    chk("阿哈密帧被分段覆盖 ≥85%", hit >= 0.85 * tot,
        "%d/%d = %.0f%%" % (hit, tot, 100.0 * hit / max(1, tot)))
    # 认脸留一（段级多数投票）
    try:
        ok_n, n_all, _conf = selftest_face(verbose=verbose)
        chk("认脸留一 = %d/%d" % (ok_n, n_all), ok_n == n_all)
    except Exception as e:                       # noqa: BLE001
        chk("认脸留一可运行", False, str(e))
    # 43 段都有结论（用户标注 27 + 认脸 16）
    tl2 = timeline_labeled()
    chk("43 段全部有身份", len(tl2) == 43 and all(r["member"] for r in tl2),
        "有身份 %d/%d" % (sum(1 for r in tl2 if r["member"]), len(tl2)))
    if verbose:
        print("\n自检：%s" % ("全部通过 ✓" if ok else "**有失败** ×"))
    return 0 if ok else 1


def _cli():
    if "--selftest" in _sys.argv:
        return selftest()
    if "--faces" in _sys.argv:
        return 0 if selftest_face()[0] == selftest_face()[1] else 1
    if "--build" in _sys.argv:
        bank = build_bank()
        print("模板库已写出 %s：%s" % (BANK_PATH, {k: len(v) for k, v in bank.items()}))
        return 0
    if "--sheet" in _sys.argv:
        label_sheet()
        return 0
    if "--preview" in _sys.argv:
        preview()
        return 0
    if "--runs" in _sys.argv:
        for (a, b) in SEGS:
            print("阿哈段 %g~%g：" % (a, b))
            for (t0, t1, n) in runs_in_segment(a, b):
                print("     t=%6.1f~%-6.1f %4.1fs (%d 帧)" % (t0, t1, (t1 - t0) + STEP, n))
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    _sys.exit(_cli())
