# vibe-coding 踩坑记录

> 倒序追加，新的在上。格式见 ~/.gemini/dev-workflow.md。

## 2026-10-29 | 空间拓扑逆向与架构守卫：全局单位魔法数字防御、宽卡片几何防误判与单字噪点抑制
- 现象：1）开发 M1 底层清洗与卡片语义流式成组时，全量单元测试 `test_no_unit_constants_outside_units_module` 失败：`raster/pipeline.py contains 12700`；2）多边形轮廓在边缘带局部端点突起时，长条形矩形卡片被几何分类器误分类为 `right_arrow`；3）图标内残影单字（如 `¢`, `口`）被 OCR 误生成浮动文本框。
- 原因：1）为计算段后距临时使用了 `gap_emu / 12700.0`，违背了项目 GEMINI.md 中「单位换算函数唯一收敛于 `pptkit/common/units.py`」的核心原则；2）简化箭头分类器只检测局部峰值，未针对高填充率（`fill_ratio > 0.80`）的大矩形卡片设置互斥防御；3）高对比度矢量图标局部特征与文字笔画在局部卷积感受野中呈现相似特征。
- 解决：1）必须统一从 `pptkit.common.units` 导入 `emu_to_pt` 进行换算，严禁任何业务代码硬编码 `12700` 或 `914400`；2）在 `_is_right_arrow` 和 `classify_contour_shape` 中建立严格长宽比与填充率防误判门限（`aspect_ratio >= 1.8` 且 `fill_ratio >= 0.80` 坚决排除箭头）；3）在 `suppress_icon_pseudo_characters` 中对与图标区域重叠且字符长度为 1 的噪点进行彻底剥离，同时保护 `>= 22pt` 的合法标号。
- 适用范围：多图层几何分类、OCR 噪点过滤及全局单位规约守护。


## 2026-10-27 | 跨平台 CI 回归：Windows Sockets 端口复用差异、Typer/Rich 终端 ANSI 序列与弱算力 Runner 超时
- 现象：v0.3.0 在 GitHub Actions 多系统矩阵 CI 运行时，三端均出现失败：1）Windows 上 `test_find_available_port_increments_when_busy` 与 `test_find_available_port_exhaustion_raises` 失败，端口已被占用却能重复 bind；2）三平台上 `test_cli_gui_help` 断言 `assert "--port" in result.output` 失败；3）macOS CI 虚拟化节点上 `test_task_runner_dispatches_events` 超时，`task.status == "running"` 未达到 `"completed"`。
- 原因：1）Winsock 对 `SO_REUSEADDR` 的语义与 POSIX 截然相反，在 Windows 上显式设置 `SO_REUSEADDR` 允许其它套接字强制复用已被监听的端口，必须使用 Windows 专属的 `SO_EXCLUSIVEADDRUSE`；2）Rich 终端着色器在 CI 环境下将 `--` 与 `port` 切开并插入 ANSI 颜色转义序列（`\x1b[1m--\x1b[0m\x1b[36mport\x1b[0m`），导致单纯的连续子串匹配失效；3）GitHub Actions 的 macOS 虚拟机 CPU 算力受限且队列拥堵，冷启动多图层 OCR 推理超过了原本写死的 15.0 秒超时门限。
- 解决：1）在 `find_available_port` 及对应单元测试中，区分系统平台：非 Windows 平台使用 `SO_REUSEADDR`，Windows 平台使用 `SO_EXCLUSIVEADDRUSE` 杜绝端口盗用；2）CLI Help 测试增加 `color=False` 并通过正则彻底滤除 ANSI 序列；3）将 CI 异步任务的等待上限 `timeout` 由 15.0s 放宽至 60.0s（任务完成立即 return，不增加正常耗时）。
- 适用范围：多操作系统 CI 矩阵（Linux/macOS/Windows）、网络端口分配及终端 CLI 文本断言。

## 2026-10-26 | 跨平台单元测试：非 macOS 运行环境无 CJK 字体、几何色块误报为口字与复检清洗闭环
- 现象：v0.2.0 CI 在 `ubuntu-latest` 和 `windows-latest` 运行时，3 个单元测试用例失败：1）`test_inpaint.py` 中直接硬编码了 `AppleVisionOCRAdapter`；2）`test_text_style.py` 硬编码了 macOS 独有的 `/System/Library/Fonts/STHeiti Medium.ttc` 路径，CI 容器回退到默认点阵字体后无法渲染中文字符，导致颜色提取算法只采样到背景底色；3）背景抹除复检中，纯色非文字几何色块被 RapidOCR 误报为 `"口"` 字。
- 原因：1）早期测试用例编写在跨平台抽象前，遗留了单一平台实现直接绑定；2）云端精简 Linux/Windows CI runner 未预装 CJK 矢量字体，FreeType 无法绘制中文字形；3）高对比度矩形几何块容易在通用 OCR 检测模型中产生类似于方形单字符（如 `"口"`, `"□"`）的假阳性，且复检未启用 pipeline 标准清洗规则。
- 解决：1）测试用例统一通过 `get_ocr_adapter("auto")` 获取适配器；2）单元测试中采用标准 FreeType/默认字号与 Latin 字符生成文字样本，摆脱对宿主操作系统 CJK 字体文件的物理依赖；3）在 `clean_ocr_boxes` 中增加对单字符 `"口"`、`"〇"` 以及大尺寸方形单字符（`min(w, h) >= 60`）的几何滤除，并在 `verify_background_cleanliness` 中应用 `clean=True`。
- 适用范围：跨操作系统自动化测试、高对比度图标/容器与 OCR 文本框防误检。

## 2026-10-26 | 位图表格逆向还原：边缘梯度分离实心表头与细网格线、防文本双重重叠与底图彻底擦除
- 现象：1）若直接用前景颜色差二值化进行网格线开运算，带有纯色填充的表头矩形内部会被误检为密集的假垂直线，导致列拓扑坍缩；2）表格提取后，若未在顶层流程中过滤已分配给表格单元格的 OCR 文本框，会在生成的 PPTX 中表格上方飘浮一层完全重复的孤立文本框；3）底图未抹平表格线时，PPTX 原生表格透过微小边距缝隙会露出底层原本的位图重影。
- 原因：1）实心色块在 2D 空间上长宽皆大，一维开运算核在进入色块内部时同样满足长度约束；2）表格和常规幻灯片文本在 IR 中原本属于平级元素，缺少消耗追踪闭环；3）PPT 表格边框与底图位图对齐存在亚像素渲染差异。
- 解决：1）改为使用边缘梯度（`grad_x = np.abs(gray[:, 1:] - gray[:, :-1]) > 18`）进行垂直/水平线开运算，纯色表头内部梯度为 0，只有真正的细网格线和外轮廓产生响应；2）建立 `used_box_indices` 追踪机制，在构建幻灯片顶层 `TextBoxElement` 时严格跳过表格单元格已消耗的 OCR 索引；3）在提取出表格后，将背景图中整个表格连通区域用周边外围环境背景色平滑擦除抹平。
- 适用范围：位图幻灯片中原生可编辑表格的高精度提取与图层防重叠。


## 2026-10-26 | 原生表格 PPTX 生成：单元格默认内边距清零、DrawingML 边框底层注入与全局单位规约
- 现象：1）使用 python-pptx 生成原生 Table 时，单元格默认带有左右各 0.1 inch（~14.4pt）的内边距，导致原本刚好单行的文本在表格中被挤压换行，行高剧增；2）python-pptx 未暴露单元格边框（Border）高层 API，若通过叠放原生 Line 模拟边框，用户拖拽表格时边框滞留在原地；3）单元测试 `test_units.py` 严格防御 `units.py` 之外出现 `12700` 或 `914400` 等单位换算魔法数字。
- 原因：1）PowerPoint OpenXML 规范中表格单元格的默认边距为预设值（非 0）；2）DrawingML 将边框存储在 `tcPr` 的 `<a:lnL>` / `<a:lnR>` / `<a:lnT>` / `<a:lnB>` 命名空间子节点中；3）项目架构规约要求单位换算必须在 `pptkit/common/units.py` 统一收敛。
- 解决：1）在 `_add_table` 中对每个单元格主动应用 `cell.margin_left = 0` 等边距收敛策略；2）底层直接操作 `cell._tc.get_or_add_tcPr()`，为单元格注入原生矢量边框并绑定 `solidFill` 颜色与线宽；3）统一从 `pptkit.common.units` 导入 `EMU_PER_PT`，杜绝代码内硬编码。
- 适用范围：PPTX 原生表格写入与高保真单元格排版。


## 2026-10-26 | 跨平台 OCR 适配：惰性加载避免 CLI 延迟、平台能力平滑降级与合成文字断词容差
- 现象：1）引入 RapidOCR ONNX 引擎后，若在模块导入阶段初始化引擎，会导致 `pptkit --help` 和纯矢量 PDF 解析变慢数百毫秒；2）非 macOS CI 跑单元测试时，Apple Vision 测试会因为找不到 `swiftc` 或 macOS 系统框架直接报错；3）测试中 PIL 默认点阵字体在极小字号下渲染时，RapidOCR 会将相邻英文单词拆散（如 `'He llo RapidOC R 2026'`），硬编码精确字符串相等会导致脆弱失败。
- 原因：1）ONNX Session 创建及预加载检测与识别权重需加载约 15MB 模型文件与构建推理图；2）Apple Vision 依赖 macOS 原生 Swift/Vision 框架；3）小字号点阵位图字符间距不均，OCR 文本行聚合算子易受局部空白干扰。
- 解决：1）在 `RapidOCRAdapter` 内采用惰性加载机制（首次调用 `recognize` 时才初始化 ONNX Session）；2）抽象 `BaseOCRAdapter` 协议，工厂函数 `get_ocr_adapter` 依据平台自动调度（macOS 优先 Apple Vision，Linux/Windows 使用 RapidOCR），非 macOS 平台对 Apple Vision 单元测试增加 `@pytest.mark.skipif(sys.platform != "darwin")` 并独立拆分清洗规则断言；3）单元测试断言采用核心 token 集合包含校验。
- 适用范围：跨平台 OCR 适配与多环境调度。


## 2026-10-20 | 矢量 PDF 直接解析：零尺寸直线判定、双层通栏背景识别与跨字体坐标空隙回补
- 现象：在开发 M4 矢量 PDF 直接解析与合成基准集测试中遇到三处精度与还原陷阱：1）基准测试中分隔线 `line` 形状召回率为 0；2）PowerPoint 导出的浅色背景矢量 PDF 中，背景色块被识别为普通前景 `ShapeElement` 压在所有文字下方；3）"原生渲染器 SSIM" 提取出的文本缺少空格变为 "原生渲染器SSIM"，导致字符准确率从 100% 降至 97.4%。
- 原因：1）PDF 规范中纯水平或纯垂直直线的 `fitz.Rect` 高度或宽度为 0，若噪点过滤用 `rect.width <= 0.5 or rect.height <= 0.5` 会无差别抹杀直线；2）Office 导出 PDF 时常生成 Drawing 0（纯白纸张画布）和 Drawing 1（幻灯片实际主题底色，如 `#F8FAFC`），若仅将 `idx == 0` 当作背景，第二个全页色块会成为前景矩形；3）Office 矢量 PDF 导出引擎在字体切换（中文 `PingFang SC` 到西文 `Arial`）时，不输出 ASCII 空格字符 `\x20`，而是直接在坐标上产生 `~5pt` 的水平偏移来表现排版间隔。
- 解决：1）将直线类型与封闭矩形区分过滤，直线仅在 `max(rect.width, rect.height) <= 0.5` 时过滤，并在 PPTX writer 中以 `add_connector(MSO_CONNECTOR.STRAIGHT)` 精准还原端点坐标；2）在 `drawings.py` 中将前置连续全画幅矩形（`idx <= 1` 且覆盖率 `>= 99.8%`）识别为幻灯片背景层；3）在 `text.py` 中根据相邻 span 的水平距离检测 `gap >= 0.20 * font_size` 自动补回空格，使字符识别率达到 100%，字号平均绝对误差降至 0.0pt。
- 适用范围：矢量 PDF（PowerPoint/Keynote/Acrobat/NotebookLM 等工具直接导出的 PDF）直接解析为高保真可编辑 PPTX。

## 2026-10-19 | 纯图片版 PPTX 输入支持：内存级图片无损直取与无头渲染兜底的两级适配
- 现象：用户提出现实场景——手头已有整套「图片版 PPTX」（由 Canva/Gamma 导出，或通过 PowerPoint「另存为图片演示文稿」生成，幻灯片内容全被压平为图片），希望直接转为可编辑 PPTX。若直接走现有 Office/LibreOffice 渲染导出 PDF 再转 PNG，存在两大弊端：1）多页 PPTX 需要逐页启动外部进程渲染，耗时数秒到数十秒且有窗口弹窗闪烁；2）PowerPoint 导出 PDF 默认带有二次重采样和下采样（downsample），导致原始高清位图边缘模糊，降低 OCR 和几何形状检测精度。
- 原因：PPTX 文件本身即 OpenXML zip 包，纯图片版 PPTX 的原始高清图像以原始格式（PNG/JPEG/WebP）直接存储在 `.pptx` 内部媒体库中；仅在多图拼贴或背景填充等非标准单图场景下才需要视觉渲染。
- 解决：在 `pptkit/ingest/loader.py` 中增加两级提取机制：1）主路径（内存级无损直取）：用 `python-pptx` 遍历幻灯片，若幻灯片为单张无文字全幅 Picture 形状（或无形状且背景为单图），直接读取 `shape.image.blob`，毫秒级提取 100% 原始分辨率位图，零系统依赖；2）兜底路径（无头渲染）：若存在复杂多图拼合、形状混排，自动调用现有的 `render_pptx` 渲染出每页视口 PNG；3）在 CLI 中增加输出安全检查：当输入与输出在同一目录且扩展名相同时，输出自动重命名为 `<stem>.converted.pptx`，防止覆写输入原文件。
- 适用范围：支持 `.pptx` 作为输入直接还原为可编辑 `.pptx`。

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


