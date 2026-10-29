import math
from dataclasses import dataclass, field
from typing import Literal

import cv2
import numpy as np
from PIL import Image
from scipy.ndimage import (
    binary_closing,
    binary_dilation,
    binary_erosion,
    binary_fill_holes,
    label,
)

from pptkit.common.color import rgb_to_hex
from pptkit.common.units import (
    DEFAULT_SLIDE_HEIGHT_EMU,
    DEFAULT_SLIDE_WIDTH_EMU,
    pt_to_emu,
    px_to_emu,
)
from pptkit.ir.models import BBox, ShapeElement

SHAPE_CONFIDENCE_THRESHOLD = 0.75
REF_SHORT_SIDE = 1080.0


def scale_px(ref_px: float, short_side: int, min_val: int = 1) -> int:
    return max(min_val, int(round(ref_px * (short_side / REF_SHORT_SIDE))))


def scale_area(ref_area: float, short_side: int, min_val: int = 4) -> int:
    ratio = short_side / REF_SHORT_SIDE
    return max(min_val, int(round(ref_area * ratio * ratio)))


@dataclass
class EmbeddedLayerCrop:
    rgba: np.ndarray
    bbox_emu: BBox
    z_order: int


@dataclass
class ShapeExtractionResult:
    shapes: list[ShapeElement] = field(default_factory=list)
    degraded_ids: list[str] = field(default_factory=list)
    residual_image: Image.Image = field(default_factory=lambda: Image.new("RGB", (1, 1)))
    embedded_crops: list[EmbeddedLayerCrop] = field(default_factory=list)


def estimate_page_background_rgb(arr: np.ndarray) -> np.ndarray:
    b = max(2, min(6, min(arr.shape[0], arr.shape[1]) // 40))
    border = np.concatenate(
        [
            arr[:b, :, :].reshape(-1, 3),
            arr[-b:, :, :].reshape(-1, 3),
            arr[:, :b, :].reshape(-1, 3),
            arr[:, -b:, :].reshape(-1, 3),
        ],
        axis=0,
    )
    return np.median(border, axis=0)


def sample_ring_background_rgb(
    arr: np.ndarray,
    fg_mask: np.ndarray,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    fallback_rgb: np.ndarray,
    ring_px: int = 6,
) -> np.ndarray:
    h_img, w_img, _ = arr.shape
    rx0 = max(0, x0 - ring_px)
    ry0 = max(0, y0 - ring_px)
    rx1 = min(w_img, x1 + ring_px)
    ry1 = min(h_img, y1 + ring_px)

    ring_mask = np.ones((ry1 - ry0, rx1 - rx0), dtype=bool)
    ring_mask[y0 - ry0 : y1 - ry0, x0 - rx0 : x1 - rx0] = False
    bg_in_ring = ring_mask & (~fg_mask[ry0:ry1, rx0:rx1])
    if int(np.sum(bg_in_ring)) >= 10:
        pts = arr[ry0:ry1, rx0:rx1][bg_in_ring]
        return np.median(pts, axis=0)
    return fallback_rgb


def _is_right_arrow(comp_mask: np.ndarray, short_side: int) -> bool:
    h, w = comp_mask.shape
    min_w = scale_px(26, short_side, min_val=12)
    min_h = scale_px(16, short_side, min_val=8)
    if w < h * 1.15 or w < min_w or h < min_h:
        return False
    # Card defense: solid wide container has fill ratio > 0.80, arrows have shaft/notches
    fill_ratio = float(np.sum(comp_mask)) / float(max(w * h, 1))
    if fill_ratio >= 0.80 and (w / max(h, 1)) >= 1.8:
        return False
    col_heights = np.sum(comp_mask, axis=0).astype(np.float32)
    left_span = col_heights[int(w * 0.08) : int(w * 0.45)]
    if len(left_span) < 3:
        return False
    shaft_h = float(np.median(left_span))
    if not (0.20 * h <= shaft_h <= 0.72 * h):
        return False
    if float(np.std(left_span)) > max(3.5, h * 0.06):
        return False

    peak_idx = int(w * 0.45) + int(np.argmax(col_heights[int(w * 0.45) : int(w * 0.85)]))
    peak_h = float(col_heights[peak_idx])
    if peak_h < h * 0.82 or peak_h <= shaft_h * 1.25:
        return False

    tail = col_heights[peak_idx:]
    if len(tail) < 4:
        return False
    diffs = np.diff(tail)
    non_increasing_ratio = float(np.mean(diffs <= 2.0))
    return non_increasing_ratio >= 0.75 and float(tail[-1]) <= h * 0.35


def _classify_solid_geometry(
    comp_mask: np.ndarray,
    short_side: int = 1080,
) -> tuple[Literal["rect", "round_rect", "ellipse", "right_arrow"] | None, float, float]:
    h, w = comp_mask.shape
    area = float(np.sum(comp_mask))
    fill_ratio = area / float(max(w * h, 1))

    if _is_right_arrow(comp_mask, short_side):
        return "right_arrow", 0.0, 0.90

    tip_w = max(2, min(5, min(w, h) // 8))
    tips = [
        comp_mask[:tip_w, :tip_w],
        comp_mask[:tip_w, -tip_w:],
        comp_mask[-tip_w:, :tip_w],
        comp_mask[-tip_w:, -tip_w:],
    ]
    tip_fill = float(np.mean([np.mean(t) for t in tips]))

    cw = max(3, min(w, h) // 3)
    corners = [
        comp_mask[:cw, :cw],
        comp_mask[:cw, -cw:],
        comp_mask[-cw:, :cw],
        comp_mask[-cw:, -cw:],
    ]
    corner_fill = float(np.mean([np.mean(c) for c in corners]))
    mean_empty_corner_px = float(np.mean([np.sum(~c) for c in corners]))

    x_m0, x_m1 = int(w * 0.30), max(int(w * 0.30) + 1, int(w * 0.70))
    y_m0, y_m1 = int(h * 0.30), max(int(h * 0.30) + 1, int(h * 0.70))
    ew = max(2, min(4, min(w, h) // 10))
    mid_edges = [
        comp_mask[:ew, x_m0:x_m1],
        comp_mask[-ew:, x_m0:x_m1],
        comp_mask[y_m0:y_m1, :ew],
        comp_mask[y_m0:y_m1, -ew:],
    ]
    mid_edge_fill = float(np.mean([np.mean(e) for e in mid_edges]))

    yy, xx = np.ogrid[:h, :w]
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    ry, rx = max(h / 2.0, 1.0), max(w / 2.0, 1.0)
    ideal_ellipse = ((yy - cy) / ry) ** 2 + ((xx - cx) / rx) ** 2 <= 1.0
    inter = float(np.sum(comp_mask & ideal_ellipse))
    union = float(np.sum(comp_mask | ideal_ellipse))
    ellipse_iou = inter / max(union, 1.0)

    if fill_ratio >= 0.95 and tip_fill >= 0.80 and mean_empty_corner_px < 6.0:
        return "rect", 0.0, 0.96

    if ellipse_iou >= 0.90 and fill_ratio <= 0.84 and corner_fill <= 0.55 and tip_fill <= 0.05:
        return "ellipse", 0.0, 0.92

    if fill_ratio >= 0.74 and mid_edge_fill >= 0.78:
        r_px = math.sqrt(mean_empty_corner_px / max(1.0 - math.pi / 4.0, 0.05))
        radius_ratio = float(np.clip(r_px / max(min(w, h), 1), 0.04, 0.48))
        return "round_rect", round(radius_ratio, 3), 0.90

    return None, 0.0, 0.45


def classify_contour_shape(contour: np.ndarray, w: int, h: int) -> str:
    """Classify geometric contour with aspect-ratio guard for card containers (F29)."""
    if w <= 0 or h <= 0:
        _, _, w_b, h_b = cv2.boundingRect(contour)
        w = max(1, w or w_b)
        h = max(1, h or h_b)

    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.drawContours(mask, [contour], -1, 1, thickness=-1)
    comp_mask = mask > 0

    area = float(cv2.contourArea(contour))
    aspect_ratio = float(w) / float(max(h, 1))
    fill_ratio = area / float(max(w * h, 1))

    # AC29.1, AC29.2: Horizontal card defense against right arrow
    is_card_guard = (aspect_ratio >= 1.8 or w >= 250) and fill_ratio >= 0.80

    kind, radius_ratio, conf = _classify_solid_geometry(comp_mask)
    if is_card_guard and kind == "right_arrow":
        kind = None

    if kind is not None:
        return kind

    if is_card_guard:
        cw = max(3, min(w, h) // 4)
        corners = [
            comp_mask[:cw, :cw],
            comp_mask[:cw, -cw:],
            comp_mask[-cw:, :cw],
            comp_mask[-cw:, -cw:],
        ]
        mean_empty = float(np.mean([np.sum(~c) for c in corners]))
        return "round_rect" if mean_empty > 4.0 else "rect"

    return "rect"


def _extract_embedded_crops_from_canvas(
    canvas_arr: np.ndarray,
    bg_rgb: np.ndarray,
    offset_x: int,
    offset_y: int,
    full_w: int,
    full_h: int,
    slide_width_emu: int,
    slide_height_emu: int,
    z_order: int,
) -> list[EmbeddedLayerCrop]:
    h_sub, w_sub, _ = canvas_arr.shape
    short_side = min(full_w, full_h)
    dist_map = np.linalg.norm(canvas_arr - bg_rgb, axis=-1)
    fg_mask = dist_map > 38.0
    if not np.any(fg_mask):
        return []

    closed = np.asarray(
        binary_closing(fg_mask, structure=np.ones((3, 3), dtype=bool), iterations=1),
        dtype=bool,
    )
    lbl_res: tuple[np.ndarray, int] = label(closed)  # type: ignore[assignment]
    labeled_arr, num_features = lbl_res
    labeled = np.asarray(labeled_arr, dtype=np.int32)

    min_part_fg = scale_area(20, short_side, min_val=6)
    min_part_side = scale_px(5, short_side, min_val=3)
    raw_groups: list[list[int | list[int]]] = []
    for cid in range(1, int(num_features) + 1):
        comp_fg = (labeled == cid) & fg_mask
        ys, xs = np.where(comp_fg)
        fg_cnt = len(ys)
        if fg_cnt < min_part_fg:
            continue
        x0_c, x1_c = int(xs.min()), int(xs.max()) + 1
        y0_c, y1_c = int(ys.min()), int(ys.max()) + 1
        if (x1_c - x0_c) < min_part_side and (y1_c - y0_c) < min_part_side:
            continue
        raw_groups.append([x0_c, y0_c, x1_c, y1_c, fg_cnt, [cid]])

    max_icon_box = scale_px(88, short_side, min_val=24)
    max_gap_x = scale_px(16, short_side, min_val=5)
    max_gap_y = scale_px(20, short_side, min_val=5)
    changed = True
    while changed:
        changed = False
        for i in range(len(raw_groups)):
            if changed:
                break
            ax0 = int(raw_groups[i][0])  # type: ignore[arg-type]
            ay0 = int(raw_groups[i][1])  # type: ignore[arg-type]
            ax1 = int(raw_groups[i][2])  # type: ignore[arg-type]
            ay1 = int(raw_groups[i][3])  # type: ignore[arg-type]
            afg = int(raw_groups[i][4])  # type: ignore[arg-type]
            acids: list[int] = raw_groups[i][5]  # type: ignore[assignment]
            for j in range(i + 1, len(raw_groups)):
                bx0 = int(raw_groups[j][0])  # type: ignore[arg-type]
                by0 = int(raw_groups[j][1])  # type: ignore[arg-type]
                bx1 = int(raw_groups[j][2])  # type: ignore[arg-type]
                by1 = int(raw_groups[j][3])  # type: ignore[arg-type]
                bfg = int(raw_groups[j][4])  # type: ignore[arg-type]
                bcids: list[int] = raw_groups[j][5]  # type: ignore[assignment]

                ux0, uy0 = min(ax0, bx0), min(ay0, by0)
                ux1, uy1 = max(ax1, bx1), max(ay1, by1)
                uw, uh = ux1 - ux0, uy1 - uy0
                gap_x = max(0, max(ax0, bx0) - min(ax1, bx1))
                gap_y = max(0, max(ay0, by0) - min(ay1, by1))
                if (
                    uw <= max_icon_box
                    and uh <= max_icon_box
                    and gap_x <= max_gap_x
                    and gap_y <= max_gap_y
                ):
                    raw_groups[i] = [ux0, uy0, ux1, uy1, afg + bfg, acids + bcids]
                    raw_groups.pop(j)
                    changed = True
                    break

    min_final_fg = scale_area(65, short_side, min_val=15)
    min_final_side = scale_px(12, short_side, min_val=6)
    crops: list[EmbeddedLayerCrop] = []
    for grp in raw_groups:
        gx0 = int(grp[0])  # type: ignore[arg-type]
        gy0 = int(grp[1])  # type: ignore[arg-type]
        gx1 = int(grp[2])  # type: ignore[arg-type]
        gy1 = int(grp[3])  # type: ignore[arg-type]
        gfg = int(grp[4])  # type: ignore[arg-type]
        gw, gh = gx1 - gx0, gy1 - gy0
        if gfg < min_final_fg or gw < min_final_side or gh < min_final_side:
            continue

        pad = 2
        cx0 = max(0, gx0 - pad)
        cy0 = max(0, gy0 - pad)
        cx1 = min(w_sub, gx1 + pad)
        cy1 = min(h_sub, gy1 + pad)
        cw, ch = cx1 - cx0, cy1 - cy0

        patch_f = canvas_arr[cy0:cy1, cx0:cx1].copy()
        p_dist = dist_map[cy0:cy1, cx0:cx1]
        alpha_f = np.clip((p_dist - 26.0) / 18.0, 0.0, 1.0)
        # Un-blend edge pixels against container bg_rgb to eliminate colored fringe
        edge_mask = (alpha_f > 0.0) & (alpha_f < 1.0)
        if np.any(edge_mask):
            a_exp = alpha_f[edge_mask][:, None]
            unblended = (patch_f[edge_mask] - (1.0 - a_exp) * bg_rgb) / np.maximum(a_exp, 0.25)
            patch_f[edge_mask] = np.clip(unblended, 0.0, 255.0)

        rgb_u8 = np.clip(np.round(patch_f), 0, 255).astype(np.uint8)
        alpha_u8 = np.clip(np.round(alpha_f * 255.0), 0, 255).astype(np.uint8)
        rgba = np.dstack([rgb_u8, alpha_u8])

        abs_x = offset_x + cx0
        abs_y = offset_y + cy0
        crops.append(
            EmbeddedLayerCrop(
                rgba=rgba,
                bbox_emu=BBox(
                    x=px_to_emu(abs_x, full_w, slide_width_emu),
                    y=px_to_emu(abs_y, full_h, slide_height_emu),
                    width=max(1, px_to_emu(cw, full_w, slide_width_emu)),
                    height=max(1, px_to_emu(ch, full_h, slide_height_emu)),
                ),
                z_order=z_order,
            )
        )

    return crops


def extract_raster_shapes(
    image: Image.Image,
    slide_width_emu: int = DEFAULT_SLIDE_WIDTH_EMU,
    slide_height_emu: int = DEFAULT_SLIDE_HEIGHT_EMU,
    page_index: int = 0,
    confidence_threshold: float = SHAPE_CONFIDENCE_THRESHOLD,
    _offset_px: tuple[int, int] = (0, 0),
    _full_size_px: tuple[int, int] | None = None,
    _depth: int = 0,
    _seq_start: int = 0,
) -> ShapeExtractionResult:
    rgb_img = image.convert("RGB")
    arr = np.asarray(rgb_img, dtype=np.float32).copy()
    residual = arr.copy()
    h_img, w_img, _ = arr.shape

    full_w, full_h = _full_size_px if _full_size_px is not None else (w_img, h_img)
    off_x, off_y = _offset_px
    short_side = min(full_w, full_h)

    page_bg_rgb = estimate_page_background_rgb(arr)
    dist_map = np.linalg.norm(arr - page_bg_rgb, axis=-1)
    fg_mask = dist_map > 20.0
    lbl_res: tuple[np.ndarray, int] = label(fg_mask)  # type: ignore[assignment]
    labeled_arr, num_features = lbl_res
    labeled = np.asarray(labeled_arr, dtype=np.int32)

    shapes: list[ShapeElement] = []
    degraded_ids: list[str] = []
    embedded_crops: list[EmbeddedLayerCrop] = []
    shape_seq = _seq_start

    min_comp_area = scale_area(130, short_side, min_val=25)
    line_min_len = scale_px(55, short_side, min_val=16)
    line_max_thick = scale_px(10, short_side, min_val=3)
    card_min_w = scale_px(180, short_side, min_val=50)
    card_min_h = scale_px(38, short_side, min_val=16)
    solid_min_side = scale_px(16, short_side, min_val=8)

    for comp_id in range(1, int(num_features) + 1):
        ys, xs = np.where(labeled == comp_id)
        area = len(ys)
        if area < min_comp_area:
            continue

        x0, x1 = int(xs.min()), int(xs.max()) + 1
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        w, h = x1 - x0, y1 - y0
        if w < 1 or h < 1:
            continue

        comp_sub = labeled[y0:y1, x0:x1] == comp_id
        fill_ratio = area / float(w * h)
        comp_pixels = arr[ys, xs]
        comp_std = float(np.mean(np.std(comp_pixels, axis=0)))
        comp_med = np.median(comp_pixels, axis=0)
        comp_hex = rgb_to_hex(
            (int(round(comp_med[0])), int(round(comp_med[1])), int(round(comp_med[2])))
        )
        local_bg_rgb = sample_ring_background_rgb(arr, fg_mask, x0, y0, x1, y1, page_bg_rgb)

        # 1. Thin horizontal or vertical solid line (supports down to 1px thickness)
        comp_dist_bg = float(np.linalg.norm(comp_med - page_bg_rgb))
        is_horiz_line = (
            w >= line_min_len
            and h <= line_max_thick
            and (w / max(h, 1)) >= 12.0
            and fill_ratio >= 0.78
        )
        is_vert_line = (
            h >= line_min_len
            and w <= line_max_thick
            and (h / max(w, 1)) >= 12.0
            and fill_ratio >= 0.78
        )
        if (is_horiz_line or is_vert_line) and comp_std <= 25.0 and comp_dist_bg >= 32.0:
            axis_cov = np.mean(comp_sub, axis=0) if is_horiz_line else np.mean(comp_sub, axis=1)
            slices = np.array_split(axis_cov, 8)
            min_slice_cov = min(float(np.mean(s > 0.3)) for s in slices if len(s) > 0)
            if min_slice_cov >= 0.85:
                shape_seq += 1
                bx = px_to_emu(off_x + x0, full_w, slide_width_emu)
                by = px_to_emu(off_y + y0, full_h, slide_height_emu)
                bw = max(1, px_to_emu(w, full_w, slide_width_emu))
                bh = max(1, px_to_emu(h, full_h, slide_height_emu))
                pts = (
                    [(bx, by + bh // 2), (bx + bw, by + bh // 2)]
                    if is_horiz_line
                    else [(bx + bw // 2, by), (bx + bw // 2, by + bh)]
                )
                stroke_w = max(pt_to_emu(1.0), px_to_emu(min(w, h), full_h, slide_height_emu))
                shapes.append(
                    ShapeElement(
                        id=f"p{page_index}-sh-{shape_seq:03d}",
                        bbox=BBox(x=bx, y=by, width=bw, height=bh),
                        z_order=70 + _depth * 10,
                        confidence=0.92,
                        source="cv",
                        shape_type="line",
                        fill_color_hex=None,
                        stroke_color_hex=comp_hex,
                        stroke_width_emu=stroke_w,
                        points_emu=pts,
                    )
                )
                dil = np.asarray(binary_dilation(comp_sub, iterations=2), dtype=bool)
                residual[y0:y1, x0:x1][dil] = local_bg_rgb
                continue

        # 2. Hollow bordered container (with optional attached top header capsule)
        if w >= card_min_w and h >= card_min_h and 0.012 <= fill_ratio < 0.58:
            rem_sub = comp_sub.copy()
            card_top_offset = 0
            cap_box_coords: tuple[int, int, int] | None = None

            max_cap_h = min(scale_px(70, short_side, min_val=16), h // 3)
            min_cap_w = scale_px(110, short_side, min_val=30)
            min_cap_h = scale_px(30, short_side, min_val=12)
            if max_cap_h >= min_cap_h and w >= scale_px(360, short_side, min_val=100):
                top_band = comp_sub[:max_cap_h, :]
                col_dens = np.mean(
                    top_band[: min(max_cap_h, scale_px(44, short_side, 12)), :], axis=0
                )
                cap_cols = np.where(col_dens >= 0.70)[0]
                if len(cap_cols) >= min_cap_w:
                    cx0, cx1 = int(cap_cols.min()), int(cap_cols.max()) + 1
                    cw = cx1 - cx0
                    if min_cap_w <= cw <= int(w * 0.65):
                        row_dens = np.mean(top_band[:, cx0:cx1], axis=1)
                        cap_rows = np.where(row_dens >= 0.70)[0]
                        if len(cap_rows) >= min_cap_h:
                            cy1 = int(cap_rows.max()) + 1
                            cap_patch = arr[y0 : y0 + cy1, x0 + cx0 : x0 + cx1]
                            cap_mask = comp_sub[:cy1, cx0:cx1]
                            cap_fill_r = float(np.mean(cap_mask))
                            if cap_fill_r >= 0.78:
                                inner_cap = cap_patch[4 : max(5, cy1 - 4), 6 : max(7, cw - 6)]
                                cap_med = np.median(inner_cap.reshape(-1, 3), axis=0)
                                cap_hex = rgb_to_hex(
                                    (
                                        int(round(cap_med[0])),
                                        int(round(cap_med[1])),
                                        int(round(cap_med[2])),
                                    )
                                )
                                shape_seq += 1
                                shapes.append(
                                    ShapeElement(
                                        id=f"p{page_index}-sh-{shape_seq:03d}",
                                        bbox=BBox(
                                            x=px_to_emu(off_x + x0 + cx0, full_w, slide_width_emu),
                                            y=px_to_emu(off_y + y0, full_h, slide_height_emu),
                                            width=px_to_emu(cw, full_w, slide_width_emu),
                                            height=px_to_emu(cy1, full_h, slide_height_emu),
                                        ),
                                        z_order=75 + _depth * 10,
                                        confidence=0.90,
                                        source="cv",
                                        shape_type="round_rect",
                                        fill_color_hex=cap_hex,
                                        stroke_color_hex=cap_hex,
                                        stroke_width_emu=pt_to_emu(1.0),
                                        corner_radius_ratio=0.28,
                                    )
                                )
                                rem_sub[:cy1, cx0:cx1] = False
                                cap_box_coords = (cx0, cx1, cy1)
                                left_shoulder = comp_sub[
                                    : min(h, scale_px(38, short_side, 10)),
                                    min(w - 1, 25) : max(26, cx0 - 5),
                                ]
                                if left_shoulder.size > 0:
                                    sh_rows = np.where(np.mean(left_shoulder, axis=1) >= 0.40)[0]
                                    if len(sh_rows) > 0:
                                        card_top_offset = int(sh_rows.min())

            sub_h = h - card_top_offset
            sub_mask = rem_sub[card_top_offset:, :]
            rem_area = int(np.sum(sub_mask))
            if rem_area >= scale_area(160, short_side, min_val=30) and sub_h >= scale_px(
                32, short_side, 12
            ):
                bw_band = max(6, min(scale_px(15, short_side, 6), min(w, sub_h) // 10))
                perim_mask = np.zeros_like(sub_mask, dtype=bool)
                perim_mask[:bw_band, :] = True
                perim_mask[-bw_band:, :] = True
                perim_mask[:, :bw_band] = True
                perim_mask[:, -bw_band:] = True

                perim_ratio = float(np.sum(sub_mask & perim_mask)) / float(rem_area)
                left_cov = float(np.mean(np.any(sub_mask[:, :bw_band], axis=1)))
                right_cov = float(np.mean(np.any(sub_mask[:, -bw_band:], axis=1)))
                bot_cov = float(np.mean(np.any(sub_mask[-bw_band:, :], axis=0)))
                if (
                    perim_ratio >= 0.72
                    and left_cov >= 0.55
                    and right_cov >= 0.55
                    and bot_cov >= 0.65
                ):
                    border_pts = arr[y0 + card_top_offset : y1, x0:x1][sub_mask & perim_mask]
                    st_med = np.median(border_pts, axis=0)
                    st_hex = rgb_to_hex(
                        (int(round(st_med[0])), int(round(st_med[1])), int(round(st_med[2])))
                    )
                    shape_seq += 1
                    is_large_card = (w * sub_h) > (full_w * full_h * 0.05)
                    z_card = (10 if is_large_card else 25) + _depth * 10

                    sh_y0 = min(h - 1, card_top_offset + 8)
                    sh_y1 = max(
                        sh_y0 + 1, min(h - bw_band, card_top_offset + scale_px(64, short_side, 20))
                    )
                    sh_x0 = min(w - 1, bw_band + 6)
                    sh_x1 = max(
                        sh_x0 + 1,
                        (cap_box_coords[0] - 8) if cap_box_coords is not None else (w - bw_band),
                    )
                    inner_patch = arr[y0 + sh_y0 : y0 + sh_y1, x0 + sh_x0 : x0 + sh_x1]
                    inner_bg_mask = ~fg_mask[y0 + sh_y0 : y0 + sh_y1, x0 + sh_x0 : x0 + sh_x1]
                    if int(np.sum(inner_bg_mask)) >= 20:
                        card_inner_rgb = np.median(inner_patch[inner_bg_mask], axis=0)
                    elif inner_patch.size > 0:
                        card_inner_rgb = np.median(inner_patch.reshape(-1, 3), axis=0)
                    else:
                        card_inner_rgb = local_bg_rgb

                    inner_diff_from_page = float(np.linalg.norm(card_inner_rgb - page_bg_rgb))
                    card_fill_hex: str | None = None
                    if not is_large_card or inner_diff_from_page >= 6.0:
                        card_fill_hex = rgb_to_hex(
                            (
                                int(round(card_inner_rgb[0])),
                                int(round(card_inner_rgb[1])),
                                int(round(card_inner_rgb[2])),
                            )
                        )
                    shapes.append(
                        ShapeElement(
                            id=f"p{page_index}-sh-{shape_seq:03d}",
                            bbox=BBox(
                                x=px_to_emu(off_x + x0, full_w, slide_width_emu),
                                y=px_to_emu(off_y + y0 + card_top_offset, full_h, slide_height_emu),
                                width=px_to_emu(w, full_w, slide_width_emu),
                                height=px_to_emu(sub_h, full_h, slide_height_emu),
                            ),
                            z_order=z_card,
                            confidence=0.88,
                            source="cv",
                            shape_type="round_rect",
                            fill_color_hex=card_fill_hex,
                            stroke_color_hex=st_hex,
                            stroke_width_emu=pt_to_emu(1.75),
                            corner_radius_ratio=0.04,
                        )
                    )
                    border_only = np.zeros_like(comp_sub, dtype=bool)
                    border_only[card_top_offset:, :] = sub_mask & perim_mask
                    dil_border = np.asarray(binary_dilation(border_only, iterations=2), dtype=bool)
                    target_bg = page_bg_rgb if inner_diff_from_page >= 6.0 else card_inner_rgb
                    residual[y0:y1, x0:x1][dil_border] = target_bg
                    if inner_diff_from_page >= 6.0:
                        # Replace tinted interior with page_bg_rgb while keeping nested icons
                        card_patch = arr[y0 + card_top_offset : y1, x0:x1]
                        tint_mask = np.linalg.norm(card_patch - card_inner_rgb, axis=-1) <= 22.0
                        residual[y0 + card_top_offset : y1, x0:x1][tint_mask] = page_bg_rgb
                    if cap_box_coords is not None:
                        cx0_c, cx1_c, cy1_c = cap_box_coords
                        kx0 = max(0, cx0_c - 4)
                        kx1 = min(w, cx1_c + 4)
                        ky1 = min(h, cy1_c + 4)
                        residual[y0 : y0 + card_top_offset, x0 + kx0 : x0 + kx1] = page_bg_rgb
                        residual[y0 + card_top_offset : y0 + ky1, x0 + kx0 : x0 + kx1] = target_bg
                    continue

        # 3. Solid / stroked-solid geometric shape candidate (including arrows and solid containers)
        if fill_ratio >= 0.35 and w >= solid_min_side and h >= solid_min_side:
            px_pad = max(2, min(8, w // 6))
            py_pad = max(2, min(8, h // 6))
            core_patch = arr[y0 + py_pad : y1 - py_pad, x0 + px_pad : x1 - px_pad]
            core_mask = comp_sub[py_pad : h - py_pad, px_pad : w - px_pad]
            core_pts = core_patch[core_mask] if np.any(core_mask) else comp_pixels

            if len(core_pts) == 0:
                degraded_ids.append(f"p{page_index}-deg-{comp_id:03d}")
                continue

            is_large_solid = (
                w >= scale_px(240, short_side, min_val=80)
                and h >= scale_px(120, short_side, min_val=45)
                and (w * h) >= (full_w * full_h * 0.04)
            )
            # For large solid containers, estimate fill_med from inner margin ring
            if is_large_solid and w > 4 * px_pad and h > 4 * py_pad:
                ring_m = np.zeros_like(comp_sub, dtype=bool)
                ring_m[py_pad : 3 * py_pad, px_pad : w - px_pad] = True
                ring_m[h - 3 * py_pad : h - py_pad, px_pad : w - px_pad] = True
                ring_m[py_pad : h - py_pad, px_pad : 3 * px_pad] = True
                ring_m[py_pad : h - py_pad, w - 3 * px_pad : w - px_pad] = True
                ring_pts = arr[y0:y1, x0:x1][ring_m & comp_sub]
                fill_med = (
                    np.median(ring_pts, axis=0)
                    if len(ring_pts) >= 20
                    else np.median(core_pts, axis=0)
                )
            else:
                fill_med = np.median(core_pts, axis=0)

            core_dists = np.linalg.norm(core_pts - fill_med, axis=-1)
            uniform_ratio = float(np.mean(core_dists <= 32.0))
            uniform_std = (
                float(np.mean(np.std(core_pts[core_dists <= 32.0], axis=0)))
                if np.any(core_dists <= 32.0)
                else 99.0
            )
            min_uniform_ratio = 0.55 if is_large_solid else 0.75
            if uniform_ratio < min_uniform_ratio or uniform_std > 25.0:
                degraded_ids.append(f"p{page_index}-deg-{comp_id:03d}")
                continue

            filled_sub = np.asarray(binary_fill_holes(comp_sub), dtype=bool)
            # Classify geometry on hole-filled silhouette for containers/pills with interior icons
            geom_input = filled_sub if (is_large_solid or (w / max(h, 1)) >= 1.8) else comp_sub
            shape_kind, radius_ratio, conf = _classify_solid_geometry(geom_input, short_side)
            if shape_kind is None or conf < confidence_threshold:
                degraded_ids.append(f"p{page_index}-deg-{comp_id:03d}")
                continue

            # Check outer border stroke on large cards/banners first
            stroke_hex: str | None = None
            stroke_w_emu = 0
            if w >= scale_px(110, short_side, min_val=40) and h >= scale_px(
                40, short_side, min_val=18
            ):
                b_band = max(3, scale_px(5, short_side, min_val=3))
                edge_ring = comp_sub.copy()
                if h > 2 * b_band and w > 2 * b_band:
                    edge_ring[b_band:-b_band, b_band:-b_band] = False
                edge_pts = arr[y0:y1, x0:x1][edge_ring]
                if len(edge_pts) > 0:
                    d_fill_arr = np.linalg.norm(edge_pts - fill_med, axis=-1)
                    top_edge_pts = edge_pts[d_fill_arr >= np.percentile(d_fill_arr, 65.0)]
                    edge_med = np.median(top_edge_pts, axis=0)
                    dist_fill = float(np.linalg.norm(edge_med - fill_med))
                    dist_bg = float(np.linalg.norm(edge_med - page_bg_rgb))
                    dist_fb = float(np.linalg.norm(fill_med - page_bg_rgb))
                    if dist_fill > 24.0 and (dist_fill + dist_bg) > (dist_fb * 1.15):
                        stroke_hex = rgb_to_hex(
                            (
                                int(round(edge_med[0])),
                                int(round(edge_med[1])),
                                int(round(edge_med[2])),
                            )
                        )
                        stroke_w_emu = pt_to_emu(1.5)

            # Inspect eroded interior for high-contrast internal details (icons / child shapes)
            erode_iters = (
                max(4, scale_px(7, short_side, min_val=4))
                if stroke_hex is not None
                else max(2, scale_px(4, short_side, min_val=2))
            )
            eroded_inner = np.asarray(
                binary_erosion(filled_sub, iterations=erode_iters), dtype=bool
            )
            patch_sub = arr[y0:y1, x0:x1]
            diff_from_fill = np.linalg.norm(patch_sub - fill_med, axis=-1)
            inner_detail = eroded_inner & (diff_from_fill > 42.0)
            detail_px = int(np.sum(inner_detail))
            detail_ratio = float(detail_px) / max(1.0, float(np.sum(eroded_inner)))

            # Defect 3 protection: compact icon with internal markings (e.g. SKILL.md doc icon)
            # must NOT be flattened into a solid ShapeElement; leave for layers.py as ImageElement
            max_compact_side = scale_px(210, short_side, min_val=60)
            if (
                not is_large_solid
                and (w / float(max(h, 1))) < 1.8
                and w <= max_compact_side
                and h <= max_compact_side
                and detail_ratio >= 0.03
                and detail_px >= scale_area(50, short_side, min_val=12)
            ):
                degraded_ids.append(f"p{page_index}-deg-{comp_id:03d}")
                continue

            fill_hex = rgb_to_hex(
                (int(round(fill_med[0])), int(round(fill_med[1])), int(round(fill_med[2])))
            )
            shape_seq += 1
            z_solid = (18 if is_large_solid else 75) + _depth * 10
            ins = 1 if stroke_hex is not None else 0
            shapes.append(
                ShapeElement(
                    id=f"p{page_index}-sh-{shape_seq:03d}",
                    bbox=BBox(
                        x=px_to_emu(off_x + x0 + ins, full_w, slide_width_emu),
                        y=px_to_emu(off_y + y0 + ins, full_h, slide_height_emu),
                        width=px_to_emu(max(1, w - 2 * ins), full_w, slide_width_emu),
                        height=px_to_emu(max(1, h - 2 * ins), full_h, slide_height_emu),
                    ),
                    z_order=z_solid,
                    confidence=conf,
                    source="cv",
                    shape_type=shape_kind,
                    fill_color_hex=fill_hex,
                    stroke_color_hex=stroke_hex,
                    stroke_width_emu=stroke_w_emu,
                    corner_radius_ratio=(
                        0.05 if is_large_solid and shape_kind == "round_rect" else radius_ratio
                    ),
                )
            )

            # Recursive Container Decomposition relative to fill_med
            if detail_px >= scale_area(55, short_side, min_val=14):
                sub_canvas = np.broadcast_to(fill_med, (h, w, 3)).astype(np.float32).copy()
                sub_canvas[eroded_inner] = patch_sub[eroded_inner]

                if is_large_solid and _depth < 2:
                    sub_res = extract_raster_shapes(
                        Image.fromarray(np.clip(sub_canvas, 0, 255).astype(np.uint8)),
                        slide_width_emu=slide_width_emu,
                        slide_height_emu=slide_height_emu,
                        page_index=page_index,
                        confidence_threshold=confidence_threshold,
                        _offset_px=(off_x + x0, off_y + y0),
                        _full_size_px=(full_w, full_h),
                        _depth=_depth + 1,
                        _seq_start=shape_seq,
                    )
                    shapes.extend(sub_res.shapes)
                    shape_seq += len(sub_res.shapes)
                    embedded_crops.extend(sub_res.embedded_crops)
                    sub_canvas = np.asarray(sub_res.residual_image, dtype=np.float32)

                new_crops = _extract_embedded_crops_from_canvas(
                    canvas_arr=sub_canvas,
                    bg_rgb=fill_med,
                    offset_x=off_x + x0,
                    offset_y=off_y + y0,
                    full_w=full_w,
                    full_h=full_h,
                    slide_width_emu=slide_width_emu,
                    slide_height_emu=slide_height_emu,
                    z_order=z_solid + 5,
                )
                embedded_crops.extend(new_crops)

            erase_dil = np.asarray(binary_dilation(filled_sub, iterations=1), dtype=bool)
            residual[y0:y1, x0:x1][erase_dil] = local_bg_rgb
            continue

        degraded_ids.append(f"p{page_index}-deg-{comp_id:03d}")

    return ShapeExtractionResult(
        shapes=shapes,
        degraded_ids=degraded_ids,
        residual_image=Image.fromarray(np.clip(residual, 0, 255).astype(np.uint8)),
        embedded_crops=embedded_crops,
    )
