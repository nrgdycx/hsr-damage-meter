# -*- coding: utf-8 -*-
"""
HUD 数字读取器（最终版）—— 掩膜 + 列分割 + CNN 分类 + 多帧投票。

管线（每一环都是实测换来的，参数不要随手改）：
  1) 裁剪数字区域 —— ⚠️ 自线7 起**不再用写死的绝对坐标**：`hud_glyphs.extract` /
     `hud_profiles.glyphs` 会先按画面里的黄色墨迹动态定位（`geometry`），
     定位不出来才退回参考标定框。用【淡黄】掩膜把 HUD 数字层与伤害飘字分离；
  2) 列分割字形，用「宽/高比 + 最小高度」剔掉左侧那条细横线和被切残的碎块；
  3) 每个字形按自身峰值归一化 → 24×34 灰度 → CNN 分类（留一帧准确率 94.6%）；
  4) **按右对齐组装**（HUD 数字本身右对齐，左边缺字不影响右边对应）；
  5) 同一数值会停留 ~0.5 秒 → 多帧逐位投票，把随机误差压掉。

为什么不用 VLM / 通用 OCR：实测 VLM 会凭空造数字（曾编出 123456789、1480776），
RapidOCR 对这套美术字也不稳（48076 读成 94087）。
"""

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from ffmpeg_path import require_ffmpeg as _req_ff
import json
import os
import subprocess
import sys
from collections import Counter

import numpy as np
import torch
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_digit_cnn import DigitCNN, GW, GH  # noqa: E402
import hud_glyphs  # noqa: E402

FFMPEG = _req_ff()   # 见 ffmpeg_path.py（可用 HSR_FFMPEG 指定）
MODEL_PT = "out/digit_cnn.pt"

CY0, CY1 = hud_glyphs.CY0, hud_glyphs.CY1
CX0, CX1 = hud_glyphs.CX0, hud_glyphs.CX1   # 左界 2350：容纳到千亿（12 位）量级
BAR_ROWS = hud_glyphs.BAR_ROWS              # 数字左侧细横线所在行带：分割时挖空以断开粘连
W_MAX = hud_glyphs.W_MAX
H_MIN = hud_glyphs.H_MIN


def load_model(profile="default"):
    """加载该字体档案的规范模型（现在是集成；旧版单模型文件也兼容）。

    ⚠️ 未标定的字体档案（如 `yinlang999`）会**直接报错**而不是回退到常规字体模型 ——
    用错字体模型认数字会给出"自信但错误"的结果，比明确报错危险得多。
    """
    import hud_profiles as HP
    from train_digit_cnn import load_any_pt
    return load_any_pt(HP.require_ready(profile)["model"])


def extract_glyphs(png):
    """返回 [(glyph tensor 1×GH×GW, 像素宽, 像素高)]，已过滤碎块与细横线。

    掩膜/分割的唯一实现在 hud_glyphs.extract()（训练侧 digit_dataset.py 调同一个函数，
    避免"训练与推理管线漂移"这个老坑）。
    """
    a = np.asarray(Image.open(png).convert("RGB")).astype(np.int16)
    return [(torch.tensor(v)[None, None], w, h) for v, w, h in hud_glyphs.extract(a)]


def classify(model, glyphs):
    """返回 [(数字或None, 概率)] —— None 表示该字形的最高概率低于置信阈值。"""
    if not glyphs:
        return []
    x = torch.cat([g[0] for g in glyphs], 0)
    with torch.no_grad():
        p = torch.softmax(model(x), 1)
    conf, pred = p.max(1)
    return [(int(d), float(c)) for d, c in zip(pred, conf)]


def read_frame(model, png, conf_min=0.55, profile="default", geom_guard=True):
    """
    读单帧。返回 (数值字符串, 最低置信度, 明细)。低置信位、以及**几何超出该字体范围**的位标 '?'。

    字体档案见 hud_profiles.py：不同字体的 HUD 数字（例如用户提到的"银狼999 总伤"）
    形状不同，**必须用自己的分类器**，拿常规字体模型硬认会给出自信但错误的答案。
    """
    return read_array(model, np.asarray(Image.open(png).convert("RGB")).astype(np.int16),
                      conf_min=conf_min, profile=profile, geom_guard=geom_guard)


def read_array(model, a, conf_min=0.55, profile="default", geom_guard=True):
    """read_frame 的 ndarray 版（实时线直接用内存里的图，省一次 PNG 编解码）。"""
    import hud_profiles as HP
    gs = HP.glyphs(profile, a)
    if not gs:
        return "", 0.0, []
    x = torch.tensor(np.stack([v for v, _, _ in gs])[:, None], dtype=torch.float32)
    with torch.no_grad():
        p = torch.softmax(model(x), 1)
    conf, pred = p.max(1)
    res = []
    for (v, w, h), d, c in zip(gs, pred.tolist(), conf.tolist()):
        ok, why = HP.geom_ok(profile, w, h) if geom_guard else (True, "")
        res.append({"digit": int(d) if ok else None, "conf": float(c) if ok else 0.0,
                    "w": w, "h": h, "geom_ok": ok, "why": why})
    chars = [str(r["digit"]) if (r["digit"] is not None and r["conf"] >= conf_min) else "?"
             for r in res]
    mins = min([r["conf"] for r in res], default=0.0)
    return "".join(chars), mins, res


def read_array_for_actor(a, actor=None, conf_min=0.55):
    """
    **A 线 ⇄ E 线的衔接点**：由"当前行动者（行动轴顶端是谁）"决定用哪套字体档案。

    为什么这么做（而不是从图像里猜字体）：用户已确认 —— 像素风数字**只在银狼999 的
    强化普攻**出现。行动者身份是 E 线本来就要交付的东西，用它当切换信号比任何
    图像启发式都可靠。

    a     : 整帧 RGB ndarray
    actor : E 线给出的当前行动者（字符串/N者；None 或未知 → 常规字体档案）

    返回 dict：
      verdict    "ok" / "待复核"
      text       读数（待复核时为空）
      profile    实际使用的字体档案名
      n_glyphs   切出的字形数（用来验证"这段确实是另一种字体、且字形切得出来"）
      reason     待复核的原因
    """
    import hud_profiles as HP
    prof = HP.profile_for_actor(actor)
    p = HP.get(prof)
    try:
        gs = HP.glyphs(prof, a)
    except RuntimeError as e:
        return {"verdict": "待复核", "text": "", "profile": prof, "actor": actor,
                "n_glyphs": 0, "reason": str(e)}
    if not HP.is_ready(prof):
        return {"verdict": "待复核", "text": "", "profile": prof, "actor": actor,
                "n_glyphs": len(gs), "label": p["label"],
                "reason": ("当前行动者=%r → 该段用『%s』，但它的分类器还没训练："
                           "不做猜测，标待复核（已切出 %d 个字形）" % (actor, p["label"], len(gs)))}
    model = load_model(prof)
    text, conf, detail = read_array(model, a, conf_min=conf_min, profile=prof)
    bad = [r for r in detail if r["digit"] is None or r["conf"] < conf_min]
    return {"verdict": "ok" if text and not bad else "待复核", "text": text,
            "conf": conf, "profile": prof, "actor": actor, "n_glyphs": len(gs),
            "label": p["label"],
            "reason": "" if (text and not bad) else "低置信或几何超范围的字形 %d 个" % len(bad)}


def read_for_actor(png, actor=None, conf_min=0.55):
    """read_array_for_actor 的 PNG 版。"""
    return read_array_for_actor(np.asarray(Image.open(png).convert("RGB")).astype(np.int16),
                                actor=actor, conf_min=conf_min)


def vote_frames_checked(model, frames, profile="default", conf_min=0.55):
    """
    多帧投票 + **可信度判定**（专门用来防"换了字体却静默读错"）。

    返回 dict：
      text      投出的数值（可能含 '?'）
      verdict   "ok" / "待复核"
      reasons   为什么不可信（人话）
      readings  各帧读数
      geom_bad  几何超范围的帧数

    判定口径（宁可标待复核，不要错）：
      · 有字形几何超出该字体观测范围 → 疑似换字体/换分辨率/区域跑偏
      · 出现 '?'（低置信或几何不合格）
      · 逐位投票的**最低胜率** < 0.6（同一数值在窗口内读法不一致）
    """
    import hud_profiles as HP
    readings, geoms, lowconf = [], 0, 0
    for t, p in frames:
        s, _, detail = read_frame(model, p, conf_min, profile)
        if not detail:
            continue
        readings.append((t, s))
        lowconf += sum(1 for r in detail if not r["geom_ok"] or r["conf"] < conf_min)
        geoms += sum(1 for r in detail if not r["geom_ok"])
    reasons = []
    if not readings:
        return {"text": "", "verdict": "待复核", "reasons": ["窗口里没有任何读数"],
                "readings": [], "geom_bad": 0}
    if geoms:
        reasons.append("%d 个字形几何超出该字体观测范围（疑似换了字体/分辨率，或区域跑偏）" % geoms)
    if lowconf:
        reasons.append("%d 个字形低置信" % lowconf)
    text, votes, n = vote_frames(model, frames, conf_min)
    share = 1.0
    for v in votes:
        tot = sum(v.values()) or 1
        share = min(share, max(v.values()) / tot)
    if share < 0.6:
        reasons.append("逐位投票最低胜率仅 %.0f%%（同窗口内读法不一致）" % (share * 100))
    if "?" in (text or ""):
        reasons.append("读数里含 '?'")
    return {"text": text, "verdict": "ok" if not reasons else "待复核",
            "reasons": reasons, "readings": readings, "geom_bad": geoms,
            "share": round(share, 3), "frames": n,
            "profile": profile, "profile_label": HP.get(profile)["label"]}


def vote_frames(model, frames, conf_min=0.55):
    """
    多帧逐位投票。frames: [(时间, png路径), ...]
    返回 (投出的数值, 各位置票数明细, 帧数)
    """
    readings = []
    for t, p in frames:
        s, _, _ = read_frame(model, p, conf_min)
        if s:
            readings.append((t, s))
    if not readings:
        return None, [], 0
    # ── 多帧投票：先按"位数众数"锁定位数，再逐位投票 ──
    # 教训：曾试过"优先采信位数更多的读数"（理由是分割只会截断、不会多造字），
    # 结果被偶然多切出一位的杂散读数带偏（如 1116982 压过正确的 721193）。
    # 现在改为稳妥做法：位数取众数（个别异常读数无法改变结论），再在同样位数内逐位投票。
    cnt = Counter(len(s) for _, s in readings)
    L = cnt.most_common(1)[0][0]
    picked = [s for _, s in readings if len(s) == L]
    votes = [Counter() for _ in range(L)]
    for s in picked:
        for i, ch in enumerate(s):
            votes[i][ch] += 1
    final = "".join(v.most_common(1)[0][0] if v else "?" for v in votes)
    return final, [dict(v) for v in votes], len(picked)


def grab(video, t, out_png):
    if os.path.exists(out_png):
        return True
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    subprocess.run([FFMPEG, "-ss", "%.3f" % t, "-i", video, "-frames:v", "1", "-y", out_png],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return os.path.exists(out_png)


def read_video_window(video, t0, t1, fps=6.0, conf_min=0.55):
    """对一段时间窗口抽帧投票（实时场景下等价于"数值稳定期间累积若干帧再定论"）。"""
    model = load_model()
    frames = []
    n = max(1, int((t1 - t0) * fps))
    for i in range(n):
        t = t0 + i / fps
        p = "frames/vote/v%08.3f.png" % t
        if grab(video, t, p):
            frames.append((t, p))
    return vote_frames(model, frames, conf_min)


if __name__ == "__main__":
    import time
    model = load_model()
    print("模型已加载。单帧读取自检：\n")
    KNOWN = {106: "2809", 109: "48076", 134: "47794", 135: "191176",
             152: "324751", 167: "113891", 195: "319195",
             100: "121418", 102: "304505"}
    ok = tot = 0
    for t, val in sorted(KNOWN.items()):
        p = "frames/glyphcache/f%08.2f.png" % t
        if not os.path.exists(p):
            print("   t=%-5s 无缓存帧" % t)
            continue
        t0 = time.time()
        s, c, _ = read_frame(model, p)
        dt = (time.time() - t0) * 1000
        mark = "✓" if s == val else "✗"
        ok += (s == val)
        tot += 1
        print("   t=%-5s 期望%-9s 读出%-9s %s  (最低置信 %.2f, 耗时 %.0fms)" % (t, val, s, mark, c, dt))
    print("\n单帧整体正确率 %d/%d" % (ok, tot))
