"""Цвета дорожек — из палитры устройства, а не из ручных RGB (§4.8).

Пэды Push 2 адресуются *индексом палитры* 0..127, а не RGB-тройкой:
раньше здесь лежали 12 констант, сконвертированных в BGR565, и такой
цвет в принципе не мог подсветить пэд. Теперь слот дорожки — это позиция
в ``TRACK_PAD_INDICES``, из которой выводятся обе формы цвета:

- :func:`pad_index` — индекс палитры для LED;
- :func:`track_color` — BGR565 для полоски на дисплее.
"""

from __future__ import annotations

from src.devices.push2.palette import TRACK_PAD_INDICES, bgr565

__all__ = ["TRACK_COLOR_SLOTS", "pad_index", "track_color"]

TRACK_COLOR_SLOTS: int = len(TRACK_PAD_INDICES)
"""Сколько дорожек получают собственный различимый цвет."""


def pad_index(slot: int) -> int:
    """Индекс палитры Push 2 (0..127) для слота дорожки.

    Аргументы:
        slot: Слот цвета 0..15 (``Track.color_slot``).

    Returns:
        Индекс записи палитры для отправки на пэд.
    """
    return TRACK_PAD_INDICES[slot % TRACK_COLOR_SLOTS]


def track_color(slot: int) -> int:
    """BGR565-цвет дорожки для дисплея (тот же оттенок, что у пэда).

    Аргументы:
        slot: Слот цвета 0..15 (``Track.color_slot``).

    Returns:
        Цвет в BGR565 — формат фреймбуфера Push 2.
    """
    return bgr565(pad_index(slot))
