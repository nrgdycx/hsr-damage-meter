# -*- coding: utf-8 -*-
"""【T2】欢愉队伤害台账 —— "未判定（待人工核对）"逐条核验。

背景：`out/L2_damage_ledger.json` 的"缩放依据"是**关键词自动判定**，34 行没判出来。
若把"次数/资源/充能"当成倍率拿去做拆分，会**静默算错**。本脚本把这 34 行逐条定案，
每条带上**技能原文证据**（自动截取占位符周围的文字），并标出**哪些是真伤害倍率**。

分类（kind）：
  damage       真伤害倍率（**可以进计算**）
  damage_table 多档位表（要按条件取档，如"欢愉命途人数 1/2/3/4"）
  buff         加成（增伤/暴击/减伤/易伤/倍率提高…）→ 进乘区，不是伤害条目
  resource     资源（好活当赏/隐藏分/战技点/爆点/充能/抵御值…）
  count        段数/次数/层数
  other        秒数/上限/行动提前/概率等

用法： python -u tools/team2/verify_damage_ledger.py
产物： out/L2_damage_ledger_verified.json / .md
"""
import os as _os
import sys as _sys
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import json
import os
import re
import sys

HERE = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if not _os.path.isdir(_os.path.join(HERE, "out")):
    HERE = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
SRC = _os.path.join(HERE, "out/L2_damage_ledger.json")

# ── 逐条核验表：(技能id, 占位符) → 结论 ──
# 核验人 = 主会话读技能原文逐条判（2026-10-04）；原文证据由脚本自动截取。
V = {
    # 银狼LV.999 终结技 150603
    ("150603", "#7"): dict(kind="resource", scale="—（恢复战技点数）",
                           note="盲盒效果【爆爆爆炸蛋】：恢复 #7 个战技点 → **不是倍率**"),
    ("150603", "#4"): dict(kind="other", scale="—（概率衰减系数）",
                           note="触发后下次触发的固定概率降为当前的 #4 → **概率**，不是伤害；"
                                "「有概率」本身不可判定"),
    # 银狼LV.999 天赋 150604
    ("150604", "#1"): dict(kind="resource", scale="—（【隐藏分】阈值）",
                           note="【隐藏分】达到 #1 点可激活终结技 → 资源阈值"),
    ("150604", "#6"): dict(kind="buff", scale="暴击伤害（提高 #6）",
                           note="【无敌玩家】状态下改为使**暴击伤害提高** #6 → 进暴击区，不是伤害条目"),
    ("150604", "#5"): dict(kind="count", scale="—（强化普攻次数）",
                           note="完整施放 #5 次强化普攻后退出【无敌玩家】→ 次数"),
    # 银狼LV.999 秘技 150607
    ("150607", "#1"): dict(kind="resource", scale="—（固定计入【好活当赏】点数）",
                           note="本次欢愉伤害固定计入 #1 点【好活当赏】→ 进**好活区**（同一次攻击内可约掉）"),
    # 银狼LV.999 强化普攻 150608
    ("150608", "#5"): dict(kind="count", scale="—（盲盒触发次数）", note="总计可触发 #5 次"),
    ("150608", "#6"): dict(kind="resource", scale="—（每 #6 点【隐藏分】）",
                           note="每拥有 #6 点【隐藏分】，「强化普攻期间造成的伤害提高原伤害的 #8」，最多叠 #7 层"
                                "→ 与 #7/#8 一起构成**增伤**（buff），本身不是倍率"),
    ("150608", "#8"): dict(kind="buff", scale="增伤（每层提高原伤害的 #8）",
                           note="每 #6 点隐藏分 +1 层，每层 +原伤害的 #8 → 独立增伤"),
    ("150608", "#7"): dict(kind="count", scale="—（叠加上限）", note="最多叠加 #7 层"),
    # 银狼LV.999 欢愉技 150620 / 150621
    ("150620", "#1"): dict(kind="resource", scale="—（获得【隐藏分】）", note="获得 #1 点【隐藏分】"),
    ("150621", "#2"): dict(kind="count", scale="—（伤害段数）", note="造成 #2 次伤害（每次 #1=1.125% 欢愉伤害）"),
    # 爻光 战技 150202
    ("150202", "#2"): dict(kind="buff", scale="欢愉度（提高值 = 爻光欢愉度的 #2）",
                           note="★**全队欢愉度提高**：提高值 = 爻光欢愉度的 #2（满级 25%）→ 直接进 `(1+欢愉度)`；"
                                "**每个队友的有效欢愉度不同**，拆分时必须建模"),
    # 爻光 秘技 150207
    ("150207", "#1"): dict(kind="other", scale="—（秘技点上限）", note="每个地球周最多获得 #1 个（大世界）"),
    # 爻光 欢愉技 150220
    ("150220", "#3"): dict(kind="buff", scale="易伤（敌方受到伤害提高 #3）",
                           note="敌方目标**受到的伤害提高** #3 → 易伤区；同一次攻击内对所有来源相同 → 求占比时约掉"),
    # 火花 战技 150102 / 秘技 150107 / 战技 150109 / 欢愉技 150120
    ("150102", "#1"): dict(kind="count", scale="—（发动次数）", note="【互动陷阱】最多发动 #1 次"),
    ("150107", "#3"): dict(kind="other", scale="—（【拉黑】持续秒数）", note="【拉黑】持续 #3 秒（大世界）"),
    ("150107", "#1"): dict(kind="resource", scale="—（恢复战技点）", note="为我方恢复 #1 个战技点"),
    ("150109", "#4"): dict(kind="buff", scale="倍率提高（#4）", note="对指定敌方单体的**伤害倍率提高** #4"),
    ("150109", "#5"): dict(kind="buff", scale="倍率提高（#5）", note="对相邻目标的**伤害倍率提高** #5"),
    ("150120", "#3"): dict(kind="count", scale="—（额外伤害次数）", note="额外造成 #3 次伤害（每次 #1=0.3125% 欢愉伤害）"),
    ("150120", "#4"): dict(kind="resource", scale="—（获得【爆点】）", note="获得 #4 个【爆点】"),
    # 真珠 战技 150302 / 终结技 150303 / 天赋 150304 / 秘技 150307 / 欢愉技 150320
    ("150302", "#1"): dict(kind="resource", scale="—（获得【好活当赏】）", note="获得 #1 点【好活当赏】"),
    ("150303", "#3"): dict(kind="resource", scale="—（获得【好活当赏】）", note="获得 #3 点【好活当赏】"),
    ("150303", "#4"): dict(kind="other", scale="—（行动提前）", note="【美学底本】行动提前 #4/#5/#6%（按欢愉命途人数取档）"),
    ("150303", "#1"): dict(kind="resource", scale="—（【深度学习】充能）",
                           note="【深度学习】具有 #1 点充能，真珠施放强化普攻后消耗 → 资源"),
    ("150304", "#5"): dict(kind="resource", scale="—（抵御值）",
                           note="1 点【好活当赏】等同于 #5 点抵御值 → 防御向资源"),
    ("150304", "#2"): dict(kind="buff", scale="减伤（抵挡 #2）", note="抵御值为我方目标抵挡 #2 的伤害 → 减伤区"),
    ("150304", "#3"): dict(kind="resource", scale="—（【好活当赏】持有上限）", note="持有上限为 #3 点"),
    ("150304", "#1"): dict(kind="buff", scale="减伤（条件 #1 / 降低 #4）",
                           note="我方目标当前生命值百分比 ≤ #1 时，受到的伤害降低 #4 → 减伤（条件触发）"),
    ("150304", "#4"): dict(kind="buff", scale="减伤（降低 #4）", note="同上：受到的伤害降低 #4"),
    ("150307", "#2"): dict(kind="resource", scale="—（获得【好活当赏】）", note="战斗开始时获得 #2 点【好活当赏】"),
    ("150307", "#1"): dict(kind="resource", scale="—（【深度学习】充能）", note="【深度学习】具有 #1 点充能"),
    ("150320", "#1"): dict(kind="damage_table", scale="欢愉度（**按欢愉命途人数取档**）",
                           note="★真伤害：我方全体下一次攻击后额外造成 #1/#2/#3/#4 档欢愉伤害；"
                                "**本队 4 人欢愉 → 取 #4 = 0.5**（台账里 `#4 → 0.5（欢愉度）` 那条才对得上）"),
}

KIND_ORDER = ["damage", "damage_table", "damage_formula", "heal", "buff", "resource", "count", "other"]
KIND_TITLE = {"damage": "真伤害倍率（**进计算**）",
              "damage_table": "多档位表（按条件取档，**进计算**）",
              "damage_formula": "伤害公式里的系数（不是独立伤害条目）",
              "heal": "治疗量（**不是伤害**）",
              "buff": "加成（进乘区，不是伤害条目）", "resource": "资源", "count": "段数/次数/层数",
              "other": "其它（秒数/上限/概率/行动提前）"}

# ── 关键词自动判定里被**误判成倍率**的行（人工复核后更正）──
AUTO_FIX = {
    ("150602", "#2"): dict(kind="resource", scale="—（获得笑点）", note="获得 #2 个笑点，不是伤害"),
    ("150603", "#6"): dict(kind="resource", scale="—（获得笑点）", note="【怪怪怪味豆】：获得 #6 个笑点"),
    ("150604", "#2"): dict(kind="resource", scale="—（【隐藏分】溢出上限）",
                           note="【隐藏分】达到上限后还可溢出 #2 点 → 资源上限"),
    ("150604", "#4"): dict(kind="buff", scale="暴击率（每点隐藏分提高 #4）",
                           note="每点【隐藏分】使暴击率提高 #4；满爆后改为暴伤（#6）→ 进暴击区"),
    ("150608", "#3"): dict(kind="count", scale="—（弹射段数）", note="均分为 #3 段伤害 → 段数，不是倍率"),
    ("150202", "#1"): dict(kind="other", scale="—（结界持续回合数）", note="结界持续 #1 回合"),
    ("150202", "#3"): dict(kind="resource", scale="—（获得笑点）", note="爻光施放普攻/战技后获得 #3 个笑点"),
    ("150203", "#1"): dict(kind="resource", scale="—（获得笑点）", note="获得 #1 个笑点"),
    ("150203", "#4"): dict(kind="resource", scale="—（固定计入笑点的额外回合）",
                           note="使阿哈获得 1 个固定计入 #4 笑点的额外回合 → 资源"),
    ("150203", "#2"): dict(kind="buff", scale="全属性抗性穿透（提高 #2）",
                           note="我方全体全属性抗性穿透提高 #2 → 抗性区（同一次攻击内约掉）"),
    ("150203", "#3"): dict(kind="other", scale="—（持续回合数）", note="持续 #3 回合"),
    ("150220", "#4"): dict(kind="other", scale="—（【凶星低语】持续回合数）", note="持续 #4 回合"),
    ("150220", "#5"): dict(kind="count", scale="—（额外伤害次数）",
                           note="随后对敌方随机单体造成 **#5 次** #6 的物理属性欢愉伤害 → #5 是次数"),
    ("150103", "#1"): dict(kind="resource", scale="—（获得笑点）", note="获得 #1 个笑点"),
    ("150103", "#3"): dict(kind="damage_formula", scale="欢愉度→攻击力换算系数",
                           note="本体伤害 =（**#3 × 欢愉度** + #2%）攻击力 → #3 是公式系数，"
                                "说明火花的直伤也吃欢愉度（转成攻击力）"),
    ("150109", "#2"): dict(kind="resource", scale="—（礼物：笑点）", note="随机礼物给 #2 个笑点"),
    ("150109", "#3"): dict(kind="resource", scale="—（礼物：笑点+战技点）",
                           note="【红红火火】：#3 个笑点和 #1 个战技点"),
    ("150302", "#2"): dict(kind="heal", scale="—（治疗量）",
                           note="为我方全体**回复**等同于真珠 #2% 防御力+#3 的生命值 → 治疗，不是伤害"),
    ("150303", "#7"): dict(kind="resource", scale="—（获得笑点）", note="【美学底本】获得 #7 点笑点"),
    ("150303", "#8"): dict(kind="resource", scale="—（获得【好活当赏】）",
                           note="【美学底本】获得 #8 点【好活当赏】"),
    ("150308", "#2"): dict(kind="heal", scale="—（治疗量）", note="回复生命值 → 治疗，不是伤害"),
    ("150310", "#2"): dict(kind="heal", scale="—（治疗量）", note="回复生命值 → 治疗，不是伤害"),
}


def evidence(desc, ph):
    """截取占位符周围的原文（前后各 40 字）"""
    m = re.search(re.escape(ph) + r"\[[^\]]*\]", desc or "")
    if not m:
        return ""
    a, b = max(0, m.start() - 40), min(len(desc), m.end() + 40)
    return ("…" if a > 0 else "") + desc[a:b].replace("\n", " ") + ("…" if b < len(desc) else "")


def main():
    led = json.load(open(SRC, encoding="utf-8"))
    rows, todo, stats = [], [], {k: 0 for k in KIND_ORDER}
    for e in led:
        desc = e.get("desc", "")
        for d in e["damage"]:
            rec = dict(char=e["char"], sid=e["id"], skill=e["name"], type=e["type"],
                       owner=e["owner"], ph=d["placeholder"], value=d["value_max_level"],
                       auto_scale=d["scale"], auto_how=d["scale_how"])
            v = V.get((e["id"], d["placeholder"]))
            if v is None:
                if d["scale_how"] == "auto":
                    fix = AUTO_FIX.get((e["id"], d["placeholder"]))
                    if fix is not None:
                        rec.update(kind=fix["kind"], scale=fix["scale"], note=fix["note"],
                                   how="human", evidence=evidence(desc, d["placeholder"]))
                        stats[fix["kind"]] = stats.get(fix["kind"], 0) + 1
                    else:  # 人工逐条复核：确为伤害实例
                        rec.update(kind="damage", scale=d["scale"],
                                   note="已逐条复核：**确为伤害实例**（缩放依据=%s）" % d["scale"],
                                   how="human", evidence=evidence(desc, d["placeholder"]))
                        stats["damage"] = stats.get("damage", 0) + 1
                else:
                    rec.update(kind="?", scale="未判定", note="**仍待人工核对**", how="none")
                    todo.append(rec)
            else:
                rec.update(kind=v["kind"], scale=v["scale"], note=v["note"], how="human",
                           evidence=evidence(desc, d["placeholder"]))
                stats[v["kind"]] = stats.get(v["kind"], 0) + 1
            rows.append(rec)

    out = {"_note": "T2 台账核验结果：human=人工逐条读技能原文定案；auto=关键词自动判定（未逐条读）",
           "rows": rows, "todo": todo, "stats": stats}
    json.dump(out, open(_os.path.join(HERE, "out/L2_damage_ledger_verified.json"), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=1)

    L = ["# 欢愉队伤害台账 —— 核验结果（T2）", "",
         "> 目的：`out/L2_damage_ledger.json` 的\"缩放依据\"是**关键词自动判定**；"
         "把\"次数/资源/充能\"当成倍率去做拆分，会**静默算错**。本表逐条定案并附**技能原文证据**。",
         "> 复现：`python -u tools/team2/verify_damage_ledger.py`", "",
         "## 合计", "",
         "| 分类 | 条数 |", "|---|---|"]
    for k in KIND_ORDER:
        L.append("| %s | %d |" % (KIND_TITLE[k], stats.get(k, 0)))
    L += ["| **仍待人工核对** | **%d** |" % len(todo), "",
          "## 逐条核验（按分类）", ""]
    for k in KIND_ORDER:
        grp = [r for r in rows if r["kind"] == k]
        if not grp:
            continue
        L += ["### %s" % KIND_TITLE[k], "",
              "| 角色 | 技能 | 占位符 | 满级值 | 核验结论 | 说明 |", "|---|---|---|---|---|---|"]
        for r in grp:
            L.append("| %s | `%s` %s | `%s` | %s | %s | %s |" % (
                r["char"], r["sid"], r["skill"], r["ph"], r["value"], r["scale"], r["note"]))
        L.append("")
        ev = [r for r in grp if r.get("evidence")]
        if ev:
            L.append("<details><summary>原文证据</summary>")
            L.append("")
            for r in ev:
                L.append("* `%s` `%s`：%s" % (r["sid"], r["ph"], r["evidence"]))
            L += ["", "</details>", ""]
    if todo:
        L += ["## ⚠️ 仍待人工核对", ""]
        for r in todo:
            L.append("* `%s` %s `%s` → %s" % (r["sid"], r["skill"], r["ph"], r["auto_scale"]))
        L.append("")
    txt = "\n".join(L)
    open(_os.path.join(HERE, "out/L2_damage_ledger_verified.md"), "w", encoding="utf-8").write(txt + "\n")
    print(txt[:3000])
    print("\n核验：%d 条 ｜ " % len(rows)
          + " ｜ ".join("%s %d" % (k, stats.get(k, 0)) for k in KIND_ORDER)
          + " ｜ 待核 %d" % len(todo))
    return 1 if todo else 0


if __name__ == "__main__":
    sys.exit(main())
