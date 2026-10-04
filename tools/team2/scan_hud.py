# -*- coding: utf-8 -*-
"""【线2】全片扫描录屏2 的 HUD 读数（两套字体各读一遍再裁决）→ `out/frames_L2.csv`。

用途：
  1. 给"出伤占比"提供数值序列（配合行动轴顶端卡 = 归属）；
  2. **把 Q1 的存疑真值钉在时刻上**（`--find 2052321` 搜某个数出现在哪些时刻）。

用法：
  python -u scan_hud2_L2.py                     # 扫全部帧 → out/frames_L2.csv
  python -u scan_hud2_L2.py --find 2052321      # 在结果里找某个数值/片段的时刻
  python -u scan_hud2_L2.py --timeline          # 只打印"数值变化"的时间线（压缩重复）
"""
# [P3 整理] 原路径：scan_hud2_L2.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import csv
import glob
import os
import sys

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
sys.path.insert(0, HERE)

import hud_read_team2 as H      # noqa: E402

CROP_DIR = "frames/axis2_L2"
OUT_CSV = "out/frames_L2.csv"


def scan(model, model_pixel, crop_dir=CROP_DIR):
    paths = sorted(glob.glob(os.path.join(crop_dir, "*_hud.png")))
    rows = []
    for p in paths:
        t = float(os.path.basename(p)[1:9])
        try:
            r = H.read_crop_dual(p, model=model, model_pixel=model_pixel)
        except Exception as e:                     # noqa: BLE001
            print("  t=%s 读数异常：%s" % (t, e))
            continue
        dm, pm = r["default"]["meta"], r["pixel"]["meta"]
        rows.append({
            "t": t, "text": r["text"], "verdict": r["verdict"], "font": r["font"],
            "conf": round(r["conf"], 3), "how": r.get("how", ""),
            "cand": r.get("cand", ""),
            "def_text": r["default"]["text"], "def_verdict": r["default"]["verdict"],
            "def_digits": dm.get("n_digits", 0), "def_chain": dm.get("chain"),
            "def_h": round(float(dm.get("h_med") or 0), 1),
            "pix_text": r["pixel"]["text"], "pix_verdict": r["pixel"]["verdict"],
            "pix_digits": pm.get("n_digits", 0), "pix_h": round(float(pm.get("h_med") or 0), 1),
        })
    return rows


def write_csv(rows, path=OUT_CSV):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    keys = ["t", "text", "verdict", "font", "conf", "how", "cand",
            "def_text", "def_verdict", "def_digits", "def_chain", "def_h",
            "pix_text", "pix_verdict", "pix_digits", "pix_h"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("已写出 %s（%d 行）" % (path, len(rows)))


def timeline(rows):
    """把连续相同的读数压成段（2 帧以上才算稳定；单帧标记为瞬时）。"""
    segs = []
    for r in rows:
        key = (r["text"], r["font"]) if r["verdict"] == "ok" else None
        if segs and segs[-1]["key"] == key:
            segs[-1]["t1"] = r["t"]
            segs[-1]["n"] += 1
        else:
            segs.append({"key": key, "t0": r["t"], "t1": r["t"], "n": 1,
                         "text": r["text"], "verdict": r["verdict"], "font": r["font"],
                         "how": r.get("how", "")})
    print("\n数值时间线（%d 段；n=该读数持续的整数秒帧数）" % len(segs))
    for s in segs:
        if s["key"] is None:
            continue
        print("  t=%-6s~%-6s n=%-3d %-11s %-6s %s   %s"
              % (H.__name__ and s["t0"], s["t1"], s["n"], s["text"], s["verdict"],
                 s["font"], s["how"]))
    stable = [s for s in segs if s["key"] is not None and s["n"] >= 2]
    print("  其中稳定段（n≥2）：%d；单帧瞬时读数：%d"
          % (len(stable), len([s for s in segs if s["key"] is not None and s["n"] < 2])))
    return segs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=CROP_DIR)
    ap.add_argument("--csv", default=OUT_CSV)
    ap.add_argument("--find", default="", help="在结果里找这个数值（可逗号分隔多个）")
    ap.add_argument("--timeline", action="store_true")
    ap.add_argument("--no-scan", action="store_true", help="复用已有 CSV，不重新扫描")
    args = ap.parse_args()

    if args.no_scan and os.path.exists(args.csv):
        with open(args.csv, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            r["t"] = float(r["t"])
            r["conf"] = float(r["conf"])
    else:
        model = H.load_model()
        model_pixel = H.load_pixel_model()
        rows = scan(model, model_pixel, args.dir)
        write_csv(rows, args.csv)

    ok = [r for r in rows if r["verdict"] == "ok"]
    empty = [r for r in rows if r["verdict"] == "空"]
    pend = [r for r in rows if r["verdict"] == "待复核"]
    print("\n统计：总 %d 帧；ok %d、空 %d、待复核 %d" % (len(rows), len(ok), len(empty), len(pend)))
    from collections import Counter
    print("  采纳字体分布：%s" % dict(Counter(r["font"] for r in ok)))
    print("  逐帧两套字体各自的完整率：常规体 %d、像素体 %d"
          % (sum(1 for r in rows if r["def_verdict"] == "ok"),
             sum(1 for r in rows if r["pix_verdict"] == "ok")))

    if args.find:
        print("\n按数值搜索：")
        for tgt in [x.strip() for x in args.find.split(",") if x.strip()]:
            hits = [r["t"] for r in rows if r["text"] == tgt]
            hits_c = [r["t"] for r in rows if r.get("cand") == tgt]
            print("  %-10s 采纳读数命中：%s" % (tgt, hits or "（无）"))
            if hits_c:
                print("             （作为待复核候选出现：%s）" % hits_c)
    if args.timeline:
        timeline(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
