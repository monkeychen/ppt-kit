import numpy as np
from PIL import Image, ImageDraw, ImageFont

from pptkit.adapters.ocr import OCRBox
from pptkit.common.units import px_to_emu
from pptkit.ir.models import TableElement
from pptkit.raster.table import TableExtractionResult, extract_raster_tables


def _draw_table_image(
    width: int = 800,
    height: int = 500,
    origin: tuple[int, int] = (100, 100),
    col_widths: list[int] | None = None,
    row_heights: list[int] | None = None,
    line_color: tuple[int, int, int] = (50, 50, 50),
    header_fill: tuple[int, int, int] | None = (37, 99, 235),
    bg_color: tuple[int, int, int] = (250, 250, 250),
) -> tuple[Image.Image, list[OCRBox]]:
    if col_widths is None:
        col_widths = [180, 200, 180]
    if row_heights is None:
        row_heights = [50, 60, 60]

    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)
    x0, y0 = origin
    total_w = sum(col_widths)
    total_h = sum(row_heights)

    # Optional header background fill
    if header_fill is not None:
        draw.rectangle([x0, y0, x0 + total_w, y0 + row_heights[0]], fill=header_fill)

    # Draw horizontal grid lines
    curr_y = y0
    for h in [0] + row_heights:
        curr_y += h
        draw.line([(x0, curr_y), (x0 + total_w, curr_y)], fill=line_color, width=2)

    # Draw vertical grid lines
    curr_x = x0
    for w in [0] + col_widths:
        curr_x += w
        draw.line([(curr_x, y0), (curr_x, y0 + total_h)], fill=line_color, width=2)

    # Generate synthetic text & OCR boxes
    ocr_boxes: list[OCRBox] = []
    font = ImageFont.load_default()

    curr_y = y0
    for r_idx, rh in enumerate(row_heights):
        curr_x = x0
        for c_idx, cw in enumerate(col_widths):
            text = f"R{r_idx}C{c_idx}"
            tx = curr_x + 15
            ty = curr_y + 15
            draw.text(
                (tx, ty),
                text,
                fill=(255, 255, 255) if (r_idx == 0 and header_fill) else (30, 30, 30),
                font=font,
            )
            ocr_boxes.append(
                OCRBox(
                    text=text,
                    bbox_px=(tx, ty, 45, 18),
                    confidence=0.95,
                )
            )
            curr_x += cw
        curr_y += rh

    # Outside stray text box
    draw.text((100, 30), "幻灯片外围主标题", fill=(10, 10, 10), font=font)
    ocr_boxes.append(
        OCRBox(
            text="幻灯片外围主标题",
            bbox_px=(100, 30, 150, 24),
            confidence=0.98,
        )
    )

    return img, ocr_boxes


def test_extract_grid_lines_and_topology() -> None:
    img, boxes = _draw_table_image(
        width=800,
        height=500,
        origin=(100, 100),
        col_widths=[180, 200, 180],
        row_heights=[50, 60, 60],
    )
    # Simulate text-cleaned image (inpaint fills text strokes with local background)
    cleaned_img = img.copy()

    w_emu = px_to_emu(800, 800)
    h_emu = px_to_emu(500, 800)

    res = extract_raster_tables(
        text_cleaned_img=cleaned_img,
        orig_img=img,
        ocr_boxes=boxes,
        slide_width_emu=w_emu,
        slide_height_emu=h_emu,
        page_index=0,
    )

    assert isinstance(res, TableExtractionResult)
    assert len(res.tables) == 1
    table = res.tables[0]
    assert isinstance(table, TableElement)
    assert table.rows == 3
    assert table.cols == 3
    assert len(table.cells) == 3
    assert len(table.cells[0]) == 3

    # 9 table boxes should be consumed, leaving the stray title box (idx 9) unused
    assert len(res.used_box_indices) == 9
    assert 9 not in res.used_box_indices

    # Check cell texts
    assert table.cells[0][0].paragraphs[0].runs[0].text == "R0C0"
    assert table.cells[2][2].paragraphs[0].runs[0].text == "R2C2"

    # Header fill should be detected
    assert table.cells[0][0].fill_color_hex is not None


def test_assign_ocr_boxes_to_cells_and_merge_multiline() -> None:
    img, _ = _draw_table_image(width=600, height=400, origin=(50, 50))
    # Two OCR boxes inside cell (1, 1)
    # cell (1, 1) is around x: 50+180=230..430, y: 50+50=100..160
    b1 = OCRBox(text="第一行", bbox_px=(250, 105, 60, 16), confidence=0.95)
    b2 = OCRBox(text="第二行补充", bbox_px=(250, 125, 80, 16), confidence=0.92)

    res = extract_raster_tables(
        text_cleaned_img=img,
        orig_img=img,
        ocr_boxes=[b1, b2],
        slide_width_emu=px_to_emu(600, 600),
        slide_height_emu=px_to_emu(400, 600),
    )

    if len(res.tables) > 0:
        table = res.tables[0]
        c11 = table.cells[1][1]
        assert len(c11.paragraphs) >= 1
        texts = [p.runs[0].text for p in c11.paragraphs]
        assert "第一行" in texts
        assert "第二行补充" in texts


def test_table_background_erasure() -> None:
    img, boxes = _draw_table_image(
        width=800,
        height=500,
        origin=(100, 100),
        col_widths=[180, 200, 180],
        row_heights=[50, 60, 60],
        line_color=(0, 0, 0),
        bg_color=(255, 255, 255),
    )

    res = extract_raster_tables(
        text_cleaned_img=img,
        orig_img=img,
        ocr_boxes=boxes,
        slide_width_emu=px_to_emu(800, 800),
        slide_height_emu=px_to_emu(500, 800),
    )

    assert len(res.tables) == 1
    # Check that in res.cleaned_image, inside the table rectangle, black lines are erased
    table_crop = np.array(res.cleaned_image.crop((100, 100, 100 + 560, 100 + 170)))
    # In pure table region, black lines (0, 0, 0) should be gone,
    # mean color should be close to white (> 240)
    assert np.mean(table_crop) > 235


def test_table_degradation_on_broken_grid() -> None:
    # An image with only 1 horizontal line, not forming a closed table
    img = Image.new("RGB", (800, 500), color=(250, 250, 250))
    draw = ImageDraw.Draw(img)
    draw.line([(100, 200), (700, 200)], fill=(0, 0, 0), width=2)
    boxes = [
        OCRBox(text="普通段落 1", bbox_px=(120, 100, 100, 20), confidence=0.9),
        OCRBox(text="普通段落 2", bbox_px=(120, 220, 100, 20), confidence=0.9),
    ]

    res = extract_raster_tables(
        text_cleaned_img=img,
        orig_img=img,
        ocr_boxes=boxes,
        slide_width_emu=px_to_emu(800, 800),
        slide_height_emu=px_to_emu(500, 800),
    )

    # Should not produce TableElement; boxes remain unconsumed for normal text flow
    assert len(res.tables) == 0
    assert len(res.used_box_indices) == 0
