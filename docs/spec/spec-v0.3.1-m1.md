---
doc: spec
product: pptkit
milestone: m1
date: 2026-10-29
status: approved
---

# Spec-v0.3.1-M1：底层物理清洗与卡片语义流式成组

> 覆盖需求：**F28、F29、F30、F31、F32**  
> 核心目标：解决幻灯片逆向中的“碎片化拼贴”与“点击地狱”，实现卡片内多段落流式排版、杂散碎图片聚类与下限过滤、图标单字噪点抑制、大卡片几何防误判以及标题装饰前缀净化。

---

## 1. 里程碑目标与覆盖清单

| 需求编号 | 功能名称 | 对应验收标准 (AC) | 涉及模块 |
|---|---|---|---|
| **F28** | 图标内伪单字符智能抑制与过滤 | **AC28.1, AC28.2, AC28.3** | `src/pptkit/raster/layers.py`<br>`src/pptkit/raster/pipeline.py` |
| **F29** | 大容器矩形卡片防误判机制 | **AC29.1, AC29.2** | `src/pptkit/raster/shapes.py` |
| **F30** | 标题前导装饰符号与端点标点智能净化 | **AC30.1, AC30.2** | `src/pptkit/raster/text_style.py` |
| **F31** | 卡片语义流式成组 (Card Grouping) | **AC31.1, AC31.2, AC31.3** | `src/pptkit/raster/pipeline.py` |
| **F32** | 碎图聚类与下限过滤 (Picture Clustering) | **AC32.1, AC32.2, AC32.3** | `src/pptkit/raster/layers.py` |

---

## 2. 关键功能设计思路

### 2.1 F28: 图标内伪单字符抑制与过滤

- **触发条件**：
  OCR 检出的候选文本框中，字符长度为 1（去除空白后），且其包围盒落入某个高对比度圆形图标或独立 `ImageElement` 的有效区域内部（交并比 IoU 或相交面积占文本框面积比例 `> 0.60`）。
- **判定与过滤机制**：
  1. **大号序号保护（负向放行）**：若该单字为数字（`0~9`）或英文字母（`A~Z`），且其字号 `font_size_pt >= 22.0`（如步骤序号 `①`、大标号 `1`），判定为合法文本，保留。
  2. **中文字符与标点过滤（正向命中）**：若单字符为常见残影符（如 `¢`, `目`, `园`, `的`, `G`, `口`, `□`, `O`, `o` 等），且所在区域具有明显的图标底色或复杂纹理，从最终文本框清单中彻底抹除。
  3. **背景抹平保护**：被抑制的单字区域不再对其执行强力羽化擦除，保留原生图标切片的完整视觉。

### 2.2 F29: 大容器矩形卡片防误判机制

- **问题本质**：
  在 `src/pptkit/raster/shapes.py` 的 `classify_shape` 中，检测到某些外接轮廓带有局部的微小突出或右侧与连线触点粘连，其多边形拟合满足了简化的 `right_arrow` 轮廓特征，导致正常的横向大卡片被判定为箭头。
- **几何特征防御**：
  1. 计算轮廓外接矩形的长宽比 `aspect_ratio = w / h`。
  2. 计算轮廓面积占外接矩形面积的填充率 `fill_ratio = contour_area / (w * h)`。
  3. **防误判规则**：
     - 若 `w > 300` 且 `aspect_ratio > 2.0` 且 `fill_ratio > 0.82`：对于真正的右箭头，由于箭尾和收缩段的存在，其矩形填充率通常 `< 0.65`。一旦 `fill_ratio > 0.82`，表明其四边绝大部分都是规整的水平和竖直线条，强制将其归类为 `round_rect`（若角点检测有圆角）或 `rect`，严禁判定为 `right_arrow`。

### 2.3 F30: 标题前导装饰符号与端点标点智能净化

- **前导标点规则**：
  - 在 `clean_ocr_boxes` 和 `estimate_text_runs` 中，针对文本首部进行正则扫描：
    `CLEAN_LEADING_RE = re.compile(r'^[|•■▪·]\s*')`
  - 若文本以竖线 `|`、实心圆点 `•`、方块 `■` 等非文字符号起始，且紧随中英文字符，直接安全剥离该前置符号与空格。
- **末尾标点规则**：
  - 针对短标题/卡片名称（长度 `< 25` 字符且不含谓语成分），若末尾为孤立句号（如 `XX事业部。`），剥离末尾句号。
- **样式保持**：
  - 仅清洗 `run.text` 字符串内容，其对应 `TextStyle` 中的字体、字号、颜色完全继承保留。

### 2.4 F31: 卡片语义流式成组 (Card Grouping)

- **数据流与架构**：
  ```
  原始分离元素 (ShapeElement + 多个离散 TextBoxElement)
          │
          ▼
  空间拓扑索引：按 ShapeElement 几何包围盒作为 Container
          │
          ▼
  卡片内文本聚合器 (Card Text Aggregator)：
  - 筛选落入 Container 内部且在几何上垂直居于同列的 TextBox
  - 按 Y 坐标从上至下排序
  - 将多个单个文本框合并为一个 TextBoxElement(paragraphs=[p1, p2, ...])
  - 合并文本框外接矩形 = 所有段落的联合外包围盒
          │
          ▼
  输出：PPTX 中单一原生文本框，支持自动流式换行与整体拖动
  ```
- **换行与间距维护**：
  - 每个段落 `Paragraph` 保留自身 runs 的原样字体大小与颜色；
  - 上下段落之间根据它们原本的 Y 轴间隙估算 `space_after_pt`（段后距），确保在合并后视觉位置与原图 100% 保持一致，但逻辑上变为单一流动文本框。

### 2.5 F32: 碎图聚类与下限过滤 (Picture Clustering)

- **过滤门限**：
  - 在 `extract_image_layers` 中，设置图片元素有效尺寸下限：
    `MIN_IMAGE_SIDE = 20` 像素；`MIN_IMAGE_AREA = 400` 平方像素。
  - 短边 `< 20px` 且面积 `< 400px²` 的孤立连通块（通常为噪点、线头断点或杂散白边），直接过滤，不生成 `ImageElement`。
- **插画聚类联合**：
  - 对空间距离 `< 12px` 且不在同一个文字行区域的相邻图像碎片，执行 `Bounding Union` 聚类合并，保证 3D 立体插图为一个完整的矩形切片，杜绝一张插画切成 3 个碎片的问题。

---

## 3. 接口与数据模型

### 3.1 扩展 `src/pptkit/raster/shapes.py`
```python
def classify_shape_contour(
    cnt: np.ndarray,
    approx: np.ndarray,
    rect: tuple[int, int, int, int],
) -> Literal["rect", "round_rect", "ellipse", "line", "right_arrow", "freeform"]:
    """Classify geometric contour with aspect-ratio guard for card containers."""
```

### 3.2 扩展 `src/pptkit/raster/layers.py`
```python
def filter_and_cluster_image_elements(
    images: list[ImageElement],
    min_side_px: int = 20,
    min_area_px: int = 400,
    cluster_gap_px: int = 12,
) -> list[ImageElement]:
    """Filter out noise micro-images and cluster adjacent fragmented illustration parts."""
```

### 3.3 扩展 `src/pptkit/raster/pipeline.py`
```python
def group_card_text_boxes(
    shapes: list[ShapeElement],
    text_boxes: list[TextBoxElement],
    images: list[ImageElement],
) -> tuple[list[TextBoxElement], list[TextBoxElement]]:
    """Group intra-card discrete textboxes into multi-paragraph flowing textboxes,
    and suppress isolated pseudo-characters inside icon/image bounds."""
```

---

## 4. 单元测试用例设计

| 测试函数名 | 覆盖 AC | 测试条件与预期结果 |
|---|---|---|
| `test_filter_icon_pseudo_character_suppressed` | **AC28.1, AC28.3** | 构造一个位于图标切片中心的小单字符 `¢`，断言被识别为图标伪字符并过滤，不生成 TextBox。 |
| `test_filter_large_number_not_suppressed` | **AC28.2** | 构造一个大字号大标号 `1`（字号 28pt），即使落入色块内部，依然正常保留。 |
| `test_classify_horizontal_card_defends_against_right_arrow` | **AC29.1, AC29.2** | 构造长宽比 4.0、填充率 0.88 的横向圆角矩形轮廓，断言识别为 `round_rect`，绝不输出 `right_arrow`。 |
| `test_clean_title_leading_and_trailing_punctuation` | **AC30.1, AC30.2** | 输入 `| 前期基础与团队优势` 和 `XX集团有限公司XX事业部。`，断言清洗为 `前期基础与团队优势` 和 `XX集团有限公司XX事业部`，且字号字色不变。 |
| `test_card_grouping_merges_vertical_paragraphs` | **AC31.1, AC31.2, AC31.3** | 构造一个卡片矩形内部垂直排列的 3 个独立单行文本框，断言合并为 1 个包含 3 个 `Paragraph` 的 `TextBoxElement`。 |
| `test_picture_clustering_and_micro_debris_filtering` | **AC32.1, AC32.2** | 构造 10px 孤立碎图与两个相邻的 3D 插画切片，断言孤立碎图被滤除，相邻切片被联合合并为 1 张完整图片。 |

---

## 5. 依赖与风险评估

- **性能影响**：所有聚类与几何校验均为 $O(N)$（$N \le 100$）的向量几何判定，单页增加耗时 `< 5ms`，完全可忽略。
- **向后兼容**：生成的仍然是标准 `SlideIR`，不需要更改 IR 模型，下层 PPTX Writer 无缝支持多段落与聚类图片。

---

## 6. Task 拆分与执行状态

| Task 编号 | 任务内容 | 覆盖 AC | 状态 | 验证证据 |
|---|---|---|---|---|
| T1 | 标题装饰前导与端点标点清洗（`clean_title_punctuation`） | AC30.1, AC30.2 | ✅ Done | `test_clean_title_leading_and_trailing_punctuation` 通过 |
| T2 | 大容器矩形卡片长宽比防御（`classify_contour_shape`） | AC29.1, AC29.2 | ✅ Done | `test_classify_horizontal_card_defends_against_right_arrow` 通过 |
| T3 | 碎图聚类与下限过滤（`filter_and_cluster_image_elements`） | AC32.1, AC32.2, AC32.3 | ✅ Done | `test_picture_clustering_and_micro_debris_filtering` 通过 |
| T4 | 图标内单字噪点抑制（`suppress_icon_pseudo_characters`） | AC28.1, AC28.2, AC28.3 | ✅ Done | `test_filter_icon_pseudo_character_suppressed`, `test_filter_large_number_not_suppressed` 通过 |
| T5 | 卡片多段落流式成组（`group_card_text_boxes`） | AC31.1, AC31.2, AC31.3 | ✅ Done | `test_card_grouping_merges_vertical_paragraphs` 通过 |

---

## 7. 验收记录

- **验收时间**：2026-10-29
- **验收环境**：macOS (Darwin 24.3.0), Python 3.12.12
- **自动化测试执行**：
  1. `uv run pytest tests/unit/test_clean_and_grouping.py` -> 6 passed (100%)
  2. `uv run pytest tests/unit` -> 69 passed (100%)
  3. `uv run ruff check . && uv run ruff format --check .` -> All checks passed, 113 files already formatted
  4. `uv run pyright` -> 0 errors, 0 warnings, 0 informations
- **验收结论**：M1 覆盖之需求 F28、F29、F30、F31、F32 均全绿通过自动化校验，无遗留问题。
