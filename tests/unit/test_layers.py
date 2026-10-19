from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from pptkit.common.units import DEFAULT_SLIDE_HEIGHT_EMU, DEFAULT_SLIDE_WIDTH_EMU
from pptkit.raster.layers import extract_image_layers


def test_extract_standalone_illustration_layers_with_alpha(tmp_path: Path) -> None:
    w_px, h_px = 800, 450
    bg_rgb = (250, 247, 238)
    img = Image.new("RGB", (w_px, h_px), bg_rgb)
    draw = ImageDraw.Draw(img)

    # Illustration 1: multi-color laptop-style graphic at (80, 100, 140, 110)
    draw.rectangle([80, 100, 219, 175], fill=(60, 70, 85), outline=(20, 25, 30), width=3)
    draw.rectangle([90, 110, 209, 165], fill=(140, 190, 235))
    draw.polygon([(70, 176), (229, 176), (240, 209), (60, 209)], fill=(160, 165, 170))

    # Illustration 2: multi-color folder/badge graphic at (460, 180, 120, 95)
    draw.rectangle([460, 180, 515, 198], fill=(230, 180, 60), outline=(40, 35, 25), width=2)
    draw.rectangle([460, 195, 579, 274], fill=(245, 205, 85), outline=(40, 35, 25), width=3)
    draw.ellipse([495, 215, 545, 260], fill=(210, 90, 45))

    res = extract_image_layers(
        img,
        work_dir=tmp_path,
        slide_width_emu=DEFAULT_SLIDE_WIDTH_EMU,
        slide_height_emu=DEFAULT_SLIDE_HEIGHT_EMU,
        page_index=0,
    )

    assert len(res.images) == 2
    for img_elem in res.images:
        p = Path(img_elem.image_path)
        assert p.exists()
        with Image.open(p) as cropped:
            assert cropped.mode == "RGBA"
            rgba = np.asarray(cropped)
            # Some background corners should be transparent (alpha == 0)
            assert int(np.sum(rgba[:, :, 3] == 0)) > 20
            # Foreground pixels should be opaque (alpha == 255)
            assert int(np.sum(rgba[:, :, 3] == 255)) > 1000

    # Verify both illustrations were erased from final_bg_image
    final_arr = np.asarray(res.final_bg_image, dtype=np.float32)
    target_bg = np.array(bg_rgb, dtype=np.float32)
    assert float(np.mean(np.abs(final_arr - target_bg))) < 1.0
