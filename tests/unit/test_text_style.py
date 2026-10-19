from pathlib import Path

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
    draw.rectangle([280, 180, 720, 260], fill=(232, 122, 36))

    font_path = "/System/Library/Fonts/STHeiti Medium.ttc"
    font = (
        ImageFont.truetype(font_path, 48) if Path(font_path).exists() else ImageFont.load_default()
    )
    draw.text((340, 195), "需要一台电脑", fill=(255, 255, 255), font=font)

    style_white = estimate_text_style(
        img,
        bbox_px=(340, 195, 290, 52),
        text="需要一台电脑",
    )
    assert compute_delta_e(style_white.color_hex, "#FFFFFF") <= 5.0
    assert style_white.font_family in DEFAULT_CANDIDATE_FONTS
    assert 20.0 <= style_white.font_size_pt <= 30.0

    # 2. Dark navy text (#0F172A) on light gray-blue background (#E2E8F0)
    draw.rectangle([100, 400, 1200, 600], fill=(226, 232, 240))
    draw.text((150, 440), "AI 驱动的知识管理工作流", fill=(15, 23, 42), font=font)

    style_dark = estimate_text_style(
        img,
        bbox_px=(150, 440, 560, 54),
        text="AI 驱动的知识管理工作流",
    )
    assert compute_delta_e(style_dark.color_hex, "#0F172A") <= 5.0


def test_estimate_text_runs_splits_multicolor_highlights() -> None:
    img = Image.new("RGB", (1200, 300), color=(253, 248, 242))
    draw = ImageDraw.Draw(img)
    font_path = "/System/Library/Fonts/STHeiti Medium.ttc"
    font = (
        ImageFont.truetype(font_path, 44) if Path(font_path).exists() else ImageFont.load_default()
    )

    # Draw "系统" in dark navy (#121E44) followed by "先识别文件夹" in orange (#E65C19)
    draw.text((100, 100), "系统", fill=(18, 30, 68), font=font)
    draw.text((190, 100), "先识别文件夹", fill=(230, 92, 25), font=font)

    runs = estimate_text_runs(
        img,
        bbox_px=(95, 95, 370, 58),
        text="系统先识别文件夹",
    )
    assert len(runs) == 2
    assert runs[0].text == "系统"
    assert compute_delta_e(runs[0].style.color_hex, "#121E44") <= 8.0
    assert runs[1].text == "先识别文件夹"
    assert compute_delta_e(runs[1].style.color_hex, "#E65C19") <= 8.0
