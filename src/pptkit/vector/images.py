from pathlib import Path

import pymupdf

from pptkit.common.units import pt_to_emu
from pptkit.ir.models import BBox, ImageElement


def parse_page_images(
    doc: pymupdf.Document,
    page: pymupdf.Page,
    page_index: int,
    work_dir: Path,
) -> list[ImageElement]:
    work_dir.mkdir(parents=True, exist_ok=True)
    page_area = max(1.0, page.rect.width * page.rect.height)
    image_elements: list[ImageElement] = []

    img_infos = page.get_image_info(xrefs=True)
    for idx, info in enumerate(img_infos):
        xref = info.get("xref", 0)
        if xref == 0:
            continue
        bbox = info.get("bbox")
        if not bbox:
            continue
        rect = pymupdf.Rect(bbox)
        if (rect.width * rect.height) / page_area >= 0.95:
            continue

        try:
            extracted = doc.extract_image(xref)
            img_bytes = extracted.get("image")
            img_ext = extracted.get("ext", "png")
            if not img_bytes:
                continue

            img_path = work_dir / f"embedded_img_{page_index:03d}_{idx:03d}.{img_ext}"
            img_path.write_bytes(img_bytes)

            x_emu = pt_to_emu(rect.x0)
            y_emu = pt_to_emu(rect.y0)
            w_emu = pt_to_emu(rect.width)
            h_emu = pt_to_emu(rect.height)

            image_elements.append(
                ImageElement(
                    id=f"p{page_index}-img-{idx:03d}",
                    bbox=BBox(x=x_emu, y=y_emu, width=max(1, w_emu), height=max(1, h_emu)),
                    z_order=50 + idx,
                    confidence=1.0,
                    source="vector",
                    degraded=False,
                    image_path=str(img_path),
                )
            )
        except Exception:
            continue

    return image_elements
