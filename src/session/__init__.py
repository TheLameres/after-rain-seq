"""session — граф дорожек, Session API и движки исполнения (планы C3–C6).

Структура пакета (слои, импорты только вниз):

- :mod:`events` — события (ChordEvent, NoteEvent, DrumEvent).
- :mod:`model` — доменная модель дорожек (Track, MelodicTrack, DrumTrack,
  профили, PatternSpec, евклидова математика, chord_math).
- :mod:`mutation` — дрейф параметров (NoteDrift, FloatingEuclidean,
  ParamDrift, MutationEngine).
- :mod:`graph` — граф зависимостей дорожек (TrackGraph).
- ``session.py`` — Session, корневой контейнер (model + graph).
- :mod:`drum` — DrumEngine, DrumConfig.
- :mod:`engine` — мелодические движки (BeatScheduler, generators,
  MelodicEngine).

Этот модуль — фасад: реэкспортирует публичный API для внешних
потребителей. Канонические пути для импортов внутри проекта — глубокие
(``src.session.model.melodic_track`` и т.п.).
"""

from src.session.drum.drum_engine import DrumEngine
from src.session.engine.beat_scheduler import BeatScheduler
from src.session.engine.generators import GenerationContext, generate_notes
from src.session.engine.melodic_engine import MelodicEngine
from src.session.events.chord_event import ChordEvent
from src.session.events.drum_event import DrumEvent
from src.session.events.note_event import NoteEvent
from src.session.graph.track_graph import TrackGraph
from src.session.model.drum_lane import DrumLane
from src.session.model.drum_track import DrumTrack
from src.session.model.melodic_profile import PROFILES, MelodicProfile
from src.session.model.melodic_track import MelodicTrack
from src.session.model.track import Track
from src.session.mutation.floating_euclidean import FloatingEuclidean
from src.session.mutation.mutation_engine import MutationEngine
from src.session.mutation.mutation_state import MutationState
from src.session.mutation.note_drift import NoteDrift
from src.session.mutation.param_drift import ParamDrift
from src.session.session import Session

__all__ = [
    "PROFILES",
    "BeatScheduler",
    "ChordEvent",
    "DrumEngine",
    "DrumEvent",
    "DrumLane",
    "DrumTrack",
    "FloatingEuclidean",
    "GenerationContext",
    "MelodicEngine",
    "MelodicProfile",
    "MelodicTrack",
    "MutationEngine",
    "MutationState",
    "NoteDrift",
    "NoteEvent",
    "ParamDrift",
    "Session",
    "Track",
    "TrackGraph",
    "generate_notes",
]
