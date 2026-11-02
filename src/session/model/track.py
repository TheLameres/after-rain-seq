"""Абстрактная база всех дорожек.

Всё, что общее для графа (outbox, current/history, источники), живёт
здесь один раз. Наследники — :class:`MelodicTrack` и :class:`DrumTrack`
(см. ``track-hierarchy.md``).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from src.session.events.chord_event import ChordEvent

log = logging.getLogger(__name__)


class Track(ABC):
    """Базовая дорожка сессии.

    Атрибуты:
        name: Автогенерированное имя (``"Pad 1"``, ``"Drum 1"``) —
            нужно для графа и дисплея.
        port: Имя MIDI-порта или ``None`` — дорожка молчит, сессия жива.
        channel: MIDI-канал 0..15, уникален внутри порта.
        muted: При ``True`` дорожка не звучит, но продолжает публиковать
            события (чтобы наследники не теряли гармонию).
        sources: Имена источников (максимум 2: ``"SOURCE"``, ``"SOURCE2"``).
        outbox: Опубликованные аккорды для дорожек-наследников.
    """

    def __init__(
        self,
        name: str,
        channel: int = 0,
        port: str | None = None,
    ) -> None:
        self.name = name
        self.port = port
        self.channel = channel
        self.muted = False
        self.sources: tuple[str, ...] = ()
        self.outbox: list[ChordEvent] = []

    # ------------------------------------------------------------------
    # Абстрактный интерфейс
    # ------------------------------------------------------------------

    @abstractmethod
    def generate(self) -> list:
        """Сгенерировать события в outbox.

        Вызывается движком на каждом цикле генерации. Реализация
        очищает outbox и заполняет его заново. Возвращает список
        сгенерированных событий (конкретный тип определяет наследник).
        """

    # ------------------------------------------------------------------
    # Чтение опубликованных событий
    # ------------------------------------------------------------------

    def current(self) -> ChordEvent | None:
        """Последнее событие из outbox или ``None``."""
        return self.outbox[-1] if self.outbox else None

    def history(self, since_beat: float) -> list[ChordEvent]:
        """События из outbox с ``beat >= since_beat``."""
        return [ev for ev in self.outbox if ev.beat >= since_beat]

    # ------------------------------------------------------------------
    # Отладка
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"name={self.name!r}, "
            f"port={self.port!r}, "
            f"ch={self.channel}, "
            f"muted={self.muted}, "
            f"sources={self.sources}"
            f")"
        )
