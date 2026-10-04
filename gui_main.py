# -*- coding: utf-8 -*-
"""exe 主入口 —— 双击后先弹**控制面板**，点「开始统计」才开始。

为什么单独做一个入口（用户反馈 2026-10-01）：
  "为什么我开了之后没反应，不应该要有个小 ui 然后我点开始然后开始计吗"
  原来 exe 的入口是 `mvp/live_mvp.py`，双击即按默认参数开始采集，
  **没有任何界面**，用户不知道发生了什么，也没法选位置/停止。

现在：
  * 双击 exe → 弹控制面板（有标题栏、能关、能拖动）
  * 点「开始统计」 → 倒计时 → 悬浮窗 + 实时统计
  * 点「停止」/关窗 → 结束

仍然支持命令行：任意参数（如 `--selftest` / `--replay`）会**直接透传给 live_mvp**，
保证打包自检与对账脚本行为不变。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, os.path.join(ROOT, "vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def main():
    argv = sys.argv[1:]
    # 有命令行参数 → 透传给 live_mvp（保持 --selftest / --replay 等原有行为）
    if argv:
        # ⚠️ 不能用 `runpy.run_path`：exe 里源码已打进 PYZ，磁盘上没有 `mvp/live_mvp.py`
        #    （实测报 FileNotFoundError）。直接 import 模块再调它的 main()。
        from mvp import live_mvp
        return live_mvp.main(argv)

    # 无参数（双击） → 弹控制面板
    from mvp.gui_launch import Panel
    Panel().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
