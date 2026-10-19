from pathlib import Path

from PIL import Image, ImageDraw

from pptkit.common.units import DEFAULT_SLIDE_HEIGHT_EMU, DEFAULT_SLIDE_WIDTH_EMU, px_to_emu
from pptkit.ir.models import BBox
from pptkit.render.metrics import compare_slide_images


def test_ssim_mae_and_heatmap_generation(tmp_path: Path) -> None:
    width_px, height_px = 640, 360
    img_a = Image.new("RGB", (width_px, height_px), color=(250, 250, 250))
    draw_a = ImageDraw.Draw(img_a)
    draw_a.rectangle([50, 50, 300, 150], fill=(30, 60, 90))

    path_a = tmp_path / "a.png"
    img_a.save(path_a)

    text_bbox = BBox(
        x=px_to_emu(50, width_px, DEFAULT_SLIDE_WIDTH_EMU),
        y=px_to_emu(50, height_px, DEFAULT_SLIDE_HEIGHT_EMU),
        width=px_to_emu(250, width_px, DEFAULT_SLIDE_WIDTH_EMU),
        height=px_to_emu(100, height_px, DEFAULT_SLIDE_HEIGHT_EMU),
    )

    heatmap_same = tmp_path / "heatmap_same.png"
    res_same = compare_slide_images(
        path_a,
        path_a,
        text_bboxes=[text_bbox],
        slide_width_emu=DEFAULT_SLIDE_WIDTH_EMU,
        slide_height_emu=DEFAULT_SLIDE_HEIGHT_EMU,
        heatmap_path=heatmap_same,
    )
    assert res_same.ssim >= 0.9999
    assert res_same.text_region_mae == 0.0
    assert heatmap_same.exists()

    # Now create img_b with altered pixels inside the text bbox
    img_b = img_a.copy()
    draw_b = ImageDraw.Draw(img_b)
    draw_b.rectangle([50, 50, 300, 150], fill=(230, 60, 90))
    path_b = tmp_path / "b.png"
    img_b.save(path_b)

    heatmap_diff = tmp_path / "heatmap_diff.png"
    res_diff = compare_slide_images(
        path_a,
        path_b,
        text_bboxes=[text_bbox],
        slide_width_emu=DEFAULT_SLIDE_WIDTH_EMU,
        slide_height_emu=DEFAULT_SLIDE_HEIGHT_EMU,
        heatmap_path=heatmap_diff,
    )
    assert res_diff.ssim < 0.99
    assert res_diff.text_region_mae > 50.0
    assert heatmap_diff.exists()
    assert res_diff.heatmap_path == str(heatmap_diff)
