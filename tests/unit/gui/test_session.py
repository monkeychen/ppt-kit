from pathlib import Path

import pytest
from PIL import Image

from pptkit.gui.session import SessionInfo, SessionManager


def test_create_session_stores_file_and_extracts_metadata(tmp_path: Path) -> None:
    manager = SessionManager(base_dir=tmp_path)

    # 1. Test image upload
    img = Image.new("RGB", (640, 480), color=(255, 255, 255))
    img_bytes_io = Path(tmp_path / "test.png")
    img.save(img_bytes_io)
    img_bytes = img_bytes_io.read_bytes()

    info = manager.create_session("my_slide.png", img_bytes)
    assert isinstance(info, SessionInfo)
    assert info.session_id.startswith("sess_")
    assert info.filename == "my_slide.png"
    assert info.file_size == len(img_bytes)
    assert info.file_type == "png"
    assert info.page_count == 1
    assert info.input_path.exists()
    assert info.input_path.read_bytes() == img_bytes

    # Retrieval check
    retrieved = manager.get_session(info.session_id)
    assert retrieved is not None
    assert retrieved.session_id == info.session_id


def test_unsupported_file_extension_rejected(tmp_path: Path) -> None:
    manager = SessionManager(base_dir=tmp_path)
    with pytest.raises(ValueError, match="Unsupported file format"):
        manager.create_session("malicious.exe", b"MZbinary")

    with pytest.raises(ValueError, match="Unsupported file format"):
        manager.create_session("notes.txt", b"plain text")


def test_create_session_pdf_metadata(tmp_path: Path) -> None:
    import fitz

    # Create a 2-page minimal PDF
    doc = fitz.open()
    doc.new_page(width=300, height=200)
    doc.new_page(width=300, height=200)
    pdf_bytes = doc.tobytes()
    doc.close()

    manager = SessionManager(base_dir=tmp_path)
    info = manager.create_session("doc.pdf", pdf_bytes)
    assert info.file_type == "pdf"
    assert info.page_count == 2
    assert info.to_dict()["preview_url"] == f"/api/preview/{info.session_id}/page_0"
