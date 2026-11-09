# -*- coding: utf-8 -*-
"""一条命令出包：先打单文件 exe，再打文件夹版，然后把成品拷回项目根目录。

用法（在任意目录）：
    python _打包工具\\build.py
第一次用之前先跑一次 fetch.py 把 PyInstaller 下下来。

注意：要用带 email 模块的完整 Python（例如 DSH 的 python）来跑，
项目自带的 python\\ 是裁剪版，PyInstaller 会在 importlib.metadata 处报错。
"""
import io
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APP = os.path.join(ROOT, "app", "moini.pyw")
PYLIBS = os.path.join(HERE, "pylibs")
NAME = "MO数值编辑器"
ICON = os.path.join(ROOT, "_art", "app.ico")
DATA = os.path.join(ROOT, "app", "data")

ADD = []
for src, dst in ((os.path.join(DATA, "art"), "art"),
                 (os.path.join(DATA, "cn_names.json"), "."),
                 (os.path.join(DATA, "cn_faction.json"), ".")):
    ADD += ["--add-data", "%s;%s" % (src, dst)]

COMMON = ["--noconfirm", "--clean", "--windowed", "--name", NAME,
          "--icon", ICON] + ADD


def run(mode, dist, work):
    cmd = [sys.executable, "-m", "PyInstaller", mode] + COMMON + [
        "--distpath", dist, "--workpath", work, APP]
    env = dict(os.environ)
    env["PYTHONPATH"] = PYLIBS
    env.setdefault("TMP", os.path.join(HERE, "_tmp"))
    env.setdefault("TEMP", env["TMP"])
    os.makedirs(env["TMP"], exist_ok=True)
    print(">>", mode, "->", dist)
    subprocess.run(cmd, check=True, env=env)


def version():
    try:
        src = io.open(APP, encoding="utf-8").read()
        return re.search(r'APP_VERSION\s*=\s*"([^"]+)"', src).group(1)
    except Exception:
        return "unknown"


def main():
    os.chdir(ROOT)
    one = os.path.join(HERE, "dist1")
    many = os.path.join(HERE, "dist2")
    run("--onefile", one, os.path.join(HERE, "_build1"))
    run("--onedir", many, os.path.join(HERE, "_build2"))

    exe = os.path.join(one, NAME + ".exe")
    if os.path.exists(exe):
        shutil.copy2(exe, os.path.join(ROOT, NAME + ".exe"))
        print("单文件 ->", os.path.join(ROOT, NAME + ".exe"))
    folder_src = os.path.join(many, NAME)
    folder_dst = os.path.join(ROOT, "文件夹版")
    if os.path.isdir(folder_src):
        if os.path.isdir(folder_dst):
            shutil.rmtree(folder_dst, ignore_errors=True)
        shutil.copytree(folder_src, folder_dst)
        # 打包时生成的数据目录不要发给用户
        shutil.rmtree(os.path.join(folder_dst, "MOINIEditor_data"), ignore_errors=True)
        print("文件夹版 ->", folder_dst)

    # 归档：每个版本留一份 exe，供 GitHub Releases / 事后找回
    ver = version()
    arch = os.path.join(ROOT, "dist_archive", "v" + ver)
    os.makedirs(arch, exist_ok=True)
    built = os.path.join(ROOT, NAME + ".exe")
    if os.path.exists(built):
        shutil.copy2(built, os.path.join(arch, NAME + ".exe"))
        print("已归档 ->", arch)
    print("完成，版本 v%s" % ver)


if __name__ == "__main__":
    main()
