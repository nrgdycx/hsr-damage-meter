# -*- coding: utf-8 -*-
"""把 mss 的 wheel 下载并解包到 ./vendor（绕过 pip 在沙箱内的临时目录写入失败）。

背景：本会话沙箱下 `pip install` 会在解包临时目录写 `<wheel>.metadata` 时报
EACCES（手动 python 写入同一目录却正常）。mss 是纯 Python wheel（py3-none-any），
因此直接"下载 + 解压"等价于安装。
"""
# [P3 整理] 原路径：install_mss_B.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import os
import ssl
import sys
import urllib.request
import zipfile

URL = ("https://files.pythonhosted.org/packages/f2/c3/313e14f245c79b4c05bd0f3a84a4813aa26fa10f8993aebd91d04c5fad3f/"
       "mss-10.2.0-py3-none-any.whl")
_r = os.path.dirname(os.path.abspath(__file__))
while _r != os.path.dirname(_r) and not os.path.isfile(
        os.path.join(_r, "tools", "tools_bootstrap.py")):
    _r = os.path.dirname(_r)
HERE = _r          # [P3] = 仓库根（搬家前 __file__ 就是仓库根）
VENDOR = os.path.join(HERE, "vendor")
WHL = os.path.join(VENDOR, "mss-10.2.0-py3-none-any.whl")


def main():
    os.makedirs(VENDOR, exist_ok=True)
    if not os.path.exists(WHL):
        # pip 能用网络，说明有可用 CA；优先用 certifi（pip 自带的更稳）
        ctx = ssl.create_default_context()
        try:
            import certifi  # type: ignore
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            pass
        req = urllib.request.Request(URL, headers={"User-Agent": "python-urllib"})
        with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
            data = r.read()
        with open(WHL, "wb") as f:
            f.write(data)
        print("下载完成 %d 字节 -> %s" % (len(data), WHL))
    else:
        print("已存在 %s" % WHL)

    with zipfile.ZipFile(WHL) as z:
        names = z.namelist()
        z.extractall(VENDOR)
    print("解包 %d 个条目 -> %s" % (len(names), VENDOR))
    for n in sorted(names)[:8]:
        print("   ", n)


if __name__ == "__main__":
    sys.exit(main())
