import math


def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    cleaned = hex_str.strip().lstrip("#")
    if len(cleaned) != 6:
        raise ValueError(f"Invalid hex color: {hex_str}")
    return int(cleaned[0:2], 16), int(cleaned[2:4], 16), int(cleaned[4:6], 16)


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = (max(0, min(255, int(c))) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _srgb_to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    def linearize(c: int) -> float:
        v = c / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = linearize(rgb[0]), linearize(rgb[1]), linearize(rgb[2])

    # sRGB to XYZ (D65)
    x = (r * 0.4124564 + g * 0.3575761 + b * 0.1804375) / 0.95047
    y = (r * 0.2126729 + g * 0.7151522 + b * 0.0721750) / 1.00000
    z = (r * 0.0193339 + g * 0.1191920 + b * 0.9503041) / 1.08883

    def f(t: float) -> float:
        delta = 6.0 / 29.0
        return t ** (1.0 / 3.0) if t > delta**3 else t / (3.0 * delta**2) + 4.0 / 29.0

    fx, fy, fz = f(x), f(y), f(z)
    l_val = 116.0 * fy - 16.0
    a_val = 500.0 * (fx - fy)
    b_val = 200.0 * (fy - fz)
    return l_val, a_val, b_val


def compute_delta_e(hex_a: str, hex_b: str) -> float:
    lab_a = _srgb_to_lab(hex_to_rgb(hex_a))
    lab_b = _srgb_to_lab(hex_to_rgb(hex_b))
    return math.sqrt(
        (lab_a[0] - lab_b[0]) ** 2 + (lab_a[1] - lab_b[1]) ** 2 + (lab_a[2] - lab_b[2]) ** 2
    )
