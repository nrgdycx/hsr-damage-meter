# -*- coding: utf-8 -*-
"""MVP：实时悬浮窗（阉割版）。

范围与验收见 `docs/实时链路与悬浮窗.md`，实施说明见 `docs/实时链路与悬浮窗.md`，
交付记录见 `docs/实时链路与悬浮窗.md`。

模块：
  reader.py     一帧 → 一条读数（HUD 数字 + 行动轴顶端行动者），复用 A/B/E 线现成件
  engine.py     流式事件切分 + 归属 + 累计（口径 = 线4 `events_v4.py`，见其模块头）
  av_reader.py  行动值读取器（**占位**，MVP 只留接口）
  overlay.py    悬浮窗（置顶 + 鼠标穿透 + 全局热键退出）
  live_mvp.py   主循环（实时抓屏 / 录屏回放两种帧源）
  verify_live.py 离线对账（MVP 验收第 2 条：同一段录屏，离线 == 实时）
"""
