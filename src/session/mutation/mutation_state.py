"""Состояние мутации дорожки — немутируемый снимок."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MutationState:
    """Немутируемый снимок состояния мутации дорожки.

    Атрибуты:
        mutation_count: Счётчик применённых изменений паттерна.
        last_mutation_beat: Beat последней мутации.
    """

    mutation_count: int
    last_mutation_beat: float
