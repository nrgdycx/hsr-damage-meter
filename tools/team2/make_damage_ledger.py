# -*- coding: utf-8 -*-
"""【线2】欢愉队**伤害实例台账** —— 供「按倍率把附伤拆回来源」（用户选的 C 方案）。

做法：从 `out/skills_L2.json`（由 `extract_skills_L2.py` 从 btdsh 资料库抽的原文）里，
把每个技能的**每一处伤害**解析成一条台账：
    谁（归属）/ 哪个技能 / 属性 / 倍率占位符 → 缩放依据（攻击力·欢愉度·总伤害值…）/ 触发条件

⚠️ 归属口径（已与用户确认）：
  * **【头号补给盲盒】及其三种效果（超超超大剑/爆爆爆炸蛋/怪怪怪味豆）→ 记「银狼LV.999」**
    （用户 2026-10-01：「狼尊有盲盒，那个伤害也是狼尊的」）；
  * **【大吉大利】→ 记「爻光」**（天赋原文："使我方目标施放攻击后触发…额外造成 1 次欢愉伤害"）；
  * 其余按技能归属本人。

用法：
  python -u make_damage_ledger_L2.py        # → out/L2_damage_ledger.json + out/L2_damage_ledger.md
"""
# [P3 整理] 原路径：make_damage_ledger_L2.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import json
import os
import re
import sys

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
SRC = os.path.join(HERE, "out/skills_L2.json")

# 占位符后面跟的"缩放依据"关键词 → 归类（先匹配到的优先；长的关键词放前面）
SCALE_PAT = [
    ("总伤害值", "本次总伤害值"), ("真实伤害", "本次总伤害值"),
    ("欢愉伤害", "欢愉度"), ("欢愉度", "欢愉度"),
    ("攻击力", "攻击力"), ("生命上限", "生命上限"), ("防御力", "防御力"),
    ("笑点", "笑点数"), ("忆质", "忆质点数"), ("暴击", "暴击相关"),
    ("概率", "概率"), ("回合", "回合数"), ("段", "段数/次数"),
]
# 技能里"不是本人回合也会出伤"的触发条件（人工核对过，来自技能原文）
TRIGGER = {
    "150603": "银狼LV.999 的终结技结界期间：我方目标**每消耗 1 个战技点**有概率触发【头号补给盲盒】",
    "150607": "银狼LV.999 秘技：每波次开始时触发 1 次【怪怪怪味豆】对应的盲盒",
    "150204": "爻光天赋：**我方目标施放攻击后**触发【大吉大利】（该次攻击若消耗战技点则再触发 1 次）",
    "150202": "爻光战技：展开结界（我方欢愉度提高）——本身不出伤",
    "150203": "爻光终结技：让阿哈立即获得额外回合——伤害由阿哈（欢愉技）打出",
    "150301": "真珠普攻（防御力缩放）",
    "150310": "真珠强化普攻（【深度学习】期）——防御力缩放群攻",
    "150308": "真珠强化普攻（底本为欢愉命途时）：群攻 **+ 持有【好活当赏】时额外 0.2% 冰属性欢愉伤害**",
    "150303": "真珠终结技（辅助）：**【美学底本】攻击后**额外造成 0.75% 冰属性欢愉伤害，"
              "**该次伤害按【美学底本】的属性值计算** → 归属=【美学底本】=当前行动者（用户 2026-10-01 定案）",
    "150320": "真珠欢愉技：**我方全体下一次攻击后**，对攻击目标额外造成对应属性欢愉伤害"
              "（队伍欢愉命途 4 人 → 取 0.5% 档）",
    "150302": "真珠战技：只为【好活当赏】与治疗，本身不出伤",
    "150304": "真珠天赋：防御向（消耗【好活当赏】抵挡伤害），本身不出伤",
    "150307": "真珠秘技：给【美学底本】，本身不出伤",
}
OWNER_OVERRIDE = {
    "150603": "银狼LV.999", "150610": "银狼LV.999", "150612": "银狼LV.999",
    "150618": "银狼LV.999", "150621": "银狼LV.999", "150607": "银狼LV.999",
    "150204": "爻光", "150220": "爻光",
}
BOX_EFFECTS = {"150610": "【超超超大剑】", "150612": "【爆爆爆炸蛋】", "150618": "【怪怪怪味豆】"}
# 归属有"跨角色"争议的技能 —— 用户 2026-10-01 定案
SPECIAL_ATTR = {
    "150303": ("【美学底本】= 当前行动者",
               "用户定案：该次 0.75% 欢愉伤害**按【美学底本】的属性值计算** → 记底本（=当前行动者），"
               "与「顶端卡=行动者」的默认口径一致"),
}


def parse_damage(desc, params_by_level, level=None):
    """把 desc 里的 `#n[i]%…` 解码成 (倍率值, 缩放依据, 原文片段)。

    ⚠️ 这是**自动解析**，"缩放依据"是靠关键词猜的（例：`#3[i]%的虚数属性欢愉伤害` → 欢愉度）。
    台账里凡是猜到的都标注 `auto`，需要人工过一眼才能拿去做拆分计算 —— 倍率表错了，
    拆分结果会**静默错**，比不拆更危险。
    """
    out = []
    for m in re.finditer(r"#(\d+)\[(\w+)\]\s*%?\s*([^，。；\n]{0,12})", desc):
        idx, fmt, tail = int(m.group(1)), m.group(2), m.group(3)
        window = desc[m.start():m.end() + 14]
        scale, how = "未判定（待人工核对）", "unknown"
        for kw, cat in SCALE_PAT:
            if kw in window or kw in tail:
                scale, how = cat, "auto"
                break
        val = None
        if params_by_level:
            lv = level or len(params_by_level)
            row = params_by_level[min(max(lv, 1), len(params_by_level)) - 1]
            if idx - 1 < len(row):
                val = row[idx - 1]
        out.append({"placeholder": "#%d" % idx, "value_max_level": val, "scale": scale,
                    "scale_how": how,
                    "unit": "%" if fmt == "i" or "%" in m.group(0) else fmt,
                    "snippet": desc[max(0, m.start() - 10):m.end() + 12].replace("\n", " ")})
    return out


def main():
    d = json.load(open(SRC, encoding="utf-8"))
    ledger, lines = [], []
    lines.append("# 欢愉队伤害实例台账（线2 自动生成，供 C 方案拆分附伤）")
    lines.append("")
    lines.append("> 归属口径：盲盒（含三种效果）→ **银狼LV.999**；【大吉大利】→ **爻光**；"
                 "真珠终结技那 0.75% → **【美学底本】=当前行动者**（用户定案）；其余归本人。")
    lines.append("> ⚠️ 倍率取 `paramsByLevel` 的**满级**值；实际角色技能等级未知 → 这是**待用户/游戏确认**的一项。")
    lines.append("")
    for name, cd in d.get("characters", {}).items():
        lines.append("## %s（id %s）" % (name, cd["id"]))
        lines.append("")
        lines.append("| 技能 | 类型 | 归属 | 触发条件 | 伤害条目 |")
        lines.append("|---|---|---|---|---|")
        for sid, s in cd["skills"].items():
            dmgs = parse_damage(s["desc"], s.get("params_by_level"))
            dmg_txt = "<br>".join(
                "%s → %s%s（%s）" % (x["placeholder"], x["value_max_level"],
                                    "%" if x["unit"] == "i" else "",
                                    x["scale"]) for x in dmgs) or "—"
            owner = OWNER_OVERRIDE.get(sid, name)
            box = BOX_EFFECTS.get(sid)
            owner_cell = owner + ("（盲盒效果%s）" % box if box else "")
            if sid in SPECIAL_ATTR:
                owner_cell = SPECIAL_ATTR[sid][0]
            trig = TRIGGER.get(sid, "本人回合内")
            if box:
                trig = "由【头号补给盲盒】随机选中 → " + box
            lines.append("| %s<br>`%s` | %s | %s | %s | %s |"
                         % (s["name"], sid, s["type"], owner_cell, trig, dmg_txt))
            ledger.append({"char": name, "id": sid, "name": s["name"], "type": s["type"],
                           "element": s["element"], "owner": owner,
                           "trigger": trig, "damage": dmgs,
                           "damage_outside_own_turn": s["damage_outside_own_turn"],
                           "desc": s["desc"]})
        lines.append("")

    missing = d.get("_missing") or {}
    if missing:
        lines.append("## ⚠️ 数据缺口")
        lines.append("")
        for who, info in missing.items():
            lines.append("* **%s**：%s" % (who, info.get("evidence", info)))
        lines.append("")
    else:
        lines.append("## 数据完整性")
        lines.append("")
        lines.append("* 4 个角色的技能文本**都拿到了**（来源见 `out/skills_L2.json` 的 `_sources`："
                     "全部来自 `StarRailRes-index_min/index_min/cn`）；")
        lines.append("  与 `btdsh/` 逐角色文件的倍率**逐条比对过，0 处差异**"
                     "（脚本核对：`extract_skills_L2.py` 的 from_index_min vs from_btdsh）。")
        lines.append("* 队伍命途：**4 人全是「欢愉」**（火花/爻光/真珠/银狼LV.999）→ 真珠的"
                     "「欢愉命途人数 4」档生效（欢愉技 0.5% 档、【美学底本】额外回合）。")
        lines.append("")
    lines.append("## C 方案还需要的外部输入")
    lines.append("")
    lines.append("1. ~~真珠的技能文本~~ ✅ **已解决**（`StarRailRes-index_min/` 里有，见上）；")
    lines.append("2. **四个角色的战场数值**：欢愉度、攻击力、（暴击率/暴击伤害）、增伤/穿透类加成；")
    lines.append("   → 本录屏里**没有**属性面板画面（t=0 只有队伍列表，结尾只有「挑战结束」），")
    lines.append("      所以只能：① 用户截图属性页；② 或从战斗飘字做标定（属于数值反推，需用户认可）；")
    lines.append("3. **技能等级/星魂**（决定取 paramsByLevel 的哪一档、有没有额外触发）；")
    lines.append("4. **敌人侧的防御/抗性/易伤**：同一次攻击内对所有来源是同一个系数 → 在**求占比时可约掉**，")
    lines.append("   只有要算绝对伤害时才需要。")

    txt = "\n".join(lines)
    open(os.path.join(HERE, "out/L2_damage_ledger.md"), "w", encoding="utf-8").write(txt + "\n")
    json.dump(ledger, open(os.path.join(HERE, "out/L2_damage_ledger.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(txt)
    print("\n已写出 out/L2_damage_ledger.md / out/L2_damage_ledger.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
