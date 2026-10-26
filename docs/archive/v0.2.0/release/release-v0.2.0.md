---
doc: release
product: v0.2.0
milestone: -
date: 2026-10-26
status: approved
---

# Release Note：pptkit v0.2.0

> pptkit v0.2.0 是一个重大架构与特性升级版本。
> 本版本实现了全平台跨操作系统 OCR 智能路由（macOS 延续原生硬件加速，Linux/Windows 自动接入纯 CPU RapidOCR ONNX），同时完成了原生可编辑 Table 的中间表示定义、高保真 DrawingML 写入与复杂位图表格的逆向检测与背景平滑擦除闭环。

---

## 1. 版本内容摘要

pptkit v0.2.0 彻底攻克了跨平台位图 OCR 兼容性问题与幻灯片原生可编辑表格逆向还原。macOS 默认使用系统原生 Apple Vision，Windows 和 Linux 自动调度纯 CPU 的 RapidOCR ONNX 引擎；位图中的规整网格与横纹表格可全自动逆向还原为 PowerPoint 原生 Table 形状，单元格边距清零防断行、底图网格彻底平滑抹平，避免双重文字与底层像素重影。

---

## 2. 变更记录

### Added
- **跨平台 OCR 双引擎支持（F11）**：抽象 `BaseOCRAdapter` 协议，新增 `RapidOCRAdapter`，在 `get_ocr_adapter` 中实现自动化平台感知路由（macOS $\rightarrow$ Apple Vision，Linux/Windows $\rightarrow$ RapidOCR）。
- **CLI OCR 引擎选择参数（F13）**：`pptkit convert` 新增 `--ocr-engine [auto|apple_vision|rapidocr]` 选项，并在进度日志中明确输出当前使用的引擎（如 `route=raster, ocr=rapidocr`）。
- **原生 Table 中间表示（F12）**：在 Slide IR 中定义 `CellBorder`、`TableCell`、`TableElement`，支持富文本多样式、单元格对齐、背景底色、四周边框线宽与跨行跨列（`row_span`, `col_span`）。
- **PPTX 原生 Table 写入器（F12）**：在 `pptx_writer.py` 中支持原生 PowerPoint Table 形状创建，实现单元格边距清零防断行、DrawingML 底层 `<a:ln*>` 矢量边框注入与垂直对齐。
- **位图表格逆向拓扑分析与背景擦除（F12）**：在 `pptkit/raster/table.py` 中基于文字抹除图像进行形态学梯度检线，根据几何质心分配单元格文本并合并多行段落，平滑擦除底图网格线。
- **质量度量报告字段扩展（F13）**：`report.json` 中新增 `tables_count` 与 `table_cells_count` 统计指标。
- **CI 全平台矩阵自动化**：在 GitHub Actions 中配置 `macos-latest`、`ubuntu-latest`、`windows-latest` 三系统单元测试矩阵。

### Changed
- **防文本重叠机制**：被分配入表格的 OCR 文本框不会在幻灯片顶层生成孤立悬浮文本框，消除图层文字双重重叠。
- **形状检测与图层分离前置过滤**：表格区域在背景图中被优先提取并抹平，避免表格网格线被后续算法误检为散落卡片或线条。

### Fixed
- **PyInstaller 单文件打包入口修复**：新增 `src/pptkit/__main__.py` 保证打包后的单文件二进制具备正确的入口分发。
- **非 macOS 平台 Apple Vision 报错防御**：若在非 macOS 设备上显式指定 `apple_vision`，抛出友好的 `IngestError(code="UNSUPPORTED_PLATFORM")`。

---

## 3. 交付物清单与获取方式

### 3.1 预编译独立单文件可执行文件（免 Python 环境）
可前往 GitHub Releases 下载对应操作系统的免安装独立二进制：
- **macOS (Apple Silicon)**：`pptkit-macos-arm64.tar.gz`
- **Linux (x86_64)**：`pptkit-linux-x86_64.tar.gz`
- **Windows (x86_64)**：`pptkit-windows-x86_64.zip`（内含 `pptkit.exe`）

解压后即可直接在终端中运行：
```bash
./pptkit convert input.png -o out/
```

### 3.2 Python 包与 CLI
```bash
# 从源码或包管理器安装
uv pip install -e .
# 或使用 uv 直接运行
uv run pptkit convert presentation.pdf -o out/
```

---

## 4. 验收汇总

| 里程碑 | 目标 | 验收结论 | Spec 记录 |
|---|---|---|---|
| **M1 跨平台 OCR 闭环** | 抽象 `BaseOCRAdapter`，接入 RapidOCR，全平台 CI 矩阵构建 | **通过** (2026-10-26) | [spec-v0.2.0-m1.md](../spec/spec-v0.2.0-m1.md) |
| **M2 表格 IR 模型与 PPTX 生成闭环** | 扩展 `TableElement`，实现原生 PPTX Table 写入器与 DrawingML 边框 | **通过** (2026-10-26) | [spec-v0.2.0-m2.md](../spec/spec-v0.2.0-m2.md) |
| **M3 表格逆向推断与背景修复** | 拓扑网格检测、OCR 文本质心归属、表格底图平滑抹平与度量统计 | **通过** (2026-10-26) | [spec-v0.2.0-m3.md](../spec/spec-v0.2.0-m3.md) |

- **全量测试通过率**：
  - 单元测试：47 / 47 通过（100% 通过率，耗时 ~6.5s）
  - 端到端测试：4 / 4 通过（100% 通过率，耗时 ~45s）
  - 代码质量检查：`ruff check`、`ruff format`、`pyright` 静态类型检查 100% 绿灯。

---

## 5. 已知问题与下版建议 Backlog

1. **无线纯文本多列表格**：对于完全没有横线或竖线、纯靠文本间距排版的表格，当前会退化为独立普通文本框，可考虑在 v0.3.0 引入基于文本行网格对齐的虚拟表格推断。
2. **极度倾斜手绘表格**：对于角度倾斜超过 15 度的手绘涂鸦表格，建议交由 VLM 辅助端处理。
3. **v0.3.0 规划重点**：
   - 复杂统计图表（柱状图、折线图、饼图）的逆向提取与原生 PPTX Chart 还原。
   - 跨平台本地 GUI 可视化转换桌面端。
