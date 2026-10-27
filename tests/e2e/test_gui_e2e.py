"""End-to-end test for pptkit Web GUI workflow."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

from PIL import Image

from pptkit.gui.server import PPTKitServer


def test_gui_full_lifecycle_e2e(tmp_path: Path) -> None:
    # 1. Start GUI server with ephemeral port and isolated cache dir
    cache_dir = tmp_path / "gui_cache"
    server = PPTKitServer(host="127.0.0.1", port=0, cache_dir=cache_dir)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    for _ in range(50):
        if server.bound_port > 0:
            break
        time.sleep(0.02)

    base_url = f"http://127.0.0.1:{server.bound_port}"

    try:
        # 2. Check health endpoint
        with urllib.request.urlopen(f"{base_url}/api/health") as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "ok"
            assert data["version"] in {"0.3.0", "v0.3.0"}

        # 3. Create and upload a slide image
        img = Image.new("RGB", (640, 360), color=(250, 250, 250))
        buf = BytesIO()
        img.save(buf, format="PNG")
        img_bytes = buf.getvalue()

        boundary = "----WebKitFormBoundaryGuiE2ETest"
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="e2e_slide.png"\r\n'
                f"Content-Type: image/png\r\n\r\n"
            ).encode()
            + img_bytes
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
            upload_data = json.loads(resp.read().decode("utf-8"))
            session_id = upload_data["session_id"]
            assert session_id

        # 4. Trigger conversion
        convert_payload = json.dumps({"route": "raster", "max_iter": 0}).encode("utf-8")
        convert_req = urllib.request.Request(
            f"{base_url}/api/convert/{session_id}",
            data=convert_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(convert_req) as resp:
            assert resp.status == 202

        # 5. Listen to SSE events stream until complete
        events = []
        with urllib.request.urlopen(f"{base_url}/api/events/{session_id}") as resp:
            while True:
                line = resp.readline().decode("utf-8").strip()
                if line.startswith("data:"):
                    payload = json.loads(line[5:].strip())
                    events.append(payload)
                    if payload.get("type") in {"complete", "error"}:
                        break

        assert any(e.get("type") == "start" for e in events)
        complete_event = next(e for e in events if e.get("type") == "complete")
        assert complete_event["session_id"] == session_id

        # 6. Verify original, reconstructed, heatmap preview endpoints
        for preview_type in ("original", "reconstructed", "heatmap"):
            with urllib.request.urlopen(
                f"{base_url}/api/preview/{session_id}/{preview_type}/0"
            ) as resp:
                assert resp.status == 200
                assert "image/png" in resp.headers.get("Content-Type", "")
                content = resp.read()
                assert content.startswith(b"\x89PNG\r\n\x1a\n")

        # 7. Verify elements JSON endpoint
        with urllib.request.urlopen(f"{base_url}/api/report/{session_id}/elements/0") as resp:
            assert resp.status == 200
            elem_summary = json.loads(resp.read().decode("utf-8"))
            assert elem_summary["session_id"] == session_id
            assert "elements" in elem_summary

        # 8. Download generated PPTX and verify zip integrity
        with urllib.request.urlopen(f"{base_url}/api/download/{session_id}") as resp:
            assert resp.status == 200
            pptx_bytes = resp.read()
            assert len(pptx_bytes) > 0
            # A valid pptx is a zip file containing [Content_Types].xml
            with zipfile.ZipFile(BytesIO(pptx_bytes)) as zf:
                assert "[Content_Types].xml" in zf.namelist()

        # 9. Verify quality report JSON endpoint
        with urllib.request.urlopen(f"{base_url}/api/report/{session_id}") as resp:
            assert resp.status == 200
            report = json.loads(resp.read().decode("utf-8"))
            assert report["succeeded_pages"] == 1

    finally:
        server.shutdown()
        server.server_close()
