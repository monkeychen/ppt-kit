---
doc: spec
product: pptkit
milestone: m2
date: 2026-10-29
status: approved
---

# Spec-v0.3.1-M2：双母版体系反推与全局排版阶梯规约

> 覆盖需求：**F33、F34**  
> 核心目标：解决 10 页以上真实复杂幻灯片中「每页重复保存数兆底图导致 PPTX 臃肿」以及「字号色彩微小浮动噪点导致版面不工整」两大痛点，实现自动提取封面/内页双母版模板与全局字体/调色板阶梯量化规约。

---

## 1. 里程碑目标与覆盖清单

| 需求编号 | 功能名称 | 对应验收标准 (AC) | 涉及模块 |
|---|---|---|---|
| **F33** | 幻灯片双母版体系自动反推 (Slide Master Induction) | **AC33.1, AC33.2, AC33.3** | `src/pptkit/raster/master.py`<br>`src/pptkit/writer/pptx_writer.py` |
| **F34** | 全局排版阶梯规约与调色板收敛 (Typography & Palette Quantization) | **AC34.1, AC34.2** | `src/pptkit/raster/refiner.py`<br>`src/pptkit/common/color.py` |

---

## 2. 关键功能设计思路

### 2.1 F33: 幻灯片多模板/母版体系自动反推

#### 问题本质
- 在 10 页真实幻灯片转换中，当前流水线为每一页都独立输出一张 `slide_xxx_bg.png`（每张约 1.5MB~2.5MB），导致 10 页 PPTX 体积超过 18MB；
- 实际上，整份演示文稿通常只包含两类版式：
  1. **封面/封底（Title / Closing Slide）**：大标题居中、暗色或全幅艺术底图、无栏目顶条；
  2. **正文内容页（Content Slide）**：通用的顶部栏目色条（如蓝色渐变顶栏）、右上角 Logo、底部灰色页脚与页码。

#### 反推算法设计
1. **背景图像相似度聚类与母版识别**：
   - 提取所有页面的 `cleaned_bg_image`，计算页面间的结构相似度（SSIM / 感知哈希 pHash）；
   - 聚类为两类模版：`title_master`（封面，通常为第 1 页或独特背景）与 `content_master`（内页公共背景，占据多数页面）；
   - 对 `content_master`，将多页共有底图提取公共均值或中位数背景图，生成单张底图 `master_content_bg.png`；
2. **跨页公共固定元素提取（版头/版尾/Logo）**：
   - 比对所有正文页的 `SlideElement` 空间位置与视觉特征：
     - **顶部栏目条/标题色带**：所有正文页同 Y 坐标、同高、同色的 `ShapeElement`；
     - **Logo / 徽标**：右上角或左上角尺寸与位置高度一致的 `ImageElement`；
     - **底部信息**：页脚版权文字、密级标识等；
   - 将公共固定元素提取至母版/版式层，正文页仅保留其自身特有的卡片、图表与正文，避免重复。
3. **输出 PPTX 瘦身优化**：
   - `python-pptx` 写入时，所有引用 `content_master` 的幻灯片共享同一个底图资源实体，10 页 PPTX 体积从 18MB 压缩至 3MB 以内（压缩率 80%+）。

---

### 2.2 F34: 全局排版阶梯规约与调色板收敛

#### 问题本质
- OCR 与字号估计在各个文本框计算时，由于笔画反走样像素微小差别，原本设计上完全相同的同级标题可能被估算为 `19.5pt`、`20.0pt`、`20.5pt`；
- 原本相同的主题蓝色在不同页面的轻微光影影响下可能被采样为 `#0052D9`、`#0055DA`、`#0153D8`，导致 PowerPoint 中调色板凌乱、难以一键换色。

#### 阶梯规约机制
1. **字号阶梯量化（Typography Ladder Quantization）**：
   - 收集整套幻灯片所有文本框的 `font_size_pt`，构建字号分布直方图；
   - 设定业务常用字号标准阶梯：`[44, 36, 32, 28, 24, 20, 18, 16, 14, 12, 10.5, 9]`；
   - 将邻近字号（绝对差距 `|est_pt - ladder_pt| <= 1.5pt`）自动对齐锚定至标准阶梯，消除微小浮动噪点。
2. **调色板聚合收敛（Color Palette Clustering）**：
   - 将整份演示文稿出现的所有十六进制颜色转为 CIELAB 色彩空间；
   - 计算色差 $\Delta E$。对于 $\Delta E \le 3.5$ 的相近颜色组，计算其中位数/主导颜色作为规约代表色；
   - 统一替换整份 PPTX 中的 `fill_color_hex`、`stroke_color_hex` 与 `TextRun.style.color_hex`，使全局配色严格收敛在 5~7 种核心调色板内。

---

## 3. 接口与数据模型变更

### 3.1 扩展 `src/pptkit/ir/models.py`
在 `SlideIR` 或 `PresentationIR` 中支持母版模板引用：
```python
class SlideMaster(BaseModel):
    id: str
    kind: Literal["title", "content"] = "content"
    background: Background
    static_elements: list[SlideElement] = Field(default_factory=list)


class PresentationIR(BaseModel):
    ...
    masters: list[SlideMaster] = Field(default_factory=list)
```

### 3.2 新增 `src/pptkit/raster/master.py`
```python
def induct_slide_masters(
    slides: list[SlideIR],
    similarity_threshold: float = 0.88,
) -> tuple[list[SlideMaster], list[SlideIR]]:
    """Cluster multi-slide backgrounds into title/content masters and extract common elements."""
```

### 3.3 新增 `src/pptkit/raster/quantize.py`
```python
def quantize_presentation_typography(
    presentation: PresentationIR,
    standard_ladders: list[float] | None = None,
) -> PresentationIR:
    """Quantize font sizes and unify palette across presentation."""
```

---

## 4. 单元测试用例设计

| 测试函数名 | 覆盖 AC | 测试条件与预期结果 |
|---|---|---|
| `test_slide_master_clustering_title_and_content` | **AC33.1** | 输入 1 张封面（独特底图）和 3 张相同内页底图，断言自动聚类出 2 个母版（title 与 content）。 |
| `test_extract_static_header_elements_to_master` | **AC33.2** | 3 张正文页在相同坐标均有顶部导航条与 Logo，断言导航条与 Logo 被提升至母版，正文页移除非特异性元素。 |
| `test_quantize_font_size_ladder` | **AC34.1** | 输入字号 `[19.5, 20.2, 23.8, 14.3]`，断言分别被规约对齐到 `[20.0, 20.0, 24.0, 14.0]`。 |
| `test_quantize_color_palette_clustering` | **AC34.2** | 输入微小色差 `#0052D9`, `#0053DA`, `#0152D8`，断言被聚合收敛为单一主导色 `#0052D9`。 |

---

## 5. Task 拆分

| Task 编号 | 任务内容 | 覆盖 AC | 依赖 | 状态 |
|---|---|---|---|---|
| T1 | 字号阶梯量化与调色板收敛器（`quantize.py`） | AC34.1, AC34.2 | 无 | ✅ Done（`test_quantize.py` 3/3 passed） |
| T2 | 双母版底图聚类与跨页公共固定元素提取（`master.py`） | AC33.1, AC33.2 | 无 | ✅ Done（`test_master.py` 2/2 passed） |
| T3 | PPTX Writer 母版共享注入与瘦身机制 | AC33.3 | T1, T2 | Pending |
| T4 | 端到端 10 页 PPT 基准测试与验证 | AC33.1~AC34.2 | T3 | Pending |
