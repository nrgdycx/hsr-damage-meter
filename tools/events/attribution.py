# -*- coding: utf-8 -*-
"""
归属引擎 —— 把「行动轴顶端是谁」翻译成「这一击算谁的伤害」。

规则来源（交接文档已确认口径，不要再问用户）：
  1) 归属依据 = **谁在攻击**（行动轴顶端那张卡 = 当前行动者，用户已确认"会变"）
  2) **忆灵伤害算给召唤者**
  3) 追击/插入终结技：行动轴顶端会变成释放者的卡 → 按顶端卡归属
  4) 附伤（倍率来源）：倍率来自攻击者算攻击者，来自附伤者算附伤者 —— 由技能介绍判定
  5) 敌人/boss/机制卡不计入我方伤害

重要约定（用户明确要求）：
  * **不靠伤害数值反推归属**（倍率来源看技能介绍即可）
  * 读数不确定时**宁可标"待复核"，也不猜**（避免把德谬歌算成长夜月这类静默错误）
"""
# [P3 整理] 原路径：attribution.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

# 行动轴顶端卡 → 归属者
# 我自己方角色：归本人
ALLY_SELF = {
    "遐蝶": "遐蝶",
    "风堇": "风堇",
    "昔涟": "昔涟",
    "长夜月": "长夜月",
}

# 忆灵 → 召唤者（文档：忆灵伤害算召唤者）
#   德谬歌 = 昔涟的忆灵（用户已确认：t=307 顶端是德谬歌）
#   长夜   = 长夜月的忆灵（用户描述：红或蓝水母）
#   小伊卡 = 风堇的忆灵（队伍栏 slot1 圆圈：白粉色小兽+金冠，已确认）
#   死龙   = 遐蝶的忆灵（用户提示：我先前把 slot4 蓝蝴蝶当死龙是错的）
MEMOSPRITE = {
    "德谬歌": "昔涟",
    "长夜": "长夜月",
    "小伊卡": "风堇",
    "死龙": "遐蝶",
}

# 非我方（不计入我方伤害统计）
NON_ALLY = {
    "阿哈时刻": None,        # 面具框机制：里面依次放欢技，需特判
    "boss": None,
    "boss第二动": None,
    "敌人a": None,
    "敌人b": None,
    "轮次分割线": None,
}

# 置信度 → 是否直接采纳
CONF_ACCEPT = ("high",)          # 只有 high 直接采纳
CONF_REVIEW = ("mid", "low")     # 其他一律标记待复核


def attribute(top_card, confidence="high"):
    """
    输入：行动轴顶端卡身份 + 置信度
    输出：dict(owner, status, reason)
      owner  : 归属角色 或 None
      status : 'ok'     可直接采纳
               'review' 需人工复核（识别不确定）
               'mechanic' 机制帧（阿哈时刻，需特判）
               'non_ally' 非我方
    """
    if not top_card:
        return {"owner": None, "status": "review",
                "reason": "行动轴顶端未识别出卡片（可能被特效遮挡或为空槽）"}

    if confidence not in CONF_ACCEPT:
        return {"owner": None, "status": "review",
                "reason": "顶端卡识别置信度=%s（<high），不猜；原判定=%s" % (confidence, top_card)}

    if top_card in ALLY_SELF:
        return {"owner": ALLY_SELF[top_card], "status": "ok",
                "reason": "我方角色本体行动"}

    if top_card in MEMOSPRITE:
        owner = MEMOSPRITE[top_card]
        return {"owner": owner, "status": "ok",
                "reason": "忆灵「%s」行动 → 归召唤者 %s" % (top_card, owner)}

    if top_card == "阿哈时刻":
        return {"owner": None, "status": "mechanic",
                "reason": "阿哈时刻机制帧：面具框占位，里面依次放欢技，需特判归属"}

    if top_card in NON_ALLY:
        return {"owner": None, "status": "non_ally",
                "reason": "敌方/机制卡，不计入我方伤害"}

    return {"owner": None, "status": "review",
            "reason": "未知卡片身份：%s" % top_card}


if __name__ == "__main__":
    print("归属规则自检:\n")
    cases = [
        ("遐蝶", "high"), ("风堇", "high"), ("昔涟", "high"), ("长夜月", "high"),
        ("德谬歌", "high"), ("长夜", "high"), ("小伊卡", "high"), ("死龙", "high"),
        ("阿哈时刻", "high"), ("boss", "high"), ("敌人a", "high"),
        ("长夜月", "mid"), ("昔涟", "low"), (None, "none"),
    ]
    for card, conf in cases:
        r = attribute(card, conf)
        print("  顶端=%-8s 置信=%-5s → 归属=%-6s 状态=%-9s %s" %
              (card or "(空)", conf, r["owner"] or "-", r["status"], r["reason"]))
