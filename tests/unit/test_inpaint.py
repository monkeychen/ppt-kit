from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pptkit.adapters.ocr import AppleVisionOCRAdapter
from pptkit.raster.inpaint import inpaint_text_regions, verify_background_cleanliness


def test_tiered_inpaint_removes_text_leaves_less_than_2pct_chars(tmp_path: Path) -> None:
    img = Image.new("RGB", (1280, 720), color=(251, 248, 241))
    draw = ImageDraw.Draw(img)

    # Colored container capsule + non-text icon region
    draw.rounded_rectangle([100, 100, 520, 180], radius=20, fill=(232, 122, 36))
    draw.rectangle([100, 350, 260, 500], fill=(40, 110, 190))

    font_path = "/System/Library/Fonts/STHeiti Medium.ttc"
    font = (
        ImageFont.truetype(font_path, 42) if Path(font_path).exists() else ImageFont.load_default()
    )
    draw.text((140, 118), "需要一台电脑", fill=(255, 255, 255), font=font)
    draw.text((320, 380), "一台电脑 | 内存不要低于16个G", fill=(25, 25, 25), font=font)

    orig_path = tmp_path / "orig.png"
    img.save(orig_path)

    ocr = AppleVisionOCRAdapter()
    boxes = ocr.recognize(orig_path, clean=False)
    orig_chars = sum(len(b.text) for b in boxes)
    assert orig_chars >= 15

    cleaned_img = inpaint_text_regions(img, boxes)
    cleaned_path = tmp_path / "cleaned.png"
    cleaned_img.save(cleaned_path)

    # Non-text icon area [100, 350, 260, 500] must be 100% untouched
    arr_orig = np.asarray(img)
    arr_clean = np.asarray(cleaned_img)
    assert np.array_equal(arr_orig[360:490, 110:250], arr_clean[360:490, 110:250])

    # OCR re-check on cleaned background must detect <= 2% of original characters (AC7.3)
    ratio = verify_background_cleanliness(cleaned_path, orig_chars, ocr)
    assert ratio <= 0.02
