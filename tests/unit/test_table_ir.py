import pytest
from pydantic import ValidationError

from pptkit.ir.models import (
    BBox,
    CellBorder,
    Paragraph,
    SlideIR,
    TableCell,
    TableElement,
    TextRun,
    TextStyle,
)


def _make_sample_table() -> TableElement:
    c00 = TableCell(
        row=0,
        col=0,
        paragraphs=[
            Paragraph(
                runs=[
                    TextRun(
                        text="表头 A",
                        style=TextStyle(font_size_pt=14.0, color_hex="#FFFFFF", bold=True),
                    )
                ],
                align="center",
            )
        ],
        fill_color_hex="#2563EB",
        border_bottom=CellBorder(color_hex="#1E40AF", width_emu=25400),
    )
    c01 = TableCell(
        row=0,
        col=1,
        paragraphs=[
            Paragraph(
                runs=[
                    TextRun(
                        text="表头 B",
                        style=TextStyle(font_size_pt=14.0, color_hex="#FFFFFF", bold=True),
                    )
                ],
                align="center",
            )
        ],
        fill_color_hex="#2563EB",
        border_bottom=CellBorder(color_hex="#1E40AF", width_emu=25400),
    )
    c10 = TableCell(
        row=1,
        col=0,
        paragraphs=[
            Paragraph(
                runs=[
                    TextRun(
                        text="数据 1",
                        style=TextStyle(font_size_pt=12.0, color_hex="#1F2937"),
                    )
                ],
                align="left",
            )
        ],
        fill_color_hex="#F9FAFB",
    )
    c11 = TableCell(
        row=1,
        col=1,
        paragraphs=[
            Paragraph(
                runs=[
                    TextRun(
                        text="数据 2",
                        style=TextStyle(font_size_pt=12.0, color_hex="#1F2937"),
                    )
                ],
                align="right",
            )
        ],
        fill_color_hex="#FFFFFF",
    )

    return TableElement(
        id="table-01",
        bbox=BBox(x=100000, y=200000, width=8000000, height=4000000),
        z_order=1,
        rows=2,
        cols=2,
        col_widths_emu=[4000000, 4000000],
        row_heights_emu=[1500000, 2500000],
        cells=[[c00, c01], [c10, c11]],
    )


def test_table_element_validation_and_roundtrip() -> None:
    table = _make_sample_table()
    assert table.kind == "table"
    assert table.rows == 2
    assert table.cols == 2
    assert len(table.cells) == 2
    assert len(table.cells[0]) == 2
    assert table.cells[0][0].paragraphs[0].runs[0].text == "表头 A"

    # JSON roundtrip
    dumped = table.model_dump_json()
    loaded = TableElement.model_validate_json(dumped)
    assert loaded.id == "table-01"
    assert loaded.cells[0][0].fill_color_hex == "#2563EB"
    assert loaded.cells[0][0].border_bottom is not None
    assert loaded.cells[0][0].border_bottom.width_emu == 25400


def test_table_element_invalid_dimensions_raise() -> None:
    with pytest.raises(ValidationError):
        TableElement(
            id="bad-table",
            bbox=BBox(x=0, y=0, width=100, height=100),
            rows=0,  # rows must be > 0
            cols=1,
            col_widths_emu=[100],
            row_heights_emu=[100],
            cells=[],
        )


def test_slide_ir_polymorphic_deserialization_with_table() -> None:
    table = _make_sample_table()
    slide = SlideIR(
        page_index=0,
        route="vector",
        elements=[table],
    )
    slide_json = slide.model_dump_json()
    reloaded_slide = SlideIR.model_validate_json(slide_json)

    assert len(reloaded_slide.elements) == 1
    reloaded_elem = reloaded_slide.elements[0]
    assert isinstance(reloaded_elem, TableElement)
    assert reloaded_elem.kind == "table"
    assert reloaded_elem.rows == 2
    assert reloaded_elem.cells[1][1].paragraphs[0].runs[0].text == "数据 2"
