from pathlib import Path

import pymupdf

from pptkit.ir.models import ShapeElement, TextBoxElement
from pptkit.vector.parser import parse_vector_pdf_page


def test_parse_vector_pdf_shapes_text_and_paragraphs(tmp_path: Path) -> None:
    pdf_path = tmp_path / "vector_sample.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=960, height=540)

    # 1. Background full-page fill
    page.draw_rect(pymupdf.Rect(0, 0, 960, 540), fill=(1.0, 1.0, 1.0), color=None)

    # 2. Rect with fill & stroke
    page.draw_rect(
        pymupdf.Rect(80, 80, 320, 200),
        fill=(0.2, 0.4, 0.8),
        color=(0.1, 0.2, 0.4),
        width=2,
    )

    # 3. Round rect
    page.draw_rect(
        pymupdf.Rect(360, 80, 600, 200),
        radius=0.15,
        fill=(0.9, 0.5, 0.1),
        color=None,
    )

    # 4. Straight line
    page.draw_line(pymupdf.Point(80, 240), pymupdf.Point(400, 240), color=(1.0, 0.0, 0.0), width=2)

    # 5. Ellipse
    page.draw_oval(pymupdf.Rect(640, 80, 780, 200), fill=(0.2, 0.8, 0.2))

    # 6. Text
    page.insert_text((80, 300), "Vector Test Title", fontsize=28, color=(0.1, 0.1, 0.1))
    page.insert_text((80, 350), "Line 1 of paragraph content", fontsize=16, color=(0.2, 0.2, 0.2))
    page.insert_text((80, 375), "Line 2 of paragraph content", fontsize=16, color=(0.2, 0.2, 0.2))

    doc.save(pdf_path)
    doc.close()

    res = parse_vector_pdf_page(pdf_path, page_index=0, work_dir=tmp_path / "assets")

    assert res.slide_ir.page_index == 0
    assert res.slide_ir.route == "vector"
    assert res.slide_ir.background.fill_type == "solid"

    # Shapes check
    shapes = [e for e in res.slide_ir.elements if isinstance(e, ShapeElement)]
    shape_types = [e.shape_type for e in shapes]
    assert "rect" in shape_types
    assert "round_rect" in shape_types
    assert "line" in shape_types
    assert "ellipse" in shape_types

    # Texts check
    text_boxes = [e for e in res.slide_ir.elements if isinstance(e, TextBoxElement)]
    all_texts = []
    for tb in text_boxes:
        for p in tb.paragraphs:
            for r in p.runs:
                all_texts.append(r.text)
    joined_text = " ".join(all_texts)
    assert "Vector Test Title" in joined_text
    assert "Line 1 of paragraph content" in joined_text
    assert "Line 2 of paragraph content" in joined_text
    assert len(res.degraded_ids) == 0


def test_degrade_complex_translucent_gradient_drawing(tmp_path: Path) -> None:
    pdf_path = tmp_path / "translucent.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=960, height=540)
    # Translucent drawing with fill_opacity = 0.5
    page.draw_rect(
        pymupdf.Rect(100, 100, 300, 300),
        fill=(1.0, 0.0, 0.0),
        fill_opacity=0.5,
    )
    doc.save(pdf_path)
    doc.close()

    res = parse_vector_pdf_page(pdf_path, page_index=0, work_dir=tmp_path / "assets")
    assert len(res.degraded_ids) > 0
    degraded_imgs = [e for e in res.slide_ir.elements if getattr(e, "degraded", False)]
    assert len(degraded_imgs) > 0


def test_vector_fill_stroke_merging(tmp_path: Path) -> None:
    pdf_path = tmp_path / "fill_stroke.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=960, height=540)

    # Drawing 1: Fill only
    page.draw_rect(pymupdf.Rect(100, 100, 300, 200), fill=(0.2, 0.4, 0.8), color=None)
    # Drawing 2: Stroke only on the exact same rect
    page.draw_rect(pymupdf.Rect(100, 100, 300, 200), fill=None, color=(0.1, 0.2, 0.4), width=2)

    doc.save(pdf_path)
    doc.close()

    res = parse_vector_pdf_page(pdf_path, page_index=0, work_dir=tmp_path / "assets")
    shapes = [e for e in res.slide_ir.elements if isinstance(e, ShapeElement)]
    # Should be merged into 1 shape instead of 2 separate shapes!
    assert len(shapes) == 1
    s = shapes[0]
    assert s.fill_color_hex is not None
    assert s.stroke_color_hex is not None
