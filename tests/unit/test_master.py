from pathlib import Path

from PIL import Image

from pptkit.ir.models import (
    Background,
    BBox,
    ImageElement,
    Paragraph,
    ShapeElement,
    SlideIR,
    TextBoxElement,
    TextRun,
    TextStyle,
)
from pptkit.raster.master import induct_slide_masters


def _create_test_image(path: Path, color: tuple[int, int, int]) -> str:
    im = Image.new("RGB", (100, 100), color)
    im.save(path)
    return str(path)


def test_slide_master_clustering_title_and_content(tmp_path: Path) -> None:
    # AC33.1: Automatically cluster into title and content masters
    title_bg = _create_test_image(tmp_path / "title_bg.png", (10, 20, 50))  # Dark blue cover
    content_bg1 = _create_test_image(tmp_path / "c1_bg.png", (245, 245, 245))  # White content
    content_bg2 = _create_test_image(tmp_path / "c2_bg.png", (245, 245, 245))
    content_bg3 = _create_test_image(tmp_path / "c3_bg.png", (246, 246, 246))

    slides = [
        SlideIR(
            page_index=0,
            route="raster",
            background=Background(fill_type="image", image_path=title_bg),
            elements=[],
        ),
        SlideIR(
            page_index=1,
            route="raster",
            background=Background(fill_type="image", image_path=content_bg1),
            elements=[],
        ),
        SlideIR(
            page_index=2,
            route="raster",
            background=Background(fill_type="image", image_path=content_bg2),
            elements=[],
        ),
        SlideIR(
            page_index=3,
            route="raster",
            background=Background(fill_type="image", image_path=content_bg3),
            elements=[],
        ),
    ]

    masters, updated_slides = induct_slide_masters(slides)

    # Must produce 2 masters: title and content
    assert len(masters) == 2
    master_kinds = {m.kind for m in masters}
    assert "title" in master_kinds
    assert "content" in master_kinds

    # Title slide (page 0) uses title master
    assert updated_slides[0].master_id is not None
    title_master = next(m for m in masters if m.id == updated_slides[0].master_id)
    assert title_master.kind == "title"

    # Content slides (pages 1-3) share the single content master
    content_master_ids = {s.master_id for s in updated_slides[1:]}
    assert len(content_master_ids) == 1
    content_master = next(m for m in masters if m.id == list(content_master_ids)[0])
    assert content_master.kind == "content"


def test_extract_static_header_elements_to_master(tmp_path: Path) -> None:
    # AC33.2: Extract common header banner, logo and footer to master
    bg1 = _create_test_image(tmp_path / "b1.png", (250, 250, 250))
    bg2 = _create_test_image(tmp_path / "b2.png", (250, 250, 250))
    bg3 = _create_test_image(tmp_path / "b3.png", (250, 250, 250))
    logo_path = _create_test_image(tmp_path / "logo.png", (200, 0, 0))

    bgs = [bg1, bg2, bg3]

    def make_slide(idx: int, unique_text: str) -> SlideIR:
        # Common top header bar
        header_bar = ShapeElement(
            id=f"p{idx}-hdr",
            bbox=BBox(x=0, y=0, width=12192000, height=450000),
            shape_type="rect",
            fill_color_hex="#0052D9",
        )
        # Common logo
        logo = ImageElement(
            id=f"p{idx}-logo",
            bbox=BBox(x=11000000, y=50000, width=800000, height=350000),
            image_path=logo_path,
        )
        # Unique content per slide
        content_tb = TextBoxElement(
            id=f"p{idx}-tb",
            bbox=BBox(x=1000000, y=2000000, width=5000000, height=1000000),
            paragraphs=[
                Paragraph(runs=[TextRun(text=unique_text, style=TextStyle(font_size_pt=18.0))])
            ],
        )
        return SlideIR(
            page_index=idx,
            route="raster",
            background=Background(fill_type="image", image_path=bgs[idx - 1]),
            elements=[header_bar, logo, content_tb],
        )

    slides = [
        make_slide(1, "第一部分：任务背景"),
        make_slide(2, "第二部分：核心技术"),
        make_slide(3, "第三部分：创新成果"),
    ]

    masters, updated_slides = induct_slide_masters(slides)

    # Find content master
    content_master = masters[0]
    # Header bar and logo extracted into static_elements
    assert len(content_master.static_elements) == 2
    static_types = {e.kind for e in content_master.static_elements}
    assert "shape" in static_types
    assert "image" in static_types

    # Each slide now only retains unique content_tb, no duplicate header_bar or logo
    for s in updated_slides:
        assert len(s.elements) == 1
        assert s.elements[0].kind == "textbox"
