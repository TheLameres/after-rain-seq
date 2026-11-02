"""NoteEvent — одна нота мелодической дорожки в ступенях лада.

Промежуточное представление между генераторами паттернов (C6,
``generators.py``) и :class:`MelodicEngine`. Нота выражена **ступенью лада**,
а не MIDI-номером: абсолютная нота резолвится через :class:`Harmony` в
момент конвертации в ``TransportEvent`` — смена root/scale мгновенно
слышна без пересборки паттерна.

``beat`` — позиция внутри паттерна (beats, относительно начала паттерна,
0-based). Абсолютная позиция на таймлайне вычисляется планировщиком
(:class:`BeatScheduler`) через циклическое повторение паттерна.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NoteEvent:
    """Одна нота в ступенях лада.

    Атрибуты:
        beat: Позиция внутри паттерна, beats (0-based, относительная).
        degree: Ступень лада (0 = тоника); резолвится через Harmony.
        velocity: Скорость нажатия, 0–127.
        duration: Звучащая длительность в beats (гейт уже применён
            генератором; свинг применяет движок при планировании).
        octave_offset: Сдвиг октавы от ``track.octave`` (дрейф регистра
            из ParamDrift); резолвится движком через Harmony.
    """

    beat: float
    degree: int
    velocity: int
    duration: float
    octave_offset: int = 0
