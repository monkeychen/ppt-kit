<div align="center">

# 🪄 ppt-kit

**把「图片版 PPT」一键还原为真正原生可编辑的 PPTX**  
*Convert flattened slide images, PDFs, and picture presentations into native, editable PPTX.*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![Managed by: uv](https://img.shields.io/badge/Managed%20by-uv-orange.svg)](https://github.com/astral-sh/uv)
[![Code style: ruff](https://img.shields.io/badge/Code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type checker: pyright](https://img.shields.io/badge/Type%20checker-pyright-green.svg)](https://github.com/microsoft/pyright)

[快速开始](#-快速开始) • [核心特性](#-核心特性) • [输入流转架构](#-输入流转架构) • [质量度量报告](#-质量度量报告) • [路线图](#-路线图)

</div>

---

## 💡 为什么需要 ppt-kit？

在日常办公、知识沉淀和 AI 工作流中，我们经常遇到大量「不可编辑」的幻灯片：
- 🤖 **AI 生成的 PPT 图片**：Midjourney / DALL-E / 各类 AI PPT 工具生成的整张幻灯片位图；
- 📄 **只有导出的 PDF**：别人发来的方案、NotebookLM / Canva / Keynote 导出的讲义 PDF，源文件已遗失；
- 🖼️ **纯图片版 PPTX**：使用 PowerPoint「另存为图片演示文稿」导出的幻灯片，所有内容全被压平在一张图里。

**传统方案的痛点**：
- 找收费在线转换器？有数据泄露风险、格式排版错乱、字体被偷换；
- 转成图片重新 OCR？耗时几分钟，出现错别字、标点丢失，文字背后留下大片模糊残影。

**`ppt-kit` 的解法**：
通过统一中间表示（Slide IR）、多图层拆解算法以及矢量底层直读技术，**将不可编辑的图片或 PDF 原位逆向还原为包含原生文本框、原生几何形状（圆角框/胶囊/线条）和独立透明配图层的标准 PPTX 文档**。

---

## ✨ 核心特性

- ⚡️ **矢量 PDF 零误差极速直读（M4）**：
  - 针对 PowerPoint / Keynote / NotebookLM 导出的矢量 PDF，直接解析文字编码与排版坐标；
  - **字符准确率 100%**、字号误差 0.0pt、颜色误差 $\Delta E = 0.0$；
  - 自动合并同一形状的填充与描边，单页转换耗时仅 **0.4 秒**，无需外部 API 与 Token。
- 📦 **纯图片版 PPTX 智能无损解包**：
  - 直接支持将 `.pptx` 作为输入，自动利用 OpenXML 媒体库无损直取原始高清图像，毫秒级解构；
  - 同目录输出自带安全防覆写机制。
- 🎨 **AI 幻灯片位图多图层分离与背景修复（M2 & M3）**：
  - 自动将大卡片、分区框、标题胶囊徽章（如 `[✓ 必须有]` 等）、连接线还原为 PPT 原生 Shape；
  - 独立插图与 Logo 自动抠出为独立透明 PNG 浮层，支持在 PPT 中任意拖动缩放；
  - 文字与图元区域采用分级背景修复（纯色直填 + OpenCV 纹理补全），原位抹除无残影重叠。
- 📴 **100% 本地离线 & 隐私安全**：
  - 基于 macOS 原生 Apple Vision 驱动 OCR，所有计算均在本地完成，无需连网，不消耗 API Key。
- 📊 **度量驱动与质量报告**：
  - 每一次转换均可生成 JSON 质量报告，记录每页 SSIM 相似度、可编辑元素占比、低置信元素清单及耗时。

---

## 🏛️ 核心设计原则

1. **能读就不识别**：输入里有矢量信息（PDF 文字/路径）时，直接解析，绝不走 OCR/VLM。识别只用于位图。
2. **单一中间表示（Slide IR）**：所有输入源先统一转换为严密的 `SlideIR` 数据模型，PPTX 生成器只认 IR。
3. **质量靠度量，不靠肉眼**：每次转换都由原生渲染器输出像素级质量报告（SSIM、元素召回率、MAE），量化衡量还原保真度。
4. **宁可退化，不可错乱**：无法百分之百保证位置和内容的可疑复杂图元，安全降级为高清图片层，保留原始视觉，绝不生成错乱的可编辑对象。

---

## 📐 输入流转架构

```
                             ┌─► 纯图片 (PNG / JPG / WebP) ──────► 走位图多图层路径 (Apple Vision OCR + 形状分割 + 背景抹平)
                             │
用户输入 ────► pptkit 自动探测分流 ┼─► 纯图片版 PPTX ──────────────────► 走 OpenXML 媒体库无损直取 ──► 走位图多图层路径
                             │
                             └─► PDF ──┬─ 内部包含文字流/矢量路径 ──► 走矢量直接解析路径 (100% 字符无损，0.4s/页)
                                       └─ 扫描件/纯图片 PDF ────────► 自动降级走位图多图层路径
```

---

## 🚀 快速开始

### 运行环境
- **操作系统**：macOS 13+（当前位图 OCR 依赖 macOS Apple Vision 框架）
- **Python 版本**：Python 3.11+
- **包管理器**：推荐使用 [uv](https://github.com/astral-sh/uv)

### 安装

```bash
# 1. 克隆仓库
git clone https://github.com/monkeychen/ppt-kit.git
cd ppt-kit

# 2. 安装项目依赖
uv sync

# 3. （推荐）全局安装为独立命令行工具
uv tool install .
```

---

## 💻 CLI 命令行使用说明

### 1. 基础转换
```bash
# 转换矢量 PDF（秒级还原，100% 文字保真）
pptkit convert sample.pdf -o out/

# 转换纯图片版 PPTX
pptkit convert image_slides.pptx -o out/

# 转换单张或批量图片
pptkit convert slide_01.png -o out/
pptkit convert ./slides_dir/ -o out/
```

### 2. 高级参数
```bash
# 强制指定路由 (--route auto | vector | raster)
pptkit convert lecture.pdf -o out/ --route vector

# 仅转换指定页码
pptkit convert sample.pdf -o out/ --pages 1-3,5

# Agent / 脚本调用模式（stdout 仅输出纯 JSON，进度转向 stderr）
pptkit convert sample.pdf -o out/ --json
```

### 3. 质量审查与筛选
```bash
# 筛选出 SSIM 相似度低于阈值或有降级图层的页面
pptkit report out/sample.report.json --needs-review --ssim-threshold 0.85
```

---

## 📋 质量度量报告示例

转换完成后，会在输出目录自动生成 `<name>.report.json`：

```json
{
  "source": "sample.pptx",
  "output_pptx": "out/sample.converted.pptx",
  "total_pages": 6,
  "succeeded_pages": 6,
  "failed_pages": 0,
  "pages": [
    {
      "page_index": 0,
      "route": "raster",
      "status": "ok",
      "ssim": 0.8606,
      "editable_elements": 46,
      "degraded_elements": 0,
      "low_confidence_elements": [],
      "missing_fonts": [],
      "elapsed_sec": 8.38,
      "model_calls": 0
    }
  ]
}
```

---

## 🗺️ 路线图 (Roadmap)

- [x] **v0.1.0 (已发布)**
  - [x] Slide IR 中间表示与高保真 PPTX 写入器
  - [x] 矢量 PDF 文本流直接解析与几何路径合并（M4）
  - [x] 纯图片版 PPTX 媒体库直取与安全防覆写
  - [x] 位图文字样式估算与 Apple Vision 本地离线 OCR（M2）
  - [x] 位图容器、圆角矩形、胶囊徽章与独立插图多图层分离（M3）
  - [x] 自动化 SSIM 渲染比对与质量报告系统
- [ ] **v0.2.0 (规划中)**
  - [ ] 原生表格（Table）与统计图表（Chart）结构推断与逆向重建
  - [ ] 跨平台 OCR 适配器扩展（PaddleOCR / RapidOCR），支持 Windows 与 Linux
  - [ ] 幻灯片公共母版（Slide Master）与版式反推
  - [ ] GUI 桌面客户端或 Raycast / Alfred 扩展集成

---

## 🤝 参与贡献

欢迎提交 Issue 和 Pull Request！开发与调试流程请参考 [CONTRIBUTING.md](CONTRIBUTING.md)。

```bash
# 运行单元测试
uv run pytest tests/unit

# 运行代码规范检查与格式化
uv run ruff check . && uv run ruff format --check .

# 运行静态类型检查
uv run pyright
```

---

## 📄 开源许可证

本项目基于 [MIT 许可证](LICENSE) 开源。
