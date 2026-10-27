"""Normalized percentage coordinates extraction for slide elements."""

from __future__ import annotations

from typing import Any

from pptkit.ir.models import SlideIR, TableElement, TextBoxElement


def _clamp(val: float, min_val: float = 0.0, max_val: float = 100.0) -> float:
    return max(min_val, min(max_val, val))


def extract_slide_elements_summary(slide: SlideIR, session_id: str = "") -> dict[str, Any]:
    """Convert slide elements into web-friendly JSON with percentage coordinates."""
    w_emu = max(1, slide.width_emu)
    h_emu = max(1, slide.height_emu)

    elements_data: list[dict[str, Any]] = []

    for elem in slide.elements:
        elem_text = ""
        if isinstance(elem, TextBoxElement):
            runs_text = []
            for p in elem.paragraphs:
                for r in p.runs:
                    if r.text:
                        runs_text.append(r.text)
            elem_text = "\n".join(runs_text)
        elif isinstance(elem, TableElement):
            cell_texts = []
            for row_cells in elem.cells:
                for cell in row_cells:
                    for p in cell.paragraphs:
                        for r in p.runs:
                            if r.text:
                                cell_texts.append(r.text)
            elem_text = " | ".join(cell_texts)

        x_pct = _clamp(round((elem.bbox.x / w_emu) * 100, 2))
        y_pct = _clamp(round((elem.bbox.y / h_emu) * 100, 2))
        w_pct = _clamp(round((elem.bbox.width / w_emu) * 100, 2))
        h_pct = _clamp(round((elem.bbox.height / h_emu) * 100, 2))

        elements_data.append(
            {
                "id": elem.id,
                "kind": getattr(elem, "kind", "element"),
                "text": elem_text,
                "confidence": round(elem.confidence, 3),
                "degraded": getattr(elem, "degraded", False),
                "source": getattr(elem, "source", "unknown"),
                "bbox_pct": {
                    "x": x_pct,
                    "y": y_pct,
                    "width": w_pct,
                    "height": h_pct,
                },
            }
        )

    return {
        "session_id": session_id,
        "page_index": slide.page_index,
        "width_emu": slide.width_emu,
        "height_emu": slide.height_emu,
        "elements": elements_data,
    }
