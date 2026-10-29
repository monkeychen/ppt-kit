from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from PIL import Image

from pptkit.adapters.ocr import OCREngineType, get_ocr_adapter
from pptkit.common.units import emu_to_pt, page_size_to_emu, px_to_emu
from pptkit.ir.models import (
    Background,
    BBox,
    ImageElement,
    Paragraph,
    PresentationIR,
    ShapeElement,
    SlideElement,
    SlideIR,
    TextBoxElement,
)
from pptkit.raster.inpaint import inpaint_text_regions
from pptkit.raster.layers import extract_image_layers
from pptkit.raster.refiner import refine_slide_textboxes
from pptkit.raster.shapes import extract_raster_shapes
from pptkit.raster.table import extract_raster_tables
from pptkit.raster.text_style import clean_title_punctuation, estimate_text_runs
from pptkit.render.metrics import compare_slide_images
from pptkit.render.renderer import render_pptx
from pptkit.writer.pptx_writer import write_pptx


@dataclass
class RasterReconstructionResult:
    slide_ir: SlideIR
    cleaned_bg_path: Path
    ssim: float | None = None
    text_region_mae: float | None = None
    heatmap_path: str | None = None
    low_confidence_ids: list[str] = field(default_factory=list)
    degraded_count: int = 0
    tables_count: int = 0
    table_cells_count: int = 0


def _infer_alignment(
    x_px: int, w_px: int, page_w_px: int, text: str
) -> Literal["left", "center", "right"]:
    # Short badge numbers ("01".."12") use center alignment inside their badge box;
    # all other text boxes start at their exact OCR left ink coordinate x_px.
    if len(text) <= 3 and text.isdigit():
        return "center"
    return "left"


def suppress_icon_pseudo_characters(
    text_boxes: list[TextBoxElement],
    images: list[ImageElement],
) -> list[TextBoxElement]:
    """Suppress isolated single-character OCR noise inside icon bounds (F28)."""
    if not images or not text_boxes:
        return text_boxes

    cleaned: list[TextBoxElement] = []
    for tb in text_boxes:
        full_text = "".join(r.text for p in tb.paragraphs for r in p.runs).strip()
        if len(full_text) == 1:
            max_fs = max(
                (
                    r.style.font_size_pt
                    for p in tb.paragraphs
                    for r in p.runs
                    if r.style and r.style.font_size_pt is not None
                ),
                default=12.0,
            )
            # AC28.2: Large number/letter badge (>= 22pt) is protected
            is_large_badge = (
                full_text in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ①②③④⑤⑥⑦⑧⑨⑩" and max_fs >= 22.0
            )
            if not is_large_badge:
                tb_area = max(1, tb.bbox.width * tb.bbox.height)
                inside_icon = False
                for img in images:
                    ix0 = max(tb.bbox.x, img.bbox.x)
                    iy0 = max(tb.bbox.y, img.bbox.y)
                    ix1 = min(tb.bbox.x + tb.bbox.width, img.bbox.x + img.bbox.width)
                    iy1 = min(tb.bbox.y + tb.bbox.height, img.bbox.y + img.bbox.height)
                    if ix1 > ix0 and iy1 > iy0:
                        inter_area = (ix1 - ix0) * (iy1 - iy0)
                        if (inter_area / float(tb_area)) >= 0.60:
                            inside_icon = True
                            break
                if inside_icon:
                    continue

        cleaned.append(tb)

    return cleaned


def group_card_text_boxes(
    shapes: list[ShapeElement],
    text_boxes: list[TextBoxElement],
    images: list[ImageElement] | None = None,
) -> list[TextBoxElement]:
    """Group intra-card discrete textboxes into multi-paragraph flowing textboxes (F31)."""
    if not shapes or not text_boxes:
        return text_boxes

    # Filter container shapes: solid or bordered cards (rect / round_rect)
    candidate_cards = [
        s
        for s in shapes
        if s.shape_type in ("round_rect", "rect") and s.bbox.width >= 50 and s.bbox.height >= 50
    ]
    if not candidate_cards:
        return text_boxes

    # Sort cards by area ascending to favor smaller enclosing containers first
    candidate_cards.sort(key=lambda s: s.bbox.width * s.bbox.height)

    assigned_tb_ids: set[str] = set()
    grouped_results: list[TextBoxElement] = []

    for card in candidate_cards:
        tol_x = max(10, int(card.bbox.width * 0.05))
        tol_y = max(10, int(card.bbox.height * 0.05))

        enclosed_tbs: list[TextBoxElement] = []
        for tb in text_boxes:
            if tb.id in assigned_tb_ids:
                continue
            if (
                tb.bbox.x >= card.bbox.x - tol_x
                and tb.bbox.y >= card.bbox.y - tol_y
                and (tb.bbox.x + tb.bbox.width) <= (card.bbox.x + card.bbox.width + tol_x)
                and (tb.bbox.y + tb.bbox.height) <= (card.bbox.y + card.bbox.height + tol_y)
            ):
                enclosed_tbs.append(tb)

        if len(enclosed_tbs) <= 1:
            continue

        # Partition enclosed textboxes into vertical columns
        columns: list[list[TextBoxElement]] = []
        sorted_enclosed = sorted(enclosed_tbs, key=lambda tb: (tb.bbox.x, tb.bbox.y))
        for tb in sorted_enclosed:
            matched_col = None
            for col in columns:
                col_x0 = min(t.bbox.x for t in col)
                col_x1 = max(t.bbox.x + t.bbox.width for t in col)
                col_w = max(1, col_x1 - col_x0)
                horiz_inter = max(
                    0, min(col_x1, tb.bbox.x + tb.bbox.width) - max(col_x0, tb.bbox.x)
                )
                min_w = min(col_w, tb.bbox.width)
                if (horiz_inter / float(max(1, min_w))) >= 0.40 or abs(
                    tb.bbox.x - col_x0
                ) <= 0.25 * card.bbox.width:
                    matched_col = col
                    break
            if matched_col is not None:
                matched_col.append(tb)
            else:
                columns.append([tb])

        for col in columns:
            if len(col) <= 1:
                continue
            for tb in col:
                assigned_tb_ids.add(tb.id)

            col.sort(key=lambda tb: tb.bbox.y)

            merged_paragraphs: list[Paragraph] = []
            for idx_tb, tb in enumerate(col):
                if idx_tb < len(col) - 1:
                    next_tb = col[idx_tb + 1]
                    gap_emu = max(0, next_tb.bbox.y - (tb.bbox.y + tb.bbox.height))
                    gap_pt = round(emu_to_pt(gap_emu), 1)
                else:
                    gap_pt = 0.0

                for p_idx, p in enumerate(tb.paragraphs):
                    p_copy = p.model_copy(deep=True)
                    if p_idx == len(tb.paragraphs) - 1 and gap_pt > 0:
                        p_copy.space_after_pt = gap_pt
                    merged_paragraphs.append(p_copy)

            min_x = min(tb.bbox.x for tb in col)
            min_y = min(tb.bbox.y for tb in col)
            max_r = max(tb.bbox.x + tb.bbox.width for tb in col)
            max_b = max(tb.bbox.y + tb.bbox.height for tb in col)

            grouped_results.append(
                TextBoxElement(
                    id=col[0].id,
                    bbox=BBox(x=min_x, y=min_y, width=max_r - min_x, height=max_b - min_y),
                    z_order=min(tb.z_order for tb in col),
                    confidence=min(tb.confidence for tb in col),
                    source=col[0].source,
                    degraded=any(tb.degraded for tb in col),
                    word_wrap=True,
                    paragraphs=merged_paragraphs,
                )
            )

    for tb in text_boxes:
        if tb.id not in assigned_tb_ids:
            grouped_results.append(tb)

    return grouped_results


def reconstruct_raster_slide(
    image_path: Path | str,
    page_index: int,
    work_dir: Path | str,
    max_iter: int = 3,
    enable_render_refine: bool = True,
    candidate_fonts: list[str] | None = None,
    ocr_engine: OCREngineType = "auto",
) -> RasterReconstructionResult:
    img_p = Path(image_path).resolve()
    w_dir = Path(work_dir).resolve()
    w_dir.mkdir(parents=True, exist_ok=True)

    with Image.open(img_p) as raw_im:
        orig_img = raw_im.convert("RGB")
    width_px, height_px = orig_img.size
    width_emu, height_emu = page_size_to_emu(width_px, height_px)

    ocr = get_ocr_adapter(ocr_engine)
    cleaned_boxes = ocr.recognize(img_p, clean=True)

    # 1. Inpaint text strokes using cleaned_boxes
    text_cleaned_img = inpaint_text_regions(orig_img, cleaned_boxes)

    # 2. Extract editable tables (grid lines, cells, table inpainting)
    table_res = extract_raster_tables(
        text_cleaned_img=text_cleaned_img,
        orig_img=orig_img,
        ocr_boxes=cleaned_boxes,
        slide_width_emu=width_emu,
        slide_height_emu=height_emu,
        page_index=page_index,
        candidate_fonts=candidate_fonts,
        work_dir=w_dir,
    )

    # 3. Extract editable geometric shapes from table_res.cleaned_image
    shape_res = extract_raster_shapes(
        table_res.cleaned_image,
        slide_width_emu=width_emu,
        slide_height_emu=height_emu,
        page_index=page_index,
    )

    # 4. Extract standalone illustration / icon layers as RGBA PNGs and clear base background
    layer_res = extract_image_layers(
        shape_res.residual_image,
        work_dir=w_dir,
        slide_width_emu=width_emu,
        slide_height_emu=height_emu,
        page_index=page_index,
        embedded_crops=shape_res.embedded_crops,
    )

    cleaned_bg_path = w_dir / f"slide_{page_index:03d}_bg.png"
    layer_res.final_bg_image.save(cleaned_bg_path)

    elements: list[SlideElement] = []
    elements.extend(table_res.tables)
    elements.extend(shape_res.shapes)
    elements.extend(layer_res.images)
    elements.extend(table_res.degraded_tables)

    low_conf_ids: list[str] = []
    low_conf_ids.extend(table_res.low_confidence_ids)

    raw_tb_elements: list[TextBoxElement] = []
    for idx, box in enumerate(cleaned_boxes):
        if idx in table_res.used_box_indices:
            continue
        cleaned_text = clean_title_punctuation(box.text)
        if not cleaned_text.strip():
            continue

        x_px, y_px, w_px, h_px = box.bbox_px
        runs = estimate_text_runs(
            orig_img,
            bbox_px=box.bbox_px,
            text=cleaned_text,
            candidate_fonts=candidate_fonts,
            slide_height_emu=height_emu,
        )
        align = _infer_alignment(x_px, w_px, width_px, cleaned_text)

        # Compensate for top font leading and give horizontal headroom for left-aligned text
        y_adj_px = max(0, y_px - round(h_px * 0.08))
        if align == "center":
            padded_w_px = w_px
        else:
            padded_w_px = min(width_px - x_px, max(w_px + 10, round(w_px * 1.08)))
        padded_h_px = min(height_px - y_adj_px, h_px + 6)
        bbox_emu = BBox(
            x=max(0, px_to_emu(x_px, width_px, width_emu)),
            y=max(0, px_to_emu(y_adj_px, height_px, height_emu)),
            width=max(1, px_to_emu(padded_w_px, width_px, width_emu)),
            height=max(1, px_to_emu(padded_h_px, height_px, height_emu)),
        )
        elem_id = f"p{page_index}-tb-{idx:03d}"
        if box.confidence < 0.45:
            low_conf_ids.append(elem_id)

        tb_elem = TextBoxElement(
            id=elem_id,
            bbox=bbox_emu,
            z_order=100 + idx,
            confidence=min(1.0, max(0.0, box.confidence)),
            source="ocr",
            degraded=False,
            word_wrap=False,
            paragraphs=[
                Paragraph(
                    runs=runs,
                    align=align,
                )
            ],
        )
        raw_tb_elements.append(tb_elem)

    # 5. Suppress pseudo-characters in icons (F28)
    filtered_tbs = suppress_icon_pseudo_characters(raw_tb_elements, layer_res.images)

    # 6. Group intra-card textboxes into flowing multi-paragraph textboxes (F31)
    grouped_tbs = group_card_text_boxes(shape_res.shapes, filtered_tbs, layer_res.images)
    elements.extend(grouped_tbs)

    slide_ir = SlideIR(
        page_index=page_index,
        route="raster",
        width_emu=width_emu,
        height_emu=height_emu,
        background=Background(
            fill_type="image",
            color_hex="#FFFFFF",
            image_path=str(cleaned_bg_path),
        ),
        elements=elements,
    )

    ssim_val: float | None = None
    text_mae: float | None = None
    heatmap_str: str | None = None

    if enable_render_refine:
        tb_bboxes = [e.bbox for e in slide_ir.elements if isinstance(e, TextBoxElement)]
        eval_counter = 0

        def _eval_candidate(cand_ir: SlideIR) -> float:
            nonlocal eval_counter, text_mae, heatmap_str
            eval_counter += 1
            trial_dir = w_dir / f"iter_{eval_counter:02d}"
            trial_dir.mkdir(parents=True, exist_ok=True)
            trial_pptx = write_pptx(
                PresentationIR(
                    source_path=str(img_p),
                    width_emu=width_emu,
                    height_emu=height_emu,
                    slides=[cand_ir],
                ),
                trial_dir / "trial.pptx",
            )
            rendered = render_pptx(
                trial_pptx,
                trial_dir,
                target_size=(width_px, height_px),
            )
            hp_path = w_dir / f"slide_{page_index:03d}_heatmap.png"
            cmp = compare_slide_images(
                img_p,
                rendered.png_paths[0],
                text_bboxes=tb_bboxes,
                slide_width_emu=width_emu,
                slide_height_emu=height_emu,
                heatmap_path=hp_path,
            )
            text_mae = cmp.text_region_mae
            heatmap_str = cmp.heatmap_path
            return cmp.ssim

        slide_ir, ssim_val, _ = refine_slide_textboxes(
            slide_ir,
            eval_ssim_fn=_eval_candidate,
            max_iter=min(max_iter, 1),
        )

    total_table_cells = sum(t.rows * t.cols for t in table_res.tables)
    return RasterReconstructionResult(
        slide_ir=slide_ir,
        cleaned_bg_path=cleaned_bg_path,
        ssim=ssim_val,
        text_region_mae=text_mae,
        heatmap_path=heatmap_str,
        low_confidence_ids=low_conf_ids,
        degraded_count=len(table_res.degraded_tables),
        tables_count=len(table_res.tables),
        table_cells_count=total_table_cells,
    )
