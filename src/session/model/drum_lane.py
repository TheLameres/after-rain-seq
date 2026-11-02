"""Один лейн (ряд) drum-машины.

16 лейнов = 16 GM-нот 36–51. Каждый лейн — паттерн из ``steps`` шагов:
0 = тишина, 1 = обычный, 2 = акцент.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class DrumLane:
    """Один ряд drum-сетки.

    Атрибуты:
        note: GM-номер ноты (36–51).
        name: Человекочитаемое имя (``"Kick"``, ``"Snare"``, …).
        pattern: Список шагов: 0 = off, 1 = on, 2 = accent.
            Длина по умолчанию 16, расширяется автоматически.
        muted: При ``True`` лейн не звучит.
    """

    note: int
    name: str
    pattern: list[int] = field(default_factory=lambda: [0] * 16)
    muted: bool = False

    def ensure_length(self, steps: int) -> None:
        """Расширить паттерн до steps элементов (если короче).

        Аргументы:
            steps: Требуемая длина.
        """
        while len(self.pattern) < steps:
            self.pattern.append(0)
