"""Событие аккорда — единица публикации в графе дорожек.

Когда дорожка с ``emits_chords=True`` (pad, atmos) генерирует аккорд,
она кладёт :class:`ChordEvent` в свой ``outbox``. Дорожки-наследники
(``reads_source=True``) читают события источников через ``current()`` /
``history()`` и переозвучивают их своим войсингом, октавой, гейтом.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChordEvent:
    """Аккорд, опубликованный дорожкой-источником.

    Атрибуты:
        beat: Такт, на котором аккорд начинается (float, 0-based).
        degrees: Ступени аккорда относительно тоники лада
            (например, ``(0, 2, 4)`` для триады на I).
        duration: Длительность в тактах.
        voicing: Имя войсинга из ``Voicing.VOICINGS`` (например, ``"1-3-5"``).
    """

    beat: float
    degrees: tuple[int, ...]
    duration: float
    voicing: str
