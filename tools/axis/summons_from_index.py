# -*- coding: utf-8 -*-
"""从官方 index 里挖"每个角色有没有忆灵/召唤物、它叫什么"。

来源（按可靠性排序）：
  1. `character_skills.json` 的技能描述文本 —— 记忆命途角色会写「召唤「某某」」
  2. `character_ranks.json`（星魂）与 `character_skill_trees.json`（行迹）的文本
  3. `descriptions.json` 通用词条（补漏）

做法：把技能的 desc/simple_desc/effect_text 拼起来，按角色分组；在其中找
「XX」引号里的名字 + 已知召唤物关键词，输出"角色 → 召唤物候选"。
"""
import io
import json
import os
import re
import sys

RAW = r"D:\project\btdsh\raw\index"
chars = json.load(io.open(os.path.join(RAW, "characters.json"), encoding="utf-8"))
name_of = {v["id"]: v["name"] for v in chars.values()}
sk = json.load(io.open(os.path.join(RAW, "character_skills.json"), encoding="utf-8"))
rk = json.load(io.open(os.path.join(RAW, "character_ranks.json"), encoding="utf-8"))
st = json.load(io.open(os.path.join(RAW, "character_skill_trees.json"), encoding="utf-8"))

# 已知召唤物/忆灵名（用来定位"谁提到它"）
KNOWN = ["衣匠", "死龙", "小伊卡", "德谬歌", "长夜", "神君", "账账", "浮元", "迷迷",
         "金龙", "卡厄斯兰娜", "烟兽", "忆灵", "召唤"]


def texts_for(cid):
    out = []
    for coll in (sk, rk, st):
        for k, v in coll.items():
            # 技能/星魂/行迹的 id 以角色 id 开头（例：110201…）
            if not str(k).startswith(str(cid)):
                continue
            for f in ("name", "desc", "simple_desc", "effect_text", "effect"):
                t = v.get(f)
                if isinstance(t, str) and t:
                    out.append(t)
    return out


rows = []
for cid, nm in sorted(name_of.items(), key=lambda kv: kv[1]):
    if nm.startswith("{NICKNAME}"):
        continue
    txt = "\n".join(texts_for(cid))
    if not txt:
        continue
    hits = [w for w in KNOWN if w in txt]
    # 引号里的专名（「XX」）也抓出来，很多召唤物就写在这里
    quoted = re.findall(r"「([^」]{1,8})」", txt)
    if "忆灵" in txt or "召唤" in txt:
        rows.append((cid, nm, hits, sorted(set(quoted))[:8]))

print("提到「忆灵/召唤」的角色 %d 个：\n" % len(rows))
for cid, nm, hits, quoted in rows:
    print("%-8s %-10s 关键词=%-22s 引号名=%s"
          % (cid, nm, ",".join(hits) if hits else "-", ",".join(quoted)))

# 全库范围：哪些引号专名与"忆灵"同段出现（更可能是召唤物名）
print("\n=== 含「忆灵」的角色里，引号专名统计 ===")
from collections import Counter
cnt = Counter()
for cid, nm, hits, quoted in rows:
    txt = "\n".join(texts_for(cid))
    if "忆灵" in txt:
        for q in quoted:
            cnt[q] += 1
for q, c in cnt.most_common(40):
    print("  %-14s 出现于 %d 个角色" % (q, c))
