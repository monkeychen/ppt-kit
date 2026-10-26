---
doc: spec
product: v0.2.0
milestone: m2
date: 2026-10-26
status: approved
---

# spec-v0.2.0-m2：表格 IR 数据模型与 PPTX 生成闭环

> 本文档针对 [PRD-v0.2.0.md](../prd/PRD-v0.2.0.md) 中规划的 **M2：表格 IR 模型与 PPTX 生成闭环** 进行详细技术方案设计。
> 遵循「打分尺先行」原则，先在中间表示（IR）与 PPTX 生成端将原生 Table 的结构表达与属性写入打通，建立高精度的标准答案验证闭环。

---

## 1. 本里程碑目标与覆盖的 F/AC

### 1.1 核心目标
1. **统一表格中间表示（IR）**：扩展 `SlideIR`，使之具备表达规整表格、合并单元格、单元格文字多样式、背景填充及四周边框的能力。
2. **原生 PPTX Table 写入器**：在 `pptx_writer.py` 中根据 `TableElement` 生成原生 PowerPoint `Table` 形状，确保边距规整、字号对齐、颜色无误。
3. **合成表格标准答案闭环**：通过代码生成带有标准结构与样式的 Table IR，渲染生成 `.pptx` 并反向验证其几何坐标、单元格文本、样式和表格属性无损。

### 1.2 覆盖的 F/AC 清单
- **AC12.1**：在 Slide IR 中定义 `TableElement`，具备 `rows: int`、`cols: int`、`col_widths: list[int]`（EMU）、`row_heights: list[int]`（EMU）、`cells: list[list[TableCell]]`。
- **AC12.4**：`pptx_writer.py` 能够根据 `TableElement` 生成 PowerPoint 原生 `Table` 形状，正确应用单元格文本、字号、颜色、粗体、水平/垂直对齐、背景填充色及边框线宽与颜色，并将单元格内部默认 margin 归零或收敛，防止文本因额外内边距换行错位。

---

## 2. 关键功能设计思路

### 2.1 表格 IR 数据模型设计
- 表格由行、列网格组织：
  - `TableElement` 继承自 `BaseElement`，`kind="table"`。
  - 拥有总宽度 `bbox.width`、总高度 `bbox.height`，以及各列宽度 `col_widths_emu` 和各行高度 `row_heights_emu`。
  - 列宽之和严格校验等于 `bbox.width`（容差 <= 2 EMU），行高之和严格校验等于 `bbox.height`。
- 单元格 `TableCell`：
  - 包含文字段落 `paragraphs: list[Paragraph]`，无缝复用现有 `Paragraph` / `TextRun` / `TextStyle` 模型。
  - 包含对齐方式：`align`（水平对齐）与 `vertical_align`（垂直居顶/居中/居底）。
  - 包含背景底色：`fill_color_hex`（如表头 `#2563EB`，斑马纹 `#F8FAFC`）。
  - 包含四周边框 `border_left`, `border_right`, `border_top`, `border_bottom`，每个边框包含 `color_hex` 与 `width_emu`。
  - 包含跨行跨列：`row_span: int = 1`, `col_span: int = 1`。

### 2.2 PPTX 原生表格写入器与排版优化
PowerPoint 默认的 Table 形状具有若干在自动生成时极易导致文字错位的默认行为：
1. **默认内边距陷阱**：
   - PowerPoint 单元格默认具有 `margin_left = 91440 EMU` (0.1 inch / 7.2pt)，左右各 0.1 inch 会吃掉 14.4pt 宽度，导致原本在图片里刚好一行的文字被迫换行，表格被撑高变形。
   - **方案**：`TableCell` 默认将 `margin_left`, `margin_right`, `margin_top`, `margin_bottom` 全部设为 0（或仅保留极小 1~2pt 呼吸间距），消灭不必要的强行换行。
2. **垂直对齐支持**：
   - 将 `vertical_align` 映射到 python-pptx 的 `MSO_ANCHOR`：`top -> MSO_ANCHOR.TOP`, `middle -> MSO_ANCHOR.MIDDLE`, `bottom -> MSO_ANCHOR.BOTTOM`。
3. **DrawingML 边框注入**：
   - python-pptx 没有直接暴露高层边框 API。我们通过操作底层 DrawingML 元素 `cell._tc.get_or_add_tcPr()`，为 `lnL`, `lnR`, `lnT`, `lnB` 注入 `<a:solidFill><a:srgbClr val="..."/></a:solidFill>` 与 `w="..."`，生成干净的原生矢量边框。
4. **单元格合并（Spans）**：
   - 若 `row_span > 1` 或 `col_span > 1`，调用 python-pptx 的 `table.cell(r, c).merge(table.cell(r + row_span - 1, c + col_span - 1))`。

### 2.3 数据流图

```
+--------------------------------------------------------------+
|                        SlideIR                               |
| elements: [ ..., TableElement, ... ]                         |
+------------------------------+-------------------------------+
                               |
                               v
+--------------------------------------------------------------+
| pptkit/writer/pptx_writer.py: _add_table()                   |
| 1. slide.shapes.add_table(rows, cols, left, top, w, h)       |
| 2. 设置 table.columns[c].width & table.rows[r].height        |
| 3. 清零单元格默认 margin (0 EMU)                             |
| 4. 填充 paragraphs (TextRun, TextStyle, font, color, CJK ea) |
| 5. 设置 cell.fill (solid / background)                       |
| 6. 底层注入 tcPr.lnL / lnR / lnT / lnB 边框线宽与颜色        |
| 7. 执行单元格 merge                                          |
+------------------------------+-------------------------------+
                               |
                               v
+--------------------------------------------------------------+
|                 PowerPoint 原生可编辑 Table                  |
| (用户可自由增删行列、调整列宽、修改文字、复制粘贴为 Excel 表格)  |
+--------------------------------------------------------------+
```

---

## 3. 数据模型定义

在 `src/pptkit/ir/models.py` 中新增模型：

```python
class CellBorder(BaseModel):
    color_hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    width_emu: StrictInt = Field(default=12700, ge=0)  # 默认 1pt = 12700 EMU


class TableCell(BaseModel):
    row: StrictInt = Field(ge=0)
    col: StrictInt = Field(ge=0)
    row_span: StrictInt = Field(default=1, ge=1)
    col_span: StrictInt = Field(default=1, ge=1)
    paragraphs: list[Paragraph] = Field(default_factory=list)
    fill_color_hex: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    border_left: CellBorder | None = None
    border_right: CellBorder | None = None
    border_top: CellBorder | None = None
    border_bottom: CellBorder | None = None
    margin_left_emu: StrictInt = 0
    margin_right_emu: StrictInt = 0
    margin_top_emu: StrictInt = 0
    margin_bottom_emu: StrictInt = 0
    vertical_align: Literal["top", "middle", "bottom"] = "middle"


class TableElement(BaseElement):
    kind: Literal["table"] = "table"
    rows: StrictInt = Field(gt=0)
    cols: StrictInt = Field(gt=0)
    col_widths_emu: list[StrictInt] = Field(min_length=1)
    row_heights_emu: list[StrictInt] = Field(min_length=1)
    cells: list[list[TableCell]] = Field(min_length=1)


SlideElement = Annotated[
    TextBoxElement | ShapeElement | ImageElement | TableElement,
    Field(discriminator="kind"),
]
```

---

## 4. 关键决策记录

| 编号 | 决策项 | 选择与理由 | 放弃方案与代价 |
|---|---|---|---|
| **D8** | 单元格内边距策略 | **默认清零（0 EMU）**：PPT 默认各方向内边距大，极易造成生成后文本被挤压换行 | 放弃「使用 PPT 默认 0.1 inch 内边距」。放弃代价是原本在图片中刚好横排的词语会被断成多行，导致行高变形。 |
| **D9** | 边框实现机制 | **OpenXML 底层注入 `tcPr` 的 `lnL/lnR/lnT/lnB`**：纯净原生，支持每个单元格自定义独立四周边框 | 放弃「通过叠放原生 Line 形状模拟表格边框」。叠放线会导致用户在拖动表格时边框滞留在原地，失去表格作为一个整体的可编辑性。 |
| **D10** | 表格单元格二维矩阵结构 | **`cells: list[list[TableCell]]` 显式二维数组**：直观对应 $R \times C$，索引 `[r][c]` 寻址复杂度 $O(1)$ | 放弃「扁平一维列表 `cells: list[TableCell]`」。一维列表容易在发生跨行跨列时造成行列对应歧义，增加算法复杂度。 |

---

## 5. 测试策略

### 5.1 单元测试清单（`tests/unit/`）

| 测试文件 | 测试函数 | 覆盖 AC | 验证内容 |
|---|---|---|---|
| `test_table_ir.py` | `test_table_element_validation` | AC12.1 | 验证 `TableElement` 与 `TableCell` 的字段校验、Pydantic 序列化与反序列化 |
| `test_table_ir.py` | `test_slide_ir_polymorphism_with_table` | AC12.1 | 验证 `SlideIR.elements` 正确包含 `TableElement` 多态解析与 roundtrip |
| `test_table_writer.py` | `test_write_pptx_creates_native_table_shape` | AC12.4 | 验证生成的 PPTX 中包含原生 `Table` 形状，行列数与尺寸匹配 |
| `test_table_writer.py` | `test_table_cell_styles_and_borders_applied` | AC12.4 | 验证单元格文本、粗体、字号、底色、垂直对齐及 DrawingML 边框属性精确写入 |
| `test_table_writer.py` | `test_table_cell_spans_merge` | AC12.4 | 验证具备 `col_span > 1` 或 `row_span > 1` 的单元格正确调用 merge |

### 5.2 综合与基准测试

| 测试文件 | 验证内容 | 覆盖 AC |
|---|---|---|
| `test_synthetic.py` | 增加包含表格的合成幻灯片生成用例，验证生成的幻灯片能够正常被解析和渲染 | AC12.1, AC12.4 |
| 全量回归测试 | 确保既有 37 个单元测试 + 4 个 E2E 测试全部持续通过 | 全部既有功能 |

---

## 6. Task 拆分

| 编号 | 内容 | 覆盖 AC | 依赖 | 状态 |
|---|---|---|---|---|
| **T1** | 在 `src/pptkit/ir/models.py` 中定义 `CellBorder`, `TableCell`, `TableElement` 并集成入 `SlideElement`；编写 `tests/unit/test_table_ir.py` | AC12.1 | - | completed |
| **T2** | 在 `src/pptkit/writer/pptx_writer.py` 中实现 `_add_table` 及其子逻辑（单元格文本、样式、边距清零、垂直对齐、底色、DrawingML 边框、单元格合并）；编写 `tests/unit/test_table_writer.py` | AC12.4 | T1 | completed |
| **T3** | 在 `benchmark/synthetic/generator.py` 中增加包含规整表格的合成幻灯片生成器，跑通合成基准与全量回归测试 | AC12.1, AC12.4 | T1, T2 | completed |
| **T4** | 代码格式化、Lint 与类型检查（ruff, pyright），执行全量单元与 E2E 测试，撰写 M2 验收记录并提交 Git Commit | 全部本里程碑 AC | T1, T2, T3 | completed |

---

## 7. 界面与 F/AC 映射

本里程碑为数据模型与 PPTX 文件写入器，不涉及前端 GUI，无需 HTML 原型。

---

## 8. 验收记录

### 验收时间：2026-10-26
- **代码质检**：
  - `uv run ruff check .`：通过（0 errors）。
  - `uv run ruff format --check .`：通过。
  - `uv run pyright`：通过（0 errors, 0 warnings）。
- **单元测试与覆盖**：
  - `uv run pytest tests/unit`：43 passed, 0 failed（新增 `test_table_ir.py`, `test_table_writer.py`, `test_synthetic.py` 表格生成与合并校验）。
- **端到端测试**：
  - `uv run pytest tests/e2e`：4 passed, 0 failed。
- **架构规约**：
  - 严格遵守 `units.py` 唯一换算中心规约，使用 `EMU_PER_PT` 替代魔法数字。
- **验收结论**：**通过**，M2 表格 IR 模型与 PPTX 生成闭环交付完毕。

