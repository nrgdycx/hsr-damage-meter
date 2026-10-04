# -*- coding: utf-8 -*-
"""B 线验收脚本。

三件事：
  1) `glyphs`  —— 在**全部缓存帧**上逐字形比对：本线 numpy 分割 vs A 线 read_hud.extract_glyphs
                  （证明"实时管线"与"离线管线"的分割结果逐像素一致）
  2) `offline` —— 在**全部缓存帧**上比对最终读数：ONNX 路径 vs read_hud（torch 路径）
  3) `live`    —— 连续抓 100 帧，报告平均/最大耗时；并给出"抓屏 + 推理"的单帧总耗时

用法：
    python verify_B.py glyphs  [--limit N]
    python verify_B.py offline [--limit N]
    python verify_B.py live    [--frames 100]
    python verify_B.py all
"""
from __future__ import annotations
# [P3 整理] 原路径：verify_B.py（已移入 tools/，功能见 tools/README.md）
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
import time

import numpy as np

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
sys.path.insert(0, HERE)
os.chdir(HERE)

CACHE = os.path.join(HERE, "frames", "glyphcache")


def cached_frames(limit=0):
    fs = sorted(glob.glob(os.path.join(CACHE, "f*.png")))
    return fs[:limit] if limit else fs


def _load_rgb(p):
    from PIL import Image
    return np.asarray(Image.open(p).convert("RGB"))


# ── 1) 逐字形一致性 ────────────────────────────────────────────────────────
def check_glyphs(limit=0, verbose=True):
    import read_hud
    from hud_digits import CY0, CY1, CX0, CX1, extract_glyphs

    fs = cached_frames(limit)
    if verbose:
        print("逐字形比对：%d 张缓存帧" % len(fs))
    bad = []
    n_glyph = 0
    for i, p in enumerate(fs):
        a = _load_rgb(p)
        mine = extract_glyphs(a[CY0:CY1, CX0:CX1])
        theirs = read_hud.extract_glyphs(p)          # 返回 torch 张量
        n_glyph += len(theirs)
        if len(mine) != len(theirs):
            bad.append((os.path.basename(p), "字形数 %d vs %d" % (len(mine), len(theirs))))
            continue
        for j, ((v, w, h), t) in enumerate(zip(mine, theirs)):
            # read_hud.extract_glyphs 返回 (glyph tensor 1xGHxGW, 宽, 高)
            tv = t[0][0, 0].numpy()
            if tv.shape != v.shape or not np.array_equal(tv, v):
                diff = float(np.abs(tv - v).max()) if tv.shape == v.shape else float("nan")
                bad.append((os.path.basename(p), "第%d个字形不一致 最大差 %s" % (j, diff)))
                break
            if (w, h) != tuple(t[1:]):
                bad.append((os.path.basename(p), "第%d个字形宽高 %s vs %s" % (j, (w, h), tuple(t[1:]))))
                break
        if verbose and (i + 1) % 50 == 0:
            print("   ... %d/%d" % (i + 1, len(fs)))
    ok = len(fs) - len({b[0] for b in bad})
    print("逐字形一致：%d/%d 帧（共 %d 个字形）" % (ok, len(fs), n_glyph))
    for name, why in bad[:20]:
        print("   ✗ %s  %s" % (name, why))
    return {"frames": len(fs), "ok": ok, "glyphs": n_glyph, "bad": bad}


# ── 2) 离线读数一致性（ONNX vs torch）──────────────────────────────────────
def check_offline(limit=0, verbose=True):
    import read_hud
    from hud_digits import HudOnnxReader

    torch_model = read_hud.load_model()
    onnx_reader = HudOnnxReader()
    fs = cached_frames(limit)
    print("读数比对：%d 张缓存帧（torch/read_hud  vs  onnx/hud_digits）" % len(fs))
    same = diff = both_empty = 0
    cases = []
    t_torch = t_onnx = 0.0
    for p in fs:
        t0 = time.perf_counter()
        s1, _, _ = read_hud.read_frame(torch_model, p)
        t_torch += time.perf_counter() - t0
        t0 = time.perf_counter()
        s2, _, _ = onnx_reader.read_png(p)
        t_onnx += time.perf_counter() - t0
        if not s1 and not s2:
            both_empty += 1
            continue
        if s1 == s2:
            same += 1
        else:
            diff += 1
            cases.append((os.path.basename(p), s1, s2))
    n = len(fs)
    print("完全一致 %d/%d（其中两边都读不出字的帧 %d；不一致 %d）" % (same + both_empty, n, both_empty, diff))
    for name, a, b in cases[:20]:
        print("   ✗ %s  read_hud=%-12s onnx=%-12s" % (name, a or "(空)", b or "(空)"))
    print("   平均耗时（含整张 PNG 解码）: read_hud %.1fms / onnx %.1fms"
          % (t_torch / n * 1000, t_onnx / n * 1000))
    return {"frames": n, "same": same, "diff": diff, "empty": both_empty, "cases": cases}


# ── 3) 实时抓屏 + 推理 耗时 ────────────────────────────────────────────────
def check_live(frames=100, repeat_axis=True):
    import capture
    from hud_digits import HudOnnxReader

    reader = HudOnnxReader()
    g_t, x_t, i_t, total_t = [], [], [], []

    # 用真帧字形做"有数字时"的推理耗时基准（内容不影响抓屏耗时）
    real = _load_rgb(os.path.join(CACHE, "f00134.00.png"))
    from hud_digits import CY0, CY1, CX0, CX1, extract_glyphs

    crop = real[CY0:CY1, CX0:CX1]
    for _ in range(10):
        reader.classify(extract_glyphs(crop))

    with capture.Grabber() as g:
        print("物理屏 %dx%d（DPI 感知已开启）" % g.screen)
        g.grab_rgb(capture.HUD_REGION)
        live_readings = []
        for k in range(frames):
            t0 = time.perf_counter()
            hud = g.grab_rgb(capture.HUD_REGION)
            t1 = time.perf_counter()
            s, conf, res = reader.read_region(hud, top=capture.HUD_REGION["top"])
            t2 = time.perf_counter()
            if repeat_axis or k == 0:
                t3 = time.perf_counter()
                g.grab_rgb(capture.AXIS_REGION)
                t4 = time.perf_counter()
                x_t.append((t4 - t3) * 1000)
            g_t.append((t1 - t0) * 1000)
            i_t.append((t2 - t1) * 1000)
            total_t.append((t2 - t0) * 1000)
            if s:
                live_readings.append((k, s, conf))

    def st(a, label):
        a = np.asarray(a)
        print("   %-26s 平均 %6.2fms  中位 %6.2fms  p95 %6.2fms  最大 %6.2fms"
              % (label, a.mean(), np.percentile(a, 50), np.percentile(a, 95), a.max()))
        return {"avg": float(a.mean()), "max": float(a.max()), "p95": float(np.percentile(a, 95))}

    print("连续 %d 帧：" % frames)
    r = {}
    r["grab_hud"] = st(g_t, "抓 HUD 526x80")
    r["read_hud"] = st(i_t, "掩膜+分割+ONNX 推理")
    r["e2e_hud"] = st(total_t, "抓屏+推理（HUD）")
    if x_t:
        r["grab_axis"] = st(x_t, "抓行动轴 280x1250")

    # 空屏时"读取"几乎不做功；这里单独量一次**真有 6 位数字**时的读取耗时，避免报虚数
    real_ts, ext_ts, cls_ts = [], [], []
    s_real = ""
    for _ in range(frames):
        t0 = time.perf_counter()
        gl = extract_glyphs(crop, top=CY0)
        t1 = time.perf_counter()
        res_real = reader.classify(gl)
        t2 = time.perf_counter()
        ext_ts.append((t1 - t0) * 1000)
        cls_ts.append((t2 - t1) * 1000)
        real_ts.append((t2 - t0) * 1000)
        s_real = "".join(str(d) if c >= reader.conf_min else "?" for d, c in res_real)
    r["read_real"] = st(real_ts, "读取实测（真 6 位数字）")
    st(ext_ts, "  ├─ 掩膜+列分割")
    st(cls_ts, "  └─ ONNX 分类 %d 个字形" % len(gl))
    print("      ^ 该基准帧读数 %s（离线 read_hud 读的是 47794）" % (s_real or "(空)"))

    print("\n屏幕上现在读到的内容：", live_readings[:8] if live_readings else "（HUD 区当前没有数字，属正常：游戏没在出伤害数字）")
    worst = r["e2e_hud"]["max"] + r["grab_axis"]["max"] / (frames if repeat_axis else 1)
    print("单帧最坏合计（HUD 端到端 + 行动轴摊销）: %.2fms  → 硬需求 <100ms %s"
          % (worst, "满足" if worst < 100 else "不满足"))
    print("若每帧都抓行动轴: %.2fms（仍 %s 100ms）"
          % (r["e2e_hud"]["max"] + r["grab_axis"]["max"],
             "满足" if r["e2e_hud"]["max"] + r["grab_axis"]["max"] < 100 else "超出"))
    return r


# ── 4) 区域自检：在"更大的搜索范围"里找回暖黄数字，核对固定区域没跑偏 ────
def check_region(save="samples/live_region_B.png"):
    """在 x2000~2880 / y200~450 的范围里找 HUD 数字的暖黄掩膜，报告实际位置。

    用途：游戏换分辨率 / 换窗口模式后，固定区域（CX0..CX1, CY0..CY1）可能跑偏，
    这一步能直接看出数字的实际包围盒在哪，以及固定区域是否仍然读得出同样的数。
    屏幕上没有伤害数字时（没在打）会如实报"未找到"。
    """
    from PIL import Image, ImageDraw

    import capture
    from hud_digits import CX0, CX1, CY0, CY1, HudOnnxReader

    search = {"left": 2000, "top": 200, "width": 880, "height": 250}
    with capture.Grabber() as g:
        img = g.grab_rgb(search)
        hud = g.grab_rgb(capture.HUD_REGION)
    a = img.astype(np.int16)
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    m = (R > 225) & (G > 225) & (B >= 185) & ((R - B) > 25)
    cols = np.where(m.any(axis=0))[0]
    rows = np.where(m.any(axis=1))[0]
    print("搜索范围 x%d~%d y%d~%d（物理像素）" % (search["left"], search["left"] + search["width"],
                                                search["top"], search["top"] + search["height"]))
    if len(cols):
        print("   找到暖黄像素：x %d~%d (绝对)  y %d~%d (绝对)，共 %d px"
              % (search["left"] + cols[0], search["left"] + cols[-1],
                 search["top"] + rows[0], search["top"] + rows[-1], int(m.sum())))
        inside = (search["left"] + cols[0] >= CX0 and search["left"] + cols[-1] <= CX1 - 1
                  and search["top"] + rows[0] >= CY0 and search["top"] + rows[-1] <= CY1 - 1)
        print("   是否完全落在固定区域 x%d~%d y%d~%d 内: %s"
              % (CX0, CX1, CY0, CY1, "是" if inside else "**否** —— 需要重新校准区域"))
    else:
        print("   未找到暖黄像素（屏幕上现在没有伤害数字；要验证请在游戏里打一下再看）")
    reader = HudOnnxReader()
    s, c, res = reader.read_region(hud, top=CY0)
    print("   固定区域当前读数: %s（%d 个字形，最低置信 %.2f）" % (s or "(空)", len(res), c))

    if save:
        os.makedirs(os.path.dirname(os.path.abspath(save)), exist_ok=True)
        vis = Image.fromarray(img.copy())
        d = ImageDraw.Draw(vis)
        d.rectangle([CX0 - search["left"], CY0 - search["top"],
                     CX1 - search["left"], CY1 - search["top"]], outline=(255, 0, 0), width=2)
        d.text((4, 4), "search 880x250, box=HUD region", fill=(255, 0, 0))
        vis.save(save)
        print("   搜索范围 + 固定区域框图: %s" % save)
    return {"found": bool(len(cols))}


def main(argv=None):
    ap = argparse.ArgumentParser(description="B 线验收")
    ap.add_argument("what", choices=["glyphs", "offline", "live", "region", "all"])
    ap.add_argument("--limit", type=int, default=0, help="只测前 N 张缓存帧")
    ap.add_argument("--frames", type=int, default=100, help="live 模式连续抓多少帧")
    a = ap.parse_args(argv)

    out = {}
    if a.what in ("glyphs", "all"):
        out["glyphs"] = check_glyphs(a.limit)
    if a.what in ("offline", "all"):
        out["offline"] = check_offline(a.limit)
    if a.what in ("live", "all"):
        out["live"] = check_live(a.frames)
    if a.what in ("region", "all"):
        out["region"] = check_region()

    with open(os.path.join(HERE, "out", "verify_B_%s.json" % a.what), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print("\n结果已写入 out/verify_B_%s.json" % a.what)
    return 0


if __name__ == "__main__":
    sys.exit(main())
