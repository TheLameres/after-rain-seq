"""Доменная модель дорожек — слой 1 пакета session.

Зависит только от ``events/`` и ``src/harmony/``. Движки (``engine/``)
и мутация (``mutation/``) строятся поверх этой модели.

- :class:`Track` — абстрактная база; наследники ``MelodicTrack``,
  ``DrumTrack``.
- :class:`MelodicProfile` + ``PROFILES`` — профили как данные (11 штук).
- :class:`PatternSpec` — декларативное описание паттерна профиля.
- :class:`DrumLane` — lane drum-сетки (GM 36–51).
- :class:`PEuclideanCached` — чистая математика евклидовых ритмов
  (используется мутацией и генераторами).
- ``chord_math`` — общая аккордовая математика (войсинг + обращение,
  длина паттерна) для графа и звука.
"""

from src.session.model.chord_math import (
    chord_cycle,
    chord_degrees_for,
    pattern_length,
)
from src.session.model.drum_lane import DrumLane
from src.session.model.drum_track import DrumTrack
from src.session.model.euclidean import PEuclideanCached
from src.session.model.melodic_profile import PROFILES, MelodicProfile
from src.session.model.melodic_track import MelodicTrack
from src.session.model.pattern_spec import (
    FAMILY_CC_ONLY,
    FAMILY_CHORD_SLICER,
    FAMILY_CHORD_SOURCE,
    FAMILY_FREE_MONO,
    PatternSpec,
)
from src.session.model.track import Track

__all__ = [
    "FAMILY_CC_ONLY",
    "FAMILY_CHORD_SLICER",
    "FAMILY_CHORD_SOURCE",
    "FAMILY_FREE_MONO",
    "PROFILES",
    "DrumLane",
    "DrumTrack",
    "MelodicProfile",
    "MelodicTrack",
    "PEuclideanCached",
    "PatternSpec",
    "Track",
    "chord_cycle",
    "chord_degrees_for",
    "pattern_length",
]
