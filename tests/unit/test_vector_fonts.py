from pptkit.vector.fonts import clean_font_name, resolve_font


def test_clean_subset_font_name_strips_prefix_and_maps_family() -> None:
    # 1. Subset prefix stripping
    family, bold, italic = clean_font_name("ABCDEF+PingFangSC-Semibold")
    assert family == "PingFang SC"
    assert bold is True
    assert italic is False

    # 2. Arial PostScript name mapping
    family, bold, italic = clean_font_name("XYZABC+Arial-BoldMT")
    assert family == "Arial"
    assert bold is True
    assert italic is False

    family, bold, italic = clean_font_name("ArialMT")
    assert family == "Arial"
    assert bold is False
    assert italic is False

    # 3. Helvetica and Italic
    family, bold, italic = clean_font_name("Helvetica-BoldOblique")
    assert family == "Helvetica"
    assert bold is True
    assert italic is True

    # 4. Source Han Sans
    family, bold, italic = clean_font_name("SourceHanSansSC-Regular")
    assert family == "Source Han Sans SC"
    assert bold is False
    assert italic is False

    # 5. Microsoft YaHei
    family, bold, italic = clean_font_name("MicrosoftYaHei-Bold")
    assert family == "Microsoft YaHei"
    assert bold is True
    assert italic is False


def test_resolve_font_with_flags_and_missing_detection() -> None:
    # System font should be found on macOS
    res = resolve_font("ABCDEF+PingFangSC-Medium", flags=0)
    assert res.family == "PingFang SC"
    assert not res.is_missing

    # Non-existent font should flag is_missing and provide fallback
    res_missing = resolve_font("NONEXISTENT+SuperFancyCustomFont-Bold", flags=0)
    assert res_missing.is_missing is True
    assert res_missing.family == "SuperFancyCustomFont"
    assert res_missing.fallback_family in ("PingFang SC", "Arial")
    assert res_missing.bold is True
