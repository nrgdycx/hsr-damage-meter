# `out/` 里的事件表：哪张是主表（2026-10-01 定案，线4）

> 这里放过 5 张事件表，下游（线5 悬浮窗 / 统计）**只能读一张**。
> 本文件说明它们的来历与权威性。生成/恢复：`python -u make_master_4.py`（幂等）。

---

## ⭐ 唯一主表：`events_master.csv`

**42 段 / 边界分辨率 0.2s**。列 = 三段拼起来（共 56 列）：

| 来源 | 列 |
|---|---|
| 线4 事件表（34 列） | `event` `t_first` `t_last` `t_peak` `t_anchor` `duration` `damage_first/final/max` `n_readings` `unit` `owner` `owner_start` `n_owners` `owner_breaks` `card_type` `inserted` `actor_*` `min_conf` `status` `quality` `issues` `readings` `t_res` `n_frames` `n_trusted` `n_rejected` `n_frag` `reject_kinds` `rejected` `t_trusted_span` `pairs` `split_candidates` |
| 线6 外推列（12 列，前缀 `l6_`） | `l6_t` `l6_dt` `l6_verdict` `l6_source` `l6_tier` `l6_owner` `l6_age` `l6_alt_owner` `l6_adopted` `l6_adopted_loose` `l6_agrees` `l6_fills` |
| 主表列（10 列） | `schema` `source_table` `supersedes` `c_damage_max` `attrib_owner` `attrib_src` `attrib_tier` `attrib_adopted` `count_measured` `count_adopted` |

### 该用哪一列

| 你要什么 | 用哪一列 |
|---|---|
| **这次攻击是谁打的**（唯一推荐入口）| **`attrib_owner`** —— 实测优先，缺失时才用线6 的 tier A 外推 |
| 这个归属是实测还是推的 | `attrib_src` = `read` / `extrap` / 空；`attrib_tier` = `read` / `A` / `B` / `C` |
| **能不能进合计（严格）** | **`count_measured == 1`** —— 口径与 C 线 `events.summarize` 等价：33 段 / **11,115,871** |
| **能不能进合计（含 tier A 外推）** | **`count_adopted == 1`** —— 34 段 / **11,340,930**（多的是 `t=245.2` 那次靠 tier A 补的 `昔涟`/225,059）|
| 这一行取代了旧表的哪几段 | `supersedes`（`;` 分隔的 `events_C.csv` 事件号）、`c_damage_max`（被取代的旧值）|

⚠️ **不要**自己拿 `status` + `owner` + `l6_*` 拼口径 —— 那就是本表 `attrib_*`/`count_*` 干的事，
拼错会把外推值当实测值算进合计。

---

## 其余四张表（都被取代，但都有用）

| 文件 | 段数 | 用途 / ⚠️ |
|---|---|---|
| `events_C.csv` | 54 | **1 fps 基线 + 历史对照**。⚠️ **已被取代**：54 段里 **9 段的峰值读数是丢位碎片**（假事件，其中 6 段原本 `status=ok`）、2 段最大值被截断压低。已加三列标注：`master_event`（被主表哪一段吸收）、`master_note`（`keep` 26 / `merged` 19 / `fragment` 9）、`superseded_by`。**数值一字未改** |
| `events_dense_C.csv` | — | ⛔ **反面证据**：**修扫描器之前**的密帧事件表。里面那句 `8324751` 就是它。**别当数据源** |
| `frames_dense_C.csv` | — | ⛔ 同上（旧口径密帧逐帧表）。**当前口径是 `frames_dense4.csv`**（与 1 fps 表共同整数秒帧 **240/240 完全相同**）|
| `events_dense4.csv` | 42 | 线4 引擎的**原始输出**（`events_v4.py` 重跑会覆盖它，且不含 `l6_*` 列）。要权威版请用 `events_master.csv` |
| `events_dense4_L6.csv` | 42 | 线6 的**并表底稿**（= 主表减去 10 个主表列）。主表的直接输入 |
| `events_C_L6.csv` | 54 | 线6 给旧表并的 `l6_*` 列（保留供线6 复现）|
| `axis_actors_L6.csv` | — | 线6 的**逐帧**行动者表（含 `state/source/tier/verdict/hold_age` 等），不是事件表 |

---

## 覆盖关系（为什么以线4 的 42 段为准）

```
C 的 54 段 ──全部有落点（未覆盖 0）──→ 落在主表 40 段里；13 组共段、净减 14 段
    其中  9 段 = 峰值读数是丢位碎片的「假事件」   → 并回同一次攻击
          6 段 = 密帧证据判为「同一次攻击」的合并（净减）
主表另有  7 段 = C 在 1 fps 网格上完全看不到的攻击（如 t=161.6 的 248,152）
主表修正  2 段 = 被截断压低的最大值（721,193→1,116,982、409,984→954,671）
密帧窗口内主表是 0.2s 分辨率；窗口外仍是 1 fps（覆盖不比 C 差）
```

复现账目：`python -u account_4.py`（逐组列出哪几段 C 被并进主表哪一段）。
完整证据链：`docs/归属与事件切分.md` §1~§7。

---

## ⚠️ 三张表会被引擎覆盖

| 谁 | 覆盖什么 | 后果 |
|---|---|---|
| `events.py`（**任何**运行，含 `--anchors`）| `events_C.csv` | ⚠️ **标注列会被冲掉**（`write_csv` 是无条件执行的 —— 本线在回归时实测踩过一次）|
| `events_v4.py` | `events_dense4.csv` | 主表列（`attrib_*` / `count_*`）本来就不在这张表里，主表本身不受影响 |
| `axis_coverage.py` | `events_dense4_L6.csv` | 需要重跑 `make_master_4.py` 才能刷新主表 |

所以改完上游后按这个顺序重跑，并用 `--check` 收尾：

```powershell
python -u events_v4.py --anchors --truth --compare --summary   # 重出 events_dense4.csv
python -u axis_coverage.py ...                                       # 重出 events_dense4_L6.csv（线6）
python -u make_master_4.py                                          # 重出主表 + 恢复旧表标注
python -u make_master_4.py --check                                  # 结构检查；缺标注列会**退出码 1** 并提示重跑
```
