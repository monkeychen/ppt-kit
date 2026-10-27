"""Embedded zero-dependency HTTP server for ppt-kit local GUI."""

from __future__ import annotations

import json
import queue
import socket
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

from pptkit.gui.multipart import parse_multipart_form
from pptkit.gui.session import SessionManager
from pptkit.gui.tasks import ConversionOptions, ConversionTask


class PPTKitRequestHandler(BaseHTTPRequestHandler):
    """Handles static assets and API requests for ppt-kit local GUI."""

    server_version = "ppt-kit-gui/0.3.0"

    def log_message(self, format: str, *args: object) -> None:
        """Suppress standard HTTP server request logs to keep CLI output clean."""
        return

    @property
    def ppt_server(self) -> PPTKitServer:
        """Type-safe accessor for PPTKitServer instance."""
        return self.server  # type: ignore[return-value]

    def do_GET(self) -> None:
        """Route GET requests to static assets or API endpoints."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in {"", "/", "/index.html"}:
            self._serve_index()
        elif path == "/api/health":
            self._send_json(200, {"status": "ok", "version": "0.3.0"})
        elif path.startswith("/api/events/"):
            session_id = path[len("/api/events/") :].strip()
            self._handle_events(session_id)
        elif path.startswith("/static/"):
            self._serve_static(path[len("/static/") :])
        else:
            self._send_error(404, "NOT_FOUND", f"Route not found: {path}")

    def do_POST(self) -> None:
        """Route POST requests to API endpoints."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/upload":
            self._handle_upload()
        elif path.startswith("/api/convert/"):
            session_id = path[len("/api/convert/") :].strip()
            self._handle_convert(session_id)
        else:
            self._send_error(404, "NOT_FOUND", f"Route not found: {path}")

    def _serve_index(self) -> None:
        index_file = self.ppt_server.static_dir / "index.html"
        if not index_file.exists():
            self._send_error(404, "FILE_NOT_FOUND", "GUI static index.html not found.")
            return

        content = index_file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_static(self, rel_path: str) -> None:
        target = (self.ppt_server.static_dir / rel_path).resolve()
        if not target.is_relative_to(self.ppt_server.static_dir.resolve()) or not target.exists():
            self._send_error(404, "FILE_NOT_FOUND", "Asset not found.")
            return

        content = target.read_bytes()
        content_type = "application/octet-stream"
        if target.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif target.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        elif target.suffix == ".png":
            content_type = "image/png"
        elif target.suffix == ".svg":
            content_type = "image/svg+xml"

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _handle_upload(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._send_error(400, "INVALID_CONTENT_TYPE", "Expected multipart/form-data")
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_error(400, "INVALID_LENGTH", "Invalid Content-Length header")
            return

        if content_length <= 0:
            self._send_error(400, "EMPTY_BODY", "Request body is empty")
            return

        body = self.rfile.read(content_length)
        try:
            form_data = parse_multipart_form(body, content_type)
        except Exception as e:
            self._send_error(400, "PARSE_ERROR", f"Failed to parse multipart request: {e}")
            return

        file_part = next(iter(form_data.files.values()), None)
        if not file_part:
            self._send_error(400, "NO_FILE", "No file found in upload request")
            return

        try:
            session_info = self.ppt_server.session_manager.create_session(
                filename=file_part.filename,
                content=file_part.content,
            )
        except ValueError as e:
            self._send_error(400, "UNSUPPORTED_FORMAT", str(e))
            return
        except Exception as e:
            self._send_error(500, "SERVER_ERROR", f"Session initialization failed: {e}")
            return

        self._send_json(200, session_info.to_dict())

    def _handle_convert(self, session_id: str) -> None:
        session_info = self.ppt_server.session_manager.get_session(session_id)
        if not session_info:
            self._send_error(404, "SESSION_NOT_FOUND", f"Session {session_id} not found")
            return

        options = ConversionOptions()
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length > 0:
            try:
                body = self.rfile.read(content_length)
                raw_data = json.loads(body.decode("utf-8"))
                options = ConversionOptions(
                    route=raw_data.get("route", "auto"),
                    provider=raw_data.get("provider", "gemini"),
                    use_vlm=bool(raw_data.get("use_vlm", False)),
                    ocr_engine=raw_data.get("ocr_engine", "auto"),
                    max_iter=int(raw_data.get("max_iter", 1)),
                    api_key=raw_data.get("api_key"),
                    pages_spec=raw_data.get("pages_spec"),
                )
            except Exception as e:
                self._send_error(400, "INVALID_OPTIONS", f"Failed to parse options: {e}")
                return

        self.ppt_server.start_task(session_id, options)
        self._send_json(202, {"status": "started", "session_id": session_id})

    def _handle_events(self, session_id: str) -> None:
        session_info = self.ppt_server.session_manager.get_session(session_id)
        if not session_info:
            self._send_error(404, "SESSION_NOT_FOUND", f"Session {session_id} not found")
            return

        task = self.ppt_server.get_task(session_id)
        if task is None:
            task = self.ppt_server.start_task(session_id)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        history, q = task.subscribe()
        try:
            for evt in history:
                payload = json.dumps(evt, ensure_ascii=False)
                self.wfile.write(f"data: {payload}\n\n".encode())
            self.wfile.flush()

            if history and history[-1].get("type") in {"complete", "error"}:
                return

            while True:
                try:
                    evt = q.get(timeout=0.5)
                    payload = json.dumps(evt, ensure_ascii=False)
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                    if evt.get("type") in {"complete", "error"}:
                        break
                except queue.Empty:
                    if task.status in {"completed", "failed"}:
                        break
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            task.unsubscribe(q)

    def _send_json(self, status_code: int, data: dict[str, object]) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_error(self, status_code: int, error_code: str, message: str) -> None:
        self._send_json(status_code, {"error": error_code, "message": message})


class PPTKitServer(ThreadingHTTPServer):
    """Threaded HTTP server for local GUI conversion workstation."""

    DEFAULT_STATIC_DIR: ClassVar[Path] = Path(__file__).parent / "static"

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        cache_dir: Path | None = None,
        static_dir: Path | None = None,
    ) -> None:
        self.static_dir = Path(static_dir) if static_dir else self.DEFAULT_STATIC_DIR
        self.session_manager = SessionManager(base_dir=cache_dir)
        self.tasks: dict[str, ConversionTask] = {}
        super().__init__((host, port), PPTKitRequestHandler)

    def get_task(self, session_id: str) -> ConversionTask | None:
        """Lookup active or completed conversion task by session ID."""
        return self.tasks.get(session_id)

    def start_task(
        self, session_id: str, options: ConversionOptions | None = None
    ) -> ConversionTask:
        """Initialize and launch conversion task for session."""
        session_info = self.session_manager.get_session(session_id)
        if session_info is None:
            raise ValueError(f"Session not found: {session_id}")

        existing = self.tasks.get(session_id)
        if existing and existing.status == "running":
            return existing

        task = ConversionTask(session_info=session_info, options=options)
        self.tasks[session_id] = task
        task.start()
        return task

    @property
    def bound_port(self) -> int:
        """Actual bound port, useful when port 0 is given for dynamic binding."""
        return int(self.server_address[1])


def find_available_port(
    host: str = "127.0.0.1", start_port: int = 8765, max_tries: int = 10
) -> int:
    """Find the first available port starting from start_port up to start_port + max_tries."""
    for port in range(start_port, start_port + max_tries):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
                return port
        except OSError:
            continue

    raise RuntimeError(
        f"No available port found on {host} in range [{start_port}, {start_port + max_tries - 1}]."
    )
