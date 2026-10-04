# -*- coding: utf-8 -*-
"""[MVP] 感知层：一帧画面 → 一条读数（HUD 总伤害 + 行动轴顶端行动者）。

本模块**只做接口适配，不复制任何识别逻辑**（本项目铁律：识别只有一份实现）：
  * HUD 数字：整帧走 `hud_profiles.glyphs`（含线7 动态定位，与离线扫描
    `scan_C2.py` **同一条代码路径**）；已裁好的区域走 `hud_profiles.glyphs_cropped`
    （实时抓屏用这条，省一次全屏裁切）。
    分类器两种后端：
      - `onnx`  ：`out/digit_cnn.onnx`（实时默认，0.1ms/字形，不加载 torch）
      - `torch` ：`read_hud.load_model()`（离线/对账用）
    ⚠️ 两条后端的等价性由 `hud_digits.check_model_freshness` 的探针保证
      （`out/digit_cnn.probe.npz`：argmax 必须全一致）；`mvp/probe_hud_path.py` 另做逐帧实测。
  * 行动者：`axis_actor.read_actor`（两道闸：分数 ≥0.90 且与第二名分差 ≥0.45，否则 `unit=None`）。
    判不出来就是**待复核**，绝不猜 —— 见 MVP 验收第 5 条。

产出的一条读数（row）字段与 `events_v4.load()` 读 CSV 后的结构**逐字段一致**，
这样流式引擎可以直接复用线4 的判据函数（口径不可能漂移）：
    t / text / n / conf / unit / owner / score / margin / marker / inserted / card_type / grade / reject
`grade` 与 `reject` 由 `events_v4.classify()` / `mark_rejects()` 填。
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, os.path.join(ROOT, "vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hud_glyphs as HG          # noqa: E402
import hud_profiles as HP        # noqa: E402
import axis_actor as T           # noqa: E402

# ⚠️ `read_hud` **故意不在这里 import**（打包专项 §3）：
#     read_hud.py 顶层 `import torch`（值 600MB~1GB），而实时默认后端是 `onnx`
#     （`out/digit_cnn.onnx`，0.1ms/字形，**不需要 torch**）。
#     顶层 import 会把 torch 顺带拖进 exe（800MB~1.5GB，且打包极慢）。
#     ⇒ 改成惰性：只在真的选 `backend='torch'`（离线/对账）时才 import。
#     两种后端的等价性由 `hud_digits.check_model_freshness` 的探针保证。

# 与 scan_C2.py 的 COLS 一致（对账时可以直接 diff 两张逐帧表）
ROW_COLS = ["t", "hud_text", "hud_n", "hud_len", "hud_lm", "hud_minconf", "hud_nbad",
            "hud_profile", "unit", "owner", "score", "margin", "marker", "inserted",
            "card_type"]

EMPTY_ACTOR = {"unit": "", "owner": "", "score": 0.0, "margin": 0.0,               "marker": "", "inserted": "", "card_type": ""}


def new_row(t):
    """一条空读数（字段与 events_v4.load 的结构一致）。"""
    return {"t": float(t), "text": "", "n": 0, "conf": 0.0,
            "unit": "", "owner": "", "score": 0.0, "margin": 0.0, "marker": "",
            "inserted": "", "card_type": "", "grade": "", "reject": "",
            "raw_unit": None, "lm": -1, "nbad": 0, "profile": "default",
            "ms": {}}


# T2：阿哈认脸的多帧投票参数
AHA_VOTE_WIN = 1.0      # 投票窗口（秒）—— 头像约 2.6s 换一次，1.0s 不会跨人
AHA_VOTE_MAX = 40       # 缓冲上限（约 1.3s @30fps）


class Perceiver:
    """帧 → 读数。线程不安全（内部复用同一个模型实例），单线程用。"""

    def __init__(self, profile="default", backend="onnx", conf_min=0.55,
                 check_fresh=True, actor_bank=None, span_guard=False):
        self.profile = profile
        self.backend = backend
        self.conf_min = float(conf_min)
        self.HP = HP
        # ⭐ P1 实机安全网（**默认关；实机主循环开**，见 `span_guard_hit`）：
        #    "切出来的字符合计宽度 远小于 画面里黄墨迹的跨度" → 这一帧的读数不可信。
        #    为什么不给离线/回放开：回放要与权威表 `frames_dense4.csv` **逐帧一致**（已对账 923 帧），
        #    加这道闸会改动其中约 105 帧的读数（那些帧本来就是"丢前导位"的坏读数）。
        #    实机则相反 —— 宁可漏，也不要让"看着像数"的错值进入统计。
        self.span_guard = bool(span_guard)
        # T2：阿哈时刻"框里是谁"的**多帧投票**缓冲（单帧认脸不稳，实时 30fps 下投票很划算）
        self._aha_hist = []          # [(t, member)]
        self._aha_last_t = None
        if backend == "onnx":
            from hud_digits import HudOnnxReader
            self._onnx = HudOnnxReader(conf_min=self.conf_min, check_fresh=check_fresh)
            self._model = None
        elif backend == "torch":
            import read_hud          # 惰性：只有离线/对账后端才需要（这一步会拉起 torch）
            self._onnx = None
            self._model = read_hud.load_model(profile)
        else:
            raise ValueError("backend 只能是 onnx / torch，收到 %r" % backend)
        self.bank = actor_bank if actor_bank is not None else T.load_bank()

    # ────────────────────────── HUD ──────────────────────────
    def _classify_glyphs(self, gs):
        """字形 → (读数串, 最低置信度, 字形数, 坏字形数)。几何守门与离线同口径。"""
        if not gs:
            return "", 0.0, 0, 0
        if self._onnx is not None:
            res = self._onnx.classify(gs)
        else:
            import torch
            x = torch.tensor(np.stack([v for v, _, _ in gs])[:, None], dtype=torch.float32)
            with torch.no_grad():
                p = torch.softmax(self._model(x), 1)
            cf, pd = p.max(1)
            res = [(int(d), float(c)) for d, c in zip(pd.tolist(), cf.tolist())]
        chars, mins, nbad = [], 1.0, 0
        for (v, w, h), (d, c) in zip(gs, res):
            ok, _ = self.HP.geom_ok(self.profile, w, h)
            bad = (not ok) or c < self.conf_min
            chars.append("?" if bad else str(d))
            mins = min(mins, c)
            nbad += 1 if bad else 0
        return "".join(chars), mins, len(res), nbad

    def read_hud_frame(self, frame_rgb):
        """整帧（RGB, int16/uint8）→ HUD 读数。走**动态定位**，与离线扫描同口径。"""
        gs = self.HP.glyphs(self.profile, frame_rgb)
        return self._classify_glyphs(gs)

    def read_hud_region(self, region_rgb, top, left, bar_rows=None):
        """已裁好的 HUD 区域（RGB）→ (读数串, 最低置信, 字形数, 坏字形数, 可疑原值)。

        `span_guard=True` 时多一道"段宽/墨迹跨度"闸（见模块级 `span_guard_hit`）：
        命中就**不把那个值交出去**（返回 `'?'*n`），原值放在第 5 个返回值里供诊断。
        """
        gs = self.HP.glyphs_cropped(self.profile, region_rgb, top, left, bar_rows=bar_rows)
        text, conf, n, nbad = self._classify_glyphs(gs)
        if self.span_guard and text and span_guard_hit(region_rgb, gs):
            return "?" * max(1, n), conf, n, max(1, nbad), text
        return text, conf, n, nbad, ""

    def hud_leftmost(self, region_rgb, top, left):
        """最左列段的绝对 x（**证据列**，不参与判定；口径同 scan_C2.glyph_leftmost）。

        ⚠️ scan_C2 用的是参考标定框 (2350,260)-(2876,340)，这里照抄同一口径，
        这样两边的 `hud_lm` 列才可比。
        """
        y0, x0, y1, x1 = HG.CY0, HG.CX0, HG.CY1, HG.CX1
        if top != y0 or left != x0:
            return -1
        a = np.asarray(region_rgb, dtype=np.int16)
        m_seg, _, _ = HG._masks(a, "glow")
        ms = m_seg.copy()
        r0, r1 = max(0, HG.BAR_ROWS[0] - y0), min(ms.shape[0] - 1, HG.BAR_ROWS[1] - y0)
        ms[r0:r1 + 1, :] = False
        col = ms.any(axis=0)
        nz = np.where(col)[0]
        return int(nz.min() + x0) if len(nz) else -1

    # ────────────────────────── 行动者 ──────────────────────────
    def read_actor(self, axis_rgb, geom=None, offset=(0, 0), t=None):
        """行动轴图（RGB）→ 行动者。返回 dict（判不出来时 unit/owner=None）。

        `geom`：线7 算出的行动轴几何（绝对坐标）。整帧输入时传 None（每帧动态定位，
        与离线 `scan_C2.py` 同口径）；**裁剪过的区域**输入时必须传（见 `local_axis_geom`）。
        `offset`：裁剪区域在原帧里的左上角（实时抓的是 `x60~340` 那条轴区域）。
        `t`：帧时刻（阿哈认脸的多帧投票要用；不传就按 30fps 递推）。

        🆕 T2 两件事（都是**附加**的，失败不影响主链路）：
        1. **卡面细化**：`axis_actor` 把菱形卡一律记成 `elation`，实测里面混着
           **【?】=【头号补给盲盒】**（→ 银狼LV.999）与**敌方给我方的 buff**（→ 不计入）。
           用 `card_kind_t2` 的模板再判一次（实测实时几何与模板库同为 1.900 分）。
        2. **阿哈时刻认脸**：顶端是阿哈面具框时，框里是谁由**中间那个头像**决定
           （用户 2026-10-04：框里的人不是定的，可以是非欢愉角色、也可以不是角色，必须认脸）。
           **单帧不稳 → 近 1.0s 多帧投票**，过半才认。
        """
        import cv2
        bgr = cv2.cvtColor(np.ascontiguousarray(axis_rgb, dtype=np.uint8), cv2.COLOR_RGB2BGR)
        r = T.read_actor(bgr, self.bank, geom=geom)
        if r is None:
            return r
        # ① 卡面细化（盲盒 / 敌方 buff）——只对"可能误判"的帧做，省时间：
        #    菱形卡（`elation`）里混着【?】盲盒；低分的单位卡里混着红兔（敌方 buff）。
        ct0 = r.get("card_type")
        if ct0 == "elation" or (ct0 == "unit" and float(r.get("score") or 0) < 0.90):
            try:
                from tools.team2 import card_kind_t2 as CK
                k = CK.card_kind_live(bgr, offset=offset, geom=geom)
                r["t2_card"] = k["kind"] or ""
                r["t2_card_score"] = round(float(k["score"]), 3)
                if k["kind"] == "blindbox":
                    r["card_type"], r["unit"] = "blindbox", CK.KIND_OWNER["blindbox"]
                    r["owner"] = CK.KIND_OWNER["blindbox"]
                elif k["kind"] == "enemy_buff":
                    r["card_type"], r["unit"], r["owner"] = "enemy_buff", "", ""
            except Exception as e:                      # noqa: BLE001
                r["t2_card"] = "error:%s" % e
        # ② 阿哈认脸（+ 多帧投票）
        if r.get("card_type") == "aha":
            try:
                from tools.team2 import aha_member as AHA
                k = AHA.recognize_full(bgr, offset=offset)
                if t is None:
                    t = (self._aha_last_t or 0.0) + 1.0 / 30.0
                self._aha_last_t = t
                self._aha_hist.append((t, k["member"] or ""))
                self._aha_hist = [x for x in self._aha_hist
                                  if t - x[0] <= AHA_VOTE_WIN][-AHA_VOTE_MAX:]
                votes = {}
                for _tt, m in self._aha_hist:
                    if m:
                        votes[m] = votes.get(m, 0) + 1
                n = len(self._aha_hist)
                best = max(votes.items(), key=lambda kv: kv[1]) if votes else None
                r["aha_score"] = round(float(k["score"]), 3)
                r["aha_form"] = k["form"] or ""
                r["aha_why"] = k["why"]
                r["aha_votes"] = "%s:%d/%d" % (best[0] if best else "-", best[1] if best else 0, n)
                if best and best[1] >= 0.5 * n:
                    r["unit"] = best[0]
                    r["owner"] = best[0]
            except Exception as e:                      # noqa: BLE001
                r["aha_why"] = "error:%s" % e
        else:
            self._aha_hist = []                         # 不在阿哈时段 → 清空投票缓冲
        return r

    # ────────────────────────── 组合 ──────────────────────────
    def read(self, t, frame_rgb=None, region_rgb=None, top=None, left=None,
             bar_rows=None, axis_rgb=None, axis_geom=None, axis_offset=(0, 0),
             read_axis=True, want_lm=False):
        """一帧 → 一条读数。`frame_rgb` 与 `region_rgb` 二选一。

        frame_rgb : 整帧（RGB）—— 离线/回放用（HUD 走动态定位）
        region_rgb: 已裁好的 HUD 区域 + top/left（绝对坐标）—— 实时抓屏用
        axis_rgb  : 行动轴图（RGB）；read_axis=False 或缺省时不读（保持空）
        axis_geom : 行动轴几何；整帧时给 None，裁剪区域时给 local_axis_geom() 的结果
        axis_offset: 轴区域在原帧里的左上角（实时 x60 → 传 (60, 0)）；T2 认脸要用
        """
        row = new_row(t)
        t0 = time.perf_counter()
        suspect = ""
        if region_rgb is not None:
            text, conf, n, nbad, suspect = self.read_hud_region(region_rgb, top, left, bar_rows)
            if want_lm and text:
                row["lm"] = self.hud_leftmost(region_rgb, top, left)
        elif frame_rgb is not None:
            text, conf, n, nbad = self.read_hud_frame(frame_rgb)
            if want_lm and text:
                arr = np.asarray(frame_rgb, dtype=np.int16)
                row["lm"] = self.hud_leftmost(arr[HG.CY0:HG.CY1, HG.CX0:HG.CX1],
                                              HG.CY0, HG.CX0)
        else:
            raise ValueError("read() 需要 frame_rgb 或 region_rgb")
        t1 = time.perf_counter()
        row.update({"text": text, "n": n, "conf": round(conf, 3), "nbad": nbad})
        if read_axis and axis_rgb is not None:
            a = self.read_actor(axis_rgb, geom=axis_geom, offset=axis_offset, t=t)
            row.update({"unit": a["unit"] or "", "owner": a["owner"] or "",
                        "score": round(float(a["score"]), 3),
                        "margin": round(float(a["margin"]), 3),
                        "marker": a["marker"] or "",
                        "inserted": "" if a["inserted"] is None else str(int(a["inserted"])),
                        "card_type": a["card_type"] or "",
                        "raw_unit": a["raw"]})
        t2 = time.perf_counter()
        row["ms"] = {"hud": (t1 - t0) * 1000.0, "axis": (t2 - t1) * 1000.0}
        return row

    def as_csv_row(self, row):
        """转成与 `out/frames_dense4.csv` 同列的一行（对账/落盘用）。"""
        return [row["t"], row["text"], row["n"], len(row["text"]), row["lm"], row["conf"],
                row["nbad"], row["profile"], row["unit"], row["owner"], row["score"],
                row["margin"], row["marker"], row["inserted"], row["card_type"]]


# ── 区域计算（"不要把分辨率写死"；框与 bar_rows **必须同源成对**）──────────────
# 实测依据（`tools/overlay/probe_hud_path.py`，录屏1 的 923 张密帧，四种组合逐帧比读数）：
#     torch_dyn  68/923 与离线表不同   ← line7「按画面墨迹定位」的框（**没经过平移闸**的旧口径）
#     onnx_dyn   68/923 与离线表不同   ← 同上（换后端不影响结论）
#     torch_fixed  0/923 与离线表不同  ← 参考框（= 按分辨率等比缩放的模型框）
#     onnx_fixed   0/923 与离线表不同  ← 同上
# ① ONNX 与 torch **逐帧等价**（这也是 `hud_digits.check_model_freshness` 探针的结论）；
# ② 那 68 帧的根因**不是**"墨迹定位天生不行"，而是**线7 偶尔把框算飞**
#    （923 帧里 104 帧算飞，其中 68 帧读差）→ 现在由下面的 `ink_geometry_ok` 平移闸挡住，
#    录屏回放与权威离线表重新**逐帧一致（923/923）**，同时实机（Δy0=+25 的纯平移）照旧接受。
#
# ⚠️⚠️【实机补充 2026-10-01 —— 上面这条结论需要限定条件】⚠️⚠️
# 上面那个 68/923 的结论是在**录屏帧**上测的。**实机全屏**下情况相反：
#   · 静态参考框（等比缩放）→ 框在 y 260~340，而实机数字实际在 y≈298~358
#     → 底部切掉数字 → 同一帧读出 `53438`（**错**）
#   · **档案自己的定位**（`hud_profiles.box_for('default', 整帧)`，default 档登记 `locate=True`）
#     → 框在 (285,2353,365,2880) → 读出 `73431`（**对，与屏幕一致**）
# 原因：**"不同模式下总伤位置不同"**（用户判断正确）——静态框只对"录屏那种模式"成立。
# 所以：`frame_rgb` 给了就**优先用档案定位**；没给才退回等比缩放。
# ⚠️⚠️【P1 实机定案 2026-10-02 —— `bar_rows` 那条旧结论是错的】⚠️⚠️
# `docs/行动轴识别.md` §2/§3 曾写"墨迹自适应绝不能平移 bar_rows、要用模型的"。
# 在一张**全分辨率实机帧**上逐条复测（`samples/M_full_now.png`，2880×1800，屏幕上 `73431`），
# 下面这些读数是**走实时路径（含几何守门）**得到的（`python tools/overlay/live_box_check.py`）：
#     墨迹框 (285,2353,365,2880) + 墨迹 bar (323,335) → `73431`  可信  ✅
#     墨迹框                    + 模型 bar (298,310) → `??343`  nbad=2  ❌
#     模型框 (260,2353,340,2880) + 模型 bar (298,310) → `?????`  nbad=5  ❌
#     模型框                    + 墨迹 bar (323,335) → `?????`  nbad=5  ❌
# 原因：**本机实机画面比录屏低约 25px**（数字 y 298~356 vs 录屏 272~330；
# 装饰金线行带 323~335 vs 298~310）。金线行带的作用是"分割前把这几行挖空"，
# 用错的那一对就会把数字自己的笔画挖掉 → 字形被切碎 → 丢位/几何守门失败。
# ⇒ **框与 bar_rows 必须同源成对**，只有"两样都来自画面证据"的那一对能读对；
#   `?????` 是**非空**的，这正是"永不重定位"的机关（见 `read_is_reliable`）。
#
# ⚠️ 但"画面证据"本身也会算飞：线7 的墨迹判据会把**发光光束**当墨迹，实测录屏1 的 923 帧里
#    有 104 帧得到 `box=(257,2074,380,2876)`（左边多出 276px、高 43px、金线行带下移 17px），
#    其中 **68 帧丢前导位** —— 上面那个 68/923 就是这么来的（不是"墨迹定位天生不行"）。
#    而实机上正确的情形是"整块 HUD 相对模型框**平移**"（Δy0=+25px，x0/宽/高不变，
#    行带跟着平移同样的 25px）。⇒ 加**平移闸** `ink_geometry_ok`：过不了闸就退回模型框
#    （几何里留 `ink_rejected` 痕迹）。这样录屏回放与权威表重新逐帧一致（923/923），
#    实机那一帧（Δy0=+25）照旧被接受。
def hud_region_for(shape, use_ink=False, frame_rgb=None):
    """(H, W) → (HUD 抓屏区域 dict, 金线行带 bar_rows, 几何 dict)。

    * `frame_rgb` 非空 → **按这一帧画面定位**（线7 `hud_geometry`），
      **框与 bar_rows 一起取**，返回值里的 `src` 是真实来源（`ink` / `model`），
      ⚠️ 不再是过去那个硬写死的 `"profile"`（那个标签让日志完全不可信：
      退回模型框时也印"来源 profile"，排查时被误导过一轮）。
    * `frame_rgb` 为空 → 分辨率等比的模型框（老脚本/标定工具用这条，行为未变）。
    * `use_ink` 仅为兼容旧调用保留；**现在由画面证据决定**，不再由它开关。
    """
    import geometry as SA
    H, W = int(shape[0]), int(shape[1])

    g = None
    if frame_rgb is not None:
        try:
            import geometry as SA
            g_model = model_geometry(H, W)
            g_ink = SA.hud_geometry(frame_rgb)
            if g_ink.get("src") == "ink" and not ink_geometry_ok(g_ink, g_model):
                # 线7 这次算飞了（判据把发光光束当墨迹）→ 退回模型框，并在几何里留痕
                gg = dict(g_model)
                gg["src"] = "model"
                gg["ink_rejected"] = g_ink
                g = gg
            else:
                g = g_ink
        except Exception:
            g = None
        if g is None:
            # 档案标定框兜底（**没有画面依据** → src='static'，bar 用模型值）
            try:
                import hud_profiles as HP
                box, _bar = HP.box_for("default", frame_rgb)
                g = {"box": tuple(int(v) for v in box),
                     "bar_rows": tuple(int(v) for v in model_geometry(H, W)["bar_rows"]),
                     "src": "static", "size": (H, W)}
            except Exception:
                g = None

    if g is None:
        g = model_geometry(H, W)

    y0, x0, y1, x1 = g["box"]
    region = {"left": int(x0), "top": int(y0), "width": int(max(1, x1 - x0)),
              "height": int(max(1, y1 - y0))}
    return region, tuple(int(v) for v in g["bar_rows"]), g


def model_geometry(H, W):
    """分辨率等比的模型框（**没有画面依据**的那一档，= 线7 的 model 分支）。"""
    import geometry as SA
    gg = SA.hud_geometry(shape=(int(H), int(W)))
    return {"box": tuple(int(v) for v in gg["box"]),
            "bar_rows": tuple(int(v) for v in gg["bar_rows"]),
            "src": gg.get("src") or "model", "k": gg.get("k"), "size": (int(H), int(W))}


# 线7 墨迹几何的**接受闸**（P1 实机定案 2026-10-02）。
# 为什么需要：线7 的墨迹判据会把画面里的**发光光束**也当成墨迹，于是偶尔把框算得离谱。
# 实测（录屏1 的 923 帧密帧）有 104 帧得到 `box=(257,2074,380,2876) bar=(315,333)`：
# 左边多出 276px、框高了 43px、金线行带下移 17px —— 这 104 帧里 **68 帧丢前导位**
# （`00773`→`665`、`259449`→`9449`…）。而**实机上正确的情形是"整块 HUD 相对模型框平移"**：
# 实测 Δy0=+25px，x0 / 宽 / 高都不变，金线行带跟着平移同样的 25px。
# ⇒ 只接受"像模型框的小平移"的墨迹几何；算飞的一律退回模型框（并在几何里留 `ink_rejected` 痕迹）。
# ⚠️ 2026-10-02 晚修正：`dy0` 从 60 → **150**。
#   原因（用户实测：exe/窗口化全屏下"数字一直不动"）：窗口带标题栏/边框时，整块 HUD 相对模型框
#   会往下顶 **60px 以上**（独占全屏时实测只有 +25px）。原来那道 60px 会把**正确的**墨迹框
#   一直拒掉 → 永远停在模型框 → 读出 `?????` → 全程待复核。
#   放宽 dy0 **不会**放进"算飞"的那批：录屏里 105 个算飞帧的签名都是 **左缘 dx0 = -52 ~ -276**
#   （以及字号比 k 偏大 1.5），这些仍被 `dx0 ≤ 20` / `dk ≤ 0.25` / `drelbar ≤ 12` 挡住。
INK_GATE = {"dy0": 150, "dx0": 20, "dx1": 14, "dh": 30, "drelbar": 12, "dk": 0.25}


def ink_geometry_ok(g_ink, g_model, tol=None):
    """线7 算出的墨迹几何**是否可采信**（判据见 `INK_GATE` 上方的实测说明）。

    只做**平移**容差，不做缩放容差：实测那个算飞的框在"按框高比例缩放"的口径下
    反而能通过（它整体被放大了 1.54 倍），所以必须按平移卡死。

    三个关键量（都来自实测）：
      · `dx0`（左缘位移）：实机是 **+3px**（纯平移）；算飞的框是 **-52 ~ -276px**
        （左缘由 `x1 - 容量(k)` 反推，k 估大 → 左缘猛往左跑）。取 20px 卡住。
      · `drelbar`（金线行带相对**框顶**的偏移）：实机是 **0**（行带跟着框平移 25px）。
      · `dk`（字号比）：模型帧的 k 就是分辨率比；墨迹帧 k 若偏离 >0.25 说明
        "局部墨迹把字号估大了"（4 个算飞模式里 3 个都是这样）。
    """
    t = dict(INK_GATE)
    t.update(tol or {})
    try:
        iy0, ix0, iy1, ix1 = (int(v) for v in g_ink["box"])
        my0, mx0, my1, mx1 = (int(v) for v in g_model["box"])
        ia, ib = (int(v) for v in g_ink["bar_rows"])
        ma, mb = (int(v) for v in g_model["bar_rows"])
    except Exception:
        return False
    # 金线行带相对**框顶**的偏移（行带要跟着框走，不能自己乱跳）
    rel_i, rel_m = ia - iy0, ma - my0
    ki, km = g_ink.get("k"), g_model.get("k")
    dk_ok = True
    if ki is not None and km is not None:
        dk_ok = abs(float(ki) - float(km)) <= t["dk"]
    return (abs(iy0 - my0) <= t["dy0"] and abs(ix0 - mx0) <= t["dx0"]
            and abs(ix1 - mx1) <= t["dx1"] and abs((iy1 - iy0) - (my1 - my0)) <= t["dh"]
            and abs(rel_i - rel_m) <= t["drelbar"] and dk_ok)


def read_is_reliable(row):
    """一条读数是否算"**真的读到了数字**"（P1 实机定案）。

    为什么需要它：`ScreenSource.note_hud_result` 原来只看"文本非空"，
    而**错误的框**给出的是一串 `'?'`（几何守门失败/低于置信的占位符）——
    它**非空**，于是被当成"读到了" → 永不重定位 → 用户看到的正是
    「数字动都不动一下，一直是待复核」。判据：
      * 文本非空；
      * **不含 `'?'`**；
      * `nbad == 0`（双保险，两条其实是同一件事）。
    """
    t = str(row.get("text") or "").strip()
    return bool(t) and "?" not in t and int(row.get("nbad") or 0) == 0


# 黄墨迹判据（与 `tools/overlay/hud_box.py` 的 ink_box 同一套阈值）：
# 数字是"亮黄"——R/G 都高、B 明显低。用来回答**"这一帧画面上到底有没有总伤害数字"**，
# 与"我们选的框读没读到"是两件事。P1 用它当重定位触发条件：
# 画面里已经有数字、而当前框读不出可信读数 → 立刻用画面证据重定位。
# 实测（实机帧）：数字块 399×59px，阈值下墨迹行密度峰值 ~300、低阈行 ≥8 行。
INK_THR = (195, 185, 40, 20)      # R > 195 & G > 185 & (R-B) > 40；计数 ≥ 20 才算有墨迹


# ⭐ P1 实机安全网：**"切出来的字符合计宽度 远小于 画面里墨迹的跨度" → 这一帧不可信**。
#
# 为什么需要（用户 2026-10-02 逐格核对时抓到的真实反例）：
#   实机 t=127.4 —— 画面上明明是 `630911`，程序读出 **`1`**，而且**置信 1.0、不含 `?`、
#   nbad=0**（= 一道闸都没拦住）。事后查该帧：数字块正在**放大/滚动动画**里，
#   字形溢出固定框，列分割只切出一个 33px 宽的小块 → 分类器把它当成 `1`。
#   实测该帧：墨迹跨度 527px，切出的字符合计只有 33px（比值 0.06）；
#   而**所有被用户确认读对的帧**（`177129`/`7429`/`622487`/`339724`…）比值都在 **0.40~0.68**。
# ⇒ 阈值取 `跨度 ≥ 150px` 且 `比值 < 0.30` → 命中就把读数换成 `?`（进不了统计），原值留在诊断里。
#
# ⚠️ 为什么**只给实机开**（`Perceiver(span_guard=True)`）：
#   离线回放要与权威表 `out/frames_dense4.csv` **逐帧一致**（已对账 923 帧 0 差异）；
#   实测这道闸会在录屏帧上命中 105/923（那些帧本来就是"静默丢前导位"的坏读数），
#   给回放开等于改动已对账的口径。实机的取舍是明确的：**宁可漏，不要错**。
INK_SPAN_GUARD = {"min_span": 150, "min_ratio": 0.30}


def span_guard_hit(region_rgb, glyphs, tol=None):
    """`glyphs` 的合计宽度是否**远小于**画面里的黄墨迹跨度（判据见上面那段实测）。"""
    t = dict(INK_SPAN_GUARD)
    t.update(tol or {})
    try:
        a = np.asarray(region_rgb)
        if a.size == 0:
            return False
        a = a.astype(np.int16)
        r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
        rmin, gmin, rb, _cnt = INK_THR
        cols = ((r > rmin) & (g > gmin) & ((r - b) > rb)).sum(axis=0)
        nz = np.where(cols > 2)[0]
        if len(nz) == 0:
            return False
        span = int(nz.max() - nz.min() + 1)
        if span < t["min_span"]:
            return False                      # 墨迹本来就窄（个位数/两位数的总伤）→ 不做判断
        wsum = int(sum(int(gl[1]) for gl in (glyphs or [])))
        return (wsum / float(span)) < t["min_ratio"]
    except Exception:
        return False


def hud_has_ink(region_rgb):
    """这一小块画面里有没有"亮黄墨迹"（= 屏幕上有没有总伤害数字）。"""
    a = np.asarray(region_rgb)
    if a.size == 0:
        return False
    a = a.astype(np.int16)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    rmin, gmin, rb, cnt = INK_THR
    return int(((r > rmin) & (g > gmin) & ((r - b) > rb)).sum()) >= cnt


def axis_region_for(shape, use_ink=False, frame_rgb=None, bottom_frac=0.70):
    """(H, W) → (行动轴抓屏区域 dict, **该区域坐标系**下的行动轴几何, 整屏几何)。"""
    import geometry as SA
    H, W = int(shape[0]), int(shape[1])
    if use_ink and frame_rgb is not None:
        bgr = np.ascontiguousarray(np.asarray(frame_rgb)[:, :, ::-1])
        g = SA.axis_geometry(bgr, refine=False)
    else:
        g = SA.axis_geometry(shape=(H, W))
    l, t, r, b = g["card"]
    left = int(max(0, l - 28))          # 与 SA.live_regions 同样的余量（含左标记）
    right = int(min(W, r + 57))
    region = {"left": left, "top": 0, "width": int(max(1, right - left)),
              "height": int(round(bottom_frac * H))}
    return region, local_axis_geom(g, left, 0), g


def local_axis_geom(geom, offset_x, offset_y=0):
    """把线7 在**整屏**上算出的行动轴几何平移到"已经裁好的行动轴区域"坐标系。

    为什么需要：`axis_actor.read_actor` 在整帧上会自动定位；但实时线为了省时间只抓
    行动轴那一窄条（`capture` 的做法），此时坐标原点变了 —— 直接把整屏几何喂进去
    会取到图外。这里只平移 `top_art` / `mark_c` / `card`，`s`（缩放）不变。
    """
    if geom is None:
        return None
    g = dict(geom)
    dx, dy = int(offset_x), int(offset_y)
    g["top_art"] = tuple(int(v) for v in np.subtract(geom["top_art"], (dx, dy, dx, dy)))
    g["mark_c"] = tuple(int(v) for v in np.subtract(geom["mark_c"], (dx, dy)))
    g["card"] = tuple(int(v) for v in np.subtract(geom["card"], (dx, dy, dx, dy)))
    g["left"] = int(geom["left"] - dx)
    g["top"] = int(geom["top"] - dy)
    return g


def _selftest():
    """自检：能建感知器、能读一张真帧，且读数与 A 线真值一致（不碰屏幕）。"""
    p = Perceiver(backend="onnx")
    t = 226                      # A 线真值：49065（见 digit_truth.py / eval_holdout.py）
    path = os.path.join(ROOT, "frames", "glyphcache", "f%08.2f.png" % t)
    from PIL import Image
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    row = p.read(t, frame_rgb=a)
    print("  t=%s 读出=%s（期望 49065） 字形数=%d 最低置信 %.2f  HUD 耗时 %.1fms"
          % (t, row["text"] or "(空)", row["n"], row["conf"], row["ms"]["hud"]))
    if row["text"] != "49065":
        print("  ✗ 与 A 线真值不一致")
        return 1
    print("reader 自检通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
