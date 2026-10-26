---
doc: spec
product: v0.2.0
milestone: m1
date: 2026-10-26
status: approved
---

# Spec v0.2.0-m1 — 跨平台离线 OCR 适配与双引擎自动分流

## 1. 本里程碑目标与覆盖的 F/AC

**一句话目标**：规范抽象 `BaseOCRAdapter`，在现有 macOS 原生 `AppleVisionOCRAdapter` 基础上新增纯 CPU、轻量跨平台的 `RapidOCRAdapter`，实现按操作系统的智能自动分流与 CLI 参数覆盖，并在 Linux/Windows CI 与本地完成 100% 自动化测试。

### 覆盖的 F/AC 清单

| 功能 | 覆盖 AC | 本里程碑验收方式 |
|---|---|---|
| **F11 跨平台位图 OCR 适配器** | AC11.1 | 抽象 `BaseOCRAdapter` 协议与标准化 `OCRBox` 数据结构，解耦具体引擎实现 |
| **F11 跨平台位图 OCR 适配器** | AC11.2 | `AppleVisionOCRAdapter` 封装为 `BaseOCRAdapter` 实现，macOS 默认路由，0 模型下载 |
| **F11 跨平台位图 OCR 适配器** | AC11.3 | 实现 `RapidOCRAdapter`，基于 `rapidocr-onnxruntime`，内置轻量模型，纯 CPU 运行 |
| **F11 跨平台位图 OCR 适配器** | AC11.4 | 实现 `get_ocr_adapter(engine="auto")` 工厂：macOS 默认 `apple_vision`，非 macOS 默认 `rapidocr`；支持参数指定，非 Mac 指定 `apple_vision` 时优雅报错退出（code 1） |
| **F11 跨平台位图 OCR 适配器** | AC11.5 | 在 GitHub Actions CI 的 `ubuntu-latest` 与 `windows-latest` 虚拟机中，运行单元与端到端测试 |
| **F13 质量报告与 CLI 扩展** | AC13.2 | CLI `pptkit convert` 增加 `--ocr-engine auto|apple_vision|rapidocr`，并在执行中显示生效的引擎名称 |

---

## 2. 关键功能设计思路

### 2.1 适配器协议与抽象类定义
在 `src/pptkit/adapters/ocr.py` 中：
- 定义 `class BaseOCRAdapter(typing.Protocol)`（或 ABC 抽象类），具备统一接口：
  ```python
  def recognize(self, image_path: Path | str, clean: bool = True) -> list[OCRBox]: ...
  ```
- 统一输出 `OCRBox(text=..., bbox_px=(x, y, w, h), confidence=...)`；
- 通用后处理清洗函数 `clean_ocr_boxes` 对所有 OCR 适配器输出通用生效（包括合并双位数徽章前缀、剔除噪点图标字符、同行标点片段合并）。

### 2.2 RapidOCR 适配器实现（`RapidOCRAdapter`）
- 使用 `rapidocr_onnxruntime.RapidOCR`；
- 输入：图片路径（或 PIL Image / numpy 数组）；
- 输出解析：RapidOCR 输出结构为 `result, elapse = engine(img)`，其中每项为 `[box_points, text, score]`：
  - `box_points` 为 4 个顶点的坐标 `[[x0, y0], [x1, y1], [x2, y2], [x3, y3]]`；
  - 转换为 `(x_min, y_min, width, height)` 矩形包围盒；
- 延迟初始化（Lazy Loading）：首次调用 `recognize()` 时才实例化 ONNX 运行时，避免在仅处理矢量 PDF 或展示 `--help` 时产生模型加载开销。

### 2.3 自适应工厂函数 `get_ocr_adapter`
```python
def get_ocr_adapter(engine: Literal["auto", "apple_vision", "rapidocr"] = "auto") -> BaseOCRAdapter:
    if engine == "auto":
        target = "apple_vision" if sys.platform == "darwin" else "rapidocr"
    else:
        target = engine

    if target == "apple_vision":
        if sys.platform != "darwin":
            raise IngestError(
                code="UNSUPPORTED_PLATFORM",
                message="Apple Vision OCR 仅在 macOS 系统可用",
                hint="请改用 --ocr-engine rapidocr 或保持默认 --ocr-engine auto",
            )
        return AppleVisionOCRAdapter()
    elif target == "rapidocr":
        return RapidOCRAdapter()
    else:
        raise ValueError(f"未知的 OCR 引擎：{engine}")
```

### 2.4 CLI 与 Pipeline 接入
- `pptkit.raster.pipeline.reconstruct_raster_slide` 增加参数 `ocr_engine: Literal["auto", "apple_vision", "rapidocr"] = "auto"`，调用 `get_ocr_adapter(ocr_engine)`；
- `pptkit.cli.app.convert` 增加 CLI 选项 `--ocr-engine`（默认 `"auto"`）；
- 在控制台进度打印中显示使用的 OCR 引擎名称（如 `[route=raster, ocr=apple_vision]` 或 `[route=raster, ocr=rapidocr]`）。

---

## 3. 数据模型 / 接口定义

```python
from typing import Literal, Protocol
from dataclasses import dataclass
from pathlib import Path


@dataclass
class OCRBox:
    text: str
    bbox_px: tuple[int, int, int, int]
    confidence: float


class BaseOCRAdapter(Protocol):
    def recognize(self, image_path: Path | str, clean: bool = True) -> list[OCRBox]: ...


OCREngineType = Literal["auto", "apple_vision", "rapidocr"]
```

---

## 4. 关键决策记录

| 编号 | 决策项 | 选择与理由 | 放弃方案与代价 |
|---|---|---|---|
| **D6** | OCR 引擎运行时依赖策略 | 将 `rapidocr-onnxruntime` 作为核心依赖引入 `pyproject.toml` | 放弃「仅当使用时动态 pip 安装」方案。动态安装会导致无网络环境下首次运行失败，且在打包单文件二进制时无法被 PyInstaller 收集。 |
| **D7** | 模型初始化时机 | **惰性初始化（Lazy Initialization）**：在适配器首次调用 `recognize` 时才加载 ONNX Session | 放弃「模块导入时全局初始化」。全局初始化会导致即使只运行 `pptkit --help` 或执行矢量 PDF 转换，也会白白耗费数百毫秒加载模型权重。 |

---

## 5. 测试策略

### 5.1 单元测试清单（`tests/unit/`）

| 测试文件 | 测试函数 | 覆盖 AC | 验证内容 |
|---|---|---|---|
| `test_ocr_adapters.py` | `test_base_adapter_factory_auto_selection` | AC11.4 | 验证在 macOS 上默认返回 `AppleVisionOCRAdapter`；mock 非 darwin 平台时默认返回 `RapidOCRAdapter` |
| `test_ocr_adapters.py` | `test_apple_vision_on_non_macos_raises_friendly_error` | AC11.4 | 验证在非 macOS 平台上显式要求 `apple_vision` 时抛出合规 `IngestError(code="UNSUPPORTED_PLATFORM")` |
| `test_ocr_adapters.py` | `test_rapid_ocr_recognize_output_format` | AC11.1, AC11.3 | 生成合成文字图片，验证 `RapidOCRAdapter` 正确输出 `OCRBox`，坐标与置信度合法 |
| `test_cli.py` | `test_cli_convert_with_ocr_engine_option` | AC13.2 | 验证 CLI 接收 `--ocr-engine rapidocr` 并正常完成单页栅格图转换 |

### 5.2 集成与 E2E 测试清单（`tests/e2e/`, `.github/workflows/`）

| 测试文件 | 验证内容 | 覆盖 AC |
|---|---|---|
| `tests/unit/` 全量回归 | 确保现有所有 32 个单元测试与 4 个 E2E 测试 100% 通过 | 全部既有 AC |
| `.github/workflows/ci.yml` | 增加 `ubuntu-latest` 与 `windows-latest` 运行单元测试（使用 RapidOCR） | AC11.5 |

---

## 6. Task 拆分

| 编号 | 内容 | 覆盖 AC | 依赖 | 状态 |
|---|---|---|---|---|
| **T1** | 引入 `rapidocr-onnxruntime` 依赖，重构 `src/pptkit/adapters/ocr.py`，实现 `BaseOCRAdapter`、`RapidOCRAdapter` 与 `get_ocr_adapter` 工厂 + 单元测试 | AC11.1, AC11.2, AC11.3, AC11.4 | - | completed |
| **T2** | 贯通 `pipeline.py`、`inpaint.py` 与 `cli/app.py`，支持 `--ocr-engine` 参数并在转换日志中显式输出引擎名称 + CLI 单元测试 | AC13.2 | T1 | completed |
| **T3** | 更新 `.github/workflows/ci.yml` 引入跨平台矩阵测试，在 Linux / Windows / macOS 全部跑通并验收 M1 | AC11.5 | T1, T2 | completed |

---

## 7. 界面与 F/AC 映射

本里程碑不涉及前端 GUI，无需 HTML 原型。

---

## 8. 验收记录

### 验收时间：2026-10-26
- **代码质检**：
  - `uv run ruff check .`：通过（0 errors）。
  - `uv run ruff format --check .`：通过（81 files formatted）。
  - `uv run pyright`：通过（0 errors, 0 warnings）。
- **单元测试与覆盖**：
  - `uv run pytest tests/unit`：37 passed, 0 failed（新增 `test_ocr_adapters.py` 覆盖平台自动调度、非 macOS 异常防御及 RapidOCR 输出格式）。
- **端到端测试**：
  - `uv run pytest tests/e2e`：4 passed, 0 failed。
- **CI 多平台配置**：
  - `.github/workflows/ci.yml` 已配置 `ubuntu-latest`, `windows-latest`, `macos-latest` 三平台构建矩阵。
- **验收结论**：**通过**，M1 跨平台 OCR 闭环交付完毕。

