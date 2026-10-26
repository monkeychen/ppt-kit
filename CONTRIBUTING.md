# 参与贡献指南 (Contributing to ppt-kit)

感谢你关注 `ppt-kit`！我们非常欢迎社区提交 Bug 修复、功能建议和代码贡献。

## 🛠️ 本地开发环境准备

项目使用 [uv](https://github.com/astral-sh/uv) 进行 Python 虚拟环境与依赖管理。

### 1. 环境依赖
- macOS 13+ (Apple Silicon 或 Intel)
- Python 3.11+
- uv

### 2. 初始化与安装
```bash
git clone https://github.com/monkeychen/ppt-kit.git
cd ppt-kit
uv sync
```

---

## 🧪 测试与质量验证

在提交任何 Pull Request 之前，请确保以下质量验证命令全部通过：

```bash
# 1. 运行所有单元测试（秒级）
uv run pytest tests/unit

# 2. 运行端到端测试
uv run pytest tests/e2e

# 3. 运行代码风格检查与格式化验证
uv run ruff check . && uv run ruff format --check .

# 4. 运行静态类型检查
uv run pyright
```

---

## 📐 代码设计原则

1. **能读就不识别**：处理输入源时，只要内部存在矢量文本或几何定义（如矢量 PDF），必须直接解析，杜绝脱水成图片再做 OCR/VLM。
2. **单一中间表示（Slide IR）**：所有输入解析器必须输出 `SlideIR`，PPTX Writer 仅根据 `SlideIR` 进行组装，禁止直接从输入解析直接写入 PPTX。
3. **坐标与度量单位**：项目内部坐标体系全部统一使用 **EMU**（English Metric Unit，1 inch = 914,400 EMU）。仅在输入加载和输出写入边界层调用 `pptkit.common.units` 做换算。
4. **保留注释**：请尊重既有注释和 docstring，不要在重构时删除无冲突的文档说明。

---

## 📬 提交 Pull Request

1. Fork 本仓库并基于 `main` 分支创建特性分支（如 `feature/table-inference` 或 `fix/font-mapping`）；
2. 编写测试（遵循测试先行，每个新功能必须附带对应的单元测试）；
3. 提交 Git 记录，Commit message 建议遵循 Conventional Commits 规范（英文短语，如 `feat: add table parsing` 或 `fix: resolve bbox overlap`）；
4. 提交 PR 并详细描述变更内容与影响。
