import json
import threading
import time
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

import fitz
import pytest
from PIL import Image

from pptkit.gui.server import PPTKitServer


@pytest.fixture
def gui_server(tmp_path: Path):
    server = PPTKitServer(host="127.0.0.1", port=0, cache_dir=tmp_path)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    for _ in range(50):
        if server.bound_port > 0:
            break
        time.sleep(0.02)

    base_url = f"http://127.0.0.1:{server.bound_port}"
    yield base_url, server

    server.shutdown()
    server.server_close()


def _upload_file(base_url: str, filename: str, content: bytes, mime_type: str) -> str:
    boundary = "----WebKitFormBoundaryPreviewTest"
    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode()
        + content
        + f"\r\n--{boundary}--\r\n".encode()
    )

    req = urllib.request.Request(
        f"{base_url}/api/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return str(data["session_id"])


def test_server_preview_original_image_and_pdf(gui_server) -> None:
    base_url, _ = gui_server

    # 1. Test image original preview
    img = Image.new("RGB", (320, 240), color=(120, 180, 240))
    buf = BytesIO()
    img.save(buf, format="PNG")
    img_bytes = buf.getvalue()

    sess_img = _upload_file(base_url, "test.png", img_bytes, "image/png")

    with urllib.request.urlopen(f"{base_url}/api/preview/{sess_img}/original/0") as resp:
        assert resp.status == 200
        assert "image/png" in resp.headers.get("Content-Type", "")
        data = resp.read()
        assert data.startswith(b"\x89PNG\r\n\x1a\n")

    # 2. Test PDF original preview (dynamic page rendering)
    doc = fitz.open()
    doc.new_page(width=400, height=300)
    doc.new_page(width=400, height=300)
    pdf_bytes = doc.tobytes()
    doc.close()

    sess_pdf = _upload_file(base_url, "doc.pdf", pdf_bytes, "application/pdf")

    # Page 0
    with urllib.request.urlopen(f"{base_url}/api/preview/{sess_pdf}/original/0") as resp:
        assert resp.status == 200
        assert resp.read().startswith(b"\x89PNG\r\n\x1a\n")

    # Page 1
    with urllib.request.urlopen(f"{base_url}/api/preview/{sess_pdf}/original/1") as resp:
        assert resp.status == 200
        assert resp.read().startswith(b"\x89PNG\r\n\x1a\n")

    # Out of range page should 404
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{base_url}/api/preview/{sess_pdf}/original/99")
    assert exc_info.value.code == 404


def test_server_download_pptx_and_report(gui_server) -> None:
    base_url, _ = gui_server

    img = Image.new("RGB", (320, 240), color=(255, 255, 255))
    buf = BytesIO()
    img.save(buf, format="PNG")
    img_bytes = buf.getvalue()

    session_id = _upload_file(base_url, "deck.png", img_bytes, "image/png")

    # Trigger conversion
    convert_payload = json.dumps({"route": "raster", "max_iter": 0}).encode("utf-8")
    convert_req = urllib.request.Request(
        f"{base_url}/api/convert/{session_id}",
        data=convert_payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(convert_req) as resp:
        assert resp.status == 202

    # Wait for completion via events stream
    with urllib.request.urlopen(f"{base_url}/api/events/{session_id}") as resp:
        while True:
            line = resp.readline().decode("utf-8").strip()
            if line.startswith("data:"):
                data = json.loads(line[5:].strip())
                if data.get("type") in {"complete", "error"}:
                    break

    # 1. Download PPTX
    with urllib.request.urlopen(f"{base_url}/api/download/{session_id}") as resp:
        assert resp.status == 200
        cd = resp.headers.get("Content-Disposition", "")
        assert "attachment" in cd
        assert "deck.pptx" in cd
        content = resp.read()
        assert content.startswith(b"PK\x03\x04")  # PPTX zip header

    # 2. Get JSON report
    with urllib.request.urlopen(f"{base_url}/api/report/{session_id}") as resp:
        assert resp.status == 200
        assert "application/json" in resp.headers.get("Content-Type", "")
        report = json.loads(resp.read().decode("utf-8"))
        assert report["succeeded_pages"] == 1

    # 3. Reconstructed preview
    with urllib.request.urlopen(f"{base_url}/api/preview/{session_id}/reconstructed/0") as resp:
        assert resp.status == 200
        assert resp.read().startswith(b"\x89PNG\r\n\x1a\n")
