# -*- coding: utf-8 -*-
"""下载 PyInstaller 及其依赖的 wheel 包到 _打包工具\\wheels，并解压到 pylibs。

用法（用 DSH 的 python 跑，本机 python 目录里没有 pip）：
    python fetch.py
只需在第一次打包前跑一次；之后 build.py 直接用 pylibs 里的东西。
"""
import json
import os
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
WHEELS = os.path.join(HERE, "wheels")
PYLIBS = os.path.join(HERE, "pylibs")

PACKAGES = [
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "altgraph",
    "pefile",
    "pywin32-ctypes",
    "packaging",
    "setuptools",
]


def pick(releases):
    """挑一个能在 Windows + 本机 python 上用的 wheel。"""
    best = None
    for rel in releases:
        fn = rel["filename"]
        if not fn.endswith(".whl"):
            continue
        low = fn.lower()
        if any(bad in low for bad in ("macosx", "manylinux", "musllinux", "linux", "aarch64")):
            continue
        plat = rel.get("platform") or ""
        if plat and "win_amd64" not in plat and "win32" not in plat:
            continue
        if "win" not in low and "any" not in low:
            continue
        if "win_amd64" in low:
            score = 3                       # 64 位 Windows 优先
        elif "any" in low:
            score = 2                       # 纯 python
        elif "win32" in low:
            score = 1
        else:
            score = 0
        if best is None or score > best[0]:
            best = (score, rel)
    return best[1] if best else None


def get(name):
    url = "https://pypi.org/pypi/%s/json" % name
    with urllib.request.urlopen(url, timeout=60) as r:
        data = json.load(r)
    files = data["releases"].get(data["info"]["version"]) or []
    rel = pick(files)
    if rel is None:
        print("!! 没有合适的 wheel:", name)
        return None
    dst = os.path.join(WHEELS, rel["filename"])
    if os.path.exists(dst) and os.path.getsize(dst) == rel["size"]:
        print("已存在", rel["filename"])
        return dst
    print("下载", rel["filename"])
    with urllib.request.urlopen(rel["url"], timeout=120) as r, open(dst, "wb") as f:
        f.write(r.read())
    return dst


def main():
    os.makedirs(WHEELS, exist_ok=True)
    os.makedirs(PYLIBS, exist_ok=True)
    ok = []
    for name in PACKAGES:
        try:
            p = get(name)
            if p:
                ok.append(p)
        except Exception as e:
            print("!! %s 失败: %s" % (name, e))
    for p in ok:
        print("解压", os.path.basename(p))
        with zipfile.ZipFile(p) as z:
            z.extractall(PYLIBS)
    print("完成，解压到:", PYLIBS)


if __name__ == "__main__":
    main()
