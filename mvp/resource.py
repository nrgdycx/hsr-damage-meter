# -*- coding: utf-8 -*-
"""[MVP] 资源路径统一解析：**源码模式与打包（PyInstaller）模式共用同一套代码**。

要解决的问题（打包专项 §4）
--------------------------
项目里的运行时资源（`out/digit_cnn.onnx` + `.onnx.data`、三个 `.npz` 模板库）原来都是
**相对当前工作目录**写死的。打包成 exe 后工作目录可能是桌面 / 快捷方式起始目录 / 任意位置
→ 一读就 `FileNotFoundError`（或者更糟：静默读到**错误的老模型**）。

本模块给出唯一入口 `resource(rel)`，按下面的顺序找，**第一个存在的**就是答案：

    1. `<exe 同级>/rel`        ← 打包后：允许用户**不改 exe 就换模型**（把 out/ 放 exe 旁边）
    2. `<打包解包目录>/rel`     ← 打包后：PyInstaller 收进包里的那份
                                  （onefile = 临时解包目录；onedir = exe 同级的 _internal/）
    3. `<仓库根>/rel`          ← 源码模式（也兜住"exe 被放进仓库里跑"这种情况）

源码模式下 1 和 3 是同一个目录，行为与改动前**逐字节相同**（`os.path.join(ROOT, rel)`）。

其它：
    `exe_dir()` / `repo_root()` / `bundle_dir()` / `is_frozen()`
    `chdir_runtime()` —— 源码模式 chdir 到仓库根（老行为），打包模式 chdir 到 **exe 所在目录**
                        （否则相对路径的产出，如 `--dump-readings xx.csv`，会掉进 onefile 的
                         临时解包目录里，exe 一退就没了）
    `report()`        —— 排查用：把上面每一步的解析结果打出来（`python mvp/resource.py`）

⚠️ 本模块**只做路径解析**，不引入 numpy/cv2/torch，可以被任何上游模块安全地 import。
"""
from __future__ import annotations

import os
import sys

# 运行时资源清单（打包 spec 的 datas 与 `--selftest` 的检查表都照这份走，避免两处漂移）
RESOURCES = (
    "out/digit_cnn.onnx",           # HUD 数字分类器（onnxruntime）
    "out/digit_cnn.onnx.data",      # ↑ 的外部权重文件（必须与 .onnx 同目录）
    "out/digit_cnn.probe.npz",      # 新鲜度探针（ONNX 与 .pt 等价性）
    # ⭐ 2026-10-05：像素体（银狼999 强普）那套**必须一起进包**，否则实时兜底要么缺模型、
    #    要么没有等价性探针（`check_model_freshness` 会拿默认字体的探针去比 → 必然误报）。
    "out/digit_cnn_yinlang999.onnx",
    "out/digit_cnn_yinlang999.onnx.data",
    "out/digit_cnn_yinlang999.probe.npz",
    # ⭐⭐ 2026-10-05 二轮：**T2 判定的数据文件**。漏任何一个都会**静默失效**：
    #    `t2_card_bank.npz` → 盲盒/红兔认不出（盲盒伤害不记录，用户实机报过两次）；
    #    `t2_aha_*`       → 阿哈时刻判不出"框里是谁"；
    #    `teams/owners.json` → 忆灵归属覆盖丢失，召唤物记成自己的名字。
    "out/t2_card_bank.npz",
    "out/t2_aha_bank.npz",
    "out/t2_aha_labels.json",
    "out/t2_aha_timeline.json",
    "out/teams/owners.json",
    "out/axis_top_bank_E.npz",      # 行动轴单位模板库（录屏1 的 8 个单位）
    "out/axis_top_bank_E2.npz",     # 行动轴单位模板库（录屏2 的 4 个单位）
    "out/axis_marker_bank_E.npz",   # 左侧标记模板库（判敌我 / 行动类型）
    # P1：**全分辨率实机帧**（1.6MB）。带它进包是为了让 exe 的 `--selftest` 能做
    # **真实一帧的端到端读数断言**（框选择 + 掩膜 + 分割 + ONNX 分类全链），
    # 而不是只拿随机字形证明"能推理"。真值与来历见 out/real_frames/README.md。
    "out/real_frames/live_2880x1800_73431_q88.jpg",
    # ⭐ 2026-10-05：像素体（狼尊强普）的两张真值 HUD 区域（770×148，各 ~55KB）。
    #    带它们进包是为了让 exe 自检能对**像素体读数**做端到端断言 ——
    #    这一路连坏过三轮（喂错区域 / 蓝云穿掩膜 / 几何闸误杀），"能加载模型"完全看不出来。
    "out/real_frames/pixel_t100_506286.png",
    "out/real_frames/pixel_t200_2052321.png",
    # ⭐ 2026-10-05：T2 顶端卡种类的三张真值小块（盲盒 / 红兔 / 普通卡）→
    #    exe 自检能断言"盲盒认得出、红兔判成敌方 buff、普通卡不误判"。
    "out/real_frames/t2_blindbox_t86.png",
    "out/real_frames/t2_enemybuff_t137.png",
    "out/real_frames/t2_unit_t85.png",
)

_CACHE = {}


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打出来的 exe 里。"""
    return bool(getattr(sys, "frozen", False))


def repo_root() -> str:
    """仓库根（本文件在 `mvp/` 里，往上一级）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def exe_dir() -> str:
    """exe 所在目录；源码模式 = 仓库根。"""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return repo_root()


def bundle_dir() -> str:
    """打包解包目录（`sys._MEIPASS`，PyInstaller 把 datas 摊在这里）；源码模式 = 仓库根。"""
    if is_frozen():
        return os.path.abspath(getattr(sys, "_MEIPASS", None) or exe_dir())
    return repo_root()


def search_dirs():
    """资源搜索目录（去重、保序）。"""
    out = []
    for d in (exe_dir(), bundle_dir(), repo_root()):
        d = os.path.abspath(d)
        if d not in out:
            out.append(d)
    return out


def search_paths(rel):
    """`rel` 在所有搜索目录下的候选绝对路径（按优先级）。"""
    return [os.path.normpath(os.path.join(d, rel)) for d in search_dirs()]


def resource(rel) -> str:
    """相对资源路径 → **绝对路径**（存在的优先；都不存在时给首选路径，便于报错时看出找过哪里）。

    绝对路径原样返回。结果缓存（运行期目录不会变）。
    """
    if not rel:
        return exe_dir()
    if os.path.isabs(rel):
        return os.path.normpath(rel)
    key = os.path.normpath(rel)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    cands = search_paths(key)
    for p in cands:
        if os.path.exists(p):
            _CACHE[key] = p
            return p
    _CACHE[key] = cands[0]
    return cands[0]


def exists(rel) -> bool:
    return os.path.exists(resource(rel))


def missing(paths=RESOURCES):
    """清单里**找不到**的资源（打包自检用）。"""
    return [rel for rel in paths if not os.path.exists(resource(rel))]


def chdir_runtime() -> str:
    """把工作目录切到"运行时基准目录"（打包 = exe 所在目录；源码 = 仓库根），返回该目录。

    切不过去（只读目录/权限）不致命：所有运行时资源都走 `resource()` 的绝对路径，
    只有**用户用相对路径指定的产出**（`--dump-readings`）才依赖它。
    """
    d = exe_dir()
    try:
        os.chdir(d)
    except OSError:
        pass
    return d


# 无控制台时的落盘日志名（与 exe 同目录；P2 之后交付版 exe 是 windowed，必须能留证）
LOG_NAME = "运行日志.txt"


def _stamp() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def has_console() -> bool:
    """当前进程**有没有可用的控制台**（PyInstaller 的 windowed 版 stdout 是 None）。"""
    if sys.stdout is None or sys.stderr is None:
        return False
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.GetConsoleWindow())
    except Exception:
        # 判断不了就当"有"，保持老行为（源码模式在 IDE / 管道下也不该被改动）
        return True


class _LogSink:
    """把 stdout/stderr 一起落到**同一个文件**（UTF-8、立即 flush）。

    为什么需要（P2）：交付版 exe 用 windowed（不再多弹一个控制台窗口），此时
    `print` 无处可去 —— 实时事件、汇总、`--selftest` 结果全都会消失，
    出问题就完全无据可查。所以把它们写进 exe 同目录的 `运行日志.txt`。

    ⚠️ **逐字保真**：`print("a", "b")` 会分多次 `write()` 调用（"a"、" "、"b"、"\n"），
    所以这里**按换行缓冲**、只补上行首时间戳，绝不改写字内容 —— 日志才能直接与源码模式
    的终端输出逐行对照（这是 `docs/EXE打包.md` §4.2 的对账口径）。
    每 4KB 或每个换行落一次盘；`close()` 会把最后一段没有换行的内容补出去。
    """

    _MAXBUF = 4096

    def __init__(self, fh):
        self._fh = fh
        self._buf = ""
        self.encoding = "utf-8"
        self.errors = "replace"

    def write(self, s):
        if not s:
            return 0
        try:
            self._buf += str(s).replace("\r\n", "\n").replace("\r", "\n")
            if "\n" in self._buf or len(self._buf) >= self._MAXBUF:
                head, _, tail = self._buf.rpartition("\n")
                if head or tail == "":
                    first, *rest = (head + "\n").split("\n")
                    out = ["%s  %s\n" % (_stamp(), first)]
                    out.extend(l + "\n" for l in rest[:-1])
                    self._fh.write("".join(out))
                    self._buf = tail
                self._fh.flush()
        except Exception:
            pass
        return len(s)

    def flush(self):
        try:
            self._fh.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        return False

    def close(self):
        try:
            if self._buf:
                self._fh.write("%s  %s\n" % (_stamp(), self._buf))
                self._buf = ""
            self._fh.write("%s  ---- 结束 ----\n" % _stamp())
            self._fh.flush()
        except Exception:
            pass


def _open_log_sink():
    """把日志开到 `<exe 同目录>/运行日志.txt`（失败则退到 %TEMP%，再失败则 None）。"""
    import tempfile
    banner = ("\n" + "=" * 66 +
              "\n%s  启动：%s\n%s  （无控制台 → 本次输出全部写在本文件）\n" % (
                  _stamp(), " ".join(sys.argv[:8]), LOG_NAME))
    for d in (exe_dir(), tempfile.gettempdir()):
        try:
            p = os.path.join(d, LOG_NAME)
            fh = open(p, "a", encoding="utf-8", errors="replace")
            fh.write(banner)
            fh.flush()
            return _LogSink(fh)
        except Exception:
            continue
    return None


def setup_console(log_file: bool = True) -> bool:
    """把标准输出准备好：**有控制台** → UTF-8 重定向；**没有控制台** → 落到日志文件。

    为什么要 UTF-8（打包专项实测踩到）：PyInstaller 打出来的 exe **不认**
    `PYTHONIOENCODING` 环境变量，控制台默认走 GBK(cp936) →
    `UnicodeEncodeError: 'gbk' codec can't encode character '\\u2713'`，
    而且因为发生在 `print` 里，**未捕获异常直接把进程干掉**（双击时表现为"闪一下就没了"）。

    为什么要日志文件（P2 用户反馈 3）：windowed 版（`HSR_NOCONSOLE=1`）里
    `sys.stdout is None`，`print` 会 AttributeError —— 旧代码把它换成 `os.devnull` 丢弃，
    等于**交付版没有任何输出**。现在改成写 `运行日志.txt`（可用 `log_file=False` 关掉）。

    返回：是否落到了日志文件（True = 当前输出进的是 `运行日志.txt`）。
    """
    if os.name == "nt":
        try:
            import ctypes
            if has_console():
                ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass

    to_log = log_file and not has_console()
    if to_log:
        sink = _open_log_sink()
        if sink is not None:
            sys.stdout = sink
            sys.stderr = sink
            try:
                import atexit
                atexit.register(sink.close)      # 正常退出时补出最后一段 + 结束标记
            except Exception:
                pass
            return True

    for name in ("stdout", "stderr"):
        s = getattr(sys, name, None)
        if s is None:
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
            except Exception:
                pass
            continue
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    return False


def report(paths=RESOURCES) -> str:
    """排查用多行报告：模式 / 三个目录 / 每个资源的解析结果。"""
    lines = ["运行模式：%s" % ("打包 exe（sys.frozen）" if is_frozen() else "源码"),
             "exe 目录  ：%s" % exe_dir(),
             "解包目录  ：%s" % bundle_dir(),
             "仓库根    ：%s" % repo_root(),
             "工作目录  ：%s" % os.getcwd(),
             ""]
    for rel in paths:
        p = resource(rel)
        ok = "✓" if os.path.exists(p) else "✗ 缺失"
        size = ""
        if os.path.exists(p):
            size = "%9d B" % os.path.getsize(p)
        lines.append("  %-1s %-28s %s  %s" % (ok, rel, size, p))
    return "\n".join(lines)


if __name__ == "__main__":
    setup_console()
    sys.stdout.write(report() + "\n")
    miss = missing()
    if miss:
        sys.stdout.write("\n缺少 %d 项资源：%s\n" % (len(miss), ", ".join(miss)))
    raise SystemExit(1 if miss else 0)
