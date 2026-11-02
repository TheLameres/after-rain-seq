"""Drum-событие — единица ритмической генерации drum-машины.

В отличие от :class:`ChordEvent` (гармония: ступени, войсинг, лад),
``DrumEvent`` — ритм: абсолютная GM-нота, velocity, lane-индекс.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DrumEvent:
    """Один удар drum-машины.

    Атрибуты:
        beat: Позиция в тактах (float, 0-based).
        note: GM-номер ноты (36–51).
        velocity: Сила удара 0–127 (три уровня: ghost/normal/accent).
        lane_index: Индекс лейна 0–15.
        duration: Длительность в долях (для свинга).
    """

    beat: float
    note: int
    velocity: int
    lane_index: int
    duration: float
