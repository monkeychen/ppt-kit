from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from PIL import Image

from pptkit.adapters.ocr import OCREngineType, get_ocr_adapter
from pptkit.common.units import page_size_to_emu, px_to_emu
from pptkit.ir.models import (
    Background,
    BBox,
    Paragraph,
    PresentationIR,
    SlideElement,
    SlideIR,
    TextBoxElement,
)
from pptkit.raster.inpaint import inpaint_text_regions
from pptkit.raster.layers import extract_image_layers
from pptkit.raster.refiner import refine_slide_textboxes
from pptkit.raster.shapes import extract_raster_shapes
from pptkit.raster.table import extract_raster_tables
from pptkit.raster.text_style import estimate_text_runs
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

    for idx, box in enumerate(cleaned_boxes):
        if idx in table_res.used_box_indices:
            continue
        x_px, y_px, w_px, h_px = box.bbox_px
        runs = estimate_text_runs(
            orig_img,
            bbox_px=box.bbox_px,
            text=box.text,
            candidate_fonts=candidate_fonts,
            slide_height_emu=height_emu,
        )
        align = _infer_alignment(x_px, w_px, width_px, box.text)

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
        elements.append(tb_elem)

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
