---
doc: spec
product: v0.1.0
milestone: m1
date: 2026-10-19
status: approved
---

# Spec v0.1.0-m1 — M1 地基：Slide IR、PPTX 生成、渲染度量、合成基准与 CLI 骨架

## 1. 本里程碑目标与覆盖的 F/AC

**一句话目标**：建立统一的中间表示（Slide IR）、PPTX 生成器、基于 PowerPoint 的高保真渲染对比度量器、合成基准集与输入判定 CLI 骨架，跑通「标准答案 IR → PPTX → 渲染 PNG → 对比打分」全链路闭环。

### 覆盖的 F/AC 清单

| 功能 | 覆盖 AC | 本里程碑验收方式 |
|---|---|---|
| **F1 输入加载与路径判定** | AC1.1, AC1.2, AC1.3, AC1.4 | 5 种格式加载、vector/raster 按页判定（在 20 个已标注基准样本上 100% 准确）、混合页判定、加密/损坏/不支持格式非零退出与修复引导 |
| **F2 Slide IR** | AC2.1, AC2.2 | Pydantic 模型 JSON 往返完全一致；全项目整数 EMU，换算唯一实现在 `pptkit/common/units.py`（通过 AST/正则扫描单测强制） |
| **F3 PPTX 生成器** | AC3.1, AC3.2, AC3.3, AC3.4 | PowerPoint AppleScript 打开导出验证、WPS/Keynote 打开无报错截图验证；原生文本框与形状可编辑；宽高比保持；`z_order` 顺序一致 |
| **F4 渲染与对比度量** | AC4.1, AC4.2 | 同一 PPTX 连续两次渲染 SSIM 差值 < 0.001；输出 `ssim`、`text_region_mae`、差异热力图路径 |
| **F5 合成基准集** | AC5.1, AC5.2, AC5.3 | 一条命令生成 N 页合成样本（PPTX + PNG + PDF + 标准答案 IR）；自动评分器（字符准确率、框 IoU、字号误差、颜色 ΔE、形状召回/精确率、SSIM）；`benchmark/real/manifest.json` 登记 ≥20 页样本 |
| **F9 CLI（M1 骨架）** | AC9.1, AC9.4, AC9.5 | `pptkit convert <file\|dir> -o <outdir>` 单文件/目录转换产出 `.pptx` + `.report.json`（M1 对页面先产出「整页底图降级」PPTX 以打通端到端，M2/M3 接入真实解析）；无 API Key 时 vector 正常、raster 报错提示环境变量；单页容错与退出码 0/2/1 |

---

## 2. 关键功能设计思路

### 2.1 单位换算与几何基础 (`pptkit/common/units.py`, `pptkit/common/color.py`)
- **数据流**：只在输入边界（像素 `px` / PDF 点 `pt` → `EMU`）和输出边界（`EMU` → `pt` / `px`）调用 `units.py`。
- **换算常量**：
  - `EMU_PER_INCH = 914400`
  - `EMU_PER_PT = 12700`（1 inch = 72 pt）
  - 像素转 EMU：给定原图宽高 `(width_px, height_px)`，标准宽度固定为 `12192000` EMU（即 13.333333 inch = 960 pt），高度按比例 `round(12192000 * height_px / width_px)` 计算，确保任意分辨率的 16:9 图都精确映射到 `12192000 × 6858000` EMU，4:3 图映射到 `12192000 × 9144000` EMU。
- **颜色误差 ΔE**：`pptkit/common/color.py` 实现 sRGB (`#RRGGBB`) 转 CIE Lab 并计算 CIE76 ΔE，供合成基准评分（AC5.2）与后续模块共用。

### 2.2 Slide IR (`pptkit/ir/models.py`)
- 采用 Pydantic v2 强类型建模，禁止浮点坐标（`BBox` 的 `x, y, width, height` 全部为 `int`，且 `width > 0, height > 0`）。
- 所有页面元素（`TextBoxElement`、`ShapeElement`、`ImageElement`）统一继承基础元数据（`id`, `bbox`, `z_order`, `confidence`, `source`, `degraded`），存放在 `SlideIR.elements` 列表中；序列化时使用 discriminated union（按 `kind: Literal["textbox", "shape", "image"]` 区分）。
- 图片数据引用：IR JSON 中 `ImageElement` 与 `Background` 存储相对路径或 base64 URI，确保 JSON 可独立落盘和往返序列化（AC2.1）。

### 2.3 输入加载与路径判定 (`pptkit/ingest/loader.py`, `pptkit/ingest/router.py`)
- **支持格式**：`.png`, `.jpg`, `.jpeg`, `.webp`, `.pdf`。
- **异常处理（AC1.4）**：
  - 扩展名不支持 → 抛出 `IngestError(code="UNSUPPORTED_FORMAT", hint="支持的格式：.png, .jpg, .jpeg, .webp, .pdf")`
  - PDF 加密（`doc.is_encrypted`） → 抛出 `IngestError(code="ENCRYPTED_PDF", hint="该 PDF 已加密，请先用 qpdf --decrypt <in.pdf> <out.pdf> 解密")`
  - 文件损坏或空文件 → 抛出 `IngestError(code="CORRUPTED_FILE", hint="文件已损坏或无法读取，请检查源文件完整性")`
- **单页路由判定规则（AC1.2, AC1.3）**：
  - 单张位图文件（PNG/JPG/WEBP）：直接判定为 `raster`。
  - PDF 单页：通过 PyMuPDF (`pymupdf`) 提取该页文本块 `page.get_text("dict")`、矢量路径 `page.get_drawings()` 与图片列表 `page.get_images()`：
    1. 若页面可见非空白字符数 `>= 5` 且字体非全乱码（可解码 Unicode 字符比例 `>= 90%`），判定为 `vector`。
    2. 若页面无文字，但矢量绘图路径数 `>= 5` 且不存在覆盖全页面积 `>= 90%` 的单张大图（说明是纯形状矢量页），判定为 `vector`。
    3. 其余情况（如 NotebookLM 导出的整页位图 PDF、扫描件 PDF）全部判定为 `raster`。

### 2.4 PPTX 生成器 (`pptkit/writer/pptx_writer.py`)
- 基于 `python-pptx` 构建空白演示文稿，移除默认幻灯片版式占位符（使用 blank layout `slide_layouts[6]`）。
- 页面尺寸设为 `PresentationIR.width_emu` × `PresentationIR.height_emu`（AC3.3）。
- 对每页元素按 `z_order` 升序排序后依次写入幻灯片 XML 树（AC3.4）：
  - **背景**：纯色背景直接设置 `slide.background.fill`；图片背景作为最底层全屏图片写入。
  - **文本框 (`TextBoxElement`)**：调用 `slide.shapes.add_textbox(x, y, w, h)`，关闭默认自动边距或按 IR 设置 `margin_*`，禁用自动换行或按 IR 配置 `word_wrap`，遍历 `paragraphs` 和 `runs` 设置文字、字体名（同时写入西文字体与东亚字体 `a:ea` XML 节点，防止中文回退成默认宋体）、字号、颜色、粗斜体、对齐方式与行距。
  - **形状 (`ShapeElement`)**：支持矩形 (`rect`)、圆角矩形 (`round_rect`，设置 `adjustments[0]` 圆角率)、椭圆 (`ellipse`)、直线 (`line`)、箭头 (`right_arrow`)、自由多边形 (`freeform`)，设置填充色与描边。
  - **图片 (`ImageElement`)**：调用 `slide.shapes.add_picture(path, x, y, w, h)`。

### 2.5 渲染与对比度量 (`pptkit/render/renderer.py`, `pptkit/render/metrics.py`)
- **渲染器（D1 已验证方案）**：
  - 主渲染器 `PowerPointRenderer`：
    1. 将待测 `.pptx` 复制到沙盒工作目录 `~/Library/Containers/com.microsoft.Powerpoint/Data/Documents/pptkit/<uuid>/input.pptx`。
    2. 执行 AppleScript 打开该文件并 `save ... as save as PDF` 导出 `output.pdf`，随后关闭演示文稿。
    3. 用 `pymupdf` 打开 `output.pdf`，按目标原图像素尺寸 `(target_w, target_h)` 栅格化每一页为 PNG。
    4. 清理沙盒临时目录。
  - 备用渲染器 `LibreOfficeRenderer`：调用 `/Applications/LibreOffice.app/Contents/MacOS/soffice --headless --convert-to pdf` 转 PDF，再用 `pymupdf` 栅格化为 PNG。
- **图像对比度量（AC4.1, AC4.2）**：
  - `compute_ssim(img_a, img_b)`：基于 `scikit-image` (`skimage.metrics.structural_similarity`) 或精确高斯窗口实现，返回全局 SSIM 及差异图。
  - `compute_text_region_mae(img_a, img_b, text_bboxes)`：在标准答案或 IR 的所有文本框像素区域内计算平均绝对像素误差（0–255 范围）。
  - `save_diff_heatmap(img_a, img_b, out_path)`：将像素绝对差异映射为 COLORMAP_JET 热力图并与原图半透明叠加保存。

### 2.6 合成基准集 (`benchmark/synthetic/generator.py`, `benchmark/synthetic/evaluator.py`)
- **合成生成器（AC5.1）**：给定随机种子 `seed` 和页数 `n`，用代码随机组合常见幻灯片版式（标题页、双栏对比、卡片网格、图文混排），随机选取候选字体（苹方、思源黑体、Arial 等）、字号（14–48pt）、配色、矩形/圆角矩形/椭圆/线条，生成：
  1. 标准答案 `SlideIR`（保存为 `<id>.gt.json`）
  2. 由 `pptx_writer` 生成 `<id>.pptx`
  3. 由 `PowerPointRenderer` 导出 `<id>.pdf`（矢量 PDF 样本）和 `<id>.png`（位图样本）
- **自动评分器（AC5.2）**：输入预测 `SlideIR` 与标准答案 `SlideIR` + 渲染图，使用匈牙利匹配/贪心最大 IoU 匹配文本框与形状，计算：
  - `char_accuracy`：字符级编辑距离准确率 `1 - levenshtein(pred, gt) / max(len(gt), 1)`
  - `textbox_iou`：匹配文本框的平均 IoU
  - `font_size_mae_pt`：匹配文字片段的字号误差均值与中位数（pt）
  - `color_delta_e`：匹配文字/形状的颜色 CIE76 ΔE 均值与中位数
  - `shape_recall` / `shape_precision`：IoU ≥ 0.5 且类型一致视为命中
  - `ssim`：渲染 PNG 与原图的 SSIM

---

## 3. 数据模型与接口定义

### 3.1 Slide IR 核心数据结构 (`src/pptkit/ir/models.py`)

```python
from typing import Literal, Annotated
from pydantic import BaseModel, Field


class BBox(BaseModel):
    x: int = Field(ge=0, description="Left X in EMU")
    y: int = Field(ge=0, description="Top Y in EMU")
    width: int = Field(gt=0, description="Width in EMU")
    height: int = Field(gt=0, description="Height in EMU")


class TextStyle(BaseModel):
    font_family: str = "PingFang SC"
    font_size_pt: float = Field(gt=0)
    color_hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$", default="#000000")
    bold: bool = False
    italic: bool = False
    underline: bool = False


class TextRun(BaseModel):
    text: str
    style: TextStyle


class Paragraph(BaseModel):
    runs: list[TextRun]
    align: Literal["left", "center", "right", "justify"] = "left"
    line_spacing_pt: float | None = None
    space_after_pt: float = 0.0


class BaseElement(BaseModel):
    id: str
    bbox: BBox
    z_order: int = 0
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    source: Literal["vector", "ocr", "vlm", "cv", "synthetic", "fallback"] = "vector"
    degraded: bool = False


class TextBoxElement(BaseElement):
    kind: Literal["textbox"] = "textbox"
    paragraphs: list[Paragraph]
    word_wrap: bool = True
    margin_left_emu: int = 0
    margin_right_emu: int = 0
    margin_top_emu: int = 0
    margin_bottom_emu: int = 0


class ShapeElement(BaseElement):
    kind: Literal["shape"] = "shape"
    shape_type: Literal["rect", "round_rect", "ellipse", "line", "right_arrow", "freeform"]
    fill_color_hex: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    stroke_color_hex: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    stroke_width_emu: int = 0
    corner_radius_ratio: float = Field(default=0.0, ge=0.0, le=0.5)
    points_emu: list[tuple[int, int]] | None = None


class ImageElement(BaseElement):
    kind: Literal["image"] = "image"
    image_path: str


SlideElement = Annotated[
    TextBoxElement | ShapeElement | ImageElement,
    Field(discriminator="kind"),
]


class Background(BaseModel):
    fill_type: Literal["solid", "image"] = "solid"
    color_hex: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    image_path: str | None = None


class SlideIR(BaseModel):
    page_index: int = Field(ge=0)
    route: Literal["vector", "raster"]
    width_emu: int = 12192000
    height_emu: int = 6858000
    background: Background = Field(default_factory=Background)
    elements: list[SlideElement] = Field(default_factory=list)


class PresentationIR(BaseModel):
    source_path: str
    width_emu: int = 12192000
    height_emu: int = 6858000
    slides: list[SlideIR]
```

### 3.2 CLI 入口定义 (`src/pptkit/cli/app.py`)
```bash
pptkit convert <input_path> -o <output_dir> [--route auto|vector|raster] [--provider gemini|openai] [--json]
```
- 退出码约定（AC9.5）：
  - `0`：全部页面转换成功
  - `2`：部分页面成功、部分页面失败
  - `1`：全部失败，或输入文件级错误（加密、损坏、格式不支持、缺 API Key）

---

## 4. 关键决策记录

| 编号 | 决策点 | 选择方案 | 为什么这么选 & 对用户的影响 | 放弃的方案 |
|---|---|---|---|---|
| **SD1** | PowerPoint 渲染实现方式 | AppleScript 导出沙盒内 PDF + PyMuPDF 栅格化为 PNG | 实测 PowerPoint Mac 的 `save as PNG` 在 AppleScript 下静默失效，而 `save as PDF` 耗时仅 1.7 秒且 100% 保留 PowerPoint 原生字体与换行排版；再经 PyMuPDF 按原图精确宽高转 PNG，避免分辨率不一致导致 SSIM 失真 | 直接 `save as PNG`（静默失败）；纯用 LibreOffice（中文字体回退与换行和 PowerPoint 有偏差） |
| **SD2** | `python-pptx` 东亚字体写入 | 除设置 `run.font.name` 外，显式写入 `<a:ea typeface="..."/>` XML 属性 | `python-pptx` 的 `font.name` 只设置西文字体 `<a:latin>`，中文在 PowerPoint/WPS 打开时会回退到默认字体导致字形错位。显式写 `a:ea` 确保用户打开即看到正确中文字体 | 只调 `run.font.name`（中文必回退） |
| **SD3** | M1 阶段 CLI `convert` 的转换行为 | M1 完成路由判定后，将每页栅格图作为全屏底图写入 IR（标记 `degraded=True`）并生成 PPTX + `report.json`；若指定 `--route raster`（或自动判定为 raster 且未开启 `--allow-degraded-no-key`）则校验 API Key | 让 M1 就能端到端验证 CLI 的参数、批量目录处理、API Key 门禁（AC9.4）、单页容错与退出码（AC9.5），同时严格遵循“M2 实现矢量解析、M3 实现位图识别”的里程碑边界 | 在 M1 提前写死假的识别逻辑（违反演进式架构） |

---

## 5. 测试策略

### 5.1 单元测试清单（`tests/unit/`，秒级，无外部进程/网络）

| 测试文件 | 测试函数 | 覆盖 AC | 验证内容 |
|---|---|---|---|
| `test_units.py` | `test_px_pt_inch_to_emu_roundtrip` | AC2.2 | 像素、pt、inch 与整数 EMU 互转精度与取整 |
| `test_units.py` | `test_aspect_ratio_preservation_in_emu` | AC3.3 | 16:9、4:3、任意自定义宽高比计算出的页面 EMU 比例与原图一致 |
| `test_units.py` | `test_no_unit_constants_outside_units_module` | AC2.2 | 扫描 `src/pptkit/` 源码，确保除 `units.py` 外无任何文件硬编码 `914400` 或 `12700` |
| `test_color.py` | `test_delta_e_identical_and_complementary_colors` | AC5.2 | 相同颜色 ΔE=0，黑白 ΔE≈100，相近色 ΔE 计算准确 |
| `test_ir.py` | `test_presentation_ir_json_roundtrip_all_elements` | AC2.1 | 含 TextBox、Shape（含 freeform/round_rect）、Image、Background 的 IR 序列化 JSON 再反序列化完全相等 |
| `test_ir.py` | `test_ir_rejects_float_or_negative_bbox` | AC2.2 | 传入非整数或非正数宽高时 Pydantic 校验失败 |
| `test_ingest.py` | `test_load_five_formats_page_count_matches` | AC1.1 | 加载 `.png`, `.jpg`, `.jpeg`, `.webp`, `.pdf` 各 1 个样本，页数与尺寸正确 |
| `test_ingest.py` | `test_route_detection_vector_vs_raster_and_mixed_pdf` | AC1.2, AC1.3 | 含矢量文字页判 `vector`、纯位图页判 `raster`、混合 2 页 PDF 分别返回 `["vector", "raster"]` |
| `test_ingest.py` | `test_route_benchmark_20_annotated_samples_100_accuracy` | AC1.2 | 对 20 个已标注样本运行判定，准确率 100% |
| `test_ingest.py` | `test_ingest_error_on_encrypted_corrupted_unsupported` | AC1.4 | 加密 PDF、损坏文件、`.txt` 文件抛出对应 `IngestError` 且含修复提示 |
| `test_writer.py` | `test_write_pptx_native_textbox_and_shapes_editable` | AC3.2, AC3.3, AC3.4 | 生成 PPTX 后重新用 `python-pptx` 与 XML 解析校验：页面宽高比一致、文本框与形状为原生对象且属性可改、`a:ea` 东亚字体已写入、XML 顺序与 `z_order` 一致 |
| `test_metrics.py` | `test_ssim_mae_and_heatmap_generation` | AC4.1, AC4.2 | 相同图 SSIM=1.0、MAE=0.0；带局部差异图计算 `text_region_mae` 准确并成功生成热力图 PNG |
| `test_synthetic.py` | `test_generate_synthetic_slides_and_evaluate_metrics` | AC5.1, AC5.2 | 生成合成 IR 与 PPTX，对完美预测得满分（准确率 1.0, IoU 1.0, ΔE 0），对扰动预测准确算出各项误差 |
| `test_manifest.py` | `test_real_benchmark_manifest_has_at_least_20_pages` | AC5.3 | 校验 `benchmark/real/manifest.json` 结构合法，且涵盖 4 类来源各 ≥5 页（总页数 ≥20） |
| `test_cli.py` | `test_cli_convert_file_and_dir_outputs_pptx_and_report` | AC9.1, AC1.3 | 单文件与目录转换生成 `<name>.pptx` 与 `<name>.report.json`，报告含每页 `route` |
| `test_cli.py` | `test_cli_missing_api_key_allows_vector_blocks_raster` | AC9.4 | 清空环境变量时 vector 正常退出 0，raster 退出 1 且 stderr 提示 `PPTKIT_GEMINI_API_KEY` / `GEMINI_API_KEY` |
| `test_cli.py` | `test_cli_partial_failure_isolation_and_exit_codes` | AC9.5, AC1.4 | 单页异常不中断其余页并返回退出码 2；全部成功返回 0；加密/全部失败返回 1 |

### 5.2 集成测试与 E2E 测试清单（`tests/integration/`, `tests/e2e/`）

| 测试文件 | 测试函数 | 覆盖 AC | 验证内容 |
|---|---|---|---|
| `tests/integration/test_render_powerpoint.py` | `test_powerpoint_render_repeatability_ssim` | AC4.1, AC4.2 | 调用真实 PowerPoint 连续渲染同一 PPTX 两次，SSIM 差值 < 0.001，输出热力图 |
| `tests/integration/test_app_compatibility.py` | `test_open_in_powerpoint_wps_keynote_no_error` | AC3.1, AC3.2 | 用 PowerPoint、Keynote、WPS 真实打开生成的 PPTX，自动化校验无修复/报错弹窗并保存截图到 `out/compat/` |
| `tests/e2e/test_m1_pipeline.py` | `test_synthetic_end_to_end_benchmark_pipeline` | AC5.1, AC5.2, AC9.1 | 运行合成基准生成 5 页样本 → PowerPoint 渲染 → 评分汇总输出到 `benchmark/results/`；运行 `pptkit convert` 端到端转换并验证产出物 |

---

## 6. Task 拆分

| 编号 | 内容 | 覆盖 AC | 依赖 | 状态 |
|---|---|---|---|---|
| **T1** | 项目脚手架（`pyproject.toml`、`uv sync`）与 `pptkit/common/units.py`、`color.py` | AC2.2, AC3.3, AC5.2 | - | done (`uv run pytest tests/unit/test_units.py tests/unit/test_color.py`: 4 passed in 0.01s; ruff & pyright 0 errors) |
| **T2** | `pptkit/ir/models.py` Slide IR 数据模型与 JSON 往返序列化 | AC2.1, AC2.2 | T1 | done (`uv run pytest tests/unit/test_ir.py`: 2 passed in 0.05s; ruff & pyright 0 errors) |
| **T3** | `pptkit/ingest/` 5 种格式加载、vector/raster 路由判定、异常处理与 20 个测试样本 | AC1.1, AC1.2, AC1.3, AC1.4 | T2 | done (`uv run pytest tests/unit/test_ingest.py`: 4 passed in 0.81s, 20/20 route accuracy; ruff & pyright 0 errors) |
| **T4** | `pptkit/writer/pptx_writer.py` IR → PPTX 生成器（含东亚字体、形状、图片、层级） | AC3.2, AC3.3, AC3.4 | T2 | done (`uv run pytest tests/unit/test_writer.py`: 1 passed in 0.86s; ruff & pyright 0 errors) |
| **T5** | `pptkit/render/` PowerPoint & LibreOffice 渲染器 + SSIM / 区域 MAE / 差异热力图 + 真实软件兼容性校验脚本 | AC3.1, AC4.1, AC4.2 | T4 | pending |
| **T6** | `benchmark/synthetic/` 合成样本生成器、自动评分器与 `benchmark/real/manifest.json` | AC5.1, AC5.2, AC5.3 | T4, T5 | pending |
| **T7** | `pptkit/cli/` Typer CLI 入口（`convert` 单文件/目录、API Key 门禁、单页容错与退出码）及 E2E 测试 | AC9.1, AC9.4, AC9.5 | T3, T4, T5 | pending |

---

## 7. 界面与 F/AC 映射

本里程碑不涉及前端 GUI（v0.1.0 仅包含 CLI，GUI 在 v0.2.0 实现），无需 HTML 原型。
