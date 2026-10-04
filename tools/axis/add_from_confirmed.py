# -*- coding: utf-8 -*-
"""把"当年确认过、但没进库"的角色，从已确认锚点补建成库条目。

背景：旧录屏（123200）那轮用户逐格确认过 11 个角色（`out/teams/rec1003_confirmed.json`），
但后来建库用的是另一份 24 人的时间标注，把 佩拉/真理/周日 等**覆盖掉了** ——
它们在库里一直缺着，而卡片其实还在 `frames/battle1003`。

用法：
    python tools/axis/add_from_confirmed.py --json out/teams/rec1003_confirmed.json \
        --cards frames/battle1003 --names 佩拉,真理,周日 [--window 3.0] [--dry-run]
"""
import argparse
import io
import json
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import axis_actor as T                      # noqa: E402
from harvest_characters import art_of_card, feat_fft, pair_score_shift   # noqa: E402
from build_from_annotation import feats_of_art, farthest_point            # noqa: E402
import axis_onboard                          # noqa: E402

# 用户口头名 → 官方条目名（尽量用原名）
ALIAS = {"真理": "真理医生", "周日": "星期日", "小三月": "三月七·存夏煦至"}


def imread_u(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(description="从已确认锚点补建库条目")
    ap.add_argument("--json", required=True)
    ap.add_argument("--cards", required=True)
    ap.add_argument("--names", required=True, help="逗号分隔（可用用户口头名，如 真理/周日）")
    ap.add_argument("--window", type=float, default=3.0, help="锚点前后取卡窗口（秒）")
    ap.add_argument("--max-frames", type=int, default=10)
    ap.add_argument("--bank", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    bank_path = args.bank or T.BANK_PATH
    conf = json.load(io.open(args.json, encoding="utf-8"))
    files = sorted(f for f in os.listdir(args.cards) if f.endswith(".png"))
    times = np.array([float(f[1:9]) for f in files])

    want = [w.strip() for w in args.names.split(",") if w.strip()]
    new_banks, report = {}, []
    for nm in want:
        ent = conf["characters"].get(nm)
        if not ent:
            print("！确认文件里没有「%s」，跳过" % nm)
            continue
        unit = ALIAS.get(nm, nm)
        refs = [float(s["t"]) for s in ent["samples"]]
        # 以第一个锚点为"本人"参照，窗口内取与之同人的卡
        k0 = int(np.argmin(np.abs(times - refs[0])))
        f0 = feat_fft(T.feats(art_of_card(imread_u(os.path.join(args.cards, files[k0])))))
        idxs = []
        for k, t in enumerate(times):
            if any(abs(t - r) <= args.window for r in refs):
                f = feat_fft(T.feats(art_of_card(imread_u(os.path.join(args.cards, files[k])))))
                if pair_score_shift(f0, f) >= 1.5:
                    idxs.append(k)
        if not idxs:
            print("！「%s」在窗口内没找到同人卡" % nm)
            continue
        arts = [art_of_card(imread_u(os.path.join(args.cards, files[k]))) for k in idxs]
        keep = farthest_point(arts, args.max_frames)
        chosen = [idxs[i] for i in keep]
        mats = [feats_of_art(arts[i], z) for i in keep for z in T.ZOOMS]
        new_banks[unit] = np.stack(mats).astype(np.float32)
        report.append((unit, len(idxs), len(chosen), new_banks[unit].shape[0],
                       [round(float(times[k]), 1) for k in chosen[:6]]))

    print("\n将补建 %d 个条目：\n" % len(new_banks))
    for unit, ncand, nframe, ntpl, ts_show in report:
        print("  %-10s 窗口内同人 %3d 张 → 取 %2d 帧 → 模板 %2d 张   例：%s"
              % (unit, ncand, nframe, ntpl, ts_show))
    if args.dry_run or not new_banks:
        print("\n--dry-run：没有写库")
        return 0
    n_old = len(axis_onboard.open_bank(bank_path).files)
    trim = {u: 0 for u in new_banks}          # 幂等：重跑先清空同名条目
    merged, rep = axis_onboard.merge_banks(bank_path, new_banks, trim_to=trim)
    np.savez_compressed(bank_path, **merged)
    T._BANK_CACHE.pop(bank_path, None)
    print("\n已写出 %s：条目 %d → %d；新增 %s；替换 %s"
          % (bank_path, n_old, len(merged), rep.get("appended"), rep.get("trimmed")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
