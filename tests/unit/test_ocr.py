import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from pptkit.adapters.ocr import AppleVisionOCRAdapter, OCRBox, clean_ocr_boxes


@pytest.mark.skipif(sys.platform != "darwin", reason="Apple Vision only supported on macOS")
def test_apple_vision_ocr_extracts_chinese_and_english_accurately(tmp_path: Path) -> None:
    img = Image.new("RGB", (1200, 675), color=(250, 248, 242))
    draw = ImageDraw.Draw(img)
    font_path = "/System/Library/Fonts/STHeiti Medium.ttc"
    font = (
        ImageFont.truetype(font_path, 44) if Path(font_path).exists() else ImageFont.load_default()
    )
    draw.text((100, 120), "如果你想用好AI你就按着一步一步做", fill=(20, 20, 20), font=font)
    draw.text((100, 240), "ChatGPT | 下载Codex，然后安装", fill=(30, 30, 30), font=font)

    img_path = tmp_path / "ocr_test.png"
    img.save(img_path)

    adapter = AppleVisionOCRAdapter()
    boxes = adapter.recognize(img_path)

    texts = " ".join(b.text for b in boxes)
    assert "如果你想用好AI" in texts
    assert "ChatGPT" in texts
    assert "Codex" in texts
    for b in boxes:
        x, y, w, h = b.bbox_px
        assert 0 <= x < 1200
        assert 0 <= y < 675
        assert w > 0 and h > 0


def test_clean_ocr_boxes_rule_heuristics() -> None:
    # Test post-processing cleaning rules (merged badge "o7 回答..." and stray star prefix "太 ")
    raw_samples = [
        OCRBox(text="o7 回答AI跟你提出的问题", bbox_px=(100, 100, 400, 40), confidence=0.5),
        OCRBox(
            text="太 现在，只需要半天时间，你已经学会使用AI了。",
            bbox_px=(200, 500, 800, 50),
            confidence=0.6,
        ),
    ]
    cleaned = clean_ocr_boxes(raw_samples)
    assert len(cleaned) == 3
    assert cleaned[0].text == "07"
    assert cleaned[1].text == "回答AI跟你提出的问题"
    assert cleaned[2].text == "现在，只需要半天时间，你已经学会使用AI了。"
