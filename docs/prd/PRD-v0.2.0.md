---
doc: prd
product: v0.2.0
date: 2026-10-26
status: approved
---

# PRD v0.2.0 — 跨平台离线 OCR 适配与原生表格逆向重构

## 1. 版本背景与目标

### 1.1 为什么做
在 v0.1.0 中，`ppt-kit` 成功建立了核心地基：支持 Slide IR、原生 PPTX 生成、纯图片版 PPTX 解构、矢量 PDF 100% 字符级无损解析（M4）以及 AI 幻灯片多图层拆解（M2/M3）。
然而在现实生产环境与跨平台分发中，有两个阻碍用户广泛使用的核心痛点：
1. **位图 OCR 平台绑定**：v0.1.0 的位图 OCR 依赖 macOS 原生 Apple Vision 框架。虽然在 Windows 和 Linux 上已能正常解析矢量 PDF，但位图幻灯片（PNG/JPG/图片PPTX）在非 Mac 系统上无法运行离线 OCR；
2. **表格被瓦解为碎片对象**：在企业报告、教学课件、产品分析等幻灯片中，表格（Table）占据极高比例。v0.1.0 将表格拆散为孤立的文本框与描边线条，用户在 PowerPoint 中无法直接调整列宽、增删行列或编辑单元格，二次编辑体验破碎。

### 1.2 解决什么
1. **双引擎自适应 OCR（macOS 保持原生，非 Mac 引入轻量 ONNX）**：
   - macOS 继续使用原生的零体积、硬件加速 Apple Vision；
   - Windows / Linux 自动平滑回退至轻量级跨平台引擎（RapidOCR ONNX，模型仅约 15MB），实现**全平台 100% 离线、零外部配置可用**；
2. **原生表格（Table）结构逆向推断与可编辑还原**：
   - 基于网格线拓扑交叉与文本拓扑行列对齐算法，推断表格的行列结构与跨行跨列；
   - 在 PowerPoint 中生成真正的原生 `Table` 形状，用户可自由增删行列、调整列宽、修改单元格样式；
   - 原表格区域背景原位抹平，杜绝黑线重影。

### 1.3 交付形态
- Typer CLI 工具升级（增加 `--ocr-engine auto|apple_vision|rapidocr` 参数）；
- GitHub Actions 全平台 Release 自动打包包含跨平台 OCR 权重的独立免环境安装包；
- 扩展 Slide IR 模型（`TableElement` 与 `TableCell`）；
- 详尽的表格还原质量报告指标。

---

## 2. 用户故事与覆盖场景

### US1：Windows / Linux 用户的全功能离线使用
- **输入**：Windows 或 Linux 环境下的图片版 PPTX、位图幻灯片或扫描版 PDF。
- **期望行为**：执行 `pptkit convert <input> -o out/`，无需配置任何 API Key 或复杂 C++ 环境，系统自动调用内置轻量 RapidOCR 引擎完成文字识别与图层拆解，正常输出可编辑 PPTX。
- **成功标准**：在 GitHub Actions 的 Windows 和 Linux 虚拟机中，端到端测试 100% 通过，字符准确率 $\ge 98.0\%$。

### US2：macOS 用户的无感延续与顶级体验
- **输入**：macOS 上的任意位图或图片版 PPTX。
- **期望行为**：默认自动命中 Apple Vision，零模型体积、利用 Neural Engine 硬件加速，依然保持毫秒级响应与顶级中西文混排识别率。
- **成功标准**：macOS 默认不下载、不加载外部 ONNX 模型，内存与耗时与 v0.1.0 保持一致。

### US3：含有表格的幻灯片还原为原生可编辑表格
- **输入**：含有 2x2 到 10x8 结构表格的图片、PPTX 或矢量 PDF 页面。
- **期望行为**：转换后在 PowerPoint 中，表格不再是一堆散装矩形和漂浮文本框，而是单一的 PowerPoint 原生表格形状，用户可以直接点击任意单元格打字、拖动调整列宽、右键“插入行/列”。
- **成功标准**：表格单元格内容召回率 $\ge 95\%$，行列维度推断正确率 $\ge 95\%$，在合成表格基准上视觉 SSIM $\ge 0.90$。

---

## 3. 功能清单与验收标准

### F11 跨平台位图 OCR 适配器与自动分流
- **AC11.1**：架构抽象解耦：在 `pptkit/adapters/ocr.py` 中规范统一抽象基类 `BaseOCRAdapter`，标准化输出数据结构 `OCRResult`（文本内容、置信度、绝对坐标包围盒）。
- **AC11.2**：macOS 原生适配器：保留原有 `AppleVisionOCRAdapter`，在 `sys.platform == "darwin"` 时默认使用，0 额外下载、0 外部依赖。
- **AC11.3**：跨平台 ONNX 适配器：实现 `RapidOCRAdapter`，基于 `rapidocr-onnxruntime`，内置精简模型，在 Windows 和 Linux 时默认使用；macOS 下也可通过参数选择。
- **AC11.4**：自适应路由与覆盖：默认走 `auto`（根据平台自动切换），支持 CLI 参数 `--ocr-engine auto|apple_vision|rapidocr`。若在非 macOS 上显式指定 `apple_vision` 则友好报错退出（Exit code 1），提示该平台仅支持 `rapidocr`。
- **AC11.5**：CI 全平台验证：在 GitHub Actions 的 `ubuntu-latest` 和 `windows-latest` 虚拟机中，自动化运行单元与端到端测试，通过率 100%。

### F12 原生表格（Table）结构推断与 PPTX 还原
- **AC12.1**：Slide IR 扩展：在 `pptkit/ir/models.py` 中新增 `TableCell` 与 `TableElement` 模型（包含 rows, cols, cell bbox, text paragraphs, fill_color, border_styles）。
- **AC12.2**：表格几何区域与网格线检测：
  - 矢量路径（PDF）：根据交错相交的横竖线段 (`DrawingPath`) 闭包聚合网格拓扑；
  - 位图路径（Raster）：基于水平/垂直形态学核扫描（Morphology Kernels）检测连续网格线，或基于多行多列文本框在空间上的拓扑行列对齐关系（无框线表格）。
- **AC12.3**：单元格文本分配与合并：
  - 将文字准确映射到对应的 `(row, col)` 单元格，多行文字作为单个单元格内的多个段落；
  - 支持跨列合并（Colspan）或跨行合并（Rowspan）的基础检测（单元格跨越网格线）。
- **AC12.4**：原生 PPTX 表格写入（`pptx_writer.py`）：
  - 调用 `python-pptx` 的 `slide.shapes.add_table(rows, cols, left, top, width, height)` 生成真正的原生表格；
  - 写入每个单元格的背景色、边框粗细与颜色、文字样式（字体、字号、加粗、文字颜色、对齐方式）。
- **AC12.5**：表格底图原位抹除（Inpainting）：
  - 识别出表格区域后，底图上的原表格内容（包含边框、文字、单元格背景）从幻灯片背景层中干净擦除并平滑修复，防止在 PPT 中拖动表格时底部出现黑线重影。
- **AC12.6**：表格质量评估度量：
  - 在基准集测试中，表格行列数识别正确率 $\ge 95\%$，单元格文字字符准确率 $\ge 98\%$。

### F13 质量报告与 CLI 扩展
- **AC13.1**：`report.json` 中记录表格识别信息：`tables_count`, `table_cells_count`，若存在结构置信度不足的复杂表格，安全降级为 `ImageElement(degraded=True)` 并计入报告。
- **AC13.2**：CLI `pptkit convert` 增加 `--ocr-engine` 参数，进度输出中显示当前使用的 OCR 引擎名称。

---

## 4. 里程碑划分

| 里程碑 | 目标 | 覆盖 F/AC | 前端 UI | 外部系统 / 接口 |
|---|---|---|---|---|
| **M1 跨平台 OCR 闭环** | 抽象 `BaseOCRAdapter`，接入 `RapidOCRAdapter`，实现双引擎自动路由与 CLI 切换，在 Linux 和 Windows CI 上跑通全量测试 | F11 全部 AC, AC13.2 | 否 | `rapidocr-onnxruntime`、GitHub Actions 多平台 CI |
| **M2 表格 IR 模型与 PPTX 生成闭环** | 扩展 `TableElement` IR 模型，在 `pptx_writer.py` 中实现原生 Table 生成，跑通“标准答案 Table IR $\rightarrow$ PPTX 表格 $\rightarrow$ 渲染对比”合成基准闭环 | AC12.1, AC12.4 | 否 | PowerPoint / LibreOffice 表格渲染 |
| **M3 表格逆向推断与背景修复** | 实现网格线拓扑分析与文字行列聚类分配算法，完成底图表格擦除与真实表格样片端到端验证 | AC12.2, AC12.3, AC12.5, AC12.6, AC13.1 | 否 | 真实表格幻灯片样本 |

**为什么这么排**：
- M1 先解决跨平台基础设施，让 Windows 和 Linux 拥有完整的位图处理能力，消除多平台差异；
- M2 先遵循“打分尺先行”原则，在中间表示（IR）和 PPTX 生成端把原生表格的生成能力与基准度量先跑通；
- M3 最后集中攻克最复杂的逆向推断算法（网格拓扑、单元格分配与背景擦除），依托 M2 的打分尺持续优化。

---

## 5. 非目标（v0.2.0 不做）

- 3D 立体图表与动态数据透视表（留待 v0.3.0）
- 极度扭曲、手绘草图风格的不规则自由手绘网格
- GUI 桌面客户端界面（留待 v0.3.0）
- 多人实时在线协同（云端 SaaS）

---

## 6. 决策记录

| 编号 | 问题 | 结论 | 理由与影响 |
|---|---|---|---|
| **D4** | 跨平台位图 OCR 选型与路由策略 | **macOS 默认 Apple Vision；Windows / Linux 默认 RapidOCR (ONNX)** | Apple Vision 在 macOS 上零体积、硬件加速、中英文断句极准；RapidOCR 纯 CPU 即可跑且模型仅 15MB，打包成 Windows exe 与 Linux 二进制最轻量、最稳定，无 DLL 缺失风险。 |
| **D5** | 表格还原策略 | **原生 Table 优先，结构破碎时安全降级** | 遵循“宁可退化，不可错乱”原则：只要行列网格拓扑置信度 $\ge 85\%$，还原为 PowerPoint 原生 `Table`；对于结构破碎严重的复杂嵌套图表，降级为独立图片层，杜绝错乱表格。 |
