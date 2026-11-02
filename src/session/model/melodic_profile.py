"""Профили мелодических дорожек — различия как данные, не как классы.

Каждый профиль — frozen dataclass :class:`MelodicProfile`. Реестр
``PROFILES`` мапит имя на профиль. Новый профиль добавляется строкой
в реестре, новый класс — только если поведение структурно иное
(см. ``track-hierarchy.md``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.session.model.pattern_spec import (
    FAMILY_CC_ONLY,
    FAMILY_CHORD_SLICER,
    FAMILY_CHORD_SOURCE,
    FAMILY_FREE_MONO,
    PatternSpec,
)

log = logging.getLogger(__name__)


def _default_pattern() -> PatternSpec:
    """Паттерн по умолчанию — cc_only (генератор молчит)."""
    return PatternSpec(family=FAMILY_CC_ONLY)


@dataclass(frozen=True)
class MelodicProfile:
    """Набор параметров, определяющих поведение мелодической дорожки.

    Атрибуты:
        name: Имя профиля (``"pad"``, ``"atmos"``, ``"seq"``, …).
        reads_source: Дорожка читает аккорды из источников
            (sub, stab, seq, arp, texture — ``True``).
        emits_chords: Дорожка публикует ``ChordEvent`` в outbox
            (pad, atmos — ``True``).
        default_voicing: Войсинг по умолчанию.
        default_octave: Октава по умолчанию.
        default_gate: Гейт по умолчанию (0.0–1.0).
        cc_only: Профиль не генерирует ноты, только CC
            (cc_filter, cc_space).
        pattern: Спецификация генерации паттерна (C6) — как профиль
            порождает ноты: семейство, сетка, громкости, разреженность.
    """

    name: str
    reads_source: bool
    emits_chords: bool
    default_voicing: str
    default_octave: int
    default_gate: float
    cc_only: bool = False
    pattern: PatternSpec = field(default_factory=_default_pattern)


PROFILES: dict[str, MelodicProfile] = {
    "pad": MelodicProfile(
        name="pad",
        reads_source=False,
        emits_chords=True,
        default_voicing="1-3-5",
        default_octave=5,
        default_gate=0.9,
        pattern=PatternSpec(
            family=FAMILY_CHORD_SOURCE,
            velocity_base=78,
            velocity_accent=92,
        ),
    ),
    "atmos": MelodicProfile(
        name="atmos",
        reads_source=False,
        emits_chords=True,
        default_voicing="1-3-5-7",
        default_octave=4,
        default_gate=1.0,
        pattern=PatternSpec(
            family=FAMILY_CHORD_SOURCE,
            change_every=8,
            velocity_base=70,
            velocity_accent=80,
        ),
    ),
    "sub": MelodicProfile(
        name="sub",
        reads_source=True,
        emits_chords=False,
        default_voicing="1",
        default_octave=1,
        default_gate=1.0,
        pattern=PatternSpec(
            family=FAMILY_CHORD_SLICER,
            shape="sub",
            velocity_base=100,
        ),
    ),
    "stab": MelodicProfile(
        name="stab",
        reads_source=True,
        emits_chords=False,
        default_voicing="1-4-7",
        default_octave=5,
        default_gate=0.2,
        pattern=PatternSpec(
            family=FAMILY_CHORD_SLICER,
            shape="stab",
            base_pulses=4,
            velocity_base=95,
            velocity_accent=115,
        ),
    ),
    "seq": MelodicProfile(
        name="seq",
        reads_source=True,
        emits_chords=False,
        default_voicing="1-3-5",
        default_octave=5,
        default_gate=0.5,
        pattern=PatternSpec(
            family=FAMILY_CHORD_SLICER,
            shape="seq",
            base_pulses=6,
            velocity_base=96,
            velocity_accent=112,
        ),
    ),
    "arp": MelodicProfile(
        name="arp",
        reads_source=True,
        emits_chords=False,
        default_voicing="1-3-5",
        default_octave=5,
        default_gate=0.4,
        pattern=PatternSpec(
            family=FAMILY_CHORD_SLICER,
            shape="arp",
            velocity_base=90,
            velocity_accent=104,
        ),
    ),
    "bass": MelodicProfile(
        name="bass",
        reads_source=False,
        emits_chords=False,
        default_voicing="1",
        default_octave=2,
        default_gate=0.8,
        pattern=PatternSpec(
            family=FAMILY_FREE_MONO,
            velocity_base=100,
            velocity_accent=110,
        ),
    ),
    "lead": MelodicProfile(
        name="lead",
        reads_source=False,
        emits_chords=False,
        default_voicing="1",
        default_octave=5,
        default_gate=0.6,
        pattern=PatternSpec(
            family=FAMILY_FREE_MONO,
            velocity_base=88,
            velocity_accent=104,
        ),
    ),
    "texture": MelodicProfile(
        name="texture",
        reads_source=True,
        emits_chords=False,
        default_voicing="1",
        default_octave=6,
        default_gate=0.5,
        pattern=PatternSpec(
            family=FAMILY_FREE_MONO,
            change_every=8,
            velocity_base=72,
        ),
    ),
    "cc_filter": MelodicProfile(
        name="cc_filter",
        reads_source=False,
        emits_chords=False,
        default_voicing="",
        default_octave=0,
        default_gate=0.0,
        cc_only=True,
    ),
    "cc_space": MelodicProfile(
        name="cc_space",
        reads_source=False,
        emits_chords=False,
        default_voicing="",
        default_octave=0,
        default_gate=0.0,
        cc_only=True,
    ),
}
