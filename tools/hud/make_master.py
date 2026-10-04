# -*- coding: utf-8 -*-
"""
[线4] 合唯一主表 —— 把「线4 的密帧事件表」+「线6 的外推列」合成**一张权威表**，
并给旧表打「已被取代」标注。这是《剩余工作清单.md》【线4】尾巴 1/3 与
《剩余工作清单.md》【线8】item 3/4 的落地。

════════════════════════════════════════════════════════════════════════
一、为什么要合、以谁为准
════════════════════════════════════════════════════════════════════════
现在桌面上有 5 张事件表，下游（线5 悬浮窗）只能读一张：

| 文件 | 段数 | 分辨率 | 状态 |
|---|---|---|---|
| `out/events_C.csv` | 54 | 1 fps | ❌ **已被取代**：9 段的峰值读数是丢位碎片（假事件），
|                   |     |       |    其中 6 段 `status=ok`，会污染汇总 |
| `out/events_dense_C.csv` | — | 0.2s | ❌ 反面证据：**修扫描器之前**的产物，别再引用 |
| `out/events_dense4.csv` | 42 | 0.2s | 线4 引擎的原始输出（**会被重跑覆盖**，不含线6 列）|
| `out/events_dense4_L6.csv` | 42 | 0.2s | 线6 的并表底稿（本表的上一道工序）|
| `out/events_C_L6.csv` | 54 | 1 fps | 线6 给旧表并的列（保留供线6 复现）|
| **`out/events_master.csv`** | **42** | **0.2s** | ⭐ **唯一主表**（本脚本产出）|

**以线4 的 42 段为准的实测依据**：
  · C 的 54 段**全部**能在主表里找到落点（`account_4.py` 硬检查 1：未覆盖 0）；
  · C 有 **9 段**的峰值读数是丢位碎片（假事件）→ 主表把它们并回同一次攻击；
  · 主表修正了 **2 段**被截断的最大值（`721193→1,116,982`、`409984→954,671`）；
  · 主表**多出 7 段** C 在 1 fps 上完全看不到的攻击（如 `t=161.6` 的 `248,152`）；
  · 主表在密帧窗口内是 **0.2s** 分辨率，窗口外仍是 1 fps（覆盖与 C 相同，不会更差）。

════════════════════════════════════════════════════════════════════════
二、外推列的口径（⚠️ 本脚本最重要的一条约定）
════════════════════════════════════════════════════════════════════════
线6 的列（`l6_*`）是**外推**：行动轴被特效遮住时，按"前后锚点"推出来的归属。
它和主表里的实测归属**不是一回事**，所以：

  · **实测优先**：基表已有 `owner` 时一律用基表，`attrib_src=read`。
    实测依据：线6 自己在 `docs/行动轴覆盖率外推.md` §6.1 记了
    `e35`（`actor_t=284.2`）——基表读**风堇**（=小伊卡卡面，人工核对过，对），
    线6 外推成**长夜月**（tier B，错）。
  · 基表没有 `owner` 时，才允许用线6 的 tier A（`attrib_src=extrap`）。
  · **tier B 一律不采**（回测 46.4% / 人工 3/6，线6 已定案）；tier C 默认不采，
    要采需显式 `--tier-policy A,C`。
  · 于是主表新增这些列，让下游**不必自己拼**：
      `attrib_owner`    该行实际该用的归属（实测或已采纳的外推）
      `attrib_src`      `read`（实测）/ `extrap`（外推）/ 空
      `attrib_tier`     `read` / `A` / `B` / `C` / 空
      `attrib_adopted`  按当前策略是否采纳（1/0）
      `count_measured`  **严格口径**能否进合计：`status=ok` 且归属是实测
      `count_adopted`   推荐口径能否进合计：归属已采纳（read 或 tier A）且非敌非空
    `count_measured` 的值与 C 线 `events.summarize` 的口径等价，可直接对照。

════════════════════════════════════════════════════════════════════════
三、给旧表打的标注（**不改任何原有数值**）
════════════════════════════════════════════════════════════════════════
`out/events_C.csv` 会增加三列（原有 25 列**逐字节保留**，本脚本写回后会自校验）：
  `master_event`  这一段被主表的哪一段吸收（`-` = 没有对应）
  `master_note`   `keep` / `fragment`（峰值读数是丢位碎片）/ `merged`（并进同一次攻击）
  `superseded_by` 固定 `out/events_master.csv`
⚠️ 这两张表都会被各自的引擎重跑覆盖，所以**改完上游请重跑本脚本**恢复标注。

用法：
  python -u make_master_4.py                 # 生成主表 + 标注旧表 + 自校验 + 打印账目
  python -u make_master_4.py --tier-policy A,C   # 也采纳 tier C（低可信，会写进 attrib_* ）
  python -u make_master_4.py --check          # 只校验现有主表与旧表标注，不写文件
"""
# [P3 整理] 原路径：make_master_4.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import argparse
import csv
import os
import sys

_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
sys.path.insert(0, HERE)

BASE = os.path.join(HERE, "out/events_dense4_L6.csv")    # 线4 段 + 线6 列（合表底稿）
C_TABLE = os.path.join(HERE, "out/events_C.csv")         # 旧的 1 fps 表（要打标注）
MASTER = os.path.join(HERE, "out/events_master.csv")     # ⭐ 产出

SCHEMA = "events_master/1.0"
MASTER_COLS = ["schema", "source_table", "supersedes", "c_damage_max",
               "attrib_owner", "attrib_src", "attrib_tier", "attrib_adopted",
               "count_measured", "count_adopted"]
C_ANNOT_COLS = ["master_event", "master_note", "superseded_by"]


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        return list(r.fieldnames), list(r)


def rejected_ints(master_row):
    """主表 `rejected` 列里被剔除的读数（数值集合）。

    条目形如 `158=0408[frag:sub 0408⊂210408@157]` —— `=` 后面是原始读数文本（可能带前导 0）。
    ⚠️ 必须**按数值**比，不能按字符串比：`408` 在表里写作 `0408`，
    早期版本用 `"=408["` 去匹配，于是漏掉了 C 线 #12（`408`）这一条。
    """
    out = set()
    for item in (master_row.get("rejected") or "").split("; "):
        if "=" not in item:
            continue
        txt = item.split("=", 1)[1].split("[", 1)[0].strip()
        if txt.isdigit():
            out.add(int(txt))
    return out


def strip_annot(c_cols, c_rows):
    """读旧表时把上次写的标注列摘掉，保证脚本**可重复运行**（幂等）。"""
    keep = [c for c in c_cols if c not in C_ANNOT_COLS]
    return keep, [{k: r.get(k, "") for k in keep} for r in c_rows]


def write_csv(path, cols, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})


def adopted(tier, policy):
    return tier in ("read",) or (tier in policy)


def build_master(base_cols, base_rows, c_rows, policy):
    """把线6 的 l6_* 解释成主表的 attrib_* / count_*。"""
    cpeaks = [(r["event"], float(r["t_peak"]), int(r["damage_max"])) for r in c_rows]
    out = []
    for r in base_rows:
        a, b = float(r["t_first"]), float(r["t_last"])
        hit = [c for c in cpeaks if a - 0.01 <= c[1] <= b + 0.01]
        tier_l6 = (r.get("l6_tier") or "").strip()
        base_owner = (r.get("owner") or "").strip()
        l6_owner = (r.get("l6_owner") or "").strip()
        l6_adopted = (r.get("l6_adopted") or "") == "1"

        if base_owner:                                   # ① 实测优先
            attrib_owner, src, tier = base_owner, "read", "read"
        elif l6_owner and l6_adopted and (tier_l6 in ("read",) or tier_l6 in policy):
            attrib_owner, src, tier = l6_owner, "extrap", (tier_l6 or "read")
        elif l6_owner and l6_adopted:
            attrib_owner, src, tier = l6_owner, "extrap", (tier_l6 or "A")
        else:
            attrib_owner, src, tier = "", "", ""

        ad = 1 if (attrib_owner and adopted(tier, policy)) else 0
        countable = bool(attrib_owner) and ad
        count_measured = 1 if (r.get("status") == "ok" and src == "read" and attrib_owner) else 0
        count_adopted = 1 if (countable and (r.get("status") == "ok" or src == "extrap")) else 0

        m = dict(r)
        m.update({
            "schema": SCHEMA,
            "source_table": "out/events_dense4_L6.csv",
            "supersedes": ";".join(c[0] for c in hit) or "-",
            "c_damage_max": ";".join(str(c[2]) for c in hit) or "-",
            "attrib_owner": attrib_owner,
            "attrib_src": src,
            "attrib_tier": tier,
            "attrib_adopted": ad,
            "count_measured": count_measured,
            "count_adopted": count_adopted,
        })
        out.append(m)
    return out, cpeaks


def annotate_c(c_cols, c_rows, master_rows):
    """给旧表加标注（原有列一个不动）。三类标注互斥：
       `fragment` 峰值读数被本引擎判为丢位碎片 → 这一段是**假事件**
       `merged`   不是碎片，但它的主表段吸收了 ≥2 个 C 段 → **被并进同一次攻击**
       `keep`     其余（逐段对应）
    """
    out = []
    for r in c_rows:
        t = float(r["t_peak"])
        hit = None
        for m in master_rows:
            if float(m["t_first"]) - 0.01 <= t <= float(m["t_last"]) + 0.01:
                hit = m
                break
        note = "-"
        if hit is not None:
            if int(r["damage_max"]) in rejected_ints(hit):
                note = "fragment"
            else:
                ids = [x for x in (hit.get("supersedes") or "-").split(";") if x != "-"]
                note = "merged" if len(ids) > 1 else "keep"
        a = dict(r)
        a["master_event"] = hit["event"] if hit is not None else "-"
        a["master_note"] = note
        a["superseded_by"] = "out/events_master.csv"
        out.append(a)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--c-table", default=C_TABLE)
    ap.add_argument("--out", default=MASTER)
    ap.add_argument("--tier-policy", default="A", help="采纳哪些外推档，如 A 或 A,C")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    policy = tuple(x.strip().upper() for x in args.tier_policy.split(",") if x.strip())

    bcols, brows = read_csv(args.base)
    ccols_raw, crows_raw = read_csv(args.c_table)
    ccols, crows = strip_annot(ccols_raw, crows_raw)
    master, cpeaks = build_master(bcols, brows, crows, policy)

    if args.check:
        mcols, mrows = read_csv(args.out)
        cc2, cr2 = read_csv(args.c_table)
        have = [c for c in cc2 if c in C_ANNOT_COLS]
        print("主表 %s：%d 行 / %d 列；schema=%s" % (args.out, len(mrows), len(mcols),
                                                mrows[0].get("schema")))
        print("旧表 %s：%d 行 / %d 列（标注列 %s）"
              % (args.c_table, len(cr2), len(cc2), have))
        ok = True
        if mcols != bcols + MASTER_COLS:
            print("  ⚠️ 主表列与预期不符（可能上游变了，请重跑本脚本）"); ok = False
        if have != C_ANNOT_COLS:
            print("  ⚠️ 旧表标注列缺失 —— ⚠️ `events.py` **任何**运行（含 `--anchors`）"
                  "都会无条件重写 `out/events_C.csv` 从而冲掉标注。请重跑本脚本恢复。"); ok = False
        print("  结构检查：%s" % ("通过 ✓" if ok else "**未通过**（重跑 `python -u make_master_4.py`）"))
        return 0 if ok else 1

    # ── 写主表 ──
    write_csv(args.out, bcols + MASTER_COLS, master)
    # ── 写回旧表（加标注）——先自校验"原有列逐格未变" ──
    nuevo = annotate_c(ccols, crows, master)
    for old, new in zip(crows, nuevo):
        for k in ccols:
            assert old[k] == new[k], "旧表原有列被改动：event=%s 列=%s" % (old["event"], k)
    write_csv(args.c_table, ccols + C_ANNOT_COLS, nuevo)
    # ── 复核 ──
    mcols2, mrows2 = read_csv(args.out)
    assert len(mrows2) == len(brows) and mcols2 == bcols + MASTER_COLS, "主表结构不符"
    cc3, cr3 = read_csv(args.c_table)
    assert cc3 == ccols + C_ANNOT_COLS and len(cr3) == len(crows), "旧表标注列没写对"

    # ── 打印账目 ──
    print("⭐ 已写出主表 %s（%d 段 / %d 列）" % (args.out, len(master), len(mcols2)))
    print("   已给旧表 %s 加标注列 %s（原有 %d 列逐格未变，已 assert 校验）"
          % (args.c_table, C_ANNOT_COLS, len(ccols)))
    tot_m = sum(int(r["damage_max"]) for r in master if r["count_measured"] == 1)
    tot_a = sum(int(r["damage_max"]) for r in master if r["count_adopted"] == 1)
    print("   采纳策略 tier=%s" % (",".join(policy),))
    print("   count_measured=1 的段：%d 段，合计 %s（口径等价于 C 线 summarize）"
          % (sum(1 for r in master if r["count_measured"] == 1), format(tot_m, ",")))
    print("   count_adopted =1 的段：%d 段，合计 %s（多出来的是 tier A 外推补的空）"
          % (sum(1 for r in master if r["count_adopted"] == 1), format(tot_a, ",")))
    from collections import Counter
    print("   attrib_src 分布:", dict(Counter(r["attrib_src"] or "(空)" for r in master)))
    print("   attrib_tier 分布:", dict(Counter(r["attrib_tier"] or "(空)" for r in master)))
    print("   旧表标注分布:", dict(Counter(r["master_note"] for r in nuevo)))
    frag = [r["event"] for r in nuevo if r["master_note"] == "fragment"]
    print("   ⚠️ 旧表被判为「碎片假事件」的段：%s（数值未改动，只加标注）" % (frag or "无"))
    # 与 account_4.py 对齐的账目：被并掉的"多出来"的 C 段数
    groups = {}
    for r in nuevo:
        if r["master_event"] != "-":
            groups.setdefault(r["master_event"], []).append(r["event"])
    multi = {k: v for k, v in groups.items() if len(v) > 1}
    print("   C 的 %d 段落在主表 %d 段里；其中 %d 组共段、净减 %d 段（= %d − %d 组）"
          % (len(crows), len(groups), len(multi), sum(len(v) - 1 for v in multi.values()),
             sum(len(v) for v in multi.values()), len(multi)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
