import random
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pptkit.common.units import DEFAULT_SLIDE_HEIGHT_EMU, DEFAULT_SLIDE_WIDTH_EMU, pt_to_emu
from pptkit.ir.models import (
    Background,
    BBox,
    CellBorder,
    Paragraph,
    PresentationIR,
    ShapeElement,
    SlideElement,
    SlideIR,
    TableCell,
    TableElement,
    TextBoxElement,
    TextRun,
    TextStyle,
)
from pptkit.render.renderer import render_pptx
from pptkit.writer.pptx_writer import write_pptx

CANDIDATE_FONTS = ["PingFang SC", "Arial", "Helvetica"]
BG_COLORS = ["#F8FAFC", "#FFFFFF", "#F1F5F9", "#FEFCE8"]
CARD_COLORS = ["#E2E8F0", "#DBEAFE", "#FCE7F3", "#DCFCE7"]
STROKE_COLORS = ["#334155", "#1D4ED8", "#9D174D", "#15803D"]
TEXT_COLORS = ["#0F172A", "#1E293B", "#1E3A8A", "#14532D"]
SAMPLE_TITLES = [
    "AI 驱动的企业知识管理工作流",
    "大模型产品化落地的三大核心指标",
    "从非结构化位图到可编辑元素树",
    "2026 智能办公产品演进路线图",
    "高保真幻灯片逆向重建架构设计",
]
SAMPLE_BULLETS = [
    "能读就不识别：矢量 PDF 直接解析路径与文字属性",
    "单一中间表示：所有输入源统一收敛至 Slide IR",
    "质量靠度量：基于原生渲染器 SSIM 与色差自动打分",
    "宁可退化不可错乱：低置信元素保留底图确保视觉不崩",
]


@dataclass
class SyntheticSample:
    sample_id: str
    slide_ir: SlideIR
    gt_json_path: Path
    pptx_path: Path
    pdf_path: Path | None = None
    png_path: Path | None = None


def _build_random_slide(rng: random.Random, page_index: int) -> SlideIR:
    bg_hex = rng.choice(BG_COLORS)
    font_name = rng.choice(CANDIDATE_FONTS)
    title_color = rng.choice(TEXT_COLORS)
    card_fill = rng.choice(CARD_COLORS)
    card_stroke = rng.choice(STROKE_COLORS)
    shape_kind: Literal["rect", "round_rect"] = rng.choice(["rect", "round_rect"])

    elements: list[SlideElement] = [
        ShapeElement(
            id=f"s{page_index}-card-bg",
            bbox=BBox(x=700000, y=1800000, width=10792000, height=4300000),
            z_order=1,
            source="synthetic",
            shape_type=shape_kind,
            fill_color_hex=card_fill,
            stroke_color_hex=card_stroke,
            stroke_width_emu=pt_to_emu(1.5),
            corner_radius_ratio=0.06 if shape_kind == "round_rect" else 0.0,
        ),
        TextBoxElement(
            id=f"s{page_index}-title",
            bbox=BBox(x=700000, y=500000, width=10792000, height=1000000),
            z_order=2,
            source="synthetic",
            paragraphs=[
                Paragraph(
                    runs=[
                        TextRun(
                            text=rng.choice(SAMPLE_TITLES),
                            style=TextStyle(
                                font_family=font_name,
                                font_size_pt=float(rng.choice([28, 32, 36])),
                                color_hex=title_color,
                                bold=True,
                            ),
                        )
                    ],
                    align="left",
                )
            ],
        ),
        TextBoxElement(
            id=f"s{page_index}-body",
            bbox=BBox(x=1100000, y=2200000, width=9900000, height=3400000),
            z_order=3,
            source="synthetic",
            paragraphs=[
                Paragraph(
                    runs=[
                        TextRun(
                            text=bullet,
                            style=TextStyle(
                                font_family=font_name,
                                font_size_pt=float(rng.choice([18, 20, 22])),
                                color_hex="#1E293B",
                                bold=False,
                            ),
                        )
                    ],
                    align="left",
                    space_after_pt=10.0,
                )
                for bullet in rng.sample(SAMPLE_BULLETS, k=3)
            ],
        ),
    ]

    return SlideIR(
        page_index=page_index,
        route="vector",
        width_emu=DEFAULT_SLIDE_WIDTH_EMU,
        height_emu=DEFAULT_SLIDE_HEIGHT_EMU,
        background=Background(fill_type="solid", color_hex=bg_hex),
        elements=elements,
    )


def generate_synthetic_dataset(
    out_dir: Path | str,
    count: int = 5,
    seed: int = 42,
    render: bool = False,
) -> list[SyntheticSample]:
    dst = Path(out_dir)
    dst.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    samples: list[SyntheticSample] = []

    for idx in range(count):
        sample_id = f"syn_{idx:03d}"
        slide_ir = _build_random_slide(rng, page_index=0)
        pres_ir = PresentationIR(
            source_path=f"{sample_id}.pptx",
            width_emu=slide_ir.width_emu,
            height_emu=slide_ir.height_emu,
            slides=[slide_ir],
        )
        gt_path = dst / f"{sample_id}.gt.json"
        gt_path.write_text(pres_ir.to_json(), encoding="utf-8")

        pptx_path = write_pptx(pres_ir, dst / f"{sample_id}.pptx")
        pdf_path: Path | None = None
        png_path: Path | None = None

        if render:
            rendered = render_pptx(pptx_path, dst, target_size=(1920, 1080))
            pdf_path = rendered.pdf_path
            png_path = rendered.png_paths[0] if rendered.png_paths else None

        samples.append(
            SyntheticSample(
                sample_id=sample_id,
                slide_ir=slide_ir,
                gt_json_path=gt_path,
                pptx_path=pptx_path,
                pdf_path=pdf_path,
                png_path=png_path,
            )
        )

    return samples


def _build_table_slide(rng: random.Random, page_index: int) -> SlideIR:
    bg_hex = rng.choice(BG_COLORS)
    font_name = rng.choice(CANDIDATE_FONTS)
    title_color = rng.choice(TEXT_COLORS)
    header_fill = rng.choice(["#1E40AF", "#047857", "#B91C1C", "#4338CA"])

    headers = ["模块名称", "输入类型", "目标格式", "处理耗时"]
    rows_data = [
        ["vector.parser", "矢量 PDF", "Slide IR", "< 100ms"],
        ["raster.pipeline", "位图图片", "Slide IR", "< 3.0s"],
        ["writer.pptx", "Slide IR", "PPTX 幻灯片", "< 50ms"],
    ]

    col_widths = [2600000, 2400000, 2600000, 2200000]
    row_heights = [700000, 650000, 650000, 650000]

    cells: list[list[TableCell]] = []
    # Header row
    h_row: list[TableCell] = []
    for c_idx, h_text in enumerate(headers):
        h_row.append(
            TableCell(
                row=0,
                col=c_idx,
                paragraphs=[
                    Paragraph(
                        runs=[
                            TextRun(
                                text=h_text,
                                style=TextStyle(
                                    font_family=font_name,
                                    font_size_pt=14.0,
                                    color_hex="#FFFFFF",
                                    bold=True,
                                ),
                            )
                        ],
                        align="center",
                    )
                ],
                fill_color_hex=header_fill,
                border_bottom=CellBorder(color_hex="#1E293B", width_emu=19050),
            )
        )
    cells.append(h_row)

    # Data rows
    for r_idx, r_data in enumerate(rows_data, start=1):
        bg_row = "#F8FAFC" if r_idx % 2 == 1 else "#FFFFFF"
        row_cells: list[TableCell] = []
        for c_idx, val in enumerate(r_data):
            row_cells.append(
                TableCell(
                    row=r_idx,
                    col=c_idx,
                    paragraphs=[
                        Paragraph(
                            runs=[
                                TextRun(
                                    text=val,
                                    style=TextStyle(
                                        font_family=font_name,
                                        font_size_pt=12.0,
                                        color_hex="#334155",
                                    ),
                                )
                            ],
                            align="center" if c_idx == 3 else "left",
                        )
                    ],
                    fill_color_hex=bg_row,
                    border_bottom=CellBorder(color_hex="#E2E8F0", width_emu=12700),
                )
            )
        cells.append(row_cells)

    table_elem = TableElement(
        id=f"s{page_index}-table",
        bbox=BBox(x=1200000, y=1800000, width=9800000, height=2650000),
        z_order=1,
        source="synthetic",
        rows=4,
        cols=4,
        col_widths_emu=col_widths,
        row_heights_emu=row_heights,
        cells=cells,
    )

    title_elem = TextBoxElement(
        id=f"s{page_index}-title",
        bbox=BBox(x=1200000, y=700000, width=9800000, height=800000),
        z_order=2,
        source="synthetic",
        paragraphs=[
            Paragraph(
                runs=[
                    TextRun(
                        text="PPTKit 核心模块性能与路由对照表",
                        style=TextStyle(
                            font_family=font_name,
                            font_size_pt=28.0,
                            color_hex=title_color,
                            bold=True,
                        ),
                    )
                ],
                align="left",
            )
        ],
    )

    return SlideIR(
        page_index=page_index,
        route="vector",
        width_emu=DEFAULT_SLIDE_WIDTH_EMU,
        height_emu=DEFAULT_SLIDE_HEIGHT_EMU,
        background=Background(fill_type="solid", color_hex=bg_hex),
        elements=[title_elem, table_elem],
    )


def generate_synthetic_table_dataset(
    out_dir: Path | str,
    count: int = 2,
    seed: int = 42,
    render: bool = False,
) -> list[SyntheticSample]:
    dst = Path(out_dir)
    dst.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    samples: list[SyntheticSample] = []

    for idx in range(count):
        sample_id = f"syn_table_{idx:03d}"
        slide_ir = _build_table_slide(rng, page_index=0)
        pres_ir = PresentationIR(
            source_path=f"{sample_id}.pptx",
            width_emu=slide_ir.width_emu,
            height_emu=slide_ir.height_emu,
            slides=[slide_ir],
        )
        gt_path = dst / f"{sample_id}.gt.json"
        gt_path.write_text(pres_ir.to_json(), encoding="utf-8")

        pptx_path = write_pptx(pres_ir, dst / f"{sample_id}.pptx")
        pdf_path: Path | None = None
        png_path: Path | None = None

        if render:
            rendered = render_pptx(pptx_path, dst, target_size=(1920, 1080))
            pdf_path = rendered.pdf_path
            png_path = rendered.png_paths[0] if rendered.png_paths else None

        samples.append(
            SyntheticSample(
                sample_id=sample_id,
                slide_ir=slide_ir,
                gt_json_path=gt_path,
                pptx_path=pptx_path,
                pdf_path=pdf_path,
                png_path=png_path,
            )
        )

    return samples
