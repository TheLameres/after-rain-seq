"""Мелодические движки — исполнение модели в звук.

- :class:`BeatScheduler` — lookahead-планировщик: горизонт, watermark,
  допуск опоздания 1/16; события доставляются однократно, в свой бит.
- :mod:`generators` — чистые генераторы нот по профилям
  (``generate_notes(ctx)``); паттерны как данные, один вход.
- :class:`MelodicEngine` — мост ``MelodicTrack`` → транспорт через
  ``Harmony``: резолв ступеней в MIDI, gate, свинг.
"""

from src.session.engine.beat_scheduler import BeatScheduler
from src.session.engine.generators import (
    GenerationContext,
    chord_cycle,
    chord_degrees_for,
    generate_notes,
    pattern_length,
    pattern_length_for,
)
from src.session.engine.melodic_engine import MelodicEngine

__all__ = [
    "BeatScheduler",
    "GenerationContext",
    "MelodicEngine",
    "chord_cycle",
    "chord_degrees_for",
    "generate_notes",
    "pattern_length",
    "pattern_length_for",
]
