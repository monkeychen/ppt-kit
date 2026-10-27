---
doc: spec
product: pptkit
version: v0.3.0
milestone: M2
date: 2026-10-27
status: approved
---

# Spec：v0.3.0-M2 核心转换引擎驱动与 SSE 进度实时流

> 里程碑目标：打通本地 Web GUI 与底层逆向重构引擎，实现后台异步转换工作线程、基于 Server-Sent Events (SSE) 的页级进度流式推送、原图与重构图双切片预览伺服、以及 `.pptx` 产物一键下载。

---

## 1. 需求与边界对应

| 需求编号 | 需求名称 | 本里程碑范围 (Scope) | 验收标准 (Acceptance Criteria) |
|---|---|---|---|
| **F22** | 异步转换引擎与 SSE 进度实时流 | 1. `POST /api/convert/{session_id}` 接口：接收转换参数（`use_vlm`, `ocr_engine`, `max_iter` 等），调度后台工作线程执行；<br>2. `GET /api/events/{session_id}` 接口：基于标准 SSE (`text/event-stream`) 协议，实时流式推送每页解析/识别进度、当前耗时与实时 SSIM 得分；<br>3. 转换状态机维护：`queued` -> `converting` -> `completed` / `failed`。 | **AC22.1**：触发转换后立即返回 HTTP 202，不阻塞 HTTP 工作线程；<br>**AC22.2**：浏览器通过 `EventSource` 订阅，按页接收结构化进度消息，末尾收到 `complete` 事件；<br>**AC22.3**：若转换异常中断，能推送带有清晰原因的 `error` 事件，且状态平稳收敛。 |
| **F23** | 双图切片预览伺服与 PPTX 导出 | 1. `GET /api/preview/{session_id}/original/{page_idx}`：提取并伺服原输入页的高清 PNG 切片；<br>2. `GET /api/preview/{session_id}/reconstructed/{page_idx}`：提取并伺服渲染重建后的对比切片；<br>3. `GET /api/download/{session_id}`：流式下载生成的编辑级 `.pptx` 演示文件，附带正确的 `Content-Disposition` 附件标头；<br>4. `GET /api/report/{session_id}`：下载结构化 JSON 质量诊断报告。 | **AC23.1**：原图切片针对 PDF / 纯图片输入均能秒级响应（PDF 动态渲染指定页并缓存）；<br>**AC23.2**：转换完成后，下载接口能完整输出二进制 `.pptx`，文件名匹配原输入文件主名；<br>**AC23.3**：前端 `index.html` 完成事件与数据对接，完成从上传 -> 转换 -> 进度条 -> 下载的完整闭环。 |

---

## 2. 架构设计与关键决策

### 2.1 零依赖 SSE 流式机制（Zero-Dependency SSE）
- **背景**：PRD 要求零引入额外 Web 框架（如 FastAPI、Starlette、SSE-Starlette），确保 PyInstaller 单文件跨平台免编译兼容。
- **设计**：
  - 在 `PPTKitRequestHandler` 中实现 `text/event-stream` 协议响应。
  - 标头设置：
    ```http
    HTTP/1.1 200 OK
    Content-Type: text/event-stream; charset=utf-8
    Cache-Control: no-cache, no-transform
    Connection: keep-alive
    X-Accel-Buffering: no
    ```
  - 每个事件采用标准文本帧格式：
    ```text
    event: message\n
    data: {"type": "page", "page_index": 1, "ssim": 0.94}\n\n
    ```
  - 底层使用 Python 标库 `queue.Queue` 进行线程间消息传递。当后台转换线程产生进度时，`put` 进会话事件队列，HTTP 线程 `get` 并通过 `self.wfile.write()` 实时刷新，并调用 `self.wfile.flush()` 确保无缓冲延迟。

### 2.2 线程模型与任务生命周期
- **解耦**：HTTP 处理线程与转换计算线程严格隔离。
- **状态机与缓存**：
  - `SessionManager` 中为每个 session 维护 `ConversionTask` 状态对象：
    - `status`: `"idle" | "running" | "completed" | "failed"`
    - `events_history`: `list[dict]`（保存历史事件，支持网络抖动重连或后接入客户端回放）
    - `error`: `str | None`
    - `result`: `DocumentQualityReport | None`
    - `output_pptx_path`: `Path | None`
- **幂等性**：若某 session 正在运行，重复请求 `POST /api/convert/{session_id}` 返回当前运行状态，避免重复并发消耗算力。

### 2.3 双图切片与懒加载机制
- **原图切片** (`/original/{page_idx}`)：
  - 若为图片文件（PNG/JPG/WebP），直接输出该图片（第 0 页）。
  - 若为 PDF，调用 `fitz` 将对应页光栅化渲染为 PNG 并存入会话切片缓存目录 `previews/orig_p{page_idx}.png`，二次访问直接命中磁盘缓存。
- **重构图切片** (`/reconstructed/{page_idx}`)：
  - 在转换流水线中，矢量页或位图页重建完成后会生成重构渲染图与差异热力图（见 `reconstruct_raster_slide` 产物）。接口从对应页的 `work_dir` 读取并返回。

---

## 3. HTTP API 协议规范

### 1. 触发转换：`POST /api/convert/{session_id}`
- **Request Body**: `application/json`
  ```json
  {
    "route": "auto",
    "use_vlm": false,
    "provider": "gemini",
    "ocr_engine": "auto",
    "max_iter": 1
  }
  ```
- **Success Response**: `202 Accepted`
  ```json
  {
    "status": "started",
    "session_id": "sess_20261027_a8b9c0d1"
  }
  ```
- **Error Response**: `404 Not Found` (Session 不存在) 或 `409 Conflict` (任务已在运行)

### 2. 实时进度订阅：`GET /api/events/{session_id}`
- **协议**: `text/event-stream`
- **消息帧格式**:
  - **启动帧**：
    ```json
    {"type": "start", "session_id": "...", "total_pages": 4}
    ```
  - **页级进度帧**：
    ```json
    {
      "type": "page",
      "page_index": 0,
      "status": "ok",
      "route": "vector",
      "ssim": 0.985,
      "editable_elements": 14,
      "elapsed_sec": 0.42
    }
    ```
  - **完成帧**：
    ```json
    {
      "type": "complete",
      "session_id": "...",
      "succeeded_pages": 4,
      "failed_pages": 0,
      "avg_ssim": 0.962,
      "elapsed_sec": 3.8,
      "download_url": "/api/download/sess_20261027_a8b9c0d1"
    }
    ```
  - **错误帧**：
    ```json
    {
      "type": "error",
      "session_id": "...",
      "error_code": "CONVERSION_FAILED",
      "message": "第 2 页 OCR 解析失败"
    }
    ```

### 3. 切片预览：`GET /api/preview/{session_id}/{type}/{page_idx}`
- `type`: `"original" | "reconstructed"`
- **Response**: `200 OK`，`Content-Type: image/png`

### 4. 产物下载：`GET /api/download/{session_id}`
- **Response**: `200 OK`
- **Headers**:
  - `Content-Type: application/vnd.openxmlformats-officedocument.presentationml.presentation`
  - `Content-Disposition: attachment; filename="presentation.pptx"`

---

## 4. 自动化测试清单

| 测试层级 | 测试文件 | 测试用例名 | 验证点 (Assertion) |
|---|---|---|---|
| **Unit** | `tests/unit/gui/test_task_runner.py` | `test_task_runner_dispatches_events` | 任务管理器在独立线程中执行转换，按顺序触发 `start`、`page`、`complete` 结构化事件。 |
| **Unit** | `tests/unit/gui/test_task_runner.py` | `test_task_runner_handles_failure_gracefully` | 遇到非法页或执行异常时，平稳发送 `error` 事件并记录异常信息，不发生线程泄漏。 |
| **Integration** | `tests/integration/test_gui_sse.py` | `test_server_sse_progress_stream` | 客户端通过标准 HTTP GET 发起 SSE 连接，真实接收并解析多帧事件，直到 `complete` 结束。 |
| **Integration** | `tests/integration/test_gui_preview.py` | `test_server_original_and_reconstructed_preview` | 验证合成 PDF 渲染原图切片与重构切片正常输出合法的 PNG 二进制图片流。 |
| **Integration** | `tests/integration/test_gui_download.py` | `test_server_download_pptx_and_report` | 转换完成后发起下载请求，检验返回 200、标头携带 `attachment` 且内容为合法 PPTX 文件头 (`PK..`)。 |

---

## 5. Task 拆解与执行计划

- [x] **Task 1: 会话转换任务调度器与事件队列 (Red-Green-Refactor)**
  - 编写 `tests/unit/gui/test_task_runner.py`（红）
  - 实现 `src/pptkit/gui/tasks.py`（绿）
  - 统一转换流水线执行器与监听队列，实现事件回放与线程安全
  - 验证证据：`uv run pytest tests/unit/gui/test_task_runner.py`（3 passed in 0.65s），Pyright 0 errors, Ruff clean
  - Git Commit: `feat(gui): implement async conversion task runner and event queue`
- [x] **Task 2: SSE 进度流式端点与转换调度路由 (Red-Green-Refactor)**
  - 编写 `tests/integration/test_gui_sse.py`（红）
  - 在 `src/pptkit/gui/server.py` 中实现 `POST /api/convert/{id}` 与 `GET /api/events/{id}`（绿）
  - 确保无缓冲流式传输与客户端平滑断开处理
  - 验证证据：`uv run pytest tests/integration/test_gui_sse.py`（1 passed in 0.89s），Pyright 0 errors, Ruff clean
  - Git Commit: `feat(gui): add sse progress streaming and convert endpoint`
- [x] **Task 3: 双图切片与 PPTX/报告下载端点 (Red-Green-Refactor)**
  - 编写 `tests/integration/test_gui_preview_download.py`（红）
  - 实现 `/api/preview/{id}/{type}/{page}` 与 `/api/download/{id}`、`/api/report/{id}`（绿）
  - 接入 PDF 首屏切片缓存与 PPTX 附件流式下发
  - 验证证据：`uv run pytest tests/integration/test_gui_preview_download.py`（2 passed in 3.82s），Pyright 0 errors, Ruff clean
  - Git Commit: `feat(gui): implement preview slice serving and pptx download`
- [x] **Task 4: 前端交互打通与状态闭环**
  - 在 `src/pptkit/gui/static/index.html` 中接入真实接口（上传 -> 触发转换 -> SSE 监听 -> 状态条刷新 -> 下载激活）
  - 同步更新原型文档 `docs/prototype/gui_prototype.html`
  - 验证证据：全量 GUI 测试（19 passed in 9.38s），Ruff / Pyright 0 errors
  - Git Commit: `feat(gui): connect web frontend with sse progress and download`
- [ ] **Task 5: M2 里程碑全量质量回归与验收记录**
  - 全量自动化测试回归（`pytest tests/unit tests/integration`）
  - 代码规范与类型检查（`ruff check`, `ruff format`, `pyright`）
  - 更新 Spec 验收记录并提交
