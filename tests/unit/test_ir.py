import pytest
from pydantic import ValidationError

from pptkit.ir.models import (
    Background,
    BBox,
    ImageElement,
    Paragraph,
    PresentationIR,
    ShapeElement,
    SlideIR,
    TextBoxElement,
    TextRun,
    TextStyle,
)


def test_presentation_ir_json_roundtrip_all_elements() -> None:
    tb = TextBoxElement(
        id="tb-1",
        bbox=BBox(x=100000, y=200000, width=5000000, height=1000000),
        z_order=2,
        confidence=0.98,
        source="vector",
        paragraphs=[
            Paragraph(
                runs=[
                    TextRun(
                        text="人工智能产品设计",
                        style=TextStyle(
                            font_family="PingFang SC",
                            font_size_pt=32.0,
                            color_hex="#1A2B3C",
                            bold=True,
                        ),
                    )
                ],
                align="center",
                line_spacing_pt=38.0,
            )
        ],
    )
    rect = ShapeElement(
        id="sh-1",
        bbox=BBox(x=50000, y=50000, width=3000000, height=1500000),
        z_order=1,
        shape_type="round_rect",
        fill_color_hex="#E0F0FF",
        stroke_color_hex="#0066CC",
        stroke_width_emu=12700,
        corner_radius_ratio=0.15,
    )
    freeform = ShapeElement(
        id="sh-2",
        bbox=BBox(x=400000, y=400000, width=1000000, height=1000000),
        z_order=3,
        shape_type="freeform",
        fill_color_hex="#FFCC00",
        points_emu=[(400000, 400000), (1400000, 400000), (900000, 1400000)],
    )
    img = ImageElement(
        id="im-1",
        bbox=BBox(x=0, y=0, width=12192000, height=6858000),
        z_order=0,
        image_path="assets/bg.png",
        source="fallback",
        degraded=True,
    )
    slide = SlideIR(
        page_index=0,
        route="vector",
        background=Background(fill_type="solid", color_hex="#F8FAFC"),
        elements=[img, rect, tb, freeform],
    )
    pres = PresentationIR(source_path="demo.pdf", slides=[slide])

    json_str = pres.to_json()
    restored = PresentationIR.from_json(json_str)

    assert restored == pres
    assert isinstance(restored.slides[0].elements[0], ImageElement)
    assert isinstance(restored.slides[0].elements[1], ShapeElement)
    assert isinstance(restored.slides[0].elements[2], TextBoxElement)
    assert isinstance(restored.slides[0].elements[3], ShapeElement)


def test_ir_rejects_float_or_negative_bbox() -> None:
    # Float coordinate should be rejected (strict integer EMU)
    with pytest.raises(ValidationError):
        BBox(x=100.5, y=0, width=1000, height=1000)  # type: ignore[arg-type]

    # Zero or negative width/height should be rejected
    with pytest.raises(ValidationError):
        BBox(x=0, y=0, width=0, height=1000)

    with pytest.raises(ValidationError):
        BBox(x=-1, y=0, width=1000, height=1000)
