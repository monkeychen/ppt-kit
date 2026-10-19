from pathlib import Path

from pptkit.common.units import (
    DEFAULT_SLIDE_WIDTH_EMU,
    emu_to_inches,
    emu_to_pt,
    emu_to_px,
    inches_to_emu,
    page_size_to_emu,
    pt_to_emu,
    px_to_emu,
)


def test_px_pt_inch_to_emu_roundtrip() -> None:
    # 1 inch = 914400 EMU
    assert inches_to_emu(1.0) == 914400
    assert emu_to_inches(914400) == 1.0

    # 1 pt = 12700 EMU
    assert pt_to_emu(1.0) == 12700
    assert pt_to_emu(72.0) == 914400
    assert emu_to_pt(12700) == 1.0

    # Pixel to EMU relative to slide width
    # 1920 px maps to 12192000 EMU
    assert px_to_emu(1920, total_px=1920, total_emu=12192000) == 12192000
    assert px_to_emu(960, total_px=1920, total_emu=12192000) == 6096000
    assert emu_to_px(6096000, total_px=1920, total_emu=12192000) == 960


def test_aspect_ratio_preservation_in_emu() -> None:
    # 16:9 standard -> 12192000 x 6858000 EMU
    w16_9, h16_9 = page_size_to_emu(1920, 1080)
    assert w16_9 == DEFAULT_SLIDE_WIDTH_EMU == 12192000
    assert h16_9 == 6858000

    # 4:3 standard -> 12192000 x 9144000 EMU
    w4_3, h4_3 = page_size_to_emu(1600, 1200)
    assert w4_3 == 12192000
    assert h4_3 == 9144000

    # Custom ratio preserves aspect ratio accurately
    w_custom, h_custom = page_size_to_emu(1000, 500)
    assert w_custom == 12192000
    assert h_custom == 6096000


def test_no_unit_constants_outside_units_module() -> None:
    src_root = Path(__file__).resolve().parents[2] / "src" / "pptkit"
    forbidden = ("914400", "12700")
    offenders: list[str] = []
    for py_file in src_root.rglob("*.py"):
        if py_file.name == "units.py":
            continue
        content = py_file.read_text(encoding="utf-8")
        for token in forbidden:
            if token in content:
                offenders.append(f"{py_file.relative_to(src_root)} contains {token}")
    assert not offenders, f"Unit conversion constants found outside units.py: {offenders}"
