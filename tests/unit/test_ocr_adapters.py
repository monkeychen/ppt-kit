from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

from pptkit.adapters.ocr import (
    AppleVisionOCRAdapter,
    BaseOCRAdapter,
    RapidOCRAdapter,
    get_ocr_adapter,
)
from pptkit.ingest.loader import IngestError


def _create_sample_text_image(path: Path) -> None:
    img = Image.new("RGB", (400, 100), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((20, 30), "Hello RapidOCR 2026", fill=(0, 0, 0))
    img.save(path)


def test_base_adapter_factory_auto_selection() -> None:
    # 1. On darwin (macOS), auto should return AppleVisionOCRAdapter
    with patch("sys.platform", "darwin"):
        adapter = get_ocr_adapter("auto")
        assert isinstance(adapter, AppleVisionOCRAdapter)
        assert isinstance(adapter, BaseOCRAdapter)

    # 2. On linux / win32, auto should return RapidOCRAdapter
    with patch("sys.platform", "linux"):
        adapter_linux = get_ocr_adapter("auto")
        assert isinstance(adapter_linux, RapidOCRAdapter)
        assert isinstance(adapter_linux, BaseOCRAdapter)

    with patch("sys.platform", "win32"):
        adapter_win = get_ocr_adapter("auto")
        assert isinstance(adapter_win, RapidOCRAdapter)
        assert isinstance(adapter_win, BaseOCRAdapter)


def test_apple_vision_on_non_macos_raises_friendly_error() -> None:
    with patch("sys.platform", "win32"):
        with pytest.raises(IngestError) as exc_info:
            get_ocr_adapter("apple_vision")
        assert exc_info.value.code == "UNSUPPORTED_PLATFORM"


def test_rapid_ocr_recognize_output_format(tmp_path: Path) -> None:
    img_path = tmp_path / "test_ocr.png"
    _create_sample_text_image(img_path)

    adapter = RapidOCRAdapter()
    boxes = adapter.recognize(img_path)
    assert len(boxes) > 0
    b0 = boxes[0]
    assert "Rapid" in b0.text
    assert "2026" in b0.text
    assert len(b0.bbox_px) == 4
    x, y, w, h = b0.bbox_px
    assert x >= 0 and y >= 0 and w > 0 and h > 0
    assert 0.0 <= b0.confidence <= 1.0
