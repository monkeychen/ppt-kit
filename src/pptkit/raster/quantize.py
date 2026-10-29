from collections import Counter

from pptkit.common.color import compute_delta_e
from pptkit.ir.models import (
    PresentationIR,
    ShapeElement,
    TableElement,
    TextBoxElement,
)

DEFAULT_FONT_LADDER: list[float] = [
    44.0,
    36.0,
    32.0,
    28.0,
    24.0,
    20.0,
    18.0,
    16.0,
    14.0,
    12.0,
    10.5,
    9.0,
]


def quantize_font_size(
    size_pt: float,
    ladders: list[float] | None = None,
    tolerance_pt: float = 1.5,
) -> float:
    """Quantize font size to standard typography ladder within tolerance (F34)."""
    ladder = ladders or DEFAULT_FONT_LADDER
    if not ladder:
        return size_pt

    closest = min(ladder, key=lambda s: abs(s - size_pt))
    if abs(closest - size_pt) <= tolerance_pt:
        return closest
    return size_pt


def quantize_palette(
    hex_colors: list[str],
    max_delta_e: float = 3.5,
) -> dict[str, str]:
    """Group colors within CIELAB delta E threshold and map to cluster representatives (F34)."""
    if not hex_colors:
        return {}

    normalized = [c.upper() for c in hex_colors]
    counts = Counter(normalized)
    unique_colors = list(counts.keys())

    # Sort colors by frequency descending so the most prominent color becomes cluster center
    unique_colors.sort(key=lambda c: counts[c], reverse=True)

    clusters: list[list[str]] = []
    for c in unique_colors:
        assigned = False
        for cluster in clusters:
            rep = cluster[0]
            if compute_delta_e(c, rep) <= max_delta_e:
                cluster.append(c)
                assigned = True
                break
        if not assigned:
            clusters.append([c])

    mapping: dict[str, str] = {}
    for cluster in clusters:
        rep = cluster[0]
        for c in cluster:
            mapping[c] = rep

    return mapping


def quantize_presentation(
    presentation: PresentationIR,
    standard_ladders: list[float] | None = None,
) -> PresentationIR:
    """Quantize font sizes and unify palette across presentation (F34)."""
    pres = presentation.model_copy(deep=True)

    # 1. Collect all colors across presentation
    colors_to_quantize: list[str] = []
    for slide in pres.slides:
        for elem in slide.elements:
            if isinstance(elem, TextBoxElement):
                for p in elem.paragraphs:
                    for r in p.runs:
                        if r.style and r.style.color_hex:
                            colors_to_quantize.append(r.style.color_hex)
            elif isinstance(elem, ShapeElement):
                if elem.fill_color_hex:
                    colors_to_quantize.append(elem.fill_color_hex)
                if elem.stroke_color_hex:
                    colors_to_quantize.append(elem.stroke_color_hex)
            elif isinstance(elem, TableElement):
                for row in elem.cells:
                    for cell in row:
                        if cell.fill_color_hex:
                            colors_to_quantize.append(cell.fill_color_hex)
                        if cell.border_left and cell.border_left.color_hex:
                            colors_to_quantize.append(cell.border_left.color_hex)
                        if cell.border_right and cell.border_right.color_hex:
                            colors_to_quantize.append(cell.border_right.color_hex)
                        if cell.border_top and cell.border_top.color_hex:
                            colors_to_quantize.append(cell.border_top.color_hex)
                        if cell.border_bottom and cell.border_bottom.color_hex:
                            colors_to_quantize.append(cell.border_bottom.color_hex)
                        for p in cell.paragraphs:
                            for r in p.runs:
                                if r.style and r.style.color_hex:
                                    colors_to_quantize.append(r.style.color_hex)

    palette_map = quantize_palette(colors_to_quantize, max_delta_e=3.5)

    def map_color(hex_str: str | None) -> str | None:
        if not hex_str:
            return None
        return palette_map.get(hex_str.upper(), hex_str.upper())

    # 2. Apply quantization to elements
    for slide in pres.slides:
        for elem in slide.elements:
            if isinstance(elem, TextBoxElement):
                for p in elem.paragraphs:
                    for r in p.runs:
                        r.style.font_size_pt = quantize_font_size(
                            r.style.font_size_pt, standard_ladders
                        )
                        r.style.color_hex = map_color(r.style.color_hex) or r.style.color_hex
            elif isinstance(elem, ShapeElement):
                elem.fill_color_hex = map_color(elem.fill_color_hex)
                elem.stroke_color_hex = map_color(elem.stroke_color_hex)
            elif isinstance(elem, TableElement):
                for row in elem.cells:
                    for cell in row:
                        cell.fill_color_hex = map_color(cell.fill_color_hex)
                        if cell.border_left:
                            cell.border_left.color_hex = (
                                map_color(cell.border_left.color_hex) or cell.border_left.color_hex
                            )
                        if cell.border_right:
                            cell.border_right.color_hex = (
                                map_color(cell.border_right.color_hex)
                                or cell.border_right.color_hex
                            )
                        if cell.border_top:
                            cell.border_top.color_hex = (
                                map_color(cell.border_top.color_hex) or cell.border_top.color_hex
                            )
                        if cell.border_bottom:
                            cell.border_bottom.color_hex = (
                                map_color(cell.border_bottom.color_hex)
                                or cell.border_bottom.color_hex
                            )
                        for p in cell.paragraphs:
                            for r in p.runs:
                                r.style.font_size_pt = quantize_font_size(
                                    r.style.font_size_pt, standard_ladders
                                )
                                r.style.color_hex = (
                                    map_color(r.style.color_hex) or r.style.color_hex
                                )

    return pres
