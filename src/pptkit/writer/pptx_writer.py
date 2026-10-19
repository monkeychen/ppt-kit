from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Emu, Pt

from pptkit.common.color import hex_to_rgb
from pptkit.ir.models import (
    Background,
    ImageElement,
    PresentationIR,
    ShapeElement,
    SlideIR,
    TextBoxElement,
)

ALIGN_MAP = {
    "left": PP_ALIGN.LEFT,
    "center": PP_ALIGN.CENTER,
    "right": PP_ALIGN.RIGHT,
    "justify": PP_ALIGN.JUSTIFY,
}

SHAPE_TYPE_MAP = {
    "rect": MSO_SHAPE.RECTANGLE,
    "round_rect": MSO_SHAPE.ROUNDED_RECTANGLE,
    "ellipse": MSO_SHAPE.OVAL,
    "right_arrow": MSO_SHAPE.RIGHT_ARROW,
}


def _rgb_color(hex_str: str) -> RGBColor:
    r, g, b = hex_to_rgb(hex_str)
    return RGBColor(r, g, b)


def _set_east_asian_font(run: Any, font_family: str) -> None:
    rpr = run._r.get_or_add_rPr()
    for existing in rpr.findall("{http://schemas.openxmlformats.org/drawingml/2006/main}ea"):
        rpr.remove(existing)
    ea = OxmlElement("a:ea")
    ea.set("typeface", font_family)
    rpr.append(ea)


def _apply_background(slide: Any, bg: Background, width_emu: int, height_emu: int) -> None:
    if bg.fill_type == "image" and bg.image_path:
        pic = slide.shapes.add_picture(
            bg.image_path, Emu(0), Emu(0), Emu(width_emu), Emu(height_emu)
        )
        pic.name = "bg-image"
    else:
        fill = slide.background.fill
        fill.solid()
        fill.fore_color.rgb = _rgb_color(bg.color_hex)


def _add_textbox(slide: Any, elem: TextBoxElement) -> None:
    box = slide.shapes.add_textbox(
        Emu(elem.bbox.x),
        Emu(elem.bbox.y),
        Emu(elem.bbox.width),
        Emu(elem.bbox.height),
    )
    box.name = elem.id
    tf = box.text_frame
    tf.word_wrap = elem.word_wrap
    tf.margin_left = Emu(elem.margin_left_emu)
    tf.margin_right = Emu(elem.margin_right_emu)
    tf.margin_top = Emu(elem.margin_top_emu)
    tf.margin_bottom = Emu(elem.margin_bottom_emu)

    for p_idx, para_ir in enumerate(elem.paragraphs):
        p = tf.paragraphs[0] if p_idx == 0 else tf.add_paragraph()
        p.alignment = ALIGN_MAP[para_ir.align]
        if para_ir.line_spacing_pt is not None:
            p.line_spacing = Pt(para_ir.line_spacing_pt)
        if para_ir.space_after_pt > 0:
            p.space_after = Pt(para_ir.space_after_pt)

        for run_ir in para_ir.runs:
            run = p.add_run()
            run.text = run_ir.text
            font = run.font
            font.name = run_ir.style.font_family
            font.size = Pt(run_ir.style.font_size_pt)
            font.bold = run_ir.style.bold
            font.italic = run_ir.style.italic
            font.underline = run_ir.style.underline
            font.color.rgb = _rgb_color(run_ir.style.color_hex)
            _set_east_asian_font(run, run_ir.style.font_family)


def _apply_fill_and_stroke(shape: Any, elem: ShapeElement) -> None:
    if elem.fill_color_hex:
        shape.fill.solid()
        shape.fill.fore_color.rgb = _rgb_color(elem.fill_color_hex)
    else:
        shape.fill.background()

    if elem.stroke_color_hex and elem.stroke_width_emu > 0:
        shape.line.color.rgb = _rgb_color(elem.stroke_color_hex)
        shape.line.width = Emu(elem.stroke_width_emu)
    else:
        shape.line.fill.background()


def _add_shape(slide: Any, elem: ShapeElement) -> None:
    b = elem.bbox
    if elem.shape_type == "line":
        pts = elem.points_emu or [(b.x, b.y), (b.x + b.width, b.y + b.height)]
        conn = slide.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT,
            Emu(pts[0][0]),
            Emu(pts[0][1]),
            Emu(pts[-1][0]),
            Emu(pts[-1][1]),
        )
        conn.name = elem.id
        if elem.stroke_color_hex:
            conn.line.color.rgb = _rgb_color(elem.stroke_color_hex)
        conn.line.width = Emu(max(elem.stroke_width_emu, 1))
        return

    if elem.shape_type == "freeform" and elem.points_emu and len(elem.points_emu) >= 3:
        x0, y0 = elem.points_emu[0]
        builder = slide.shapes.build_freeform(Emu(x0), Emu(y0))
        builder.add_line_segments(
            [(Emu(px), Emu(py)) for px, py in elem.points_emu[1:]], close=True
        )
        shape = builder.convert_to_shape()
        shape.name = elem.id
        _apply_fill_and_stroke(shape, elem)
        return

    mso_type = SHAPE_TYPE_MAP.get(elem.shape_type, MSO_SHAPE.RECTANGLE)
    shape = slide.shapes.add_shape(mso_type, Emu(b.x), Emu(b.y), Emu(b.width), Emu(b.height))
    shape.name = elem.id
    if elem.shape_type == "round_rect" and len(shape.adjustments) > 0:
        shape.adjustments[0] = elem.corner_radius_ratio
    _apply_fill_and_stroke(shape, elem)


def _add_image(slide: Any, elem: ImageElement) -> None:
    b = elem.bbox
    pic = slide.shapes.add_picture(elem.image_path, Emu(b.x), Emu(b.y), Emu(b.width), Emu(b.height))
    pic.name = elem.id


def _write_slide(pres: Any, slide_ir: SlideIR) -> None:
    blank_layout = pres.slide_layouts[6]
    slide = pres.slides.add_slide(blank_layout)
    _apply_background(slide, slide_ir.background, slide_ir.width_emu, slide_ir.height_emu)

    sorted_elements = sorted(slide_ir.elements, key=lambda e: e.z_order)
    for elem in sorted_elements:
        if isinstance(elem, TextBoxElement):
            _add_textbox(slide, elem)
        elif isinstance(elem, ShapeElement):
            _add_shape(slide, elem)
        elif isinstance(elem, ImageElement):
            _add_image(slide, elem)


def write_pptx(ir: PresentationIR, output_path: Path | str) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    pres = Presentation()
    pres.slide_width = Emu(ir.width_emu)
    pres.slide_height = Emu(ir.height_emu)

    for slide_ir in ir.slides:
        _write_slide(pres, slide_ir)

    pres.save(str(out))
    return out
