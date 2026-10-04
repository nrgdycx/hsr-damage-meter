# -*- coding: utf-8 -*-
"""[MVP] 「每行动值伤害」的行动值读取器 —— **本版只留接口，不实现**。

用户已定案（`docs/实时链路与悬浮窗.md` §2）：
    **每行动值伤害（DPS）本次不做，只留接口。**

为什么现在做不了
----------------
「每行动值伤害」= 总伤害 ÷ 消耗的行动值（AV）。第二个量**目前没有读取器**：
  * 线索：行动轴**每张卡右侧有个数字**（主会话在录屏2 见过 `20/53/26/91`），
    **推测**是行动值 —— 但**未经用户确认**，不能拿推测当口径；
  * 所以严禁"先随便填个数把 UI 撑起来"：那正是本项目的老坑
    （"跑得起来但结论全错"）。

接口约定（以后补读取器时**不用改 UI、不用改公式**）
----------------------------------------------------
    read_action_value(axis_img) -> float | None

  * 读得到 → 返回该次行动的行动值（>0）；
  * 读不到 / 本版未实现 → 返回 **None**；
  * 调用方必须容忍 None：`None` 时悬浮窗那一行显示 `—`，
    **绝不显示 0 或乱数**（0 会被误读成"这次行动不耗行动值"）。
"""
from __future__ import annotations

import numpy as np


def read_action_value(axis_img) -> float | None:
    """从行动轴图里读"行动值"。**MVP 阶段恒返回 None**（= 读不到）。

    axis_img: 行动轴区域 RGB ndarray (H, W, 3)，与 `capture.AXIS_REGION` 一致。

    实现路线（v2，等用户确认卡片右侧那个数字确实是行动值之后再做）：
      1. 定位每张卡右侧的数字区（相对卡框的固定偏移，做法同 A 线"锚定右缘"）；
      2. 掩膜 + 列分割 + 分类器（照 `hud_glyphs.py` / `hud_profiles.py` 的套路）；
      3. 与技能/单位绑定后，按"每次行动"累加。
    """
    if axis_img is None:
        return None
    return None


def dps(total_damage: int, av_total: float | None) -> float | None:
    """每行动值伤害。`av_total` 为 None（读不到）时返回 None —— 调用方显示 `—`。"""
    if not av_total or av_total <= 0:
        return None
    return float(total_damage) / float(av_total)


def format_dps(value: float | None, av_total: float | None) -> str:
    """悬浮窗那一行的文本。读不到行动值时显示 `—`（不是 0）。"""
    if value is None:
        return "每行动值伤害  —"
    return "每行动值伤害  %s / AV  (AV 合计 %s)" % (format(int(round(value)), ","),
                                                format(round(av_total, 1), "g"))


def _selftest():
    """自检：占位实现必须返回 None，且 dps() 在 None 下不给数。"""
    img = np.zeros((8, 8, 3), dtype=np.uint8)
    assert read_action_value(img) is None, "占位实现必须返回 None"
    assert read_action_value(None) is None
    assert dps(123456, None) is None, "行动值读不到时不许给 DPS"
    assert dps(123456, 0) is None
    assert abs(dps(1000, 4.0) - 250.0) < 1e-9
    assert format_dps(None, None) == "每行动值伤害  —"
    print("av_reader 自检通过：占位返回 None，DPS 在 None 下显示 —")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
