# -*- coding: utf-8 -*-
"""① 写"库条目 ↔ 官方身份"映射表；② 对账"还缺哪些角色/皮肤"。

为什么需要映射表：库里的条目名是历史攒下来的，有的与官方名不一致（最典型：
条目 `银狼` 装的其实是 **狼尊/银狼LV.999(1506)**，而 1006 银狼 是另一个身份）。
改名会牵动 E2 线（`axis_actor_team2.py` 写死 UNITS=["银狼",...]），所以先把映射写成数据文件。
"""
import io
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import axis_actor as T      # noqa: E402

RAW = r"D:\project\btdsh\raw\index"
chars = json.load(io.open(os.path.join(RAW, "characters.json"), encoding="utf-8"))
avs = json.load(io.open(os.path.join(RAW, "avatars.json"), encoding="utf-8"))
off = {v["name"]: v["id"] for v in chars.values()}
def norm(s):
    """官方用「•」(U+2022)，历史文件里常写成「·」(U+00B7) —— 归一化后再比对。"""
    return s.replace("·", "•")
off_n = {norm(k): v for k, v in off.items()}

# 库里那些"与官方名不同/需要人工指认"的条目
MANUAL = {
    "银狼": ("1506", "狼尊（官方名 银狼LV.999）", "⚠️历史遗留：条目名是「银狼」，实际是狼尊"),
    "小银狼": ("1006", "银狼", "本轮新录；与上面的狼尊是**不同身份**"),
    "小三月": ("1001", "三月七·存护·皮肤「冬去煦至」", "旧录屏里用的是皮肤；本轮录的是原皮"),
    "小黑塔": ("1013", "黑塔", ""),
    "老杨": ("1004", "瓦尔特", ""),
    "火花": ("1501", "火花·皮肤「甜梦电波」", "⚠️用户 2026-10-03 指出：库里这条是**皮肤**，不是原皮"),
    "火花·原皮": ("1501", "火花（原皮）", "补充1 补的；与上面那条皮肤是两个不同外观"),
    "流萤·原皮": ("1310", "流萤（原皮）", "补充1 补的；库里另有皮肤「春日手信」"),
    "流萤·春日手信": ("1310", "流萤·皮肤「春日手信」", ""),
    "阮•梅": ("1303", "阮•梅", ""),
    "开拓者•欢愉": ("208009", "开拓者•欢愉", "官方 avatars 里是 {NICKNAME}•欢愉"),
    "千冶•刃": ("1507", "千冶•刃", ""),
    "金闪闪（吉尔伽美什）": ("1509", "吉尔伽美什", ""),
    "流萤·春日手信": ("1310", "流萤·皮肤「春日手信」", ""),
    "三月七·存护（原皮）": ("1001", "三月七·存护·原皮", ""),
    "Saber": ("1014", "Saber", ""),
    "Archer": ("1015", "Archer", ""),
    "远坂凛": ("1508", "远坂凛", ""),
    "托帕": ("1112", "托帕&账账", "官方条目标题是「托帕&账账」，本体是托帕"),
    "三月七·巡猎": ("1224", "三月七（巡猎形态）", "官方名就叫「三月七」，id 1224 是巡猎那套；1001 是存护"),
    "浮元": (None, "召唤物：浮元（灵砂）", "名字出自 1222 灵砂 技能文本；粉色兔子"),
    # 用户给的皮肤名（官方 index 快照里还没有这三个；按用户给的名字存）
    "风堇·云边拾暖": ("1409", "风堇·皮肤「云边拾暖」", "名字由用户提供（raw 里没有时装表）"),
    "遐蝶·幽梦翩跹": ("1407", "遐蝶·皮肤「幽梦翩跹」", "名字由用户提供（raw 里没有时装表，avatars.json 只是头像名）"),
    "绯英·月待花时": ("1505", "绯英·皮肤「月待花时」", "名字由用户提供（raw 里没有时装表）"),
    "阮•梅·雪绽梅笺": ("1303", "阮•梅·皮肤「雪绽梅笺」", ""),
    "记忆主": ("208007", "开拓者•记忆", "官方 avatars 里是 {NICKNAME}•记忆"),
    # 召唤物/忆灵：官方 characters.json 里**没有独立条目**，名字出自角色技能文本
    "神君": (None, "召唤物：神君（景元）", "名字出自 1204 景元 技能文本"),
    "账账": (None, "召唤物：账账（托帕&账账）", "名字出自 1112 技能文本"),
    "衣匠": (None, "忆灵：衣匠（阿格莱雅）", "名字出自 1402 技能文本"),
    "龙灵": (None, "召唤物：龙灵（丹恒•腾荒）", "名字出自 1414 技能文本"),
    "晴空乐手": (None, "忆灵：晴空乐手（知更鸟•晴歌）",
                 "名字出自 1512 技能文本。⚠️用户 2026-10-03 说明：**三个是一体的**，"
                 "实战中很难打出单个忆灵 ⇒ 库里这一条就是「三合一」形态，不必再拆 贝茜/啾米/派丁"),
    "迷迷": (None, "忆灵：迷迷（记忆主/开拓者•记忆）", ""),
    "拓星者": (None, "召唤物：拓星者（姬子•启行的助战技）", ""),
    "死龙": (None, "忆灵（遐蝶的召唤物）", "官方素材里没有忆灵"),
    "长夜": (None, "忆灵（长夜月的召唤物）", "官方素材里没有忆灵"),
    "小伊卡": (None, "忆灵（风堇的召唤物）", "官方素材里没有忆灵"),
    "德谬歌": (None, "忆灵（昔涟的召唤物）", "官方素材里没有忆灵"),
}

with np.load(T.BANK_PATH) as z:
    units = list(z.files)

ident = {}
for u in units:
    if u in MANUAL:
        cid, disp, note = MANUAL[u]
    elif u in off or norm(u) in off_n:
        cid = off.get(u) or off_n[norm(u)]
        disp, note = u, ("" if u in off else "⚠️ 名字里的点与官方不同（· vs •），实际是同一身份")
    else:
        cid, disp, note = None, u, "⚠️ 未在官方名单里找到同名条目，待人工确认"
    ident[u] = dict(id=cid, name=disp, note=note)

out = os.path.join(ROOT, "out", "teams", "unit_identity.json")
with io.open(out, "w", encoding="utf-8", newline="\n") as f:
    json.dump({"_note": "库条目名 → 官方身份。库条目名是历史产物，可能与官方名不一致（见 note）。",
               "units": ident}, f, ensure_ascii=False, indent=1)
print("已写出 %s（%d 个条目）" % (out, len(ident)))

unknown = [u for u, v in ident.items() if v["id"] is None and "忆灵" not in v["name"] and "召唤物" not in v["name"]]
print("\n未能自动对上官方 id 的条目（需人工确认）：%s" % (unknown or "（无）"))

# ── 对账：官方 98 个可玩角色里，库里还没有的 ──
have_ids = {v["id"] for v in ident.values() if v["id"]}
missing = [(v["id"], v["name"]) for v in chars.values()
           if v["id"] not in have_ids and not v["name"].startswith("{NICKNAME}")]
missing.sort(key=lambda kv: kv[1])
print("\n=== 官方 %d 个可玩角色中，库里还缺 %d 个 ===" % (len(chars), len(missing)))
for i in range(0, len(missing), 6):
    print("  " + "  ".join("%s(%s)" % (n, i2) for i2, n in missing[i:i + 6]))

# ── 皮肤/变体（avatars 里带 • 的）也列出来 ──
skins = sorted({v["name"] for v in avs.values()
                if v.get("name") and "•" in v["name"]})
print("\n=== 官方记录在册的皮肤/变体（avatars，共 %d 个；库里只有极少）===" % len(skins))
for i in range(0, len(skins), 6):
    print("  " + " | ".join(skins[i:i + 6]))
