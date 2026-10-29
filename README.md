<div align="center">

# 🪄 ppt-kit

**把「图片版 PPT」一键还原为真正原生可编辑的 PPTX**  
*Convert flattened slide images, PDFs, and picture presentations into native, editable PPTX.*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![Managed by: uv](https://img.shields.io/badge/Managed%20by-uv-orange.svg)](https://github.com/astral-sh/uv)
[![Code style: ruff](https://img.shields.io/badge/Code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type checker: pyright](https://img.shields.io/badge/Type%20checker-pyright-green.svg)](https://github.com/microsoft/pyright)

[快速开始](#-快速开始) • [Web GUI 工作台](#-web-gui-工作台) • [CLI 使用说明](#-cli-命令行使用说明) • [核心特性](#-核心特性) • [质量度量报告](#-质量度量报告) • [路线图](#-路线图)

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

- 🖥️ **本地交互式 Web GUI 工作台（v0.3.0 新增）**：
  - 启动后自动弹出浏览器操作界面，支持拖拽批量上传图片 / PDF / PPTX；
  - 实时显示转换进度、每页还原元素树（文本框/形状/配图/表格）、原图与还原结果并排对比与一键下载；
  - 完全本地运行，内置静态资源，断网环境亦可流畅使用。
- ⚡️ **矢量 PDF 零误差极速直读（M4）**：
  - 针对 PowerPoint / Keynote / NotebookLM 导出的矢量 PDF，直接解析文字编码与排版坐标；
  - **字符准确率 100%**、字号误差 0.0pt、颜色误差 $\Delta E = 0.0$；
  - 自动合并同一形状的填充与描边，单页转换耗时仅 **0.4 秒**，无需外部 API 与 Token。
- 📦 **纯图片版 PPTX 智能无损解包**：
  - 直接支持将 `.pptx` 作为输入，自动利用 OpenXML 媒体库无损直取原始高清图像，毫秒级解构；
  - 同目录输出自带安全防覆写机制。
- 📊 **原生表格智能识别与逆向重建（Table IR）**：
  - 自动检测并提取规整表格结构，转为 PowerPoint 原生可编辑 Table 对象，保留单元格文字、行列跨度与对齐方式。
- 🎨 **AI 幻灯片位图多图层分离与背景修复（M2 & M3）**：
  - 自动将大卡片、分区框、标题胶囊徽章（如 `[✓ 必须有]` 等）、连接线还原为 PPT 原生 Shape；
  - 独立插图与 Logo 自动抠出为独立透明 PNG 浮层，支持在 PPT 中任意拖动缩放；
  - 文字与图元区域采用分级背景修复（纯色直填 + OpenCV 纹理补全），原位抹除无残影重叠。
- 📴 **100% 本地离线 & 跨平台隐私安全**：
  - 支持 macOS（Apple Vision）及 Windows / Linux（RapidOCR）多后端自动切换，计算全在本地完成，隐私零外泄。
- 📈 **度量驱动与质量报告**：
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
                             ┌─► 纯图片 (PNG / JPG / WebP) ──────► 走位图多图层路径 (本地 OCR + 形状分割 + 背景抹平)
                             │
用户输入 ────► pptkit 自动探测分流 ┼─► 纯图片版 PPTX ──────────────────► 走 OpenXML 媒体库无损直取 ──► 走位图多图层路径
                             │
                             └─► PDF ──┬─ 内部包含文字流/矢量路径 ──► 走矢量直接解析路径 (100% 字符无损，0.4s/页)
                                       └─ 扫描件/纯图片 PDF ────────► 自动降级走位图多图层路径
```

---

## 🚀 快速开始

### 方式一：下载独立免环境可执行包（免装 Python，解压即用）

直接前往 [GitHub Releases](https://github.com/monkeychen/ppt-kit/releases/latest) 下载对应系统架构的预编译安装包：

| 平台 | 下载包 | 说明 |
|---|---|---|
| 🍏 **macOS (Apple Silicon)** | [pptkit-macos-arm64.tar.gz](https://github.com/monkeychen/ppt-kit/releases/latest/download/pptkit-macos-arm64.tar.gz) | 解压后直接在终端执行 `./pptkit` |
| 🪟 **Windows (x86_64)** | [pptkit-windows-x86_64.zip](https://github.com/monkeychen/ppt-kit/releases/latest/download/pptkit-windows-x86_64.zip) | 解压后双击或 CMD/PowerShell 执行 `pptkit.exe` |
| 🐧 **Linux (x86_64)** | [pptkit-linux-x86_64.tar.gz](https://github.com/monkeychen/ppt-kit/releases/latest/download/pptkit-linux-x86_64.tar.gz) | 解压后 `./pptkit` 运行 |

### 方式二：通过 uv / pip 安装（开发者推荐）

```bash
# 推荐方式一：通过 GitHub 仓库直接一键全局安装
uv tool install git+https://github.com/monkeychen/ppt-kit.git

# 方式二：通过最新 Release Wheel 安装
uv tool install https://github.com/monkeychen/ppt-kit/releases/download/v0.3.0/pptkit-0.3.0-py3-none-any.whl
# 或标准 pip 安装
pip install pptkit
```

### 方式三：源码本地开发调试

```bash
git clone https://github.com/monkeychen/ppt-kit.git
cd ppt-kit
uv sync
```

---

## 🖥️ Web GUI 工作台（推荐图形化操作）

`ppt-kit` 内置开箱即用的轻量级交互式 Web 工作台，无需配置复杂参数，适合日常高频转换与结果审查。

```bash
# 启动本地 Web 工作台（自动在默认浏览器中打开）
pptkit gui

# 源码开发方式启动
uv run pptkit gui

# Windows 独立程序启动
.\pptkit.exe gui
```

> **Windows 一键双击运行**：在 `pptkit.exe` 同级目录下新建 `run-gui.bat`，写入 `pptkit.exe gui`，双击批处理文件即可直接启动。

### 工作台核心功能
- 📂 **拖拽即传**：直接将单张图片、批量幻灯片图片、PDF 文档或 `.pptx` 文件拖入页面。
- ⚡️ **实时流式进度**：多页文档逐页展示还原状态与耗时。
- 🔍 **图层树透视**：点击任意幻灯片查看提取出的文本框、背景层、几何形状与独立透明图片。
- ⚖️ **双栏对比与下载**：原图与还原结果并排对比，一键下载高保真 PPTX。

**常用参数**：
```bash
pptkit gui -p 9000            # 指定监听端口（默认 8765）
pptkit gui --no-browser       # 后台静默启动，不自动弹出浏览器
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

### 2. 启动 GUI 交互界面
```bash
pptkit gui                    # 启动 Web 工作台并自动打开浏览器
```

### 3. 高级参数
```bash
# 强制指定路由 (--route auto | vector | raster)
pptkit convert lecture.pdf -o out/ --route vector

# 指定 OCR 引擎 (--ocr-engine auto | apple_vision | rapidocr)
pptkit convert scan.pdf -o out/ --ocr-engine rapidocr

# 仅转换指定页码
pptkit convert sample.pdf -o out/ --pages 1-3,5

# Agent / 脚本调用模式（stdout 仅输出纯 JSON，进度转向 stderr）
pptkit convert sample.pdf -o out/ --json
```

### 4. 质量审查与筛选
```bash
# 筛选出 SSIM 相似度低于阈值或有降级图层的页面
pptkit report out/sample.report.json --needs-review --ssim-threshold 0.85
```

---

## 🛠️ 本地构建与打包（可选）

项目内置跨平台便捷打包脚本，支持一键构建独立可执行二进制或 Python Wheel：

```bash
# macOS / Linux 便捷脚本
./scripts/build.sh          # 默认：打包独立可执行单文件（内置 Web 前端静态资源）
./scripts/build.sh wheel    # 打包标准 Wheel 与源码包
./scripts/build.sh all      # 同时打包二进制与 Wheel
./scripts/build.sh --clean  # 打包前清理历史 dist/ 和 build/

# 跨平台通用执行命令（Windows / Linux / macOS）
uv run python scripts/build.py [binary|wheel|all]
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
- [x] **v0.2.0 (已发布)**
  - [x] 原生表格（Table IR）数据结构推断与行列边界提取
  - [x] PPTX 原生表格写入器与单元格边框对齐
- [x] **v0.3.0 (已发布)**
  - [x] 跨平台 OCR 适配器扩展（内置 RapidOCR ONNXRuntime，全平台即开即用）
  - [x] 交互式本地 Web GUI 工作台（拖拽上传、多页流式状态、双栏对比、图层透视）
  - [x] 跨平台单文件二进制发布（PyInstaller 静态资源捆绑，Windows / macOS / Linux 独立包）
- [ ] **v0.4.0 (规划中)**
  - [ ] 统计图表（Chart）结构推断与可编辑图表重建
  - [ ] 幻灯片公共母版（Slide Master）版式反推与主题色板提取
  - [ ] Raycast / Alfred 扩展集成与系统右键菜单快速转换

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
