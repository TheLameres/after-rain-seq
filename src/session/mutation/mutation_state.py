"""Состояние мутации дорожки — немутируемый снимок."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MutationState:
    """Немутируемый снимок состояния мутации дорожки.

    Атрибуты:
        mutate: Вероятность мутации 0.0–1.0 (0 = заморожено).
        mutation_count: Изменений с последней заморозки.
        next_mutation_beat: Beat следующей мутации.
        last_mutation_beat: Beat последней мутации.
    """

    mutate: float
    mutation_count: int
    next_mutation_beat: float
    last_mutation_beat: float
