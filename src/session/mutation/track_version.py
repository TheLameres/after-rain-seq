"""Снимки версий дорожки для линейной истории (spec «ручная мутация», §6).

Связанные DTO (исключение из правила «один класс — один файл»): версия —
полный снимок состояния мутации дорожки; два вида — мелодический и drum.

Мелодическая версия хранит снимки тех механизмов, которые есть у дорожки
(один механизм на профиль); отсутствующие механизмы — ``None``. Drum-версия —
паттерны всех 16 лейнов.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MelodicVersion:
    """Снимок мелодической дорожки: ступени, pulses, параметры дрейфа."""

    degrees: tuple[int, ...] | None = None
    """NoteDrift.snapshot() — текущие ступени; None, если механизм не NoteDrift."""

    pulses: int | None = None
    """FloatingEuclidean.snapshot() — текущие pulses; None, если механизм не евклидов."""

    params: tuple[tuple[str, float], ...] | None = None
    """ParamDrift.snapshot() — текущие значения параметров; None, если механизм не ParamDrift."""


@dataclass(frozen=True)
class DrumVersion:
    """Снимок drum-дорожки: паттерны всех лейнов (0/1/2)."""

    lanes: tuple[tuple[int, ...], ...]
    """Кортеж паттернов лейнов в порядке индексов (16 лейнов)."""
