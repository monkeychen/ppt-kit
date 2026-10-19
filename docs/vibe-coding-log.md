# vibe-coding 踩坑记录

> 倒序追加，新的在上。格式见 ~/.gemini/dev-workflow.md。

## 2026-10-19 | 跨风格幻灯片通用化：容器递归拆解、内部纹理排他保护与同行多色 TextRun
- 现象：将算法迁移到第二张不同风格的真实幻灯片（`02-skill-folder-concept.jpg`）时暴露 4 个问题：1）`SKILL.md` 深蓝文档图标因深蓝像素占比 `>75%` 被压平为纯色圆角矩形，丢失内部白横线；2）橙色胶囊 `[✓ 必须有]` 与灰色胶囊 `[⛶ 可选]` 内的白色微图标与页面暖白底色相近，擦除胶囊后白色图标在白色底图上失去对比度而消失，且 `⛶` 被 OCR 误识为字母 `"L"`；3）大尺寸细描边卡片（`fill_ratio = 0.0188`）和底部浅米色横幅（`fill_ratio = 0.0539`）因低于固定 `0.06` 下限被漏检，进而在 `layers.py` 中通过 `is_enclosed` 吞并了内部灯泡图标后又因长宽比 `>8.5` 被丢弃；4）同行内「深蓝 + 橙色」双色混排文字被赋予单一中位数颜色。
- 原因：1）实心形状判定只看主体颜色占比，未检查腐蚀核内部是否存在高对比度花纹；2）内嵌白色图标只有相对于胶囊自身填充色 `fill_med` 才有显著色差，直接留在全局页面底色上无法被二次提取；3）大容器的周界像素占比随面积增大而自然下降（`2(W+H)t / (WH)`），固定 `0.06` 下限排除了大尺寸细框，且 `layers.py` 的包含合并未限制外框尺寸；4）文字样式估计对单行只生成一个 `TextRun`。
- 解决：1）将 `shapes.py` 与 `layers.py` 所有像素/面积阈值改为按短边 `min(W, H)` 动态缩放；2）对紧凑型色块增加内部腐蚀核高对比纹理排他检查（`detail_ratio >= 0.03` 则保留为图标）；3）实现容器递归拆解：以实心容器/胶囊的 `fill_med` 为局部背景构造 `sub_canvas`，递归提取内部子形状并相对于 `fill_med` 抠取内嵌透明图标（含去底色边缘反混色）；4）放宽空心描边容器 `fill_ratio` 下限至 `0.012` 并限制 `layers.py` 的 `is_enclosed` 仅作用于图标级外框（`<= 320px`）；5）在 `text_style.py` 中增加 `estimate_text_runs`，基于单字核心笔画的色度与欧氏距离双门限自动切分同行多色 `TextRun`，并在 `clean_ocr_boxes` 中合并同行标点断句框、过滤微图标低置信伪字符。
- 适用范围：跨分辨率、跨设计风格的位图幻灯片通用多图层重建

## 2026-10-19 | NumPy 布尔掩码赋值覆盖导致卡片顶部彩色胶囊残留
- 现象：在 PowerPoint 中移开还原后的 4 个分区标题彩色胶囊（`ShapeElement`）时，底层背景图 `slide_000_bg.png` 上仍残留一条 `16px` 高的彩色胶囊顶部横条，以及底部横幅四角的橙色圆角残点。
- 原因：1）提取顶部胶囊后已将 `rem_sub[:cy1, cx0:cx1]` 置为 `False`，随后执行 `card_erase[card_top_offset:, :][perim_mask] = sub_mask[perim_mask]` 时，`perim_mask` 顶部 `16px` 带宽把原本在 `card_erase` 中标记为 `True` 的胶囊区域重新用 `False` 覆盖，导致胶囊顶部未被擦除；2）底部横幅内嵌图标保护区 `inner_zone[8:-8, 8:-8]` 水平边距过小，误把横幅四角的深色圆角描边当作内嵌图标保留。
- 解决：1）对大卡片边框与顶部胶囊分别独立擦除，胶囊上沿填充全局页面底色 `page_bg_rgb`、下沿填充卡片左肩采样得到的局部卡片内底色 `card_inner_rgb`；2）将横幅内嵌图标检测区水平内缩至 `inner_zone[8:-8, 25:-25]`，并在 E2E 测试中增加 `slide_000_bg.png` 四个胶囊区域色差方差 `< 3.0` 的防回归断言。
- 适用范围：复杂容器与附着标题胶囊的背景彻底抹平

## 2026-10-19 | 15x15 形态学膨胀导致相邻独立插图粘连合并
- 现象：在 `01-ai-beginner-workflow.jpg` 上分割独立插图时，人物与话筒、多份文档与箭头和文件夹、清单与循环图被合并成一张大图，无法在 PPTX 中对单个图标独立缩放或替换。
- 原因：使用 `15x15` 结构元膨胀会跨越相邻独立图标之间 `8~14px` 的留白间距，把整组配图桥接成单一连通域。
- 解决：改为 `3x3` 形态学闭运算桥接单笔触抗锯齿缝隙，随后仅按「外框包含关系（`inter / min_area >= 0.80`，如文档外框包含内部表格/饼图/核对项）」与「小尺寸紧凑多笔触图标（合并后尺寸 `<= 95x95px`）」聚合组件，并在导出每个图标的 RGBA 裁剪图时将其他独立图标掩码置为透明（`alpha = 0`）。
- 适用范围：位图多插图/多图标的独立个体分割

## 2026-10-19 | python-pptx 原生形状默认主题阴影与空心大卡片擦除伪影
- 现象：M3 将位图中的胶囊徽章、分区框与分隔线还原为原生 `ShapeElement` 后，PowerPoint 渲染图上所有徽章和线条下方都多出一圈深色模糊阴影；同时小框「一次只问一个问题」底图残留浅色色斑被误当成独立插图抠出，导致文字背后出现灰色噪点。
- 原因：1）`python-pptx` 的 `add_shape` 和 `add_connector` 默认写入 `<p:style><a:effectRef idx="2">`，PowerPoint 渲染时会自动附加主题投影；2）小尺寸描边子框若只擦除边框而不擦除内部浅色底，残留块会被 `layers.py` 当作低对比度前景再次抠图叠加。
- 解决：1）在 `pptx_writer.py` 的 `_disable_shadow` 中同时设置 `shape.shadow.inherit = False` 并将 `<p:style>` 下 `<a:effectRef>` 的 `idx` 置为 `"0"`；2）在 `shapes.py` 中对小尺寸描边子框采样内部填充色并完整擦除框体区域，同时在 `layers.py` 中要求独立插图连通域的 85 分位背景色差 `>= 45.0`。
- 适用范围：`python-pptx` 形状写入与位图多图层分割

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


