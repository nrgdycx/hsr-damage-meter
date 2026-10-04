# EXE 打包（双击即用）

> 本文合并了原来 2 篇（`EXE打包_交付` / `EXE打包_专项记录`），去掉了实施过程。
> 实时链路与悬浮窗本身见 [`实时链路与悬浮窗.md`](实时链路与悬浮窗.md)。
> ⚠️ 模块改名映射见 `代码改名_交付` §7（`live_mvp` 等名字可能已变）。

**一句话**：把 `mvp/` 那套实时悬浮窗打成**双击即用**的 exe ——
不需要装 Python、不需要命令行；运行时资源按 **exe 所在位置**解析。

---

## 0. 产物与体积（实测）

| 产物 | 体积 | 首启 | 说明 |
|---|---|---|---|
| `dist/HSR伤害统计/`（**onedir**）| ~230 MB | **0.46 s** | ⭐ **推荐**：双击 `HSR伤害统计.exe` |
| `dist/HSR伤害统计_onedir.zip` | ~98 MB | — | 分发用 |
| onefile（可选）| ~96 MB | 5.47 s | 单文件；每次启动自解包 ~230MB 到 `%TEMP%` |

构建用时：onedir ≈ 31~43 s、onefile ≈ 51~56 s（本机，增量）。

**进 git 的**：`hud_pack.spec`、`build_exe.py`、`mvp/resource.py`。
**不进 git 的**：`dist/`、`build/`（已 `.gitignore`）。

### 交付形态（用户反馈定案）

* ✅ **一个入口**（不再有同名 exe 混淆）
* ✅ **无控制台窗口**（`HSR_NOCONSOLE=1`）
* ✅ 中文入口名 `HSR伤害统计.exe`
* ✅ 自动打 zip + 把使用说明放进交付目录与 zip

---

## 1. 怎么构建

```powershell
cd D:\project\hsr-damage-meter
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUNBUFFERED='1'

# 排错版（带控制台，能看见报错）—— 先跑这个
python build_exe.py --mode onedir

# 交付版（无控制台 + 中文名 + 使用说明 + 打 zip）
python build_exe.py --mode onedir --name HSR伤害统计 --readme out\交付说明_模板.txt

# 其他
python build_exe.py --mode both        # onedir + onefile
python build_exe.py --clean            # 先删 dist/ build/ 再全量重建
```

等价的原始命令（不想用脚本时）：`python -m PyInstaller --noconfirm hud_pack.spec`

> ⚠️ **入口是 `gui_main.py`，不是 `live_mvp.py`**：
> 双击弹**控制面板**（点「开始统计」）；带命令行参数时**透传给 `live_mvp`**
> （保持 `--selftest` / `--replay` 等原有行为）。

---

## 2. 怎么用（用户视角）

1. 双击 `dist\HSR伤害统计\HSR伤害统计.exe`
2. 弹出**控制面板** → 点「**开始统计**」
3. 倒计时后切回游戏 → 悬浮窗出现在屏幕左上角开始计数

* **建议进战前就点**（保证最早的伤害也被记录，见 [`实时链路与悬浮窗.md`](实时链路与悬浮窗.md) §4）
* **退出**：按 `Ctrl+Alt+Q`，或直接在控制面板点「停止」

---

## 3. ⚠️ 打包的六个坑（改打包时必看）

### 3.1 ⭐ `torch` 要**两道保险**才能摘掉（最省体积的一步）

`mvp/reader.py` 对 `read_hud` 的 import 已改**惰性**；spec 里**还要** `excludes=['torch']`。
不摘 → 体积 **800MB~1.5GB**。

### 3.2 资源路径：一律过 `mvp/resource.py`

**不许再写"相对当前目录"** —— 打包后工作目录是任意位置（桌面等）。

### 3.3 ⚠️ 控制台编码：打包后 `print("✓")` 会把程序**静默干掉**

打包后控制台默认 **GBK** → `R.setup_console()` 先把输出切 **UTF-8**。

### 3.4 ⚠️ 一个**静默降级**的坑：标记模板库变空（已修）

### 3.5 不要 `os.chdir(ROOT)`

### 3.6 先带 console 再谈无控制台

`--noconsole` 后**看不到报错**，排错会浪费大量时间。

---

## 4. 验收（全部可复现）

### 4.1 源码模式三件套（改动后仍全绿）

```powershell
python eval_holdout.py                 # 逐字 29/29、整串 5/5
python axis_actor.py --selftest        # 18 条真值帧 + 3 档缩放
python -u events_v4.py --anchors  # 10 一致 / 0 不一致 / 8 正确弃权
```

### 4.2 ⭐ exe 与源码模式**逐项相同**（同一段真帧回放）

### 4.3 `--selftest`（双击后"到底有没有装好"的自动答案）

```powershell
.\dist\HSR伤害统计\HSR伤害统计.exe --selftest
```
覆盖：资源路径 → 模型加载 → 行动轴模板库 → 事件引擎 → **悬浮窗扩展样式读回**。
（自检里含一张**随包实机帧**的端到端读数，用于确认打包没把识别链路弄坏。）

### 4.4 资源不靠工作目录（**专项验收第 4 条**）

⚠️ **必须把产物拷到「仓库外」再跑一次** —— 在仓库目录里双击永远能跑（工作目录刚好对），
**复制到桌面才能发现路径问题**。

### 4.5 P2 形态验收（用户问题 2 与 3）

* 全仓库只有**一个**面向用户的 exe 入口 ✅
* 双击后**只出现控制面板**，没有额外控制台窗口 ✅

---

## 5. 已知限制（诚实清单）

1. **onefile 首启慢**（~5.5s）：每次启动自解包 ~230MB 到 `%TEMP%` → **推荐 onedir**。
2. **体积 ~230 MB**：ONNX Runtime + OpenCV + numpy 就这些；已摘掉 torch。
3. **exe 产物不进 git**：几百 MB；spec 与脚本进。
4. **`--noconsole` 后无输出**：排错必须用带控制台的构建。
5. **独占全屏下悬浮窗可能看不见** → 建议游戏用「窗口化全屏/无边框」（同实时文档 §10）。
6. **模型权重在 exe 里是可见的**：`_internal/out/*.onnx`、模板库 `.npz` 都在包内，
   即使不公开源码，**权重也是公开的**。

---

## 6. 故障排查

| 症状 | 先查 |
|---|---|
| 双击没反应 | 用**带控制台**的构建跑一次，看报错 |
| 找不到资源 / 模型加载失败 | 是否把 exe **复制到仓库外**跑了？资源按 exe 位置解析 |
| 控制台一闪而过 | 控制台编码问题（§3.3）；或程序崩在 `print` |
| 悬浮窗纯黑 | `WS_EX_LAYERED` 未清除 + 深色配色（见实时文档 §2.2 / §2.3）|
| 数字一直不动 | 悬浮窗是否**压住行动轴**（见实时文档 §2.1）→ 用 `--pos` 挪开 |
| 标记识别全空 | 标记模板库是否**静默变空**（§3.4）|

---

## 7. 复现命令速查

```powershell
cd D:\project\hsr-damage-meter
$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUNBUFFERED='1'

# ① 改动后先跑源码模式三件套（别跳）
python eval_holdout.py ; python axis_actor.py --selftest ; python -u events_v4.py --anchors

# ② 源码模式基线（exe 必须与它逐项相同）
python mvp/live_mvp.py --replay frames/glyphcache --range 98,340 --step 0 --no-overlay
#    → 期望：遐蝶 5,686,611 / 长夜月 3,265,051 / 风堇 1,348,907 / 昔涟 815,302
#            合计 11,115,871，事件 42（待复核 9），保险丝 0

# ③ 构建：排错版（带控制台）→ 确认干净 → 交付版（无控制台）
python build_exe.py --mode onedir
python build_exe.py --mode onedir --name HSR伤害统计 --readme out\交付说明_模板.txt

# ④ 拷到仓库外再验（"资源不靠工作目录"的关键一步）
.\dist\HSR伤害统计\HSR伤害统计.exe --selftest
```
