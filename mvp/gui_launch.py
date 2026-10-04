# -*- coding: utf-8 -*-
"""控制面板 —— 双击 exe 后弹出的主界面：点「开始统计」才开始。

为什么要它（用户反馈 2026-10-01）：
  "为什么我开了之后没反应，不应该要有个小 ui 然后我点开始然后开始计吗"
  —— 原来只有命令行，双击 exe 看不到任何界面，体验不对。

设计：
  * 主窗口（有标题栏、可关闭、可拖动）—— 这就是"小 UI"；
  * 「开始统计」→ 倒计时（可设）→ 启动实时采集 + 悬浮窗；
  * 「停止」/关窗 → 结束采集并显示汇总；
  * 采集在**子进程**里跑，主界面按钮始终能响应（不会被采集循环卡死）。

用法：
    python mvp/gui_launch.py                 # 源码模式
    hsr_mvp.exe --gui                        # exe 模式
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, os.path.join(ROOT, "vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TITLE = "HSR 伤害统计（MVP）"

BG = "#eef1f9"
FG = "#141826"
BTN = "#3b6fd4"
BTN_FG = "#ffffff"
ACCENT = "#c8511a"


def _spawn_cmd(args, frozen):
    """构造子进程命令行：exe 模式下再调用 exe 自身；源码模式用 python -m。"""
    if frozen:
        return [sys.executable] + args
    return [sys.executable, os.path.join("mvp", "live_mvp.py")] + args


class Panel:
    def __init__(self):
        from capture import enable_dpi_awareness
        enable_dpi_awareness()
        import tkinter as tk
        from tkinter import font as tkfont

        self.tk = tk
        self.proc = None
        self.reader_thread = None
        self.frozen = bool(getattr(sys, "frozen", False))

        self.root = tk.Tk()
        self.root.title(TITLE)
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", False)
        try:
            self.root.geometry("+80+80")
        except Exception:
            pass

        fams = set(tkfont.families())
        fam = next((f for f in ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei")
                    if f in fams), "TkDefaultFont")
        self.f_h = tkfont.Font(family=fam, size=15, weight="bold")
        self.f_n = tkfont.Font(family=fam, size=11)
        self.f_s = tkfont.Font(family=fam, size=10)

        pad = 14
        tk.Label(self.root, text="HSR 伤害统计", font=self.f_h, bg=BG, fg=FG).pack(
            anchor="w", padx=pad, pady=(pad, 2))
        tk.Label(self.root, text="实时读游戏右上角「总伤害」→ 按角色统计",
                 font=self.f_s, bg=BG, fg="#4a5372").pack(anchor="w", padx=pad)

        # 位置
        row = tk.Frame(self.root, bg=BG)
        row.pack(fill="x", padx=pad, pady=(10, 0))
        tk.Label(row, text="悬浮窗位置 x,y:", font=self.f_n, bg=BG, fg=FG).pack(side="left")
        self.v_pos = tk.StringVar(value="40,40")
        tk.Entry(row, textvariable=self.v_pos, font=self.f_n, width=10).pack(side="left", padx=6)

        row2 = tk.Frame(self.root, bg=BG)
        row2.pack(fill="x", padx=pad, pady=(6, 0))
        tk.Label(row2, text="倒计时(秒):", font=self.f_n, bg=BG, fg=FG).pack(side="left")
        self.v_cd = tk.StringVar(value="10")
        tk.Entry(row2, textvariable=self.v_cd, font=self.f_n, width=6).pack(side="left", padx=6)
        tk.Label(row2, text="采集时长(秒, 0=不停):", font=self.f_n, bg=BG, fg=FG).pack(side="left")
        self.v_sec = tk.StringVar(value="3600")
        tk.Entry(row2, textvariable=self.v_sec, font=self.f_n, width=7).pack(side="left", padx=6)

        # 按钮
        btns = tk.Frame(self.root, bg=BG)
        btns.pack(fill="x", padx=pad, pady=(12, 4))
        self.btn_start = tk.Button(btns, text="▶  开始统计", font=self.f_h, bg=BTN, fg=BTN_FG,
                                   activebackground="#2f5cb0", activeforeground="#ffffff",
                                   relief="flat", padx=18, pady=8, command=self.on_start)
        self.btn_start.pack(side="left")
        self.btn_stop = tk.Button(btns, text="■  停止", font=self.f_n, bg="#c9ceda", fg=FG,
                                  relief="flat", padx=14, pady=8, state="disabled",
                                  command=self.on_stop)
        self.btn_stop.pack(side="left", padx=8)

        self.lbl_status = tk.Label(self.root, text="就绪。点「开始统计」后请切回游戏。",
                                   font=self.f_n, bg=BG, fg=ACCENT, wraplength=460,
                                   justify="left")
        self.lbl_status.pack(anchor="w", padx=pad, pady=(6, 2))

        # 日志
        box = tk.Frame(self.root, bg=BG)
        box.pack(fill="both", expand=True, padx=pad, pady=(2, pad))
        self.txt = tk.Text(box, height=11, width=62, font=("Consolas", 9),
                           bg="#ffffff", fg="#1b2033", relief="solid", borderwidth=1)
        sb = tk.Scrollbar(box, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Escape>", lambda e: self.on_close())

    # ────────────────────────── 逻辑 ──────────────────────────
    def log(self, s):
        self.txt.insert("end", s.rstrip() + "\n")
        self.txt.see("end")

    def set_status(self, s, color=ACCENT):
        self.lbl_status.configure(text=s, fg=color)

    def on_start(self):
        if self.proc is not None:
            return
        try:
            x, y = (int(v) for v in self.v_pos.get().split(","))
            cd = float(self.v_cd.get() or 0)
            sec = float(self.v_sec.get() or 0)
        except Exception:
            self.set_status("参数格式不对：位置要写 x,y（如 40,40），秒数要写数字。")
            return

        args = ["--countdown", str(int(cd)), "--seconds", str(int(sec)),
                "--overlay", "--pos", "%d,%d" % (x, y)]
        cmd = _spawn_cmd(args, self.frozen)
        self.log("$ " + " ".join('"%s"' % c if " " in c else c for c in cmd))
        # 从"日志文件末尾"开始读（只显示本次新增的行）
        self._logf_pos = 0
        _fp0 = self._log_file()
        if _fp0 and os.path.exists(_fp0):
            try:
                self._logf_pos = os.path.getsize(_fp0)
            except OSError:
                self._logf_pos = 0
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:
            self.set_status("启动失败：%r" % (e,))
            self.proc = None
            return

        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.set_status("已开始。%d 秒后开始采集 —— 请切回游戏。停止按「停止」或 Ctrl+Alt+Q。" % int(cd))
        self.reader_thread = threading.Thread(target=self._pump, daemon=True)
        self.reader_thread.start()
        self.root.after(300, self._tick)

    def _log_file(self):
        """采集进程的日志文件路径（`<exe 同目录>/运行日志.txt`）。

        ⚠️ 2026-10-05：**打包版必须靠这个文件看输出**。
        原因：exe 是 windowed（`HSR_NOCONSOLE=1`）→ 子进程 `sys.stdout is None`
        → `_pump` 从管道里**一行都拿不到**，面板日志框会是空的。
        而 `mvp/resource.setup_console()` 会把输出落到 exe 同目录的 `运行日志.txt`。
        """
        try:
            from mvp import resource as R
            return os.path.join(R.exe_dir(), R.LOG_NAME)
        except Exception:
            return None

    def _pump(self):
        """把采集进程的输出喂到面板日志框。

        两条来源（都读，谁有内容显示谁）：
          · 源码模式：管道的 stdout
          · 打包模式：`运行日志.txt` 的新增内容（管道是空的）
        """
        p = self.proc
        if p is None:
            return
        # ① 管道（源码模式有效）
        try:
            for line in p.stdout:
                self.root.after(0, self.log, line)
        except Exception:
            pass

    def _pump_logfile(self):
        """增量读 `运行日志.txt`（打包模式唯一的输出来源）。"""
        fp = self._log_file()
        if not fp or not os.path.exists(fp):
            return
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                f.seek(getattr(self, "_logf_pos", 0))
                new = f.read()
                self._logf_pos = f.tell()
            for line in new.splitlines():
                if line.strip():
                    self.root.after(0, self.log, line + "\n")
        except Exception:
            pass

    def _tick(self):
        """轮询子进程是否结束；没结束就继续等。"""
        if self.proc is None:
            return
        self._pump_logfile()          # 打包模式：把日志文件里的新行显示出来
        rc = self.proc.poll()
        if rc is not None:
            self._pump_logfile()      # 结束前再收一次尾巴
            self.log("--- 采集进程结束（返回码 %s）---" % rc)
            fp = self._log_file()
            if fp:
                self.log("--- 完整日志见：%s ---\n" % fp)
            self.proc = None
            self.btn_start.configure(state="normal")
            self.btn_stop.configure(state="disabled")
            self.set_status("已停止。可以再点「开始统计」。", "#1f7a3a")
            return
        self.root.after(500, self._tick)

    def on_stop(self):
        if self.proc is None:
            return
        self.set_status("正在停止…")
        try:
            self.proc.terminate()
        except Exception:
            pass
        self.proc = None
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.set_status("已停止。", "#1f7a3a")

    def on_close(self):
        if self.proc is not None:
            try:
                self.proc.terminate()
            except Exception:
                pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


def main():
    try:
        Panel().run()
    except Exception as e:
        import traceback
        traceback.print_exc()
        # 出错时不要让双击的窗口一闪而过
        try:
            input("出错（按回车关闭）：%r" % (e,))
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
