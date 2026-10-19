import numpy as np
from PIL import Image

from pptkit.common.color import rgb_to_hex
from pptkit.common.units import DEFAULT_SLIDE_HEIGHT_EMU, emu_to_pt, px_to_emu
from pptkit.ir.models import TextStyle

DEFAULT_CANDIDATE_FONTS: list[str] = [
    "PingFang SC",
    "Heiti SC",
    "Songti SC",
    "Arial",
    "Helvetica",
]


def _text_em_count(text: str) -> float:
    ems = 0.0
    for ch in text:
        if ord(ch) > 127:
            ems += 1.0
        elif ch.isspace():
            ems += 0.28
        elif ch in "iIl|!.,:;1":
            ems += 0.38
        else:
            ems += 0.56
    return max(ems, 0.5)


def sample_local_background_rgb(
    arr: np.ndarray, bbox_px: tuple[int, int, int, int], ring: int = 3
) -> tuple[np.ndarray, float]:
    h_img, w_img, _ = arr.shape
    x, y, w, h = bbox_px
    x0, y0 = max(0, x - ring), max(0, y - ring)
    x1, y1 = min(w_img, x + w + ring), min(h_img, y + h + ring)

    ix0, iy0 = max(0, x), max(0, y)
    ix1, iy1 = min(w_img, x + w), min(h_img, y + h)

    mask = np.ones((y1 - y0, x1 - x0), dtype=bool)
    mask[iy0 - y0 : iy1 - y0, ix0 - x0 : ix1 - x0] = False

    patch = arr[y0:y1, x0:x1]
    border_pixels = patch[mask]
    if len(border_pixels) == 0:
        border_pixels = patch.reshape(-1, 3)

    median_rgb = np.median(border_pixels, axis=0)
    std_val = float(np.mean(np.std(border_pixels.astype(np.float32), axis=0)))

    inner_crop = arr[iy0:iy1, ix0:ix1].reshape(-1, 3)
    if len(inner_crop) > 0 and std_val > 22.0:
        inner_med = np.median(inner_crop, axis=0)
        if float(np.linalg.norm(median_rgb - inner_med)) > 25.0:
            median_rgb = inner_med

    return median_rgb, std_val


def estimate_text_style(
    image: Image.Image,
    bbox_px: tuple[int, int, int, int],
    text: str,
    candidate_fonts: list[str] | None = None,
    slide_height_emu: int = DEFAULT_SLIDE_HEIGHT_EMU,
) -> TextStyle:
    fonts = candidate_fonts or DEFAULT_CANDIDATE_FONTS
    rgb_img = image.convert("RGB")
    arr = np.asarray(rgb_img, dtype=np.float32)
    h_img, w_img, _ = arr.shape

    x, y, w, h = bbox_px
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w_img, x + w), min(h_img, y + h)

    crop = arr[y0:y1, x0:x1].reshape(-1, 3)
    bg_rgb, _ = sample_local_background_rgb(arr, bbox_px, ring=3)

    if len(crop) == 0:
        fg_hex = "#000000"
        is_bold = False
    else:
        dists = np.linalg.norm(crop - bg_rgb, axis=-1)
        max_dist = float(np.max(dists))
        if max_dist < 10.0:
            fg_rgb = crop[0]
            is_bold = False
        else:
            # Select top 18% most contrasted stroke core pixels to avoid anti-aliased edge blending
            thresh = float(np.percentile(dists, 82.0))
            stroke_core = crop[dists >= thresh]
            fg_rgb = np.median(stroke_core, axis=0)

            stroke_mask = dists >= (max_dist * 0.45)
            stroke_density = float(np.mean(stroke_mask))
            is_bold = stroke_density >= 0.24 or (h / max(h_img, 1)) >= 0.042

        fg_hex = rgb_to_hex((int(round(fg_rgb[0])), int(round(fg_rgb[1])), int(round(fg_rgb[2]))))

    # Font size estimation from bbox pixel height & width converted via units.py
    box_h_emu = px_to_emu(h, h_img, slide_height_emu)
    box_w_emu = px_to_emu(w, h_img, slide_height_emu)
    box_h_pt = emu_to_pt(box_h_emu)
    box_w_pt = emu_to_pt(box_w_emu)
    ems = _text_em_count(text)
    if ems >= 3.5:
        pt_h = box_h_pt * 0.88
        pt_w = box_w_pt / ems
        raw_pt = min(pt_h * 1.05, pt_w * 0.98)
    else:
        raw_pt = box_h_pt * 0.82
    est_pt = max(8.0, round(raw_pt * 2.0) / 2.0)

    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in text)
    if has_cjk:
        chosen_font = fonts[0]
    else:
        ascii_fonts = [f for f in fonts if f in ("Arial", "Helvetica")]
        chosen_font = ascii_fonts[0] if ascii_fonts else fonts[0]

    return TextStyle(
        font_family=chosen_font,
        font_size_pt=est_pt,
        color_hex=fg_hex,
        bold=is_bold,
    )
