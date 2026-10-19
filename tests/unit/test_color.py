from pptkit.common.color import compute_delta_e, hex_to_rgb, rgb_to_hex


def test_delta_e_identical_and_complementary_colors() -> None:
    assert hex_to_rgb("#FF8000") == (255, 128, 0)
    assert rgb_to_hex((255, 128, 0)) == "#FF8000"

    # Identical colors -> 0.0
    assert compute_delta_e("#1A2B3C", "#1A2B3C") == 0.0

    # Near-identical colors -> small Delta E (< 2.0)
    near_de = compute_delta_e("#204060", "#214161")
    assert 0.0 < near_de < 2.0

    # Black vs White -> ~100
    bw_de = compute_delta_e("#000000", "#FFFFFF")
    assert 99.0 <= bw_de <= 101.0
