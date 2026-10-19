# ppt-kit 项目规范

> 把「图片版 PPT」（AI 生成的幻灯片图片、NotebookLM 导出的 PDF、PowerPoint 导出的 PDF）还原为**可编辑**的 PPTX。
> 开发流程严格遵循 `~/.gemini/dev-workflow.md`；本文件只写本项目特有的约定。

## 1. 核心原则

1. **能读就不识别**：输入里有矢量信息（PDF 文字/路径）时，直接解析，不走 OCR/VLM。识别只用于没有矢量信息的位图。
2. **单一中间表示**：所有输入路径都产出同一份元素树（Slide IR），PPTX 生成器只认 IR。新增输入源 = 新增一个 IR 生产者，禁止直接写 PPTX。
3. **质量靠度量，不靠肉眼**：每次转换都必须能输出质量报告（渲染后与原图的 SSIM、可编辑元素占比、低置信元素清单）。任何「效果更好了」的结论必须附基准集数字。
4. **宁可退化，不可错乱**：识别置信度不足的元素降级为图片层保留视觉，绝不输出位置/内容错误的可编辑元素。
5. **模型可插拔**：VLM / OCR / 修复模型都通过 adapter 接入，默认 Gemini；业务代码不得直接 import 某家 SDK。

## 2. 目录结构

```
ppt-kit/
├── GEMINI.md
├── pyproject.toml              # uv 管理依赖
├── src/pptkit/
│   ├── ir/                     # Slide IR 数据模型（pydantic），唯一的中间表示
│   ├── ingest/                 # 输入加载 + 每页路径判定（vector / raster）
│   ├── vector/                 # 矢量 PDF 解析 → IR
│   ├── raster/                 # 位图重建 → IR（ocr/ inpaint/ shapes/ layout/）
│   ├── adapters/               # 外部模型适配器（gemini/ openai/ ocr/ inpaint/）
│   ├── writer/                 # IR → PPTX
│   ├── render/                 # PPTX → PNG 渲染 + 图像对比度量
│   ├── report/                 # 质量报告
│   └── cli/                    # Typer CLI 入口
├── tests/
│   ├── unit/                   # 无网络、无外部模型，秒级
│   ├── integration/            # 真实模型 / 真实渲染器，需 API Key，标记 @pytest.mark.integration
│   ├── e2e/                    # CLI 端到端：输入文件 → PPTX → 渲染校验
│   └── fixtures/               # 小体积测试样本（单文件 ≤ 500KB）
├── benchmark/
│   ├── synthetic/              # 合成样本生成器：代码生成 PPTX → 渲染成图 → 自带标准答案
│   ├── real/                   # 真实样本（GPT / NotebookLM / PPT 导出 PDF），大文件不入库
│   └── results/                # 基准跑分输出（gitignore，可重新生成）
├── docs/                       # 按 dev-workflow 规范：prd/ spec/ prototype/ release/ archive/ vibe-coding-log.md
└── out/                        # 本地转换输出（gitignore）
```

**什么放哪**：
- 只被一个子模块用的工具函数放在该模块内；被 ≥2 个模块用才提升到 `pptkit/common/`。
- 坐标换算、颜色处理等通用几何逻辑放 `pptkit/common/`，禁止各模块各写一份。
- 一次性调试脚本放 `scratch/`（gitignore），不进 `src/`。

## 3. 命名约定

- Python 模块、函数、变量：`snake_case`；类：`PascalCase`；常量：`UPPER_SNAKE`。
- 测试文件：`tests/<层级>/test_<被测模块>.py`；测试函数：`test_<行为>_<条件>_<预期>`。
- 基准样本：`benchmark/real/<来源>/<编号>-<简述>.<ext>`，来源取值 `gpt | notebooklm | gemini | pptpdf | other`。
- CLI 输出文件：默认与输入同名，`<name>.pptx` + `<name>.report.json`。

## 4. 单位与坐标（全项目统一）

- IR 内部统一使用 **EMU**（English Metric Unit，914400 EMU = 1 inch），整数。
- 页面原点在左上角，x 向右、y 向下。
- 只在边界层（ingest / writer）做单位换算，换算函数唯一实现在 `pptkit/common/units.py`。

## 5. 常用命令

```bash
uv sync                                  # 安装依赖
uv run pytest tests/unit                 # 单元测试
uv run pytest -m integration             # 集成测试（需 GEMINI_API_KEY）
uv run pytest tests/e2e                  # 端到端测试
uv run ruff check . && uv run ruff format --check .
uv run pyright                           # 类型检查
uv run pptkit convert <input> -o out/    # 转换
uv run python -m benchmark.run           # 跑基准集，结果写入 benchmark/results/
```

## 6. 密钥与配置

- API Key 只从环境变量或 `~/.config/pptkit/config.toml` 读取，**禁止写进代码、测试、fixtures**。
- 环境变量命名：`PPTKIT_<PROVIDER>_API_KEY`，同时兼容 `GEMINI_API_KEY` / `OPENAI_API_KEY`。

## 7. 清理规则

- `out/`、`benchmark/results/`、`scratch/`、`.cache/` 全部 gitignore，随时可删。
- `benchmark/real/` 里的大文件不入库，只入库 `manifest.json`（文件名、来源、页数、sha256）。
- 版本交付后，`docs/` 下本版文档整组移入 `docs/archive/vx.y.z/`。
