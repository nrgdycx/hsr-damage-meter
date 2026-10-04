# -*- coding: utf-8 -*-
"""【线2】录屏2 的**归属可行性**体检：HUD 数值变动 ↔ 行动轴顶端卡。

回答"附伤多的时候归属还做得下去吗"这个问题，先把**能挂上人的比例**量出来：
  * 对每个读出数值的时刻，用因果窗口（[-1.5s,+0.5s]，优先取时刻之前的已确认帧，
    与 C 线 `axis_event_E.py` 同口径）找最近的**已识别我方行动者**；
  * 找不到人的，按顶端卡类型分类（阿哈面具框 / 敌人 / 空槽 / 过渡）；
  * 再统计"数值变动"（相邻读数不同）里有多少能挂上人。

用法：
  python -u analyze_L2_attrib.py            # 控制台报告 + out/L2_attrib.txt
"""
# [P3 整理] 原路径：analyze_L2_attrib.py
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import csv
import os
import sys

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
sys.path.insert(0, HERE)

HUD = "out/frames_L2.csv"
ACT = "out/axis_actors_L2.csv"
WIN_BEFORE, WIN_AFTER = 1.5, 0.5


def load():
    hud = []
    for r in csv.DictReader(open(HUD, encoding="utf-8-sig")):
        hud.append({"t": float(r["t"]), "text": r["text"], "verdict": r["verdict"],
                    "font": r["font"], "how": r["how"]})
    act = {}
    for r in csv.DictReader(open(ACT, encoding="utf-8-sig")):
        act[float(r["t"])] = r
    return hud, act


def nearest_actor(act, t):
    """因果窗口里最近的我方行动者：先看 [t-1.5, t]，再看 (t, t+0.5]。"""
    cands = [(abs(t2 - t), t2, act[t2]) for t2 in act
             if -WIN_BEFORE <= t2 - t <= 0 and act[t2]["unit"]]
    if cands:
        return min(cands, key=lambda x: x[0])
    cands = [(abs(t2 - t), t2, act[t2]) for t2 in act
             if 0 < t2 - t <= WIN_AFTER and act[t2]["unit"]]
    if cands:
        return min(cands, key=lambda x: x[0])
    return None


def topcard_type(act, t):
    """窗口里最近的顶端卡类型（用于解释"为什么挂不上人"）。"""
    cands = [(abs(t2 - t), act[t2]["card_type"]) for t2 in act if abs(t2 - t) <= WIN_BEFORE]
    if not cands:
        return "无帧"
    return min(cands, key=lambda x: x[0])[1]


def main():
    hud, act = load()
    ok = [r for r in hud if r["verdict"] == "ok"]
    lines = ["录屏2 归属可行性体检（HUD 读数 %d 帧，其中 ok %d 帧）" % (len(hud), len(ok)), ""]
    lines.append("== 1. 读出数值的时刻能不能挂到人（因果窗口 -1.5s/+0.5s）==")
    got, miss = [], []
    for r in ok:
        n = nearest_actor(act, r["t"])
        (got if n else miss).append((r, n))
    lines.append("  挂上行动者：%d/%d = %.1f%%" % (len(got), len(ok), 100.0 * len(got) / max(1, len(ok))))
    from collections import Counter
    c = Counter(n[2]["unit"] for _, n in got)
    lines.append("  分布：%s" % dict(c))
    lines.append("  挂不上的 %d 帧，顶端卡类型分布：%s"
                 % (len(miss), dict(Counter(topcard_type(act, r["t"]) for r, _ in miss))))
    lines.append("  （阿哈面具框 = 欢愉技结算，归属要看框里头像 → 线3；敌人/空槽 = 我方没人行动）")
    lines.append("")

    lines.append("== 2. 数值变动（相邻 ok 读数不同）==")
    chg, same = [], 0
    prev = None
    for r in ok:
        if prev is not None:
            if r["text"] != prev["text"]:
                chg.append((prev, r))
            else:
                same += 1
        prev = r
    lines.append("  相邻读数**不同**：%d 对；**相同**：%d 对" % (len(chg), same))
    inc = [(a, b) for a, b in chg if b["text"].isdigit() and a["text"].isdigit()
           and int(b["text"]) > int(a["text"])]
    lines.append("  其中数值**上涨**：%d 对（下降 %d 对 —— 下降=新一次攻击把累计清零重算）"
                 % (len(inc), len(chg) - len(inc)))
    cov = 0
    for a, b in inc:
        if nearest_actor(act, b["t"]) or nearest_actor(act, a["t"]):
            cov += 1
    lines.append("  上涨的对里，至少一端能挂上行动者：%d/%d = %.1f%%"
                 % (cov, len(inc), 100.0 * cov / max(1, len(inc))))
    lines.append("")

    lines.append("== 3. 结论（给归属口径用）==")
    lines.append("  · HUD 每个数值都是一次攻击的**累计值**，一次攻击只对应 1~2 个可读帧（1fps），")
    lines.append("    所以归属靠「顶端卡」而不是靠数值差；**附伤无法从 HUD 里看出来**。")
    lines.append("  · 已知会产生「非本人回合伤害」的机制（技能文本，见 out/L2_skills.txt）：")
    lines.append("      银狼LV.999 终结技结界：我方**每消耗 1 个战技点**有概率触发【头号补给盲盒】")
    lines.append("      银狼LV.999 秘技/【怪怪怪味豆】：每波次开始触发 1 次盲盒")
    lines.append("      爻光 天赋【屏开千光，遍观自在】：**我方目标施放攻击后**对受击目标额外造成")
    lines.append("      　　1 次欢愉伤害（本次攻击若消耗战技点再触发 1 次）→ 别人的回合里出爻光的伤害")
    lines.append("  · 因此「整段数值算给当前行动者」会**高估行动者**；真珠（id 1503）技能文本资料库里没有，")
    lines.append("    她的附伤连来源都无从判断 → 只能标待复核，或由用户提供技能文本。")
    txt = "\n".join(lines)
    print(txt)
    open("out/L2_attrib.txt", "w", encoding="utf-8").write(txt + "\n")
    print("\n已写出 out/L2_attrib.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
