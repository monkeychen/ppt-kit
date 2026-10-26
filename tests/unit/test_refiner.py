from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from pptkit.ir.models import BBox, Paragraph, SlideIR, TextBoxElement, TextRun, TextStyle
from pptkit.raster.pipeline import reconstruct_raster_slide
from pptkit.raster.refiner import refine_slide_textboxes


def test_iterative_refiner_monotonic_ssim_and_max_iter(tmp_path: Path) -> None:
    img = Image.new("RGB", (1280, 720), color=(251, 248, 241))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=44)
    except TypeError:
        font = ImageFont.load_default()
    draw.text((120, 140), "STEP BY STEP AI WORKFLOW GUIDE", fill=(20, 20, 20), font=font)
    img_path = tmp_path / "slide.png"
    img.save(img_path)

    res = reconstruct_raster_slide(
        img_path,
        page_index=0,
        work_dir=tmp_path / "work",
        max_iter=2,
        enable_render_refine=False,
    )
    assert isinstance(res.slide_ir, SlideIR)
    tbs = [e for e in res.slide_ir.elements if isinstance(e, TextBoxElement)]
    assert len(tbs) >= 1
    assert Path(res.cleaned_bg_path).exists()

    # Verify refiner enforces max_iter and strictly monotonic non-decreasing SSIM (AC7.4)
    calls: list[int] = []

    def fake_eval_fn(candidate_ir: SlideIR) -> float:
        calls.append(1)
        first_tb = next(e for e in candidate_ir.elements if isinstance(e, TextBoxElement))
        pt = first_tb.paragraphs[0].runs[0].style.font_size_pt
        # Peak SSIM around pt=25.0
        return 0.95 - abs(pt - 25.0) * 0.01

    initial_slide = SlideIR(
        page_index=0,
        route="raster",
        elements=[
            TextBoxElement(
                id="tb-0",
                bbox=BBox(x=1000000, y=1000000, width=6000000, height=800000),
                z_order=1,
                paragraphs=[
                    Paragraph(
                        runs=[
                            TextRun(
                                text="测试微调",
                                style=TextStyle(font_size_pt=23.0, color_hex="#141414"),
                            )
                        ]
                    )
                ],
            )
        ],
    )
    init_score = fake_eval_fn(initial_slide)
    refined_ir, final_score, iters = refine_slide_textboxes(
        initial_slide, eval_ssim_fn=fake_eval_fn, max_iter=2
    )
    assert iters == 2
    assert final_score >= init_score
    refined_tb = next(e for e in refined_ir.elements if isinstance(e, TextBoxElement))
    assert refined_tb.paragraphs[0].runs[0].style.font_size_pt == 25.0
