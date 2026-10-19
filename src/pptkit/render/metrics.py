from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity

from pptkit.common.units import emu_to_px
from pptkit.ir.models import BBox


@dataclass
class SlideComparisonResult:
    ssim: float
    text_region_mae: float
    heatmap_path: str | None


def _jet_colormap(norm_diff: np.ndarray) -> np.ndarray:
    v = np.clip(norm_diff * 4.0, 0.0, 4.0)
    r = np.clip(np.minimum(v - 1.5, -v + 4.5), 0.0, 1.0)
    g = np.clip(np.minimum(v - 0.5, -v + 3.5), 0.0, 1.0)
    b = np.clip(np.minimum(v + 0.5, -v + 2.5), 0.0, 1.0)
    return (np.stack([r, g, b], axis=-1) * 255.0).astype(np.uint8)


def compare_slide_images(
    orig_png: Path | str,
    rendered_png: Path | str,
    text_bboxes: list[BBox],
    slide_width_emu: int,
    slide_height_emu: int,
    heatmap_path: Path | str | None = None,
) -> SlideComparisonResult:
    with Image.open(orig_png) as img_a_raw:
        img_a = img_a_raw.convert("RGB")
    with Image.open(rendered_png) as img_b_raw:
        img_b = img_b_raw.convert("RGB")

    if img_b.size != img_a.size:
        img_b = img_b.resize(img_a.size, Image.Resampling.LANCZOS)

    arr_a = np.asarray(img_a, dtype=np.float32)
    arr_b = np.asarray(img_b, dtype=np.float32)

    raw_ssim = structural_similarity(
        arr_a,
        arr_b,
        channel_axis=-1,
        data_range=255.0,
    )
    ssim_val = float(raw_ssim[0] if isinstance(raw_ssim, tuple) else raw_ssim)

    abs_diff = np.abs(arr_a - arr_b)
    width_px, height_px = img_a.size

    if text_bboxes:
        mask = np.zeros((height_px, width_px), dtype=bool)
        for box in text_bboxes:
            x0 = max(0, emu_to_px(box.x, width_px, slide_width_emu))
            y0 = max(0, emu_to_px(box.y, height_px, slide_height_emu))
            x1 = min(width_px, emu_to_px(box.x + box.width, width_px, slide_width_emu))
            y1 = min(height_px, emu_to_px(box.y + box.height, height_px, slide_height_emu))
            if x1 > x0 and y1 > y0:
                mask[y0:y1, x0:x1] = True
        if np.any(mask):
            text_mae = float(np.mean(abs_diff[mask]))
        else:
            text_mae = 0.0
    else:
        text_mae = float(np.mean(abs_diff))

    saved_heatmap: str | None = None
    if heatmap_path is not None:
        out_hp = Path(heatmap_path)
        out_hp.parent.mkdir(parents=True, exist_ok=True)
        mean_diff_norm = np.mean(abs_diff, axis=-1) / 255.0
        heat_rgb = _jet_colormap(mean_diff_norm).astype(np.float32)
        blended = np.clip(0.55 * arr_a + 0.45 * heat_rgb, 0, 255).astype(np.uint8)
        Image.fromarray(blended).save(out_hp)
        saved_heatmap = str(out_hp)

    return SlideComparisonResult(
        ssim=ssim_val,
        text_region_mae=text_mae,
        heatmap_path=saved_heatmap,
    )
