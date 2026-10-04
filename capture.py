# -*- coding: utf-8 -*-
"""B 线：实时抓屏（mss）—— 只抓 HUD 数字区与行动轴区两块小区域。

为什么必须声明 DPI 感知（本会话实测）：
  * 物理屏 **2880x1800**，系统缩放 **200%**（GetDpiForSystem=192）。
  * 未声明 DPI 感知的进程里 GetSystemMetrics 只返回 **1440x900**（逻辑像素），
    mss 也会跟着只报 1440x900 -> 用录屏里量出来的物理坐标（如 CX0=2350）会裁错地方。
  * 声明 SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2) 后 mss.monitors 才是
    2880x1800，物理坐标直接可用。
  => 抓屏前**必须**先 `enable_dpi_awareness()`，且要在创建 mss 实例之前。

另：录屏是 2876x1798，比物理屏小一点点（宽 -4 / 高 -2），说明录制时有轻微裁边/缩放。
    按录屏量的坐标拿到实屏上大约差 0~4px —— 现有区域本身留了大量余量（数字右缘
    x≈2852，区域左界 2350；行动轴区域 x60~340 包住 x≈86 起的卡片），所以不受影响。

提供：
  * `enable_dpi_awareness()`
  * `REGIONS`：HUD / AXIS 的绝对物理像素矩形（**参考标定值**，2876×1798 时适用）
  * `auto_regions(g)`：**线7** —— 抓一张整屏 → 动态定位 → 给出当前分辨率下该抓的两块区域
  * `Grabber`：复用同一个 mss 实例连续抓屏，`grab_rgb(region)` 直接给 RGB ndarray；
    `g.calibrate()` 让 `grab_hud()/grab_axis()` 改用自动定位出来的区域
  * 命令行：`python capture.py --bench 100` 连续抓 100 帧并统计耗时；
            `python capture.py --save` 把两块区域各存一张 PNG 供人工核对；
            `python capture.py --calibrate` 打印线7 自动定位出来的区域
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
# mss 装在仓库内的 vendor/（本会话沙箱里 pip install 会 EACCES，见 install_mss_B.py）
sys.path.insert(0, os.path.join(HERE, "vendor"))

# ── 区域（绝对物理像素，与交接文档第 3 节一致）─────────────────────────────
# ⚠️ 线7 起这两条只是**参考标定**（2876×1798 录屏1 量出来的），不再是唯一来源：
#    换分辨率请用 `auto_regions()` / `Grabber.calibrate()` 从画面上动态定位。
HUD_REGION = {"left": 2350, "top": 260, "width": 526, "height": 80}
AXIS_REGION = {"left": 60, "top": 0, "width": 280, "height": 1250}

REGIONS = {"hud": HUD_REGION, "axis": AXIS_REGION}

_dpi_done = False


def enable_dpi_awareness() -> bool:
    """让本进程按物理像素看屏幕。返回是否成功。必须在 mss 实例化之前调用。"""
    global _dpi_done
    if _dpi_done:
        return True
    import ctypes

    user32 = ctypes.windll.user32
    try:
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):  # PER_MONITOR_AWARE_V2
            _dpi_done = True
            return True
    except Exception:
        pass
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:  # PROCESS_PER_MONITOR_DPI_AWARE
            _dpi_done = True
            return True
    except Exception:
        pass
    return _dpi_done


class Grabber:
    """复用 mss 实例的抓屏器。`grab_rgb()` 返回 (H, W, 3) uint8 RGB。"""

    def __init__(self, monitor: int = 1):
        enable_dpi_awareness()
        import mss

        cls = getattr(mss, "MSS", None) or mss.mss  # mss>=10 用 MSS，旧版用 mss
        self._sct = cls()
        self.monitor = self._sct.monitors[monitor]
        self.screen = (self.monitor["width"], self.monitor["height"])
        self.regions = {k: dict(v) for k, v in REGIONS.items()}   # 当前使用的区域

    def close(self):
        self._sct.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def grab_bgra(self, region: dict) -> np.ndarray:
        """抓一块区域，返回 (H, W, 4) uint8 BGRA（不拷贝像素，只是 frombuffer 视图）。"""
        shot = self._sct.grab(region)
        return np.frombuffer(shot.raw, dtype=np.uint8).reshape(shot.height, shot.width, 4)

    def grab_rgb(self, region: dict) -> np.ndarray:
        """抓一块区域，返回 (H, W, 3) uint8 RGB（一次通道重排拷贝，526x80 约 0.05ms）。"""
        bgra = self.grab_bgra(region)
        return np.ascontiguousarray(bgra[:, :, 2::-1])

    def grab_screen(self) -> np.ndarray:
        """抓整屏（RGB）。线7 的 `calibrate()` 用它做一次定位。"""
        return self.grab_rgb({"left": 0, "top": 0, "width": self.screen[0], "height": self.screen[1]})

    def calibrate(self, verbose: bool = True) -> dict:
        """
        **线7 的"上屏先探测"落地**：抓一张整屏 → 动态定位 HUD/行动轴 → 之后只抓这两块小区域。

        这样换分辨率/换字号时区域跟着画面走，不需要人去改常量。
        定位不出来时会退回参考标定区域（`REGIONS`），不会把区域弄丢。
        """
        import geometry as SA
        full = self.grab_screen()
        g = SA.live_regions(full)
        self.regions = {"hud": g["hud"], "axis": g["axis"]}
        if verbose:
            print("整屏 %dx%d → HUD 框 %s（来源 %s，字号比 %.2f）｜行动轴 %s（来源 %s）" % (
                self.screen[0], self.screen[1], g["hud"], g["hud_geometry"]["src"],
                g["hud_geometry"]["k"], g["axis"], g["axis_geometry"]["src"]))
        return self.regions

    def grab_hud(self) -> np.ndarray:
        return self.grab_rgb(self.regions["hud"])

    def grab_axis(self) -> np.ndarray:
        return self.grab_rgb(self.regions["axis"])


def auto_regions(grabber: "Grabber" = None, rgb_screen=None) -> dict:
    """
    线7：给出当前分辨率下该抓的两块区域（物理像素矩形）。

    可以传一张已经抓好的整屏图（rgb_screen，RGB），也可以传一个 Grabber（自己抓整屏）。
    """
    import geometry as SA
    if rgb_screen is None:
        if grabber is None:
            with Grabber() as g:
                return g.calibrate(verbose=False)
        rgb_screen = grabber.grab_screen()
    g = SA.live_regions(rgb_screen)
    return {"hud": g["hud"], "axis": g["axis"]}


def _stats(ts_ms):
    a = np.asarray(ts_ms, dtype=np.float64)
    return {"n": int(a.size), "avg": float(a.mean()), "max": float(a.max()),
            "p50": float(np.percentile(a, 50)), "p95": float(np.percentile(a, 95))}


def bench(n=100, both=True):
    """连续抓 n 帧，分别统计 HUD / 行动轴区域耗时。返回统计字典。"""
    out = {}
    with Grabber() as g:
        print("物理屏 %dx%d（DPI 已感知）" % g.screen)
        for name in (["hud", "axis"] if both else ["hud"]):
            reg = REGIONS[name]
            region = dict(reg)
            g.grab_rgb(region)  # 预热
            ts = []
            for _ in range(n):
                t0 = time.perf_counter()
                g.grab_rgb(region)
                ts.append((time.perf_counter() - t0) * 1000.0)
            out[name] = _stats(ts)
            s = out[name]
            print("  %-5s %4dx%-5d 连续 %d 帧: 平均 %.2fms  中位 %.2fms  p95 %.2fms  最大 %.2fms"
                  % (name, region["width"], region["height"], s["n"], s["avg"], s["p50"], s["p95"], s["max"]))
    return out


def overview(out="samples/live_overview_B.png", scale=0.5):
    """抓整屏 -> 缩放 -> 在 HUD/行动轴区域画框标注，用于人工核对"区域对不对"。"""
    import subprocess

    from PIL import Image, ImageDraw

    with Grabber() as g:
        full = g.grab_rgb({"left": 0, "top": 0, "width": g.screen[0], "height": g.screen[1]})
    img = Image.fromarray(full).resize((int(full.shape[1] * scale), int(full.shape[0] * scale)),
                                       Image.LANCZOS)
    d = ImageDraw.Draw(img)
    for name, reg in REGIONS.items():
        box = [reg["left"] * scale, reg["top"] * scale,
               (reg["left"] + reg["width"]) * scale, (reg["top"] + reg["height"]) * scale]
        d.rectangle(box, outline=(255, 0, 0), width=2)
        d.text((box[0] + 4, box[1] + 4), name, fill=(255, 0, 0))   # 文字标签，不靠颜色传信息
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    img.save(out)
    print("整屏标注图已存 %s (%dx%d, 缩放 %.2f)" % (out, img.width, img.height, scale))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="B 线实时抓屏")
    ap.add_argument("--bench", type=int, default=0, help="连续抓 N 帧并统计耗时")
    ap.add_argument("--hud-only", action="store_true", help="只抓 HUD 区")
    ap.add_argument("--save", action="store_true", help="把两块区域各存一张 PNG 到 samples/")
    ap.add_argument("--overview", action="store_true", help="存一张整屏标注图，核对区域位置")
    ap.add_argument("--calibrate", action="store_true", help="线7：抓整屏 → 动态定位两块区域并打印")
    ap.add_argument("--open", action="store_true", help="存完用系统看图器打开")
    ap.add_argument("--out", default="samples", help="--save 的输出目录")
    a = ap.parse_args(argv)

    if a.calibrate:
        with Grabber() as g:
            reg = g.calibrate()
        print("（直接抓屏用 g.grab_hud()/g.grab_axis()；想自己拼区域就用 auto_regions()）")
        return 0
    if a.bench:
        bench(a.bench, both=not a.hud_only)
    if a.save or not (a.bench or a.overview):
        from PIL import Image

        os.makedirs(a.out, exist_ok=True)
        with Grabber() as g:
            g.calibrate()                     # 线7：先按画面定位，再存，存的就是实际会抓的区域
            for name, region in g.regions.items():
                rgb = g.grab_rgb(region)
                p = os.path.join(a.out, "live_%s_B.png" % name)
                Image.fromarray(rgb).save(p)
                print("已存 %s  (%dx%d)  区域 %s" % (p, rgb.shape[1], rgb.shape[0], region))
    if a.overview:
        p = overview(os.path.join(a.out, "live_overview_B.png"))
        if a.open:
            os.system('cmd /c start "" "%s"' % os.path.abspath(p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
