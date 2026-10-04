# tools/ —— 开发与诊断脚本（按**功能**分类，不再用 A/B/C/E 线代号）

> 这里放的是**开发期**用的东西：诊断、标定、训练、对账、一次性实验。
> 用户双击运行的产品不在这里 —— 入口是仓库根的 `gui_main.py`（打包成
> `dist/HSR伤害统计/HSR伤害统计.exe`），核心运行库也在仓库根（见根 `README.md`）。
>
> 每个脚本的 **原路径 → 现路径 + 一句话用途** 见 [`清单.md`](清单.md)（100 个脚本）。
> 这次整理（P3）的完整记录与新旧路径映射总表见
> `docs/工作区整理_P3_按功能重组`。

---

## 1. 目录一览

| 目录 | 干什么 | 在用个数 |
|---|---|---|
| [`hud/`](hud) | HUD 数字识别：诊断字形/掩膜/字号、训练与导出 ONNX、数据集、评测 | 16 |
| [`axis/`](axis) | 行动轴顶端单位识别：标定模板、标注、诊断、报表 | 19 |
| [`events/`](events) | 事件切分与归属：扫描、锚点对账、台账、表格 | 11 |
| [`overlay/`](overlay) | 悬浮窗与实机核对：抓屏取证、渲染实验、样式诊断 | 22 |
| [`team2/`](team2) | **第二支队伍**（录屏2）：素材、单位识别、技能台账 | 7 |
| [`capture/`](capture) | 抓屏与屏幕适配：探针、计时、定位诊断 | 4 |
| [`coverage/`](coverage) | 覆盖率外推（旧 L6）：保持率与采纳口径 | 2 |
| [`prep/`](prep) | 重建 `out/` 里的模板资产 | 2 |
| [`report/`](report) | 交付/验收产物生成 | 1 |
| [`vm/`](vm) | 伤害模型（旧 D 线）——⚠️ **其结论**已证伪**（用户 2026-10-02 原话：「D 线出来的全是错误结论」）**，仅留档 | 2 |
| [`archive/`](archive) | 历史留档：一次性补丁（已用完）与已弃用脚本 | 3 |
| [`archive/deprecated/`](archive/deprecated) | 🗄️ **已归档的脚本**（被取代 / 一次性，11 个）—— 见其 [README](archive/deprecated/README.md) | 11 |

> 归档判据（三条都要满足）：全仓**零 import**、**零真实文档引用**、结论已固化进上层实现或被后继脚本取代。
> 依据是 `docs/无用文件审计` §2.4；**归档不等于删除**，
> `git log --follow <路径>` 仍有历史。

---

## 2. 怎么跑（**都在仓库根跑**）

```powershell
cd D:\project\hsr-damage-meter
$env:PYTHONIOENCODING='utf-8'
python tools\hud\diag_glyph.py          # 例：逐位诊断字形
python tools\events\account.py          # 例：逐组算账
python tools\capture\probe_screen.py    # 例：抓屏探针
```

**三条回归命令**（改任何东西后都跑；入口仍在仓库根，因为它们是库+CLI 两用的）：

```powershell
python eval_holdout.py                    # 数字：期望 逐字 29/29、整串 5/5
python axis_actor.py --selftest           # 行动轴：期望 18 条真值帧 + 3 档缩放全一致
python -u events_v4.py --anchors     # 归属：期望 10 一致 / 0 不一致 / 8 正确弃权
```

---

## 3. 脚本为什么能"从根跑"：`tools_bootstrap`

整理前，每个脚本都躺在仓库根，体里写着
`sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` —— 那等价于"把仓库根加进
`sys.path`"，于是 `import hud_glyphs`、读 `out/xxx.npz`、读 `frames/glyphcache` 都能用。

搬进 `tools/<功能>/` 后 `__file__` 不再是仓库根，所以每个脚本头部多了一段引导
（由 `out/p3_fix_bootstrap.py` 自动注入）：

```python
import os as _os, sys as _sys
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *
```

`tools/tools_bootstrap.py` 做三件事：

1. 把**仓库根**与 `vendor/` 插进 `sys.path`（`vendor/` 放的是 `mss`）；
2. `chdir` 到仓库根 —— 老脚本都假设"在仓库根跑"，`out/`、`frames/` 这类相对路径才成立；
3. 把 stdout/stderr 切 UTF-8（Windows 控制台默认 GBK，`print("✓")` 会直接崩）。

另外每个脚本里原来的 `HERE = os.path.dirname(os.path.abspath(__file__))`（搬家前 = 仓库根）
被改成了**自适应查找**（向上找含 `tools/tools_bootstrap.py` 的那一层），
这样 `os.path.join(HERE, "out/...")` 这类派生常量继续指向仓库根：

```python
_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r
```

> ⚠️ 脚本自己的 `sys.path.insert(0, ...)` 那行**没有删**（留着无害，被拷到别处单跑还能自救）。

---

## 4. 新增脚本时

* 放 `tools/<功能>/`，文件名写**功能**（`diag_xxx.py` / `train_xxx.py` / `report_xxx.py`），
  **不要**再用 `_A/_B/_C/_E/_L2/_L6/_L7/_M` 线代号；
* 头部照抄上面那段引导，并保留一行 `from tools_bootstrap import *`；
* 需要仓库根路径时用 `ROOT`（由引导导出）或自适应 `HERE`，**不要**写
  `os.path.dirname(os.path.abspath(__file__))` 再拼 `out/`（搬过家就会错）；
* 产物落到 `out/`（中间产物）或 `samples/`（给人看的图），别落在 `tools/` 里。
