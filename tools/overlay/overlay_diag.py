# -*- coding: utf-8 -*-
"""
悬浮窗可见性诊断 —— 不靠截图（Windows BitBlt 抓不到 layered 窗口），
直接用 Win32 API 查：窗口是否存在、位置、大小、是否可见、扩展样式、是否被遮挡。
"""
# [P3 整理] 原路径：mvp/overlay_diag_M.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403

import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

user32 = ctypes.windll.user32
GWL_EXSTYLE = -20
GWL_STYLE = -16

u32 = user32
u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
u32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
u32.IsWindowVisible.restype = ctypes.c_bool
u32.IsWindowVisible.argtypes = [ctypes.c_void_p]
u32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
u32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


NAME = {0x00000008: "TOPMOST", 0x00000020: "TRANSPARENT", 0x00000080: "TOOLWINDOW",
        0x00080000: "LAYERED", 0x08000000: "NOACTIVATE"}
STYLE = {0x10000000: "VISIBLE", 0x8000000: "CLIPSIBLINGS", 0x4000000: "CLIPCHILDREN",
         0x1000000: "BORDER", 0x800000: "DLGFRAME", 0x400000: "POPUP"}


def describe(h, tag=""):
    ex = u32.GetWindowLongPtrW(int(h), GWL_EXSTYLE) & 0xFFFFFFFF
    st = u32.GetWindowLongPtrW(int(h), GWL_STYLE) & 0xFFFFFFFF
    r = RECT()
    u32.GetWindowRect(int(h), ctypes.byref(r))
    buf = ctypes.create_unicode_buffer(256)
    u32.GetWindowTextW(int(h), buf, 256)
    exs = ",".join(v for k, v in NAME.items() if ex & k) or "(无)"
    sts = ",".join(v for k, v in STYLE.items() if st & k) or "(无)"
    print("  %s hwnd=0x%X '%s'" % (tag, int(h), buf.value))
    print("     可见=%s  矩形=(%d,%d)-(%d,%d)  %dx%d"
          % (bool(u32.IsWindowVisible(int(h))), r.left, r.top, r.right, r.bottom,
             r.right - r.left, r.bottom - r.top))
    print("     exstyle=0x%08X [%s]" % (ex, exs))
    print("     style  =0x%08X [%s]" % (st, sts))
    return ex, st, r


def main():
    from mvp.overlay import Overlay, FIXTURE

    print("=== 建悬浮窗（alpha=0.94，与运行期一致）===")
    ov = Overlay(x=40, y=40, alpha=0.94, debug=True, hotkey=None)
    ov.update(FIXTURE)
    for _ in range(30):
        ov.pump()
        time.sleep(0.03)
    print("窗口矩形(winfo): %dx%d @ (%d,%d)"
          % (ov.root.winfo_width(), ov.root.winfo_height(),
             ov.root.winfo_rootx(), ov.root.winfo_rooty()))
    print("Tk 报告的 alpha:", ov.root.attributes("-alpha"))
    print("Tk 报告的 topmost:", ov.root.attributes("-topmost"))
    print()
    print("=== Win32 实测每个句柄 ===")
    for i, h in enumerate(ov.hwnds):
        describe(h, "句柄%d" % i)
    print()
    ok, detail = ov.styles_ok()
    print("styles_ok:", ok, "|", detail)
    print()
    print("=== 窗口是否真在屏幕最前（用 WindowFromPoint 命中测试）===")
    cx = ov.root.winfo_rootx() + 10
    cy = ov.root.winfo_rooty() + 10
    hit = u32.WindowFromPoint(ctypes.wintypes.POINT(cx, cy)) if hasattr(ctypes, "wintypes") else 0
    if hit:
        print("  点 (%d,%d) 命中 hwnd=0x%X" % (cx, cy, int(hit)))
        print("  该句柄是否属于悬浮窗:", int(hit) in [int(x) for x in ov.hwnds])
    print()
    print(">>> 请现在看屏幕左上角 (40,40) 附近：应该有一个深色卡片，写着“当前行动: 遐蝶（死龙）”等")
    ov.update(FIXTURE)
    t = time.perf_counter() + 6
    while time.perf_counter() < t:
        ov.pump()
        time.sleep(0.02)
    ov.destroy()
    print("已关闭。")


if __name__ == "__main__":
    main()
