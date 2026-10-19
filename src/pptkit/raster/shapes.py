import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, label

from pptkit.common.color import rgb_to_hex
from pptkit.common.units import (
    DEFAULT_SLIDE_HEIGHT_EMU,
    DEFAULT_SLIDE_WIDTH_EMU,
    pt_to_emu,
    px_to_emu,
)
from pptkit.ir.models import BBox, ShapeElement

SHAPE_CONFIDENCE_THRESHOLD = 0.75


@dataclass
class ShapeExtractionResult:
    shapes: list[ShapeElement] = field(default_factory=list)
    degraded_ids: list[str] = field(default_factory=list)
    residual_image: Image.Image = field(default_factory=lambda: Image.new("RGB", (1, 1)))


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


def _is_right_arrow(comp_mask: np.ndarray) -> bool:
    h, w = comp_mask.shape
    if w < h * 1.15 or w < 30 or h < 18:
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
    # Tail should generally decrease toward the right tip
    diffs = np.diff(tail)
    non_increasing_ratio = float(np.mean(diffs <= 2.0))
    return non_increasing_ratio >= 0.75 and float(tail[-1]) <= h * 0.35


def _classify_solid_geometry(
    comp_mask: np.ndarray,
) -> tuple[Literal["rect", "round_rect", "ellipse", "right_arrow"] | None, float, float]:
    h, w = comp_mask.shape
    area = float(np.sum(comp_mask))
    fill_ratio = area / float(max(w * h, 1))

    if _is_right_arrow(comp_mask):
        return "right_arrow", 0.0, 0.90

    # Corner fill check
    cw = max(2, min(w, h) // 6)
    corners = [
        comp_mask[:cw, :cw],
        comp_mask[:cw, -cw:],
        comp_mask[-cw:, :cw],
        comp_mask[-cw:, -cw:],
    ]
    corner_fill = float(np.mean([np.mean(c) for c in corners]))

    # Mid-edge fill check (middle 40% of each of the 4 sides)
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

    # Ideal ellipse IoU
    yy, xx = np.ogrid[:h, :w]
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    ry, rx = max(h / 2.0, 1.0), max(w / 2.0, 1.0)
    ideal_ellipse = ((yy - cy) / ry) ** 2 + ((xx - cx) / rx) ** 2 <= 1.0
    inter = float(np.sum(comp_mask & ideal_ellipse))
    union = float(np.sum(comp_mask | ideal_ellipse))
    ellipse_iou = inter / max(union, 1.0)

    if fill_ratio >= 0.95 and corner_fill >= 0.82:
        return "rect", 0.0, 0.96

    if ellipse_iou >= 0.90 and fill_ratio <= 0.84 and corner_fill <= 0.18:
        return "ellipse", 0.0, 0.92

    if fill_ratio >= 0.74 and mid_edge_fill >= 0.78:
        missing_ratio = max(0.0, 1.0 - fill_ratio)
        r_px = math.sqrt(missing_ratio * w * h / max(4.0 - math.pi, 0.1))
        radius_ratio = float(np.clip(r_px / max(min(w, h), 1), 0.06, 0.48))
        return "round_rect", round(radius_ratio, 3), 0.90

    return None, 0.0, 0.45


def extract_raster_shapes(
    image: Image.Image,
    slide_width_emu: int = DEFAULT_SLIDE_WIDTH_EMU,
    slide_height_emu: int = DEFAULT_SLIDE_HEIGHT_EMU,
    page_index: int = 0,
    confidence_threshold: float = SHAPE_CONFIDENCE_THRESHOLD,
) -> ShapeExtractionResult:
    rgb_img = image.convert("RGB")
    arr = np.asarray(rgb_img, dtype=np.float32).copy()
    residual = arr.copy()
    h_img, w_img, _ = arr.shape

    page_bg_rgb = estimate_page_background_rgb(arr)
    page_bg_hex = rgb_to_hex(
        (int(round(page_bg_rgb[0])), int(round(page_bg_rgb[1])), int(round(page_bg_rgb[2])))
    )

    dist_map = np.linalg.norm(arr - page_bg_rgb, axis=-1)
    fg_mask = dist_map > 20.0
    lbl_res: tuple[np.ndarray, int] = label(fg_mask)  # type: ignore[assignment]
    labeled_arr, num_features = lbl_res
    labeled = np.asarray(labeled_arr, dtype=np.int32)

    shapes: list[ShapeElement] = []
    degraded_ids: list[str] = []
    shape_seq = 0

    for comp_id in range(1, int(num_features) + 1):
        ys, xs = np.where(labeled == comp_id)
        area = len(ys)
        if area < 150:
            continue

        x0, x1 = int(xs.min()), int(xs.max()) + 1
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        w, h = x1 - x0, y1 - y0
        if w < 4 or h < 4:
            continue

        comp_sub = labeled[y0:y1, x0:x1] == comp_id
        fill_ratio = area / float(w * h)
        comp_pixels = arr[ys, xs]
        comp_std = float(np.mean(np.std(comp_pixels, axis=0)))
        comp_med = np.median(comp_pixels, axis=0)
        comp_hex = rgb_to_hex(
            (int(round(comp_med[0])), int(round(comp_med[1])), int(round(comp_med[2])))
        )

        # 1. Thin horizontal or vertical line
        is_horiz_line = w >= 40 and h <= 12 and (w / max(h, 1)) >= 10.0 and fill_ratio >= 0.65
        is_vert_line = h >= 40 and w <= 12 and (h / max(w, 1)) >= 10.0 and fill_ratio >= 0.65
        if (is_horiz_line or is_vert_line) and comp_std <= 30.0:
            shape_seq += 1
            bx = px_to_emu(x0, w_img, slide_width_emu)
            by = px_to_emu(y0, h_img, slide_height_emu)
            bw = max(1, px_to_emu(w, w_img, slide_width_emu))
            bh = max(1, px_to_emu(h, h_img, slide_height_emu))
            pts = (
                [(bx, by + bh // 2), (bx + bw, by + bh // 2)]
                if is_horiz_line
                else [(bx + bw // 2, by), (bx + bw // 2, by + bh)]
            )
            stroke_w = max(pt_to_emu(1.0), px_to_emu(min(w, h), h_img, slide_height_emu))
            shapes.append(
                ShapeElement(
                    id=f"p{page_index}-sh-{shape_seq:03d}",
                    bbox=BBox(x=bx, y=by, width=bw, height=bh),
                    z_order=70,
                    confidence=0.92,
                    source="cv",
                    shape_type="line",
                    fill_color_hex=None,
                    stroke_color_hex=comp_hex,
                    stroke_width_emu=stroke_w,
                    points_emu=pts,
                )
            )
            dil = np.asarray(binary_dilation(comp_sub, iterations=1), dtype=bool)
            residual[y0:y1, x0:x1][dil] = page_bg_rgb
            continue

        # 2. Hollow bordered container (with optional attached top header capsule)
        if w >= 140 and h >= 42 and 0.06 <= fill_ratio < 0.58:
            rem_sub = comp_sub.copy()
            card_top_offset = 0

            # Check for attached top solid header capsule (like the 4 section headers)
            max_cap_h = min(76, h // 3)
            if max_cap_h >= 36 and w >= 400:
                top_band = comp_sub[:max_cap_h, :]
                col_dens = np.mean(top_band[:48, :], axis=0)
                cap_cols = np.where(col_dens >= 0.70)[0]
                if len(cap_cols) >= 120:
                    cx0, cx1 = int(cap_cols.min()), int(cap_cols.max()) + 1
                    cw = cx1 - cx0
                    if 120 <= cw <= int(w * 0.65):
                        row_dens = np.mean(top_band[:, cx0:cx1], axis=1)
                        cap_rows = np.where(row_dens >= 0.70)[0]
                        if len(cap_rows) >= 34:
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
                                            x=px_to_emu(x0 + cx0, w_img, slide_width_emu),
                                            y=px_to_emu(y0, h_img, slide_height_emu),
                                            width=px_to_emu(cw, w_img, slide_width_emu),
                                            height=px_to_emu(cy1, h_img, slide_height_emu),
                                        ),
                                        z_order=75,
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
                                # Find top border row of the main card outside the capsule
                                left_shoulder = comp_sub[:40, 25 : max(26, cx0 - 5)]
                                sh_rows = np.where(np.mean(left_shoulder, axis=1) >= 0.40)[0]
                                if len(sh_rows) > 0:
                                    card_top_offset = int(sh_rows.min())

            # Check perimeter concentration on remaining container `[card_top_offset:h, 0:w]`
            sub_h = h - card_top_offset
            sub_mask = rem_sub[card_top_offset:, :]
            rem_area = int(np.sum(sub_mask))
            if rem_area >= 200 and sub_h >= 36:
                bw_band = max(8, min(16, min(w, sub_h) // 10))
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
                    z_card = 10 if (w * sub_h) > (w_img * h_img * 0.05) else 25
                    shapes.append(
                        ShapeElement(
                            id=f"p{page_index}-sh-{shape_seq:03d}",
                            bbox=BBox(
                                x=px_to_emu(x0, w_img, slide_width_emu),
                                y=px_to_emu(y0 + card_top_offset, h_img, slide_height_emu),
                                width=px_to_emu(w, w_img, slide_width_emu),
                                height=px_to_emu(sub_h, h_img, slide_height_emu),
                            ),
                            z_order=z_card,
                            confidence=0.88,
                            source="cv",
                            shape_type="round_rect",
                            fill_color_hex=page_bg_hex,
                            stroke_color_hex=st_hex,
                            stroke_width_emu=pt_to_emu(1.75),
                            corner_radius_ratio=0.04,
                        )
                    )
                    dil = np.asarray(binary_dilation(comp_sub, iterations=1), dtype=bool)
                    residual[y0:y1, x0:x1][dil] = page_bg_rgb
                    continue

        # 3. Solid / stroked-solid geometric shape candidate (including arrows)
        if fill_ratio >= 0.35 and w >= 18 and h >= 18:
            px_pad = max(2, min(8, w // 6))
            py_pad = max(2, min(8, h // 6))
            core_patch = arr[y0 + py_pad : y1 - py_pad, x0 + px_pad : x1 - px_pad]
            core_mask = comp_sub[py_pad : h - py_pad, px_pad : w - px_pad]
            core_pts = core_patch[core_mask] if np.any(core_mask) else comp_pixels

            if len(core_pts) == 0:
                degraded_ids.append(f"p{page_index}-deg-{comp_id:03d}")
                continue

            fill_med = np.median(core_pts, axis=0)
            core_dists = np.linalg.norm(core_pts - fill_med, axis=-1)
            uniform_ratio = float(np.mean(core_dists <= 32.0))
            uniform_std = (
                float(np.mean(np.std(core_pts[core_dists <= 32.0], axis=0)))
                if np.any(core_dists <= 32.0)
                else 99.0
            )

            if uniform_ratio < 0.75 or uniform_std > 25.0:
                degraded_ids.append(f"p{page_index}-deg-{comp_id:03d}")
                continue

            shape_kind, radius_ratio, conf = _classify_solid_geometry(comp_sub)
            if shape_kind is None or conf < confidence_threshold:
                degraded_ids.append(f"p{page_index}-deg-{comp_id:03d}")
                continue

            fill_hex = rgb_to_hex(
                (int(round(fill_med[0])), int(round(fill_med[1])), int(round(fill_med[2])))
            )

            # Check if outer 5px border has a distinct stroke color on large cards/banners
            stroke_hex: str | None = None
            stroke_w_emu = 0
            if w >= 120 and h >= 45:
                b_band = 5
                edge_ring = comp_sub.copy()
                edge_ring[b_band:-b_band, b_band:-b_band] = False
                edge_pts = arr[y0:y1, x0:x1][edge_ring]
                if len(edge_pts) > 0:
                    d_fill_arr = np.linalg.norm(edge_pts - fill_med, axis=-1)
                    top_edge_pts = edge_pts[d_fill_arr >= np.percentile(d_fill_arr, 65.0)]
                    edge_med = np.median(top_edge_pts, axis=0)
                    dist_fill = float(np.linalg.norm(edge_med - fill_med))
                    dist_bg = float(np.linalg.norm(edge_med - page_bg_rgb))
                    dist_fb = float(np.linalg.norm(fill_med - page_bg_rgb))
                    # Ignore anti-aliasing where edge_med lies between fill_med and page_bg_rgb
                    if dist_fill > 24.0 and (dist_fill + dist_bg) > (dist_fb * 1.15):
                        stroke_hex = rgb_to_hex(
                            (
                                int(round(edge_med[0])),
                                int(round(edge_med[1])),
                                int(round(edge_med[2])),
                            )
                        )
                        stroke_w_emu = pt_to_emu(1.75)

            shape_seq += 1
            z_solid = 18 if (w * h) > (w_img * h_img * 0.06) else 75
            shapes.append(
                ShapeElement(
                    id=f"p{page_index}-sh-{shape_seq:03d}",
                    bbox=BBox(
                        x=px_to_emu(x0, w_img, slide_width_emu),
                        y=px_to_emu(y0, h_img, slide_height_emu),
                        width=px_to_emu(w, w_img, slide_width_emu),
                        height=px_to_emu(h, h_img, slide_height_emu),
                    ),
                    z_order=z_solid,
                    confidence=conf,
                    source="cv",
                    shape_type=shape_kind,
                    fill_color_hex=fill_hex,
                    stroke_color_hex=stroke_hex,
                    stroke_width_emu=stroke_w_emu,
                    corner_radius_ratio=(
                        0.04 if z_solid == 18 and shape_kind == "round_rect" else radius_ratio
                    ),
                )
            )

            # Erase shape from residual_image, preserving embedded icons inside wide banners
            erase_mask = np.asarray(binary_dilation(comp_sub, iterations=1), dtype=bool)
            if w >= 600 and h >= 50:
                patch_sub = arr[y0:y1, x0:x1]
                diff_from_fill = np.linalg.norm(patch_sub - fill_med, axis=-1)
                inner_zone = np.zeros_like(comp_sub, dtype=bool)
                inner_zone[8:-8, 8:-8] = True
                embedded_icon = inner_zone & (diff_from_fill > 55.0)
                if int(np.sum(embedded_icon)) >= 120:
                    keep_icon = np.asarray(binary_dilation(embedded_icon, iterations=1), dtype=bool)
                    erase_mask = erase_mask & (~keep_icon)

            residual[y0:y1, x0:x1][erase_mask] = page_bg_rgb
            continue

        degraded_ids.append(f"p{page_index}-deg-{comp_id:03d}")

    return ShapeExtractionResult(
        shapes=shapes,
        degraded_ids=degraded_ids,
        residual_image=Image.fromarray(np.clip(residual, 0, 255).astype(np.uint8)),
    )
