from pathlib import Path

import pytest

from pptkit.common.units import DEFAULT_SLIDE_HEIGHT_EMU, DEFAULT_SLIDE_WIDTH_EMU
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
from pptkit.render.metrics import compare_slide_images
from pptkit.render.renderer import render_with_powerpoint
from pptkit.writer.pptx_writer import write_pptx


@pytest.mark.integration
def test_powerpoint_render_repeatability_ssim(tmp_path: Path) -> None:
    slide = SlideIR(
        page_index=0,
        route="vector",
        background=Background(fill_type="solid", color_hex="#F8FAFC"),
        elements=[
            ShapeElement(
                id="card-1",
                bbox=BBox(x=800000, y=800000, width=10500000, height=5200000),
                z_order=1,
                shape_type="round_rect",
                fill_color_hex="#E2E8F0",
                stroke_color_hex="#475569",
                stroke_width_emu=12700,
                corner_radius_ratio=0.08,
            ),
            TextBoxElement(
                id="title-1",
                bbox=BBox(x=1200000, y=1500000, width=9600000, height=1500000),
                z_order=2,
                paragraphs=[
                    Paragraph(
                        runs=[
                            TextRun(
                                text="PowerPoint 渲染一致性基准测试",
                                style=TextStyle(
                                    font_family="PingFang SC",
                                    font_size_pt=36.0,
                                    color_hex="#0F172A",
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
    pres = PresentationIR(source_path="repeat.pdf", slides=[slide])
    pptx_path = write_pptx(pres, tmp_path / "repeat.pptx")

    run1 = render_with_powerpoint(pptx_path, tmp_path / "run1", target_size=(1920, 1080))
    run2 = render_with_powerpoint(pptx_path, tmp_path / "run2", target_size=(1920, 1080))

    heatmap = tmp_path / "repeat_diff.png"
    cmp_res = compare_slide_images(
        run1.png_paths[0],
        run2.png_paths[0],
        text_bboxes=[
            BBox(x=1200000, y=1500000, width=9600000, height=1500000),
        ],
        slide_width_emu=DEFAULT_SLIDE_WIDTH_EMU,
        slide_height_emu=DEFAULT_SLIDE_HEIGHT_EMU,
        heatmap_path=heatmap,
    )

    assert 1.0 - cmp_res.ssim < 0.001
    assert cmp_res.text_region_mae < 0.1
    assert heatmap.exists()
