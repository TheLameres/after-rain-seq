"""Дрейф нот в пределах лада — механизм мутации для lead/texture профилей."""

from __future__ import annotations

import logging
import random
from collections.abc import Sequence

log = logging.getLogger(__name__)


class NoteDrift:
    """Дрейф нот в пределах лада — для lead/texture профилей.

    Хранит текущие ступени (degrees) для каждой позиции паттерна.
    При мутации смещает одну ступень на ±1 (в пределах лада).
    Деградация возвращает ступень к базовому значению.

    Дрейф ограничен: ступень не выходит за пределы ``[0, max_degree)``,
    где ``max_degree = scale_length * 2`` (две октавы лада).
    Это предотвращает уход в неслышимые регистры.
    """

    def __init__(self, base_degrees: list[int], scale_length: int = 7) -> None:
        if scale_length < 1:
            raise ValueError(f"scale_length должен быть >= 1, got {scale_length}")
        self._base: list[int] = list(base_degrees)
        self._current: list[int] = list(base_degrees)
        self._scale_length: int = scale_length
        self._max_degree: int = scale_length * 2

    def set_base(self, degrees: Sequence[int]) -> None:
        """Заменить базовую прогрессию (правка ``track.degrees`` пользователем).

        Пользовательская правка — новая истина: накопленный дрейф сбрасывается,
        ``current`` становится равен новой базе. Смена длины логируется на
        уровне ``info`` (позиции старого дрейфа не соответствуют новым).

        Аргументы:
            degrees: Новая базовая прогрессия (непустая).

        Raises:
            ValueError: Если прогрессия пуста.
        """
        new = list(degrees)
        if not new:
            raise ValueError("NoteDrift.set_base: пустая прогрессия")
        if len(new) != len(self._base):
            log.info(
                "NoteDrift: длина базы %d -> %d, дрейф сброшен",
                len(self._base),
                len(new),
            )
        self._base = new
        self._current = list(new)

    def drift_one(self, rng: random.Random) -> bool:
        """Сместить одну случайную ступень на ±1.

        Аргументы:
            rng: Генератор случайных чисел (инъекция для тестов).

        Returns:
            True если изменение произошло.
        """
        if not self._current:
            return False
        idx = rng.randrange(len(self._current))
        delta = rng.choice([-1, 1])
        new_val = self._current[idx] + delta
        # Жёсткие границы: [0, max_degree)
        if not 0 <= new_val < self._max_degree:
            # Пробуем противоположное направление
            new_val = self._current[idx] - delta
            if not 0 <= new_val < self._max_degree:
                return False
        self._current[idx] = new_val
        log.debug("NoteDrift: idx=%d %d→%d", idx, self._current[idx] - delta, new_val)
        return True

    def revert_one(self, rng: random.Random) -> bool:
        """Вернуть одну продугую ступень к базовому значению.

        Аргументы:
            rng: Генератор случайных чисел.

        Returns:
            True если откат произошёл.
        """
        drifted = [
            i for i in range(len(self._current)) if self._current[i] != self._base[i]
        ]
        if not drifted:
            return False
        idx = rng.choice(drifted)
        old_val = self._current[idx]
        self._current[idx] = self._base[idx]
        log.debug("NoteDrift: revert idx=%d %d→%d", idx, old_val, self._base[idx])
        return True

    def snapshot(self) -> tuple[int, ...]:
        return tuple(self._current)

    def restore(self, state: tuple[int, ...]) -> None:
        if len(state) != len(self._base):
            raise ValueError(f"snapshot length {len(state)} != {len(self._base)}")
        self._current = list(state)

    @property
    def current_degrees(self) -> list[int]:
        """Текущие (возможно продугие) ступени — копия списка."""
        return list(self._current)

    @property
    def base_degrees(self) -> list[int]:
        """Базовые (исходные) ступени — копия списка."""
        return list(self._base)

    @property
    def drift_count(self) -> int:
        """Сколько ступеней отличается от базы."""
        return sum(
            1 for i in range(len(self._current)) if self._current[i] != self._base[i]
        )

    def __repr__(self) -> str:
        return (
            f"NoteDrift(base={self._base}, current={self._current}, "
            f"scale_len={self._scale_length})"
        )
