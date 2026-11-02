"""Drum-движок — мост между DrumTrack и транспортом.

- :class:`DrumEngine` — конвертация ``DrumEvent`` в ``TransportEvent``,
  свинг, drop-oldest очередь.
- :class:`DrumConfig` — pydantic-схема конфигурации drum-машины.
"""

from src.session.drum.drum_config import DrumConfig
from src.session.drum.drum_engine import DrumEngine

__all__ = [
    "DrumConfig",
    "DrumEngine",
]
