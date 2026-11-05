"""Плавающий евклидов паттерн — механизм мутации для seq/arp/stab профилей."""

from __future__ import annotations

import logging
import random

from src.session.model.euclidean import PEuclideanCached

log = logging.getLogger(__name__)


class FloatingEuclidean:
    """Евклидов паттерн с дрейфующим количеством pulses.

    Оборачивает :class:`PEuclideanCached`. При мутации pulses меняется
    на ±1 (в пределах ``[1, steps-1]``). PEuclideanCached автоматически
    инвалидирует кеш при смене pulses.

    Использование:
        fe = FloatingEuclidean(steps=16, base_pulses=4)
        pattern = fe.pattern  # из кеша
        fe.drift(rng)         # pulses может стать 3 или 5
        pattern = fe.pattern  # пересчёт
    """

    def __init__(self, steps: int, base_pulses: int) -> None:
        if steps < 2:
            raise ValueError(f"steps должен быть >= 2, got {steps}")
        if not 1 <= base_pulses <= steps - 1:
            raise ValueError(
                f"base_pulses должен быть в [1, {steps - 1}], got {base_pulses}"
            )
        self._base_pulses: int = base_pulses
        self._euclidean: PEuclideanCached = PEuclideanCached(steps, base_pulses)

    def drift(self, rng: random.Random) -> bool:
        """Изменить pulses на ±1.

        Аргументы:
            rng: Генератор случайных чисел.

        Returns:
            True если изменение произошло.
        """
        current = self._euclidean.pulses
        choices: list[int] = []
        if current > 1:
            choices.append(-1)
        if current < self._euclidean.steps - 1:
            choices.append(1)
        if not choices:
            return False
        delta = rng.choice(choices)
        self._euclidean.pulses = current + delta
        log.debug("FloatingEuclidean: pulses %d→%d", current, self._euclidean.pulses)
        return True

    def revert(self, rng: random.Random) -> bool:
        """Вернуть pulses к базовому значению.

        Аргументы:
            rng: Генератор случайных чисел (не используется, для API-совместимости).

        Returns:
            True если откат произошёл.
        """
        if self._euclidean.pulses == self._base_pulses:
            return False
        self._euclidean.pulses = self._base_pulses
        log.debug("FloatingEuclidean: revert pulses→%d", self._base_pulses)
        return True

    def snapshot(self) -> int:
        return self._euclidean.pulses

    def restore(self, pulses: int) -> None:
        self._euclidean.pulses = pulses

    @property
    def pattern(self) -> list[int]:
        """Текущий евклидов паттерн (кешированный)."""
        return self._euclidean.pattern

    @property
    def pulses(self) -> int:
        """Текущее количество pulses."""
        return self._euclidean.pulses

    @property
    def base_pulses(self) -> int:
        """Базовое количество pulses."""
        return self._base_pulses

    @property
    def steps(self) -> int:
        """Общее количество шагов."""
        return self._euclidean.steps

    def __repr__(self) -> str:
        return (
            f"FloatingEuclidean(steps={self.steps}, "
            f"pulses={self.pulses}, base={self._base_pulses})"
        )
