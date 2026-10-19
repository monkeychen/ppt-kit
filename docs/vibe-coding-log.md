# vibe-coding 踩坑记录

> 倒序追加，新的在上。格式见 ~/.gemini/dev-workflow.md。

## 2026-10-19 | macOS PowerPoint AppleScript 沙盒导出与 save as PNG 静默失败
- 现象：用 AppleScript 调用 PowerPoint 打开文件时，`set pres to open POSIX file ...` 返回空引用报错 `-2753`；改用 `active presentation` 后，`save pres in ... as save as PNG` 不报错但磁盘上不生成任何文件。
- 原因：1）PowerPoint for Mac 的 `open` 命令不直接返回 `presentation` 对象引用，必须先 `open` 再通过 `active presentation` 获取；2）App Sandbox 限制了写入路径，且 `save as PNG` 在 AppleScript 下静默失效，而 `save as PDF` 写入沙盒容器的 `~/Library/Containers/com.microsoft.Powerpoint/Data/Documents/` 目录完全正常。
- 解决：将 PPTX 复制到 `~/Library/Containers/com.microsoft.Powerpoint/Data/Documents/` 子目录，通过 `open` + `active presentation` 打开后，使用 `save pres in (... as POSIX file) as save as PDF` 导出矢量 PDF，再用 PyMuPDF (`fitz`) 按目标 DPI 栅格化为 PNG。
- 适用范围：macOS PowerPoint 自动化渲染

