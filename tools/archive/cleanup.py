# -*- coding: utf-8 -*-
"""清理 pip 在工作区留下的临时目录（能在沙箱内删的就删，删不掉的如实报告）。"""
# [P3 整理] 原路径：cleanup_B.py（已移入 tools/，功能见 tools/README.md）
import os as _os, sys as _sys  # noqa: E401  [P3] 让脚本在 tools/ 里也能找到仓库根（见 tools/README.md）
_t = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))   # .../<仓库>/tools
if _os.path.isdir(_t) and _t not in _sys.path:
    _sys.path.insert(0, _t)
from tools_bootstrap import *  # noqa: E402,F401,F403
import os
import shutil

base = r"D:\project\hsr-damage-meter\.piptmp"
if not os.path.isdir(base):
    print("没有 %s，无需清理" % base)
    raise SystemExit(0)

left = []
for name in sorted(os.listdir(base)):
    p = os.path.join(base, name)
    try:
        if os.path.isdir(p):
            shutil.rmtree(p)
        else:
            os.remove(p)
    except Exception as e:
        left.append((name, "%s: %s" % (type(e).__name__, e)))
try:
    os.rmdir(base)
    print("已删除 %s" % base)
except Exception as e:
    print("保留 %s（%s）" % (base, e))
    for n, why in left:
        print("   删不掉: %s  (%s)" % (n, why))
    print("   剩余 %d 项；这些目录的权限项里没有当前用户，只有 OWNER RIGHTS/SYSTEM/管理员，"
          "沙箱内的令牌动不了（详见 out/acl_reports/ 的诊断报告）。要清掉需本会话切到完全权限。" % len(left))
