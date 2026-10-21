from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from pptkit.common.units import pt_to_emu
from pptkit.ir.models import Background, SlideElement, SlideIR
from pptkit.vector.drawings import parse_page_drawings
from pptkit.vector.images import parse_page_images
from pptkit.vector.text import parse_page_text


@dataclass
class VectorParseResult:
    slide_ir: SlideIR
    missing_fonts: list[str] = field(default_factory=list)
    degraded_ids: list[str] = field(default_factory=list)
    low_confidence_ids: list[str] = field(default_factory=list)


def parse_vector_pdf_page(
    pdf_path: Path | str,
    page_index: int,
    work_dir: Path | str,
) -> VectorParseResult:
    p_path = Path(pdf_path).resolve()
    w_dir = Path(work_dir).resolve()
    w_dir.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(p_path)
    try:
        if page_index < 0 or page_index >= len(doc):
            raise IndexError(f"Page index {page_index} out of range [0, {len(doc)})")
        page = doc[page_index]

        w_emu = pt_to_emu(page.rect.width)
        h_emu = pt_to_emu(page.rect.height)

        # 1. Drawings (shapes, background, degraded complex effects)
        draw_res = parse_page_drawings(page, page_index, w_dir)
        bg = draw_res.background or Background(fill_type="solid", color_hex="#FFFFFF")

        # 2. Text (paragraphs, styles, missing fonts)
        text_elements, missing_fonts = parse_page_text(page, page_index)

        # 3. Embedded images
        image_elements = parse_page_images(doc, page, page_index, w_dir)

        # Combine all elements and sort by z_order
        all_elements: list[SlideElement] = []
        all_elements.extend(draw_res.elements)
        all_elements.extend(image_elements)
        all_elements.extend(text_elements)
        all_elements.sort(key=lambda e: e.z_order)

        slide_ir = SlideIR(
            page_index=page_index,
            route="vector",
            width_emu=w_emu,
            height_emu=h_emu,
            background=bg,
            elements=all_elements,
        )

        return VectorParseResult(
            slide_ir=slide_ir,
            missing_fonts=missing_fonts,
            degraded_ids=draw_res.degraded_ids,
            low_confidence_ids=[],
        )
    finally:
        doc.close()
