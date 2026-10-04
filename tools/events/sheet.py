# -*- coding: utf-8 -*-
"""
[C 线] 出验收证据图 `samples/C_accept.png`：把"读数缺陷"这条结论做成一张可核对的图。

三块内容（都用文字标签，不用颜色编码传递信息）：
  1. 真值锚点对账表（引擎输出 vs C线交接 §4 的真值）
  2. 前导位静默丢失的证据：屏幕实际值 vs 引擎/A 线读出的值（并排裁图，人眼可核）
  3. ⛔ **反面证据（已被推翻）**：密集抽帧下曾出现 `8324751` 这类"多一位前缀"读数 ——
     那是**修扫描器之前**的 `out/frames_dense_C.csv` 的产物，当前口径下同一批帧带 `?`
     （见 `docs/归属与事件切分.md` §1）。这块保留为历史证据，不要再当当前行为引用。

用法：python sheet_C.py
"""
# [P3 整理] 原路径：sheet_C.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import events as E  # noqa: E402

FRAME = "frames/glyphcache/f%08.2f.png"
OUT = "samples/C_accept.png"


def font(sz):
    for f in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(f, sz)
        except Exception:
            continue
    return ImageFont.load_default()


def hud_crop(t, box=(2380, 262, 2876, 348), scale=1.0):
    """HUD 数字区裁剪（紧凑框：数字实际落在 x≈2400~2860 / y≈270~340）。"""
    im = Image.open(FRAME % t).convert("RGB").crop(box)
    if scale != 1.0:
        im = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
    return im


def main():
    readings, events = E.build()
    F = font(20)
    F2 = font(17)
    lines = []
    lines.append("C 线验收 —— 事件切分 + 归属（录屏1，249 帧 / t=100~340）")
    lines.append("")
    lines.append("① 真值锚点对账（docs/归属与事件切分.md §4）：")
    okn = badn = abn = 0
    by_t = {round(r["t"], 2): r for r in readings}
    for t, eu, eo, est in E.ANCHORS:
        # 锚点**那一帧自己**有没有可用读数、有没有已确认行动者 —— 没有就应当弃权
        # （C线交接 §4 那 6 条"待复核"锚点正好就是这种帧；引擎给不出归属是正确行为）
        row = by_t.get(round(float(t), 2))
        own, _ = E.find_actor(readings, float(t))
        if not (row and row["hud_text"]) or own is None:
            abn += 1
            lines.append("   t=%-5s 期望 %-12s → 该帧%s，引擎弃权（不算错）"
                         % (t, eu or "待复核",
                            "无可用读数" if not (row and row["hud_text"]) else "顶端不可判"))
            continue
        hit = None
        for e in events:
            if e["t_first"] - 0.01 <= t <= e["t_last"] + 0.01 or abs(e["t_peak"] - t) <= 0.51:
                hit = e
                break
        gu = (hit["unit"] if hit else "-") or "-"
        go = (hit["owner"] if hit else "-") or "-"
        good = (hit is not None) and (hit["unit"] == eu) and (hit["owner"] == eo)
        okn += good
        badn += (not good)
        lines.append("   t=%-5s 期望 顶端%-7s 归属%-6s → 实得 顶端%-7s 归属%-6s  %s"
                     % (t, eu, eo, gu, go, "一致" if good else "不一致"))
    lines.append("   小计：一致 %d，不一致 %d，正确弃权 %d" % (okn, badn, abn))
    lines.append("")
    lines.append("② 前导位静默丢失（屏幕实际值 vs A 线读出值；都不带 '?'，属于「自信的错」）：")
    drops = [(102, "304505", "4505"), (135.6, "191176", "76"), (142, "108018", "8"),
             (303, "120754", "20754"), (158, "210408", "0408"), (312, "379852", "7985")]
    for t, real, got in drops:
        lines.append("   t=%-7s 屏幕 %-8s → 读出 %-8s（少 %d 位）"
                     % (("%.2f" % t).rstrip("0").rstrip("."), real, got, len(real) - len(got)))
    lines.append("")
    lines.append("③ ⛔ 反面证据（已被线4 推翻）：下排是「修扫描器之前」的密帧读数，"
                 "屏幕上一直 324751，旧口径读出 8324751")
    lines.append("   —— 当前口径下这些帧带 '?'，会被整条丢掉；密帧真正的危险是"
                 "「丢前导位」（见上面 ② 与 docs/归属与事件切分.md）")

    # ── 画图 ──
    pad, lh = 16, 26
    W = 1500
    text_h = pad * 2 + lh * len(lines)
    crops = [102, 135.6, 142, 303, 158, 312]
    cw, ch = hud_crop(102).size
    cols = 2
    grid_h = ((len(crops) + cols - 1) // cols) * (ch + 34)
    sweep = [150.4 + i * 0.2 for i in range(14)]
    sw = hud_crop(sweep[0], scale=0.55)
    rows_sw = (len(sweep) + 6) // 7
    sheet = Image.new("RGB", (W, text_h + grid_h + rows_sw * (sw.height + 28) + 60),
                      (22, 22, 22))
    d = ImageDraw.Draw(sheet)
    y = pad
    for ln in lines:
        d.text((pad, y), ln, font=F if not ln.startswith("  ") else F2, fill=(235, 235, 235))
        y += lh

    y = text_h
    d.text((pad, y), "证据图 A：六帧原始裁剪（人眼可核对屏幕上的真实数字）", font=F, fill=(255, 255, 255))
    y += 30
    for i, t in enumerate(crops):
        im = hud_crop(t)
        cx = pad + (i % cols) * (cw + 20)
        cy = y + (i // cols) * (ch + 34)
        sheet.paste(im, (cx, cy))
        d.text((cx + 2, cy + ch + 2),
               "t=%s（屏幕实际值）" % (("%.2f" % t).rstrip("0").rstrip(".")),
               font=F2, fill=(230, 230, 180))
    y += grid_h + 10
    d.text((pad, y), "证据图 B：t=150.4~153.0 连续 0.2s 抽帧（HUD 数字在这段时间一直在涨/停住）",
           font=F, fill=(255, 255, 255))
    y += 30
    for i, t in enumerate(sweep):
        im = hud_crop(t, scale=0.55)
        cx = pad + (i % 7) * (im.width + 4)
        cy = y + (i // 7) * (im.height + 28)
        sheet.paste(im, (cx, cy))
        d.text((cx + 2, cy + im.height + 2), "%.1f" % t, font=F2, fill=(230, 230, 180))
    sheet.save(OUT)
    print("已写出 %s %s" % (OUT, sheet.size))
    for ln in lines:
        print(ln)


if __name__ == "__main__":
    main()
