"""BeatScheduler — lookahead-планировщик MIDI-событий по битам (C6, шаг 1).

Решает разрыв R1: события доставляются **однократно, в свой бит**, а не
пачкой на каждый тик. Планировщик хранит ``TransportEvent`` с абсолютным
``beat`` на окне ``[watermark, watermark + horizon)`` и отдаёт (``due()``)
все события, время которых наступило.

Модель:

1. ``ensure(now)`` — ленивая инициализация водяного знака текущим битом
   (первый тик не порождает всплеск «наверстывания»).
2. Производитель генерирует события на окно ``[watermark, until)`` и кладёт
   их через ``schedule()``; затем поднимает знак ``advance(until)``.
3. На каждом тике ``due(now)`` возвращает (и изымает) события с
   ``beat <= now + epsilon``, в порядке beat. Опоздавшие более чем на 1/16
   доли пропускаются с логом — не играются пачкой после потери тиков.
4. ``reset()`` — при STOP/панике: сброс знака и очистка pending, чтобы
   после остановки не «доигрывать прошлое».

Без потоков: всё исполняется в dispatch-хуке TickProxy (один рабочий поток).
Сортировка по beat поддерживается вставкой (``bisect``); pending-очередь
мала (события одного горизонта), ``pop(0)`` дёшев.
"""

from __future__ import annotations

import bisect
import logging

from src.sync.transport_event import TransportEvent

log = logging.getLogger(__name__)


class BeatScheduler:
    """Планировщик TransportEvent с горизонтом в beats.

    Аргументы:
        horizon: Горизонт планирования в beats (по умолчанию 1 такт = 4).
        epsilon: Допуск сравнения beat (защита от float-дрейфа).

    Атрибуты (read-only):
        watermark: Абсолютный beat, до которого расписание достроено.
        initialized: Был ли знак инициализирован (ensure).
    """

    def __init__(self, horizon: float = 4.0, epsilon: float = 1e-6) -> None:
        if horizon <= 0:
            raise ValueError(f"horizon должен быть > 0, got {horizon}")
        if epsilon < 0:
            raise ValueError(f"epsilon должен быть >= 0, got {epsilon}")
        self._horizon: float = float(horizon)
        self._epsilon: float = float(epsilon)
        self._late: float = 1.0 / 16.0  # 1/16 доли — граница «слишком поздно»
        self._pending: list[TransportEvent] = []
        self._watermark: float = 0.0
        self._initialized: bool = False

    # ------------------------------------------------------------------
    # Свойства
    # ------------------------------------------------------------------

    @property
    def horizon(self) -> float:
        """Горизонт планирования в beats."""
        return self._horizon

    @property
    def watermark(self) -> float:
        """Beat, до которого расписание достроено."""
        return self._watermark

    @property
    def initialized(self) -> bool:
        """True после первого ensure()."""
        return self._initialized

    @property
    def pending_count(self) -> int:
        """Количество событий в очереди ожидания."""
        return len(self._pending)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def ensure(self, now: float) -> None:
        """Инициализировать водяной знак текущим beat (лениво, один раз).

        Аргументы:
            now: Текущая позиция таймлайна в beats.
        """
        if not self._initialized:
            self._watermark = float(now)
            self._initialized = True

    def advance(self, until: float) -> None:
        """Поднять водяной знак до until.

        Аргументы:
            until: Новый watermark (beats). Только вперёд: меньшие значения
                игнорируются.
        """
        if until > self._watermark:
            self._watermark = float(until)

    def schedule(self, event: TransportEvent) -> None:
        """Поместить событие в очередь ожидания (сортировка по beat).

        Аргументы:
            event: Событие с абсолютным beat.
        """
        bisect.insort(self._pending, event, key=lambda ev: ev.beat)

    def due(self, now: float) -> list[TransportEvent]:
        """Изъять и вернуть события, время которых наступило.

        Возвращает события с ``beat <= now + epsilon`` в порядке возрастания
        beat. События с ``beat < now - late`` (опоздали более чем на 1/16
        доли) пропускаются с логом — защита от всплеска после потери тиков,
        а не нормальный путь: ``due()`` вызывается на каждом тике, поэтому
        событие доставляется в пределах одного тика после своего beat.

        Аргументы:
            now: Текущая позиция таймлайна в beats.

        Returns:
            Список событий к немедленной доставке (может быть пустым).
        """
        limit = float(now) + self._epsilon
        result: list[TransportEvent] = []
        while self._pending and self._pending[0].beat <= limit:
            event = self._pending.pop(0)
            if event.beat < float(now) - self._late:
                log.debug(
                    "BeatScheduler: опоздавшее событие %s (beat=%.3f, now=%.3f), "
                    "пропущено",
                    event.kind.name,
                    event.beat,
                    now,
                )
                continue
            result.append(event)
        return result

    def reset(self) -> None:
        """Сбросить планировщик: очистить pending и водяной знак.

        Вызывается при STOP транспорта и панике (all_notes_off), чтобы
        после остановки не доставлять запланированное «прошлое».
        """
        self._pending.clear()
        self._watermark = 0.0
        self._initialized = False

    def __repr__(self) -> str:
        return (
            f"BeatScheduler(horizon={self._horizon}, "
            f"watermark={self._watermark:.3f}, pending={len(self._pending)})"
        )
