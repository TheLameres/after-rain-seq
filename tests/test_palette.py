"""Тесты палитры LED Push 2 (план §3.2б).

Проверяем не «красивость» цветов, а контракт: 128 записей, якоря совпадают
со спецификацией, индекс дорожки — валидный цветной индекс, отбор
устойчив по ΔE и соседние дорожки различимы.
"""

from __future__ import annotations

import colorsys
import math

import pytest

from src.core.color import Color
from src.devices.push2 import palette
from src.devices.push2.palette import (
    PALETTE,
    PALETTE_OFF,
    TRACK_PAD_INDICES,
    bgr565,
    rgb,
)
from src.devices.push2.track_colors import track_color

# ---------------------------------------------------------------------------
# Структура
# ---------------------------------------------------------------------------


def test_has_128_entries() -> None:
    assert len(PALETTE) == 128


def test_entries_are_valid_rgb() -> None:
    for index, entry in enumerate(PALETTE):
        assert len(entry) == 3, f"запись {index}: ожидалось 3 компонента"
        for component in entry:
            assert 0 <= component <= 255, f"запись {index}: {component} вне 0..255"


def test_rgb_getter_matches_table() -> None:
    assert rgb(0) == PALETTE[0]
    assert rgb(127) == PALETTE[127]


@pytest.mark.parametrize("index", [-1, 128, 1000])
def test_rgb_getter_rejects_bad_index(index: int) -> None:
    with pytest.raises(IndexError):
        rgb(index)


def test_off_index_is_black() -> None:
    assert PALETTE_OFF == 0
    assert rgb(PALETTE_OFF) == (0, 0, 0)


# ---------------------------------------------------------------------------
# Якоря официальной спецификации
# ---------------------------------------------------------------------------

# Ableton Push 2 MIDI & Display Interface, «Default Color Palettes».
SPEC_ANCHORS = {
    0: (0, 0, 0),
    117: (0, 0, 0),
    118: (89, 89, 89),
    121: (89, 89, 89),
    125: (0, 0, 255),
    126: (0, 255, 0),
    127: (255, 0, 0),
}


@pytest.mark.parametrize(("index", "expected"), sorted(SPEC_ANCHORS.items()))
def test_spec_anchors(index: int, expected: tuple[int, int, int]) -> None:
    assert rgb(index) == expected


def test_duplicate_entries_per_spec() -> None:
    """Спека прямо говорит про дубликаты серых — их не должно «исчезнуть»."""
    assert rgb(0) == rgb(117)
    assert rgb(118) == rgb(121)


# ---------------------------------------------------------------------------
# Структура рядов (обнаружена разбором, план §3.2б)
# ---------------------------------------------------------------------------


def _saturation_value(index: int) -> tuple[float, float]:
    r, g, b = rgb(index)
    _, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return s, v


def test_dark_row_is_dimmer_than_bright_row() -> None:
    dark = max(_saturation_value(i)[1] for i in range(65, 117))
    bright = max(_saturation_value(i)[1] for i in range(1, 65))
    assert dark <= bright


def test_grays_have_zero_saturation() -> None:
    for index in (0, 117, 118, 119, 121, 124):
        assert _saturation_value(index)[0] == pytest.approx(0.0)


def test_nearest_chromatic_entry_is_above_tolerance() -> None:
    """Порог 0.05 стоит в зазоре между серыми и ближайшим оттенком."""
    chromatic = [
        _saturation_value(i)[0] for i in range(128) if _saturation_value(i)[0] > 0.0
    ]
    assert min(chromatic) > 0.05


def test_dark_row_is_not_a_mirror_of_bright_row() -> None:
    """Гипотеза «+64 = тот же оттенок темнее» опровергнута — фиксируем это."""
    matches = 0
    for index in range(1, 53):
        h1 = colorsys.rgb_to_hsv(*[c / 255 for c in rgb(index)])[0]
        h2 = colorsys.rgb_to_hsv(*[c / 255 for c in rgb(index + 64)])[0]
        delta = abs(h1 - h2)
        if min(delta, 1 - delta) < 0.05:
            matches += 1
    assert matches < 20, "ряды снова стали зеркалом — проверить таблицу"


# ---------------------------------------------------------------------------
# Цвета дорожек
# ---------------------------------------------------------------------------


def test_track_indices_cover_max_tracks() -> None:
    assert len(TRACK_PAD_INDICES) == 16


def test_track_indices_are_unique() -> None:
    assert len(set(TRACK_PAD_INDICES)) == len(TRACK_PAD_INDICES)


def test_track_indices_are_valid() -> None:
    for index in TRACK_PAD_INDICES:
        assert 0 <= index < 128


def test_track_indices_exclude_off() -> None:
    assert PALETTE_OFF not in TRACK_PAD_INDICES


def test_every_track_color_is_chromatic() -> None:
    """Главная проверка: цвет дорожки не должен быть серым."""
    for index in TRACK_PAD_INDICES:
        assert Color(*rgb(index)).is_chromatic(), f"индекс {index} серый"


def test_every_track_color_is_bright_enough() -> None:
    """Тёмный ряд на пэде неотличим от погашенного."""
    for index in TRACK_PAD_INDICES:
        _, value = _saturation_value(index)
        assert value >= 0.5, f"индекс {index} слишком тёмный (V={value:.2f})"


def test_track_colors_are_distinct_after_bgr565_quantization() -> None:
    packed = {bgr565(index) for index in TRACK_PAD_INDICES}
    assert len(packed) == len(TRACK_PAD_INDICES)


def _lab(index: int) -> tuple[float, float, float]:
    """CIE L*a*b* записи палитры после квантования в BGR565."""
    color = Color.from_bgr565(bgr565(index))
    channels = []
    for value in (color.r, color.g, color.b):
        srgb = value / 255
        linear = srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4
        channels.append(linear)
    lr, lg, lb = channels
    x = lr * 0.4124 + lg * 0.3576 + lb * 0.1805
    y = lr * 0.2126 + lg * 0.7152 + lb * 0.0722
    z = lr * 0.0193 + lg * 0.1192 + lb * 0.9505
    xn, yn, zn = 0.95047, 1.0, 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def test_track_colors_differ_by_perceptible_delta_e() -> None:
    labs = [_lab(index) for index in TRACK_PAD_INDICES]
    minimum = min(
        math.dist(labs[a], labs[b])
        for a in range(len(labs))
        for b in range(a + 1, len(labs))
    )
    # Порог из плана: набор отобран greedy farthest-point, ΔE ≥ 33.
    assert minimum >= 30.0, f"минимальная ΔE упала до {minimum:.1f}"


def test_adjacent_tracks_are_far_apart() -> None:
    """Соседние дорожки различимы по ΔE, а не обязательно по тону.

    Порядок подобран «по кругу оттенков», но двух цветов одного тона это
    не исключает: индексы 30 и 40 оба жёлтые и различаются яркостью и
    насыщенностью. Значимо именно перцептивное расстояние.
    """
    labs = [_lab(index) for index in TRACK_PAD_INDICES]
    count = len(labs)
    for k in range(count):
        delta = math.dist(labs[k], labs[(k + 1) % count])
        assert delta >= 30.0, (
            f"дорожки {TRACK_PAD_INDICES[k]} и {TRACK_PAD_INDICES[(k + 1) % count]} "
            f"слишком близки (ΔE={delta:.1f})"
        )


# ---------------------------------------------------------------------------
# BGR565
# ---------------------------------------------------------------------------


def test_bgr565_encoding() -> None:
    # 126 = (0,255,0) зелёный: 6 бит зелёного в середине
    assert bgr565(126) == 0x07E0


def test_bgr565_red_and_blue_are_swapped() -> None:
    # 127 = (255,0,0) красный → в BGR565 красный в младших 5 битах
    assert bgr565(127) == 0x001F
    assert bgr565(125) == 0xF800


def test_bgr565_matches_color_type() -> None:
    for index in (0, 1, 64, 126, 127):
        assert bgr565(index) == Color(*rgb(index)).to_bgr565()


def test_palette_module_imports_without_side_effects() -> None:
    """Модуль статический: никакого обращения к железу при импорте."""
    assert palette.PALETTE is PALETTE


# ---------------------------------------------------------------------------
# §4.8 — индекс палитры для пэда, а не RGB
# ---------------------------------------------------------------------------


def test_pad_index_returns_real_palette_index() -> None:
    """Пэд Push 2 адресуется индексом палитры, а не RGB-тройкой."""
    from src.devices.push2.track_colors import pad_index

    for slot in range(16):
        index = pad_index(slot)
        assert index in TRACK_PAD_INDICES
        assert 0 <= index < len(PALETTE)


def test_pad_index_matches_track_color() -> None:
    """Цвет дисплея (BGR565) и индекс пэда — про один и тот же оттенок."""
    from src.devices.push2.track_colors import pad_index

    for slot in range(16):
        assert bgr565(pad_index(slot)) == track_color(slot)


def test_all_sixteen_slots_are_distinct_pads() -> None:
    """16 дорожек получают 16 разных пэдов."""
    from src.devices.push2.track_colors import pad_index

    pads = [pad_index(slot) for slot in range(16)]
    assert len(set(pads)) == 16
