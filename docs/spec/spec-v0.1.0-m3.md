---
doc: spec
product: v0.1.0
milestone: m3
date: 2026-10-19
status: approved
---

# Spec v0.1.0-m3 — M3 位图形状与配图分层还原：几何形状检测、独立插图抠取与低置信退化保护

## 1. 本里程碑目标与覆盖的 F/AC

**一句话目标**：在 M2 抹除文字后的净空背景图（`cleaned_bg_img`）基础上，进一步将纯色/描边几何形状（矩形、圆角矩形、胶囊标签、椭圆、直线、箭头）还原为 PowerPoint 原生可编辑 `ShapeElement`，将独立插图/图标/照片裁切为可单独选中拖动的透明 PNG `ImageElement`，并将各自的原始区域从底层背景抹除，实现真正的**多图层独立可编辑 PPTX**。

### 覆盖的 F/AC 清单

| 功能 | 覆盖 AC | 本里程碑验收方式 |
|---|---|---|
| **F8 位图路径：形状与图片分层** | AC8.1 | 纯色填充或描边的矩形、圆角矩形、椭圆、直线、箭头还原为原生 `ShapeElement`；在合成基准位图集上形状召回率 ≥ 85%、精确率 ≥ 90% |
| **F8 位图路径：形状与图片分层** | AC8.2 | 照片与复杂插图（如真实样图中的电脑图标组、人物麦克风、气泡框、文档文件夹组、五角星等）作为独立 `ImageElement`（带透明通道 PNG）裁出，底层背景同步填平，在 PowerPoint 中可单独选中、移动、缩放且底层无重影 |
| **F8 位图路径：形状与图片分层** | AC8.3 | 几何拟合置信度低于阈值（`< 0.75`）的候选区域不强行转成走样的矢量形状，自动降级为图片层或保留在背景层，并在 `report.json` 的 `degraded_elements` 与 `low_confidence_elements` 中记录 |

---

## 2. 关键功能设计思路

### 2.1 分层重建总体流水线（在 `cleaned_bg_img` 上执行）
M2 已经产出移除了全部文字笔画的 `cleaned_bg_img` 及 `TextBoxElement` 列表（`z_order >= 100`）。M3 在 `cleaned_bg_img` 上按从大到小、从底到顶的顺序拆解非文字视觉元素：
1. **全局底色估计**：采样页面四边外框像素中位数，得到页面基础底色 `page_bg_rgb`（例如真实样图的米白纸张底色 `#FAF7EE`，或合成样本的纯色背景）。
2. **原生几何形状检测与提取 (`pptkit/raster/shapes.py`)**：
   - **色块填充型形状（卡片、胶囊标签、纯色块、箭头、椭圆）**：
     - 对偏离 `page_bg_rgb` 的显著色块区域提取连通域掩码，计算外接框 `(x, y, w, h)`、面积占比 `fill_ratio = area / (w * h)`、内部色彩标准差 `inner_std` 以及四角圆弧曲率。
     - **分类规则**：
       - `fill_ratio >= 0.94` 且内部色彩均匀：`rect`（直角矩形）。
       - `0.76 <= fill_ratio < 0.94` 且四角对称内缩：`round_rect`（圆角矩形/胶囊标签），根据四角空白像素面积反推 `corner_radius_ratio`（`0.05`–`0.50`）。
       - `0.70 <= fill_ratio < 0.84` 且轮廓与椭圆方程拟合误差 `< 0.04`：`ellipse`。
       - 单向凸起且长宽比显著、头部呈三角形收敛：`right_arrow`。
   - **细线描边型容器与分隔线（大圆角容器框、横幅框、直线）**：
     - 检测内部接近 `page_bg_rgb` 但四周存在闭合彩色描边的矩形环路（如真实样图的 4 个大圆角分区框与底部横幅框），提取 `stroke_color_hex`、`stroke_width_emu`、`fill_color_hex` 与 `corner_radius_ratio`，生成底层容器 `ShapeElement`（`z_order: 1..20`）。
     - 检测水平或垂直细长线段（`w / h >= 12` 或 `h / w >= 12`），还原为 `line` 形状。
3. **独立插图与图标层分割 (`pptkit/raster/layers.py`)**：
   - 在扣除已还原为 `ShapeElement` 的区域后，对剩余偏离背景色（或容器内底色）的复杂多色连通区域（经形态学膨胀聚合邻近笔触，过滤噪点）提取为独立插图区域（如电脑+麦克风插图、人物+话筒、文档+文件夹、循环箭头、底部五角星等）。
   - **透明背景抠图（Alpha Matting）**：将插图裁剪区域内与局部背景色差 `<= 18` 的像素设为透明（`alpha = 0`），边缘像素平滑过渡，保存为独立 RGBA PNG（`slide_000_img_001.png` 等），生成 `ImageElement`（`z_order: 30..80`）。
4. **底层背景同步抹除**：
   - 所有已提取为原生 `ShapeElement` 或独立 `ImageElement` 的像素区域，在最终 `cleaned_bg_img` 中用其所在容器的底色（或 `page_bg_rgb`）填平，确保用户在 PowerPoint 中拖动任何形状或插图时，底下不会留有原图的残影。
5. **置信度门禁与退化策略 (`AC8.3`)**：
   - 每个候选形状计算几何与色彩一致性得分 `confidence in [0.0, 1.0]`。
   - 若 `confidence >= 0.75`：生成可编辑 `ShapeElement`。
   - 若 `0.40 <= confidence < 0.75`：遵循「宁可退化，不可错乱」，不生成走样的矢量形状，而是将其作为 `ImageElement(degraded=True)`（或保留在背景层），并将元素 ID 记入 `PageQualityReport.degraded_elements` 与 `low_confidence_elements`。

---

## 3. 数据模型与接口定义

### 3.1 形状与图层提取结果结构 (`pptkit/raster/shapes.py` & `pptkit/raster/layers.py`)

```python
@dataclass
class ShapeExtractionResult:
    shapes: list[ShapeElement]
    degraded_ids: list[str]
    residual_image: Image.Image  # Background image with extracted shapes erased


@dataclass
class LayerExtractionResult:
    images: list[ImageElement]
    final_bg_image: Image.Image  # Fully cleaned base background image
```

### 3.2 元素层级顺序 (`z_order`) 规范
- `0`：底图背景（`Background`）
- `10..29`：大型描边容器框（如 4 大分区圆角框、底部横幅框）
- `30..59`：独立插图与图标层（`ImageElement`）
- `60..99`：顶层胶囊标签与小徽章（如 `01`–`12` 圆角框、分区标题胶囊）
- `100+`：原生可编辑文本框（`TextBoxElement`，永远位于形状与徽章上方，保证文字不被遮挡）

---

## 4. 关键决策记录

| 编号 | 决策点 | 选择方案 | 为什么这么选 & 对用户的影响 | 放弃的方案 |
|---|---|---|---|---|
| **SD7** | 形状提取后底层背景如何处理 | 提取出 `ShapeElement` 或 `ImageElement` 后，同步将该区域在 `slide_xxx_bg.png` 中用局部底色填平 | 如果底层背景不抹除，用户在 PowerPoint 里移动或改色一个胶囊/插图时，原位置还会露出一模一样的死图残影，等于“假可编辑” | 只在原背景图上叠加新形状、不抹除底层（移动元素即露馅） |
| **SD8** | 复杂手绘插图（电脑/人物/文件夹）的还原方式 | 抠取为带 RGBA 透明通道的独立 `ImageElement`，而非强行矢量化为几十个碎多边形 | 手绘/AI 插图用碎多边形拟合会严重失真且难以整体拖动；做成透明背景 PNG 图层既能 100% 保持原画视觉（像素零损失），又能像普通配图一样在 PPT 中任意拖动、缩放、替换（符合 AC8.2） | 强行用 `freeform` 拟合复杂插图（视觉崩坏且元素碎裂） |
| **SD9** | 形状拟合低置信阈值 | `SHAPE_CONFIDENCE_THRESHOLD = 0.75`；低于该阈值的复杂非规则区域标记 `degraded=True` 并保留像素视觉 | 严格落实 GEMINI.md 原则 4「宁可退化，不可错乱」，绝不输出变形错位的原生形状 | 无论什么连通域都强转矩形/椭圆 |

---

## 5. 测试策略

### 5.1 单元测试清单（`tests/unit/`）

| 测试文件 | 测试函数 | 覆盖 AC | 验证内容 |
|---|---|---|---|
| `test_shapes.py` | `test_detect_solid_rect_round_rect_ellipse_line_and_arrow` | AC8.1 | 在包含纯色矩形、圆角矩形、椭圆、水平线、右箭头的合成画布上运行 `extract_raster_shapes`，验证形状类型、颜色（ΔE ≤ 5）、位置（IoU ≥ 0.85）全部正确，且底层画布已被抹平 |
| `test_shapes.py` | `test_low_confidence_irregular_blob_degrades_gracefully` | AC8.3 | 对不规则渐变噪点色块运行 `extract_raster_shapes`，验证其不会生成错误 `ShapeElement`，而是记录到 `degraded_ids` 且视觉保留 |
| `test_layers.py` | `test_extract_standalone_illustration_layers_with_alpha` | AC8.2 | 在干净背景上绘制多色图标组合，运行 `extract_image_layers`，验证输出独立 RGBA PNG 的 `ImageElement`，透明通道正确，且原背景对应区域被填平 |

### 5.2 集成与 E2E 测试清单（`tests/integration/`, `tests/e2e/`）

| 测试文件 | 测试函数 | 覆盖 AC | 验证内容 |
|---|---|---|---|
| `tests/integration/test_raster_synthetic_benchmark.py` | `test_synthetic_raster_benchmark_shapes_recall_and_precision` | AC8.1 | 在合成基准位图集上验证形状召回率 ≥ 85%、精确率 ≥ 90%，整体 SSIM ≥ 0.90 |
| `tests/e2e/test_real_slide_workflow.py` | `test_convert_user_real_slide_shapes_and_layers_editable` | AC8.1, AC8.2, AC8.3 | 在真实样图 `01-ai-beginner-workflow.jpg` 上验证生成的 PPTX 同时包含原生可编辑 `TextBoxElement`（≥ 35 个）、原生可编辑 `ShapeElement`（胶囊徽章与容器框 ≥ 15 个）以及可独立移动的插图 `ImageElement`（≥ 4 个），PowerPoint 渲染无错乱 |

---

## 6. Task 拆分

| 编号 | 内容 | 覆盖 AC | 依赖 | 状态 |
|---|---|---|---|---|
| **T1** | `pptkit/raster/shapes.py` 纯色与描边几何形状检测、分类（`rect`/`round_rect`/`ellipse`/`line`/`right_arrow`）、置信度退化与背景填平 | AC8.1, AC8.3 | - | done (`uv run pytest tests/unit/test_shapes.py`: 2 passed in 0.29s; ruff & pyright 0 errors) |
| **T2** | `pptkit/raster/layers.py` 独立插图/照片连通域分割、RGBA 透明背景抠图与背景填平 | AC8.2 | T1 | done (`uv run pytest tests/unit/test_layers.py`: 1 passed in 0.33s; ruff & pyright 0 errors) |
| **T3** | 将 `shapes` 与 `layers` 接入 `pptkit/raster/pipeline.py`，完成合成基准形状召回率/精确率集成测试与真实样图多图层 E2E 验收 | AC8.1, AC8.2, AC8.3 | T1, T2 | done (`uv run pytest tests/unit tests/integration/test_raster_synthetic_benchmark.py tests/e2e`: 28 passed; ruff & pyright 0 errors) |

---

## 7. 界面与 F/AC 映射

本里程碑不涉及前端 GUI，无需 HTML 原型。

---

## 8. 验收记录

- 验收日期：2026-10-19
- 验收范围：AC8.1、AC8.2、AC8.3
- 验证结果：
  - 单元测试：`uv run pytest tests/unit` 25 passed in 4.19s
  - 合成基准集成测试：`uv run pytest tests/integration/test_raster_synthetic_benchmark.py` 1 passed in 14.91s（形状召回率 `1.00 >= 0.85`，精确率 `1.00 >= 0.90`，平均 `SSIM >= 0.90`）
  - 真实样图端到端测试：`uv run pytest tests/e2e` 2 passed（`01-ai-beginner-workflow.jpg` 生成 80 个独立可编辑元素：41 个原生文本框 + 22 个原生几何形状 + 17 个带透明通道的独立插图图层，PowerPoint 渲染图像经肉眼与指标双重核验无阴影伪影、无底层重影）
  - 静态检查：`uv run ruff check . && uv run ruff format --check . && uv run pyright` 0 errors, 0 warnings
