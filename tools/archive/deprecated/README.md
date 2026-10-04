# 归档：已被取代 / 一次性脚本（P3b）

> 依据 `docs/无用文件审计` §2.4 的确认结论归档。
> **不是删除**：git 历史里都还在（`git log --follow <路径>`）。
> 归档判据（三条都要满足）：① 全仓 **零 import**；② **零真实文档引用**；
> ③ 结论已固化进上层实现，或被后继脚本取代。

| 脚本 | 归档理由 |
|---|---|
| `damage_model.py` | ⛔ 旧 D 线伤害模型（补全版）—— 用户 2026-10-02 定案：**「D 线出来的全是错误结论」**。它的「整局累计」假设与实际「一次攻击内累计」相反，`delta_check()` 那套校验方案随之作废 |
| `damage_model_early.py` | ⛔ 更早的 D 线伤害模型（原 `damage_model.py`）—— 同上；补全版还指出它「有一条真的口径错误」 |
| `analyze_aha.py` | commit 信息即「实测负结果，模型被否定」 |
| `analyze_aha_cycle.py` | 同上 |
| `borderline.py` | 间距分布标定；`MIN_MARGIN=0.45` 已定案写进 `axis_actor.py` |
| `fix_imgrefs.py` | 一次性文档断链修补；审计实测**硬断链 0**，目标已达成 |
| `fix_imgrefs2.py` | 同上（第二版） |
| `fix_overlay_colors.py` | 一次性配色修补；**写死改 `mvp/overlay.py`**，重跑会破坏现配色 |
| `fix_overlay_colors2.py` | 同上（第二版） |
| `match_templates.py` | `docs/项目总交接` 明记「0.57，此路不通」—— 方案未采用 |
| `scan.py` | 被 `scan_chain.py`（v2）取代 —— v2 的 docstring 明写「与 v1 的差别」 |
| `tune_chain.py` | 自述「给 A 线的建议」，建议已采纳进 `hud_glyphs.py`（链阈值定案） |
| `window.py` | 自述「演示」；多帧投票已在 `read_hud.vote_frames` 实现 |

> ⚠️ **D 线那 2 项与其它归档不同**：其它是"用完 / 被取代"，D 线是**结论错误** ——
> 归档的目的是**防止再被当成依据**。对应的作废产物在
> `out/archive/D线_作废_candidates.{json,csv}`；反面教材文档在
> `docs/伤害模型_D线_未被采信`。

## 什么时候该把它们删掉

确认**没有任何文档/习惯命令**还会用到它们之后（例如你连续几次整理都没再翻过这些文件），
直接 `git rm -r tools/archive/deprecated/` 即可 —— 历史仍在。
