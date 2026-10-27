import json
import threading
import time
import urllib.request
from io import BytesIO
from pathlib import Path

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


def test_server_sse_progress_stream(gui_server) -> None:
    base_url, _ = gui_server

    # 1. Upload sample image
    img = Image.new("RGB", (320, 240), color=(255, 255, 255))
    buf = BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    boundary = "----WebKitFormBoundarySSE123"
    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="slide.png"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode()
        + png_bytes
        + f"\r\n--{boundary}--\r\n".encode()
    )

    upload_req = urllib.request.Request(
        f"{base_url}/api/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(upload_req) as resp:
        assert resp.status == 200
        session_data = json.loads(resp.read().decode("utf-8"))
        session_id = session_data["session_id"]

    # 2. Trigger conversion
    payload_dict = {"route": "raster", "max_iter": 0, "ocr_engine": "auto"}
    convert_payload = json.dumps(payload_dict).encode("utf-8")
    convert_req = urllib.request.Request(
        f"{base_url}/api/convert/{session_id}",
        data=convert_payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(convert_req) as resp:
        assert resp.status == 202
        res_data = json.loads(resp.read().decode("utf-8"))
        assert res_data.get("status") == "started"

    # 3. Connect to SSE stream
    sse_req = urllib.request.Request(f"{base_url}/api/events/{session_id}")
    events = []
    with urllib.request.urlopen(sse_req, timeout=15) as resp:
        assert resp.status == 200
        assert "text/event-stream" in resp.headers.get("Content-Type", "")

        while True:
            line = resp.readline().decode("utf-8")
            if not line:
                break
            line = line.strip()
            if line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                events.append(payload)
                if payload.get("type") in {"complete", "error"}:
                    break

    event_types = [e["type"] for e in events]
    assert "start" in event_types
    assert "page" in event_types
    assert "complete" in event_types

    complete_evt = next(e for e in events if e["type"] == "complete")
    assert complete_evt["session_id"] == session_id
    assert complete_evt["succeeded_pages"] == 1
