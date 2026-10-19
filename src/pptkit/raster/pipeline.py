from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from PIL import Image

from pptkit.adapters.ocr import AppleVisionOCRAdapter, clean_ocr_boxes
from pptkit.common.units import page_size_to_emu, px_to_emu
from pptkit.ir.models import (
    Background,
    BBox,
    Paragraph,
    PresentationIR,
    SlideElement,
    SlideIR,
    TextBoxElement,
    TextRun,
)
from pptkit.raster.inpaint import inpaint_text_regions
from pptkit.raster.refiner import refine_slide_textboxes
from pptkit.raster.text_style import estimate_text_style
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
) -> RasterReconstructionResult:
    img_p = Path(image_path).resolve()
    w_dir = Path(work_dir).resolve()
    w_dir.mkdir(parents=True, exist_ok=True)

    with Image.open(img_p) as raw_im:
        orig_img = raw_im.convert("RGB")
    width_px, height_px = orig_img.size
    width_emu, height_emu = page_size_to_emu(width_px, height_px)

    ocr = AppleVisionOCRAdapter()
    raw_boxes = ocr.recognize(img_p, clean=False)
    cleaned_boxes = clean_ocr_boxes(raw_boxes)

    # Inpaint using cleaned_boxes so stray icons and divider lines outside text are preserved
    cleaned_bg_img = inpaint_text_regions(orig_img, cleaned_boxes)
    cleaned_bg_path = w_dir / f"slide_{page_index:03d}_bg.png"
    cleaned_bg_img.save(cleaned_bg_path)

    elements: list[SlideElement] = []
    low_conf_ids: list[str] = []

    for idx, box in enumerate(cleaned_boxes):
        x_px, y_px, w_px, h_px = box.bbox_px
        style = estimate_text_style(
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
            z_order=idx + 1,
            confidence=min(1.0, max(0.0, box.confidence)),
            source="ocr",
            degraded=False,
            word_wrap=False,
            paragraphs=[
                Paragraph(
                    runs=[TextRun(text=box.text, style=style)],
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

    return RasterReconstructionResult(
        slide_ir=slide_ir,
        cleaned_bg_path=cleaned_bg_path,
        ssim=ssim_val,
        text_region_mae=text_mae,
        heatmap_path=heatmap_str,
        low_confidence_ids=low_conf_ids,
    )
