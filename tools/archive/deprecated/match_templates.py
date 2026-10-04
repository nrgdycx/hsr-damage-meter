# -*- coding: utf-8 -*-
"""
录屏2（欢愉队）单位识别 —— 用右侧面板的 4 个头像建模板，匹配行动轴卡片。

背景：
  * 录屏2 队伍与录屏1 完全不同 → E 线对录屏2 的单位识别 100% 弃权（安全行为，但不是 bug）
  * 用户目标「欢愉队出伤占比」全靠录屏2 → 必须把这一队认出来
  * 用户指路：视频开头右侧有队伍人物和名字
    实测：右侧 y540/690/830/970 四条 = 银狼 / 爻光 / 火花 / 真珠（各带头像 + 血条 + 编号1-4）

做法：
  1) 从 t=0 帧右侧面板裁 4 个头像（去掉名字与编号）
  2) 再用行动轴顶端卡（x66-300, y66-195）与这 4 个头像做多尺度匹配
  3) 报告：哪张卡最像谁 + 分数，用于确认"卡 ↔ 名字"的对应
"""
# [P3 整理] 原路径：match_team2_M.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import glob
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SRC = [c for c in sorted(glob.glob("frames/team_M/d*.png")) if "0.0" in os.path.basename(c)]
TEAM = [("银狼", 2600, 505, 2870, 660), ("爻光", 2600, 655, 2870, 810),
        ("火花", 2600, 795, 2870, 950), ("真珠", 2600, 935, 2870, 1090)]
AXIS = (66, 66, 300, 196)      # 行动轴顶端卡
OUT_TPL = "out/team2_templates_M"


def font(sz):
    for p in ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/arialbd.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            continue
    return ImageFont.load_default()


def build_templates():
    """从右侧面板裁 4 个头像，去掉右侧编号圆牌，存成模板。"""
    os.makedirs(OUT_TPL, exist_ok=True)
    if not SRC:
        raise FileNotFoundError("找不到 frames/team_M/d000.0.png")
    im = Image.open(SRC[0]).convert("RGB")
    out = {}
    for name, x0, y0, x1, y1 in TEAM:
        # 右侧编号圆牌约占 90px，裁掉
        c = im.crop((x0, y0, x1 - 90, y1))
        c.save(os.path.join(OUT_TPL, "%s.png" % name))
        out[name] = np.asarray(c.convert("L"), dtype=np.float32)
    return out


def top_card(video_frame_png):
    im = Image.open(video_frame_png).convert("RGB")
    return im, np.asarray(im.crop(AXIS).convert("L"), dtype=np.float32), im.crop(AXIS)


def match(card, tpls, scales=(0.45, 0.55, 0.65, 0.75, 0.85, 0.95, 1.05, 1.2, 1.4, 1.6)):
    res = {}
    for name, t in tpls.items():
        best = -2.0
        for sc in scales:
            th, tw = int(t.shape[0] * sc), int(t.shape[1] * sc)
            if th < 16 or tw < 16 or th > card.shape[0] or tw > card.shape[1]:
                continue
            tt = cv2.resize(t, (tw, th), interpolation=cv2.INTER_AREA)
            if tt.std() < 5:
                continue
            r = cv2.matchTemplate(card, tt, cv2.TM_CCOEFF_NORMED)
            best = max(best, float(r.max()))
        res[name] = round(best, 3)
    return res


def main():
    tpls = build_templates()
    print("模板（录屏2 队伍，来自右侧面板）:", {k: v.shape for k, v in tpls.items()})

    # 用若干帧的顶端卡来验证对应关系
    times = [21.0, 22.0, 26.0, 30.0, 64.0, 110.0, 150.0, 200.0, 238.0, 300.0]
    tiles = []
    print("\n%-8s %-28s %s" % ("t", "各角色匹配分", "最高"))
    model = None
    for t in times:
        p = "frames/accept_M/t%08.2f.png" % t
        if not os.path.exists(p):
            continue
        _im, card, crop = top_card(p)
        sc = match(card, tpls)
        order = sorted(sc.items(), key=lambda kv: -kv[1])
        print("%-8.1f %-28s %s(%.3f)" % (t, " ".join("%s%.2f" % kv for kv in order),
                                         order[0][0], order[0][1]))
        # 出图：顶端卡 + 4 个模板缩略
        crop = crop.resize((crop.size[0] * 2, crop.size[1] * 2), Image.LANCZOS)
        W = crop.size[0] + 4 * 110 + 40
        H = max(crop.size[1], 150) + 40
        tile = Image.new("RGB", (W, H), (18, 18, 18))
        d = ImageDraw.Draw(tile)
        d.text((4, 2), "t=%.0f  最佳=%s(%.2f)" % (t, order[0][0], order[0][1]),
               font=font(16), fill=(255, 255, 0))
        tile.paste(crop, (4, 24))
        for i, (name, tp) in enumerate(tpls.items()):
            th = Image.fromarray(tp.astype(np.uint8)).convert("RGB")
            k = 100 / th.size[1]
            th = th.resize((int(th.size[0] * k), 100), Image.LANCZOS)
            tile.paste(th, (crop.size[0] + 12 + i * 110, 24))
            d.text((crop.size[0] + 12 + i * 110, 128), name, font=font(14),
                   fill=(0, 255, 0) if name == order[0][0] else (180, 180, 180))
        tiles.append(tile)

    if tiles:
        per = 2
        rows = (len(tiles) + per - 1) // per
        TW = max(t.size[0] for t in tiles)
        TH = max(t.size[1] for t in tiles)
        sheet = Image.new("RGB", (per * TW + (per + 1) * 8, rows * TH + (rows + 1) * 8 + 26), (16, 16, 16))
        for i, tl in enumerate(tiles):
            r, c = divmod(i, per)
            sheet.paste(tl, (8 + c * (TW + 8), 8 + r * (TH + 8)))
        d = ImageDraw.Draw(sheet)
        d.text((8, sheet.size[1] - 20),
               "左=行动轴顶端卡  右=4 个模板(绿字=最佳匹配)  请确认对应是否正确",
               font=font(16), fill=(255, 255, 255))
        if sheet.size[0] > 1600:
            k = 1600 / sheet.size[0]
            sheet = sheet.resize((1600, int(sheet.size[1] * k)), Image.LANCZOS)
        sheet.save("samples/M_行动轴vs队伍模板.png")
        print("\n已写出 samples/M_行动轴vs队伍模板.png %s" % (sheet.size,))


if __name__ == "__main__":
    main()
