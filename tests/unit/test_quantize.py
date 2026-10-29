from pptkit.ir.models import (
    BBox,
    Paragraph,
    PresentationIR,
    ShapeElement,
    SlideIR,
    TableCell,
    TableElement,
    TextBoxElement,
    TextRun,
    TextStyle,
)
from pptkit.raster.quantize import (
    quantize_font_size,
    quantize_palette,
    quantize_presentation,
)


def test_quantize_font_size_ladder() -> None:
    # AC34.1: Close font sizes mapped to standard typography ladder
    assert quantize_font_size(19.5) == 20.0
    assert quantize_font_size(20.2) == 20.0
    assert quantize_font_size(23.8) == 24.0
    assert quantize_font_size(14.3) == 14.0

    # Non-ladder custom large title beyond tolerance stays as is
    assert quantize_font_size(58.0) == 58.0


def test_quantize_color_palette_clustering() -> None:
    # AC34.2: Subtle color noise clustered to primary representative color
    colors = ["#0052D9", "#0053DA", "#0152D8", "#FF0000"]
    mapping = quantize_palette(colors, max_delta_e=3.5)

    rep_blue = mapping["#0052D9"]
    assert mapping["#0053DA"] == rep_blue
    assert mapping["#0152D8"] == rep_blue
    # Far color (#FF0000) not merged with blue
    assert mapping["#FF0000"] == "#FF0000"


def test_quantize_presentation_applies_to_ir() -> None:
    # Construct a mini PresentationIR with slight typography/color variations
    tb = TextBoxElement(
        id="tb-1",
        bbox=BBox(x=100, y=100, width=1000, height=200),
        paragraphs=[
            Paragraph(
                runs=[
                    TextRun(
                        text="标题",
                        style=TextStyle(
                            font_size_pt=19.6,
                            color_hex="#0053DA",
                        ),
                    ),
                    TextRun(
                        text="正文",
                        style=TextStyle(
                            font_size_pt=14.2,
                            color_hex="#0052D9",
                        ),
                    ),
                ]
            )
        ],
    )
    shape = ShapeElement(
        id="sh-1",
        bbox=BBox(x=50, y=50, width=500, height=500),
        shape_type="rect",
        fill_color_hex="#0152D8",
        stroke_color_hex="#0052D9",
    )
    table = TableElement(
        id="tbl-1",
        bbox=BBox(x=200, y=200, width=800, height=400),
        rows=1,
        cols=1,
        col_widths_emu=[800],
        row_heights_emu=[400],
        cells=[
            [
                TableCell(
                    row=0,
                    col=0,
                    fill_color_hex="#0053DA",
                    paragraphs=[
                        Paragraph(
                            runs=[
                                TextRun(
                                    text="单元格",
                                    style=TextStyle(
                                        font_size_pt=12.2,
                                        color_hex="#0052D9",
                                    ),
                                )
                            ]
                        )
                    ],
                )
            ]
        ],
    )

    slide = SlideIR(
        page_index=0,
        route="raster",
        elements=[tb, shape, table],
    )
    pres = PresentationIR(
        source_path="/fake/test.png",
        slides=[slide],
    )

    quantized_pres = quantize_presentation(pres)
    q_slide = quantized_pres.slides[0]
    q_tb = q_slide.elements[0]
    q_sh = q_slide.elements[1]
    q_tbl = q_slide.elements[2]

    assert isinstance(q_tb, TextBoxElement)
    assert isinstance(q_sh, ShapeElement)
    assert isinstance(q_tbl, TableElement)

    # Font sizes quantized
    assert q_tb.paragraphs[0].runs[0].style.font_size_pt == 20.0
    assert q_tb.paragraphs[0].runs[1].style.font_size_pt == 14.0
    assert q_tbl.cells[0][0].paragraphs[0].runs[0].style.font_size_pt == 12.0

    # Colors unified across runs, shape fills, and table cells
    blue_rep = q_sh.fill_color_hex
    assert q_sh.stroke_color_hex == blue_rep
    assert q_tb.paragraphs[0].runs[0].style.color_hex == blue_rep
    assert q_tb.paragraphs[0].runs[1].style.color_hex == blue_rep
    assert q_tbl.cells[0][0].fill_color_hex == blue_rep
    assert q_tbl.cells[0][0].paragraphs[0].runs[0].style.color_hex == blue_rep
