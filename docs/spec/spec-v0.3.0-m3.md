---
doc: spec
product: pptkit
version: v0.3.0
milestone: M3
date: 2026-10-27
status: draft
---

# Spec：v0.3.0-M3 前后视觉对比画板与局部差异高亮交互

> 里程碑目标：打造专业生产力级别的多页幻灯片对比工作台，实现多页缩略图导航、百叶窗滑动双图对比、低置信度元素标注图层、差异热力图切换、画板手势缩放与全局快捷键。

---

## 1. 需求与边界对应

| 需求编号 | 需求名称 | 本里程碑范围 (Scope) | 验收标准 (Acceptance Criteria) |
|---|---|---|---|
| **F24** | 视觉对比画板与局部差异高亮交互 | 1. **多页缩略图底栏导航**：支持多页输入，底部渲染每页缩略图与 SSIM 质量胶囊，支持一键翻页切片；<br>2. **低置信度元素标注图层**：提供 `GET /api/report/{id}/elements/{page}` 接口，在重构图上高亮置信度低于阈值的元素边界框，悬浮显示识别详情；<br>3. **差异热力图图层切换**：提供 `GET /api/preview/{id}/heatmap/{page}` 接口，支持原图/重构图/差异热力图自由切换；<br>4. **画板平移缩放 (Pan & Zoom)**：支持画布 50% ~ 200% 缩放与平移，双击重置；<br>5. **键盘快捷键**：支持快捷键快速切图（`1` 对比、`2` 仅 PPTX、`3` 仅原图、`[`/`]` 翻页）。 | **AC24.1**：多页文档转换完成后，缩略图底栏完整展示所有页面，点击任一页能在 200ms 内平滑切页加载双图；<br>**AC24.2**：低置信度（< 0.60 或降级）元素在前端准确绘制虚线警示框，点击能查看原文本与置信度；<br>**AC24.3**：若该页具备差异热力图，可无缝叠加显示；<br>**AC24.4**：快捷键响应丝滑，无焦点失焦或页面滚动冲突。 |

---

## 2. 架构设计与关键决策

### 2.1 响应式百分比坐标系（Percentage Bounding Box Coordinates）
- **痛点**：IR 内部统一采用 EMU 整数单位（如 12192000 × 6858000），而前端画板支持自适应窗口宽度及手势缩放。若前端自行换算像素，极易在不同 DPR、缩放比例下发生对齐错位。
- **决策**：
  - 后端接口 `GET /api/report/{session_id}/elements/{page_idx}` 在返回元素时，直接计算归一化百分比坐标 `bbox_pct`:
    ```json
    {
      "x": (elem.bbox.x / slide.width_emu) * 100,
      "y": (elem.bbox.y / slide.height_emu) * 100,
      "width": (elem.bbox.width / slide.width_emu) * 100,
      "height": (elem.bbox.height / slide.height_emu) * 100
    }
    ```
  - 前端以绝对定位百分比（`left: ${x}%`, `top: ${y}%`, `width: ${w}%`, `height: ${h}%`）渲染标注矩形，天然自适应任何容器分辨率与画板缩放，零对齐偏差。

### 2.2 多页切片缓存与懒加载
- 多页 PDF 上传后，原图与重构图按页懒加载。
- 缩略图栏只在页面进入可视区或点击时加载原图切片 `/api/preview/{id}/original/{page}`，避免大量并发请求拖慢初始渲染。

### 2.3 键盘交互与生产力工作流
- 遵从专业桌面软件（Figma / Keynote）操作习惯：
  - `1` / `Space`：切换为双图滑动对比模式 (Split)
  - `2`：仅看 PPTX 重构结果 (After)
  - `3`：仅看输入原图 (Before)
  - `[`：跳转上一页
  - `]`：跳转下一页
  - `Ctrl/Cmd + 0` 或双击画板空白处：重置画板缩放与平移

---

## 3. HTTP API 协议规范

### 1. 单页元素拓扑与标注数据：`GET /api/report/{session_id}/elements/{page_idx}`
- **Response**: `200 OK`
  ```json
  {
    "session_id": "sess_20261027_a8b9c0d1",
    "page_index": 0,
    "width_emu": 12192000,
    "height_emu": 6858000,
    "elements": [
      {
        "id": "p0-tb-001",
        "kind": "textbox",
        "text": "企业级知识管理架构",
        "confidence": 0.42,
        "degraded": false,
        "source": "ocr",
        "bbox_pct": {
          "x": 12.5,
          "y": 18.2,
          "width": 35.4,
          "height": 6.8
        }
      }
    ]
  }
  ```
- **Error Response**: `404 Not Found` (Session 或该页数据未就绪)

### 2. 差异热力图切片：`GET /api/preview/{session_id}/heatmap/{page_idx}`
- **Response**: `200 OK`，`Content-Type: image/png`
- **Error Response**: `404 Not Found` (未开启迭代或无热力图生成)

---

## 4. 自动化测试清单

| 测试层级 | 测试文件 | 测试用例名 | 验证点 (Assertion) |
|---|---|---|---|
| **Unit** | `tests/unit/gui/test_elements_export.py` | `test_slide_ir_elements_to_normalized_pct` | 验证 EMU 坐标准确换算为百分比坐标，且边界溢出被安全截断在 [0, 100] 范围内。 |
| **Integration** | `tests/integration/test_gui_m3_api.py` | `test_server_serves_page_elements_and_heatmap` | 转换完成后请求 `/api/report/{id}/elements/0`，验证返回 200 且包含合法元素列表与 `bbox_pct`；请求 `/api/preview/{id}/heatmap/0` 正常返回 PNG 图片。 |

---

## 5. Task 拆解与执行计划

- [ ] **Task 1: 页级元素拓扑与热力图后端接口 (Red-Green-Refactor)**
  - 编写 `tests/unit/gui/test_elements_export.py` 与 `tests/integration/test_gui_m3_api.py`（红）
  - 在 `src/pptkit/gui/tasks.py` 中保存页级 `slide_ir_{page}.json` 并确保热力图切片落盘
  - 在 `src/pptkit/gui/server.py` 中实现 `/api/report/{id}/elements/{page}` 与 `/api/preview/{id}/heatmap/{page}` 路由（绿）
  - Git Commit: `feat(gui): implement page elements topology and heatmap endpoints`
- [ ] **Task 2: 前端多页缩略图底栏与翻页导航**
  - 在 `src/pptkit/gui/static/index.html` 中实现缩略图组件与 SSIM 彩色徽章
  - 支持多页快速切片加载与页码状态同步
  - Git Commit: `feat(gui): implement multi-page thumbnail strip navigation`
- [ ] **Task 3: 低置信度元素标注图层与差异热力图叠加**
  - 在画板重构图上方叠加高亮标注层，根据 `bbox_pct` 绘制低置信元素边界框
  - 增加 Tooltip 属性悬浮窗与热力图切换开关
  - Git Commit: `feat(gui): add low-confidence elements overlay and heatmap toggle`
- [ ] **Task 4: 画板平移缩放 (Pan & Zoom) 与全局快捷键**
  - 实现画板鼠标滚轮缩放与拖拽平移
  - 接入 `1`/`2`/`3` 模式切换、`[`/`]` 翻页、双击重置
  - Git Commit: `feat(gui): support pan-zoom canvas and keyboard shortcuts`
- [ ] **Task 5: M3 里程碑全量质量回归与验收记录**
  - 全量自动化测试回归（`pytest tests/unit tests/integration`）
  - 代码规范与类型检查（`ruff check`, `ruff format`, `pyright`）
  - 更新 Spec 验收记录并提交
