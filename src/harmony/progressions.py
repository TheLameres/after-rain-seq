"""Популярные прогрессии (пресеты) для выбора на Push 2 (GEN, E6).

Ступени — числа ``0..13`` (римские ``I..XIV``, см. :mod:`harmony.degree_names`).
Пресет целиком заполняет ``degrees`` дорожки; применяется через B2 (на границе
ступени), как и любая правка прогрессии.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from src.harmony.degree_names import format_degrees


@dataclass(frozen=True)
class Progression:
    """Именованная прогрессия в ступенях."""

    name: str
    degrees: tuple[int, ...]

    @property
    def roman(self) -> str:
        """Запись римскими цифрами: ``I V VI IV``."""
        return format_degrees(self.degrees)


PROGRESSIONS: tuple[Progression, ...] = (
    Progression("Pop", (0, 4, 5, 3)),  # I-V-vi-IV
    Progression("Classic", (0, 3, 4, 0)),  # I-IV-V-I
    Progression("Sad", (5, 3, 0, 4)),  # vi-IV-I-V
    Progression("Jazz", (1, 4, 0)),  # ii-V-I
    Progression("Doo-wop", (0, 5, 3, 4)),  # I-vi-IV-V
    Progression("Andalusian", (0, 6, 5, 4)),  # i-VII-VI-V
    Progression("Canon", (0, 4, 5, 2, 3, 0, 3, 4)),  # I-V-vi-iii-IV-I-IV-V
)


def index_of(degrees: Sequence[int]) -> int | None:
    """Индекс пресета с такой прогрессией или ``None`` (своя прогрессия)."""
    target = tuple(degrees)
    for i, preset in enumerate(PROGRESSIONS):
        if preset.degrees == target:
            return i
    return None


def name_of(degrees: Sequence[int]) -> str:
    """Имя пресета для прогрессии или пустая строка, если это своя."""
    idx = index_of(degrees)
    return PROGRESSIONS[idx].name if idx is not None else ""


def next_progression(degrees: Sequence[int], increment: int) -> Progression:
    """Пресет на ``increment`` шагов от текущего (по кругу).

    Если текущая прогрессия не из словаря, первый шаг вперёд даёт первый
    пресет, назад — последний.
    """
    idx = index_of(degrees)
    if idx is None:
        return PROGRESSIONS[0] if increment >= 0 else PROGRESSIONS[-1]
    return PROGRESSIONS[(idx + increment) % len(PROGRESSIONS)]
