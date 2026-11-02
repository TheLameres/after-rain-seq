"""События UI — frozen DTO, которые MIDI-поток кладёт в UiEventQueue."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UiEvent:
    """Одно событие от контроллера (кнопка/энкодер).

    Атрибуты:
        kind: ``"button"`` или ``"encoder"``.
        name: Имя кнопки/энкодера из mapping.py (физический слой).
        value: Для кнопки — 1 (press) / 0 (release); для энкодера —
            relative-инкремент (two's complement, уже декодирован
            драйвером).
    """

    kind: str
    name: str
    value: int

    @classmethod
    def button(cls, name: str, pressed: bool) -> UiEvent:
        """Кнопочное событие."""
        return cls(kind="button", name=name, value=1 if pressed else 0)

    @classmethod
    def encoder(cls, name: str, increment: int) -> UiEvent:
        """Событие поворота энкодера."""
        return cls(kind="encoder", name=name, value=int(increment))
