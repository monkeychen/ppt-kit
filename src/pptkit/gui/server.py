"""Embedded zero-dependency HTTP server for ppt-kit local GUI."""

from __future__ import annotations

import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

from pptkit.gui.multipart import parse_multipart_form
from pptkit.gui.session import SessionManager


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
        super().__init__((host, port), PPTKitRequestHandler)

    @property
    def bound_port(self) -> int:
        """Actual bound port, useful when port 0 is given for dynamic binding."""
        return int(self.server_address[1])
