from dataclasses import dataclass
from typing import Any

import pymupdf

from pptkit.common.units import pt_to_emu
from pptkit.ir.models import BBox, Paragraph, TextBoxElement, TextRun, TextStyle
from pptkit.vector.fonts import resolve_font


@dataclass
class TextBlockData:
    x0: float
    y0: float
    x1: float
    y1: float
    paragraphs: list[Paragraph]
    font_sizes: list[float]


def _color_int_to_hex(color_int: int) -> str:
    r = (color_int >> 16) & 0xFF
    g = (color_int >> 8) & 0xFF
    b = color_int & 0xFF
    return f"#{r:02X}{g:02X}{b:02X}"


def parse_page_text(
    page: pymupdf.Page,
    page_index: int,
) -> tuple[list[TextBoxElement], list[str]]:
    raw_dict = page.get_text("dict")
    text_dict: dict[str, Any] = raw_dict if isinstance(raw_dict, dict) else {}
    blocks: list[dict[str, Any]] = text_dict.get("blocks", [])

    raw_blocks: list[TextBlockData] = []
    missing_fonts_set: set[str] = set()

    for b in blocks:
        if b.get("type") != 0:
            continue

        b_lines = b.get("lines", [])
        if not b_lines:
            continue

        paragraphs: list[Paragraph] = []
        block_font_sizes: list[float] = []

        for line in b_lines:
            runs: list[TextRun] = []
            prev_span_x1: float | None = None
            prev_span_text: str = ""
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text:
                    continue

                font_raw = span.get("font", "Arial")
                flags = span.get("flags", 0)
                font_size = float(span.get("size", 12.0))
                block_font_sizes.append(font_size)

                span_bbox = span.get("bbox", (0, 0, 0, 0))
                if prev_span_x1 is not None:
                    gap = span_bbox[0] - prev_span_x1
                    if (
                        gap >= 0.20 * font_size
                        and not prev_span_text.endswith(" ")
                        and not text.startswith(" ")
                    ):
                        text = " " + text
                prev_span_x1 = span_bbox[2]
                prev_span_text = text

                resolved = resolve_font(font_raw, flags)
                if resolved.is_missing:
                    missing_fonts_set.add(resolved.family)

                family = resolved.fallback_family if resolved.is_missing else resolved.family
                color_hex = _color_int_to_hex(span.get("color", 0))

                style = TextStyle(
                    font_family=family,
                    font_size_pt=round(font_size, 1),
                    color_hex=color_hex,
                    bold=resolved.bold,
                    italic=resolved.italic,
                    underline=bool(flags & (1 << 0)),
                )
                runs.append(TextRun(text=text, style=style))

            if runs:
                paragraphs.append(Paragraph(runs=runs, align="left"))

        if paragraphs:
            bbox = b.get("bbox", (0, 0, 0, 0))
            raw_blocks.append(
                TextBlockData(
                    x0=bbox[0],
                    y0=bbox[1],
                    x1=bbox[2],
                    y1=bbox[3],
                    paragraphs=paragraphs,
                    font_sizes=block_font_sizes,
                )
            )

    # Paragraph & Multi-line block aggregation (AC6.2)
    # Group vertically adjacent, left-aligned text blocks
    merged_blocks: list[TextBlockData] = []
    skip_indices: set[int] = set()

    for i in range(len(raw_blocks)):
        if i in skip_indices:
            continue
        cur = raw_blocks[i]
        cur_x0 = cur.x0
        cur_y0 = cur.y0
        cur_x1 = cur.x1
        cur_y1 = cur.y1
        cur_paras = list(cur.paragraphs)

        avg_fs = sum(cur.font_sizes) / max(1, len(cur.font_sizes))

        for j in range(i + 1, len(raw_blocks)):
            if j in skip_indices:
                continue
            nxt = raw_blocks[j]
            # Check left alignment tolerance: <= 4.0 pt
            # Check vertical gap: <= 2.2 * avg_fs
            vert_gap = nxt.y0 - cur_y1
            if abs(nxt.x0 - cur_x0) <= 4.0 and 0.0 <= vert_gap <= (2.2 * avg_fs):
                cur_y1 = max(cur_y1, nxt.y1)
                cur_x1 = max(cur_x1, nxt.x1)
                cur_x0 = min(cur_x0, nxt.x0)
                cur_paras.extend(nxt.paragraphs)
                skip_indices.add(j)
            else:
                break

        merged_blocks.append(
            TextBlockData(
                x0=cur_x0,
                y0=cur_y0,
                x1=cur_x1,
                y1=cur_y1,
                paragraphs=cur_paras,
                font_sizes=cur.font_sizes,
            )
        )

    # Convert to TextBoxElement
    elements: list[TextBoxElement] = []
    for idx, mb in enumerate(merged_blocks):
        x_emu = pt_to_emu(mb.x0)
        y_emu = pt_to_emu(mb.y0)
        w_emu = pt_to_emu(mb.x1 - mb.x0)
        h_emu = pt_to_emu(mb.y1 - mb.y0)

        elements.append(
            TextBoxElement(
                id=f"p{page_index}-tb-{idx:03d}",
                bbox=BBox(x=x_emu, y=y_emu, width=max(1, w_emu), height=max(1, h_emu)),
                z_order=100 + idx,
                confidence=1.0,
                source="vector",
                degraded=False,
                paragraphs=mb.paragraphs,
                word_wrap=True,
            )
        )

    return elements, sorted(list(missing_fonts_set))
