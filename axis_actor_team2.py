# -*- coding: utf-8 -*-
"""【线2】录屏2（欢愉队）行动轴顶端卡识别器。

设计**照抄 E 线已验证的套路**（`axis_actor.py`），只换素材来源与队伍：
  * 顶端槽位置固定 —— 不做全图滑窗（旧的滑窗方案是"昔涟↔长夜月系统性混淆"的来源）
  * 特征 = 灰度 NCC + 0.6×梯度 NCC + 0.3×色度(Lab ab) NCC
  * 两道闸：分数 ≥ 0.90 **且** 与第二名分差 ≥ 0.45，否则「待复核」
  * 模板库每张存**两种卡面缩放**（1.0 / 1.08，E 线实测两种渲染差 1.08 倍 + (4,2)px 位移）

与 E 线的唯一区别：**输入是抽帧时裁好的小块**（`frames/axis2_L2/tXXXX_top.png`，282×167），
不是整帧。为了让 E 线的特征/标记函数**原样复用**，这里把小块贴回一张**全尺寸零画布**上
（几何位置与真实整帧完全一致）—— 这样"裁错了框"这类错会立刻暴露成低分，不会静默漂移。

对外接口：
    bank = axis_actor_team2.load_bank()
    r = axis_actor_team2.read_actor("frames/axis2_L2/t00012.00_top.png", bank)
    r -> {"unit": "银狼"|None, "owner": ..., "score":..., "margin":..., "marker":..., "card_type":...,
          "reject": None|"low_score"|"low_margin"|"not_unit"}

命令行：
    python axis_actor_team2.py --build          # 按 out/axis_top_labels_E2.json 重建模板库
    python axis_actor_team2.py --selftest       # 真值帧逐条核对（留出帧口径见 axis_report_L2.py）
    python axis_actor_team2.py 12 13 26 --json
"""
import json
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, HERE)

import axis_actor as T          # noqa: E402  复用 E 线的特征/标记实现（不改它）

CROP_DIR = os.path.join(HERE, "frames/axis2_L2")
LABELS_PATH = os.path.join(HERE, "out/axis_top_labels_E2.json")
BANK_PATH = os.path.join(HERE, "out/axis_top_bank_E2.npz")

# `axis_extract_team2.REGIONS["top"]` 的裁剪原点；小块贴回全画布时用
CROP_ORIGIN = (40, 50)
REF_W2, REF_H2 = 2870, 1800     # 录屏2 的实际分辨率（E 线的参考系是 2876×1798）

# 录屏2 我方 4 人（用户确认：银狼 / 爻光 / 火花 / 真珠，**无忆灵/召唤物**，见 docs/用户口径与铁律.md Q4）
UNITS = ["银狼", "爻光", "火花", "真珠"]
NEG_CLASSES = ["enemy", "empty", "aha", "elation", "transition"]

# 阈值与 E 线一致（先照抄，再用 axis_report_L2.py 在录屏2 自己的帧上重新标定）
THR = T.THR
MIN_MARGIN = T.MIN_MARGIN

_BANK_CACHE = {}


def stem_t(t):
    return "t%08.2f" % float(t)


def crop_path(t, outdir=CROP_DIR):
    return os.path.join(outdir, "%s_top.png" % stem_t(t))


def load_crop(src):
    """src = 帧号 / 小块路径 / 已经是小块 ndarray。"""
    if isinstance(src, np.ndarray):
        img = src
    elif hasattr(src, "convert"):
        img = cv2.cvtColor(np.asarray(src.convert("RGB")), cv2.COLOR_RGB2BGR)
    else:
        p = src if isinstance(src, str) and os.path.exists(src) else crop_path(src)
        img = cv2.imread(p, cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(p)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return img


def as_full(crop):
    """小块 → 画布（几何与原整帧一致）。E 线的 `top_art` / `marker_patch` 需要它。

    ⚠️ 画布只留"上半截"：需要的区域是顶端卡 + 左标记（都在 y≤200、x≤330），
    `T.scale_of` 只按**宽度**算缩放，所以画布高度截到 220 而几何不变。
    **实测这只省内存（每帧 15.5MB → 1.9MB），速度没变**（9.18 → 9.01 ms/帧）——
    耗时在特征提取（`T.feats` 的 resize/Sobel/Lab）与标记匹配上，不在分配。
    当前实测：整帧识别 ~9 ms/帧（标记 ~4.3 + 匹配 ~3.5 + 细节/特征 ~1.2），硬需求 100ms 富余。
    """
    x0, y0 = CROP_ORIGIN
    h, w = crop.shape[:2]
    canvas = np.zeros((max(y0 + h, 220), max(REF_W2, x0 + w), 3), np.uint8)
    canvas[y0:y0 + h, x0:x0 + w] = crop
    return canvas


def feats_top(crop):
    """顶端卡头像区特征（形状 4×48×72）。复用 E 线的实现，保证与模板库口径一致。"""
    return feats_full(as_full(crop))


def feats_full(full):
    """整帧画布 → 顶端卡头像区特征（内部用；避免同一帧重复贴画布）。"""
    s = T.scale_of(full.shape)
    return T.feats(T.top_art(full, s))


def feats_top_zoom(crop, s_zoom):
    """带"卡面缩放态"的特征（s_zoom=1.08 = 放大态；与 axis_actor 的 ZOOMS 口径一致）。"""
    full = as_full(crop)
    s = T.scale_of(full.shape)
    art = T.top_art(full, s)
    if s_zoom != 1.0:
        h, w = art.shape[:2]
        z = cv2.resize(art, (max(2, int(round(w * s_zoom))), max(2, int(round(h * s_zoom)))),
                       interpolation=cv2.INTER_LINEAR if s_zoom > 1 else cv2.INTER_AREA)
        if z.shape[0] >= h and z.shape[1] >= w:
            yy, xx = (z.shape[0] - h) // 2, (z.shape[1] - w) // 2
            z = z[yy:yy + h, xx:xx + w]
        else:
            z = cv2.copyMakeBorder(z, 0, max(0, h - z.shape[0]), 0, max(0, w - z.shape[1]),
                                   cv2.BORDER_REPLICATE)
        art = z
    return T.feats(art)


def marker_of(crop):
    """左标记（形状/颜色/分数）—— 复用 E 线的标记库（含录屏2 的 127 个手工样本）。"""
    return marker_full(as_full(crop))


def marker_full(full):
    """整帧画布 → 左标记判定（内部用）。"""
    return T.marker_feat(full, T.scale_of(full.shape))


# 「这张卡糊到没法认」的判据：卡面头像区的**梯度能量**（相邻列灰度差的 std）。
# 来历：实测 t=15 是一张糊掉的暗色卡，却拿到 爻光 1.51 分（间距 0.59 → 会被采纳）；
# t=105（敌方糊卡）→ 真珠 1.12；t=242 → 银狼 0.47。
# 而 84 张已标真值帧的梯度能量最低是 10.2（中位 20.1）。
# 因为这些特征做了**逐通道归一化**，糊卡的"低频糊"能和同样偏灰的模板高度相关 → 必须单独设闸。
GRAD_MIN = 8.0


def art_detail(crop):
    """卡面头像区的梯度能量（越小越糊）。"""
    return art_detail_full(as_full(crop))


def art_detail_full(full):
    """整帧画布 → 卡面头像区梯度能量（内部用）。"""
    art = T.top_art(full, T.scale_of(full.shape))
    g = art.mean(axis=2)
    return float(np.abs(np.diff(g, axis=1)).std())


def build_bank(labels_path=LABELS_PATH, out_path=BANK_PATH, cache=True):
    """按真值标签建库。缺任何一帧**放弃重建**（不覆盖旧 npz），避免把库建残。"""
    with open(labels_path, encoding="utf-8") as f:
        labels = json.load(f)
    units, mats = [], []
    missing = []
    for unit in UNITS:
        fs = []
        for t in labels.get(unit, []):
            try:
                c = load_crop(t)
            except FileNotFoundError:
                missing.append("%s@%s" % (unit, t))
                continue
            for z in T.ZOOMS:
                fs.append(feats_top_zoom(c, z))
        if fs:
            units.append(unit)
            mats.append(np.stack(fs))
    if missing:
        raise SystemExit("缺 %d 张真值帧（%s）—— 先跑 `python axis_extract_team2.py --times ...`，"
                         "已放弃覆盖 %s" % (len(missing), missing[:8], out_path))
    banks = {u: m for u, m in zip(units, mats)}
    np.savez_compressed(out_path, **banks)
    if cache:
        _BANK_CACHE[out_path] = banks
    print("模板库已写出 %s：%s" % (out_path, {u: m.shape[0] // len(T.ZOOMS) for u, m in banks.items()}))
    return banks


def load_bank(path=BANK_PATH, cache=True):
    if cache and path in _BANK_CACHE:
        return _BANK_CACHE[path]
    if not os.path.exists(path):
        banks = build_bank(out_path=path)
    else:
        z = np.load(path)
        banks = {k: z[k] for k in z.files}
    if cache:
        _BANK_CACHE[path] = banks
    return banks


def match(bank, crop):
    """{单位: (最高分, 次高分)}，分数口径与 E 线一致（同类多模板取最大，含两种缩放态）。"""
    return match_feats(bank, feats_top(crop))


def match_feats(bank, f):
    """`match` 的特征直传版（read_actor 里已经算过特征，别再算一次）。"""
    pen = np.array([T.ZOOM_PEN[i % len(T.ZOOMS)] for i in range(max(
        (m.shape[0] for m in bank.values()), default=0))], dtype=np.float32)
    out = {}
    for unit, mats in bank.items():
        ch = (mats[:, 0] * f[0]).mean(axis=(1, 2))
        gr = (mats[:, 1] * f[1]).mean(axis=(1, 2))
        co = ((mats[:, 2] * f[2]).mean(axis=(1, 2)) + (mats[:, 3] * f[3]).mean(axis=(1, 2))) / 2
        s_ = T.W_GRAY * ch + T.W_GRAD * gr + T.W_COLOR * co - pen[:mats.shape[0]]
        out[unit] = (float(s_.max()), float(np.sort(s_)[-2]) if len(s_) > 1 else -1.0)
    return out


def read_actor(src, bank=None, thr=THR, min_margin=MIN_MARGIN):
    """读顶端卡。判不了 → unit=None（宁可漏，不要错）。

    ⚠️ 性能：小块→全画布（`as_full`）在一帧里只做**一次**（曾经特征/标记/细节各做一次，
    实测 9.3 ms/帧；现在 2~3 ms/帧）。实时线直接传内存图时更快。
    """
    if bank is None:
        bank = load_bank()
    crop = load_crop(src)
    full = as_full(crop)
    s = T.scale_of(full.shape)
    art = T.top_art(full, s)
    f = T.feats(art)
    sc = match_feats(bank, f)
    rank = sorted(sc.items(), key=lambda kv: -kv[1][0])
    unit, (best, _) = rank[0]
    second = rank[1][1][0] if len(rank) > 1 else -1.0
    margin = best - second
    mk, mscore, hue = T.marker_feat(full, s)
    _g = art.mean(axis=2)
    detail = float(np.abs(np.diff(_g, axis=1)).std())
    if mk == "gold_aha":
        card_type = "aha"
    elif mk == "ally_diamond":
        card_type = "elation"
    elif mk.startswith("enemy"):
        card_type = "enemy"
    elif mk == "empty":
        card_type = "empty"
    else:
        card_type = "unit"
    ok = best >= thr and (min_margin is None or margin >= min_margin)
    reject = None
    if not ok:
        reject = "low_score" if best < thr else "low_margin"
    elif detail < GRAD_MIN:
        ok, reject = False, "low_detail"          # 卡面糊/白屏/极暗 → 不认（见 GRAD_MIN 注释）
    elif card_type not in ("unit", "elation"):
        # 标记说这不是"我方单位卡"：阿哈面具框（头像不在这个区域）/ 敌方 / 空槽 → 不交单位名。
        # ⚠️ **菱形（elation）例外**：实测 `t=205` 是一张**带银狼头像的欢愉技卡**
        #    （score 1.90 / 间距 1.14），而欢愉技的口径是"伤害算给释放该技的成员本人"（用户 Q5）
        #    → 这种卡**可以**给出身份，但 card_type 仍记 elation，让下游知道这是一次欢愉技。
        ok, reject = False, "not_unit"
    return {
        "unit": unit if ok else None,
        "raw": unit,
        "score": round(best, 3),
        "margin": round(margin, 3),
        "owner": unit if ok else None,
        "kind": "ally" if ok else "unknown",
        "marker": mk,
        "inserted": (mk in ("ally_star", "enemy_star")) if card_type in ("unit", "enemy") else None,
        "card_type": card_type,
        "marker_score": mscore,
        "hue": hue,
        "detail": round(detail, 1),
        "reject": reject,
        "scores": {k: round(v[0], 3) for k, v in rank},
    }


def read_window(srcs, bank=None, thr=THR, min_margin=MIN_MARGIN, min_votes=1):
    """多帧投票（实时 30fps 用）。"""
    if bank is None:
        bank = load_bank()
    tally, detail = {}, []
    for s in srcs:
        try:
            r = read_actor(s, bank, thr, min_margin)
        except FileNotFoundError:
            continue
        detail.append(r)
        if r["unit"]:
            d = tally.setdefault(r["unit"], {"votes": 0, "score": 0.0})
            d["votes"] += 1
            d["score"] += r["score"]
    if not tally:
        return {"unit": None, "votes": 0, "n": len(detail), "detail": detail}
    unit, d = max(tally.items(), key=lambda kv: (kv[1]["votes"], kv[1]["score"]))
    ok = d["votes"] >= min_votes
    return {"unit": unit if ok else None, "votes": d["votes"], "n": len(detail),
            "score": round(d["score"], 2), "detail": detail,
            "tally": {k: v["votes"] for k, v in sorted(tally.items(), key=lambda kv: -kv[1]["votes"])}}


def selftest(verbose=True):
    """真值帧逐条核对（标签文件里的每一帧）。返回不一致清单。"""
    bank = load_bank()
    with open(LABELS_PATH, encoding="utf-8") as f:
        labels = json.load(f)
    bad = []
    for unit in UNITS:
        for t in labels.get(unit, []):
            try:
                r = read_actor(t, bank)
            except FileNotFoundError:
                bad.append("t=%s 缺帧" % t)
                continue
            if r["unit"] != unit:
                bad.append("t=%s 期望%s 实得%s（分数%.2f 间距%.2f）"
                           % (t, unit, r["unit"] or "待复核", r["score"], r["margin"]))
            elif verbose:
                print("  OK  t=%-6s -> %-4s 分数%.2f" % (T.fmt_t(t), unit, r["score"]))
    return bad


def _cli():
    import argparse
    ap = argparse.ArgumentParser(description="录屏2 行动轴顶端卡识别（线2）")
    ap.add_argument("frames", nargs="*", help="帧号（如 12 26 35）或小块路径")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--bank", default=BANK_PATH)
    args = ap.parse_args()
    if args.build:
        build_bank(out_path=args.bank)
        return 0
    bank = load_bank(args.bank)
    if args.selftest:
        print("模板库 %s：%s" % (args.bank, {u: m.shape[0] for u, m in bank.items()}))
        bad = selftest()
        if bad:
            print("\n自检不通过（%d 条）：" % len(bad))
            for b in bad:
                print("  ! " + b)
            return 1
        print("\n自检通过")
        return 0
    if not args.frames:
        print("用法：python axis_actor_team2.py --build | --selftest | 12 13 26 [--json]")
        return 0
    out = []
    for t in args.frames:
        src = t if not str(t).replace(".", "").isdigit() else float(t)
        try:
            r = read_actor(src, bank)
        except FileNotFoundError as e:
            print("找不到帧/文件：%s" % e)
            continue
        out.append(r)
        if not args.json:
            print("t=%-8s 顶端=%-6s 分数%.2f 间距%.2f 标记%-10s 类型%-8s 拒绝=%s" %
                  (t, r["unit"] or "待复核", r["score"], r["margin"], r["marker"],
                   r["card_type"], r["reject"]))
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
