# 发布文件放这里（不入库）

exe 太大（约 12 MB），不建议塞进 git 历史。发布方式：

1. GitHub 仓库页面 → **Releases** → **Draft a new release**
2. Tag 填 `v1.2.1`（或 `v1.2.1-beta`），标题 `MO 数值编辑器 v1.2.1`
3. 正文直接粘贴 `docs/发布记录/1.2.1更新条目.txt` 的内容
4. 附件拖入 `MO数值编辑器.exe`（单文件版）
5. 需要的话再加一个 `文件夹版.zip`（单文件被安全软件误杀时用）

本地需要归档时，把各版本 exe 按 `releases/v1.2.1/MO数值编辑器.exe` 的目录放好，但**别 `git add` 这个目录**（.gitignore 已忽略 `*.exe`）。
