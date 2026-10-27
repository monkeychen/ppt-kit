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


def _upload_file(base_url: str, filename: str, content: bytes, mime_type: str) -> str:
    boundary = "----WebKitFormBoundaryM3ApiTest"
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


def test_server_serves_page_elements_and_heatmap(gui_server) -> None:
    base_url, _ = gui_server

    img = Image.new("RGB", (320, 240), color=(255, 255, 255))
    buf = BytesIO()
    img.save(buf, format="PNG")
    img_bytes = buf.getvalue()

    session_id = _upload_file(base_url, "slide.png", img_bytes, "image/png")

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

    # Wait for completion
    with urllib.request.urlopen(f"{base_url}/api/events/{session_id}") as resp:
        while True:
            line = resp.readline().decode("utf-8").strip()
            if line.startswith("data:"):
                data = json.loads(line[5:].strip())
                if data.get("type") in {"complete", "error"}:
                    break

    # 1. Test elements endpoint
    elements_url = f"{base_url}/api/report/{session_id}/elements/0"
    with urllib.request.urlopen(elements_url) as resp:
        assert resp.status == 200
        assert "application/json" in resp.headers.get("Content-Type", "")
        summary = json.loads(resp.read().decode("utf-8"))
        assert summary["session_id"] == session_id
        assert summary["page_index"] == 0
        assert "width_emu" in summary
        assert "elements" in summary
        assert isinstance(summary["elements"], list)

    # 2. Test heatmap endpoint
    heatmap_url = f"{base_url}/api/preview/{session_id}/heatmap/0"
    with urllib.request.urlopen(heatmap_url) as resp:
        assert resp.status == 200
        assert "image/png" in resp.headers.get("Content-Type", "")
        img_data = resp.read()
        assert img_data.startswith(b"\x89PNG\r\n\x1a\n")


def test_gui_frontend_contains_m3_ui_components(gui_server) -> None:
    base_url, _ = gui_server
    with urllib.request.urlopen(f"{base_url}/") as resp:
        assert resp.status == 200
        html = resp.read().decode("utf-8")
        # Check Task 2: Thumbnail strip container
        assert 'id="thumbStripContainer"' in html
        assert 'id="thumbTrack"' in html

        # Check Task 3: Elements overlay, tooltip and heatmap toggle
        assert 'id="elementsOverlay"' in html
        assert 'id="elemTooltip"' in html
        assert 'id="btnToggleOverlay"' in html
        assert 'id="btnModeHeatmap"' in html

        # Check Task 4: Canvas transform wrapper & zoom controls
        assert 'id="stageTransformWrapper"' in html
        assert 'id="zoomLabel"' in html


def test_multipage_pdf_conversion_and_assets(gui_server) -> None:
    import pymupdf

    base_url, _ = gui_server

    # Create 2-page PDF
    doc = pymupdf.open()
    p1 = doc.new_page(width=300, height=200)
    p1.insert_text((40, 50), "First Page Slide")
    p2 = doc.new_page(width=300, height=200)
    p2.insert_text((40, 50), "Second Page Slide")
    pdf_bytes = doc.tobytes()
    doc.close()

    session_id = _upload_file(base_url, "multi.pdf", pdf_bytes, "application/pdf")

    # Start conversion with vector route
    convert_payload = json.dumps({"route": "vector", "max_iter": 0}).encode("utf-8")
    convert_req = urllib.request.Request(
        f"{base_url}/api/convert/{session_id}",
        data=convert_payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(convert_req) as resp:
        assert resp.status == 202

    # Listen to SSE events
    events = []
    with urllib.request.urlopen(f"{base_url}/api/events/{session_id}") as resp:
        while True:
            line = resp.readline().decode("utf-8").strip()
            if line.startswith("data:"):
                ev = json.loads(line[5:].strip())
                events.append(ev)
                if ev.get("type") in {"complete", "error"}:
                    break

    complete_ev = next((e for e in events if e.get("type") == "complete"), None)
    assert complete_ev is not None
    assert complete_ev["total_pages"] == 2
    assert len(complete_ev["pages"]) == 2

    # Verify both pages have original, reconstructed, heatmap and elements
    for page_idx in (0, 1):
        with urllib.request.urlopen(
            f"{base_url}/api/preview/{session_id}/original/{page_idx}"
        ) as resp:
            assert resp.status == 200
            assert "image/png" in resp.headers.get("Content-Type", "")

        with urllib.request.urlopen(
            f"{base_url}/api/preview/{session_id}/reconstructed/{page_idx}"
        ) as resp:
            assert resp.status == 200
            assert "image/png" in resp.headers.get("Content-Type", "")

        with urllib.request.urlopen(
            f"{base_url}/api/preview/{session_id}/heatmap/{page_idx}"
        ) as resp:
            assert resp.status == 200
            assert "image/png" in resp.headers.get("Content-Type", "")

        with urllib.request.urlopen(
            f"{base_url}/api/report/{session_id}/elements/{page_idx}"
        ) as resp:
            assert resp.status == 200
            elem_summary = json.loads(resp.read().decode("utf-8"))
            assert elem_summary["page_index"] == page_idx
            assert len(elem_summary["elements"]) > 0
