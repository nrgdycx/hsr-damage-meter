# -*- coding: utf-8 -*-
"""【T2】附伤来源库扫描器 —— 全库找出"伤害归属不一定是行动者"的条目。

判据（用户 2026-10-04 定案，详见 docs/附伤与开大踢轴.md）：
  * **归属 = 倍率所有者**：一次伤害里有 a% 主c + b% 辅助 → a% 算主c、b% 算辅助。
  * 「造成原伤害 / 本次攻击总伤害 X%」= **独立乘区，跟当前行动者**（用户口径），不算附伤。
  * 忆灵/召唤物（顶轴有自己的卡，含**盲盒**）→ 按顶端卡归召唤者。
  * 停云【赐福】这类"等同于**持有者自身**攻击力"→ 归持有者（=行动者），不剥离。

结构：
  1) 关键词抓**候选**（会漏，所以另有 MANUAL 兜底清单）；
  2) 人工定案表 `CURATION`（key = `skill:<id>` / `rank:<id>` / `tree:<id>` / `lc:<id>`）；
  3) 规则自动分类（本体多段等一眼可判的）；
  4) 同文案继承（同一技能的不同变体 id 文案相同 → 继承分类）；
  5) **没归到类的候选会被报出来**（不允许静默漏掉）。

用法：
  python -u tools/team2/scan_add_damage.py            # → out/add_damage_catalog.{json,md}
  python -u tools/team2/scan_add_damage.py --dump      # 只列候选（调试/补分类用）
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
DB = _os.path.join(HERE, "StarRailRes-index_min", "index_min", "cn")

# ── 候选关键词：只抓"制造一次伤害"的写法（"伤害提高"这类 buff 不抓）──
CAND = re.compile(
    r"额外造成[^。；\n]{0,60}?伤害"
    r"|附加伤害"
    r"|(立即产生|相当于原伤害|等同于原伤害)[^。；\n]{0,20}伤害"
    r"|本次攻击总伤害值|本次总伤害值"
    r"|记录治疗量"
    r"|(我方目标|我方队友|我方其他目标|我方角色|我方全体|队友|任意单位)[^。；\n]{0,25}攻击后[^。；\n]{0,35}?(追加攻击|发动|造成|触发)"
    r"|每回合开始时或我方目标单次攻击后")

# ── 关键词抓不到、但确实要收录的条目（兜底，防漏）──
MANUAL = [
    "skill:141003",   # 海瑟音 终结技结界：我方目标单次攻击后触发
]

# ── 人工定案表 ──
# kind: cross       外源附伤（要剥离，归倍率所有者）
#       designated  倍率取自"被指定队友"（剥离，归被指定者）
#       self        归行动者本人（不剥离）
#       follow_up   追击类（跨人，但不是附伤；按顶端卡/规则）
#       pct_actor   原伤害%/总伤害% 型（独立乘区，跟行动者）
#       dot_settle  dot 立即结算（本轮不处理）
#       summon      召唤物/忆灵伤害（按顶端卡归召唤者）
#       modifier    不是伤害，而是改另一条附伤的倍率/次数
#       not_damage  命中关键词但不是伤害
S = "自伤"
CURATION = {
    # ===== 外源附伤（要剥离）=====
    "skill:130903": dict(kind="cross", owner="知更鸟", trigger="我方目标每次施放攻击后",
                         state="处于【协奏】（行动序列上有【协奏】倒计时卡）",
                         note="暴击率/暴击伤害文本写死（#5/#6）→ 不需要面板"),
    "rank:130906": dict(kind="modifier", owner="知更鸟", trigger="处于【协奏】时",
                        state="", note="【月隐的午夜】：附加伤害暴伤+450%，最多8次（改 130903）"),
    "skill:141204": dict(kind="cross", owner="刻律德菈", trigger="持有【军功】的角色施放攻击后",
                         state="有人持【军功】且触发次数未耗尽（#4 次，刻律放终结技重置）",
                         note="倍率=刻律德菈攻击力"),
    "rank:141206": dict(kind="modifier", owner="刻律德菈", trigger="", state="",
                        note="【军功】触发的附加伤害倍率+300%（改 141204）"),
    "skill:150204": dict(kind="cross", owner="爻光", trigger="我方目标施放攻击后触发【大吉大利】",
                         state="爻光持有【好活当赏】",
                         note="倍率=欢愉度；**攻击者欢愉度更高时用攻击者的**（用户 2026-10-04 指出）；"
                              "该次攻击若消耗战技点再触发 1 次"),
    "skill:140303": dict(kind="cross", owner="缇宝", trigger="受到我方目标攻击后",
                         state="结界持续中", note="倍率=缇宝生命上限；无敌人数量上限"),
    "rank:140302": dict(kind="modifier", owner="缇宝", trigger="", state="",
                        note="结界附加伤害→原伤害120%，且额外多 1 次（改 140303）"),
    "rank:140301": dict(kind="pct_actor", owner="当前行动者",
                        trigger="我方目标攻击敌人后（对结界造成附加伤害的目标）",
                        state="结界持续中",
                        note="**本次攻击总伤害值24% 真实伤害** → 按用户口径：%型=独立乘区，跟行动者"),
    "rank:140604": dict(kind="cross", owner="赛飞儿", trigger="【老主顾】受到我方目标攻击后",
                        state="场上有【老主顾】", note="倍率=赛飞儿攻击力50%"),
    "skill:140604": dict(kind="not_damage", owner="赛飞儿", trigger="", state="",
                         note="只是施加【老主顾】状态，本身不出伤（状态来源）"),
    "skill:131402": dict(kind="cross", owner="翡翠", trigger="【收债人】施放攻击后",
                         state="场上有【收债人】", note="倍率=翡翠攻击力"),
    "skill:122304": dict(kind="cross", owner="貊泽", trigger="我方目标攻击【猎物】后",
                         state="场上有【猎物】", note="倍率=貊泽攻击力；追加攻击部分见同条后段"),
    "skill:141003": dict(kind="cross", owner="海瑟音", trigger="每回合开始时 或 我方目标单次攻击后",
                         state="结界持续中", note="倍率=海瑟音攻击力；最多触发 #5 次；该伤害不重复触发"),
    "skill:1141522": dict(kind="modifier", owner="海瑟音", trigger="", state="",
                          note="昔涟忆灵技给海瑟音【暖流】：dot 立即结算（dot 类，本轮不处理）"),
    "skill:1141525": dict(kind="designated", owner="【同袍】", trigger="【龙灵】的下#3次攻击",
                          state="丹恒•腾荒持有【献予「大地」之诗】",
                          note="倍率=**同袍护盾量**% → 归同袍"),
    "rank:141406": dict(kind="designated", owner="【同袍】", trigger="丹恒•腾荒施放终结技时",
                        state="场上有【同袍】", note="倍率=**同袍330%攻击力** → 归同袍"),
    "skill:141403": dict(kind="designated", owner="丹恒•腾荒 + 【同袍】",
                         trigger="【龙灵】行动时（强化期间）",
                         state="龙灵强化次数未耗尽",
                         note="**一次攻击两个归属**：基础伤害=丹恒#2%攻击力→丹恒；"
                              "附加伤害=【同袍】#8%攻击力→同袍。用户 2026-10-04：要分开计"),
    "rank:141402": dict(kind="modifier", owner="丹恒•腾荒/同袍", trigger="", state="",
                        note="强化龙灵时【同袍】附加伤害→原伤害200%（改 141403）"),
    "skill:150303": dict(kind="designated", owner="【美学底本】= 当前行动者",
                         trigger="【美学底本】攻击后", state="【美学底本】已指定",
                         note="用户 2026-10-01 定案：该次伤害按【美学底本】属性计算 → 归底本"),
    "rank:150306": dict(kind="designated", owner="【美学底本】", trigger="真珠强化普攻",
                        state="【深度学习】中", note="真珠强普额外240%欢愉伤害，用【美学底本】属性值"),
    "skill:150320": dict(kind="cross", owner="真珠", trigger="我方全体下一次攻击后",
                         state="4 人欢愉命途档（0.5%）", note="倍率来自真珠 → 归真珠"),
    "skill:150603": dict(kind="summon", owner="银狼LV.999", trigger="结界内我方目标每消耗 1 个战技点（**有概率**）",
                         state="处于【无敌玩家】结界 + 爻光/银狼持【好活当赏】",
                         note="用户 2026-10-01：盲盒算银狼的；2026-10-04：**顶轴出现【?】卡 = 盲盒**，"
                              "按召唤物处理 → 归银狼。⚠️「有概率」→ 概率本身不可判定"),
    "skill:150610": dict(kind="summon", owner="银狼LV.999", trigger="盲盒随机选中", state="",
                         note="盲盒效果【超超超大剑】"),
    "skill:150612": dict(kind="summon", owner="银狼LV.999", trigger="盲盒随机选中", state="",
                         note="盲盒效果【爆爆爆炸蛋】"),
    "skill:150618": dict(kind="summon", owner="银狼LV.999", trigger="盲盒随机选中 / 秘技每波次",
                         state="", note="盲盒效果【怪怪怪味豆】；秘技每波次开始触发 1 次"),
    "skill:150607": dict(kind="summon", owner="银狼LV.999", trigger="每波次开始时触发 1 次盲盒",
                         state="怪怪怪味豆在场", note="本次欢愉伤害固定计入 99 点【好活当赏】"),
    "skill:150621": dict(kind="modifier", owner="银狼LV.999", trigger="", state="",
                         note="欢愉技：6 次 ×1.125% 虚数欢愉伤害；并把盲盒概率重置"),
    # ===== 追击类（跨人，但不是附伤）=====
    "skill:122004": dict(kind="follow_up", owner="飞霄", trigger="我方队友对敌方施放攻击后",
                         state="【飞黄】可触发次数未耗尽", note="每回合最多 1 次"),
    "skill:1100504": dict(kind="follow_up", owner="卡芙卡", trigger="队友对敌方施放攻击后",
                          state="", note="立即发动追加攻击"),
    "skill:101504": dict(kind="follow_up", owner="Archer", trigger="队友对敌方施放攻击后",
                         state="有充能", note="消耗 1 点充能"),
    "skill:100304": dict(kind="follow_up", owner="姬子", trigger="我方目标施放攻击后",
                         state="充能达到上限", note="立即发动追加攻击（敌方全体）"),
    "skill:110703": dict(kind="follow_up", owner="克拉拉", trigger="任意我方目标…（史瓦罗反击强化）",
                         state="终结技后", note="反击强化"),
    "skill:150905": dict(kind="follow_up", owner="吉尔伽美什 + Saber",
                         trigger="任意单位攻击后累计计数达标",
                         state="", note="**一次攻击两个归属**：两人各按自己的倍率"),
    "skill:150403": dict(kind="follow_up", owner="不死途", trigger="终结技后立即发动强化天赋追加攻击",
                         state="", note=""),
    "rank:110706": dict(kind="follow_up", owner="克拉拉（史瓦罗反击）",
                        trigger="我方其他目标遭到攻击后（50% 固定概率）",
                        state="", note="反击 → 归克拉拉；并给攻击者加【反击标记】"),
    "skill:121104": dict(kind="not_damage", owner="白露", trigger="", state="",
                         note="治疗/免死，不出伤"),
    "tree:1304103": dict(kind="not_damage", owner="砂金", trigger="", state="",
                         note="给护盾/攒【盲注】，不出伤"),
    "skill:140204": dict(kind="cross", owner="阿格莱雅", trigger="攻击处于【间隙织线】的敌人后",
                         state="衣匠在场", note="倍率=阿格莱雅攻击力 → 归阿格莱雅"),
    # ===== 指定队友（归被指定者）=====
    "skill:120202": dict(kind="self", owner="被【赐福】者（=行动者）",
                         trigger="获得【赐福】的目标施放攻击后",
                         state="【赐福】在有效期内",
                         note="倍率=**其自身**攻击力 → 归持有者（=行动者）；用户 2026-10-04 明确"),
    "skill:120204": dict(kind="self", owner="被【赐福】者（=行动者）",
                         trigger="敌方目标受到停云攻击后",
                         state="【赐福】有效期内",
                         note="倍率=**自身**攻击力 → 归持有者；由停云攻击触发但倍率不是停云的"),
    "skill:122402": dict(kind="self", owner="三月七（本人）", trigger="三月七施放普攻/强普时（有【师父】时）",
                         state="场上有指定命途的【师父】",
                         note="倍率=**三月七**#2%攻击力、属性依据【师父】；按「倍率所有者」→ 归三月七本人。"
                              "⚠️ 若要改为归【师父】，说一声"),
    "rank:120901": dict(kind="self", owner="彦卿（本人）", trigger="彦卿攻击处于冻结状态的目标时",
                        state="目标冻结", note="倍率=彦卿攻击力 → 归本人"),
    "skill:110904": dict(kind="self", owner="虎克（本人）", trigger="攻击处于灼烧状态的敌方目标时",
                         state="目标灼烧", note="倍率=虎克攻击力 → 归本人"),
    "skill:100104": dict(kind="follow_up", owner="三月七", trigger="**敌方**攻击带护盾的我方目标后（反击）",
                         state="我方目标有三月七的护盾", note="倍率=三月七攻击力 → 归三月七（敌方回合触发）"),
    "skill:122206": dict(kind="summon", owner="灵砂（召唤物「浮元」）", trigger="【浮元】攻击时",
                         state="浮元在场", note="额外 4 次伤害倍率=灵砂攻击力 → 召唤物归召唤者"),
    "skill:1141515": dict(kind="modifier", owner="缇宝", trigger="", state="",
                          note="昔涟忆灵技：缇宝追加攻击触发结界附加伤害时额外多 1 次（改 140303）"),
    # ===== 原伤害% / 总伤害%（独立乘区，跟行动者）=====
    "skill:141502": dict(kind="pct_actor", owner="当前行动者", trigger="我方全体目标每造成 1 次伤害",
                         state="昔涟结界持续中",
                         note="额外造成**原伤害 #1% 的真实伤害** → 用户口径：独立乘区，跟行动者"),
    "skill:1800707": dict(kind="pct_actor", owner="当前行动者", trigger="持有【迷迷的声援】者每造成 1 次伤害",
                          state="【迷迷的声援】持续中",
                          note="同 141502：原伤害% → 跟行动者"),
    "rank:140806": dict(kind="pct_actor", owner="白厄（本人）", trigger="施放【支柱•死星天裁】后",
                        state="", note="本次攻击总伤害值36% 真实伤害；白厄自己的攻击 → 归本人"),
    "rank:100306": dict(kind="pct_actor", owner="姬子（本人）", trigger="终结技",
                        state="", note="终结技额外 2 次，各为原伤害40% → 归本人"),
    "rank:131506": dict(kind="pct_actor", owner="波提欧（本人）", trigger="天赋击破伤害触发时",
                        state="", note="原伤害倍率40%/70% 的击破伤害 → 归本人"),
    # ===== dot 立即结算（本轮不处理）=====
    "skill:100502": dict(kind="dot_settle", owner="dot 施加者（混伤）", trigger="战技命中处于持续伤害状态的目标",
                         state="", note="**本轮不处理**：多角色 dot 混伤（用户 2026-10-04）"),
    "skill:100503": dict(kind="dot_settle", owner="dot 施加者（混伤）", trigger="终结技",
                         state="", note="同上"),
    "rank:110804": dict(kind="dot_settle", owner="dot 施加者（混伤）", trigger="战技击中风化≥5层",
                        state="", note="同上"),
    "skill:121003": dict(kind="dot_settle", owner="dot 施加者（混伤）", trigger="目标处于灼烧状态",
                         state="", note="同上"),
    "skill:111104": dict(kind="dot_settle", owner="dot 施加者（混伤）", trigger="强化普攻击中裂伤目标",
                         state="", note="同上"),
    "rank:111106": dict(kind="dot_settle", owner="dot 施加者（混伤）", trigger="同上", state="", note="同上"),
    "tree:1410102": dict(kind="dot_settle", owner="dot 施加者（混伤）", trigger="海瑟音施放终结技时",
                         state="", note="同上"),
    "tree:11005103": dict(kind="dot_settle", owner="dot 施加者（混伤）", trigger="卡芙卡天赋追加攻击",
                          state="", note="同上"),
    "tree:1005101": dict(kind="dot_settle", owner="dot 施加者（混伤）", trigger="卡芙卡终结技扩展",
                         state="", note="同上"),
    # ===== 光锥 =====
    "lc:23013": dict(kind="cross", owner="光锥装备者", trigger="任意我方目标施放攻击后",
                     state="装备者治疗过（记录治疗量）",
                     note="倍率=记录治疗量 → 归装备者（治疗者），不一定是行动者；每回合最多 1 次"),
    "lc:23042": dict(kind="cross", owner="光锥装备者（忆灵属性）",
                     trigger="装备者的忆灵下一次攻击后", state="",
                     note="倍率=生命值消耗总量 → 归装备者阵营"),
    "lc:20018": dict(kind="self", owner="光锥装备者（=行动者）", trigger="施放战技后下一次普攻",
                     state="", note="倍率=自身攻击力 → 归行动者"),
    "lc:21029": dict(kind="self", owner="光锥装备者（=行动者）", trigger="装备者施放普攻/战技后",
                     state="", note="倍率=自身攻击力 → 归行动者"),
    # ===== 命中关键词但不是伤害 =====
    "rank:110302": dict(kind="not_damage", owner="希露瓦", trigger="", state="",
                        note="「每触发1次天赋的附加伤害，恢复能量」= 引用，不是伤害"),
    "rank:122301": dict(kind="not_damage", owner="貊泽", trigger="", state="",
                        note="同上（引用天赋附加伤害恢复能量）"),
    "tree:1414103": dict(kind="not_damage", owner="丹恒•腾荒", trigger="", state="",
                         note="给护盾，不出伤"),
    "rank:151201": dict(kind="cross", owner="知更鸟•晴歌（忆灵「晴空乐手」）",
                        trigger="忆灵施放忆灵技时", state="有记录伤害总额",
                        note="额外造成记录伤害总额（11%+气氛值×0.1%）→ 归知更鸟•晴歌"),
    # ===== 其它需要点明的 =====
    "rank:110206": dict(kind="cross", owner="希儿", trigger="【乱蝶】状态下的敌方目标受到攻击后",
                        state="目标带【乱蝶】", note="倍率=希儿终结技伤害15% → 归希儿（触发者可能不是希儿）"),
    "skill:130307": dict(kind="cross", owner="阮•梅", trigger="我方主动攻击、击破敌方弱点后",
                         state="", note="倍率=阮•梅#3%冰属性击破伤害 → 归阮•梅（在模拟宇宙/差分宇宙）"),
    "skill:110304": dict(kind="self", owner="希露瓦（本人）", trigger="本人施放攻击后",
                         state="目标处于触电", note="倍率=希露瓦攻击力 → 归本人"),
    "skill:110702": dict(kind="self", owner="克拉拉（本人）", trigger="战技命中带【反击标记】的目标",
                         state="", note="倍率=克拉拉攻击力 → 归本人"),
    "skill:150308": dict(kind="self", owner="真珠（本人）", trigger="强化普攻",
                         state="持【好活当赏】", note="额外 0.2% 冰属性欢愉伤害 → 归真珠"),
    "rank:141006": dict(kind="modifier", owner="海瑟音", trigger="", state="",
                        note="结界触发的持续伤害次数上限与倍率提高（改 141003）"),
    "skill:1141521": dict(kind="modifier", owner="白厄", trigger="", state="",
                          note="昔涟忆灵技给白厄【火种】/【永续的燃烧】，非独立伤害条目"),
    "skill:1141301": dict(kind="summon", owner="长夜月（忆灵「长夜」）", trigger="忆灵技",
                          state="", note="倍率=「长夜」生命上限 → 忆灵伤害归召唤者"),
    "skill:122403": dict(kind="modifier", owner="三月七", trigger="施放终结技后", state="",
                         note="使下一次强化普攻的段数与额外伤害概率提高（改 122408/122402）"),
    "skill:120904": dict(kind="self", owner="彦卿（本人）", trigger="本人施放攻击后（含追加攻击）",
                         state="", note="本体伤害；**另有冻结附加伤害**（敌方回合结算，属状态类）"),
}

# ── 该条附伤的"倍率占位符 + 所属乘区"（引擎按它取倍率、按乘区决定能不能比）──
# box: atk 攻击力 / elation 欢愉度（白值 7535.107）/ hp 生命上限 / def 防御力
#      / pct 原伤害或总伤害% / heal_record 记录治疗量 / break 击破
BOX_PH = {
    "skill:130903": ("atk", "#4"), "skill:141204": ("atk", "#3"),
    "rank:141206": ("modifier", None), "skill:150204": ("elation", "#1"),
    "skill:140303": ("hp", "#3"), "rank:140301": ("pct", None),
    "rank:140604": ("atk", None), "skill:131402": ("atk", "#3"),
    "skill:122304": ("atk", "#1"), "skill:141003": ("atk", "#4"),
    "skill:1141525": ("hp", "#4"), "rank:141406": ("atk", None),
    "skill:141403": ("atk", "#8"), "rank:141402": ("modifier", None),
    "skill:150303": ("elation", "#2"), "rank:150306": ("elation", None),
    "skill:150320": ("elation", "#4"), "skill:150603": ("elation", "#3"),
    "skill:150610": ("pct", "#5"), "skill:150621": ("elation", "#1"),
    "skill:140204": ("atk", "#1"), "skill:130307": ("break", "#3"),
    "rank:110206": ("pct", None), "rank:130906": ("modifier", None),
    "rank:140302": ("modifier", None), "skill:1141515": ("modifier", None),
    "lc:23013": ("heal_record", "#3"), "lc:23042": ("hp", "#6"),
    "lc:20018": ("atk", "#1"), "lc:21029": ("atk", "#1"),
    "skill:120202": ("atk", "#1"), "skill:120204": ("atk", "#1"),
    "skill:122402": ("atk", "#2"), "skill:150308": ("elation", "#5"),
    "rank:151201": ("heal_record", None), "skill:141502": ("pct", "#1"),
    "skill:1800707": ("pct", "#1"), "rank:140806": ("pct", None),
    "rank:100306": ("pct", None), "rank:131506": ("pct", None),
    "skill:100104": ("atk", "#1"), "rank:110706": ("atk", None),
    "skill:122206": ("atk", None), "skill:110304": ("atk", "#1"),
    "skill:110702": ("atk", "#2"), "skill:120904": ("atk", "#4"),
}

# ── 规则自动分类（一眼可判的）──
RULES = [
    ("dot_immediate", re.compile(r"立即产生(相当于|等同于)原伤害|立即产生伤害"),
     "dot_settle", "dot 施加者（混伤）", "状态立即结算 → **本轮不处理**（用户 2026-10-04）"),
    ("state_dot", re.compile(r"(冻结|触电|灼烧|裂伤|风化)[^。；\n]{0,80}(附加伤害|持续伤害)"),
     "state_dot", "状态施加者", "状态类持续伤害（冻结/触电/灼烧…）：倍率=施加者、**在敌方回合结算**，与 dot 同因，本轮登记不处理"),
    ("literal_multi", re.compile(r"额外造成(#\d+\[i\]|\d+)次伤害"),
     "self", "本人", "本体多段（归本人）"),
    ("extra_own_pct", re.compile(r"额外造成#\d+\[[if]\d?\]%[^。；\n]{0,10}伤害"),
     "self", "本人", "本体额外一段，倍率取自自身 → 归本人"),
    ("equals_own_literal", re.compile(r"(额外)?造成等同于[^。；\n]{0,16}?(\d+%|#\d+\[)[^。；\n]{0,14}?(附加伤害|伤害)"),
     "self", "本人", "倍率取自自身 → 归本人"),
    ("one_extra_hit", re.compile(r"额外造成1次伤害|造成1次附加伤害"),
     "self", "本人", "本体额外一段 → 归本人"),
    ("equals_own_mult", re.compile(r"等同于(普攻|战技|终结技|天赋)?伤害倍率"),
     "self", "本人", "倍率=本人技能倍率 → 归本人"),
    ("summon_attack", re.compile(r"【浮元】攻击时|忆灵[^。；\n]{0,10}攻击时"),
     "summon", "召唤者", "召唤物攻击 → 归召唤者"),
    ("multi_hit", re.compile(r"额外造成#\d+\[i\](次|段)伤害"),
     "self", "本人", "本体多段/弹射（归本人，不需剥离）"),
    ("multi_hit_seg", re.compile(r"初始造成#\d+\[i\]段伤害|额外造成#\d+\[i\]段伤害"),
     "self", "本人", "本体多段（归本人）"),
    ("own_attr_extra", re.compile(r"额外造成[^。；\n]{0,40}?等同于[^。；\n]{0,14}#\d+\["),
     "self", "本人", "倍率取自自身 → 归本人"),
    ("own_attr_extra2", re.compile(r"(额外造成|追加)1次等同于(其自身|自身|持有者自身)#"),
     "self", "本人", "倍率取自自身 → 归本人"),
    ("counter", re.compile(r"发起反击"),
     "follow_up", "技能主人", "反击 → 归技能主人"),
]


def load_db():
    j = lambda n: json.load(open(_os.path.join(DB, n), encoding="utf-8"))
    return {"characters": j("characters.json"), "skills": j("character_skills.json"),
            "ranks": j("character_ranks.json"), "trees": j("character_skill_trees.json"),
            "light_cones": j("light_cones.json"), "lc_ranks": j("light_cone_ranks.json")}


def all_entries(db):
    """全库条目：key → {who,id,type,name,text}"""
    out = {}
    char_by_id = {cid: c["name"] for cid, c in db["characters"].items()}
    for cid, c in db["characters"].items():
        for sid in c.get("skills", []):
            s = db["skills"].get(sid) or {}
            out["skill:%s" % sid] = {"who": c["name"], "id": sid,
                                     "type": s.get("type_text") or "", "name": s.get("name") or "",
                                     "text": s.get("desc") or ""}
        for rid in c.get("ranks", []):
            r = db["ranks"].get(rid) or {}
            out["rank:%s" % rid] = {"who": c["name"], "id": rid,
                                    "type": "星魂%d" % (r.get("rank") or 0), "name": r.get("name") or "",
                                    "text": r.get("desc") or ""}
    for tid, tr in db["trees"].items():
        out["tree:%s" % tid] = {"who": char_by_id.get(tid[:4], ""), "id": tid, "type": "行迹",
                                "name": tr.get("name") or "", "text": tr.get("desc") or ""}
    for lid, lr in db["lc_ranks"].items():
        out["lc:%s" % lid] = {"who": db["light_cones"].get(lid, {}).get("name", ""), "id": lid,
                              "type": "光锥", "name": "", "text": lr.get("desc") or ""}
    return out


def classify(key, e, by_text):
    if key in CURATION:
        return dict(CURATION[key], how="human")
    if e["text"] in by_text:
        return dict(by_text[e["text"]], how="inherit")
    for name, pat, kind, owner, note in RULES:
        if pat.search(e["text"]):
            return dict(kind=kind, owner=owner, trigger="本人回合内", state="", note=note,
                        how="rule:" + name)
    return None


def main():
    db = load_db()
    ents = all_entries(db)
    for k in MANUAL:
        if k not in ents:
            print("⚠️ MANUAL 里的 key 不存在：%s" % k)
    cand_keys = [k for k, e in ents.items() if CAND.search(e["text"])] + \
                [k for k in MANUAL if k in ents and not CAND.search(ents[k]["text"])]
    cand_keys = sorted(set(cand_keys))

    if "--dump" in sys.argv:
        for k in cand_keys:
            e = ents[k]
            print("=" * 78)
            print("%-16s %-12s %-8s %s" % (k, e["who"], e["type"], e["name"]))
            print("   ", e["text"].replace("\n", " ")[:240])
        print("\n候选 %d ｜ 人工定案 %d ｜ 规则/继承 %d ｜ 未分类 %d"
              % (len(cand_keys), sum(1 for k in cand_keys if k in CURATION),
                 sum(1 for k in cand_keys if k not in CURATION and classify(k, ents[k], {})),
                 sum(1 for k in cand_keys if classify(k, ents[k], {}) is None)))
        return 0

    # 同文案继承表（只认人工定案过的文案）
    by_text = {}
    for k, c in CURATION.items():
        if k in ents:
            by_text.setdefault(ents[k]["text"], c)

    rows, unclassified = [], []
    try:
        from tools.team2.make_damage_ledger import parse_damage
    except Exception:                                     # noqa: BLE001
        parse_damage = None
    for k in cand_keys:
        e = ents[k]
        cl = classify(k, e, by_text)
        if cl is None:
            unclassified.append(k)
            cl = dict(kind="未分类", owner="", trigger="", state="", note="**待人工定案**", how="none")
        box, ph = BOX_PH.get(k, (None, None))
        dmg = []
        if parse_damage is not None and "skill:" in k:
            params = (db["skills"].get(e["id"]) or {}).get("params")
            dmg = parse_damage(e["text"], params)
        rows.append(dict(key=k, who=e["who"], id=e["id"], type=e["type"], name=e["name"],
                         text=e["text"], box=box, mult_ph=ph, damage=dmg, **cl))
    order = ["cross", "designated", "follow_up", "pct_actor", "dot_settle", "state_dot", "summon",
             "self", "modifier", "not_damage", "未分类"]
    rows.sort(key=lambda r: (order.index(r["kind"]) if r["kind"] in order else 99, r["who"], r["id"]))
    json.dump(rows, open(_os.path.join(HERE, "out/add_damage_catalog.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    title = {
        "cross": "一、外源附伤（**要剥离**，归倍率所有者）",
        "designated": "二、倍率取自「被指定队友」（**要剥离**，归被指定者；一次攻击可能两个归属）",
        "follow_up": "三、追击类（跨人，但不是附伤）",
        "pct_actor": "四、原伤害%/总伤害% 型（独立乘区，**跟当前行动者**，不剥离）",
        "dot_settle": "五、dot 立即结算（**本轮不处理**：多角色混伤）",
        "state_dot": "五之二、状态类持续伤害（冻结/触电/灼烧…，**本轮登记不处理**：倍率=施加者、在敌方回合结算）",
        "summon": "六、召唤物/忆灵（顶轴有卡 → 按顶端卡归召唤者；**盲盒【?】卡在此**）",
        "self": "七、归行动者本人（**不剥离**）",
        "modifier": "八、不是伤害：改另一条附伤的倍率/次数",
        "not_damage": "九、不是伤害：命中关键词但只是引用/状态",
        "未分类": "⚠️ 未分类（必须补）",
    }
    L = ["# T2 附伤来源库（全库扫描 + 人工定案）", "",
         "> **判据**：归属 = **倍率所有者**（一次伤害 `a%` 主c + `b%` 辅助 → 分开计）。",
         "> 「造成原伤害/本次攻击总伤害 X%」= **独立乘区，跟当前行动者**（用户 2026-10-04 口径）。",
         "> 忆灵/召唤物（顶轴有自己的卡，**含盲盒**）→ 按顶端卡归召唤者。",
         "> 停云【赐福】这类\"等同于**持有者自身**\"→ 归持有者（=行动者），不剥离。",
         "",
         "生成：`python -u tools/team2/scan_add_damage.py` ｜ 数据源：`StarRailRes-index_min/index_min/cn`",
         "（全 88 角色 + 星魂 + 行迹 + 光锥 + 遗器；遗器扫描结果：**0 条**）", ""]
    for kind in order:
        grp = [r for r in rows if r["kind"] == kind]
        if not grp:
            continue
        L += ["## " + title.get(kind, kind), "",
              "| 谁 | 条目 | 触发条件 | 归属（倍率所有者）| 状态条件 | 分类依据 |",
              "|---|---|---|---|---|---|"]
        for r in grp:
            L.append("| %s | `%s` %s %s | %s | %s | %s | %s |" % (
                r["who"], r["id"], r["type"], r["name"], r["trigger"], r["owner"], r["state"],
                r["how"]))
        L.append("")
        for r in grp:
            if r["note"]:
                L.append("* `%s` %s：%s" % (r["id"], r["name"], r["note"]))
        L.append("")
    txt = "\n".join(L)
    open(_os.path.join(HERE, "out/add_damage_catalog.md"), "w", encoding="utf-8").write(txt + "\n")
    print(txt)
    print("候选 %d ｜ 未分类 %d %s" % (len(rows), len(unclassified), unclassified))
    return 1 if unclassified else 0


if __name__ == "__main__":
    sys.exit(main())
