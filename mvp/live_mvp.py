# -*- coding: utf-8 -*-
"""[MVP] 主循环：帧源 → 读数 → 流式事件 → 悬浮窗。

两种帧源，**同一套下游**（这是"离线对账"能成立的前提）：
  * `--replay <dir>`：回放 `frames/glyphcache/` 里的真帧（**不需要游戏、不需要屏幕**），
    用于对账与演示；时间轴就是帧号。
  * 默认（不传 --replay）：实时抓屏（`capture.Grabber`），启动时用线7 动态定位
    两块区域（HUD 数字区 / 行动轴列），之后只抓这两块小区域。

必须落实的三条 MVP 要求：
  * 判不出来不猜 → 行动者识别不出时悬浮窗显示「待复核」（`engine.current_actor()` 不给上一人）；
  * 占比只在归属确定的事件上算 → 口径 = `status == ok`（见 `mvp/engine.py`）；
  * 单帧 抓屏+识别+更新 < 100ms → 结束时打印 p50/p95/最大值。

示例：
  python mvp/live_mvp.py --seconds 30                      # 实机：悬浮窗 + 终端日志
  python mvp/live_mvp.py --no-overlay --seconds 30         # 只看终端（排查用）
  python mvp/live_mvp.py --replay frames/glyphcache --range 98,340 --step 0 --no-overlay
  python mvp/live_mvp.py --replay frames/glyphcache --speed 4 --overlay   # 4 倍速演示
  python mvp/live_mvp.py --selftest                        # 打包/安装自检（不碰屏幕）

打包（exe）后同样支持这些参数，**资源路径按 exe 位置解析**（见 `mvp/resource.py`），
所以 exe 放在桌面也能跑；相对路径的产出（`--dump-readings`）落在 exe 所在目录。
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# 源码模式：仓库根 + vendor/（mss）进 sys.path；打包模式：模块已随 exe 打进去，不用管。
# ⚠️ 不要无条件 `os.chdir(ROOT)`：打包后 ROOT 是"解包目录"（onefile 甚至是临时目录），
#    一切相对路径（如 --dump-readings 的产出）都会掉进那里、退出即消失。见 mvp/resource.py。
if not getattr(sys, "frozen", False):
    for _p in (ROOT, os.path.join(ROOT, "vendor")):
        if _p not in sys.path:
            sys.path.insert(0, _p)

from mvp import resource as R                 # noqa: E402
from mvp.resource import chdir_runtime        # noqa: E402

RUNTIME_DIR = chdir_runtime()                 # 源码=仓库根；exe=exe 所在目录

import hud_glyphs as HG                       # noqa: E402
from mvp import av_reader as AVR              # noqa: E402
from mvp.engine import LiveEngine             # noqa: E402
from mvp.reader import (Perceiver, ROW_COLS,  # noqa: E402
                        hud_has_ink, ink_geometry_ok, local_axis_geom,
                        model_geometry, read_is_reliable)

# P1 诊断表列（**故意与 ROW_COLS 分开**：`--dump-readings` 的列必须与
# `out/frames_dense4.csv` 一致，离线对账脚本逐列比它；加列会破坏对账口径）
DIAG_COLS = ["t", "hud_text", "hud_n", "hud_nbad", "hud_conf", "hud_has_q", "hud_has_ink",
             "hud_src", "hud_box", "hud_bar", "hud_suspect", "axis_read", "unit", "owner",
             "score", "margin", "marker", "card_type", "ms_frame", "ms_hud", "ms_axis",
             "reliable"]


# ══════════════════════════════ 帧源 ══════════════════════════════
class ReplaySource:
    """回放磁盘上的真帧。帧号就是时间（秒）。"""

    def __init__(self, frame_dir, lo=98.0, hi=340.0, step=0.0, hud_mode="region",
                 use_ink=False):
        self.dir = frame_dir
        self.hud_mode = hud_mode
        self.use_ink = use_ink
        items = []
        for p in sorted(glob.glob(os.path.join(frame_dir, "*.png"))):
            try:
                t = float(os.path.basename(p)[1:-4])
            except ValueError:
                continue
            if not (lo <= t <= hi):
                continue
            if step > 0 and abs(t / step - round(t / step)) > 1e-6:
                continue
            items.append((t, p))
        self.items = items

    def __len__(self):
        return len(self.items)

    def frames(self):
        from PIL import Image
        from mvp.reader import hud_region_for
        for t, p in self.items:
            _t0 = time.perf_counter()
            arr = np.asarray(Image.open(p).convert("RGB")).astype(np.int16)
            f = {"t": t, "frame_rgb": None, "hud_region": None, "hud_top": HG.CY0,
                 "hud_left": HG.CX0, "hud_bar": HG.BAR_ROWS,
                 "axis_rgb": arr, "axis_geom": None, "read_axis": True}
            if self.hud_mode == "region":
                # 按该帧分辨率等比缩放（2876×1798 → 恰好是参考框 (260,2350)-(340,2876)）
                reg, bar, _g = hud_region_for(arr.shape, use_ink=self.use_ink, frame_rgb=arr)
                y0, x0 = reg["top"], reg["left"]
                f["hud_region"] = np.ascontiguousarray(
                    arr[y0:y0 + reg["height"], x0:x0 + reg["width"]], dtype=np.int16)
                f["hud_top"], f["hud_left"], f["hud_bar"] = y0, x0, bar
                f["hud_box"] = (y0, x0, y0 + reg["height"], x0 + reg["width"])
                f["hud_src"] = ("ink-rej" if _g.get("ink_rejected") is not None
                                else (_g.get("src") or "model"))
                f["hud_has_ink"] = hud_has_ink(f["hud_region"])
            else:
                f["frame_rgb"] = arr
            # 帧源自身耗时（PNG 解码）—— 计入 ms["frame"]，否则"单帧 <100ms"会漏掉这一块
            f["src_ms"] = (time.perf_counter() - _t0) * 1000.0
            yield f

    def close(self):
        pass


class ScreenSource:
    """实时抓屏。两块区域按分辨率算出来。

    ⚠️【P1 实机定案 2026-10-02】HUD 框与 `bar_rows` **必须同源成对**（见 `mvp/reader.py`）。
    本机实机画面比录屏**低约 25px**，所以：
      * 有数字时 → 线7 墨迹定位（`src='ink'`）给出**正确的那一对**；
      * 进战前启动（画面里还没有数字）→ 只能退回模型那一对，而它在实机上是**错的**
        （读出 `?????`）⇒ 必须靠"画面里出现墨迹就立刻重定位"自救，并用
        `out/live_calib.json` 记住上次标定，让下次进战前启动直接就对。
    """

    CALIB = os.path.join("out", "live_calib.json")     # 相对 RUNTIME_DIR（源码=仓库根，exe=exe 目录）

    def __init__(self, axis_every=5, calibrate=False, verbose=True, use_calib=True,
                 dump_frames=None, dump_frames_every=3.0):
        from capture import Grabber
        from mvp.reader import axis_region_for, hud_region_for
        self.g = Grabber()
        self.axis_every = max(1, axis_every)
        self.n = 0
        self.hud_geom = None
        self.axis_geom = None
        self.use_calib = bool(use_calib)
        # ⭐ P1：实机采集时把**整屏帧**按秒落盘 → 离线出"核对图"让用户读数（真值来源）。
        #    只用于取证跑，正常使用不开（每次多一次全屏抓取 + JPEG 编码 ≈ 100ms）。
        self.dump_frames = dump_frames
        self.dump_frames_every = max(0.2, float(dump_frames_every))
        self._last_dump = 0.0
        self.n_dump = 0
        self.screen = self.g.screen                     # (W, H)
        shape = (self.screen[1], self.screen[0])
        # 线7 的墨迹几何要拿它当"平移基准"过闸（见 reader.ink_geometry_ok）
        self.model_geom = model_geometry(shape[0], shape[1])
        if calibrate:
            import geometry as SA
            full = self.g.grab_screen()
            reg = SA.live_regions(full)
            self.g.regions = {"hud": reg["hud"], "axis": reg["axis"]}
            self.hud_geom = reg["hud_geometry"]
            self.axis_geom = local_axis_geom(reg["axis_geometry"], reg["axis"]["left"], 0)
            self.hud_bar = tuple(reg["hud_geometry"]["bar_rows"])
            if verbose:
                print("⚠️ 已开启 --calibrate：直接采信线7 的墨迹几何（**不过 P1 的平移闸**，"
                      "只用于多分辨率试验）。生产默认走 `reader.ink_geometry_ok` 过闸。")
                print("整屏 %dx%d → HUD %s（来源 %s，字号比 %.2f，金线行带 %s）｜行动轴 %s（来源 %s）"
                      % (self.screen[0], self.screen[1], reg["hud"], self.hud_geom["src"],
                         self.hud_geom["k"], self.hud_geom["bar_rows"], reg["axis"],
                         reg["axis_geometry"]["src"]))
        else:
            # ⚠️【实机教训 2026-10-01】这里必须**给整帧**让档案自己定位，不能用静态框。
            # 原因：`hud_region_for(shape)`（只给尺寸）会退回**静态模型框** `(260,2350,340,2876)`，
            # 而实机全屏下数字实际在 `y≈298~358`（`default` 档登记了 `locate=True`，
            # 档案自己定位会得到 `(285,2353,365,2880)`）。
            # 实测同一帧：静态框读出 `53438`/`?????`（错），档案动态框读出 `73431`（对，与屏幕一致）。
            # 用户判断"不同模式下总伤位置不同"是对的 —— 所以定位必须跟画面走。
            import numpy as _np
            frame0 = None
            try:
                frame0 = self.g.grab_screen()
            except Exception:
                frame0 = None
            hud, bar, hg = hud_region_for(shape, use_ink=True, frame_rgb=frame0)
            axis, ag, axg = axis_region_for(shape)
            self.g.regions = {"hud": hud, "axis": axis}
            self.hud_geom, self.hud_bar, self.axis_geom = hg, bar, ag
            if verbose:
                print("整屏 %dx%d → HUD %s（来源 %s，金线行带 %s）｜行动轴 %s"
                      % (self.screen[0], self.screen[1], hud,
                         "ink-rej(退回模型)" if hg.get("ink_rejected") is not None
                         else hg.get("src"), bar, axis))
        self.hud_src = "ink-rej" if (self.hud_geom or {}).get("ink_rejected") is not None \
            else ((self.hud_geom or {}).get("src") or "model")
        self._fails = 0
        self._last_try = 0.0
        self._last_periodic = time.perf_counter()
        self.n_reloc = 0
        self.n_ink_rejected = 0
        self.n_calib_saved = 0
        self.n_forced = 0            # "同一个框反复不符 → 强制采用"的次数
        self._ever_reliable = False  # 本次会话读到过**完整数字**吗（标定落盘的前提）
        self._rej_box = None         # 最近一次被闸掉的墨迹框（判"是不是同一个框"）
        self._rej_n = 0

        # ⭐ P1：进战前启动时画面里**还没有伤害数字** → 没有墨迹 → 只能拿到模型那一对，
        #    而它在实机上是错的。所以先用**上次标定的框**（如果分辨率一致）。
        if not calibrate and self.use_calib:
            cal = self.load_calib()
            if cal is not None:
                self.g.regions["hud"] = cal["region"]
                self.hud_bar = tuple(int(v) for v in cal["bar"])
                self.hud_geom = {"box": tuple(cal["box"]), "bar_rows": self.hud_bar,
                                 "src": "calib", "size": shape}
                self.hud_src = "calib"
                if verbose:
                    print("  ✓ 用上次标定的 HUD 框 %s（金线行带 %s）—— 进战前启动也能直接读"
                          % (cal["region"], self.hud_bar))
            # ⚠️ 这里**不再**"开局就把墨迹框落盘"：开局那一帧可能是桌面上别的窗口，
            #    落盘要等"读到过一次完整数字"（见 note_hud_result）。

        self.t0 = None

    # ────────────────── 标定落盘（P1：进战前启动也能直接读）──────────────────
    def _box_plausible(self, box):
        """这个框像不像"屏幕右上角的总伤害数字块"。

        为什么要查：标定会落盘、下次开局直接用。如果某次把**别的窗口里的黄色**
        当成 HUD 记下来，下次开局就会用错的框。所以只接受：
        在屏幕右半边（HUD 是右对齐的）+ 高度是"数字块"量级 + 宽度给够了容量。
        """
        try:
            y0, x0, y1, x1 = (int(v) for v in box)
        except Exception:
            return False
        W, H = int(self.screen[0]), int(self.screen[1])
        return (x0 > 0.55 * W and y0 >= 0 and y1 <= H and x1 <= W
                and 30 <= (y1 - y0) <= 200 and (x1 - x0) >= 100)
    def calib_path(self):
        return os.path.join(RUNTIME_DIR, self.CALIB)

    def load_calib(self):
        """读上次标定；分辨率不一致就作废（换了屏幕/窗口大小 → 那对框不可用）。"""
        return calib_load(self.calib_path(), self.screen)

    def save_calib(self, box, bar):
        """把"已经用画面证据验证过的"那一对 (框, bar) 记下来，供下次开局直接用。"""
        if calib_save(self.calib_path(), self.screen, box, bar):
            self.n_calib_saved += 1
        # 写不进去（exe 放在只读目录）只是"没有标定"，不影响读数 → 不报错

    def relocate(self, verbose=False, min_shift=3):
        """按**当前画面**重新定位 HUD 框（用画面证据，框与 bar_rows **成对**取）。

        为什么需要：启动时那一帧很可能**不是游戏**（一执行命令焦点就离开游戏，
        mss 抓到的是终端/别的窗口），或**进战前还没有数字**（没有墨迹）→ 框会按错误
        依据算出来并固定下来 → 之后即使画面出现数字也一直读不到
        （实机踩过：2429 帧零读数）。

        ⚠️ 判据（两道，缺一不可）：
          1. `SA.hud_geometry` 必须报 **`src='ink'`**（真的从画面里定位到）。
             画面是终端时它找不到墨迹，会**退回模型框**（`src='model'`）——
             那一对在实机上是错的（读出 `?????`），接受它就等于没修。
          2. 这次算出来的几何必须**像模型框的小平移**（`reader.ink_geometry_ok`）。
             线7 偶尔会把画面里的发光光束当墨迹、把框算飞
             （实测录屏1 有 104 帧得到左边多出 276px 的框，其中 68 帧丢前导位）→
             不过闸的一律退回模型框，绝不采信。

        `min_shift`：新框与当前框差 < 它（像素）时视为"没变"，不重复打印/落盘。
        返回 True 表示**拿到了有画面依据的定位**（无论与当前是否相同）。
        """
        try:
            full = self.g.grab_screen()
        except Exception:
            return False
        if full is None:
            return False
        try:
            import geometry as SA
            g = SA.hud_geometry(np.asarray(full))
        except Exception:
            return False
        # 没定位到墨迹（多半这一帧不是游戏 / 还没有数字）→ 不接受，等下一帧
        if g.get("src") != "ink":
            return False
        # 采到了墨迹，但几何"算飞了"（不像模型框的小平移）→ 先拒；**同一个框连续出现
        # 15 次**就认为"布局真的不一样"（窗口带标题栏/换模式都可能），按画面证据采用。
        # 为什么要有这条兜底：2026-10-02 用户实测 exe/窗口化全屏下"数字一直不动" ——
        # 就是因为永远过不了闸、永远停在模型框（读出 `?????`）。宁可承认"我看不懂这个布局"，
        # 也不能一直卡着；采用后读数仍要过"可信读数"与"段宽/墨迹跨度"两道闸。
        if not ink_geometry_ok(g, self.model_geom):
            box_now = tuple(int(v) for v in g["box"])
            same = (self._rej_box is not None
                    and all(abs(a - b) <= 5 for a, b in zip(box_now, self._rej_box)))
            self._rej_n = (self._rej_n + 1) if same else 1
            self._rej_box = box_now
            self.n_ink_rejected += 1
            if self._rej_n < 15 or not self._box_plausible(box_now):
                return False
            self.n_forced += 1
            print("  ⚠️ 同一个墨迹框连续 %d 次不符合模型框（布局确实不同）→ **按画面证据强制采用** "
                  "%s（金线行带 %s）" % (self._rej_n, box_now, g["bar_rows"]))
        else:
            self._rej_box, self._rej_n = None, 0
        # 采到了墨迹，但框不像"右上角数字块"（别的窗口的黄色）→ 也不接受
        if not self._box_plausible(g["box"]):
            return False
        y0, x0, y1, x1 = (int(v) for v in g["box"])
        bar = tuple(int(v) for v in g["bar_rows"])
        old = self.g.regions.get("hud") or {}
        old_bar = tuple(self.hud_bar or ())
        changed = (not old) or any(abs(int(old.get(k, 0)) - v) > int(min_shift)
                                   for k, v in (("top", y0), ("left", x0),
                                                ("width", x1 - x0), ("height", y1 - y0))) \
            or any(abs(a - b) > int(min_shift) for a, b in zip(old_bar, bar)) \
            or len(old_bar) != len(bar)
        hud = {"left": x0, "top": y0, "width": int(max(1, x1 - x0)), "height": int(max(1, y1 - y0))}
        self.g.regions["hud"] = hud
        self.hud_geom, self.hud_bar, self.hud_src = g, bar, "ink"
        self.n_reloc += 1
        if changed:
            # ⚠️ 标定落盘的**前提**：本次会话至少读到过一次"完整数字"。
            #    否则可能把**别的窗口/桌面**上碰巧出现的黄墨迹记成 HUD 框，
            #    下次开局直接用它 → 一路读不到（用户 2026-10-02 的实际症状之一）。
            if self.use_calib and self._ever_reliable:
                self.save_calib((y0, x0, y1, x1), bar)
            if verbose:
                print("  ✓ 重定位 HUD → %s（来源 ink，金线行带 %s，第 %d 次）"
                      % (hud, bar, self.n_reloc))
        return True

    def wait_for_game(self, timeout=45.0, poll=0.5, verbose=True):
        """开局**短尝试**定位一次（不阻塞），然后立刻开始记录。

        ⚠️⚠️【用户反馈 2026-10-01 —— 这里曾经做错，务必看】⚠️⚠️
        用户原话："我用的时候是在进战前开始的，这样能保证所有的伤害能被记录，
        但是你做的好像是第一帧开始才能用"。

        即：**正确的起手时序是「进战前就开始记录」**。
        本函数最初写成"阻塞等到能定位到 HUD 再开始"——这是**错的**：
        开局时还没有伤害数字 → 没有墨迹 → 定位必然失败 → 白等到超时，
        把最早几段伤害全丢掉。

        ⇒ 正解（当前实现）：
          1. **立刻开始记录**（用兜底框，能读到就读）；
          2. 一旦**第一帧读到数字**，`note_hud_result` 触发重定位 →
             自动切到正确的动态框；
          3. 本函数只做**一次短尝试**，不阻塞主流程。

        返回 True 表示开局就定位成功（进战前通常为 False，不影响记录）。
        """
        t0 = time.perf_counter()
        n = 0
        while time.perf_counter() - t0 < max(0.0, timeout):
            n += 1
            if self.relocate(verbose=False):
                if verbose:
                    print("  ✓ 开局即定位到 HUD（用时 %.1fs）" % (time.perf_counter() - t0))
                return True
            if verbose and n % 6 == 0:
                print("  … 开局暂未定位到 HUD（%d 秒）—— 不影响记录："
                      "先用兜底框读，读到数字后会自动重定位。"
                      % int(time.perf_counter() - t0))
            time.sleep(poll)
        if verbose:
            print("  ⚠️ 开局未定位到 HUD（正常：进战前还没有伤害数字）。"
                  "已用兜底框开始记录；读到数字后会自动切到动态框。")
        return False

    def frames(self):
        self.t0 = time.perf_counter()
        # ⚠️ 不阻塞：立即开始产出帧（见 wait_for_game 的说明）
        self.relocate(verbose=True)
        while True:
            hud = self.g.regions["hud"]
            read_axis = (self.n % self.axis_every == 0)
            _ts = time.perf_counter()
            # ⭐ P1 取证对齐（2026-10-02 实测教训）：要落盘整屏帧时，**先抓整屏、
            #    再从它裁出 HUD 区域** —— 这样"落盘的那张图"与"这一帧的读数"
            #    用的是**同一份像素**。旧写法是先抓 HUD 小区域、再单独抓整屏存图，
            #    两者差 50~150ms；而总伤害数字在攻击中涨得很快，
            #    于是核对图上会出现"读数与图上数字不符"的**假差异**（真查过一轮才发现）。
            full = None
            if self.dump_frames:
                now2 = time.perf_counter()
                if now2 - self._last_dump >= self.dump_frames_every:
                    self._last_dump = now2
                    try:
                        full = self.g.grab_screen()
                    except Exception as e:
                        print("  ⚠️ 取证整屏抓取失败（不影响记录）：%r" % (e,))
            if full is not None:
                arr_all = np.asarray(full)
                if arr_all.ndim == 3 and arr_all.shape[2] == 4:
                    arr_all = arr_all[:, :, :3]
                region = np.ascontiguousarray(
                    arr_all[hud["top"]:hud["top"] + hud["height"],
                            hud["left"]:hud["left"] + hud["width"]])
            else:
                arr_all = None
                region = self.g.grab_rgb(hud)
            f = {"t": time.perf_counter() - self.t0,
                 "frame_rgb": None,
                 "hud_region": region,
                 "hud_top": hud["top"], "hud_left": hud["left"], "hud_bar": self.hud_bar,
                 # 当前这一帧用的框（诊断/对账用；框与 bar 必须同源，见 S1 注释）
                 "hud_box": (hud["top"], hud["left"],
                             hud["top"] + hud["height"], hud["left"] + hud["width"]),
                 # 画面里到底有没有数字（与"我们选的框读没读到"是两件事）——
                 # P1 用它当"立刻重定位"的触发条件，见 note_hud_result
                 "hud_has_ink": hud_has_ink(region),
                 "hud_src": self.hud_src,
                 "axis_rgb": self.g.grab_rgb(self.g.regions["axis"]) if read_axis else None,
                 "axis_geom": self.axis_geom,
                 # T2 认脸要用：轴区域在原帧里的左上角（实时抓的是 x60~340 那条区域）
                 "axis_offset": (self.g.regions["axis"]["left"], self.g.regions["axis"]["top"]),
                 "read_axis": read_axis}
            self.n += 1
            # 落盘取证帧（与上面的读数**同源像素**）
            if arr_all is not None:
                try:
                    from PIL import Image
                    os.makedirs(self.dump_frames, exist_ok=True)
                    p = os.path.join(self.dump_frames,
                                     "live_%08.2f.jpg" % (time.perf_counter() - self.t0))
                    Image.fromarray(np.ascontiguousarray(arr_all)).save(
                        p, quality=88, subsampling=0)
                    self.n_dump += 1
                except Exception as e:
                    print("  ⚠️ 落盘整屏帧失败（不影响记录）：%r" % (e,))
            # ⭐ P1 安全网：**每 5 秒**无条件拿一次画面证据复核框（约 10~30ms → 占 0.5% 预算）。
            #    为什么不能只在"读不到"时做：还有一种危险情况是"框是错的、但读出一个**看着
            #    像数**的值"（旧文档里 `53438` 这种），它会让 `ok=True`、永远不会触发重定位
            #    → 数字会动，但全错。本项目最危险的失败模式正是"跑得起来但结论是错的"。
            now = time.perf_counter()
            if now - self._last_periodic >= 5.0:
                self._last_periodic = now
                self._last_try = now
                self.relocate(verbose=True)
            # ⭐ P1 取证：按秒落盘整屏帧 —— **已移到抓屏那一步**（与读数同源像素，
            #    见上面"取证对齐"的注释）。这里不再单独抓一次整屏。
            # 帧源自身耗时（抓屏 + 墨迹判定 + 定位 + 取证落盘）→ 计入 ms["frame"]，
            # 否则"单帧 <100ms"这条会漏掉抓屏本身（过去就是这么漏的）
            f["src_ms"] = (time.perf_counter() - _ts) * 1000.0
            yield f

    def note_hud_result(self, ok, has_ink=False):
        """主循环把"HUD 这一帧读到没有 / 画面里有没有数字"告诉这里，决定要不要立刻重定位。

        ⚠️【P1 实机定案 2026-10-02】三件事缺一不可：
          1. **`ok` 必须是"完整数字"**（`reader.read_is_reliable`：非空、不含 `?`、nbad=0）。
             旧写法只看"文本非空"，而错误的框给出的是一串 `?????` —— **非空** →
             被当成"读到了" → 永不重定位 → 用户看到的就是「数字动都不动、一直待复核」。
          2. **画面里已经有数字（`has_ink`）却读不出可信读数** → 立刻重定位（半秒限速）。
             这正是"进战前启动"那一类：开局没有墨迹、只能退回模型那一对，
             数字一出现就马上切到正确的那一对。
          3. 读不到时的兜底（每 ~1.5 秒一次）；"看着像数但其实是错的"由 `frames()` 里
             每 5 秒一次的定期复核兜住。
        """
        if ok:
            self._fails = 0
            if not self._ever_reliable:
                self._ever_reliable = True
                # 第一次读到**完整数字** → 这一对 (框, bar) 才是可信的，记下来给下次开局直接用
                if self.use_calib and self.hud_src == "ink" and self.hud_geom \
                        and self._box_plausible(self.hud_geom.get("box")):
                    self.save_calib(self.hud_geom["box"], self.hud_bar)
                    print("  ✓ 已把这一对 (框, bar) 落盘为标定（下次进战前启动直接就用它）")
            return
        self._fails += 1
        now = time.perf_counter()
        if (has_ink and now - self._last_try >= 0.5) or \
           (self._fails % 90 == 0 and now - self._last_try >= 1.0):
            self._last_try = now
            self._last_periodic = now
            self.relocate(verbose=True)

    def close(self):
        try:
            self.g.close()
        except Exception:
            pass


# ══════════════════════════════ 标定文件（P1）══════════════════════════════
# 为什么放在模块级（而不是 ScreenSource 的方法里）：`--selftest` 要能在**没有屏幕**的情况下
# 验证"读写往返 + 分辨率不一致要作废"这两条；打 exe 后自检也才能覆盖它。
def calib_load(path, screen):
    """读标定文件 → {box, bar, region}；不存在 / 分辨率不一致 / 内容不合法 → None。"""
    try:
        if not os.path.exists(path):
            return None
        d = json.load(open(path, encoding="utf-8"))
        if [int(v) for v in d.get("screen", [])] != [int(screen[0]), int(screen[1])]:
            return None                      # 换了屏幕/窗口大小 → 那一对框不可用
        box = tuple(int(v) for v in d["box"])
        bar = tuple(int(v) for v in d["bar"])
        if len(box) != 4 or len(bar) != 2 or box[0] >= box[2] or box[1] >= box[3]:
            return None
        y0, x0, y1, x1 = box
        return {"box": (y0, x0, y1, x1), "bar": bar,
                "region": {"left": x0, "top": y0,
                           "width": int(max(1, x1 - x0)), "height": int(max(1, y1 - y0))}}
    except Exception:
        return None


def calib_save(path, screen, box, bar):
    """写标定文件（成功返回 True；目录只读等失败返回 False，调用方不该因此报错）。"""
    try:
        y0, x0, y1, x1 = (int(v) for v in box)
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        json.dump({"screen": [int(screen[0]), int(screen[1])],
                   "box": [y0, x0, y1, x1], "bar": [int(v) for v in bar],
                   "right": x1, "ts": time.strftime("%Y-%m-%d %H:%M:%S")},
                  open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return True
    except Exception:
        return False


# ══════════════════════════════ 主循环 ══════════════════════════════
def run(a):
    # 倒计时：给你时间切回游戏（一执行命令，焦点就离开游戏了，mss 会抓到别的窗口）
    if a.countdown and a.countdown > 0 and not a.replay:
        for i in range(int(a.countdown), 0, -1):
            print("  %d 秒后开始采集…（现在切回游戏）" % i, flush=True)
            time.sleep(1)

    # ⭐ P1 安全网（**只给实机开**）：读数 `?` 之外再加一道"段宽/墨迹跨度"闸，
    #    拦住"看着像数、其实是动画里切出来的小块"这种**自信的错值**
    #    （用户核对时抓到的实机反例：画面 `630911` 被读成 `1`）。
    #    回放不加，保持与权威离线表逐帧一致 —— 理由见 mvp/reader.py 的 INK_SPAN_GUARD。
    perc = Perceiver(backend=a.backend, conf_min=a.conf_min,
                     span_guard=not bool(a.replay))
    eng = LiveEngine()
    ov = None
    if a.overlay:
        from mvp.overlay import Overlay
        ov = Overlay(x=a.pos[0], y=a.pos[1], alpha=a.alpha, hotkey=a.hotkey,
                     debug=a.debug, scale=a.scale)
        ov.update(eng.state(debug=a.debug))
        # ⭐ P1 实机定案（2026-10-02）：悬浮窗必须**对抓屏不可见**，否则它自己会盖住
        #    左上角的行动轴 → 顶端卡识别 0 → 每条事件都 review → 合计恒 0（用户实际症状）。
        print("悬浮窗：对抓屏不可见(capture-hidden) = %s%s"
              % ("是 ✓" if getattr(ov, "capture_hidden", False) else "**否** ✗",
                 "" if getattr(ov, "capture_hidden", False)
                 else "（抓屏会把悬浮窗也拍进去 → 若它压着行动轴，行动者会一直认不出；"
                      "解决办法：用 --pos 把悬浮窗挪开）"))
    dump = None
    if a.dump_readings:
        os.makedirs(os.path.dirname(os.path.abspath(a.dump_readings)) or ".", exist_ok=True)
        dump = open(a.dump_readings, "w", newline="", encoding="utf-8-sig")
        csv.writer(dump).writerow(ROW_COLS)
    # ⭐ P1：诊断表（**与 --dump-readings 分开**，因为它多几列、不参与离线对账口径）
    diag = None
    if getattr(a, "dump_diag", None):
        os.makedirs(os.path.dirname(os.path.abspath(a.dump_diag)) or ".", exist_ok=True)
        diag = open(a.dump_diag, "w", newline="", encoding="utf-8-sig")
        csv.writer(diag).writerow(DIAG_COLS)

    if a.replay:
        src = ReplaySource(a.replay, a.range[0], a.range[1], a.step, hud_mode=a.hud_mode)
        axis_every = 1 if a.axis_every is None else a.axis_every
        print("回放 %s：%d 帧（t=%.1f~%.1f，step=%s，HUD 模式=%s，行动轴每 %d 帧读一次）"
              % (a.replay, len(src), a.range[0], a.range[1], a.step or "全部", a.hud_mode,
                 axis_every))
    else:
        src = ScreenSource(axis_every=(5 if a.axis_every is None else a.axis_every),
                           calibrate=a.calibrate, use_calib=not getattr(a, "no_calib", False),
                           dump_frames=getattr(a, "dump_frames", None),
                           dump_frames_every=getattr(a, "dump_frames_every", 3.0))
        axis_every = src.axis_every
        print("实时抓屏：%d 秒（Ctrl+C 可提前结束）" % a.seconds if a.seconds else
              "实时抓屏：直到 Ctrl+C")
        # ⭐ 开局等待游戏画面（解决"一直是待复核"）：
        #    启动那一刻用户往往还没切回游戏，若此时定框就会一直读不到。
        # ⚠️ 起手时序（用户 2026-10-01 明确要求）：
        #    "我用的时候是在**进战前开始的**，这样能保证所有的伤害能被记录"
        #    ⇒ 进战前还没有伤害数字 → 没有墨迹 → 定位必然失败，
        #      所以这里**绝不能阻塞等待**。只顺手试一次（默认 3 秒），
        #      然后用兜底框立即开始记录；第一帧读到数字时
        #      `note_hud_result` 会触发重定位，自动切到正确的动态框。
        if ov is not None:
            ov.update({"rows": [], "total": 0, "actor_owner": None,
                       "dps_line": "正在准备（首次读到数字后自动定位）…", "debug": ""})
            ov.pump()
        src.wait_for_game(timeout=float(getattr(a, "wait_game", 3.0) or 0),
                          verbose=True)

    # ⭐ P1 兜底：万一这台机器设不上"对抓屏隐身"，而悬浮窗又压着行动轴 → 明确警告。
    #    为什么查：用户 2026-10-02 的实际症状就是"悬浮窗盖住左上角行动轴 → 行动者认不出
    #    → 每条事件都 review → 合计恒 0"。抓屏隐身是首选修法，挪开位置是兜底办法。
    if ov is not None and not getattr(ov, "capture_hidden", False):
        try:
            rx = ov.root.winfo_rootx()
            ry = ov.root.winfo_rooty()
            rw, rh = ov.root.winfo_width(), ov.root.winfo_height()
            ax = (src.g.regions or {}).get("axis") or {}
            if ax and not (rx + rw < ax["left"] or rx > ax["left"] + ax["width"]
                           or ry + rh < ax["top"] or ry > ax["top"] + ax["height"]):
                print("  ⚠️⚠️ 悬浮窗(%d,%d %dx%d)压着行动轴区域 %s，而它**没能**对抓屏隐身"
                      " → 行动者会一直认不出（事件全 review、合计恒 0）。"
                      "请用 --pos 把它挪开（例如 --pos 1500,1450）"
                      % (rx, ry, rw, rh, ax))
        except Exception:
            pass

    ms = {"frame": [], "src": [], "hud": [], "axis": [], "engine": [], "ui": []}    # ⭐ P1 统计：验收要求"哪种帧读不出来要**可计数**"，不是"有时候不行"
    st_n = {"frame": 0, "text": 0, "reliable": 0, "hasq": 0, "nog": 0, "ink": 0,
            "axis_read": 0, "axis_unit": 0, "suspect": 0}
    st_src = {}
    t_start = time.perf_counter()
    t_last_log = t_start
    n_frame = 0
    n_new = 0
    prev_t = None
    try:
        while True:
            for f in src.frames():
                t0 = time.perf_counter()
                read_axis = bool(f.get("read_axis", True)) and (f["axis_rgb"] is not None) \
                    and (n_frame % axis_every == 0)
                row = perc.read(f["t"], frame_rgb=f["frame_rgb"], region_rgb=f["hud_region"],
                                top=f["hud_top"], left=f["hud_left"], bar_rows=f["hud_bar"],
                                axis_rgb=f["axis_rgb"], axis_geom=f.get("axis_geom"),
                                axis_offset=f.get("axis_offset", (0, 0)),
                                read_axis=read_axis, want_lm=bool(dump))
                t1 = time.perf_counter()
                # 把"这一帧读没读到**完整数字** / 画面里有没有数字"告诉帧源，决定要不要重定位。
                # ⚠️【P1 实机定案】这里以前传的是 `bool(text)` —— 而错误的框给的是 `?????`，
                #    非空 → 被当成读到了 → 永不重定位 → "数字动都不动、一直待复核"。
                ok = read_is_reliable(row)
                if hasattr(src, "note_hud_result"):
                    src.note_hud_result(ok, has_ink=bool(f.get("hud_has_ink")))
                new = eng.add(row)
                t2 = time.perf_counter()
                if dump is not None:
                    csv.writer(dump).writerow(perc.as_csv_row(row))
                # ── P1 统计（验收要求"哪种帧读不出来要**可计数**"）──
                txt = str(row.get("text") or "")
                st_n["frame"] += 1
                st_n["text"] += 1 if txt.strip() else 0
                st_n["reliable"] += 1 if ok else 0
                st_n["hasq"] += 1 if "?" in txt else 0
                st_n["nog"] += 1 if int(row.get("n") or 0) == 0 else 0
                st_n["ink"] += 1 if f.get("hud_has_ink") else 0
                st_n["axis_read"] += 1 if read_axis else 0
                st_n["axis_unit"] += 1 if (read_axis and row.get("unit")) else 0
                st_n["suspect"] += 1 if row.get("suspect") else 0
                k_src = str(f.get("hud_src") or "?")
                st_src[k_src] = st_src.get(k_src, 0) + 1
                if diag is not None:
                    csv.writer(diag).writerow(
                        [round(row["t"], 3), txt, row["n"], row["nbad"], row["conf"],
                         1 if "?" in txt else 0, 1 if f.get("hud_has_ink") else 0,
                         f.get("hud_src") or "",
                         ",".join(str(int(v)) for v in (f.get("hud_box") or ())),
                         ",".join(str(int(v)) for v in (f.get("hud_bar") or ())),
                         row.get("suspect") or "",
                         1 if read_axis else 0,
                         row.get("unit") or "", row.get("owner") or "", row["score"],
                         row["margin"], row.get("marker") or "", row.get("card_type") or "",
                         round((t2 - t0) * 1000.0, 2),
                         round(row["ms"].get("hud", 0.0), 2),
                         round(row["ms"].get("axis", 0.0), 2), 1 if ok else 0])
                n_new += len(new)
                for e in new:
                    print("  [%7.2fs] 事件 #%-3d %-4s %12s  %s%s"
                          % (e["t_last"], e["event"], e["owner"] or "(未定)",
                             format(int(e["damage_max"]), ","),
                             (e["unit"] + "/") if e["unit"] else "",
                             "  quality=%s status=%s" % (e["quality"], e["status"])
                             if e["status"] != "ok" else ""))
                if ov is not None:
                    ov.update(eng.state(debug=a.debug))
                    t3 = time.perf_counter()
                    ms["ui"].append((t3 - t2) * 1000)
                    if ov.should_quit():
                        print("收到退出热键 %s，收尾…" % a.hotkey)
                        raise KeyboardInterrupt
                else:
                    t3 = t2
                n_frame += 1
                ms["src"].append(float(f.get("src_ms") or 0.0))
                ms["frame"].append((t3 - t0) * 1000 + float(f.get("src_ms") or 0.0))
                ms["hud"].append(row["ms"]["hud"])
                if row["ms"]["axis"]:
                    ms["axis"].append(row["ms"]["axis"])
                ms["engine"].append((t2 - t1) * 1000)
                if a.replay and a.speed > 0 and prev_t is not None:
                    dt = (f["t"] - prev_t) / a.speed
                    if dt > 0:
                        time.sleep(dt)
                prev_t = f["t"]
                now = time.perf_counter()
                if a.no_log_interval <= 0 or now - t_last_log >= a.no_log_interval:
                    st = eng.state(debug=a.debug)
                    print("  t=%-7.2fs 当前行动 %-6s 合计 %12s  帧 %d  单帧 %.1fms %s"
                          % (f["t"], (st["actor_owner"] or "待复核"),
                             format(st["total"], ","), n_frame,
                             float(np.mean(ms["frame"][-30:])) if ms["frame"] else 0.0,
                             "  " + st["debug"] if a.debug else ""))
                    # ⭐ 2026-10-05：**把诊断计数也定期写进日志**。
                    # 起因：用户实机出问题时，统计只在会话**正常结束**时才打印 ——
                    # 中途关窗口/崩溃就**完全无据可查**（我因此只能猜，猜错过一轮）。
                    # 现在每 no_log_interval 秒把关键三行刷进日志，任何异常退出都留得下。
                    try:
                        _n = max(1, st_n["frame"])
                        print("      [诊断] 框来源=%s ｜ 可信读数 %d/%d=%.1f%% ｜ "
                              "行动轴 判出行动者 %d/%d=%.1f%% ｜ 事件 %d（待复核 %d）"
                              % (" ".join("%s:%d" % (k, v)
                                          for k, v in sorted(st_src.items())) or "无",
                                 st_n.get("reliable", 0), _n,
                                 100.0 * st_n.get("reliable", 0) / _n,
                                 st_n["axis_unit"], max(1, st_n["axis_read"]),
                                 100.0 * st_n["axis_unit"] / max(1, st_n["axis_read"]),
                                 st["n_events"], st["n_review"]))
                    except Exception as _e:              # noqa: BLE001
                        print("      [诊断] 计数失败: %s" % _e)
                    t_last_log = now
                if a.seconds and (time.perf_counter() - t_start) >= a.seconds:
                    raise KeyboardInterrupt
                if a.max_frames and n_frame >= a.max_frames:
                    raise KeyboardInterrupt
            break
    except KeyboardInterrupt:
        print("\n结束。")
    finally:
        new = eng.flush()
        n_new += len(new)
        for e in new:
            print("  [%7.2fs] 事件 #%-3d %-4s %12s  （收尾定稿）"
                  % (e["t_last"], e["event"], e["owner"] or "(未定)",
                     format(int(e["damage_max"]), ",")))
        if ov is not None:
            ov.update(eng.state(debug=a.debug))
            time.sleep(0.3)
            ov.destroy()
        if dump is not None:
            dump.close()
        if diag is not None:
            diag.close()
        src.close()

    # ── 汇总 ──
    rows, total = eng.totals()
    print("\n=== 按角色累计（口径：只算 status=ok，占比分母同）===")
    for r in rows:
        print("  %-6s %12s  %5.1f%%   %d 次" % (r["owner"], format(r["damage"], ","),
                                              r["pct"], r["n"]))
    print("  %-6s %12s" % ("合计", format(total, ",")))
    print("  %s" % eng.state()["dps_line"])
    print("  事件 %d（待复核 %d）｜定稿延迟 %.2fs｜重算 %d 次｜保险丝 %d 次"
          % (len(eng.events), sum(1 for e in eng.events if e["status"] == "review"),
             eng.lag, eng.n_pass, eng.n_stale_merge))

    # ── P1：读数可靠性统计（验收要求"可计数"，不是"有时候不行"）──
    print("\n=== HUD 读数可靠性（P1 · 可计数）===")
    n = max(1, st_n["frame"])
    _p = lambda k: "%5d / %-5d = %5.1f%%" % (st_n[k], st_n["frame"], 100.0 * st_n[k] / n)
    print("  采集帧数                    %d" % st_n["frame"])
    print("  画面里有黄墨迹              %s   ← 含「总伤害」标签/金线装饰，**不等于**有数字"
          % _p("ink"))
    print("  切出了字形（n>0）           %s" % ("%5d / %-5d = %5.1f%%"
          % (st_n["frame"] - st_n["nog"], st_n["frame"],
             100.0 * (st_n["frame"] - st_n["nog"]) / n)))
    print("  读到**完整数字**（可信读数）%s   ← 悬浮窗真正用得上的帧" % _p("reliable"))
    print("  含 '?' 的帧                 %s" % _p("hasq"))
    print("  其中「段宽/墨迹跨度」闸拦下 %s   ← 画面像在动画/字号变了时，宁可不给数"
          % _p("suspect"))
    print("  无字形（空）的帧            %s" % _p("nog"))
    print("  HUD 框来源分布              %s"
          % ("  ".join("%s %d" % (k, v) for k, v in sorted(st_src.items())) or "(无)"))
    if hasattr(src, "n_reloc"):
        print("  运行中重定位次数            %d（其中因「几何不符」先拒 %d 次、因同一框反复不符"
              "而强制采用 %d 次；落盘标定 %d 次 → %s）"
              % (src.n_reloc, getattr(src, "n_ink_rejected", 0), getattr(src, "n_forced", 0),
                 src.n_calib_saved, getattr(src, "CALIB", "-")))
    print("  行动轴：读了 %d 帧，判出行动者 %d 帧（%.1f%%）"
          % (st_n["axis_read"], st_n["axis_unit"],
             100.0 * st_n["axis_unit"] / max(1, st_n["axis_read"])))
    print("  ⚠️ 以上只说明「读到了几个数」，**不证明读数与屏幕一致** —— "
          "一致性必须用真值核对（`--dump-diag` 出表 + 人工对图），见 docs/实时链路与悬浮窗.md")
    if getattr(a, "dump_diag", None):
        print("  诊断逐帧表：%s" % a.dump_diag)
    if getattr(a, "dump_frames", None):
        print("  整屏取证帧：%s（%d 张，每 %.1fs 一张，JPEG q=88）"
              % (a.dump_frames, getattr(src, "n_dump", 0),
                 getattr(a, "dump_frames_every", 3.0)))
    if a.dump_readings:
        print("  逐帧读数表（对账口径，列同 frames_dense4）：%s" % a.dump_readings)

    print("\n=== 单帧耗时（验收第 4 条：<100ms）===")
    for k, label in (("frame", "抓屏+识别+更新"), ("src", "帧源(抓屏/定位)"), ("hud", "HUD 读数"),
                     ("axis", "抓/读行动轴"), ("engine", "事件引擎"), ("ui", "悬浮窗刷新")):
        if ms[k]:
            arr = np.asarray(ms[k])
            print("  %-16s 平均 %6.2fms  p50 %6.2fms  p95 %6.2fms  最大 %7.2fms  (%d 帧)"
                  % (label, arr.mean(), np.percentile(arr, 50), np.percentile(arr, 95),
                     arr.max(), arr.size))
    if ms["frame"]:
        p95 = float(np.percentile(np.asarray(ms["frame"]), 95))
        if a.replay:
            print("  → 回放模式：帧源是**读盘 PNG + 整帧动态定位**，不是实机路径，"
                  "本条（<100ms）不适用于回放；实机数字见 docs/实时链路与悬浮窗.md §5")
        else:
            print("  → p95 %s 100ms：%s" % ("<" if p95 < 100 else ">=",
                                            "达标" if p95 < 100 else "不达标"))
    return 0


def selftest():
    """打包自检：**不碰屏幕、不需要游戏**，检查"包内资源 + 模型 + 引擎"是不是都活着。

    为什么需要它：双击 exe 时看不到任何报错（尤其 `--noconsole` 版本）。
    exe 里跑 `live_mvp.exe --selftest` = 验证
      * 资源按 **exe 位置**解析到了（不是靠"当前目录恰好是仓库根"）；
      * onnxruntime 能在包里推理、行动轴/标记模板库能读出来；
      * 事件引擎（C 线判据）能 import 且自检通过；
      * **悬浮窗能真建出来**、四个扩展样式位（置顶/穿透/不抢焦点/半透明）读回正确
        —— 这一步会弹一个约 0.6 秒的窗口并在 CWD 存一张 `mvp_overlay_selftest.png`。
    注意：它**不验证识别正确率**（那要用真帧回放，见 docs/EXE打包.md 的验收命令）；
    也**不验证"游戏里看不看得见"**（独占全屏下截图里不含悬浮窗，见 MVP实施记录 §7 限制 5）。
    """
    print("=== 资源解析 ===")
    print(R.report())
    miss = R.missing()
    print("资源清单：%s" % ("全部就绪 ✓" if not miss else "缺少 %d 项 → %s ✗" % (len(miss), miss)))

    print("\n=== 依赖 ===")
    try:
        import torch  # noqa: F401
        print("  torch：**在包里**（打包时应该排除它；体积会到 800MB+，回 spec 的 excludes 查）")
    except Exception:
        print("  torch：不在包里 ✓（实时用 ONNX，不需要 torch）")

    print("\n=== 模型 ===")
    p = Perceiver(backend="onnx")
    print("  ONNX 模型：%s" % R.resource("out/digit_cnn.onnx"))
    # ⚠️ 2026-10-05：分类器改成**按字体档案取**（`_reader_for`），
    #    不再有 `p._onnx` 这个单一实例（实时链路要按行动者切档案）。
    rd = p._reader_for(p.profile)
    print("  会话已建立，输入名 %r" % rd.input)
    glyph = (np.random.RandomState(0).rand(34, 24).astype(np.float32), 30, 70)
    res = rd.classify([glyph])
    print("  推理跑通：随机字形 → digit=%d conf=%.3f（只证明能跑，不代表识别正确）"
          % (res[0][0], res[0][1]))
    # 顺带确认第二套字体档案也能加载（狼尊强普用）
    rd2 = p._reader_for("yinlang999")
    print("  第二套字体档案 yinlang999：%s" % ("已加载 ✓" if rd2 is not None else "不可用"))
    print("  行动轴模板库：%d 个单位 %s" % (len(p.bank), sorted(p.bank)))
    import axis_actor as T
    print("  左侧标记模板库：%s" % (sorted(T._marker_bank()) or "(空)"))

    print("\n=== 事件引擎（C 线判据，口径不许漂移）===")
    from mvp import engine as E
    E._selftest()

    print("\n=== P1：选框与重定位判据（不碰屏幕）===")
    p1_ok = _selftest_p1(p)
    print("  → %s" % ("P1 判据自检**通过** ✓" if p1_ok else "P1 判据自检**未通过** ✗"))

    print("\n=== 悬浮窗（置顶 + 鼠标穿透，真建一次窗口再读回样式）===")
    ov_ok = None
    try:
        import tempfile
        from mvp import overlay as OV
        shot = os.path.join(tempfile.gettempdir(), "mvp_overlay_selftest.png")   # 别在仓库/exe 目录拉屎
        ov_ok, info = OV.selftest(save=shot, seconds=0.6, verbose=False)
        print("  窗口矩形 %s @ %s，截图 %s" % (
            (info["rect"][2], info["rect"][3]), (info["rect"][0], info["rect"][1]), info["shot"]))
        print("  %s" % info["detail"])
        print("  → %s" % ("扩展样式位读回**通过** ✓（自动化能证明的就到这里；"
                          "'游戏里看不看得见'必须实机确认，见 docs/EXE打包.md §5）"
                          if ov_ok else "样式位没置全 ✗"))
    except Exception as e:
        # 无桌面会话（远程/服务）会建不出窗口 —— 不算打包失败，但必须说清楚
        print("  ⚠️ 建窗失败：%r" % (e,))
        print("  → 这一项**没有验证**（多半是没有桌面会话）；实机双击时再看")

    print("\n自检%s" % ("通过 ✓" if (not miss and ov_ok is not False and p1_ok)
                      else "**未通过**"))
    return 1 if (miss or ov_ok is False or not p1_ok) else 0


def _selftest_p1(perc=None):
    """P1 的判据自检（**不碰屏幕、不需要游戏**）—— 打包后的 exe 也跑这一段。

    验的都是"实机那次故障"的关键判据，任何一条坏了都会让"数字一直是待复核"复活：
      1. `read_is_reliable`：`?????` 必须算**不可信**（它非空，是"永不重定位"的机关）；
      2. `ink_geometry_ok`：**实机那种纯平移（Δy=+25、行带也跟着+25）必须放行**，
         而线7 算飞的那种（左缘差 276px）必须挡住；
      3. `hud_has_ink`：亮黄块 = 有数字，暗块 = 没有；
      4. 标定文件读写往返 + **分辨率不一致要作废**（否则换屏幕后会拿旧框读错）；
      5. ⭐ **真实实机帧端到端读数**（1.6MB 的帧随包发）：全链（选框 → 掩膜 → 分割 →
         ONNX 分类）必须读出真值 `73431`。这是"能推理"和"读得对"之间的那道坎。
    """
    ok = True
    from mvp.reader import (hud_has_ink, hud_region_for, ink_geometry_ok,
                            model_geometry, read_is_reliable, span_guard_hit)

    def chk(name, cond):
        nonlocal ok
        print("  %s %s" % ("✓" if cond else "✗", name))
        ok = ok and bool(cond)

    # ① 可信读数判据
    r_ok = {"text": "73431", "n": 5, "nbad": 0}
    r_q = {"text": "?????", "n": 5, "nbad": 5}
    r_part = {"text": "7?431", "n": 5, "nbad": 1}
    chk("read_is_reliable('73431', nbad=0) → 可信", read_is_reliable(r_ok))
    chk("read_is_reliable('?????', nbad=5) → **不可信**（关键：它非空）",
        not read_is_reliable(r_q))
    chk("read_is_reliable('7?431') → 不可信", not read_is_reliable(r_part))
    chk("read_is_reliable('') → 不可信", not read_is_reliable({"text": "", "nbad": 0}))

    # ② 平移闸：实机那一帧的三种几何（数字都来自实测）
    gm = model_geometry(1800, 2880)                      # (260,2353,340,2880) bar(298,310)
    g_real = {"box": (285, 2353, 365, 2880), "bar_rows": (323, 335), "k": 1.0014}
    g_wild = {"box": (257, 2074, 380, 2876), "bar_rows": (315, 333), "k": 1.52}
    g_barmoved = {"box": (260, 2353, 340, 2880), "bar_rows": (323, 335), "k": 1.0014}
    chk("ink_geometry_ok(模型框自己) → 放行（等价于没动）", ink_geometry_ok(gm, gm))
    chk("ink_geometry_ok(实机 +25px 纯平移) → **放行**（这是实机正确的那一对）",
        ink_geometry_ok(g_real, gm))
    chk("ink_geometry_ok(线7 算飞的框, 左缘差 276px) → **挡住**",
        not ink_geometry_ok(g_wild, gm))
    chk("ink_geometry_ok(只把行带挪走、框不动) → 挡住",
        not ink_geometry_ok(g_barmoved, gm))

    # ③ 画面里到底有没有数字（重定位触发条件）
    yellow = np.zeros((40, 60, 3), dtype=np.uint8)
    yellow[:, :, 0] = 230
    yellow[:, :, 1] = 225
    yellow[:, :, 2] = 120
    dark = np.zeros((40, 60, 3), dtype=np.uint8)
    dark[:, :, 0], dark[:, :, 1], dark[:, :, 2] = 40, 45, 60
    chk("hud_has_ink(亮黄块) → True", hud_has_ink(yellow))
    chk("hud_has_ink(暗块) → False", not hud_has_ink(dark))

    # ③b 「段宽/墨迹跨度」闸（合成）：实机 t=127.4 那种"画面宽、只切出一小块"必须判可疑
    wide = np.zeros((40, 500, 3), dtype=np.uint8)
    wide[:, 100:460, 0] = 230
    wide[:, 100:460, 1] = 225
    wide[:, 100:460, 2] = 120
    chk("span_guard_hit(墨迹跨 360px、只切出 1 块 33px) → 判可疑（实机 t=127.4：630911 被读成 1）",
        span_guard_hit(wide, [(0, 33, 65)]))
    chk("span_guard_hit(同一帧、切出 6 块 ≈198px) → 放行",
        not span_guard_hit(wide, [(0, 33, 65)] * 6))
    chk("span_guard_hit(墨迹本身就窄 120px) → 不做判断（两位数总伤也合法）",
        not span_guard_hit(wide[:, :120], [(0, 33, 65)]))

    # ④ 标定文件往返（含"换分辨率要作废"）
    #    ⚠️ 写在 RUNTIME_DIR/out/ 下（源码=仓库根；exe=exe 目录），**不写系统 temp**：
    #       一是 exe 装在被保护的目录时能立刻暴露"写不进去"，二是沙箱/受限环境里
    #       系统 temp 的子目录未必可写（本项目环境实测就是 PermissionError）。
    p = os.path.join(RUNTIME_DIR, "out", "_p1_selftest_calib.json")
    chk("calib_load(不存在的文件) → None",
        calib_load(p + ".nope", (2880, 1800)) is None)
    try:
        os.remove(p)
    except OSError:
        pass
    if not calib_save(p, (2880, 1800), (285, 2353, 365, 2880), (323, 335)):
        print("  ⚠️ 标定文件写不进去（目录只读？）→ **跳过**往返验证（不算失败，"
              "实机只影响「下次开局直接用上次标定」这一条优化）")
    else:
        got = calib_load(p, (2880, 1800))
        chk("calib_load 往返一致（框 / 行带 / 抓屏区域）",
            bool(got) and tuple(got["box"]) == (285, 2353, 365, 2880)
            and tuple(got["bar"]) == (323, 335)
            and got["region"] == {"left": 2353, "top": 285, "width": 527, "height": 80})
        chk("分辨率变了 → 标定作废（返回 None）", calib_load(p, (1920, 1080)) is None)
        try:
            os.remove(p)
        except OSError:
            pass

    # ⑤ ⭐ 真实实机帧的端到端读数（这一帧随包发，所以 exe 里也能跑）
    try:
        from PIL import Image
        fx = R.resource("out/real_frames/live_2880x1800_73431_q88.jpg")
        if not os.path.exists(fx):
            print("  ⚠️ 找不到实机帧素材 %s → **跳过**端到端读数断言" % fx)
        else:
            arr = np.asarray(Image.open(fx).convert("RGB"))
            reg, bar, geom = hud_region_for(arr.shape, use_ink=True, frame_rgb=arr)
            y0, x0 = reg["top"], reg["left"]
            crop = np.ascontiguousarray(arr[y0:y0 + reg["height"], x0:x0 + reg["width"]],
                                       dtype=np.int16)
            rd = perc if perc is not None else Perceiver(backend="onnx")
            row = rd.read(0.0, region_rgb=crop, top=y0, left=x0, bar_rows=bar,
                          read_axis=False)
            chk("实机帧（%s）读出 73431 [实得 %r，来源 %s，框 %s bar %s]"
                % (os.path.basename(fx), row["text"], geom.get("src"), geom.get("box"), bar),
                read_is_reliable(row) and row["text"] == "73431")
    except Exception as e:
        chk("实机帧端到端读数（异常 %r）" % (e,), False)
    return ok


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="HSR 伤害统计 MVP —— 实时悬浮窗")
    ap.add_argument("--replay", default=None, help="回放帧目录（如 frames/glyphcache）")
    ap.add_argument("--range", default="98,340", help="回放帧号范围 lo,hi")
    ap.add_argument("--step", type=float, default=0.0, help="只回放该秒网格上的帧（0=全部）")
    ap.add_argument("--hud-mode", choices=("frame", "region"), default="region",
                    help="region=按分辨率缩放的参考框（= 离线权威口径，生产用）；"
                         "frame=整帧+墨迹定位（实测会掉分，仅对照用）")
    ap.add_argument("--calibrate", action="store_true",
                    help="实时模式改用 line7 墨迹定位（多分辨率试验；HUD 侧实测会掉分）")
    ap.add_argument("--speed", type=float, default=0.0, help="回放倍速（0=全速）")
    ap.add_argument("--seconds", type=float, default=0.0, help="实时模式时长（0=直到 Ctrl+C）")
    ap.add_argument("--wait-game", type=float, default=3.0,
                    help="开局顺手试定位的秒数（不阻塞；默认 3）。进战前开始记录时设 0 即可")
    ap.add_argument("--countdown", type=float, default=0.0,
                    help="启动前倒计时秒数（给你时间切回游戏；0=不等）")
    ap.add_argument("--max-frames", type=int, default=0)
    ap.add_argument("--axis-every", type=int, default=None,
                    help="每 N 帧读一次行动轴（实时默认 5，回放默认 1）")
    ap.add_argument("--backend", choices=("onnx", "torch"), default="onnx",
                    help="HUD 分类器后端（实时用 onnx）")
    ap.add_argument("--conf-min", type=float, default=0.55)
    ap.add_argument("--overlay", dest="overlay", action="store_true", default=True)
    ap.add_argument("--no-overlay", dest="overlay", action="store_false")
    ap.add_argument("--pos", default="40,40", help="悬浮窗位置 x,y")
    ap.add_argument("--alpha", type=float, default=0.85)
    ap.add_argument("--scale", type=float, default=1.0, help="字号缩放")
    ap.add_argument("--hotkey", default="ctrl+alt+q", help="退出热键（空串=不要热键）")
    ap.add_argument("--debug", action="store_true", help="悬浮窗显示调试脚注")
    ap.add_argument("--no-log-interval", type=float, default=2.0, help="终端状态行间隔秒（0=关）")
    ap.add_argument("--dump-readings", default=None, help="把逐帧读数写成 CSV（对账用）")
    ap.add_argument("--dump-diag", default=None,
                    help="P1 逐帧诊断表（框来源/框坐标/有没有墨迹/含不含 ?/耗时）；"
                         "与 --dump-readings 分开，保证对账口径的列不变")
    ap.add_argument("--no-calib", action="store_true",
                    help="不要读写 out/live_calib.json（P1 的「上次标定框」缓存）")
    ap.add_argument("--dump-frames", default=None, metavar="DIR",
                    help="P1 取证：按秒把**整屏帧**落盘成 JPEG（离线出核对图、让用户读数）")
    ap.add_argument("--dump-frames-every", type=float, default=3.0,
                    help="整屏帧落盘间隔秒（默认 3）")
    ap.add_argument("--selftest", action="store_true",
                    help="打包/安装自检：资源解析 + ONNX + 模板库 + 引擎口径（不碰屏幕，不看识别正确率）")
    a = ap.parse_args(argv)
    a.range = tuple(float(x) for x in str(a.range).split(","))
    a.pos = tuple(int(x) for x in str(a.pos).split(","))
    return a


def main(argv=None):
    R.setup_console()          # 打包后控制台默认 GBK，先把输出切 UTF-8（否则 print ✓ 会崩）
    a = parse_args(argv)
    if a.selftest:
        return selftest()
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
