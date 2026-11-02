"""События сессии — значения-объекты, которыми обмениваются слои.

Ни от кого внутри пакета не зависят (слой 0):

- :class:`ChordEvent` — публикация аккордов по рёбрам графа.
- :class:`NoteEvent` — нота в ступенях лада (MIDI резолвит движок).
- :class:`DrumEvent` — событие drum-сетки (абсолютная нота GM).
"""

from src.session.events.chord_event import ChordEvent
from src.session.events.drum_event import DrumEvent
from src.session.events.note_event import NoteEvent

__all__ = [
    "ChordEvent",
    "DrumEvent",
    "NoteEvent",
]
