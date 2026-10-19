EMU_PER_INCH: int = 914400
EMU_PER_PT: int = 12700
DEFAULT_SLIDE_WIDTH_EMU: int = 12192000
DEFAULT_SLIDE_HEIGHT_EMU: int = 6858000


def inches_to_emu(inches: float) -> int:
    return round(inches * EMU_PER_INCH)


def emu_to_inches(emu: int) -> float:
    return emu / EMU_PER_INCH


def pt_to_emu(pt: float) -> int:
    return round(pt * EMU_PER_PT)


def emu_to_pt(emu: int) -> float:
    return emu / EMU_PER_PT


def px_to_emu(px: float, total_px: int, total_emu: int = DEFAULT_SLIDE_WIDTH_EMU) -> int:
    if total_px <= 0:
        raise ValueError(f"total_px must be positive, got {total_px}")
    return round(px * total_emu / total_px)


def emu_to_px(emu: int, total_px: int, total_emu: int = DEFAULT_SLIDE_WIDTH_EMU) -> int:
    if total_emu <= 0:
        raise ValueError(f"total_emu must be positive, got {total_emu}")
    return round(emu * total_px / total_emu)


def page_size_to_emu(
    width_px: float, height_px: float, base_width_emu: int = DEFAULT_SLIDE_WIDTH_EMU
) -> tuple[int, int]:
    if width_px <= 0 or height_px <= 0:
        raise ValueError(f"Page dimensions must be positive, got {width_px}x{height_px}")
    height_emu = round(base_width_emu * height_px / width_px)
    return base_width_emu, height_emu
