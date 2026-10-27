from pptkit.gui.elements import extract_slide_elements_summary
from pptkit.ir.models import (
    Background,
    BBox,
    Paragraph,
    SlideIR,
    TextBoxElement,
    TextRun,
    TextStyle,
)


def test_slide_ir_elements_to_normalized_pct() -> None:
    width_emu = 1000000
    height_emu = 500000

    tb = TextBoxElement(
        id="elem_01",
        bbox=BBox(x=100000, y=50000, width=300000, height=100000),
        confidence=0.45,
        source="ocr",
        degraded=False,
        paragraphs=[
            Paragraph(
                runs=[
                    TextRun(
                        text="Hello World",
                        style=TextStyle(font_size_pt=14.0),
                    )
                ]
            )
        ],
    )

    slide = SlideIR(
        page_index=0,
        route="raster",
        width_emu=width_emu,
        height_emu=height_emu,
        background=Background(color_hex="#FFFFFF"),
        elements=[tb],
    )

    summary = extract_slide_elements_summary(slide)
    assert summary["page_index"] == 0
    assert summary["width_emu"] == width_emu
    assert summary["height_emu"] == height_emu
    assert len(summary["elements"]) == 1

    e = summary["elements"][0]
    assert e["id"] == "elem_01"
    assert e["kind"] == "textbox"
    assert e["text"] == "Hello World"
    assert e["confidence"] == 0.45
    assert not e["degraded"]
    assert e["bbox_pct"]["x"] == 10.0
    assert e["bbox_pct"]["y"] == 10.0
    assert e["bbox_pct"]["width"] == 30.0
    assert e["bbox_pct"]["height"] == 20.0
