from PIL import Image, ImageDraw, ImageFont

from pptkit.common.color import compute_delta_e
from pptkit.raster.text_style import (
    DEFAULT_CANDIDATE_FONTS,
    estimate_text_runs,
    estimate_text_style,
)


def test_extract_text_color_font_size_and_bold_from_crop() -> None:
    # 1. White text on orange capsule background (#E87A24)
    img = Image.new("RGB", (1920, 1080), color=(251, 248, 241))
    draw = ImageDraw.Draw(img)
    draw.rectangle([280, 180, 800, 260], fill=(232, 122, 36))

    try:
        font = ImageFont.load_default(size=44)
    except TypeError:
        font = ImageFont.load_default()

    draw.text((320, 195), "NEED A COMPUTER", fill=(255, 255, 255), font=font)
    bbox = draw.textbbox((320, 195), "NEED A COMPUTER", font=font)
    w = int(bbox[2] - bbox[0])
    h = int(bbox[3] - bbox[1])

    style_white = estimate_text_style(
        img,
        bbox_px=(320, 195, w, h),
        text="NEED A COMPUTER",
    )
    assert compute_delta_e(style_white.color_hex, "#FFFFFF") <= 5.0
    assert style_white.font_family in DEFAULT_CANDIDATE_FONTS
    assert 10.0 <= style_white.font_size_pt <= 30.0

    # 2. Dark navy text (#0F172A) on light gray-blue background (#E2E8F0)
    draw.rectangle([100, 400, 1200, 600], fill=(226, 232, 240))
    draw.text((150, 440), "AI KNOWLEDGE WORKFLOW", fill=(15, 23, 42), font=font)
    bbox2 = draw.textbbox((150, 440), "AI KNOWLEDGE WORKFLOW", font=font)
    w2 = int(bbox2[2] - bbox2[0])
    h2 = int(bbox2[3] - bbox2[1])

    style_dark = estimate_text_style(
        img,
        bbox_px=(150, 440, w2, h2),
        text="AI KNOWLEDGE WORKFLOW",
    )
    assert compute_delta_e(style_dark.color_hex, "#0F172A") <= 5.0


def test_estimate_text_runs_splits_multicolor_highlights() -> None:
    img = Image.new("RGB", (1200, 300), color=(253, 248, 242))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=44)
    except TypeError:
        font = ImageFont.load_default()

    text1 = "SYSTEM "
    text2 = "IDENTIFY FOLDERS"
    full_text = text1 + text2

    draw.text((100, 100), text1, fill=(18, 30, 68), font=font)
    bbox1 = draw.textbbox((100, 100), text1, font=font)
    w1 = bbox1[2] - bbox1[0]
    draw.text((100 + int(w1), 100), text2, fill=(230, 92, 25), font=font)

    bbox_full = draw.textbbox((100, 100), full_text, font=font)
    x0, y0, x1, y1 = bbox_full
    w = int(x1 - x0)
    h = int(y1 - y0)

    runs = estimate_text_runs(
        img,
        bbox_px=(int(x0), int(y0), w, h),
        text=full_text,
    )
    assert len(runs) == 2
    assert runs[0].text == "SYSTEM "
    assert compute_delta_e(runs[0].style.color_hex, "#121E44") <= 8.0
    assert runs[1].text == "IDENTIFY FOLDERS"
    assert compute_delta_e(runs[1].style.color_hex, "#E65C19") <= 8.0
