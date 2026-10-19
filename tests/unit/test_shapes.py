import numpy as np
from PIL import Image, ImageDraw

from pptkit.common.color import compute_delta_e, rgb_to_hex
from pptkit.common.units import DEFAULT_SLIDE_HEIGHT_EMU, DEFAULT_SLIDE_WIDTH_EMU, emu_to_px
from pptkit.raster.shapes import extract_raster_shapes


def _bbox_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix0, iy0 = max(ax, bx), max(ay, by)
    ix1, iy1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    union = aw * ah + bw * bh - inter
    return inter / max(union, 1)


def test_detect_solid_rect_round_rect_ellipse_line_and_arrow() -> None:
    w_px, h_px = 1200, 675
    img = Image.new("RGB", (w_px, h_px), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # 1. Solid rectangle
    gt_rect = (60, 60, 260, 140)
    draw.rectangle(
        [gt_rect[0], gt_rect[1], gt_rect[0] + gt_rect[2] - 1, gt_rect[1] + gt_rect[3] - 1],
        fill=(219, 234, 254),
    )

    # 2. Solid rounded rectangle
    gt_rrect = (380, 60, 280, 140)
    draw.rounded_rectangle(
        [gt_rrect[0], gt_rrect[1], gt_rrect[0] + gt_rrect[2] - 1, gt_rrect[1] + gt_rrect[3] - 1],
        radius=28,
        fill=(220, 252, 231),
    )

    # 3. Solid ellipse
    gt_ellipse = (740, 60, 240, 140)
    draw.ellipse(
        [
            gt_ellipse[0],
            gt_ellipse[1],
            gt_ellipse[0] + gt_ellipse[2] - 1,
            gt_ellipse[1] + gt_ellipse[3] - 1,
        ],
        fill=(252, 231, 243),
    )

    # 4. Horizontal line
    gt_line = (60, 280, 420, 6)
    draw.rectangle(
        [gt_line[0], gt_line[1], gt_line[0] + gt_line[2] - 1, gt_line[1] + gt_line[3] - 1],
        fill=(51, 65, 85),
    )

    # 5. Right arrow
    gt_arrow = (60, 360, 240, 90)
    ax, ay, aw, ah = gt_arrow
    shaft_h = 38
    sy0 = ay + (ah - shaft_h) // 2
    sy1 = sy0 + shaft_h
    head_x = ax + int(aw * 0.62)
    draw.polygon(
        [
            (ax, sy0),
            (head_x, sy0),
            (head_x, ay),
            (ax + aw - 1, ay + ah // 2),
            (head_x, ay + ah - 1),
            (head_x, sy1),
            (ax, sy1),
        ],
        fill=(234, 179, 8),
    )

    res = extract_raster_shapes(
        img,
        slide_width_emu=DEFAULT_SLIDE_WIDTH_EMU,
        slide_height_emu=DEFAULT_SLIDE_HEIGHT_EMU,
    )

    detected_types = {s.shape_type for s in res.shapes}
    assert {"rect", "round_rect", "ellipse", "line", "right_arrow"}.issubset(detected_types)

    for gt_box, expected_type, expected_rgb in [
        (gt_rect, "rect", (219, 234, 254)),
        (gt_rrect, "round_rect", (220, 252, 231)),
        (gt_ellipse, "ellipse", (252, 231, 243)),
        (gt_line, "line", (51, 65, 85)),
        (gt_arrow, "right_arrow", (234, 179, 8)),
    ]:
        matches = [s for s in res.shapes if s.shape_type == expected_type]
        assert len(matches) >= 1
        best = max(
            matches,
            key=lambda s: _bbox_iou(
                gt_box,
                (
                    emu_to_px(s.bbox.x, w_px, DEFAULT_SLIDE_WIDTH_EMU),
                    emu_to_px(s.bbox.y, h_px, DEFAULT_SLIDE_HEIGHT_EMU),
                    emu_to_px(s.bbox.width, w_px, DEFAULT_SLIDE_WIDTH_EMU),
                    emu_to_px(s.bbox.height, h_px, DEFAULT_SLIDE_HEIGHT_EMU),
                ),
            ),
        )
        pred_box = (
            emu_to_px(best.bbox.x, w_px, DEFAULT_SLIDE_WIDTH_EMU),
            emu_to_px(best.bbox.y, h_px, DEFAULT_SLIDE_HEIGHT_EMU),
            emu_to_px(best.bbox.width, w_px, DEFAULT_SLIDE_WIDTH_EMU),
            emu_to_px(best.bbox.height, h_px, DEFAULT_SLIDE_HEIGHT_EMU),
        )
        assert _bbox_iou(gt_box, pred_box) >= 0.85
        color_hex = best.stroke_color_hex if expected_type == "line" else best.fill_color_hex
        assert color_hex is not None
        assert compute_delta_e(color_hex, rgb_to_hex(expected_rgb)) <= 5.0

    # Verify extracted shapes were erased from residual_image
    res_arr = np.asarray(res.residual_image, dtype=np.float32)
    assert float(np.mean(np.abs(res_arr - 255.0))) < 1.0


def test_low_confidence_irregular_blob_degrades_gracefully() -> None:
    w_px, h_px = 600, 400
    arr = np.full((h_px, w_px, 3), 255, dtype=np.uint8)
    rng = np.random.default_rng(42)
    # Create an irregular multi-color L/U-shaped noisy illustration region
    arr[80:260, 100:145] = rng.integers(20, 220, size=(180, 45, 3), dtype=np.uint8)
    arr[215:260, 100:280] = rng.integers(20, 220, size=(45, 180, 3), dtype=np.uint8)
    arr[80:260, 235:280] = rng.integers(20, 220, size=(180, 45, 3), dtype=np.uint8)
    img = Image.fromarray(arr)

    res = extract_raster_shapes(
        img,
        slide_width_emu=DEFAULT_SLIDE_WIDTH_EMU,
        slide_height_emu=DEFAULT_SLIDE_HEIGHT_EMU,
    )
    assert len(res.shapes) == 0
    assert len(res.degraded_ids) >= 1
    # Ensure the irregular region was preserved in residual_image for layer extraction
    res_arr = np.asarray(res.residual_image)
    assert np.array_equal(res_arr[80:260, 100:280], arr[80:260, 100:280])
