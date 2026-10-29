import re

import numpy as np
from PIL import Image

from pptkit.common.color import rgb_to_hex
from pptkit.common.units import DEFAULT_SLIDE_HEIGHT_EMU, emu_to_pt, px_to_emu
from pptkit.ir.models import TextRun, TextStyle

DEFAULT_CANDIDATE_FONTS: list[str] = [
    "PingFang SC",
    "Heiti SC",
    "Songti SC",
    "Arial",
    "Helvetica",
]


def _char_em_weight(ch: str) -> float:
    if ch in "，。：；！？、（）【】":
        return 0.85
    if ord(ch) > 127:
        return 1.0
    if ch.isspace():
        return 0.25
    if ch in "iIl|!.,:;1":
        return 0.35
    if ch.isupper():
        return 0.68
    return 0.54


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


def estimate_text_runs(
    image: Image.Image,
    bbox_px: tuple[int, int, int, int],
    text: str,
    candidate_fonts: list[str] | None = None,
    slide_height_emu: int = DEFAULT_SLIDE_HEIGHT_EMU,
) -> list[TextRun]:
    base_style = estimate_text_style(
        image=image,
        bbox_px=bbox_px,
        text=text,
        candidate_fonts=candidate_fonts,
        slide_height_emu=slide_height_emu,
    )
    if len(text) < 4:
        return [TextRun(text=text, style=base_style)]

    arr = np.asarray(image.convert("RGB"), dtype=np.float32)
    h_img, w_img, _ = arr.shape
    x, y, w, h = bbox_px
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w_img, x + w), min(h_img, y + h)
    if x1 - x0 < 12 or y1 - y0 < 6:
        return [TextRun(text=text, style=base_style)]

    bg_rgb, _ = sample_local_background_rgb(arr, bbox_px, ring=3)
    patch = arr[y0:y1, x0:x1]
    dists = np.linalg.norm(patch - bg_rgb, axis=-1)
    if dists.size == 0 or float(np.max(dists)) < 25.0:
        return [TextRun(text=text, style=base_style)]

    thresh = float(np.percentile(dists, 82.0))
    stroke_mask = dists >= max(30.0, thresh * 0.75)
    ink_cols = np.where(np.any(stroke_mask, axis=0))[0]
    if len(ink_cols) < 10:
        return [TextRun(text=text, style=base_style)]

    ix0, ix1 = int(ink_cols.min()), int(ink_cols.max()) + 1
    iw = max(1, ix1 - ix0)
    ems = [_char_em_weight(ch) for ch in text]
    tot_em = sum(ems)
    cur = 0.0
    char_colors: list[np.ndarray] = []

    for ch, em in zip(text, ems, strict=True):
        cx0 = ix0 + int((cur / tot_em) * iw)
        cur += em
        cx1 = ix0 + max(cx0 - ix0 + 1, int((cur / tot_em) * iw))
        if ch.isspace() or ch in "，。：；！？、|~-（）【】":
            continue
        sub_pts = patch[:, cx0:cx1][stroke_mask[:, cx0:cx1]]
        if len(sub_pts) >= 5:
            char_colors.append(np.median(sub_pts, axis=0))

    if len(char_colors) < 4:
        return [TextRun(text=text, style=base_style)]

    cc = np.array(char_colors, dtype=np.float32)
    c1 = np.percentile(cc, 15, axis=0)
    c2 = np.percentile(cc, 85, axis=0)
    for _ in range(10):
        d1 = np.linalg.norm(cc - c1, axis=-1)
        d2 = np.linalg.norm(cc - c2, axis=-1)
        m1 = d1 <= d2
        if not np.any(m1) or not np.any(~m1):
            break
        c1 = np.median(cc[m1], axis=0)
        c2 = np.median(cc[~m1], axis=0)

    cdist = float(np.linalg.norm(c1 - c2))
    chroma_diff = float(
        max(
            abs((c1[0] - c1[2]) - (c2[0] - c2[2])),
            abs((c1[0] - c1[1]) - (c2[0] - c2[1])),
            abs((c1[1] - c1[2]) - (c2[1] - c2[2])),
        )
    )
    if cdist < 80.0 or chroma_diff < 45.0:
        return [TextRun(text=text, style=base_style)]

    hex1 = rgb_to_hex((int(round(c1[0])), int(round(c1[1])), int(round(c1[2]))))
    hex2 = rgb_to_hex((int(round(c2[0])), int(round(c2[1])), int(round(c2[2]))))
    sat1 = float(np.max(c1) - np.min(c1))
    sat2 = float(np.max(c2) - np.min(c2))
    neutral_hex = hex1 if sat1 <= sat2 else hex2

    cur = 0.0
    runs_raw: list[tuple[str, str]] = []
    for idx_ch, (ch, em) in enumerate(zip(text, ems, strict=True)):
        cx0 = ix0 + int((cur / tot_em) * iw)
        cur += em
        cx1 = ix0 + max(cx0 - ix0 + 1, int((cur / tot_em) * iw))
        if ch in "，。；！？、":
            # Full-width punctuation uses the neutral body text color
            col_hex = neutral_hex
        elif ch == "：" and idx_ch > 0 and runs_raw:
            col_hex = runs_raw[-1][1]
        elif ch.isspace():
            col_hex = runs_raw[-1][1] if runs_raw else neutral_hex
        else:
            sub_pts = patch[:, cx0:cx1][stroke_mask[:, cx0:cx1]]
            if len(sub_pts) == 0:
                col_hex = runs_raw[-1][1] if runs_raw else neutral_hex
            else:
                med_p = np.median(sub_pts, axis=0)
                col_hex = (
                    hex1
                    if float(np.linalg.norm(med_p - c1)) <= float(np.linalg.norm(med_p - c2))
                    else hex2
                )

        if runs_raw and runs_raw[-1][1] == col_hex:
            runs_raw[-1] = (runs_raw[-1][0] + ch, col_hex)
        else:
            runs_raw.append((ch, col_hex))

    return [
        TextRun(
            text=seg_text,
            style=base_style.model_copy(update={"color_hex": seg_hex}),
        )
        for seg_text, seg_hex in runs_raw
    ]


_LEADING_PUNCT_RE = re.compile(r"^[|•■▪·]\s*")
_METRIC_COMMA_RE = re.compile(r"([\u4e00-\u9fa5\w]+)[，,](\d+\+?[项篇份册条次万])")


def clean_title_punctuation(text: str) -> str:
    """Clean isolated decorative punctuation from heading texts (F30)."""
    cleaned = _LEADING_PUNCT_RE.sub("", text).strip()

    # Fix metric comma typos like "专利，250+项" -> "专利250+项"
    cleaned = _METRIC_COMMA_RE.sub(r"\1\2", cleaned)

    # For short titles/names (not full sentences), strip trailing isolated dot/period
    if len(cleaned) < 25 and cleaned.endswith("。"):
        cleaned = cleaned[:-1].strip()

    return cleaned
