import numpy as np

from pptkit.ir.models import (
    BBox,
    ImageElement,
    Paragraph,
    ShapeElement,
    TextBoxElement,
    TextRun,
    TextStyle,
)
from pptkit.raster.layers import filter_and_cluster_image_elements
from pptkit.raster.pipeline import group_card_text_boxes, suppress_icon_pseudo_characters
from pptkit.raster.shapes import classify_contour_shape
from pptkit.raster.text_style import clean_title_punctuation


def _make_textbox(
    text: str,
    x: int,
    y: int,
    w: int,
    h: int,
    font_size_pt: float = 14.0,
    color_hex: str = "#000000",
    bold: bool = False,
    tb_id: str = "tb-01",
) -> TextBoxElement:
    return TextBoxElement(
        id=tb_id,
        bbox=BBox(x=x, y=y, width=w, height=h),
        paragraphs=[
            Paragraph(
                runs=[
                    TextRun(
                        text=text,
                        style=TextStyle(
                            font_size_pt=font_size_pt,
                            color_hex=color_hex,
                            bold=bold,
                        ),
                    )
                ]
            )
        ],
    )


def test_clean_title_leading_and_trailing_punctuation() -> None:
    # AC30.1: Leading decorative punctuation stripped
    assert clean_title_punctuation("| 前期基础与团队优势") == "前期基础与团队优势"
    assert clean_title_punctuation("• 关键技术") == "关键技术"
    assert clean_title_punctuation("■ 核心指标") == "核心指标"

    # AC30.2: Trailing isolated connector dot or period stripped for short titles
    assert clean_title_punctuation("XX集团有限公司XX事业部。") == "XX集团有限公司XX事业部"
    # Long sentences should NOT strip full stops
    long_sentence = "面对通信网络拓扑复杂、告警风暴频发等问题，本任务通过多项技术实现自主决策。"
    assert clean_title_punctuation(long_sentence) == long_sentence

    # Metric typo with comma cleaned
    assert clean_title_punctuation("论文60+篇、专利，250+项") == "论文60+篇、专利250+项"


def test_classify_horizontal_card_defends_against_right_arrow() -> None:
    # AC29.1, AC29.2:
    # Construct a wide horizontal rectangle (e.g. 500x120) with a slight vertex imperfection
    # that could trigger arrow classification.
    h, w = 120, 500
    contour = np.array(
        [
            [[10, 0]],
            [[490, 0]],
            [[500, 10]],
            [[500, 110]],
            [[490, 120]],
            [[10, 120]],
            [[0, 110]],
            [[0, 10]],
        ],
        dtype=np.int32,
    )
    classified = classify_contour_shape(contour, w=w, h=h)
    assert classified in ("round_rect", "rect")
    assert classified != "right_arrow"


def test_filter_icon_pseudo_character_suppressed() -> None:
    # AC28.1, AC28.3:
    # An image icon is located at (1000, 1000) with size (300, 300) EMU
    icon = ImageElement(
        id="icon-1",
        bbox=BBox(x=1000, y=1000, width=300, height=300),
        image_path="/tmp/fake_icon.png",
    )
    # A single pseudo character '¢' recognized inside the icon bounds
    noise_tb = _make_textbox("¢", x=1050, y=1050, w=100, h=100, font_size_pt=12.0, tb_id="noise-1")
    # A normal text box far away
    normal_tb = _make_textbox(
        "本体约束协同决策", x=1500, y=1000, w=1200, h=300, font_size_pt=18.0, tb_id="title-1"
    )

    cleaned = suppress_icon_pseudo_characters([noise_tb, normal_tb], [icon])
    assert len(cleaned) == 1
    assert cleaned[0].id == "title-1"


def test_filter_large_number_not_suppressed() -> None:
    # AC28.2: Large number index inside a badge should NOT be suppressed
    icon = ImageElement(
        id="badge-1",
        bbox=BBox(x=500, y=500, width=400, height=400),
        image_path="/tmp/fake_badge.png",
    )
    big_number_tb = _make_textbox("1", x=600, y=600, w=200, h=200, font_size_pt=26.0, tb_id="idx-1")

    cleaned = suppress_icon_pseudo_characters([big_number_tb], [icon])
    assert len(cleaned) == 1
    assert cleaned[0].id == "idx-1"


def test_card_grouping_merges_vertical_paragraphs() -> None:
    # AC31.1, AC31.2, AC31.3:
    # A container card from x=1000, y=1000, w=3000, h=4000 EMU
    card = ShapeElement(
        id="card-1",
        bbox=BBox(x=1000, y=1000, width=3000, height=4000),
        shape_type="round_rect",
        fill_color_hex="#FFFFFF",
    )

    # 3 textboxes inside this card vertically stacked
    tb_title = _make_textbox(
        "语义标准化", x=1200, y=1200, w=2000, h=400, font_size_pt=20.0, bold=True, tb_id="t1"
    )
    tb_sub = _make_textbox(
        "攻关难点：术语复杂与语义歧义",
        x=1200,
        y=1700,
        w=2400,
        h=350,
        font_size_pt=14.0,
        tb_id="t2",
    )
    tb_desc = _make_textbox(
        "解决思路：术语词典+别名映射",
        x=1200,
        y=2200,
        w=2500,
        h=350,
        font_size_pt=13.0,
        tb_id="t3",
    )

    grouped_tbs = group_card_text_boxes([card], [tb_title, tb_sub, tb_desc])
    # The 3 discrete textboxes inside the card should be merged into
    # 1 flowing multi-paragraph textbox
    assert len(grouped_tbs) == 1
    merged = grouped_tbs[0]
    assert len(merged.paragraphs) == 3
    assert merged.paragraphs[0].runs[0].text == "语义标准化"
    assert merged.paragraphs[0].runs[0].style.font_size_pt == 20.0
    assert merged.paragraphs[0].runs[0].style.bold is True
    assert merged.paragraphs[1].runs[0].text == "攻关难点：术语复杂与语义歧义"
    assert merged.paragraphs[2].runs[0].text == "解决思路：术语词典+别名映射"
    # Merged bbox must encompass all paragraphs
    assert merged.bbox.x <= 1200
    assert merged.bbox.y <= 1200
    assert merged.bbox.y + merged.bbox.height >= 2200 + 350


def test_picture_clustering_and_micro_debris_filtering(tmp_path) -> None:
    # AC32.1, AC32.2, AC32.3:
    # 1. Micro debris image: 10px by 10px (under 20px threshold)
    img_debris = ImageElement(
        id="debris-1",
        bbox=BBox(x=100, y=100, width=15 * 9525, height=15 * 9525),  # ~15px
        image_path=str(tmp_path / "debris.png"),
    )
    # 2. Two adjacent illustration parts that belong to the same 3D illustration
    part1 = ImageElement(
        id="part-1",
        bbox=BBox(x=1000 * 9525, y=1000 * 9525, width=100 * 9525, height=80 * 9525),
        image_path=str(tmp_path / "p1.png"),
    )
    part2 = ImageElement(
        id="part-2",
        bbox=BBox(x=1000 * 9525, y=1085 * 9525, width=100 * 9525, height=80 * 9525),  # 5px gap
        image_path=str(tmp_path / "p2.png"),
    )

    filtered = filter_and_cluster_image_elements([img_debris, part1, part2])
    # Micro debris filtered out
    assert not any(img.id == "debris-1" for img in filtered)
    # Adjacent parts clustered into single illustration
    assert len(filtered) == 1
    clustered = filtered[0]
    assert clustered.bbox.height > part1.bbox.height
