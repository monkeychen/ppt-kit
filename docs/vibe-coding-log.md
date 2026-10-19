# vibe-coding 踩坑记录

> 倒序追加，新的在上。格式见 ~/.gemini/dev-workflow.md。

## 2026-10-19 | 真实 AI 幻灯片位图文字抹除与字号估算的三个视觉陷阱
- 现象：在真实样图 `01-ai-beginner-workflow.jpg` 上首次跑通位图重建后，PowerPoint 渲染图出现三处瑕疵：1）`07` 绿色胶囊被抹白、字号变大；2）`11` 黄色胶囊内的白字被误判为黄色；3）单靠 `bbox_h * 0.78` 估算字号导致长行文字偏小 15% 或碰到虚线时字号暴涨。
- 原因：1）Apple Vision 将 `07` 上方的绿色虚线并入了 `o7 回答AI...` 的检测框（`h=69px`），按整个外框涂抹时把绿色胶囊和虚线一起抹掉了；2）`11` 的检测框紧贴黄色胶囊外缘，外扩 3px 环形采样踩到了外部米白底色，误把黄色胶囊当成前景文字色；3）CJK 字体高度易受邻近分隔线干扰，而水平字宽除以字符 em 数（`w_pt / ems`）对垂直噪声完全免疫。
- 解决：1）在 `clean_ocr_boxes` 拆分编号与正文时，根据正文字符平均宽度自动收敛虚线拉高的 `y, h`；2）`sample_local_background_rgb` 在外环方差大且与框内中位数色差显著时，回退使用框内中位数作为局部背景色；3）`inpaint_text_regions` 仅对偏离局部背景色的笔画像素膨胀掩码填充，不动背景纸张纹理与边框；4）`estimate_text_style` 联合 `box_h_pt` 与 `box_w_pt / ems` 估算字号。
- 适用范围：复杂排版位图幻灯片的 OCR 清洗、背景修复与字号估算

## 2026-10-19 | macOS PowerPoint AppleScript 沙盒导出与 save as PNG 静默失败
- 现象：用 AppleScript 调用 PowerPoint 打开文件时，`set pres to open POSIX file ...` 返回空引用报错 `-2753`；改用 `active presentation` 后，`save pres in ... as save as PNG` 不报错但磁盘上不生成任何文件。
- 原因：1）PowerPoint for Mac 的 `open` 命令不直接返回 `presentation` 对象引用，必须先 `open` 再通过 `active presentation` 获取；2）App Sandbox 限制了写入路径，且 `save as PNG` 在 AppleScript 下静默失效，而 `save as PDF` 写入沙盒容器的 `~/Library/Containers/com.microsoft.Powerpoint/Data/Documents/` 目录完全正常。
- 解决：将 PPTX 复制到 `~/Library/Containers/com.microsoft.Powerpoint/Data/Documents/` 子目录，通过 `open` + `active presentation` 打开后，使用 `save pres in (... as POSIX file) as save as PDF` 导出矢量 PDF，再用 PyMuPDF (`fitz`) 按目标 DPI 栅格化为 PNG。
- 适用范围：macOS PowerPoint 自动化渲染


