# -*- mode: python ; coding: utf-8 -*-
"""[专项] MVP 实时悬浮窗的 PyInstaller 打包配置（exe）。

用法（**必须从仓库根调用**，这样 spec 里的相对路径才有意义）：

    python -m PyInstaller --noconfirm hud_pack.spec              # onedir（默认，首启快）
    $env:HSR_ONEFILE='1'; python -m PyInstaller --noconfirm hud_pack.spec   # onefile
    $env:HSR_NOCONSOLE='0'; python -m PyInstaller --noconfirm hud_pack.spec # 带控制台（调试）
    $env:HSR_NAME='HSR伤害统计'; python -m PyInstaller --noconfirm hud_pack.spec  # 改产物名

推荐直接跑 `python build_exe.py`（会把上面几条串起来 + 打 zip + 打体积）。

交付形态（P2）：**默认无控制台**（`HSR_NOCONSOLE` 不设或为 1）—— 用户反馈"双击后多出一个
黑窗口"。代价是 `print` 无处可去，所以 `mvp/resource.py` 的 `setup_console()` 会把输出
落到 exe 同目录的 `运行日志.txt`。要排查启动期报错就用 `python build_exe.py --console`
打一个带控制台的版本（`docs/EXE打包.md` §6）。

三条要点（对应 docs/专项_EXE打包.md §3/§4）
  1. **必须 excludes 掉 torch**：`mvp/reader.py` 里对 `read_hud` 的 import 已改成惰性，
     但 PyInstaller 是**按字节码扫描**的 —— 函数体内的 `import read_hud` 照样会被它跟进去，
     而 read_hud 顶层 `import torch`（600MB~1GB）。所以"惰性 import"只保证**运行时**不加载
     torch，**打包时**还得靠 excludes 拦住。两个都要做。
  2. **datas 带上全部运行时资源**（onnx + 外部权重 .data + 探针 + 三个 npz 模板库），
     落到包内 `out/` 下 —— 与 `mvp/resource.py` 的搜索顺序对应。
  3. **pathex 加 vendor/**：mss 装在仓库内的 `vendor/`（本工作区 pip install 不可用）。
"""
import os
import sys

# SPECPATH 由 PyInstaller 注入（本 spec 所在目录 = 仓库根）
ROOT = os.path.abspath(SPECPATH)

NAME = os.environ.get("HSR_NAME") or "hsr_mvp"
ONEFILE = os.environ.get("HSR_ONEFILE", "0") == "1"
CONSOLE = os.environ.get("HSR_NOCONSOLE", "1") != "1"   # 默认无控制台（交付形态）

# ── 运行时资源（与 mvp/resource.py 的 RESOURCES 一一对应）────────────────────
# 缺任何一个都直接中止 —— 让它在**打包时**报错，而不是让用户双击后看到 Traceback。
DATAS_REL = [
    "out/digit_cnn.onnx",          # HUD 数字分类器（常规字体）
    "out/digit_cnn.onnx.data",     # ↑ 的外部权重（必须与 .onnx 同目录）
    "out/digit_cnn.probe.npz",     # ONNX/.pt 等价性探针（新鲜度检查用）
    # ⚠️ 2026-10-05 补：**像素字体**（狼尊强普）的分类器。
    #    实时链路现在会按行动者切字体档案（`mvp/reader.py: profile_for`），
    #    缺这两个文件时 `HudOnnxReader(profile='yinlang999')` 会**静默退回 default 模型**
    #    → 自我感觉"加载成功"，实际用错模型，强普数字照样读不出。
    "out/digit_cnn_yinlang999.onnx",
    "out/digit_cnn_yinlang999.onnx.data",
    # ⭐ 2026-10-05 补：像素体**自己的**等价性探针。没有它时 `check_model_freshness`
    #    会拿默认字体那份探针去比像素体 ONNX（档案盲）→ 必然误报"不等价"。
    "out/digit_cnn_yinlang999.probe.npz",
    "out/axis_top_bank_E.npz",     # 行动轴单位模板库（109 角色，共享库）
    "out/axis_top_bank_E2.npz",    # 行动轴单位模板库（录屏2 的 4 个单位）
    "out/axis_marker_bank_E.npz",  # 左侧标记模板库
    # ⚠️ 2026-10-05 补：**阿哈时刻认脸**（T2）的模板库与标签。
    #    缺了它们 → `aha_member` 读不到库 → 阿哈时刻判不出"框里是谁" →
    #    status 只能停在 review → **阿哈时刻的伤害进不了合计**。
    #    （用户实机反馈"阿哈时刻没反应"正是这个原因。）
    "out/t2_aha_bank.npz",
    "out/t2_aha_labels.json",
    "out/t2_aha_timeline.json",
    # ⚠️⚠️ 2026-10-05 补第二轮：**盲盒 / 红兔的卡面模板库**。
    #    上一轮只补了 `tools/team2/` 与 `t2_aha_bank.npz`，**漏了这个 npz** ——
    #    而 `card_kind_t2.load_bank()` 当时"文件不在就静默重建"（要吃 frames/ 抽帧缓存，
    #    exe 里没有）→ 抛异常 → 被 `read_actor` 的兜底吞掉
    #    → **盲盒整块功能静默失效**（用户 2026-10-05 实机："盲盒还是没记进去"）。
    "out/t2_card_bank.npz",
    # ⚠️ 2026-10-05 补：忆灵/召唤物 → 召唤者的覆盖表（`axis_actor._load_owner_overrides`）。
    #    它有 11 条（神君→景元、账账→托帕、迷迷→记忆主、龙灵→丹恒•腾荒 …），
    #    而代码里只硬编码了队伍1 的 4 条；**缺这个文件会静默退回**，
    #    于是那些召唤物的伤害记成它们自己的名字（实测过：拓星者被记成"拓星者"）。
    "out/teams/owners.json",
    # P1：实机帧 —— 让 exe 的 `--selftest` 能做**真实一帧的端到端读数断言**
    "out/real_frames/live_2880x1800_73431_q88.jpg",
    # ⭐ 2026-10-05：像素体（狼尊强普）两张真值 HUD 区域 → exe 自检对像素体读数做端到端断言
    "out/real_frames/pixel_t100_506286.png",
    "out/real_frames/pixel_t200_2052321.png",
    # ⭐ 2026-10-05：T2 顶端卡种类（盲盒 / 红兔 / 普通卡）顶端卡小块 → exe 自检能断言
    #    "盲盒认得出、红兔判成敌方 buff、普通卡不误判" —— 就是被漏掉那个 npz 的哨兵。
    "out/real_frames/t2_blindbox_t86.png",
    "out/real_frames/t2_enemybuff_t137.png",
    "out/real_frames/t2_unit_t85.png",
]

# ── 运行时要 import 的**包目录**（PyInstaller 的静态分析看不到函数体内的 import）──
# ⚠️ 2026-10-05 补：`mvp/reader.py` 在函数体里 `from tools.team2 import ...`
#    （盲盒卡判定 / 阿哈认脸 / 附伤展示口径）。**不显式带上就整块功能缺失** ——
#    用户实机反馈的"盲盒不记录"正是这个原因（exe 里根本没有 tools/team2）。
DATAS_TREE = [
    ("tools", "tools"),            # 整个 tools/ 包含 team2（T2 判定）与各诊断脚本
]

datas = []
_missing = []
for _rel in DATAS_REL:
    _src = os.path.join(ROOT, _rel)
    if not os.path.exists(_src):
        _missing.append(_rel)
        continue
    datas.append((_src, os.path.dirname(_rel)))
# 整目录带上（tools/team2 等"函数体内 import"的包）
for _srcdir, _dst in DATAS_TREE:
    _src = os.path.join(ROOT, _srcdir)
    if not os.path.isdir(_src):
        _missing.append(_srcdir + "/")
        continue
    for _dp, _dn, _fn in os.walk(_src):
        _dn[:] = [d for d in _dn if d != "__pycache__"]
        for _f in _fn:
            if _f.endswith((".pyc",)):
                continue
            _full = os.path.join(_dp, _f)
            _relsub = os.path.relpath(_dp, ROOT)
            datas.append((_full, _relsub))
if _missing:
    raise SystemExit("打包中止：缺少运行时资源 %s（先按 docs/EXE打包.md §8 重建产物）"
                     % (_missing,))

# ── 隐式依赖：这些都在函数体/条件分支里 import，显式写出来更稳 ──────────────
HIDDEN = [
    "onnxruntime",                 # hud_digits.HudOnnxReader.__init__ 里懒加载
    "onnxruntime.capi._pybind_state",
    "mss", "mss.windows", "mss.base",   # capture.Grabber.__init__ 里懒加载（在 vendor/）
    "tkinter", "tkinter.font",     # mvp/overlay.py 里懒加载
    "PIL.Image", "PIL.ImageDraw", "PIL.ImageTk",
    "geometry", "hud_glyphs", "hud_profiles", "hud_digits",
    "axis_actor", "capture", "events_v4", "events",
    "mvp.resource", "mvp.reader", "mvp.engine", "mvp.overlay", "mvp.av_reader",
]

# ── 排除：① 摘掉 torch（体积 600MB~1GB）② 顺手排掉离线分析用的重依赖 ────────
EXCLUDES = [
    "torch", "torchvision", "torchaudio", "functorch",
    # read_hud / train_digit_cnn 只在 backend='torch'（离线对账）时用；它们 =
    # "torch 的入口"。exe 里不支持 torch 后端（已知限制，见 docs/EXE打包.md）。
    "read_hud", "train_digit_cnn",
    "matplotlib", "scipy", "pandas", "IPython", "notebook", "jupyter",
    "pytest", "PIL.ImageQt",
]

a = Analysis(
    # 入口：双击 exe 弹控制面板（gui_main.py）；带命令行参数时透传给 live_mvp
    [os.path.join(ROOT, "gui_main.py")],
    pathex=[ROOT, os.path.join(ROOT, "vendor")],   # vendor/ = mss 所在（见 install_mss_B.py）
    binaries=[],
    datas=datas,
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

_common = dict(
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                       # 本机没有 UPX；也别引入额外变量
    console=CONSOLE,                 # 交付=无控制台（输出进 运行日志.txt）；调试用 HSR_NOCONSOLE=0
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],  # onefile：全部塞进单个 exe
              runtime_tmpdir=None, **_common)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **_common)
    coll = COLLECT(exe, a.binaries, a.datas,
                   strip=False, upx=False, name=NAME)
