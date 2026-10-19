---
doc: spec
product: v0.1.0
milestone: m2
date: 2026-10-19
status: draft
---

# Spec v0.1.0-m2 — M2 位图文字还原与质量报告：Apple Vision OCR、分级背景净化、字体/字号/取色与渲染对比微调

## 1. 本里程碑目标与覆盖的 F/AC

**一句话目标**：基于 macOS 原生 Apple Vision OCR + 分级背景净化 + 笔画像素聚类取色 + PowerPoint 渲染对比迭代，把位图幻灯片（包括用户提供的真实样图 `01-ai-beginner-workflow.jpg`）还原为「无文字残影的净空背景 + 100% 原生可编辑文本框」的 PPTX，并输出完整质量报告。

### 覆盖的 F/AC 清单

| 功能 | 覆盖 AC | 本里程碑验收方式 |
|---|---|---|
| **F7 位图路径：文字还原** | AC7.1, AC7.2, AC7.3, AC7.4, AC7.5 | 合成基准位图子集中英文字符级准确率 ≥ 98%；文字框 IoU 均值 ≥ 0.85、字号误差中位数 ≤ 1pt、颜色 ΔE 中位数 ≤ 5；净化后背景层用 OCR 复检残留字符比例 ≤ 2%；渲染对比迭代后 SSIM 不低于迭代前（默认最多 3 轮，可配 `--max-iter`）；候选字体集可配置 |
| **F9 CLI（完整参数）** | AC9.2, AC9.3, AC9.4 | 支持 `--route auto\|vector\|raster`、`--pages 1-3,5`、`--max-iter`、`--provider gemini\|openai`、`--vlm`、`--json`；显示每页进度与预计剩余时间（`--json` 时输出到 stderr）；本地离线模式无需 API Key 即可跑通 raster 路径，开启 `--vlm` 且无 API Key 时报错提示环境变量 |
| **F10 质量报告** | AC10.1, AC10.2 | `report.json` 含每页路由、SSIM、`text_region_mae`、可编辑元素数、降级元素数、低置信元素清单、缺失字体、耗时、模型调用次数；提供 `pptkit report <report.json> --needs-review` 筛出需人工复核页面 |

---

## 2. 关键功能设计思路

### 2.1 Apple Vision OCR 适配器 (`pptkit/adapters/ocr.py`)
- **架构遵循 GEMINI.md 原则 5**：定义统一的 `OCRAdapter` 协议与 `OCRTextBox` 数据结构（归一化或像素级 `x, y, width, height`、`text`、`confidence`）。
- **macOS 原生实现 (`AppleVisionOCRAdapter`)**：
  - 使用内嵌 Swift 源码编译并缓存轻量可执行二进制至 `~/.cache/pptkit/bin/vision_ocr`（首次编译约 1 秒，后续直接调用耗时 ~0.5 秒/页，无需额外安装庞大的 PyObjC 依赖）。
  - 配置 `VNRecognizeTextRequest`：`recognitionLevel = .accurate`、`recognitionLanguages = ["zh-Hans", "en-US"]`、`usesLanguageCorrection = true`。
  - 将 Vision 左下角原点坐标转换为左上角原点的像素框 `(x_px, y_px, w_px, h_px)`。
  - **后处理清洗**：修正常见 OCR 符号粘连（例如真实样图中 `o7 回答AI跟你提出的问题` 自动拆分为编号 `07` 与正文 `回答AI跟你提出的问题`；行首误识别为单字 `太 ` 的五角星图标符号自动剥离）。

### 2.2 文字颜色提取、字号估算与粗细判定 (`pptkit/raster/text_style.py`)
- **前景/背景像素双聚类分离（解决“取框平均色会混入背景色”的问题）**：
  1. 在文字框外围扩充 3–6px 的环形边框采样**局部背景色** `bg_rgb`（取中位数 RGB）及其色彩标准差 `bg_std`。
  2. 在文字框内部计算每个像素与 `bg_rgb` 的欧氏距离，选取距离最大的前 25%–35% 像素作为**文字笔画前景像素**。
  3. 取前景像素的中位数 RGB 作为文字颜色 `color_hex`（在合成基准与真实样图上 ΔE < 2）。
- **粗细 (`bold`) 判定**：计算框内前景笔画像素占比（stroke density），结合字号高度判定是否为粗体（如大标题与胶囊白字自动判为 `bold=True`）。
- **字号 (`font_size_pt`) 初始估算**：
  - 在 16:9 标准页（高度 `540pt = 6858000 EMU`）下，根据文字框像素高度 `h_px / page_h_px * 540` 乘以字面框与行高比例系数（中文单行约 `0.78`）并对齐常见字号梯度，随后交由渲染对比微调器精确校准。
- **候选字体集（AC7.5）**：默认 `["PingFang SC", "Heiti SC", "Songti SC", "Arial", "Helvetica"]`，支持配置覆盖。

### 2.3 分级背景净化 (`pptkit/raster/inpaint.py`)
- **遵循 PRD 决策 D3 的三级净化策略**：
  1. 对每个 OCR 文本框向四周外扩 `pad = 3px` 得到抹除区域 `box_pad`，采样其环形外框像素计算颜色标准差 `std`。
  2. **第 1 级（纯色背景，`std <= 12.0`）**：直接用环形外框的中位数颜色填平该矩形区域。对于圆角彩色胶囊内的白字（如 `01`–`12`、“需要一台电脑”），环形外框正好采样到胶囊内部的纯色（橙色/绿色/蓝色/黄色），填平后胶囊形状完好无损、文字 100% 消失！
  3. **第 2 级（渐变或纹理边界，`std > 12.0`）**：仅将文字框内偏离背景色的笔画前景像素生成二值掩码 `mask`，使用双线性/距离加权邻域插值（或 OpenCV Navier-Stokes 修复）平滑过渡填充，绝不破坏旁边的容器边框线。
  4. **第 3 级（复杂照片背景）**：预留 `LaMaInpaintAdapter` 接口，按需加载 `~/.cache/pptkit/models/lama_fp32.onnx`。
- **OCR 复检门禁（AC7.3）**：提供 `verify_background_cleanliness(clean_img, orig_char_count, ocr_adapter)`，对净化后的背景图再跑一次 OCR，确保残留原文字数比例 `<= 2%`。

### 2.4 渲染对比微调循环 (`pptkit/raster/refiner.py`)
- **闭环优化（AC7.4）**：
  - 第 0 轮：用初始估算的字号与位置生成 PPTX 并渲染 PNG，计算初始 `SSIM_0` 与每个文本框区域的局部 MAE。
  - 第 `1..max_iter` 轮（默认 `max_iter=3`）：针对局部误差较大的文本框，在候选字号偏移 `[-1.5pt, -0.5pt, +0.5pt, +1.5pt]` 及微调垂直偏移中搜索能降低局部像素误差的参数；若新一轮整体 `SSIM >= 当前最佳 SSIM` 则采纳，否则回退，**严格保证迭代后 SSIM 单调不降（AC7.4）**。

### 2.5 CLI 增强与质量报告 (`pptkit/cli/app.py`, `pptkit/report/reporter.py`)
- 支持 `--pages`（如 `1-3,5` 解析为 0-based 索引集合 `{0, 1, 2, 4}`）、`--max-iter`、`--vlm`（可选开启 Gemini VLM 校验）。
- 转换进度条输出到 `stderr`（包含当前页、总页数、预计剩余秒数 ETA），确保 `--json` 模式下 `stdout` 只有纯 JSON（AC9.2, AC9.3）。
- 新增子命令 `pptkit report <report_json_path> [--needs-review] [--ssim-threshold 0.90]`，输出需要人工复核的页面列表（AC10.2）。

---

## 3. 数据模型与接口定义

### 3.1 OCR 与报告数据结构
```python
@dataclass
class OCRBox:
    text: str
    bbox_px: tuple[int, int, int, int]  # (x, y, w, h) in pixels, top-left origin
    confidence: float

class PageQualityReport(BaseModel):
    page_index: int
    route: Literal["vector", "raster"]
    status: Literal["ok", "failed"]
    ssim: float | None = None
    text_region_mae: float | None = None
    heatmap_path: str | None = None
    editable_elements: int = 0
    degraded_elements: int = 0
    low_confidence_elements: list[str] = Field(default_factory=list)
    missing_fonts: list[str] = Field(default_factory=list)
    elapsed_sec: float = 0.0
    model_calls: int = 0
    error: str | None = None
```

---

## 4. 关键决策记录

| 编号 | 决策点 | 选择方案 | 为什么这么选 & 对用户的影响 | 放弃的方案 |
|---|---|---|---|---|
| **SD4** | Apple Vision 调用方式 | 编译 ~40 行 Swift CLI 二进制并缓存到 `~/.cache/pptkit/bin/vision_ocr` | 机器自带 Swift 6.2，编译一次仅需 0.8s，运行一次 0.5s，零 Python C 扩展兼容问题，完美支持 macOS 26 | 安装 `pyobjc-framework-Vision`（包体大、编译慢、常与 Python 3.12+ 产生 wheel 兼容冲突） |
| **SD5** | 离线 raster 路径与 API Key 的关系 | 默认使用「Apple Vision + 本地分级背景净化」直接完成位图还原，无需 API Key；仅当指定 `--vlm` 时才强制要求 API Key | 让用户拿到工具零配置就能直接转换截图和 NotebookLM PDF（践行“系统承担复杂性、不要让用户思考”）；需要云端大模型增强时再配 Key | 只要是图片就强制要求填 Gemini API Key（增加使用门槛，且无 Key 时无法本地离线工作） |
| **SD6** | 胶囊标签内文字的背景净化边界 | 仅对框内偏离局部背景中位数色的前景笔画像素做掩码替换，不粗暴涂抹整个外扩矩形 | 像 `01-ai-beginner-workflow.jpg` 中 `01`–`12` 小圆角框紧贴边缘，只抹除笔画像素可 100% 保留圆角框本身轮廓与填充色 | 整个矩形框无脑涂抹（会把小圆角标签的圆角和边框一起抹坏） |

---

## 5. 测试策略

### 5.1 单元测试清单（`tests/unit/`）

| 测试文件 | 测试函数 | 覆盖 AC | 验证内容 |
|---|---|---|---|
| `test_ocr.py` | `test_apple_vision_ocr_extracts_chinese_and_english_accurately` | AC7.1 | 在合成含中英文的图片上调用 `AppleVisionOCRAdapter`，字符准确率 ≥ 98%，坐标在图像范围内 |
| `test_text_style.py` | `test_extract_text_color_font_size_and_bold_from_crop` | AC7.2, AC7.5 | 从带背景色的文字图像块中准确分离出前景文字色（ΔE ≤ 5）、字号误差 ≤ 1pt、候选字体合法 |
| `test_inpaint.py` | `test_tiered_inpaint_removes_text_leaves_less_than_2pct_chars` | AC7.3 | 对含多处中英文文字的幻灯片执行背景净化后，用 Apple Vision 复检背景图，检出原文字符比例 ≤ 2%，且非文字区像素不变 |
| `test_refiner.py` | `test_iterative_refiner_monotonic_ssim_and_max_iter` | AC7.4 | 验证微调器遵守 `max_iter` 上限，且输出结果的 SSIM 严格不低于初始未微调版本 |
| `test_report.py` | `test_report_model_and_needs_review_filter` | AC10.1, AC10.2 | 验证 `report.json` 包含全部必需字段，`filter_needs_review` 准确筛出 `ssim < 阈值` 或 `degraded > 0` 的页面 |
| `test_cli.py` | `test_cli_pages_filter_progress_stderr_and_vlm_key_check` | AC9.2, AC9.3, AC9.4 | 验证 `--pages 1,3` 只转指定页、`--json` 模式下进度写 stderr 而 stdout 为纯 JSON、离线 raster 免 Key 成功、`--vlm` 缺 Key 报错退出 1 |

### 5.2 集成与 E2E 测试清单（`tests/integration/`, `tests/e2e/`）

| 测试文件 | 测试函数 | 覆盖 AC | 验证内容 |
|---|---|---|---|
| `tests/integration/test_raster_synthetic_benchmark.py` | `test_synthetic_raster_benchmark_meets_f7_thresholds` | AC7.1, AC7.2, AC7.3, AC7.4 | 对合成基准的位图样本运行完整 raster 还原 + PowerPoint 渲染打分，验证字符准确率 ≥ 98%、IoU ≥ 0.85、字号中位误差 ≤ 1pt、颜色 ΔE 中位数 ≤ 5、背景残留字符 ≤ 2% |
| `tests/e2e/test_real_slide_workflow.py` | `test_convert_user_real_slide_to_editable_pptx` | F7, F9, F10 | 对用户真实样图 `benchmark/real/other/01-ai-beginner-workflow.jpg` 执行 `pptkit convert`，用 PowerPoint 渲染还原后的 PPTX，校验原生可编辑文本框数量 ≥ 25、核心标题与条目文字全部可编辑、背景无残影、生成对比图与质量报告 |

---

## 6. Task 拆分

| 编号 | 内容 | 覆盖 AC | 依赖 | 状态 |
|---|---|---|---|---|
| **T1** | `pptkit/adapters/ocr.py` Apple Vision OCR 适配器与文本行后处理清洗 | AC7.1 | - | pending |
| **T2** | `pptkit/raster/text_style.py` 笔画像素前景取色、字号估算、粗细/对齐判定与候选字体配置 | AC7.2, AC7.5 | T1 | pending |
| **T3** | `pptkit/raster/inpaint.py` 分级背景净化器与 OCR 残留字符复检 | AC7.3 | T1, T2 | pending |
| **T4** | `pptkit/raster/pipeline.py` & `refiner.py` 位图文字重建流水线与渲染对比单调微调 | AC7.1–7.5 | T1, T2, T3 | pending |
| **T5** | `pptkit/report/` & `pptkit/cli/app.py` 完整质量报告、`--pages`/`--max-iter`/`--vlm`、`pptkit report --needs-review` 及真实样图 E2E 验收 | AC9.2, AC9.3, AC9.4, AC10.1, AC10.2 | T4 | pending |

---

## 7. 界面与 F/AC 映射

本里程碑不涉及前端 GUI，无需 HTML 原型。
