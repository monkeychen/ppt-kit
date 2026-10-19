from pathlib import Path

import pytest

from pptkit.ir.models import (
    Background,
    BBox,
    Paragraph,
    PresentationIR,
    ShapeElement,
    SlideIR,
    TextBoxElement,
    TextRun,
    TextStyle,
)
from pptkit.render.compat import (
    check_keynote_compat,
    check_powerpoint_compat,
    check_wps_compat,
)
from pptkit.writer.pptx_writer import write_pptx


@pytest.mark.integration
def test_open_in_powerpoint_wps_keynote_no_error(tmp_path: Path) -> None:
    slide = SlideIR(
        page_index=0,
        route="vector",
        background=Background(fill_type="solid", color_hex="#FFFFFF"),
        elements=[
            ShapeElement(
                id="box-1",
                bbox=BBox(x=900000, y=900000, width=10000000, height=5000000),
                z_order=1,
                shape_type="rect",
                fill_color_hex="#EFF6FF",
                stroke_color_hex="#1D4ED8",
                stroke_width_emu=25400,
            ),
            TextBoxElement(
                id="text-1",
                bbox=BBox(x=1500000, y=1800000, width=8800000, height=2000000),
                z_order=2,
                paragraphs=[
                    Paragraph(
                        runs=[
                            TextRun(
                                text="跨软件兼容性验证：PowerPoint / Keynote / WPS",
                                style=TextStyle(
                                    font_family="PingFang SC",
                                    font_size_pt=32.0,
                                    color_hex="#1E3A8A",
                                    bold=True,
                                ),
                            )
                        ],
                        align="center",
                    )
                ],
            ),
        ],
    )
    pres = PresentationIR(source_path="compat.pdf", slides=[slide])
    pptx_path = write_pptx(pres, tmp_path / "compat.pptx")

    compat_out = Path("out/compat")
    pp_status = check_powerpoint_compat(pptx_path, compat_out)
    kn_status = check_keynote_compat(pptx_path, compat_out)
    wps_status = check_wps_compat(pptx_path, compat_out)

    assert pp_status.opened_ok and not pp_status.has_repair_or_error_dialog
    assert kn_status.opened_ok and not kn_status.has_repair_or_error_dialog
    assert wps_status.opened_ok and not wps_status.has_repair_or_error_dialog
