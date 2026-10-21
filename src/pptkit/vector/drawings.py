from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from pptkit.common.units import pt_to_emu
from pptkit.ir.models import Background, BBox, ImageElement, ShapeElement


def _color_to_hex(color: tuple[float, ...] | list[float] | None) -> str | None:
    if not color:
        return None
    if len(color) == 1:
        v = round(max(0.0, min(1.0, color[0])) * 255)
        return f"#{v:02X}{v:02X}{v:02X}"
    if len(color) >= 3:
        r = round(max(0.0, min(1.0, color[0])) * 255)
        g = round(max(0.0, min(1.0, color[1])) * 255)
        b = round(max(0.0, min(1.0, color[2])) * 255)
        return f"#{r:02X}{g:02X}{b:02X}"
    return None


def _rect_to_bbox_emu(rect: pymupdf.Rect) -> BBox:
    x_emu = pt_to_emu(rect.x0)
    y_emu = pt_to_emu(rect.y0)
    w_emu = pt_to_emu(rect.width)
    h_emu = pt_to_emu(rect.height)
    return BBox(x=x_emu, y=y_emu, width=max(1, w_emu), height=max(1, h_emu))


@dataclass
class DrawingsParseResult:
    background: Background | None
    elements: list[ShapeElement | ImageElement]
    degraded_ids: list[str] = field(default_factory=list)


def parse_page_drawings(
    page: pymupdf.Page,
    page_index: int,
    work_dir: Path,
) -> DrawingsParseResult:
    drawings = page.get_drawings()
    page_w = page.rect.width
    page_h = page.rect.height

    bg: Background | None = None
    raw_elements: list[ShapeElement | ImageElement] = []
    degraded_ids: list[str] = []

    for idx, d in enumerate(drawings):
        rect = d.get("rect", pymupdf.Rect(0, 0, 0, 0))
        if max(rect.width, rect.height) <= 0.5:
            continue

        fill_hex = _color_to_hex(d.get("fill"))
        stroke_hex = _color_to_hex(d.get("color"))
        stroke_w_pt = float(d.get("width") or 0.0)
        stroke_w_emu = pt_to_emu(stroke_w_pt) if stroke_hex else 0
        fill_opacity = float(d.get("fill_opacity") if d.get("fill_opacity") is not None else 1.0)
        stroke_opacity = float(
            d.get("stroke_opacity") if d.get("stroke_opacity") is not None else 1.0
        )

        # 1. Background detection: full-bleed solid fill at the bottom
        if (
            idx <= 1
            and rect.width >= 0.98 * page_w
            and rect.height >= 0.98 * page_h
            and fill_hex is not None
            and stroke_hex is None
        ):
            bg = Background(fill_type="solid", color_hex=fill_hex)
            continue

        # 2. Check for complex / translucent degradation (AC6.5)
        if fill_opacity < 0.95 or stroke_opacity < 0.95:
            deg_id = f"p{page_index}-deg-{idx:03d}"
            work_dir.mkdir(parents=True, exist_ok=True)
            deg_png = work_dir / f"degraded_drawing_{idx:03d}.png"
            pix = page.get_pixmap(clip=rect, dpi=150)
            pix.save(deg_png)
            raw_elements.append(
                ImageElement(
                    id=deg_id,
                    bbox=_rect_to_bbox_emu(rect),
                    z_order=10 + idx,
                    confidence=0.8,
                    source="vector",
                    degraded=True,
                    image_path=str(deg_png),
                )
            )
            degraded_ids.append(deg_id)
            continue

        if fill_hex is None and stroke_hex is None:
            continue

        items = d.get("items", [])
        if not items:
            continue

        # 3. Geometry classification
        item_types = [it[0] for it in items]
        shape_type = "rect"
        corner_radius_ratio = 0.0
        points_emu: list[tuple[int, int]] | None = None

        if len(items) == 1 and item_types[0] == "l" and fill_hex is None:
            shape_type = "line"
            p1 = items[0][1]
            p2 = items[0][2]
            points_emu = [
                (pt_to_emu(p1.x), pt_to_emu(p1.y)),
                (pt_to_emu(p2.x), pt_to_emu(p2.y)),
            ]
        elif len(items) == 1 and item_types[0] == "re":
            shape_type = "rect"
        elif len(items) == 4 and all(t == "l" for t in item_types):
            shape_type = "rect"
        elif len(items) == 4 and all(t == "c" for t in item_types):
            shape_type = "ellipse"
        elif item_types.count("l") == 4 and item_types.count("c") == 4:
            shape_type = "round_rect"
            # Estimate corner radius
            min_side = max(1.0, min(rect.width, rect.height))
            # First curve item: ("c", p1, p2, p3, p4)
            curves = [it for it in items if it[0] == "c"]
            if curves:
                c_p1 = curves[0][1]
                c_p4 = curves[0][4]
                corner_len = max(abs(c_p4.x - c_p1.x), abs(c_p4.y - c_p1.y))
                corner_radius_ratio = round(min(0.5, max(0.01, corner_len / min_side)), 4)
        else:
            shape_type = "freeform"
            pts: list[tuple[int, int]] = []
            for it in items:
                for arg in it[1:]:
                    if isinstance(arg, pymupdf.Point):
                        pts.append((pt_to_emu(arg.x), pt_to_emu(arg.y)))
                    elif isinstance(arg, pymupdf.Rect):
                        pts.append((pt_to_emu(arg.x0), pt_to_emu(arg.y0)))
                        pts.append((pt_to_emu(arg.x1), pt_to_emu(arg.y1)))
            points_emu = pts if len(pts) >= 2 else None

        raw_elements.append(
            ShapeElement(
                id=f"p{page_index}-sh-{idx:03d}",
                bbox=_rect_to_bbox_emu(rect),
                z_order=10 + idx,
                confidence=1.0,
                source="vector",
                degraded=False,
                shape_type=shape_type,  # type: ignore[arg-type]
                fill_color_hex=fill_hex,
                stroke_color_hex=stroke_hex,
                stroke_width_emu=stroke_w_emu,
                corner_radius_ratio=corner_radius_ratio,
                points_emu=points_emu,
            )
        )

    # 4. Fill and Stroke Merging pass
    merged_elements: list[ShapeElement | ImageElement] = []
    skip_indices: set[int] = set()

    tol_emu = pt_to_emu(2.0)
    for i in range(len(raw_elements)):
        if i in skip_indices:
            continue
        cur = raw_elements[i]
        if not isinstance(cur, ShapeElement):
            merged_elements.append(cur)
            continue

        # Look for matching sibling immediately following or nearby
        for j in range(i + 1, min(i + 3, len(raw_elements))):
            if j in skip_indices:
                continue
            nxt = raw_elements[j]
            if not isinstance(nxt, ShapeElement) or nxt.shape_type != cur.shape_type:
                continue

            # Check bbox similarity
            if (
                abs(cur.bbox.x - nxt.bbox.x) <= tol_emu
                and abs(cur.bbox.y - nxt.bbox.y) <= tol_emu
                and abs(cur.bbox.width - nxt.bbox.width) <= tol_emu
                and abs(cur.bbox.height - nxt.bbox.height) <= tol_emu
            ):
                # Check complementary fill and stroke
                if (
                    cur.fill_color_hex is not None
                    and cur.stroke_color_hex is None
                    and nxt.stroke_color_hex is not None
                    and nxt.fill_color_hex is None
                ):
                    cur.stroke_color_hex = nxt.stroke_color_hex
                    cur.stroke_width_emu = nxt.stroke_width_emu
                    skip_indices.add(j)
                    break
                elif (
                    cur.stroke_color_hex is not None
                    and cur.fill_color_hex is None
                    and nxt.fill_color_hex is not None
                    and nxt.stroke_color_hex is None
                ):
                    cur.fill_color_hex = nxt.fill_color_hex
                    skip_indices.add(j)
                    break

        merged_elements.append(cur)

    return DrawingsParseResult(
        background=bg,
        elements=merged_elements,
        degraded_ids=degraded_ids,
    )
