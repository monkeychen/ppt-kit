---
doc: release
version: v0.1.0
date: 2026-10-21
status: approved
---

# Release v0.1.0 — 幻灯片逆向重构引擎首次正式发布

## 1. 版本内容摘要

ppt-kit v0.1.0 实现了将「图片版 PPT」（AI 生成图片、图片版 PPTX、导出的 PDF）还原为完全原生可编辑 PPTX 的完整能力。核心支持 Apple Vision 本地离线 OCR、背景分级原位修复、多图层矢量几何与独立插图分割，以及矢量 PDF 的 100% 字符级无损直接解析与毫秒级极速转换。全流程依托度量驱动与「能读就不识别、宁可退化不可错乱」原则，提供开箱即用的 Typer CLI 与详尽的质量度量报告。

---

## 2. 变更记录（User-Facing Changes）

### Added
- **矢量 PDF 直接解析路径（F6）**：
  - 针对 PowerPoint、Keynote、NotebookLM 等导出的矢量 PDF，直接解析文字编码与排版坐标，字符准确率达 100%、字号误差 0.0pt、颜色色差 $\Delta E = 0.0$。
  - 自动识别并合并同一形状的 Fill 与 Stroke 绘图，单页转换耗时仅 0.42 秒，零 API Token 消耗。
  - 复杂半透明路径与渐变自动安全降级为高清图片层，杜绝视觉错乱。
- **纯图片版 PPTX 直接转换支持**：
  - 支持直接将压平为纯图片的 `.pptx` 作为输入，自动利用 OpenXML 媒体库无损直取原始位图，并自动分流至多图层逆向引擎。
  - 智能安全保护：同名同目录转换自动命名为 `<stem>.converted.pptx`，防止覆写源文件。
- **AI 幻灯片位图多图层分层与背景原位修复（F7, F8）**：
  - 原生支持将位图中的大卡片边框、分区背景框、胶囊徽章（`[✓ 必须有]` 等）、连接线自动提取为 PowerPoint 原生 Shape。
  - 独立插图与 Logo 自动抠出为独立透明 PNG 浮层，支持在 PPT 中随意拖拽、替换、缩放。
  - 原文字与已提取图元区域自动平滑原位擦除并修复纸张纹理，背景层无残影、无重影。
  - 离线 OCR：macOS 原生 Apple Vision 驱动，开箱即用，无需配置 API Key。
- **自动化视觉度量与质量报告（F4, F10）**：
  - 转换后自动输出 `<name>.report.json`，提供每页 SSIM 相似度、可编辑元素数、低置信元素清单及耗时。
  - 自动集成 PowerPoint（经 AppleScript 沙盒）及 LibreOffice 无头渲染器闭环度量。
- **CLI 命令行工具（F9）**：
  - `pptkit convert <file|dir> -o <outdir>` 支持单文件与批量目录处理。
  - 支持 `--route auto|vector|raster` 指定或自动识别处理链路。
  - 支持 `--json` 纯 JSON 输出，专为 Agent 自动化集成设计。

### Changed
- **自适应路由分流**：根据输入文件（PDF 内部是否有文本流、PPTX 内部形状结构、位图格式）全自动选择最快、最保真的处理路径。

### Fixed
- **字体切换处空格缺失**：修复 Office 导出 PDF 时中西文切换仅有坐标偏移无空格字符的问题，自动按相对字号距离补全空格。
- **PowerPoint 原生形状黑圈阴影**：修复 `python-pptx` 默认附带主题阴影导致胶囊徽章带模糊黑圈的问题。
- **细描边大卡片误判**：修复由于大尺寸外框周长面积比较低导致卡片容器漏检的问题。

### Removed
- 无。

---

## 3. 交付物清单与获取方式

### 3.1 运行依赖
- macOS 13+（Apple Vision OCR 本地驱动）
- Python 3.12+，包管理器推荐使用 `uv`
- （可选）Microsoft PowerPoint for Mac 或 LibreOffice（用于输出质量对比度量）

### 3.2 安装与运行
```bash
# 1. 克隆代码并安装依赖
git clone <repo_url> ppt-kit
cd ppt-kit
uv sync

# 2. 转换任何图片、PPTX 或 PDF
uv run pptkit convert /path/to/slide.pdf -o out/
uv run pptkit convert /path/to/image.png -o out/
uv run pptkit convert /path/to/image_presentation.pptx -o out/

# 3. 质量报告查看
cat out/slide.report.json
```

---

## 4. 验收汇总

| 里程碑 | 核心目标 | 验收结果 | 自动化证据 |
|---|---|---|---|
| **M1 地基** | Slide IR、PPTX 生成、PowerPoint 渲染与合成基准 | **通过** | 标准答案 IR $\rightarrow$ PPTX $\rightarrow$ 渲染全链路闭环跑通 |
| **M2 位图文字** | Apple Vision OCR、分级背景修复、文字样式估计与报告 | **通过** | 真实样片 `01-ai-beginner-workflow` 字符准确率 98.6%，文字区域底图 100% 抹平 |
| **M3 位图分层** | 形状/卡片/胶囊原生还原、独立插图分割抠取 | **通过** | 真实幻灯片拆解出 280+ 个原生可编辑元素，容器与配图无重叠残留 |
| **M4 矢量路径** | 矢量 PDF 文本流直接解析、几何路径提取与合并 | **通过** | 字符准确率 100%，字号误差 0.0pt，色差 0.0，单页耗时 0.42s，SSIM 0.918 |

- **全量自动化测试通过率**：
  - 单元测试：`32 / 32 PASSED`（100%）
  - 端到端测试：`4 / 4 PASSED`（100%）
  - 集成基准测试：`1 / 1 PASSED`（100%）
  - 代码规范与类型检查：`pyright` 0 error / 0 warning，`ruff` 100% clean。

---

## 5. 已知问题与下版建议 Backlog（v0.2.0）

1. **表格与图表原生识别**：当前版本的复杂表格和统计图表会被解析为矢量线条或独立插图层，v0.2.0 计划通过结构推断逆向还原为 PowerPoint 原生 Table 和 Chart 对象；
2. **多语言扩展与跨平台**：当前 OCR 绑定 macOS Apple Vision，后续版本将抽象接入 PaddleOCR / EasyOCR 适配 Linux 与 Windows；
3. **母版（Slide Master）反推**：对多页风格一致的演示文稿，自动提取公共背景、版式母版和页码占位符。
