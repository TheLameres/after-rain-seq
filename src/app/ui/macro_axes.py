"""Макро-оси DEN/MUT/SPACE/DEPTH/TONE (план D2 §3.5).

- DEN (плотность) и MUT (мутация) — семантика движка: значение оси 0..127
  конвертируется в 0..1 и уходит через ``EngineControl``.
- TONE/SPACE/DEPTH — performance-CC: состав оси (логические CC-параметры)
  берётся из конфига ``ui.macro_axes``; отправка — через переданный
  sender-колбэк (App резолвит порт + CCMap + троттлинг 30 Hz, B3).

Ось → CC-параметры валидируются при загрузке конфига: неизвестный
параметр — ошибка (стиль B3).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum

from src.sync.cc_map import DEFAULT_CC_PARAMS


class MacroAxis(Enum):
    """Пять макро-осей (метки на экране TRACK)."""

    DENSITY = "DEN"
    MUTATE = "MUT"
    SPACE = "SPACE"
    DEPTH = "DEPTH"
    TONE = "TONE"

    @property
    def is_cc_axis(self) -> bool:
        """True для TONE/SPACE/DEPTH — performance-CC, конфигурируемый состав."""
        return self in (MacroAxis.TONE, MacroAxis.SPACE, MacroAxis.DEPTH)


def cc_to_unit(value: int) -> float:
    """CC-значение 0..127 → 0.0–1.0 (DEN/MUT)."""
    return max(0, min(127, int(value))) / 127.0


def unit_to_cc(value: float) -> int:
    """0.0–1.0 → CC-значение 0..127 (округление, кламп)."""
    return max(0, min(127, round(max(0.0, min(1.0, value)) * 127)))


class MacroAxes:
    """Состав CC-осей из конфига (провалидированный).

    Parameters
    ----------
    config:
        Маппинг ``axis → [logical param names]`` (ключи — ``MacroAxis.value``
        в lower-case). Неизвестная ось или параметр — ``ValueError``.
    """

    def __init__(self, config: dict[str, list[str]] | None = None) -> None:
        raw: dict[str, list[str]] = (
            dict(config) if config is not None else _default_config()
        )
        self._cc_params: dict[MacroAxis, tuple[str, ...]] = {}
        for key, params in raw.items():
            axis = self._resolve_axis(key)
            if not params:
                raise ValueError(f"ui.macro_axes: ось {key!r} без параметров")
            for param in params:
                if param not in DEFAULT_CC_PARAMS:
                    known = ", ".join(sorted(DEFAULT_CC_PARAMS))
                    raise ValueError(
                        f"ui.macro_axes: неизвестный параметр {param!r} "
                        f"в оси {key!r} (choose: {known})"
                    )
            self._cc_params[axis] = tuple(params)

    @classmethod
    def from_ui_config(cls, macro_axes: Mapping[str, list[str]] | None) -> MacroAxes:
        """Построить из карты осей (``UiConfig.macro_axes``; None — дефолтный состав).

        Принимает сам словарь, а не ``UiConfig``: модуль не импортирует конфиг,
        поэтому цикл ``config`` ↔ ``macro_axes`` исчезает.
        """
        if macro_axes is None:
            return cls()
        return cls({axis: list(params) for axis, params in macro_axes.items()})

    def cc_params(self, axis: MacroAxis) -> tuple[str, ...]:
        """Логические CC-параметры оси (TONE/SPACE/DEPTH)."""
        if not axis.is_cc_axis:
            raise ValueError(f"ось {axis.value} не является CC-осью")
        return self._cc_params.get(axis, ())

    @staticmethod
    def _resolve_axis(key: str) -> MacroAxis:
        try:
            return MacroAxis(key.upper())
        except ValueError as exc:
            known = ", ".join(a.value for a in MacroAxis)
            raise ValueError(
                f"ui.macro_axes: неизвестная ось {key!r} (choose: {known})"
            ) from exc


def _default_config() -> dict[str, list[str]]:
    """Дефолтный состав осей (план D2 §3.7)."""
    return {
        "tone": ["filter"],
        "space": ["reverb", "delay"],
        "depth": ["resonance"],
    }
