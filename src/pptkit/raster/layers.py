from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, label

from pptkit.common.units import (
    DEFAULT_SLIDE_HEIGHT_EMU,
    DEFAULT_SLIDE_WIDTH_EMU,
    px_to_emu,
)
from pptkit.ir.models import BBox, ImageElement
from pptkit.raster.shapes import estimate_page_background_rgb


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
    fg_mask = dist_map > 22.0

    # Group nearby illustration strokes using a 15x15 structuring kernel
    group_mask = np.asarray(
        binary_dilation(fg_mask, structure=np.ones((15, 15), dtype=bool), iterations=1),
        dtype=bool,
    )
    lbl_res: tuple[np.ndarray, int] = label(group_mask)  # type: ignore[assignment]
    labeled_arr, num_features = lbl_res
    labeled = np.asarray(labeled_arr, dtype=np.int32)

    images: list[ImageElement] = []
    img_seq = 0

    for comp_id in range(1, int(num_features) + 1):
        comp_fg = (labeled == comp_id) & fg_mask
        ys, xs = np.where(comp_fg)
        fg_count = len(ys)
        if fg_count < 380:
            continue
        if float(np.percentile(dist_map[ys, xs], 85)) < 45.0:
            continue

        x0_raw, x1_raw = int(xs.min()), int(xs.max()) + 1
        y0_raw, y1_raw = int(ys.min()), int(ys.max()) + 1
        w_raw, h_raw = x1_raw - x0_raw, y1_raw - y0_raw

        # Skip thin 1D dashed lines or tiny artifacts
        if w_raw < 24 or h_raw < 22:
            continue
        aspect = w_raw / float(max(h_raw, 1))
        if aspect > 7.5 or aspect < (1.0 / 7.5):
            continue

        pad = 2
        x0 = max(0, x0_raw - pad)
        y0 = max(0, y0_raw - pad)
        x1 = min(w_img, x1_raw + pad)
        y1 = min(h_img, y1_raw + pad)
        w, h = x1 - x0, y1 - y0

        patch_rgb = np.clip(np.round(arr[y0:y1, x0:x1]), 0, 255).astype(np.uint8)
        patch_dist = dist_map[y0:y1, x0:x1]

        # Exterior background connected to the crop boundary gets alpha=0; interior stays opaque
        bg_cand = patch_dist <= 18.0
        bg_lbl_res: tuple[np.ndarray, int] = label(bg_cand)  # type: ignore[assignment]
        bg_lbl, _ = bg_lbl_res
        border_labels = set(np.unique(bg_lbl[0, :]))
        border_labels.update(np.unique(bg_lbl[-1, :]))
        border_labels.update(np.unique(bg_lbl[:, 0]))
        border_labels.update(np.unique(bg_lbl[:, -1]))
        border_labels.discard(0)

        ext_bg_mask = np.isin(bg_lbl, list(border_labels))
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

        # Erase foreground pixels of this illustration from final_bg_image
        sub_fg = comp_fg[y0:y1, x0:x1]
        erase_sub = np.asarray(binary_dilation(sub_fg, iterations=2), dtype=bool)
        final_bg[y0:y1, x0:x1][erase_sub] = page_bg_rgb

    return LayerExtractionResult(
        images=images,
        final_bg_image=Image.fromarray(np.clip(final_bg, 0, 255).astype(np.uint8)),
    )
