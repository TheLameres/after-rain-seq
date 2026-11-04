"""Абстрактная база всех дорожек.

Всё, что общее для графа (outbox, current/history, источники), живёт
здесь один раз. Наследники — :class:`MelodicTrack` и :class:`DrumTrack`
(см. ``track-hierarchy.md``).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from src.session.events.chord_event import ChordEvent
from src.session.events.drum_event import DrumEvent

log = logging.getLogger(__name__)

TrackEvent = ChordEvent | DrumEvent
"""Событие, опубликованное дорожкой: гармония либо ритм (§4.5)."""

MAX_SOURCES: int = 2
"""Предел источников на дорожку (``SOURCE`` + ``SOURCE2``)."""


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
        outbox: Опубликованные события (``ChordEvent`` для мелодических,
            ``DrumEvent`` для ударных) для дорожек-наследников.
    """

    def __init__(
        self,
        name: str,
        channel: int = 0,
        port: str | None = None,
        color_slot: int | None = None,
    ) -> None:
        self.name = name
        self.port = port
        self.channel = channel
        # §4.8: цвет — свойство дорожки, а не позиция в списке. Слот выдаётся
        # Session при создании и не переиспользуется, пока дорожка жива:
        # удаление соседа не перекрашивает остальные.
        self.color_slot: int | None = color_slot
        self.muted = False
        self._sources: tuple[str, ...] = ()
        self.outbox: list[TrackEvent] = []
        # §4.4: счётчик принадлежит дорожке (источник истины, §3.4).
        # Мутирующие механизмы (MutationEngine, DrumTrack) пишут сюда,
        # UI читает отсюда — константы больше нет.
        self._mutation_count: int = 0

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

    def current(self) -> TrackEvent | None:
        """Последнее событие из outbox или ``None`` (любого типа, §4.5)."""
        return self.outbox[-1] if self.outbox else None

    def history(self, since_beat: float) -> list[TrackEvent]:
        """События из outbox с ``beat >= since_beat``."""
        return [ev for ev in self.outbox if ev.beat >= since_beat]

    # ------------------------------------------------------------------
    # Источники (§4.7)
    # ------------------------------------------------------------------

    @property
    def sources(self) -> tuple[str, ...]:
        """Имена дорожек-источников (максимум 2)."""
        return self._sources

    @sources.setter
    def sources(self, value: tuple[str, ...]) -> None:
        """Назначить источники.

        Валидация в базовом классе: наследник больше не подменяет
        атрибут property с другим контрактом (§4.7). Дорожки, не
        участвующие в графе, запрещают непустое значение через
        :attr:`accepts_sources`.
        """
        value = tuple(value)
        if value and not self.accepts_sources:
            raise ValueError(
                f"{self.__class__.__name__} не участвует в графе гармонии, "
                "источники недопустимы"
            )
        if len(value) > MAX_SOURCES:
            raise ValueError(f"Максимум {MAX_SOURCES} источника, получено {len(value)}")
        self._sources = value

    @property
    def accepts_sources(self) -> bool:
        """Может ли дорожка получать источники (для drum — нет)."""
        return True

    # ------------------------------------------------------------------
    # Счётчик мутаций (§4.4)
    # ------------------------------------------------------------------

    @property
    def mutation_count(self) -> int:
        """Изменений с последней заморозки.

        Пишут мутирующие механизмы через :meth:`record_mutation`,
        сбрасывается :meth:`reset_mutation_count` (вызывает ``freeze()``).
        Без подключённого движка остаётся 0.
        """
        return self._mutation_count

    def record_mutation(self, delta: int = 1) -> None:
        """Учесть изменение паттерна (вызывает механизм мутации)."""
        self._mutation_count += delta

    def reset_mutation_count(self) -> None:
        """Сбросить счётчик (заморозка начинает новый отсчёт)."""
        self._mutation_count = 0

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
