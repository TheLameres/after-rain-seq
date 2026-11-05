"""Плавный дрейф числовых параметров — механизм мутации для pad/atmos/bass/sub."""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class _DriftParam:
    """Состояние одного дрейфующего параметра."""

    base: float
    current: float
    lo: float
    hi: float
    step: float


class ParamDrift:
    """Плавный дрейф числовых параметров дорожки.

    Моделирует поведение isobar PWhite: значение блуждает в диапазоне,
    не выходя за границы. Каждая мутация смещает значение на малую
    величину (step), с вероятностью возврата к базовому.

    Поддерживает параметры:
        gate: 0.1–1.0 (длительность ноты)
        density: 0.0–1.0 (плотность паттерна)
        register: -2..+2 (смещение октавы от базовой)
    """

    def __init__(self) -> None:
        self._params: dict[str, _DriftParam] = {}

    def add_param(
        self, name: str, base: float, lo: float, hi: float, step: float
    ) -> None:
        """Зарегистрировать параметр для дрейфа.

        Аргументы:
            name: Имя параметра (``"gate"``, ``"density"``, ``"register"``).
            base: Базовое значение.
            lo: Нижняя граница.
            hi: Верхняя граница.
            step: Максимальное смещение за одну мутацию.

        Raises:
            ValueError: Если lo >= hi, base вне [lo, hi], или step <= 0.
        """
        if lo >= hi:
            raise ValueError(f"lo ({lo}) должен быть < hi ({hi})")
        if not lo <= base <= hi:
            raise ValueError(f"base ({base}) вне [{lo}, {hi}]")
        if step <= 0:
            raise ValueError(f"step должен быть > 0, got {step}")
        self._params[name] = _DriftParam(
            base=base, current=base, lo=lo, hi=hi, step=step
        )

    def drift_one(self, rng: random.Random) -> str | None:
        """Сместить один случайный параметр.

        Аргументы:
            rng: Генератор случайных чисел.

        Returns:
            Имя изменённого параметра, или None если нет параметров.
        """
        if not self._params:
            return None
        name = rng.choice(list(self._params.keys()))
        p = self._params[name]
        delta = rng.uniform(-p.step, p.step)
        new_val = p.current + delta
        # Жёсткий clamp к границам
        new_val = max(p.lo, min(p.hi, new_val))
        p.current = new_val
        log.debug("ParamDrift: %s %s", name, new_val)
        return name

    def revert_one(self, rng: random.Random) -> str | None:
        """Вернуть один продугий параметр к базовому.

        Аргументы:
            rng: Генератор случайных чисел.

        Returns:
            Имя откаченного параметра, или None если нет дрейфа.
        """
        drifted = [n for n, p in self._params.items() if p.current != p.base]
        if not drifted:
            return None
        name = rng.choice(drifted)
        self._params[name].current = self._params[name].base
        log.debug("ParamDrift: revert %s→%s", name, self._params[name].base)
        return name

    def snapshot(self) -> tuple[tuple[str, float], ...]:
        return tuple((n, p.current) for n, p in self._params.items())

    def restore(self, state: tuple[tuple[str, float], ...]) -> None:
        if {n for n, _ in state} != set(self._params):
            raise ValueError("snapshot params do not match registered params")
        for name, current in state:
            self._params[name].current = current

    def get(self, name: str) -> float:
        """Текущее значение параметра.

        Аргументы:
            name: Имя параметра.

        Returns:
            Текущее (возможно продугое) значение.

        Raises:
            KeyError: Если параметр не зарегистрирован.
        """
        return self._params[name].current

    def get_base(self, name: str) -> float:
        """Базовое значение параметра.

        Аргументы:
            name: Имя параметра.

        Returns:
            Базовое (исходное) значение.

        Raises:
            KeyError: Если параметр не зарегистрирован.
        """
        return self._params[name].base

    @property
    def drift_count(self) -> int:
        """Сколько параметров отличается от базы."""
        return sum(1 for p in self._params.values() if p.current != p.base)

    @property
    def param_names(self) -> list[str]:
        """Имена всех зарегистрированных параметров."""
        return list(self._params.keys())

    def __repr__(self) -> str:
        params = {n: p.current for n, p in self._params.items()}
        return f"ParamDrift({params})"
