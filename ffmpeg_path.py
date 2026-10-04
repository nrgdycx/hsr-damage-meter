# -*- coding: utf-8 -*-
"""
ffmpeg 可执行文件解析 —— **全项目唯一入口**。

## 为什么有这个模块

原来 19 个文件里各自硬编码了作者本机的路径：
```python
FF = r"C:\\Users\\<用户名>\\Desktop\\a\\vsc\\node_modules\\
        @remotion\\compositor-win32-x64-msvc\\ffmpeg.exe"
```
后果：① 别人 clone 下来**根本跑不了**；② 把作者的 Windows 用户名写进了仓库。

现在改成按顺序查找（**找到就返回，找不到返回 None 并给清晰指引**）：

1. 显式传入的参数（`find_ffmpeg("/path/to/ffmpeg")`）
2. 环境变量 `HSR_FFMPEG`（推荐：最明确，跨机器可用）
3. 环境变量 `FFMPEG`（兼容早期脚本用的名字）
4. **`PATH` 里的 `ffmpeg`**（`shutil.which`）
5. 本机已知兜底位置（Remotion 捆绑版等；**仅为作者本机方便**）
6. 常见系统安装位置（`C:/ffmpeg/bin/ffmpeg.exe`、`/usr/bin/ffmpeg`、`/usr/local/bin/ffmpeg`）

## 用法

```python
from ffmpeg_path import FFMPEG or find_ffmpeg

FF = FFMPEG                      # 模块导入时解析一次（找不到就是 None）
ff = find_ffmpeg()               # 需要时再找；找不到抛清晰错误
ff = find_ffmpeg(explicit)       # 带显式参数
```

⚠️ **注意**：作者本机那个 Remotion 捆绑版是**精简版**（`fps` / `crop` / `select` 滤镜不可用），
只能 `-ss` 逐帧抽。用别的 ffmpeg 反而**功能更全**，所以这个模块只负责"找到"，
不负责保证滤镜可用 —— 各脚本自己按需处理。

## 给用户的话（会写进 README）

> 本项目需要 **ffmpeg**。任选一种：
> * Windows：`winget install Gyan.FFmpeg`（装完重开终端）
> * 或下载后把 `ffmpeg.exe` 所在目录加进 `PATH`
> * 或设环境变量：`setx HSR_FFMPEG "D:\\tools\\ffmpeg\\bin\\ffmpeg.exe"`
"""

from __future__ import annotations

import os
import shutil

#: 本机兜底位置 —— **从 gitignore 的 `ffmpeg_path_local.py` 读**，
#: 所以发布出去的仓库里**不含任何用户名/本机路径**。
#: （本机想兜底就建那个文件，或直接设 `HSR_FFMPEG`；见该文件里的说明。）
try:
    from ffmpeg_path_local import FALLBACKS as _LOCAL_FALLBACKS
except Exception:                      # 别人 clone 下来没有这个文件 → 正常
    _LOCAL_FALLBACKS = ()

_FALLBACKS = tuple(_LOCAL_FALLBACKS) + (
    # 常见系统安装位置（跨机器通用，可以留在仓库里）
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
    "/usr/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "/opt/homebrew/bin/ffmpeg",
)


def find_ffmpeg(explicit: str | None = None) -> str | None:
    """按 §用法 的顺序找 ffmpeg；**找不到返回 None**（不抛异常，调用方自己决定怎么办）。"""
    cands: list[str | None] = [
        explicit,
        os.environ.get("HSR_FFMPEG"),
        os.environ.get("FFMPEG"),
        "ffmpeg",                      # 交给 PATH
        "ffmpeg.exe",
    ]
    cands += list(_FALLBACKS)

    for c in cands:
        if not c:
            continue
        # 像路径（含分隔符或以 .exe 结尾）→ 直接查文件存在
        if os.sep in c or c.endswith(".exe"):
            if os.path.isfile(c):
                return c
            continue
        # 否则当命令名，查 PATH
        p = shutil.which(c)
        if p:
            return p
    return None


def require_ffmpeg(explicit: str | None = None) -> str:
    """找 ffmpeg；**找不到就抛出带指引的错误**（给需要硬依赖的脚本用）。"""
    ff = find_ffmpeg(explicit)
    if ff:
        return ff
    raise SystemExit(
        "找不到 ffmpeg。请任选一种方式：\n"
        "  · Windows: winget install Gyan.FFmpeg   （装完重开终端）\n"
        "  · 或把 ffmpeg.exe 的目录加进 PATH\n"
        '  · 或设环境变量: setx HSR_FFMPEG "D:\\tools\\ffmpeg\\bin\\ffmpeg.exe"\n'
        "（本项目原先硬编码了作者本机路径，现已改为自动查找。）"
    )


#: 模块级解析结果。脚本可直接 `FFMPEG = ffmpeg_path.FFMPEG` 后使用；
#: 为 None 时应自行调用 `require_ffmpeg()` 拿到带指引的报错。
FFMPEG = find_ffmpeg()


if __name__ == "__main__":
    print("find_ffmpeg() ->", find_ffmpeg())
    print("HSR_FFMPEG 环境变量 =", os.environ.get("HSR_FFMPEG"))
    print("FFMPEG 环境变量     =", os.environ.get("FFMPEG"))
    print("PATH 里的 ffmpeg    =", shutil.which("ffmpeg"))
