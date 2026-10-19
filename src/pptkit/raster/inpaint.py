from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation

from pptkit.adapters.ocr import AppleVisionOCRAdapter, OCRBox
from pptkit.raster.text_style import sample_local_background_rgb


def inpaint_text_regions(image: Image.Image, boxes: list[OCRBox]) -> Image.Image:
    rgb = image.convert("RGB")
    arr = np.asarray(rgb, dtype=np.float32).copy()
    h_img, w_img, _ = arr.shape

    for box in boxes:
        x, y, w, h = box.bbox_px
        pad = 3
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(w_img, x + w + pad), min(h_img, y + h + pad)
        if x1 <= x0 or y1 <= y0:
            continue

        bg_rgb, bg_std = sample_local_background_rgb(arr, (x, y, w, h), ring=3)
        patch = arr[y0:y1, x0:x1]

        if bg_std <= 14.0:
            # Tier 1: Solid background -> fill directly with median background color
            arr[y0:y1, x0:x1] = bg_rgb
        else:
            # Tier 2: Textured/bordered background -> mask only stroke foreground pixels
            # so container borders and capsule rounded corners remain completely intact
            dists = np.linalg.norm(patch - bg_rgb, axis=-1)
            max_dist = float(np.max(dists))
            if max_dist >= 18.0:
                stroke_mask = dists >= max(22.0, max_dist * 0.28)
                dilated = np.asarray(binary_dilation(stroke_mask, iterations=2), dtype=bool)
                # Estimate interior background from non-stroke pixels inside the box
                non_stroke = patch[~dilated]
                fill_color = np.median(non_stroke, axis=0) if len(non_stroke) > 0 else bg_rgb
                patch[dilated] = fill_color
                arr[y0:y1, x0:x1] = patch

    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def verify_background_cleanliness(
    cleaned_image_path: Path | str,
    original_char_count: int,
    ocr_adapter: AppleVisionOCRAdapter,
) -> float:
    if original_char_count <= 0:
        return 0.0
    remaining_boxes = ocr_adapter.recognize(cleaned_image_path, clean=False)
    remaining_chars = sum(len(b.text.strip()) for b in remaining_boxes)
    return remaining_chars / original_char_count
