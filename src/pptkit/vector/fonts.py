import functools
import re
from dataclasses import dataclass
from pathlib import Path

STANDARD_MAP: dict[str, str] = {
    "ArialMT": "Arial",
    "Arial-BoldMT": "Arial",
    "Arial-ItalicMT": "Arial",
    "Arial-BoldItalicMT": "Arial",
    "TimesNewRomanPSMT": "Times New Roman",
    "TimesNewRomanPS-BoldMT": "Times New Roman",
    "TimesNewRomanPS-ItalicMT": "Times New Roman",
    "TimesNewRomanPS-BoldItalicMT": "Times New Roman",
    "CourierNewPSMT": "Courier New",
    "CourierNewPS-BoldMT": "Courier New",
}

FAMILY_PREFIX_MAP: list[tuple[str, str]] = [
    ("PingFangSC-", "PingFang SC"),
    ("PingFangTC-", "PingFang TC"),
    ("PingFangHK-", "PingFang HK"),
    ("SourceHanSansSC-", "Source Han Sans SC"),
    ("SourceHanSansCN-", "Source Han Sans SC"),
    ("SourceHanSerifSC-", "Source Han Serif SC"),
    ("SourceHanSerifCN-", "Source Han Serif SC"),
    ("MicrosoftYaHei-", "Microsoft YaHei"),
    ("MicrosoftYaHei", "Microsoft YaHei"),
    ("SimSun", "SimSun"),
    ("SimHei", "SimHei"),
    ("KaiTi", "KaiTi"),
    ("FangSong", "FangSong"),
    ("Helvetica-", "Helvetica"),
    ("HelveticaNeue-", "Helvetica Neue"),
    ("Calibri-", "Calibri"),
    ("Calibri", "Calibri"),
    ("Cambria-", "Cambria"),
    ("Cambria", "Cambria"),
]


@dataclass
class ResolvedFont:
    family: str
    bold: bool
    italic: bool
    is_missing: bool
    fallback_family: str


def clean_font_name(raw_name: str) -> tuple[str, bool, bool]:
    # 1. Strip subset prefix (e.g. "ABCDEF+Arial-BoldMT" -> "Arial-BoldMT")
    name = re.sub(r"^[A-Z]+\+", "", raw_name)

    # 2. Check for bold / italic keywords in the name
    bold = False
    italic = False
    lower = name.lower()
    if any(k in lower for k in ("bold", "heavy", "black", "semibold", "demibold")):
        bold = True
    if any(k in lower for k in ("italic", "oblique")):
        italic = True

    # 3. Direct lookup in standard map
    if name in STANDARD_MAP:
        return STANDARD_MAP[name], bold, italic

    # 4. Check prefix map
    for prefix, target_family in FAMILY_PREFIX_MAP:
        if name.startswith(prefix) or name == prefix.rstrip("-"):
            return target_family, bold, italic

    # 5. Generic hyphen split: e.g. "MyFont-Bold" -> "MyFont"
    if "-" in name:
        base, suffix = name.split("-", 1)
        if any(
            k in suffix.lower()
            for k in (
                "regular",
                "bold",
                "italic",
                "medium",
                "light",
                "thin",
                "heavy",
                "black",
                "semibold",
            )
        ):
            return base, bold, italic

    return name, bold, italic


@functools.lru_cache(maxsize=1)
def get_installed_fonts() -> set[str]:
    # Common system font families known on macOS
    installed = {
        "PingFang SC",
        "PingFang TC",
        "PingFang HK",
        "Arial",
        "Helvetica",
        "Helvetica Neue",
        "Times New Roman",
        "Courier New",
        "Georgia",
        "Verdana",
        "Tahoma",
        "Trebuchet MS",
        "Comic Sans MS",
        "Impact",
        "Palatino",
        "Songti SC",
        "Heiti SC",
        "Kaiti SC",
        "Yuanti SC",
        "Apple Color Emoji",
        "Apple SD Gothic Neo",
        "Hiragino Sans GB",
        "Microsoft YaHei",
        "SimSun",
        "SimHei",
        "KaiTi",
        "FangSong",
    }
    font_dirs = [
        Path("/System/Library/Fonts"),
        Path("/Library/Fonts"),
        Path.home() / "Library/Fonts",
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path.home() / ".fonts",
        Path.home() / ".local/share/fonts",
        Path("C:/Windows/Fonts"),
    ]
    for d in font_dirs:
        if d.exists():
            for f in d.rglob("*"):
                if f.suffix.lower() in (".ttf", ".otf", ".ttc"):
                    stem = f.stem
                    installed.add(stem)
                    if "-" in stem:
                        installed.add(stem.split("-", 1)[0])
    return installed


def resolve_font(raw_name: str, flags: int = 0) -> ResolvedFont:
    family, bold, italic = clean_font_name(raw_name)
    if flags & (1 << 6):
        italic = True
    if flags & (1 << 18) or flags & (1 << 4):
        bold = True

    installed = get_installed_fonts()
    is_missing = family not in installed

    has_cjk_hints = any(
        k in family.lower()
        for k in ("sc", "tc", "cn", "song", "hei", "kai", "fang", "yahei", "ming")
    )
    fallback = "PingFang SC" if has_cjk_hints else "Arial"

    return ResolvedFont(
        family=family,
        bold=bold,
        italic=italic,
        is_missing=is_missing,
        fallback_family=fallback,
    )
