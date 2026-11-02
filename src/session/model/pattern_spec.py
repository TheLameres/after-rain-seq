"""PatternSpec — спецификация генерации паттерна профиля как данные (C6).

Различия между профилями — данные, не код (``track-hierarchy.md``): каждый
:class:`MelodicProfile` несёт :class:`PatternSpec`, описывающий **как**
порождаются ноты (семейство генератора, сетка, громкости, разреженность).
Генераторы (``generators.py``) читают спецификацию и не ветвятся по именам
профилей.

Семейства генераторов (структурно разные способы порождения нот):

- ``chord_source`` — собственная прогрессия ``degrees`` → аккорды целиком;
  ``change_every`` > 1 даёт разреженный аккорд (atmos).
- ``chord_slicer`` — нарезка ``ChordEvent`` источников (шаг 3 C6).
- ``free_mono`` — одна линия из собственных ступеней; ``change_every`` > 1
  даёт редкую одиночную ноту (texture).
- ``cc_only`` — нот нет (CC — отдельная задача).

Внутри семейства вариации тоже выводятся из данных: pad/atmos — один
генератор с разным ``change_every``; bass/lead — один генератор (lead
получает ``NoteDrift``, bass — нет); texture — тот же генератор с
``change_every > 1``.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Семейство: собственная прогрессия → аккорды целиком (pad, atmos).
FAMILY_CHORD_SOURCE: str = "chord_source"

#: Семейство: нарезка ChordEvent источников (sub, stab, seq, arp).
FAMILY_CHORD_SLICER: str = "chord_slicer"

#: Семейство: одна мелодическая линия из собственных ступеней.
FAMILY_FREE_MONO: str = "free_mono"

#: Семейство: нот нет, только CC (cc_filter, cc_space).
FAMILY_CC_ONLY: str = "cc_only"


@dataclass(frozen=True)
class PatternSpec:
    """Как профиль порождает ноты — данные, не код.

    Атрибуты:
        family: Одно из ``FAMILY_*``.
        shape: Форма нарезки внутри семейства (``"sub"``, ``"stab"``,
            ``"seq"``, ``"arp"`` для chord_slicer; пусто — форма выводится
            из остальных полей).
        steps: Сетка нарезки в шагах (для chord_slicer), 16 по умолчанию.
        base_pulses: Базовое число pulses евклидова паттерна (chord_slicer).
        change_every: Смена материала раз в N beats: >1 — один аккорд/нота
            на весь паттерн такой длины (atmos, texture); 1 — каждый beat.
        velocity_base: Базовая velocity нот (0–127).
        velocity_accent: Velocity акцентированной ноты (первый шаг паттерна).
        sub_shift: Сдвиг sub в долях от длительности аккорда источника.
        arp_direction: Направление обхода аккорда (``"up"`` / ``"down"``).
    """

    family: str
    shape: str = ""
    steps: int = 16
    base_pulses: int = 4
    change_every: int = 1
    velocity_base: int = 100
    velocity_accent: int = 100
    sub_shift: float = 0.25
    arp_direction: str = "up"

    def __post_init__(self) -> None:
        known = (
            FAMILY_CHORD_SOURCE,
            FAMILY_CHORD_SLICER,
            FAMILY_FREE_MONO,
            FAMILY_CC_ONLY,
        )
        if self.family not in known:
            raise ValueError(f"Неизвестное семейство генератора: {self.family!r}")
        if self.steps < 2:
            raise ValueError(f"steps должен быть >= 2, got {self.steps}")
        if self.change_every < 1:
            raise ValueError(f"change_every должен быть >= 1, got {self.change_every}")
        if not 0 <= self.velocity_base <= 127:
            raise ValueError(f"velocity_base вне [0, 127]: {self.velocity_base}")
        if not 0 <= self.velocity_accent <= 127:
            raise ValueError(f"velocity_accent вне [0, 127]: {self.velocity_accent}")
