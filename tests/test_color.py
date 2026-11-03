"""Тесты ``core.Color`` — контракт значения цвета (план §3.2а)."""

from __future__ import annotations

import dataclasses

import pytest

from src.core.color import ACHROMATIC_TOLERANCE, Color

# ---------------------------------------------------------------------------
# Конструктор и валидация
# ---------------------------------------------------------------------------


def test_holds_components() -> None:
    c = Color(10, 20, 30)
    assert (c.r, c.g, c.b) == (10, 20, 30)


def test_is_frozen() -> None:
    c = Color(1, 2, 3)
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.r = 4  # type: ignore[misc]


def test_equality_by_value() -> None:
    assert Color(1, 2, 3) == Color(1, 2, 3)
    assert Color(1, 2, 3) != Color(1, 2, 4)


def test_hashable() -> None:
    assert len({Color(1, 2, 3), Color(1, 2, 3)}) == 1


@pytest.mark.parametrize("value", [-1, 256, 1000])
def test_rejects_out_of_range(value: int) -> None:
    with pytest.raises(ValueError):
        Color(value, 0, 0)


@pytest.mark.parametrize("component", ["r", "g", "b"])
def test_rejects_bool(component: str) -> None:
    kwargs = {"r": 0, "g": 0, "b": 0}
    kwargs[component] = True
    with pytest.raises(TypeError):
        Color(**kwargs)


def test_rejects_float() -> None:
    with pytest.raises(TypeError):
        Color(1.5, 0, 0)  # type: ignore[arg-type]


def test_accepts_bounds() -> None:
    assert Color(0, 0, 0) == Color(0, 0, 0)
    assert Color(255, 255, 255) == Color(255, 255, 255)


# ---------------------------------------------------------------------------
# Хроматичность
# ---------------------------------------------------------------------------


def test_chroma() -> None:
    assert Color(255, 0, 0).chroma == 255
    assert Color(100, 100, 100).chroma == 0


def test_saturation_of_red() -> None:
    assert Color(255, 0, 0).saturation == pytest.approx(1.0)


def test_saturation_of_black_is_zero() -> None:
    assert Color(0, 0, 0).saturation == 0.0


def test_saturation_of_white_is_zero() -> None:
    assert Color(255, 255, 255).saturation == 0.0


def test_saturation_of_gray() -> None:
    assert Color(128, 128, 128).saturation == 0.0


@pytest.mark.parametrize(
    "color",
    [Color(0, 0, 0), Color(255, 255, 255), Color(89, 89, 89), Color(20, 20, 20)],
)
def test_grays_are_achromatic(color: Color) -> None:
    assert color.is_achromatic()
    assert not color.is_chromatic()


@pytest.mark.parametrize(
    "color",
    [Color(255, 0, 0), Color(0, 128, 0), Color(0, 0, 64), Color(1, 2, 3)],
)
def test_tinted_are_chromatic(color: Color) -> None:
    assert color.is_chromatic()
    assert not color.is_achromatic()


def test_tolerance_boundary() -> None:
    # saturation = 1/255 ≈ 0.0039 — оттенок есть, но он на грани
    faint = Color(255, 254, 254)
    assert faint.saturation == pytest.approx(1 / 255)
    # при нулевом допуске любой оттенок уже цветной
    assert faint.is_chromatic(0.0) is True
    # при допуске выше фактической насыщенности — уже серый
    assert faint.is_achromatic(0.01) is True


def test_default_tolerance_is_documented_constant() -> None:
    assert 0.02 <= ACHROMATIC_TOLERANCE <= 0.08


# ---------------------------------------------------------------------------
# Яркость
# ---------------------------------------------------------------------------


def test_luminance_black_is_zero() -> None:
    assert Color(0, 0, 0).relative_luminance == pytest.approx(0.0)


def test_luminance_white_is_one() -> None:
    assert Color(255, 255, 255).relative_luminance == pytest.approx(1.0, abs=1e-6)


def test_luminance_green_dominates_red() -> None:
    assert Color(0, 255, 0).relative_luminance > Color(255, 0, 0).relative_luminance


def test_luminance_is_ordered_for_gray_ramp() -> None:
    ramp = [Color(v, v, v) for v in (0, 32, 64, 128, 192, 255)]
    values = [c.relative_luminance for c in ramp]
    assert values == sorted(values)


# ---------------------------------------------------------------------------
# Упаковка RGB565 / BGR565
# ---------------------------------------------------------------------------


def test_rgb565_pure_red() -> None:
    assert Color(255, 0, 0).to_rgb565() == 0xF800


def test_rgb565_pure_green() -> None:
    assert Color(0, 255, 0).to_rgb565() == 0x07E0


def test_rgb565_pure_blue() -> None:
    assert Color(0, 0, 255).to_rgb565() == 0x001F


def test_rgb565_black() -> None:
    assert Color(0, 0, 0).to_rgb565() == 0


def test_bgr565_pure_red() -> None:
    assert Color(255, 0, 0).to_bgr565() == 0x001F


def test_bgr565_pure_blue() -> None:
    assert Color(0, 0, 255).to_bgr565() == 0xF800


def test_bgr565_swaps_channels_of_rgb565() -> None:
    c = Color(200, 100, 50)
    assert c.to_bgr565() == Color(50, 100, 200).to_rgb565()


@pytest.mark.parametrize("value", [0, 0x1234, 0xF800, 0x07E0, 0x001F, 0xFFFF])
def test_rgb565_roundtrip_is_close(value: int) -> None:
    restored = Color.from_rgb565(value)
    assert restored.to_rgb565() == value


@pytest.mark.parametrize("value", [0, 0x1234, 0xF800, 0x07E0, 0x001F, 0xFFFF])
def test_bgr565_roundtrip_is_close(value: int) -> None:
    restored = Color.from_bgr565(value)
    assert restored.to_bgr565() == value


def test_bgr565_roundtrip_loss_is_at_most_seven_per_channel() -> None:
    original = Color(200, 101, 47)
    restored = Color.from_bgr565(original.to_bgr565())
    assert abs(restored.r - original.r) <= 7
    assert abs(restored.g - original.g) <= 7
    assert abs(restored.b - original.b) <= 7


@pytest.mark.parametrize("value", [-1, 0x10000])
def test_pack_rejects_out_of_range(value: int) -> None:
    with pytest.raises(ValueError):
        Color.from_rgb565(value)
    with pytest.raises(ValueError):
        Color.from_bgr565(value)


# ---------------------------------------------------------------------------
# Hex
# ---------------------------------------------------------------------------


def test_to_hex() -> None:
    assert Color(255, 0, 16).to_hex() == "#ff0010"


def test_from_hex_with_hash() -> None:
    assert Color.from_hex("#ff0010") == Color(255, 0, 16)


def test_from_hex_without_hash() -> None:
    assert Color.from_hex("ff0010") == Color(255, 0, 16)


def test_hex_roundtrip() -> None:
    c = Color(12, 34, 56)
    assert Color.from_hex(c.to_hex()) == c


@pytest.mark.parametrize("bad", ["#fff", "zzzzzz", "#1234567", ""])
def test_from_hex_rejects_bad_input(bad: str) -> None:
    with pytest.raises(ValueError):
        Color.from_hex(bad)


def test_str_is_hex() -> None:
    assert str(Color(1, 2, 3)) == "#010203"
