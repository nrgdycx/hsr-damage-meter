# -*- coding: utf-8 -*-
"""【线2】把欢愉队 4 人的技能文本抽成 JSON（**两个数据源合并**）。

数据源（**都只读，不改**）：
  1. `StarRailRes-index_min/index_min/cn/character_skills.json`（**主源**，工作区内的新数据）
     —— 全角色技能，含 **真珠（1503）**；schema：name/type_text/effect_text/element/desc/params
  2. `D:/project/btdsh/01_角色战斗文本/角色/<id>_<名字>/`（**兜底源**，D 线/A 线一直在用）
     —— 逐角色文件，schema：typeCN/effectCN/elementCN/desc/paramsByLevel

⚠️ 教训（2026-10-01，用户指出）：我第一版**只查了 btdsh/**，就下结论"资料库没有真珠的技能"。
   真珠的数据在工作区内的 `StarRailRes-index_min/` 里有。**多数据源要先都列一遍再下结论。**

用法：
  python -u extract_skills_L2.py            # → out/skills_L2.json + out/L2_skills.txt
"""
# [P3 整理] 原路径：extract_skills_L2.py（已移入 tools/，功能见 tools/README.md）
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
INDEX_MIN = os.path.join(HERE, "StarRailRes-index_min/index_min/cn")
REF = r"D:/project/btdsh/01_角色战斗文本/角色"

CHARS = [("1506", "银狼LV.999"), ("1502", "爻光"), ("1501", "火花"), ("1503", "真珠")]

# 「伤害不是在自己回合打出来」的机制关键词 —— 归属时最容易混账的那些
TRIGGER_KW = ("结界", "触发", "每消耗", "持续伤害", "附加", "附伤", "额外造成", "真实伤害",
              "欢愉伤害", "结算", "忆质", "笑点", "好活当赏", "追击", "追加", "攻击后",
              "下一次攻击", "深度学习", "美学底本")


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "")


def from_index_min(cid):
    """新数据源（StarRailRes index_min）：返回 {skill_id: 统一格式} 或 None。"""
    p = os.path.join(INDEX_MIN, "character_skills.json")
    if not os.path.exists(p):
        return None
    sk = json.load(open(p, encoding="utf-8"))
    out = {}
    for sid, s in sk.items():
        if not str(sid).startswith(cid):
            continue
        out[sid] = {
            "name": s.get("name"), "type": s.get("type_text"), "effect": s.get("effect_text"),
            "element": s.get("element"), "desc": strip_tags(s.get("desc", "")),
            "params_by_level": s.get("params"), "max_level": s.get("max_level"),
        }
    return out or None


def from_btdsh(cid, name):
    """兜底数据源（btdsh 逐角色文件）。"""
    d = os.path.join(REF, "%s_%s" % (cid, name))
    if not os.path.isdir(d):
        return None
    f = [x for x in os.listdir(d) if x.endswith(".json")]
    if not f:
        return None
    raw = json.load(open(os.path.join(d, f[0]), encoding="utf-8"))
    out = {}
    for sid, s in (raw.get("skills") or {}).items():
        out[sid] = {
            "name": s.get("name"), "type": s.get("typeCN"), "effect": s.get("effectCN"),
            "element": s.get("elementCN"), "desc": strip_tags(s.get("desc", "")),
            "params_by_level": s.get("paramsByLevel"), "max_level": s.get("maxLevel"),
        }
    return out or None


def main():
    out = {"_note": "欢愉队（录屏2）技能文本 —— 主源 StarRailRes-index_min/index_min/cn，"
                    "兜底源 D:/project/btdsh/01_角色战斗文本/角色（都只读）",
           "_sources": {}, "_missing": {}, "characters": {}}
    lines = []
    for cid, name in CHARS:
        src, skills = "index_min", from_index_min(cid)
        if not skills:
            src, skills = "btdsh", from_btdsh(cid, name)
        if not skills:
            out["_missing"][name] = {"id": cid, "evidence": "两个数据源都没有该 id 的技能"}
            lines.append("### ⚠️ %s（id %s）：两个数据源都没有" % (name, cid))
            continue
        out["_sources"][name] = src
        if src == "btdsh":                      # 主源没有时，用兜底源补，并记明来源
            out["_missing"].setdefault("_note", {})["%s 的主源缺失" % name] = "已用 btdsh 兜底"
        for sid, s in skills.items():
            desc = s["desc"]
            simple = desc
            hits = [k for k in TRIGGER_KW if k in desc]
            s["damage_outside_own_turn"] = bool(hits)
            s["trigger_keywords"] = hits
        out["characters"][name] = {"id": cid, "source": src, "skills": skills}
        lines.append("### %s（id %s，来源 %s）" % (name, cid, src))
        for sid, s in sorted(skills.items()):
            flag = "  ⚠️ 非本人回合也能出伤" if s["damage_outside_own_turn"] else ""
            lines.append("  [%s] %s  %s/%s%s" % (sid, s["name"], s["type"], s["effect"], flag))
            if s["damage_outside_own_turn"]:
                for ln in s["desc"].split("\n"):
                    if any(k in ln for k in TRIGGER_KW):
                        lines.append("        · " + ln.strip()[:160])
        lines.append("")

    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
    json.dump(out, open(os.path.join(HERE, "out/skills_L2.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    txt = "\n".join(lines)
    open(os.path.join(HERE, "out/L2_skills.txt"), "w", encoding="utf-8").write(txt + "\n")
    print(txt[:3000])
    print("\n来源：%s" % out["_sources"])
    print("已写出 out/skills_L2.json / out/L2_skills.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
