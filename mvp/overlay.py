# -*- coding: utf-8 -*-
"""[MVP] 悬浮窗：**置顶 + 鼠标穿透**，显示 4 个角色的累计伤害/占比/总和/当前行动者。

Windows 实现要点（都是实测踩过坑的）：
  * **先声明 DPI 感知**再建窗口：不声明时 Tk 与 `GetSystemMetrics` 都按逻辑像素算，
    窗口会被系统缩放搬到别处（B 线抓屏踩过同一个坑，见 `capture.enable_dpi_awareness`）。
  * 鼠标穿透 = 扩展样式 `WS_EX_LAYERED | WS_EX_TRANSPARENT`（`ctypes` 调
    `SetWindowLongPtrW`）。⚠️ 必须设 `argtypes/restype`：不设时 ctypes 默认按 32 位
    处理 `HWND`，在 64 位进程上会把句柄截断。
  * 不抢焦点 = `WS_EX_NOACTIVATE`；不进 Alt-Tab = `WS_EX_TOOLWINDOW`。
  * 穿透之后**点不到窗口**，所以退出只能靠热键/终端：
    本实现用 `GetAsyncKeyState` **轮询**全局按键（零依赖，不需要 keyboard/pynput，
    也不需要注册窗口消息），默认 `Ctrl+Alt+Q`；终端里 Ctrl+C 也有效。
  * 悬浮窗只显示、不判断：所有数字都来自 `mvp/engine.py` 的状态字典。

自检（不需要游戏、不需要悬浮窗被点到）：
    python mvp/overlay.py --selftest
它会把窗口真的建出来 → 读回扩展样式断言四个位都置上了 → 截一张屏存成 PNG → 退出。
"""
from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

GA_ROOT = 2

# 全局热键用的虚拟键码（只列需要的）
VK = {"ctrl": 0x11, "control": 0x11, "alt": 0x12, "menu": 0x12, "shift": 0x10,
      "win": 0x5B, "escape": 0x1B, "esc": 0x1B, "space": 0x20}
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
    VK[_c.lower()] = ord(_c)

FONT_CANDIDATES = ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "SimSun")

DEFAULT_TITLE = "HSR 伤害统计（MVP）"

# ══════════════════════════════════════════════════════════════════════
#  配色（实机教训 2026-10-01，经用户两次屏幕反馈修正）
#
#  用户反馈 1："悬浮窗是纯黑"（原配色 bg=#252a3d 约 6% 亮度 + alpha 0.85）。
#  用户反馈 2（关键）："你中间有一步对了，其他都是全黑" ——
#    那次"对了"的是**亮绿 #00ff00 / 亮青 #00e5ff** 的测试窗口，
#    而深色系（#252a3d 约 17%、#3d4463 约 27%）**在用户实际屏幕上全看成纯黑**。
#  ⇒ 结论：在"暗色游戏画面 + 该显示器伽马/对比设置"下，**深色一律不可辨**，
#    必须用**浅底深字**（背景亮度 ~85%+）。
#
#  另外记一个自身 bug（导致前面几轮误判）：测试脚本 `paint()` 只改了**一层**子控件，
#  没递归到 outer→grid→Label 内部，所以那几档"不同配色"其实卡片内部一直是深色 ——
#  测试本身是无效的。改配色时必须**递归整棵控件树**。
# ══════════════════════════════════════════════════════════════════════
CHROMA = "#ff00fe"        # 透明键色（几乎不会与 UI 撞色的品红）
BG = "#e9edf7"            # 卡片背景：浅灰白（亮，暗色游戏上极醒目）
BG_LINE = "#8a93b0"       # 分隔线 / 边框
FG = "#141826"            # 主文字：近黑（浅底上对比强）
FG_DIM = "#3b4666"        # 次要文字（占比、脚注）
FG_ACTOR = "#a8480f"      # "当前行动"：深橙（浅底上可读）


def parse_hotkey(spec):
    """'ctrl+alt+q' → [VK...]；空/None → None（关闭热键）。"""
    if not spec:
        return None
    keys = []
    for part in str(spec).replace(" ", "").split("+"):
        if not part:
            continue
        if part.lower() not in VK:
            raise ValueError("不认识的热键键名 %r（可用：ctrl/alt/shift/win/字母/数字/esc）" % part)
        keys.append(VK[part.lower()])
    return keys or None


class _Win32:
    """SetWindowLongPtrW / GetWindowLongPtrW 的 64 位安全封装。"""

    def __init__(self):
        self.user32 = ctypes.windll.user32
        ptr = getattr(self.user32, "GetWindowLongPtrW", None)
        if ptr is not None:
            self.get = ptr
            self.set = self.user32.SetWindowLongPtrW
            self.get.restype = ctypes.c_ssize_t
            self.set.restype = ctypes.c_ssize_t
            self.get.argtypes = [ctypes.c_void_p, ctypes.c_int]
            self.set.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        else:                                    # 32 位
            self.get = self.user32.GetWindowLongW
            self.set = self.user32.SetWindowLongW
            self.get.restype = ctypes.c_long
            self.set.restype = ctypes.c_long
            self.get.argtypes = [ctypes.c_void_p, ctypes.c_int]
            self.set.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]

    def ex_style(self, hwnd):
        return int(self.get(int(hwnd), GWL_EXSTYLE)) & 0xFFFFFFFF

    def add_ex_style(self, hwnd, bits):
        cur = self.ex_style(hwnd)
        self.set(int(hwnd), GWL_EXSTYLE, cur | int(bits))
        return self.ex_style(hwnd)

    def roots(self, hwnd):
        """给一个 Tk 子窗口句柄，返回它和它的顶层祖先（去重）。"""
        out = [int(hwnd)]
        p = int(self.user32.GetParent(int(hwnd)) or 0)
        if p and p not in out:
            out.append(p)
        g = int(self.user32.GetAncestor(int(hwnd), GA_ROOT) or 0)
        if g and g not in out:
            out.append(g)
        return out


class Overlay:
    """置顶 + 鼠标穿透的统计悬浮窗。单线程使用（同一线程里 `update()`）。"""

    ROW_SLOTS = 6            # 最多显示 6 行（MVP 队伍 4 行 + 余量）

    def __init__(self, x=40, y=40, alpha=1.0, click_through=True, topmost=True,
                 hotkey="ctrl+alt+q", scale=1.0, title=DEFAULT_TITLE, debug=False,
                 overrideredirect=True, closable=False):
        """closable=True：**不**鼠标穿透、**保留标题栏** → 可以直接点 × 关闭。

        用途：调试/让用户确认窗口长什么样时用（穿透窗口点不到，用户会说"关不掉"）。
        """
        from capture import enable_dpi_awareness
        enable_dpi_awareness()               # ⚠️ 必须在建窗口之前
        import tkinter as tk
        from tkinter import font as tkfont

        if closable:
            click_through = False
            overrideredirect = False

        self.tk = tk
        self.hotkey = parse_hotkey(hotkey)
        self.quit_requested = False
        self.click_through = click_through
        self.topmost = topmost
        self.debug = debug
        self.scale = float(scale)
        self.hwnds = []
        self.style_report = {}

        self.root = tk.Tk()
        self.root.title(title)
        if overrideredirect:
            self.root.overrideredirect(True)      # 无边框（本来也点不到）
        # ⚠️⚠️【实机教训 2026-10-01 三次修正 —— 必读】⚠️⚠️
        # 用户实测反馈："这个弹窗还是半透明的纯黑啊，而且现在关不掉"
        #
        # 事实：窗口**确实显示了**（用户能看到），但背景是**半透明纯黑**，
        # 而不是我们设的浅色 `BG`。说明 **`-transparentcolor` / `-alpha`
        # 这两个属性会破坏 Tk 的渲染**（把卡片画成黑的）。
        #
        # ⇒ 结论（按可靠性排序）：
        #   ① **不要用 `-transparentcolor`**（Tk 的键色抠图与 layered 窗口叠加会画黑）；
        #   ② **不要用整窗 `-alpha`**（同样会把内容压成半透明黑）；
        #   ③ 就用**最朴素的不透明窗口 + 明亮背景**（BG 浅灰白）——
        #      用户能看见窗口这件事已经证明"显示本身没问题"，
        #      唯一要保证的是**背景别是深色**。
        #
        # 另外：用户遇到"关不掉"。鼠标穿透后点不到窗口，只能靠热键/终端。
        # 本实现保留 `Ctrl+Alt+Q` 热键 + 终端 Ctrl+C；`closable=True` 时
        # 不设鼠标穿透，可以直接点标题栏关闭（调试用）。
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", bool(topmost))
        # `-alpha` 仅在显式要求半透明时设置；默认 1.0 完全不透明。
        if float(alpha) < 1.0:
            self.root.attributes("-alpha", float(alpha))
        self.transparent_ok = False           # 明确：本版本不使用键色透明
        self.root.geometry("+%d+%d" % (int(x), int(y)))

        fams = set(tkfont.families())
        family = next((f for f in FONT_CANDIDATES if f in fams), "TkDefaultFont")
        base = max(9, int(round(12 * self.scale)))
        big = max(10, int(round(15 * self.scale)))
        self.f_name = tkfont.Font(family=family, size=base)
        self.f_num = tkfont.Font(family=family, size=base)
        self.f_head = tkfont.Font(family=family, size=big, weight="bold")
        self.f_foot = tkfont.Font(family=family, size=max(7, base - 3))

        self._build()
        self.root.update_idletasks()
        self._window_size = (self.root.winfo_width(), self.root.winfo_height())
        self._apply_win32()
        self._last_key_state = False
        self._t0 = time.perf_counter()
        self._n_updates = 0
        self.after_id = None
        if self.hotkey:
            self._poll_hotkey()

    # ────────────────────────── 界面 ──────────────────────────
    def _build(self):
        tk = self.tk
        pad = max(4, int(6 * self.scale))
        # ⚠️ root 用**透明键色** CHROMA，同时 `-transparentcolor` 把该色抠成透明；
        #    卡片本体（outer）用不透明的 BG —— 这样背景不会变成"一块黑"。
        outer = tk.Frame(self.root, bg=BG, highlightthickness=2,
                         highlightbackground=BG_LINE)
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        self.lbl_actor = tk.Label(outer, text="当前行动: 待复核", font=self.f_head,
                                  fg=FG_ACTOR, bg=BG, anchor="w", padx=pad, pady=pad)
        self.lbl_actor.pack(fill="x")
        tk.Frame(outer, bg=BG_LINE, height=1).pack(fill="x", padx=pad)

        grid = tk.Frame(outer, bg=BG)
        grid.pack(fill="x", padx=pad, pady=pad)
        self.row_widgets = []
        for i in range(self.ROW_SLOTS):
            n = tk.Label(grid, text="", font=self.f_name, fg=FG, bg=BG,
                         anchor="w", width=6)
            d = tk.Label(grid, text="", font=self.f_num, fg=FG, bg=BG,
                         anchor="e", width=13)
            p = tk.Label(grid, text="", font=self.f_num, fg=FG_DIM, bg=BG,
                         anchor="e", width=7)
            n.grid(row=i, column=0, sticky="w")
            d.grid(row=i, column=1, sticky="e")
            p.grid(row=i, column=2, sticky="e", padx=pad)
            self.row_widgets.append((n, d, p))

        tk.Frame(outer, bg=BG_LINE, height=1).pack(fill="x", padx=pad)
        self.lbl_total = tk.Label(outer, text="合计  0", font=self.f_head, fg=FG,
                                  bg=BG, anchor="w", padx=pad, pady=pad)
        self.lbl_total.pack(fill="x")
        tk.Frame(outer, bg=BG_LINE, height=1).pack(fill="x", padx=pad)
        self.lbl_dps = tk.Label(outer, text="每行动值伤害  —", font=self.f_num,
                                fg=FG_DIM, bg=BG, anchor="w", padx=pad, pady=pad)
        self.lbl_dps.pack(fill="x")
        self.lbl_foot = tk.Label(outer, text="", font=self.f_foot, fg=FG_DIM,
                                 bg=BG, anchor="w", padx=pad, pady=pad)
        if self.debug:
            self.lbl_foot.pack(fill="x")

    # ────────────────────────── Win32 扩展样式 ──────────────────────────
    def _apply_win32(self):
        """只加**必要的**扩展样式。

        ⚠️⚠️【实机教训 2026-10-01 四次修正 —— 找到真凶】⚠️⚠️
        用户描述："一个正方形不透明黑色，右边有一段残留" ——
        这是 **`WS_EX_LAYERED` 没被正确填充**的典型症状：
        DWM 把窗口当作 layered 表面，而 Tk 用普通 GDI 绘制，
        两者不匹配 → 合成出来就是**纯黑**（用 PrintWindow 抓窗口自身缓冲
        却是正常的，所以之前一直查不出来）。

        关键事实：**鼠标穿透只需要 `WS_EX_TRANSPARENT`，不需要 `WS_EX_LAYERED`。**
        `LAYERED` 只是"不透明模式"（我们不用它的 alpha / 键色），反而会破坏渲染。

        ⇒ 修法：**不再加 `WS_EX_LAYERED`**。
        保留：TRANSPARENT（鼠标穿透）、NOACTIVATE（不抢焦点）、
              TOOLWINDOW（不进 Alt-Tab）、TOPMOST（置顶）。
        """
        self.w32 = _Win32()
        bits = WS_EX_TOOLWINDOW
        if self.click_through:
            bits |= WS_EX_TRANSPARENT
        bits |= WS_EX_NOACTIVATE
        if self.topmost:
            bits |= WS_EX_TOPMOST
        wid = self.root.winfo_id()
        self.hwnds = self.w32.roots(wid)
        for h in self.hwnds:
            # ⚠️ 关键：**主动清除** `WS_EX_LAYERED`，而不只是"不添加"。
            # 实测：Tk 的**顶层窗口**自己就带 LAYERED
            #   （诊断输出：句柄1 exstyle=0x080800A8 含 LAYERED，而句柄0 不含）。
            # 而 LAYERED + Tk 的 GDI 绘制 = 合成成**纯黑**（用户看到"不透明黑色正方形"）。
            cur = self.w32.ex_style(h)
            self.w32.set(int(h), GWL_EXSTYLE, (cur & ~WS_EX_LAYERED) | bits)
        # 读回断言（自检用，也用于运行期监控）
        self.style_report = {h: self.w32.ex_style(h) for h in self.hwnds}
        self._exclude_from_capture()
        return self.style_report

    def _exclude_from_capture(self):
        """让悬浮窗**对抓屏不可见**（`SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`）。

        为什么必须做（2026-10-02 实机定位到的设计缺陷，用户"悬浮窗数字不动"的真因）：
          悬浮窗默认画在左上角 (40,40)，而**行动轴就在左上角那一列**（x 60~340, y 0~1250）。
          我们的抓屏是**整屏 BitBlt**（mss）——它会连同我们自己的窗口一起抓到，
          于是行动轴区域被悬浮窗挡住 → 顶端卡识别 0/380 → 每条事件都 `status=review`
          → 合计恒为 0、界面显示"待复核"（而 HUD 数字其实一直在正常读）。

        `WDA_EXCLUDEFROMCAPTURE` = 0x11（Windows 10 2004+；本机 Win11 支持）：
        窗口只在显示器上可见，**屏幕捕获 API 里看不到它**。失败也不致命（返回 False），
        但要把结果记下来 —— 失败时靠 `--pos` 把悬浮窗挪开也是办法（见 README/交付文档）。
        """
        WDA_EXCLUDEFROMCAPTURE = 0x00000011
        ok = 0
        try:
            u = ctypes.windll.user32
            for h in (self.hwnds or []):
                try:
                    if u.SetWindowDisplayAffinity(int(h), WDA_EXCLUDEFROMCAPTURE):
                        ok += 1
                except Exception:
                    pass
        except Exception:
            ok = 0
        self.capture_hidden = bool(ok)
        self.n_capture_hidden = ok
        return self.capture_hidden

    def styles_ok(self):
        """必需的扩展样式位是否都置上了（取最外层那个句柄判定）。

        ⚠️ **刻意不检查 `LAYERED`** —— 我们不再加它。
        原因：`WS_EX_LAYERED` 让 DWM 把窗口当 layered 表面，而 Tk 用 GDI 绘制，
        合成结果是**纯黑**（用户实测："一个正方形不透明黑色"）。
        鼠标穿透只需要 `WS_EX_TRANSPARENT`。
        """
        if not self.style_report:
            return False, "没有句柄"
        need = {"NOACTIVATE": WS_EX_NOACTIVATE}
        if self.click_through:
            need["TRANSPARENT"] = WS_EX_TRANSPARENT
        if self.topmost:
            need["TOPMOST"] = WS_EX_TOPMOST
        st = self.style_report[self.hwnds[-1]]
        missing = [k for k, v in need.items() if not (st & v)]
        detail = "句柄 %s 扩展样式 0x%08X %s" % (
            [hex(h) for h in self.hwnds], st, "缺 " + ",".join(missing) if missing else "OK")
        return (not missing), detail

    # ────────────────────────── 热键 ──────────────────────────
    def _poll_hotkey(self):
        """定时轮询全局按键（GetAsyncKeyState）——穿透后点不到窗口，只能这样退出。"""
        if not self.hotkey:
            return
        u = ctypes.windll.user32
        down = all(u.GetAsyncKeyState(vk) & 0x8000 for vk in self.hotkey)
        if down and not self._last_key_state:
            self.quit_requested = True
        self._last_key_state = down
        if not self.quit_requested:
            self.after_id = self.root.after(60, self._poll_hotkey)

    def hotkey_state(self):
        """给自检用：热键组合当前是否按下（不依赖轮询）。"""
        if not self.hotkey:
            return None
        u = ctypes.windll.user32
        return all(u.GetAsyncKeyState(vk) & 0x8000 for vk in self.hotkey)

    # ────────────────────────── 更新 ──────────────────────────
    @staticmethod
    def fmt(n):
        return format(int(n), ",")

    def update(self, state):
        """把 `mvp.engine.LiveEngine.state()` 的结果刷到界面上。"""
        self._n_updates += 1
        rows = state.get("rows") or []
        # T2：有附伤拆分时，占比按"剥离后"的展示口径刷（份额从行动者挪到倍率所有者）
        t2_rows = state.get("t2_rows") or []
        t2_used = bool(t2_rows) and any(
            abs((a.get("damage") or 0) - (b.get("damage") or 0)) > 0
            for a, b in zip(t2_rows, rows)) if rows else False
        if t2_used:
            rows = t2_rows
        for i, (n, d, p) in enumerate(self.row_widgets):
            if i < len(rows):
                r = rows[i]
                n.configure(text=r["owner"])
                d.configure(text=self.fmt(r["damage"]))
                p.configure(text="%.1f%%" % r["pct"])
            else:
                n.configure(text="")
                d.configure(text="")
                p.configure(text="")
        self.lbl_total.configure(text="合计  %s" % self.fmt(state.get("total", 0)))
        owner = state.get("actor_owner")
        if owner:
            unit = state.get("actor_unit") or ""
            txt = owner if (not unit or unit == owner) else "%s（%s）" % (owner, unit)
            self.lbl_actor.configure(text="当前行动: %s" % txt)
        else:
            # 用户 2026-10-04：界面里不要出现「待复核」字样 → 用「—」
            self.lbl_actor.configure(text="当前行动: —")
        self.lbl_dps.configure(text=state.get("dps_line") or "每行动值伤害  —")
        # T2 附伤分离：脚注显示最近带附伤的事件（估算/精确；不出现「待复核」字样）
        t2_line = state.get("t2_line") or ""
        if self.debug:
            self.lbl_foot.configure(text=state.get("debug", "") or t2_line)
        else:
            pre = "附伤(已剥离,估算) " if t2_used else ("附伤 " if t2_line else "")
            self.lbl_foot.configure(text=(pre + t2_line) if t2_line else "")
        self.root.update()
        return True

    def pump(self):
        """只跑一遍消息循环（主循环里非阻塞用）。"""
        self.root.update()

    def should_quit(self):
        """主循环每帧问一次：要不要退出。

        ⚠️【2026-10-02 修正】原来只返回 `quit_requested`，而那个标志**只**由 Tk 的
        `after(60, _poll_hotkey)` 定时器设置 —— 一旦主循环里 Tk 消息循环没被及时跑到
        （或 after 链断掉），热键就完全失效（用户实测"游戏在前台按 Ctrl+Alt+Q 没反应"）。
        现在**每帧直接查一次按键状态**（GetAsyncKeyState，不依赖 Tk 定时器）。
        """
        try:
            st = self.hotkey_state()
        except Exception:
            st = None
        if st and not self._last_key_state:
            self.quit_requested = True
        if st is not None:
            self._last_key_state = bool(st)
        return bool(self.quit_requested)

    def destroy(self):
        try:
            if self.after_id is not None:
                self.root.after_cancel(self.after_id)
                self.after_id = None
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


FIXTURE = {
    "rows": [
        {"owner": "遐蝶", "damage": 5686611, "pct": 51.2, "n": 9},
        {"owner": "长夜月", "damage": 3265051, "pct": 29.4, "n": 8},
        {"owner": "风堇", "damage": 1348907, "pct": 12.1, "n": 11},
        {"owner": "昔涟", "damage": 815302, "pct": 7.3, "n": 5},
    ],
    "total": 11115871, "n_events": 33, "n_review": 9, "n_non_ally": 0,
    "actor": {"owner": "遐蝶", "unit": "死龙", "src": "open_event"},
    "actor_owner": "遐蝶", "actor_unit": "死龙",
    "dps": None, "dps_line": "每行动值伤害  —",
    "debug": "事件 33（待复核 9 / 敌方 0）  重算 1 次  覆盖 t≤340.0s",
}


def selftest(save="samples/mvp_overlay_selftest.png", seconds=2.0, verbose=True):
    """真建窗口 → 断言扩展样式 → 截屏存 PNG → 退出。返回 (ok, 说明)。"""
    ov = Overlay(x=60, y=60, alpha=1.0, debug=True, hotkey=None)
    ov.update(FIXTURE)
    ov.pump()
    ok, detail = ov.styles_ok()
    rect = (ov.root.winfo_rootx(), ov.root.winfo_rooty(),
            ov.root.winfo_width(), ov.root.winfo_height())
    t_end = time.perf_counter() + seconds
    while time.perf_counter() < t_end:
        ov.pump()
        time.sleep(0.02)
    ov.update(FIXTURE)
    ov.pump()
    shot = None
    hidden = getattr(ov, "capture_hidden", None)
    detail += "；对抓屏不可见(capture-hidden)=%s（%d 个句柄）" % (
        "是" if hidden else "否", getattr(ov, "n_capture_hidden", 0))
    try:
        from PIL import Image
        from capture import Grabber
        x, y, w, h = rect
        # ⚠️ 截图前**临时关掉**"对抓屏不可见"：否则这一抓只会拍到桌面
        #    （那个 affinity 的作用就是让抓屏看不到悬浮窗），截图就没法当视觉证据了。
        u = ctypes.windll.user32
        for hh in (ov.hwnds or []):
            try:
                u.SetWindowDisplayAffinity(int(hh), 0)
            except Exception:
                pass
        ov.pump()
        time.sleep(0.2)
        with Grabber() as g:
            pad = 8
            rgb = g.grab_rgb({"left": max(0, x - pad), "top": max(0, y - pad),
                              "width": w + 2 * pad, "height": h + 2 * pad})
        os.makedirs(os.path.dirname(os.path.abspath(save)), exist_ok=True)
        Image.fromarray(rgb).save(save)
        shot = os.path.abspath(save)
        for hh in (ov.hwnds or []):           # 恢复（自检期间也要保持与生产一致）
            try:
                u.SetWindowDisplayAffinity(int(hh), 0x00000011)
            except Exception:
                pass
    except Exception as e:                       # 抓屏失败不影响样式断言
        detail += "；截屏失败 %r" % (e,)
    ov.destroy()
    if verbose:
        print("悬浮窗自检：%s" % detail)
        print("  窗口矩形 %dx%d @ (%d,%d)，截图 %s" % (rect[2], rect[3], rect[0], rect[1], shot))
    return ok, {"detail": detail, "shot": shot, "rect": rect, "capture_hidden": hidden}


def main():
    ap = argparse.ArgumentParser(description="MVP 悬浮窗")
    ap.add_argument("--selftest", action="store_true", help="建窗口 + 断言鼠标穿透样式 + 截图")
    ap.add_argument("--shot", default="samples/mvp_overlay_selftest.png")
    ap.add_argument("--seconds", type=float, default=2.0)
    a = ap.parse_args()
    if a.selftest:
        ok, info = selftest(a.shot, a.seconds)
        return 0 if ok else 1
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
