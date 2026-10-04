# -*- coding: utf-8 -*-
"""[专项] 一键构建 MVP 的 exe（onedir / onefile）+ 打 zip + 报体积。

    python build_exe.py                          # 默认：onedir + 无控制台 + 打 zip（= 交付形态）
    python build_exe.py --console                # 带控制台窗口（调试用：看得到报错/实时事件）
    python build_exe.py --name HSR伤害统计        # 指定产物名（目录名与 exe 名都用它）
    python build_exe.py --name HSR伤害统计 --readme dist/HSR伤害统计/使用说明.txt
                                                 # ↑ 把给用户的一页说明放进交付目录与 zip 里
    python build_exe.py --mode both              # onedir + onefile 都出

产物（默认，name=hsr_mvp）：
    dist/hsr_mvp/hsr_mvp.exe            ← onedir：双击即用（整个目录一起拷）
    dist/hsr_mvp_onedir.zip             ← onedir 压缩包（推荐交付形态）
    dist/hsr_mvp.exe                    ← onefile（单个文件，首启慢、体积大）

交付形态（P2 定稿，见 docs/EXE打包.md）：
    python build_exe.py --name HSR伤害统计
    → dist/HSR伤害统计/HSR伤害统计.exe  +  dist/HSR伤害统计_onedir.zip
    **无控制台**：stdout 改写到 exe 同目录的 `运行日志.txt`（mvp/resource.py 的 setup_console）。

为什么用脚本而不是直接写命令：三个模式共用 spec，这里把环境变量、输出目录、打包后的
体积统计与 zip 都固定下来，**构建可复现**（spec 与脚本都进 git，exe 产物不进 git）。

⚠️ 必须在**仓库根**运行（spec 里的相对路径以本脚本所在目录为基准）。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "hud_pack.spec")
NAME = "hsr_mvp"


def _size_mb(path: str) -> float:
    if os.path.isfile(path):
        return os.path.getsize(path) / 1048576.0
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            total += os.path.getsize(os.path.join(root, f))
    return total / 1048576.0


def build(mode: str, dist: str, work: str, console: bool, name: str = NAME,
          noconfirm: bool = True) -> str:
    """跑一次 PyInstaller。mode = onedir / onefile。返回产物路径。"""
    env = dict(os.environ)
    env["HSR_ONEFILE"] = "1" if mode == "onefile" else "0"
    env["HSR_NOCONSOLE"] = "1" if not console else "0"
    env["HSR_NAME"] = name
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    cmd = [sys.executable, "-m", "PyInstaller", "--log-level", "WARN",
           "--distpath", dist, "--workpath", os.path.join(work, mode)]
    if noconfirm:
        cmd.append("--noconfirm")
    cmd.append(SPEC)
    print("\n=== 打包 %s（name=%s，console=%s）===\n%s"
          % (mode, name, console, " ".join(cmd)))
    t0 = time.time()
    # 不用管道抓输出（沙箱下抓子进程 stdio 可能被拒，且构建日志本来就该直接看）
    rc = subprocess.call(cmd, cwd=HERE, env=env)
    if rc != 0:
        raise SystemExit("PyInstaller 失败（%s，退出码 %d）" % (mode, rc))
    print("=== %s 完成，用时 %.0fs ===" % (mode, time.time() - t0))
    out = os.path.join(dist, name + (".exe" if mode == "onefile" else ""))
    if not os.path.exists(out):
        raise SystemExit("没找到产物 %s（PyInstaller 布局变了？）" % out)
    return out


def zip_onedir(onedir: str, out_zip: str) -> str:
    """把 onedir 目录打成 zip（解压后直接双击里面的 exe；目录名保留）。"""
    if os.path.exists(out_zip):
        os.remove(out_zip)
    base = os.path.dirname(onedir)
    root_name = os.path.basename(onedir)
    n = 0
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for cur, _dirs, files in os.walk(onedir):
            for f in files:
                p = os.path.join(cur, f)
                z.write(p, os.path.join(root_name, os.path.relpath(p, onedir)))
                n += 1
    print("已打 zip：%s（%d 个文件，%.1f MB）" % (out_zip, n, _size_mb(out_zip)))
    return out_zip


def copy_readme(onedir: str, readme: str) -> str:
    """把给用户的一页说明拷进交付目录（PyInstaller 只认识它自己的产物）。"""
    if not os.path.isabs(readme):
        readme = os.path.join(HERE, readme)
    if not os.path.isfile(readme):
        raise SystemExit("--readme 指向的文件不存在：%s" % readme)
    dst = os.path.join(onedir, os.path.basename(readme))
    shutil.copyfile(readme, dst)
    print("已放入使用说明：%s" % dst)
    return dst


def main(argv=None):
    ap = argparse.ArgumentParser(description="构建 MVP exe（交付形态：onedir + 无控制台）")
    ap.add_argument("--mode", choices=("onedir", "onefile", "both"), default="onedir")
    ap.add_argument("--name", default=NAME,
                    help="产物名（默认 %s，中文名也可；同时决定目录名与 exe 名）" % NAME)
    ap.add_argument("--dist", default=os.path.join(HERE, "dist"))
    ap.add_argument("--work", default=os.path.join(HERE, "build"))
    ap.add_argument("--console", action="store_true",
                    help="带控制台窗口（**调试用**：能看到报错与实时事件；交付版不要带）")
    ap.add_argument("--readme", default=None,
                    help="给用户的一页说明（如 dist/HSR伤害统计/使用说明.txt），"
                         "构建后拷进交付目录并**重新打 zip**，保证 zip 里也有它")
    ap.add_argument("--no-zip", action="store_true")
    ap.add_argument("--clean", action="store_true", help="先删掉 dist/ 与 build/")
    a = ap.parse_args(argv)

    # ⚠️ 先校验 --readme 存在：PyInstaller 会**先清空 dist/<name>/**，
    #    如果把说明放在 dist/<name>/ 里再传进来，构建一开始就把它删了，
    #    结果"构建成功但说明丢了"（P3 实测踩到）。所以在这里挡住，并给出建议位置。
    if a.readme:
        _r = a.readme if os.path.isabs(a.readme) else os.path.join(HERE, a.readme)
        if not os.path.isfile(_r):
            raise SystemExit(
                "--readme 指向的文件不存在：%s\n"
                "  ⚠️ 不要把说明放在 dist/<产物名>/ 里 —— 构建会先清空那个目录。\n"
                "  建议放在仓库里（如 out/交付说明_模板.txt），构建时由本脚本拷进交付目录。"
                % os.path.abspath(_r))

    if a.clean:
        for d in (a.dist, a.work):
            if os.path.isdir(d):
                print("删除 %s" % d)
                shutil.rmtree(d)

    modes = ["onedir", "onefile"] if a.mode == "both" else [a.mode]
    made = {}
    for m in modes:
        made[m] = build(m, a.dist, a.work, a.console, a.name)

    print("\n=== 产物与体积 ===")
    for m, p in made.items():
        print("  %-8s %8.1f MB  %s" % (m, _size_mb(p), p))
    if "onedir" in made and a.readme:
        # ⚠️ 必须在打 zip **之前**放进去，否则 zip 里没有使用说明
        copy_readme(made["onedir"], a.readme)
    if "onedir" in made and not a.no_zip:
        zip_onedir(made["onedir"], os.path.join(a.dist, a.name + "_onedir.zip"))
    if made.get("onedir") and _size_mb(made["onedir"]) > 400:
        print("⚠️ onedir 超过 400MB —— torch 可能没摘干净，检查 hud_pack.spec 的 excludes")
    print("\n下一步（验收）：把产物拷到**仓库外**的目录再跑，例如")
    print("  %s --selftest" % made.get("onedir", "dist\\%s\\%s.exe" % (a.name, a.name)))
    print("  %s --replay <仓库绝对路径>\\frames\\glyphcache --range 200,240 --no-overlay"
          % made.get("onedir", "dist\\%s\\%s.exe" % (a.name, a.name)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
