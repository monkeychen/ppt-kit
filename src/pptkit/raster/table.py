from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import (
    binary_dilation,
    binary_opening,
    label,
)

from pptkit.adapters.ocr import OCRBox
from pptkit.common.color import rgb_to_hex
from pptkit.common.units import (
    DEFAULT_SLIDE_HEIGHT_EMU,
    DEFAULT_SLIDE_WIDTH_EMU,
    EMU_PER_PT,
    px_to_emu,
)
from pptkit.ir.models import (
    BBox,
    CellBorder,
    ImageElement,
    Paragraph,
    TableCell,
    TableElement,
)
from pptkit.raster.text_style import estimate_text_runs


@dataclass
class TableExtractionResult:
    tables: list[TableElement]
    used_box_indices: set[int]
    cleaned_image: Image.Image
    degraded_tables: list[ImageElement] = field(default_factory=list)
    low_confidence_ids: list[str] = field(default_factory=list)


def _cluster_1d_coords(coords: list[int], max_gap: int = 8) -> list[int]:
    """Clusters close 1D coordinates (within max_gap) and returns sorted cluster means."""
    if not coords:
        return []
    sorted_coords = sorted(coords)
    clusters: list[list[int]] = [[sorted_coords[0]]]
    for c in sorted_coords[1:]:
        if c - clusters[-1][-1] <= max_gap:
            clusters[-1].append(c)
        else:
            clusters.append([c])
    return [int(round(float(np.mean(cl)))) for cl in clusters]


def _infer_columns_from_text(
    boxes: list[tuple[int, OCRBox]],
    table_x0: int,
    table_x1: int,
) -> list[int]:
    """Infers column divider coordinates from text box x distributions

    when vertical lines are absent.
    """
    if not boxes:
        mid = (table_x0 + table_x1) // 2
        return [table_x0, mid, table_x1]

    # Cluster left x-coordinates of text
    lefts = [b.bbox_px[0] for _, b in boxes]
    clusters = _cluster_1d_coords(lefts, max_gap=25)
    if len(clusters) < 2:
        mid = (table_x0 + table_x1) // 2
        return [table_x0, mid, table_x1]

    dividers: list[int] = [table_x0]
    for i in range(len(clusters) - 1):
        mid_point = (clusters[i] + clusters[i + 1]) // 2
        dividers.append(mid_point)
    dividers.append(table_x1)
    return dividers


def extract_raster_tables(
    text_cleaned_img: Image.Image,
    orig_img: Image.Image,
    ocr_boxes: list[OCRBox],
    slide_width_emu: int = DEFAULT_SLIDE_WIDTH_EMU,
    slide_height_emu: int = DEFAULT_SLIDE_HEIGHT_EMU,
    page_index: int = 0,
    candidate_fonts: list[str] | None = None,
    work_dir: Path | str | None = None,
) -> TableExtractionResult:
    """Detects table grid lines, assigns OCR texts to cells, in-paints table background,

    and returns TableElements.
    """
    cleaned_img = text_cleaned_img.copy()
    w_px, h_px = text_cleaned_img.size
    arr = np.array(text_cleaned_img.convert("RGB"))

    # 1. Sample global background color from outer borders
    border_px = np.concatenate(
        [
            arr[:10, :].reshape(-1, 3),
            arr[-10:, :].reshape(-1, 3),
            arr[:, :10].reshape(-1, 3),
            arr[:, -10:].reshape(-1, 3),
        ],
        axis=0,
    )
    bg_rgb = np.median(border_px, axis=0).astype(int)

    # 2. Compute edge gradients
    gray = np.array(text_cleaned_img.convert("L")).astype(float)
    grad_x = np.abs(gray[:, 1:] - gray[:, :-1]) > 18.0
    grad_x = np.pad(grad_x, ((0, 0), (0, 1)), mode="constant", constant_values=False)

    grad_y = np.abs(gray[1:, :] - gray[:-1, :]) > 18.0
    grad_y = np.pad(grad_y, ((0, 1), (0, 0)), mode="constant", constant_values=False)

    # 3. Detect horizontal and vertical grid lines
    min_h_len = max(35, int(w_px * 0.05))
    struct_h = np.ones((1, min_h_len), dtype=bool)
    h_lines = binary_opening(grad_y, structure=struct_h)

    min_v_len = max(25, int(h_px * 0.04))
    struct_v = np.ones((min_v_len, 1), dtype=bool)
    v_lines = binary_opening(grad_x, structure=struct_v)

    # 4. Connected components of grid
    grid_union = np.logical_or(h_lines, v_lines)
    combined_grid = binary_dilation(grid_union, structure=np.ones((5, 5), dtype=bool))
    lbl_res: tuple[np.ndarray, int] = label(combined_grid)  # type: ignore[assignment]
    labeled_grid, num_features = lbl_res

    tables: list[TableElement] = []
    used_box_indices: set[int] = set()
    degraded_tables: list[ImageElement] = []
    low_confidence_ids: list[str] = []

    cleaned_arr = np.array(cleaned_img)

    for f_id in range(1, num_features + 1):
        comp_mask = labeled_grid == f_id
        ys, xs = np.where(comp_mask)
        if len(ys) == 0:
            continue

        x_min, x_max = int(np.min(xs)), int(np.max(xs))
        y_min, y_max = int(np.min(ys)), int(np.max(ys))
        comp_w = x_max - x_min
        comp_h = y_max - y_min

        # Minimum table size threshold: width >= 15% and height >= 7% of slide
        if comp_w < w_px * 0.15 or comp_h < h_px * 0.07:
            continue

        # Find horizontal divider lines within this bounding box
        comp_h_lines = h_lines[y_min : y_max + 1, x_min : x_max + 1]
        row_line_sums = np.sum(comp_h_lines, axis=1)
        # Threshold: at least 30% horizontal coverage
        line_y_rel = np.where(row_line_sums >= comp_w * 0.30)[0]
        if len(line_y_rel) == 0:
            continue
        h_dividers = _cluster_1d_coords([y_min + int(y) for y in line_y_rel], max_gap=10)
        # Ensure top and bottom bounds are anchored
        if not h_dividers or abs(h_dividers[0] - y_min) > 15:
            h_dividers.insert(0, y_min)
        if abs(h_dividers[-1] - y_max) > 15:
            h_dividers.append(y_max)

        if len(h_dividers) < 3:
            # Need at least 2 rows (3 dividers)
            continue

        # Find vertical divider lines
        comp_v_lines = v_lines[y_min : y_max + 1, x_min : x_max + 1]
        col_line_sums = np.sum(comp_v_lines, axis=0)
        line_x_rel = np.where(col_line_sums >= comp_h * 0.25)[0]
        v_dividers = _cluster_1d_coords([x_min + int(x) for x in line_x_rel], max_gap=10)

        # If vertical lines exist, ensure left and right boundaries are anchored
        if len(v_dividers) >= 3:
            if abs(v_dividers[0] - x_min) > 15:
                v_dividers.insert(0, x_min)
            if abs(v_dividers[-1] - x_max) > 15:
                v_dividers.append(x_max)
        else:
            # Vertical lines not drawn; check text boxes within table region to infer columns
            candidate_boxes = [
                (idx, b)
                for idx, b in enumerate(ocr_boxes)
                if x_min <= b.bbox_px[0] + b.bbox_px[2] // 2 <= x_max
                and y_min <= b.bbox_px[1] + b.bbox_px[3] // 2 <= y_max
            ]
            v_dividers = _infer_columns_from_text(candidate_boxes, x_min, x_max)

        if len(v_dividers) < 3:
            # Need at least 2 columns
            continue

        num_rows = len(h_dividers) - 1
        num_cols = len(v_dividers) - 1

        # Check OCR boxes that fall into this grid
        cell_boxes: list[list[list[tuple[int, OCRBox]]]] = [
            [[] for _ in range(num_cols)] for _ in range(num_rows)
        ]
        table_used_indices: set[int] = set()

        for b_idx, box in enumerate(ocr_boxes):
            bx, by, bw, bh = box.bbox_px
            cx = bx + bw // 2
            cy = by + bh // 2
            if v_dividers[0] <= cx <= v_dividers[-1] and h_dividers[0] <= cy <= h_dividers[-1]:
                # Locate row
                target_r = -1
                for r in range(num_rows):
                    if h_dividers[r] <= cy < h_dividers[r + 1]:
                        target_r = r
                        break
                if target_r == -1 and cy >= h_dividers[-2]:
                    target_r = num_rows - 1

                # Locate col
                target_c = -1
                for c in range(num_cols):
                    if v_dividers[c] <= cx < v_dividers[c + 1]:
                        target_c = c
                        break
                if target_c == -1 and cx >= v_dividers[-2]:
                    target_c = num_cols - 1

                if target_r != -1 and target_c != -1:
                    cell_boxes[target_r][target_c].append((b_idx, box))
                    table_used_indices.add(b_idx)

        # Confidence verification
        cells_with_text = sum(
            1 for r in range(num_rows) for c in range(num_cols) if len(cell_boxes[r][c]) > 0
        )
        total_cells = num_rows * num_cols

        # Degradation check: if very few cells have text, or invalid shape
        table_id = f"s{page_index}-table-{len(tables) + len(degraded_tables) + 1:02d}"
        if cells_with_text < 2 and total_cells > 2:
            # Degrade table to image layer or ignore
            low_confidence_ids.append(table_id)
            continue

        # Calculate row heights and column widths in EMU
        col_widths_emu = [
            px_to_emu(v_dividers[c + 1] - v_dividers[c], w_px, slide_width_emu)
            for c in range(num_cols)
        ]
        row_heights_emu = [
            px_to_emu(h_dividers[r + 1] - h_dividers[r], h_px, slide_height_emu)
            for r in range(num_rows)
        ]
        table_w_emu = sum(col_widths_emu)
        table_h_emu = sum(row_heights_emu)
        table_x_emu = px_to_emu(v_dividers[0], w_px, slide_width_emu)
        table_y_emu = px_to_emu(h_dividers[0], h_px, slide_height_emu)

        # Build TableCell objects
        table_cells: list[list[TableCell]] = []
        for r in range(num_rows):
            row_cells: list[TableCell] = []
            c_y0 = h_dividers[r]
            c_y1 = h_dividers[r + 1]

            for c in range(num_cols):
                c_x0 = v_dividers[c]
                c_x1 = v_dividers[c + 1]

                # Sample cell fill color
                inner_crop = arr[c_y0 + 2 : c_y1 - 2, c_x0 + 2 : c_x1 - 2]
                fill_color_hex: str | None = None
                if inner_crop.size > 0:
                    med_c = np.median(inner_crop.reshape(-1, 3), axis=0).astype(int)
                    # If cell median color differs noticeably from slide background
                    if np.linalg.norm(med_c - bg_rgb) > 15.0:
                        fill_color_hex = rgb_to_hex(tuple(med_c))

                # Construct paragraphs for cell text
                cell_box_list = cell_boxes[r][c]
                paragraphs: list[Paragraph] = []
                if cell_box_list:
                    # Sort top to bottom
                    cell_box_list.sort(key=lambda t: t[1].bbox_px[1])
                    for _, b in cell_box_list:
                        runs = estimate_text_runs(
                            orig_img,
                            bbox_px=b.bbox_px,
                            text=b.text,
                            candidate_fonts=candidate_fonts,
                            slide_height_emu=slide_height_emu,
                        )
                        left_gap = b.bbox_px[0] - c_x0
                        right_gap = c_x1 - (b.bbox_px[0] + b.bbox_px[2])
                        align = "center" if abs(left_gap - right_gap) < 15 else "left"
                        paragraphs.append(Paragraph(runs=runs, align=align))

                # Cell borders
                row_cells.append(
                    TableCell(
                        row=r,
                        col=c,
                        paragraphs=paragraphs,
                        fill_color_hex=fill_color_hex,
                        border_bottom=CellBorder(
                            color_hex=rgb_to_hex((100, 116, 139)), width_emu=EMU_PER_PT
                        ),
                        border_top=CellBorder(
                            color_hex=rgb_to_hex((100, 116, 139)), width_emu=EMU_PER_PT
                        )
                        if r == 0
                        else None,
                        margin_left_emu=0,
                        margin_right_emu=0,
                        margin_top_emu=0,
                        margin_bottom_emu=0,
                        vertical_align="middle",
                    )
                )
            table_cells.append(row_cells)

        table_elem = TableElement(
            id=table_id,
            bbox=BBox(x=table_x_emu, y=table_y_emu, width=table_w_emu, height=table_h_emu),
            z_order=1,
            source="cv",
            rows=num_rows,
            cols=num_cols,
            col_widths_emu=col_widths_emu,
            row_heights_emu=row_heights_emu,
            cells=table_cells,
        )
        tables.append(table_elem)
        used_box_indices.update(table_used_indices)

        # 5. Erase table region in cleaned_arr with surrounding background
        cleaned_arr[h_dividers[0] : h_dividers[-1] + 1, v_dividers[0] : v_dividers[-1] + 1] = bg_rgb

    final_cleaned_img = Image.fromarray(cleaned_arr)
    return TableExtractionResult(
        tables=tables,
        used_box_indices=used_box_indices,
        cleaned_image=final_cleaned_img,
        degraded_tables=degraded_tables,
        low_confidence_ids=low_confidence_ids,
    )
