"""События UI — frozen DTO, которые MIDI-поток кладёт в UiEventQueue."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UiEvent:
    """Одно событие от контроллера (кнопка/энкодер/пад).

    Атрибуты:
        kind: ``"button"``, ``"encoder"`` или ``"pad"``.
        name: Имя кнопки/энкодера из mapping.py; для пада — номер ноты
            (``"36"``..``"99"``) строкой.
        value: Для кнопки — 1 (press) / 0 (release); для энкодера —
            relative-инкремент (two's complement, уже декодирован
            драйвером); для пада — velocity (0 = release).
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

    @classmethod
    def pad(cls, note: int, velocity: int) -> UiEvent:
        """Событие пада: note 36–99, velocity (0 = release)."""
        return cls(kind="pad", name=str(int(note)), value=int(velocity))
