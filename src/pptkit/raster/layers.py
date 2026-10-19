from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import binary_closing, binary_dilation, label

from pptkit.common.units import (
    DEFAULT_SLIDE_HEIGHT_EMU,
    DEFAULT_SLIDE_WIDTH_EMU,
    px_to_emu,
)
from pptkit.ir.models import BBox, ImageElement
from pptkit.raster.shapes import estimate_page_background_rgb, sample_ring_background_rgb


@dataclass
class LayerExtractionResult:
    images: list[ImageElement] = field(default_factory=list)
    final_bg_image: Image.Image = field(default_factory=lambda: Image.new("RGB", (1, 1)))


def extract_image_layers(
    image: Image.Image,
    work_dir: Path | str,
    slide_width_emu: int = DEFAULT_SLIDE_WIDTH_EMU,
    slide_height_emu: int = DEFAULT_SLIDE_HEIGHT_EMU,
    page_index: int = 0,
) -> LayerExtractionResult:
    w_dir = Path(work_dir).resolve()
    w_dir.mkdir(parents=True, exist_ok=True)

    rgb_img = image.convert("RGB")
    arr = np.asarray(rgb_img, dtype=np.float32).copy()
    final_bg = arr.copy()
    h_img, w_img, _ = arr.shape

    page_bg_rgb = estimate_page_background_rgb(arr)
    dist_map = np.linalg.norm(arr - page_bg_rgb, axis=-1)
    fg_mask = dist_map > 28.0

    # Use a 3x3 closing kernel to bridge 1px anti-aliased gaps without merging neighboring icons
    closed_mask = np.asarray(
        binary_closing(fg_mask, structure=np.ones((3, 3), dtype=bool), iterations=1),
        dtype=bool,
    )
    lbl_res: tuple[np.ndarray, int] = label(closed_mask)  # type: ignore[assignment]
    labeled_arr, num_features = lbl_res
    labeled = np.asarray(labeled_arr, dtype=np.int32)

    # Collect raw foreground components: [x0, y0, x1, y1, fg_count, [comp_ids]]
    raw_groups: list[list[int | list[int]]] = []
    for comp_id in range(1, int(num_features) + 1):
        comp_fg = (labeled == comp_id) & fg_mask
        ys, xs = np.where(comp_fg)
        fg_count = len(ys)
        if fg_count < 80:
            continue
        if float(np.percentile(dist_map[ys, xs], 85)) < 45.0:
            continue

        x0_c, x1_c = int(xs.min()), int(xs.max()) + 1
        y0_c, y1_c = int(ys.min()), int(ys.max()) + 1
        w_c, h_c = x1_c - x0_c, y1_c - y0_c
        if w_c < 10 and h_c < 10:
            continue
        raw_groups.append([x0_c, y0_c, x1_c, y1_c, fg_count, [comp_id]])

    # Merge enclosed inner parts (e.g. table/pie inside document) and compact multi-stroke icons
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

                ix0, iy0 = max(ax0, bx0), max(ay0, by0)
                ix1, iy1 = min(ax1, bx1), min(ay1, by1)
                inter = max(0, ix1 - ix0) * max(0, iy1 - iy0)
                area_a = max(1, (ax1 - ax0) * (ay1 - ay0))
                area_b = max(1, (bx1 - bx0) * (by1 - by0))
                is_enclosed = (inter / float(min(area_a, area_b))) >= 0.80

                ux0, uy0 = min(ax0, bx0), min(ay0, by0)
                ux1, uy1 = max(ax1, bx1), max(ay1, by1)
                uw, uh = ux1 - ux0, uy1 - uy0
                gap_x = max(0, max(ax0, bx0) - min(ax1, bx1))
                gap_y = max(0, max(ay0, by0) - min(ay1, by1))

                # Compact multi-stroke icon (download arrow+tray, refresh arcs, rays)
                is_compact_icon = uw <= 95 and uh <= 95 and gap_x <= 14 and gap_y <= 22
                # Parallel double-underline decorative strokes
                horiz_ov = max(0, min(ax1, bx1) - max(ax0, bx0)) / float(
                    max(1, min(ax1 - ax0, bx1 - bx0))
                )
                is_double_underline = uh <= 36 and uw <= 220 and gap_y <= 10 and horiz_ov >= 0.75

                if is_enclosed or is_compact_icon or is_double_underline:
                    raw_groups[i] = [ux0, uy0, ux1, uy1, afg + bfg, acids + bcids]
                    raw_groups.pop(j)
                    changed = True
                    break

    final_groups: list[list[int | list[int]]] = []
    for grp in sorted(raw_groups, key=lambda g: (int(g[1]) // 180, int(g[0]))):  # type: ignore[arg-type]
        x0_raw = int(grp[0])  # type: ignore[arg-type]
        y0_raw = int(grp[1])  # type: ignore[arg-type]
        x1_raw = int(grp[2])  # type: ignore[arg-type]
        y1_raw = int(grp[3])  # type: ignore[arg-type]
        fg_count = int(grp[4])  # type: ignore[arg-type]
        w_raw, h_raw = x1_raw - x0_raw, y1_raw - y0_raw
        if fg_count < 320 or w_raw < 22 or h_raw < 20:
            continue
        aspect = w_raw / float(max(h_raw, 1))
        if aspect > 8.5 or aspect < (1.0 / 8.5):
            continue
        final_groups.append(grp)

    images: list[ImageElement] = []
    img_seq = 0

    for idx_g, grp in enumerate(final_groups):
        x0_raw = int(grp[0])  # type: ignore[arg-type]
        y0_raw = int(grp[1])  # type: ignore[arg-type]
        x1_raw = int(grp[2])  # type: ignore[arg-type]
        y1_raw = int(grp[3])  # type: ignore[arg-type]
        other_cids: list[int] = [
            cid
            for k, other_g in enumerate(final_groups)
            if k != idx_g
            for cid in other_g[5]  # type: ignore[union-attr]
        ]

        pad = 2
        x0 = max(0, x0_raw - pad)
        y0 = max(0, y0_raw - pad)
        x1 = min(w_img, x1_raw + pad)
        y1 = min(h_img, y1_raw + pad)
        w, h = x1 - x0, y1 - y0

        patch_rgb = np.clip(np.round(arr[y0:y1, x0:x1]), 0, 255).astype(np.uint8)
        patch_dist = dist_map[y0:y1, x0:x1]
        sub_lbl = labeled[y0:y1, x0:x1]

        other_comp = (
            np.isin(sub_lbl, other_cids) if other_cids else np.zeros_like(sub_lbl, dtype=bool)
        )
        own_comp = (sub_lbl > 0) & (~other_comp)
        other_dil = (
            np.asarray(binary_dilation(other_comp, iterations=2), dtype=bool)
            if np.any(other_comp)
            else np.zeros_like(own_comp, dtype=bool)
        )

        # Exterior background connected to the crop boundary (or other icons) gets alpha=0
        bg_cand = (patch_dist <= 20.0) | other_dil
        bg_lbl_res: tuple[np.ndarray, int] = label(bg_cand)  # type: ignore[assignment]
        bg_lbl, _ = bg_lbl_res
        border_labels = set(np.unique(bg_lbl[0, :]))
        border_labels.update(np.unique(bg_lbl[-1, :]))
        border_labels.update(np.unique(bg_lbl[:, 0]))
        border_labels.update(np.unique(bg_lbl[:, -1]))
        border_labels.discard(0)

        ext_bg_mask = np.isin(bg_lbl, list(border_labels)) | other_dil
        alpha = np.where(ext_bg_mask, 0, 255).astype(np.uint8)

        rgba = np.dstack([patch_rgb, alpha])
        img_seq += 1
        out_png = w_dir / f"slide_{page_index:03d}_img_{img_seq:03d}.png"
        Image.fromarray(rgba, mode="RGBA").save(out_png)

        images.append(
            ImageElement(
                id=f"p{page_index}-img-{img_seq:03d}",
                bbox=BBox(
                    x=px_to_emu(x0, w_img, slide_width_emu),
                    y=px_to_emu(y0, h_img, slide_height_emu),
                    width=max(1, px_to_emu(w, w_img, slide_width_emu)),
                    height=max(1, px_to_emu(h, h_img, slide_height_emu)),
                ),
                z_order=40 + img_seq,
                confidence=0.90,
                source="cv",
                degraded=False,
                image_path=str(out_png),
            )
        )

        # Erase this illustration's opaque region from final_bg_image using local background
        local_bg_rgb = sample_ring_background_rgb(arr, fg_mask, x0, y0, x1, y1, page_bg_rgb)
        erase_sub = np.asarray(binary_dilation(alpha > 0, iterations=2), dtype=bool)
        final_bg[y0:y1, x0:x1][erase_sub] = local_bg_rgb

    return LayerExtractionResult(
        images=images,
        final_bg_image=Image.fromarray(np.clip(final_bg, 0, 255).astype(np.uint8)),
    )
