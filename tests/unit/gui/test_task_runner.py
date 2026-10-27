from pathlib import Path

from PIL import Image

from pptkit.gui.session import SessionInfo, SessionManager
from pptkit.gui.tasks import ConversionOptions, ConversionTask


def test_task_runner_event_queue_and_replay(tmp_path: Path) -> None:
    session_info = SessionInfo(
        session_id="sess_test_123",
        filename="dummy.png",
        file_size=100,
        file_type="png",
        page_count=1,
        input_path=tmp_path / "dummy.png",
        session_dir=tmp_path,
    )
    task = ConversionTask(session_info=session_info)

    task.emit_event({"type": "start", "total_pages": 2})
    task.emit_event({"type": "page", "page_index": 0, "status": "ok"})

    history, q = task.subscribe()
    assert len(history) == 2
    assert history[0]["type"] == "start"
    assert history[1]["page_index"] == 0

    task.emit_event({"type": "complete", "succeeded_pages": 1})
    live_event = q.get(timeout=1.0)
    assert live_event["type"] == "complete"


def test_task_runner_dispatches_events(tmp_path: Path) -> None:
    # 1. Create a minimal valid test image
    img_path = tmp_path / "slide.png"
    img = Image.new("RGB", (320, 240), color=(255, 255, 255))
    img.save(img_path)

    manager = SessionManager(base_dir=tmp_path / "sessions")
    session_info = manager.create_session("slide.png", img_path.read_bytes())

    options = ConversionOptions(
        route="raster",
        max_iter=0,  # Fast run without iterative refinement
        ocr_engine="auto",
    )
    task = ConversionTask(session_info=session_info, options=options)

    history, q = task.subscribe()
    task.start()
    task.wait(timeout=60.0)

    assert task.status == "completed"
    assert task.output_pptx_path is not None
    assert task.output_pptx_path.exists()
    assert task.output_pptx_path.stat().st_size > 0

    # Collect all events from history + queue
    events = list(history)
    while not q.empty():
        events.append(q.get_nowait())

    event_types = [e["type"] for e in events]
    assert "start" in event_types
    assert "page" in event_types
    assert "complete" in event_types


def test_task_runner_handles_failure_gracefully(tmp_path: Path) -> None:
    session_info = SessionInfo(
        session_id="sess_invalid",
        filename="nonexistent.png",
        file_size=0,
        file_type="png",
        page_count=1,
        input_path=tmp_path / "nonexistent.png",
        session_dir=tmp_path,
    )
    task = ConversionTask(session_info=session_info)
    history, q = task.subscribe()
    task.start()
    task.wait(timeout=5.0)

    assert task.status == "failed"
    events = list(history)
    while not q.empty():
        events.append(q.get_nowait())

    event_types = [e["type"] for e in events]
    assert "error" in event_types
