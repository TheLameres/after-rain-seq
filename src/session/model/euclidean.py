"""Евклидовы ритмы с кешем — обёртка над isobar PEuclidean.

isobar ``PEuclidean`` пересчитывает алгоритм Бьорклунда **каждый тик**
(поле ``self.sequence`` объявлено, но не используется). При 16 lane
× 480 PPQN это тысячи пересчётов в секунду. Кеш обязателен.

Также в isobar ``PEuclidean.__repr__`` печатает ``self.phase``, а поле
называется ``self.pos`` — ``AttributeError`` на любом ``repr()``.
Не вызывать ``repr()`` на isobar-объекте.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class PEuclideanCached:
    """Евклидов ритм с кешем паттерна.

    Паттерн вычисляется один раз при первом доступе и пересчитывается
    только при смене ``steps`` или ``pulses``.

    Аргументы:
        steps: Общее количество шагов (длина сетки).
        pulses: Количество активных шагов (≤ steps).
    """

    def __init__(self, steps: int, pulses: int) -> None:
        if steps < 1:
            raise ValueError(f"steps должно быть >= 1, got {steps}")
        if pulses < 0:
            raise ValueError(f"pulses должно быть >= 0, got {pulses}")
        if pulses > steps:
            raise ValueError(f"pulses ({pulses}) не может быть > steps ({steps})")
        self._steps = steps
        self._pulses = pulses
        self._cached: list[int] | None = None

    # ------------------------------------------------------------------
    # Свойства
    # ------------------------------------------------------------------

    @property
    def steps(self) -> int:
        """Общее количество шагов."""
        return self._steps

    @property
    def pulses(self) -> int:
        """Количество активных шагов."""
        return self._pulses

    @pulses.setter
    def pulses(self, value: int) -> None:
        if value < 0:
            raise ValueError(f"pulses должно быть >= 0, got {value}")
        if value > self._steps:
            raise ValueError(f"pulses ({value}) не может быть > steps ({self._steps})")
        if value != self._pulses:
            self._pulses = value
            self._cached = None  # инвалидация кеша

    @property
    def pattern(self) -> list[int]:
        """Кешированный паттерн: 1 на активном шаге, 0 на паузе.

        Длина = ``steps``. Первый шаг всегда активен (pulses > 0).
        """
        if self._cached is None:
            self._cached = self._compute()
        return list(self._cached)  # копия, чтобы внешний код не портил кеш

    # ------------------------------------------------------------------
    # Алгоритм Бьорклунда
    # ------------------------------------------------------------------

    def _compute(self) -> list[int]:
        """Вычислить евклидов паттерн алгоритмом Бьорклунда.

        Returns:
            Список 0/1 длины ``steps``.
        """
        if self._pulses == 0:
            return [0] * self._steps
        if self._pulses == self._steps:
            return [1] * self._steps

        # Классический алгоритм Бьорклунда через распределение.
        # Представляем pulses единиц и (steps - pulses) нулей,
        # распределяем по столбцам, затем схлопываем.
        return self._bjorklund(self._pulses, self._steps - self._pulses)

    @staticmethod
    def _bjorklund(pulses: int, rests: int) -> list[int]:
        """Алгоритм Бьорклунда: равномерно распределить pulses единиц.

        Для позиции i (0-based) шаг активен если:
            (i * pulses) % (pulses + rests) < pulses

        Это гарантирует: первый шаг активен, сумма = pulses,
        распределение максимально равномерное (алгоритм Бресенхема).
        """
        total = pulses + rests
        if total == 0:
            return []

        result: list[int] = []
        for i in range(total):
            active = (i * pulses) % total < pulses
            result.append(1 if active else 0)
        return result

    # ------------------------------------------------------------------
    # Отладка
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"PEuclideanCached(steps={self._steps}, pulses={self._pulses})"
