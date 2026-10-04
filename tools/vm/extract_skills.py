# -*- coding: utf-8 -*-
"""D 线：把 btdsh 资料库里 4 名角色（含忆灵）的完整技能倍率抽成 out/skills_full.json。

只读 D:/project/btdsh/，不写那里。
输出结构：
{
  "角色": {
     "id": "1413", "name": "长夜月",
     "skills": [ {...统一字段...} ],
     "eidolons": [...], "traces": [...]
  }, ...
}
统一技能字段：id / owner / name / typeCN / effectCN / elementCN / maxLevel /
             params_max（满级参数）/ paramsByLevel / desc / simple / source
"""
# [P3 整理] 原路径：extract_skills_full_D.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

REF = r"D:/project/btdsh/01_角色战斗文本/角色"
OUT = os.path.join(ROOT, "out", "skills_full.json")

# 角色 id → (显示名, btdsh 目录名)
TARGETS = {
    "1407": ("遐蝶", "1407_遐蝶"),
    "1409": ("风堇", "1409_风堇"),
    "1413": ("长夜月", "1413_长夜月"),
    "1415": ("昔涟", "1415_昔涟"),
}

# 技能 id 前缀 → 归属（忆灵）
MEMO_PREFIX = {
    "14071": "死龙", "14072": "死龙",
    "14091": "小伊卡", "14092": "小伊卡",
    "14131": "长夜", "14132": "长夜",
    "14151": "德谬歌", "14152": "德谬歌",
}

OUTER_KEYS = ("skills", "memospriteSkills", "memoSkills", "summonSkills",
              "servantSkills", "pets", "memosprite", "summons", "children")


def walk_skills(node, path, sink):
    """递归找出所有形如 {id, name, desc, paramsByLevel} 的技能对象。"""
    if isinstance(node, dict):
        if "paramsByLevel" in node or ("name" in node and "desc" in node and "maxLevel" in node):
            sink.append((path, node))
            return
        for k, v in node.items():
            walk_skills(v, path + "/" + str(k), sink)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk_skills(v, path + "[%d]" % i, sink)


def norm(skill, owner, path):
    pbl = skill.get("paramsByLevel") or []
    return {
        "id": skill.get("id") or skill.get("baseId"),
        "owner": owner,
        "name": skill.get("name"),
        "typeCN": skill.get("typeCN") or skill.get("type"),
        "effectCN": skill.get("effectCN") or skill.get("effect"),
        "elementCN": skill.get("elementCN"),
        "maxLevel": skill.get("maxLevel"),
        "params_max": pbl[-1] if pbl else None,
        "paramsByLevel": pbl,
        "desc": skill.get("desc"),
        "simple": skill.get("simple"),
        "source": path,
    }


def owner_of(skill_id, char_name):
    sid = str(skill_id or "")
    for pref, memo in MEMO_PREFIX.items():
        if sid.startswith(pref):
            return memo
    return char_name


def main():
    result = {}
    for cid, (name, dirname) in TARGETS.items():
        fp = os.path.join(REF, dirname, "%s_%s.json" % (cid, name))
        if not os.path.exists(fp):
            # 目录名里可能有特殊字符，退化成前缀匹配
            d = os.path.join(REF, dirname)
            cand = [f for f in os.listdir(d) if f.endswith(".json")]
            fp = os.path.join(d, cand[0])
        raw = json.load(io.open(fp, encoding="utf-8"))

        sink = []
        walk_skills(raw, "", sink)
        # 去重：同 id 只留第一个
        seen, skills = set(), []
        for path, sk in sink:
            sid = str(sk.get("id") or sk.get("baseId") or "")
            if not sid or sid in seen:
                continue
            seen.add(sid)
            skills.append(norm(sk, owner_of(sid, name), path))

        result[name] = {
            "id": cid,
            "name": name,
            "top_keys": sorted(raw.keys()),
            "skills": skills,
            "raw": raw,
        }
        kinds = {}
        for s in skills:
            kinds[s["owner"]] = kinds.get(s["owner"], 0) + 1
        print("%-5s id=%s  顶层键=%s  技能 %d 条 %s"
              % (name, cid, ",".join(result[name]["top_keys"]), len(skills), kinds))

    # 落盘（去掉 raw 以免文件过大，单独留一个 keys 概览）
    slim = {}
    for name, v in result.items():
        slim[name] = {k: v[k] for k in ("id", "name", "skills")}
    with io.open(OUT, "w", encoding="utf-8") as f:
        json.dump(slim, f, ensure_ascii=False, indent=1)
    print("\n写出 %s" % OUT)

    for name, v in result.items():
        print("\n===== %s =====" % name)
        for s in v["skills"]:
            print("  %-8s %-22s %-4s %-4s maxLv=%-3s params=%s"
                  % (s["owner"], s["name"], s["typeCN"], s["effectCN"],
                     s["maxLevel"], s["params_max"]))


if __name__ == "__main__":
    main()
