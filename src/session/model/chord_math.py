"""Общая аккордовая математика — одна точка правды для графа и звука.

Чистые функции без состояния. Используются моделью (публикация
``ChordEvent``), генераторами нот и движками. Живут в слое ``model/``,
чтобы модель не импортировала движок (разрыв бывшего цикла
``melodic_track`` ↔ ``generators``).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Protocol

from src.harmony.voicings import Voicing
from src.session.events.chord_event import ChordEvent
from src.session.model.melodic_profile import MelodicProfile
from src.session.model.pattern_spec import (
    FAMILY_CC_ONLY,
    FAMILY_CHORD_SOURCE,
)

log = logging.getLogger(__name__)


class ChordTrack(Protocol):
    """Что математике аккордов нужно от дорожки.

    Протокол вместо ``MelodicTrack``: модель не импортирует конкретный класс
    дорожки, поэтому цикл ``chord_math`` ↔ ``melodic_track`` исчезает.
    ``MelodicTrack`` подходит структурно и менять его не нужно.
    """

    degrees: list[int]
    inversion: int
    voicing: str
    profile: MelodicProfile


def chord_degrees_for(track: ChordTrack, degree: int) -> tuple[int, ...]:
    """Ступени аккорда для ступени прогрессии: войсинг + обращение.

    Общая математика для публикации ``ChordEvent`` (граф) и генерации
    нот (звучание) — одна точка правды.

    Аргументы:
        track: Мелодическая дорожка (voicing + inversion).
        degree: Ступень прогрессии (0 = тоника).

    Returns:
        Ступени аккорда относительно тоники лада.
    """
    offsets = Voicing.VOICINGS[track.voicing]
    degs = tuple(degree + off for off in offsets)
    if track.inversion > 0:
        degs = Voicing.invert(degs, track.inversion)
    return degs


def pattern_length(track: ChordTrack) -> float:
    """Длина паттерна профиля в beats (период циклического повторения).

    Аргументы:
        track: Мелодическая дорожка.

    Returns:
        Период паттерна в beats; 0.0 для cc_only/пустой прогрессии.
    """
    spec = track.profile.pattern
    n = len(track.degrees)
    if spec.family == FAMILY_CC_ONLY or n == 0:
        return 0.0
    if spec.change_every > 1:
        # atmos: n аккордов × change_every beats; texture: change_every beats
        if spec.family == FAMILY_CHORD_SOURCE:
            return float(n) * spec.change_every
        return float(spec.change_every)
    return float(n)


def chord_cycle(window: Iterable[ChordEvent]) -> float:
    """Период цикла аккордов окна: максимальный beat + длительность.

    Аргументы:
        window: ChordEvent источников (относительные beats одного цикла).

    Returns:
        Период в beats; 0.0 для пустого окна.
    """
    return max((ev.beat + ev.duration for ev in window), default=0.0)
