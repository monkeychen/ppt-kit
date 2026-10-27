import json
import threading
import time
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from pptkit.gui.server import PPTKitServer


@pytest.fixture
def gui_server(tmp_path: Path):
    """Fixture that starts a PPTKitServer on an ephemeral port and stops it cleanly."""
    server = PPTKitServer(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    # Wait for server to bind port
    for _ in range(50):
        if server.bound_port > 0:
            break
        time.sleep(0.02)

    base_url = f"http://127.0.0.1:{server.bound_port}"
    yield base_url, server

    server.shutdown()
    server.server_close()


def test_server_serves_static_html_and_health_check(gui_server) -> None:
    base_url, _ = gui_server

    # 1. Test root GET /
    with urllib.request.urlopen(f"{base_url}/") as response:
        assert response.status == 200
        content_type = response.headers.get("Content-Type", "")
        assert "text/html" in content_type
        body = response.read().decode("utf-8")
        assert "ppt-kit" in body

    # 2. Test GET /api/health
    with urllib.request.urlopen(f"{base_url}/api/health") as response:
        assert response.status == 200
        assert "application/json" in response.headers.get("Content-Type", "")
        data = json.loads(response.read().decode("utf-8"))
        assert data.get("status") == "ok"


def test_server_handles_upload_end_to_end(gui_server) -> None:
    base_url, _ = gui_server

    # Create dummy PNG
    img = Image.new("RGB", (320, 240), color=(100, 150, 200))
    buf = BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    boundary = "----WebKitFormBoundaryTest12345"
    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="sample.png"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode()
        + png_bytes
        + f"\r\n--{boundary}--\r\n".encode()
    )

    req = urllib.request.Request(
        f"{base_url}/api/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )

    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "session_id" in data
        assert data["filename"] == "sample.png"
        assert data["file_type"] == "png"
        assert data["page_count"] == 1


def test_server_rejects_unsupported_upload(gui_server) -> None:
    base_url, _ = gui_server

    boundary = "----WebKitFormBoundaryReject123"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="script.sh"\r\n'
        f"Content-Type: text/x-shellscript\r\n\r\n"
        f"echo hello\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    req = urllib.request.Request(
        f"{base_url}/api/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)

    assert exc_info.value.code == 400
    err_body = exc_info.value.read().decode("utf-8")
    assert "UNSUPPORTED_FORMAT" in err_body
