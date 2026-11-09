# 打包工具（给自己用的，不用发给群友）

一条命令出包：

```powershell
& "C:\Users\王\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" ".\_打包工具\build.py"
```

大概 2~3 分钟，产出两样东西（都会自动拷到项目根目录）：

- `MO数值编辑器.exe` —— 单文件，发给群友就用这个
- `文件夹版\` —— exe + `_internal` 文件夹，杀软误杀单文件时用

## 目录里都是什么

```
fetch.py      第一次用（或者换电脑）时跑它，从 PyPI 下 PyInstaller 及其依赖
wheels\       下下来的 wheel 包（缓存，别删，删了要重新下）
pylibs\       解压后的库，build.py 通过 PYTHONPATH 用它（约 11MB）
build.py      出包脚本
dist1\ dist2\ _build1\ _build2\ _tmp\   每次打包的临时产物（可以随时删）
```

## 几个坑（踩过）

- 本机自带的 `MOINIEditor\python\` 里**没有 pip**，所以不能用 `pip install`。
  而且这个环境里 pip 写不了工作区（`Permission denied`），所以走的是
  “手工下 wheel → zipfile 解压”这条路，见 `fetch.py`。
- wheel 要挑 **win_amd64** 的（PyInstaller 有 win32/win_amd64/macosx 三个版本，
  选错会拿到 mac 的 bootloader）。
- 打出来的单文件 exe 在**这个开发环境里跑不起来**（沙箱不让它往临时目录解包，
  报 `fopen: Permission denied`），不是包坏了。验证请用 `文件夹版\`。
- 换版本号：改 `app\moini.pyw` 顶部的 `APP_VERSION`，重新打一次包。
