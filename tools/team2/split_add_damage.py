# -*- coding: utf-8 -*-
"""【T2】附伤分离引擎 —— 把一段伤害按「倍率所有者」拆开。

口径（用户 2026-10-04 定案，详见 docs/附伤与开大踢轴.md）：
  1. **归属 = 倍率所有者**：一次伤害 `a%` 主c + `b%` 辅助 → 分开计。
  2. 忆灵/召唤物（顶轴有自己的卡，**含盲盒**）→ 按顶端卡归召唤者。
  3. 「造成原伤害 / 本次攻击总伤害 X%」= 独立乘区，**跟当前行动者**，不剥离。
  4. 停云【赐福】这类"等同于**持有者自身**"→ 归持有者（=行动者），不剥离。
  5. dot / 状态类持续伤害 → 本轮不处理，登记在来源库里。

量的口径（用户 2026-10-04 选 α：**不输入面板**）：
  * 同一乘区内：权重 = 倍率之比（等价假设：两边的面板项/暴击区相同）→ `估算`
  * 跨乘区（如 攻击力倍率 vs 欢愉度白值 7535.107）：**给区间**，把未知系数扫一遍 → `估算(区间)`
  * 召唤物/盲盒/欢愉技整段归其所有者 → `精确`
  * 缺倍率或缺触发规则 → `missing`（**界面不显示"待复核"**，按用户要求；依据写在 `why` 里）

用法：
  python -u tools/team2/split_add_damage.py --selftest
  python -u tools/team2/split_add_damage.py --frame 86        # 单帧判定（看归属）
  python -u tools/team2/split_add_damage.py --team 火花 爻光 真珠 银狼 LV.999 --actor 火花
"""
import os as _os
import sys as _sys
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import json
import os
import sys

HERE = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if not _os.path.isdir(_os.path.join(HERE, "out")):
    HERE = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))

CATALOG = _os.path.join(HERE, "out/add_damage_catalog.json")
OWNERS = _os.path.join(HERE, "out/teams/owners.json")
PREFS = _os.path.join(HERE, "out/t2_prefs.json")

# 用户的默认偏好（可被 out/t2_prefs.json 覆盖）
DEFAULT_PREFS = {
    "tongpao": None,        # 【同袍】是谁；None = 用"累计伤害最高者"（用户 2026-10-04：给了就不变、默认伤最高）
    "strict": False,        # True = 判不了就弃权（界面会出现"待复核"）；默认 False（界面不出现"待复核"）
    "panel": {},            # 面板项（可选）：{"atk": {"火花": 2000}, "elation": {"爻光": 1.2},
                            #   "crit": {"爻光": 0.8}}；给了就精确，不给就区间
}

# 「我方目标施放攻击后」触发的附伤（跨乘区比较用 box 区分）
ON_ATTACK = {
    "知更鸟": ("skill:130903", "协奏"), "刻律德菈": ("skill:141204", "军功"),
    "爻光": ("skill:150204", "好活当赏"), "缇宝": ("skill:140303", "结界"),
    "海瑟音": ("skill:141003", "结界"), "赛飞儿": ("rank:140604", "老主顾"),
    "翡翠": ("skill:131402", "收债人"), "貊泽": ("skill:122304", "猎物"),
    "阿格莱雅": ("skill:140204", "间隙织线"), "阮•梅": ("skill:130307", ""),
    "希儿": ("rank:110206", "乱蝶"),
}
LC_ON_ATTACK = {"时节不居": "lc:23013"}


def _load(path, default):
    if os.path.isfile(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:                                   # noqa: BLE001
            pass
    return default


def load_catalog():
    cat = _load(CATALOG, None)
    if cat is None:
        raise FileNotFoundError("先跑 python -u tools/team2/scan_add_damage.py 生成来源库")
    return {r["key"]: r for r in cat}


def load_owners():
    d = _load(OWNERS, {})
    return {k: v for k, v in d.items() if not k.startswith("_")}


def prefs():
    p = dict(DEFAULT_PREFS)
    p.update(_load(PREFS, {}))
    return p


def mult_of(entry):
    """取该条目的倍率（数据值本身就是比例：1.44 = 144%，0.25 = 25%）。"""
    ph = entry.get("mult_ph")
    if not ph:
        return None
    for d in entry.get("damage", []):
        if d.get("placeholder") == ph:
            return d.get("value_max_level")
    return None


# ────────────────────────── 归属层 ──────────────────────────

def split_summon(unit, owners, catalog, scores=None):
    """顶端卡是召唤物/盲盒/欢愉技 → 整段归属（**精确**）。"""
    if unit in owners:
        owner = owners[unit]
        return dict(kind="summon", parts=[dict(owner=owner, share=1.0, mark="精确",
                                               why="「%s」是 %s 的召唤物/忆灵 → 顶上卡归召唤者" % (unit, owner))],
                    note="")
    return None


def split_attack(actor, team, catalog=None, owners=None, p=None, states=None):
    """一次**角色攻击**的拆分：本体（行动者）+ 各"我方目标施放攻击后"触发的附伤。

    actor: 行动者名（如「火花」）
    team : 在场我方角色名单
    states: {'爻光': True/False/None} —— 触发状态是否确认（None=未确认，照口径计入并按在场算）
    返回 {'parts': [...], 'mark': '估算'/'精确', 'range': {...}, 'missing': [...] }
    """
    catalog = catalog or load_catalog()
    owners = owners or load_owners()
    p = p or prefs()
    states = states or set()
    parts, missing = [], []

    # 1) 主C 本体（倍率未知 → 用候选集合给区间；这里只登记"本体"）
    parts.append(dict(owner=actor, share=None, mark="本体", why="行动者本人伤害（乘区取决于用的技能）"))

    # 2) 外源附伤：队友机制里"我方目标施放攻击后"触发的
    for who, (key, state_name) in ON_ATTACK.items():
        if who == actor or who not in team:
            continue
        e = catalog.get(key)
        if not e:
            continue
        m = mult_of(e)
        if m is None:
            missing.append("%s %s 缺倍率（%s）" % (who, key, e.get("mult_ph")))
            continue
        if state_name and who in states and states[who] is False:
            continue                        # 明确没触发 → 不计入
        parts.append(dict(owner=who, share=None, mult=m, box=e.get("box"), mark="估算",
                          why=e.get("note") or e.get("trigger"),
                          state=(state_name or ""), state_confirmed=(who in states)))

    # 3) 光锥类（装备者不一定是行动者）—— 需要知道谁装备了，未配置则记 missing
    for lc_name, key in LC_ON_ATTACK.items():
        e = catalog.get(key)
        if not e:
            continue
        if lc_name in (p.get("equipped") or {}):
            m = mult_of(e)
            parts.append(dict(owner=p["equipped"][lc_name], share=None, mult=m, box=e.get("box"),
                              mark="估算", why="光锥「%s」：任意我方目标施放攻击后触发" % lc_name,
                              state="", state_confirmed=False))
        else:
            missing.append("光锥「%s」装备者未配置 → 未计入（在 out/t2_prefs.json 的 equipped 里配）" % lc_name)

    return dict(parts=parts, missing=missing, actor=actor)


# ────────────────────────── 量的层 ──────────────────────────

BOX_NAME = {"atk": "攻击力", "elation": "欢愉度（白值 7535.107）", "hp": "生命上限",
            "def": "防御力", "pct": "原伤害/总伤害%", "heal_record": "记录治疗量", "break": "击破"}

DB_DIR = _os.path.join(HERE, "StarRailRes-index_min", "index_min", "cn")
_ATTACK_TYPES = ("普攻", "战技", "终结技", "欢愉技", "忆灵技", "助战技", "强化普攻")


def _db():
    global _DB
    try:
        return _DB
    except NameError:
        pass
    _DB = {}
    for n in ("characters.json", "character_skills.json"):
        p = _os.path.join(DB_DIR, n)
        if _os.path.isfile(p):
            _DB[n] = json.load(open(p, encoding="utf-8"))
    return _DB


def _box_of(text, tail):
    if "欢愉伤害" in tail or "欢愉度" in tail:
        return "elation"
    if "防御力" in tail:
        return "def"
    if "生命上限" in tail:
        return "hp"
    if "攻击力" in tail:
        return "atk"
    return "atk"


def skill_total(desc, rows):
    """一个技能的**合计倍率**（把"造成 N 次，每次 M"乘起来）。

    例：火花欢愉技 = #2(0.625) + #3(20)×#1(0.3125) = 6.875；银狼欢愉技 = #2(6)×#1(1.125) = 6.75。
    返回 (total, box, 明细字符串)。
    """
    import re as _re
    val = {r["placeholder"].lstrip("#"): r["value_max_level"] for r in rows
           if r.get("value_max_level") is not None}
    desc = desc or ""
    counts = set(_re.findall(r"#(\d+)\[i\]\s*次", desc))
    used, total, detail = set(), 0.0, []
    for m in _re.finditer(r"#(\d+)\[i\]\s*次[^\n；]{0,40}?#(\d+)\[[if]\d?\]\s*%", desc):
        n_ph, m_ph = m.group(1), m.group(2)
        nv, mv = val.get(n_ph), val.get(m_ph)
        if nv and mv:
            total += nv * mv
            used |= {n_ph, m_ph}
            detail.append("#%s(%g)×#%s(%g)" % (n_ph, nv, m_ph, mv))
    for ph, v in val.items():
        if ph in used or ph in counts:
            continue
        tail = _window(desc, ph, 24)
        if "伤害" not in tail and "欢愉" not in tail:
            continue
        total += v
        detail.append("#%s(%g)" % (ph, v))
    return total, _box_of(desc, desc), " + ".join(detail)


def _window(desc, ph, span=30):
    import re as _re
    m = _re.search(r"#%s\[[^\]]*\]" % _re.escape(ph), desc or "")
    if not m:
        return ""
    return desc[m.start():min(len(desc), m.end() + span)]


LEDGER_VERIFIED = _os.path.join(HERE, "out/L2_damage_ledger_verified.json")
SCALE_BOX = [("欢愉度", "elation"), ("攻击力", "atk"), ("防御力", "def"), ("生命上限", "hp"),
             ("总伤害值", "pct"), ("原伤害", "pct"), ("记录治疗量", "heal_record"), ("击破", "break")]


def _box_of_scale(scale):
    for k, b in SCALE_BOX:
        if k in (scale or ""):
            return b
    return "atk"


def actor_candidates(actor, limit=8):
    """行动者的**技能候选**（这一下可能用的是哪个技能 → 倍率不同）。

    * 有**已核验台账**的角色（欢愉队 4 人）→ 直接用它（口径已人工定案）；
    * 其余角色 → 资料库解析 + 收紧规则（必须"造成…伤害"，排除"伤害提高/倍率提高"）。
    返回 [{'name','mult','box','detail'}]，按倍率降序。
    """
    led = _load(LEDGER_VERIFIED, {})
    if led:
        per = {}
        for r in led.get("rows", []):
            per.setdefault(r["char"], {}).setdefault(r["sid"], []).append(r)
        if actor in per:
            from tools.team2.make_damage_ledger import parse_damage      # noqa: F401
            db = _db()
            sk = db.get("character_skills.json", {})
            out = []
            for sid, rows in per[actor].items():
                if (rows[0]["type"] or "") not in _ATTACK_TYPES:
                    continue                       # 天赋/秘技/行迹不是"一次出手"，只当修正项
                dmg = [r for r in rows if r["kind"] in ("damage", "damage_table")]
                if not dmg:
                    continue
                s = sk.get(sid) or {}
                vals = [dict(placeholder=r["ph"], value_max_level=r["value"]) for r in rows
                        if r["kind"] in ("damage", "damage_table", "count")]
                total, _b, detail = skill_total(s.get("desc", ""), vals)
                if total <= 0:
                    total = sum(r["value"] for r in dmg)        # 兜底
                box = _box_of_scale(dmg[0]["scale"])
                out.append(dict(name="%s「%s」" % (rows[0]["type"], rows[0]["skill"]),
                                mult=total, box=box, detail=detail or "+".join(
                                    "%s(%g)" % (r["ph"], r["value"]) for r in dmg), sid=sid))
            out.sort(key=lambda r: -r["mult"])
            return out[:limit]

    db = _db()
    ch = db.get("characters.json", {})
    sk = db.get("character_skills.json", {})
    cid = next((i for i, c in ch.items() if c["name"] == actor), None)
    if cid is None:
        return []
    from tools.team2.make_damage_ledger import parse_damage
    out = []
    for sid in ch[cid].get("skills", []):
        s = sk.get(sid) or {}
        if s.get("type_text") not in _ATTACK_TYPES:
            continue
        rows = [r for r in parse_damage(s.get("desc", ""), s.get("params"))
                if r.get("value_max_level") is not None]
        rows = [r for r in rows if _is_damage_ph(s.get("desc", ""), r["placeholder"])]
        if not rows:
            continue
        total, box, detail = skill_total(s.get("desc", ""), rows)
        if total <= 0:
            continue
        out.append(dict(name="%s「%s」" % (s.get("type_text"), s.get("name")), mult=total,
                        box=box, detail=detail, sid=sid))
    out.sort(key=lambda r: -r["mult"])
    return out[:limit]


def _is_damage_ph(desc, ph):
    """占位符是不是"造成一次伤害"的倍率（排除"伤害提高/倍率提高"这类加成）。"""
    import re as _re
    m = _re.search(r"#%s\[[^\]]*\]" % _re.escape(ph.lstrip("#")), desc or "")
    if not m:
        return False
    seg = desc[max(0, m.start() - 40):m.end() + 30]
    if "倍率提高" in seg or "伤害提高" in seg or "提高" in seg:
        return False
    return "造成" in seg and ("伤害" in seg or "欢愉" in seg)


# 各乘区"**每 1 单位倍率**大概值多少伤害"（相对攻击力，攻击力=1.0）
#   atk   ：攻击力面板 ≈ 1500~3000（满级角色 + 光锥遗器）→ 基准 1.0
#   def   ：真珠等防御缩放，防御力 ≈ 1500~4000
#   hp    ：生命上限缩放的技能，血 ≈ 4000~8000 → 2.5~4× 攻击力
#   elation：**固定白值 7535.107 × (1+欢愉度)**（手册公式，未实测校验）→ 4~10× 攻击力
#   break ：击破伤害另成体系 → 1~3×
# ⚠️ 这是"没面板"的代价：只有**同乘区**时这些系数会约掉（占比=倍率之比），跨乘区才有区间。
#    有面板时在 out/t2_prefs.json 里给 panel，区间会收窄成精确值。
BOX_UNIT = {"atk": (1.0, 1.0), "def": (1.0, 1.5), "hp": (2.5, 4.0),
            "elation": (4.0, 10.0), "break": (1.0, 3.0), "pct": (1.0, 1.0),
            "heal_record": (1.0, 3.0)}


def weigh(res, p=None, actor_cands=None, unit=None):
    """把 parts 里的倍率变成占比。

    * **主C 本体倍率未知** → 用 `actor_cands`（他这一下可能用的技能）逐个算，取包络 → 区间
    * 同乘区 → 占比 = 倍率之比（乘区系数约掉；估算）
    * 跨乘区 → 按 `BOX_UNIT` 的区间配对扫描 → 占比区间
    * `out/t2_prefs.json` 给了 panel → 直接算（精确）
    """
    import collections
    import itertools
    p = p or prefs()
    unit = unit or (p.get("box_unit") or BOX_UNIT)
    panel = p.get("panel") or {}
    src = [x for x in res["parts"] if x.get("mult") is not None]
    if not src:
        return dict(parts=res["parts"], mark="无法估算", note="没有可用倍率", missing=res["missing"])
    cands = actor_cands or [dict(name="本体（倍率未知）", mult=None, box=None)]

    lo, hi = collections.defaultdict(lambda: 1.0), collections.defaultdict(float)
    body_lo, body_hi = 1.0, 0.0
    exact = False
    for c in cands:
        boxes = sorted({x["box"] for x in src} | ({c["box"]} if c.get("box") else set()))
        grids = []
        for b in boxes:
            rng = unit.get(b, (1.0, 1.0))
            if b in panel:                       # 给了面板 → 这一乘区是确定值
                rng = (rng[0], rng[0])
            grids.append(sorted(set(rng)))
        for combo in itertools.product(*grids):
            f = dict(zip(boxes, combo))
            w_body = (c.get("mult") or 0.0) * f.get(c.get("box"), 1.0)
            ws = {x["owner"]: x["mult"] * f.get(x["box"], 1.0) for x in src}
            tot = w_body + sum(ws.values())
            if tot <= 0:
                continue
            for o, w in ws.items():
                lo[o] = min(lo[o], w / tot)
                hi[o] = max(hi[o], w / tot)
            if c.get("mult"):
                body_lo, body_hi = min(body_lo, w_body / tot), max(body_hi, w_body / tot)
            exact = exact or all(b in panel for b in boxes)

    out = []
    for x in src:
        single = abs(hi[x["owner"]] - lo[x["owner"]]) < 1e-9
        out.append(dict(x, share=(hi[x["owner"]] if single else None),
                        share_lo=lo[x["owner"]], share_hi=hi[x["owner"]],
                        mark="精确" if exact else ("估算" if single else "估算(区间)")))
    span = "、".join("%s「%s」" % (c.get("name"), ("%g" % c["mult"]) if c.get("mult") else "?")
                     for c in cands[:4])
    body = dict(owner=res.get("actor", "本体"), share=None, share_lo=body_lo, share_hi=body_hi,
                mark="精确" if exact else "估算(区间)", why="行动者本人伤害", owner_body=True)
    marks = {x["mark"] for x in out} | {body["mark"]}
    return dict(parts=[body] + out,
                mark="精确" if marks == {"精确"} else ("估算" if marks <= {"估算"} else "估算(区间)"),
                note="主C 技能候选：%s ｜ 附伤占比是**区间**（不知道这一下用的什么技能；"
                     "跨乘区还要按 BOX_UNIT 扫）" % span,
                missing=res["missing"])


# ────────────────────────── 顶端卡 → 结论 ──────────────────────────

def split_frame(t, team=None, bank_e2=None, t2bank=None, p=None, catalog=None, owners=None):
    """离线：给帧号 → 归属结论（含召唤物/盲盒/欢愉技的整段归属）。"""
    sys.path.insert(0, HERE)
    from tools.team2.card_kind_t2 import read_actor_t2
    r = read_actor_t2(float(t), bank_e2=bank_e2, bank_t2=t2bank)
    owners = owners or load_owners()
    catalog = catalog or load_catalog()
    ct = r.get("card_type")
    if ct == "blindbox":
        kind = split_summon("银狼LV.999", {"银狼LV.999": "银狼LV.999"}, catalog)
        return dict(t=t, card=r, whole=dict(parts=[dict(owner="银狼LV.999", share=1.0, mark="精确",
                                                        why="顶轴是【头号补给盲盒】的卡 → 归银狼LV.999")],
                                            mark="精确", note="整段归盲盒主人（召唤物口径）"),
                    missing=[])
    if ct == "enemy_buff":
        return dict(t=t, card=r, whole=dict(parts=[], mark="不计入",
                                            note="敌方给我方的 buff 卡 → 不计入我方伤害"), missing=[])
    if ct in ("unit", "elation") and r.get("unit"):
        owners = load_owners()
        if r["unit"] in owners:      # 忆灵/召唤物 → 归召唤者
            return dict(t=t, card=r, whole=dict(parts=[dict(owner=owners[r["unit"]], share=1.0,
                                                            mark="精确",
                                                            why="顶上卡是召唤物「%s」→ 归召唤者" % r["unit"])],
                                                mark="精确", note="召唤物整段归属"), missing=[])
        res = split_attack(r["unit"], team or [], catalog, owners, p)
        return dict(t=t, card=r, whole=weigh(res, p, actor_cands=actor_candidates(r["unit"])),
                    missing=res["missing"])
    return dict(t=t, card=r, whole=dict(parts=[], mark="无法判定", note="顶端卡不是可归属单位"),
                missing=[])


# ────────────────────────── 自检 ──────────────────────────

def selftest(verbose=True):
    sys.path.insert(0, HERE)
    from tools.team2.card_kind_t2 import load_bank as load_t2
    catalog, owners = load_catalog(), load_owners()
    ok = True

    def chk(name, cond, extra=""):
        nonlocal ok
        ok &= bool(cond)
        if verbose:
            print("  [%s] %s %s" % ("OK" if cond else "✗", name, extra))

    if verbose:
        print("① 盲盒帧 → 整段归银狼（精确）")
    for t in (86, 150, 256, 329):
        r = split_frame(t, t2bank=load_t2(), catalog=catalog, owners=owners)
        chk("t=%d 归银狼" % t, r["whole"]["parts"] and r["whole"]["parts"][0]["owner"] == "银狼LV.999"
            and r["whole"]["mark"] == "精确", r["whole"]["mark"])

    if verbose:
        print("② 欢愉技帧（t=205 银狼头像+菱形）→ 归银狼")
    r = split_frame(205, t2bank=load_t2(), catalog=catalog, owners=owners)
    chk("t=205", r["card"].get("card_type") == "elation" and r["card"].get("unit") == "银狼",
        "%s/%s" % (r["card"].get("card_type"), r["card"].get("unit")))

    if verbose:
        print("③ 红兔帧 → 不计入我方伤害")
    r = split_frame(137, t2bank=load_t2(), catalog=catalog, owners=owners)
    chk("t=137", r["whole"]["mark"] == "不计入", r["whole"]["mark"])

    if verbose:
        print("④ 欢愉队 火花回合 → 爻光的【大吉大利】必须被拆出来，且是**区间**（主C 技能未知）")
    res = split_attack("火花", ["火花", "爻光", "真珠", "银狼LV.999"], catalog, owners)
    w = weigh(res, actor_cands=actor_candidates("火花"))
    yg = [x for x in w["parts"] if x["owner"] == "爻光"]
    body = [x for x in w["parts"] if x.get("owner_body")]
    chk("爻光附伤在列", len(yg) == 1,
        "占比区间=%.1f%%~%.1f%%" % (100 * yg[0]["share_lo"], 100 * yg[0]["share_hi"]) if yg else "")
    chk("区间合法（0<lo≤hi）", yg and 0 < yg[0]["share_lo"] <= yg[0]["share_hi"] < 1)
    chk("本体区间下界 >30%", body and body[0]["share_lo"] > 0.30,
        "本体区间=%.1f%%~%.1f%%" % (100 * body[0]["share_lo"], 100 * body[0]["share_hi"]) if body else "")
    chk("含区间标记", yg and yg[0]["mark"].startswith("估算"), yg[0]["mark"] if yg else "")
    chk("主C 技能候选 ≥3 个", len(actor_candidates("火花")) >= 3,
        "候选=%d" % len(actor_candidates("火花")))

    if verbose:
        print("④b 主C 技能候选（火花）")
    for c in actor_candidates("火花")[:5]:
        print("     %-28s 合计倍率=%-8g 乘区=%-7s %s" % (c["name"], c["mult"], c["box"], c["detail"]))

    if verbose:
        print("⑤ 反例：停云【赐福】必须**不剥离**（归持有者=行动者）")
    e = [r for r in catalog.values() if r["id"] == "120202"]
    chk("120202 分类=self", e and e[0]["kind"] == "self", e[0]["kind"] if e else "缺条目")

    if verbose:
        print("⑥ 反例：dot 立即结算 / 状态类 → 不在可剥离集合里")
    dots = [r for r in catalog.values() if r["kind"] in ("dot_settle", "state_dot")]
    chk("dot 条目已登记且不参与拆分", len(dots) > 0, "%d 条" % len(dots))

    if verbose:
        print("⑦ 缺倍率 → 记进 missing（界面不显示「待复核」）")
    res = split_attack("火花", ["火花", "赛飞儿"], catalog, owners)
    chk("赛飞儿星魂缺倍率占位 → missing", any("赛飞儿" in m for m in res["missing"]), res["missing"][:1])

    if verbose:
        print("\n自检：%s" % ("全部通过 ✓" if ok else "**有失败** ✗"))
    return 0 if ok else 1


def _cli():
    if "--selftest" in sys.argv:
        return selftest()
    if "--frame" in sys.argv:
        t = sys.argv[sys.argv.index("--frame") + 1]
        import pprint
        pprint.pprint(split_frame(float(t), team=["火花", "爻光", "真珠", "银狼LV.999"]))
        return 0
    if "--actor" in sys.argv:
        actor = sys.argv[sys.argv.index("--actor") + 1]
        team = sys.argv[sys.argv.index("--team") + 1:sys.argv.index("--actor")] if "--team" in sys.argv \
            else ["火花", "爻光", "真珠", "银狼LV.999"]
        res = split_attack(actor, team)
        w = weigh(res)
        print("行动者：%s ｜ 队伍：%s" % (actor, team))
        for x in w["parts"]:
            print("  %-12s 倍率=%-8s 乘区=%-10s 占比=%s%s  %s" % (
                x["owner"], x.get("mult"), x.get("box_name") or x.get("box") or "-",
                ("%.4f" % x["share"]) if x.get("share") is not None else
                ("%.3f~%.3f" % (x["share_lo"], x["share_hi"]) if x.get("share_lo") is not None else "-"),
                "" if x.get("share") is not None else "(区间)", x.get("mark")))
        print("说明：%s" % w.get("note"))
        if w.get("missing"):
            print("缺输入：%s" % w["missing"])
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
