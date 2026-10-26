---
doc: spec
product: v0.2.0
milestone: m3
date: 2026-10-26
status: approved
---

# spec-v0.2.0-m3：表格逆向推断与背景修复

> 本文档针对 [PRD-v0.2.0.md](../prd/PRD-v0.2.0.md) 中规划的 **M3：表格逆向推断与背景修复（v0.2.0 收官里程碑）** 进行详细技术方案设计。
> 依托 M1 跨平台 OCR 基础设施与 M2 原生 Table 生成能力，攻克位图幻灯片中网格拓扑分析、文字行列聚类归属与表格背景彻底抹平算法，实现原生可编辑表格的全自动逆向还原与安全降级。

---

## 1. 本里程碑目标与覆盖的 F/AC

### 1.1 核心目标
1. **表格网格线与拓扑分析**：通过形态学水平/垂直核与边缘轮廓检测，从文字抹除后的位图中提取表格外边界及内部行列拓扑（Rows $\times$ Cols）。
2. **单元格内容分配与样式提取**：将表格区域内的 OCR 文本行按几何质心聚类至各单元格 $(r, c)$，同一单元格内多行文本自动合并为段落，提取表头底色与斑马纹。
3. **底图表格彻底擦除**：在背景位图中彻底抹平表格网格线、底色与文字笔画，避免 PPTX 渲染后在单元格边框缝隙处产生重影。
4. **低置信度降级保护**：当网格不闭合、行列表达紊乱或置信度 $< 0.70$ 时，安全降级为 `ImageElement(degraded=True)`，绝不生成错位错乱表格。
5. **质量报告与度量呈现**：在 `report.json` 中完整记录 `tables_count` 与 `table_cells_count`。

### 1.2 覆盖的 F/AC 清单
- **AC12.2**：实现表格网格线与拓扑分析算法：通过水平/垂直形态学核或边缘连接检测表格边框与内外网格线，识别表格外边界（BBox）与内部行列拓扑结构（Rows $\times$ Cols）。
- **AC12.3**：实现单元格内容分配算法：将表格区域内的 OCR 文本行根据其几何中心分配至对应的单元格 $(r, c)$；同一单元格内的多行文本按垂直顺序合并为单单元格内的段落。
- **AC12.5**：实现表格底图擦除：在提取出 `TableElement` 后，将底层背景位图中的表格边框线、斑马纹底色与文字笔画彻底抹平（使用局部背景中位数颜色修复），避免生成 PPTX 后在表格缝隙处透出原图表格重影。
- **AC12.6**：降级保护策略：当表格检测置信度不足（网格不闭合、文字跨越紊乱）或无法明确推断拓扑时，将表格区域降级为普通 `ImageElement(degraded=True)` 抠图层，并在报告中告警，绝不生成错乱错位的乱码表格（“宁可退化，不可错乱”）。
- **AC13.1**：`report.json` 中记录表格识别信息：`tables_count`, `table_cells_count`，若存在结构置信度不足的复杂表格，安全降级为 `ImageElement(degraded=True)` 并计入报告。

---

## 2. 关键功能设计思路

### 2.1 拓扑分析与网格线检测（先文字抹除，再检线）
在原始图像上，文本笔画与表格网格线会相互穿插交叉，直接检测直线容易造成断线或虚假交点。
因此，表格检测的最佳时机是 **在 `inpaint_text_regions` 抹除文字之后** 执行：
1. **二值化与形态学核提取**：
   - 将 `text_cleaned_img` 转为灰度并提取局部对比度边缘。
   - 水平形态学核（宽 $L_h \ge 50\text{px}$，高 $1\text{px}$）提取水平网格分割线。
   - 垂直形态学核（高 $L_v \ge 30\text{px}$，宽 $1\text{px}$）提取垂直网格分割线。
   - 若无纵向垂直线（现代幻灯片常见“无竖线横纹表”），利用水平分隔线构筑行带（Row Bands），通过内部 OCR 文本框的水平左边界/质心分布聚类推断列边界。
2. **外框与网格判定**：
   - 提取表格连通外包围矩形 $[X_t, Y_t, W_t, H_t]$。
   - 筛选门限：宽度 $\ge 0.25 \times \text{Slide Width}$，高度 $\ge 0.10 \times \text{Slide Height}$，行数 $\ge 2$，列数 $\ge 2$。

### 2.2 单元格内容聚类与段落合并
1. **质心落入判定**：
   - 遍历 `cleaned_boxes` 中的 OCR 文本框。
   - 计算文本框中心点 $(cx, cy) = (x + w/2, y + h/2)$。
   - 若 $(cx, cy)$ 落在单元格 $(r, c)$ 的 $[x_{c-1}, x_c) \times [y_{r-1}, y_r)$ 矩形内，则归属于该单元格。
   - 记录已归属文本框的索引 `used_box_indices`，**在后续生成顶层 `TextBoxElement` 时跳过这些文本框**，避免在 PPTX 中表格上方叠加重复文本！
2. **多行合并**：
   - 单元格内若包含多行文字（如标题较长折成两行，或有主标题和副标题），按纵坐标 $y$ 升序排列。
   - 使用 `estimate_text_runs` 生成段落，放入 `TableCell.paragraphs`。
3. **单元格底色与对齐推断**：
   - 在 `text_cleaned_img` 中对该单元格区域内采样中位数颜色。若与全局背景色色差 $\Delta E \ge 12.0$，设为单元格 `fill_color_hex`（精准还原表头强调色或奇偶斑马纹）。
   - 根据文本框左坐标相对于单元格左侧的留白推断水平对齐（左对齐 / 居中对齐）。

### 2.3 表格底图彻底抹平与背景修复
1. 提取出 `TableElement` 后，在背景图像 `cleaned_image` 中将整个表格矩形区域 $[Y_t:Y_t+H_t, X_t:X_t+W_t]$ 标记为擦除掩码。
2. 使用表格外围邻域（上、下、左、右各外扩 8px 环形区域）采样的幻灯片背景基准颜色填充抹平。
3. 这样，`slide_000_bg.png` 上绝不残留原本的网格黑线、色块或残余斑马纹，PPTX 原生表格覆在其上时无任何像素重影。

### 2.4 降级保护策略（“宁可退化，不可错乱”）
- 表格置信度评分 $C_{table}$ 结合三个维度：
  1. 网格规整度：各行高、各列宽方差是否在合理排版范围；
  2. 内容覆盖度：具有文本内容的有效单元格占比 $\ge 40\%$；
  3. 文本框冲突度：跨越多个单元格边界的歧义文本框占比 $< 20\%$。
- 若 $C_{table} < 0.70$：
  - **不生成** 错位的 `TableElement`。
  - 将表格区域裁切为 `ImageElement(degraded=True)` 独立图片层保留视觉（或退回普通文本框）。
  - 将表格 ID 记入 `low_confidence_elements`，并在报告中标记 `degraded_elements += 1`。

### 2.5 整体架构与流水线集成顺序

```
                   +----------------------------------+
                   |         orig_img (RGB)           |
                   +-----------------+----------------+
                                     |
                                     v
                   +----------------------------------+
                   |  1. OCR 文字识别 (Apple/Rapid)    |
                   +-----------------+----------------+
                                     |
                                     v
                   +----------------------------------+
                   |  2. inpaint 文字笔画抹除          |
                   +-----------------+----------------+
                                     | (text_cleaned_img)
                                     v
                   +----------------------------------+
                   |  3. extract_raster_tables()      | <--- 本里程碑核心
                   |     - 形态学网格线提取            |
                   |     - 拓扑矩阵与单元格划分        |
                   |     - OCR 文本归入单元格          |
                   |     - 擦除底图表格区域            |
                   |     - 记录 used_box_indices      |
                   +-----------------+----------------+
                                     | (table_cleaned_img, tables)
                                     v
                   +----------------------------------+
                   |  4. extract_raster_shapes()      | (不受表格线条干扰)
                   +-----------------+----------------+
                                     |
                                     v
                   +----------------------------------+
                   |  5. extract_image_layers()       |
                   +-----------------+----------------+
                                     |
                                     v
                   +----------------------------------+
                   |  6. 组装 SlideIR                 |
                   |     - elements.extend(tables)    |
                   |     - elements.extend(shapes)    |
                   |     - 仅对 unused_boxes 生成文本框 |
                   +----------------------------------+
```

---

## 3. 接口与数据模型定义

### 3.1 质量报告模型拓展（`src/pptkit/report/reporter.py`）

```python
class PageQualityReport(BaseModel):
    ...
    tables_count: int = 0
    table_cells_count: int = 0
```

### 3.2 表格提取结果接口（`src/pptkit/raster/table.py`）

```python
@dataclass
class TableExtractionResult:
    tables: list[TableElement]
    used_box_indices: set[int]
    cleaned_image: Image.Image
    degraded_tables: list[ImageElement] = field(default_factory=list)
    low_confidence_ids: list[str] = field(default_factory=list)


def extract_raster_tables(
    text_cleaned_img: Image.Image,
    orig_img: Image.Image,
    ocr_boxes: list[OCRBox],
    slide_width_emu: int,
    slide_height_emu: int,
    page_index: int = 0,
    candidate_fonts: list[str] | None = None,
) -> TableExtractionResult: ...
```

---

## 4. 关键决策记录

| 编号 | 决策项 | 选择与理由 | 放弃方案与代价 |
|---|---|---|---|
| **D11** | 表格检测介入时机 | **在文字抹除（inpaint）之后进行网格线检测**：消除了文字笔画与表格网格线交叉造成的虚假交点和断线干扰 | 放弃「在原图上直接检线」。在原图检线时汉字横竖笔画会被误当成分割线，导致网格过度碎片化。 |
| **D12** | 文本归属判定策略 | **几何质心归属 + 单元格内多行垂直合并**：质心判定对轻微贴边文本鲁棒，同一单元格内合并为同一文本框的多段落 | 放弃「仅当文本框完全落在单元格内部才归属」。完全包含会导致略微溢出格子的字号被遗漏，造成文字浮在表格外。 |
| **D13** | 跨模块图层防重叠机制 | **记录 `used_box_indices` 并在底图抹除表格区域**：表格内的文字被表格吃掉，表格网格被背景抹除 | 放弃「表格与普通文本框独立处理」。不记录消耗索引会导致表格内文字在 PPTX 中被重复生成两遍。 |

---

## 5. 测试策略

### 5.1 单元测试清单（`tests/unit/`）

| 测试文件 | 测试函数 | 覆盖 AC | 验证内容 |
|---|---|---|---|
| `test_raster_table.py` | `test_extract_grid_lines_and_topology` | AC12.2 | 构造合成表格图像（含横竖网格线），验证正确推断出 $R \times C$ 行列数与尺寸 |
| `test_raster_table.py` | `test_assign_ocr_boxes_to_cells_and_merge_multiline` | AC12.3 | 验证文字框准确分配到对应单元格，多行文字正确合并为有序段落 |
| `test_raster_table.py` | `test_table_background_erasure` | AC12.5 | 验证提取表格后，输出底图上的表格线与斑马纹被彻底平滑擦除 |
| `test_raster_table.py` | `test_table_degradation_on_broken_grid` | AC12.6 | 验证当网格严重破碎或缺乏有效内容时，安全降级为普通图层并在报告中告警 |
| `test_report.py` | `test_report_records_table_metrics` | AC13.1 | 验证 `PageQualityReport` 正确序列化与汇总 `tables_count` 和 `table_cells_count` |

### 5.2 综合与回归测试

| 测试文件 | 验证内容 | 覆盖 AC |
|---|---|---|
| `test_refiner.py` & `test_cli.py` | 验证引入表格检测后现有无表格栅格图不被误判，既有 43 个单元测试全部绿灯 | 全部回归功能 |
| 端到端流水线测试 | 生成带表格的位图输入，经 `pptkit convert` 还原为 PPTX，断言包含原生 Table 且无重复文本框 | AC12.2 ~ AC13.1 |

---

## 6. Task 拆分

| 编号 | 内容 | 覆盖 AC | 依赖 | 状态 |
|---|---|---|---|---|
| **T1** | 扩展 `report/reporter.py` 与 `pipeline.py`，支持 `tables_count` 与 `table_cells_count` 字段 | AC13.1 | - | completed |
| **T2** | 实现 `src/pptkit/raster/table.py`（网格线检测、拓扑分析、文本行列分配、背景擦除与降级保护），编写 `tests/unit/test_raster_table.py` | AC12.2, AC12.3, AC12.5, AC12.6 | T1 | completed |
| **T3** | 将 `extract_raster_tables` 贯通至 `src/pptkit/raster/pipeline.py` 与 `cli/app.py`，防范文字框重复并更新质量报告 | 全部本里程碑 AC | T1, T2 | completed |
| **T4** | 代码质检（ruff, pyright, pytest 全量回归），撰写 M3 验收记录，提交 Git Commit，收官 v0.2.0 | 全部本里程碑 AC | T1, T2, T3 | completed |

---

## 7. 界面与 F/AC 映射

本里程碑为后端逆向识别算法，不涉及前端 GUI，无需 HTML 原型。

---

## 8. 验收记录

### 验收时间：2026-10-26
- **代码质检**：
  - `uv run ruff check .`：通过（0 errors）。
  - `uv run ruff format --check .`：通过。
  - `uv run pyright`：通过（0 errors, 0 warnings）。
- **单元测试与覆盖**：
  - `uv run pytest tests/unit`：47 passed, 0 failed（新增 `test_raster_table.py` 4 个用例，覆盖网格线检测、多行合并、背景平滑擦除与断网格安全降级）。
- **端到端测试**：
  - `uv run pytest tests/e2e`：4 passed, 0 failed。
- **功能验收指标（F12 / F13）**：
  - 表格网格拓扑识别准确，单元格文本由几何质心映射并按垂直顺序有序合并为段落；
  - 表格底图被平滑抹平，PPTX 原生表格无底层像素重影；
  - 表格文字框不重复出现在顶层，彻底杜绝元素重复；
  - `report.json` 正确统计并记录 `tables_count` 与 `table_cells_count`。
- **验收结论**：**通过**，M3 表格逆向推断与背景修复交付完毕，**v0.2.0 版本全部 3 个里程碑均已顺利通过验收闭环**。

