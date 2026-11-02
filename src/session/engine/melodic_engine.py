"""MelodicEngine — мост между MelodicTrack и транспортом.

C6 (шаг 1): движок переведён на lookahead-планировщик
(:class:`BeatScheduler`). Тик больше не кладёт в очередь весь паттерн
целиком — события доставляются **однократно, в свой бит**:

1. ``ensure(now)`` — ленивая инициализация водяного знака.
2. Достроение горизонта: пока ``watermark < now + H``, генерируем ноты
   на окно ``[watermark, watermark + H)`` (паттерн циклически повторяется
   через ``track.pattern_length``) и кладём note_on/note_off-пары в
   планировщик.
3. Доставка: всё, чей beat наступил (``<= now + ε``), — в event_queue;
   Transport забирает сразу после хука.

NoteEvent (ступени) резолвятся в MIDI-ноты через :class:`Harmony` при
построении окна; gate и свинг применяются к длительности до планирования.
"""

from __future__ import annotations

import logging
import math
import queue
from typing import TYPE_CHECKING

from src.harmony.harmony import Harmony
from src.session.engine.beat_scheduler import BeatScheduler
from src.session.engine.generators import (
    GenerationContext,
    generate_notes,
    pattern_length_for,
)
from src.session.events.note_event import NoteEvent
from src.session.model.melodic_track import MelodicTrack
from src.sync.swing import SwingApplier
from src.sync.transport_event import TransportEvent

if TYPE_CHECKING:
    from src.session.mutation.mutation_engine import MutationEngine

log = logging.getLogger(__name__)


class MelodicEngine:
    """Движок мелодической дорожки — планирование NoteEvent → TransportEvent.

    Аргументы:
        track: Мелодическая дорожка-источник.
        harmony: Гармонический слой для резолвинга ступеней.
        event_queue: Очередь для TransportEvent (разделяется с Transport).
        port_label: Метка MIDI-порта для событий.
        swing: Применитель свинга (amount=0 — без свинга).
        horizon: Горизонт планирования в beats (по умолчанию 1 такт).
    """

    def __init__(
        self,
        track: MelodicTrack,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        port_label: str | None,
        swing: SwingApplier,
        horizon: float = 4.0,
        mutation_engine: MutationEngine | None = None,
    ) -> None:
        self._track = track
        self._harmony = harmony
        self._queue = event_queue
        self._port_label = port_label
        self._swing = swing
        self._scheduler = BeatScheduler(horizon=horizon)
        self._mutation_engine = mutation_engine

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    @property
    def track(self) -> MelodicTrack:
        """Дорожка-источник движка."""
        return self._track

    @property
    def port_label(self) -> str | None:
        """Метка MIDI-порта событий; None — дорожка молчит."""
        return self._port_label

    @property
    def scheduler(self) -> BeatScheduler:
        """Планировщик событий дорожки (для тестов и интроспекции)."""
        return self._scheduler

    def set_port_label(self, label: str | None) -> str | None:
        """Сменить порт событий дорожки (рантайм, thread-safe по GIL).

        Аргументы:
            label: Новая метка порта; None — отключить (тишина).

        Returns:
            Предыдущая метка (вызывающий шлёт all_notes_off на неё).
        """
        old = self._port_label
        self._port_label = label
        return old

    def tick(self, current_beat: float) -> int:
        """Один тик мелодического движка.

        1. Инициализация знака (первый тик).
        2. Достроение горизонта: события на ``[watermark, now + H)``.
        3. Доставка всех событий, чей beat наступил.

        Аргументы:
            current_beat: Текущая позиция в тактах.

        Returns:
            Количество событий, положенных в очередь на этой тике.
        """
        if self._port_label is None:
            return 0
        self._scheduler.ensure(current_beat)
        self._extend_horizon(current_beat)
        count = 0
        for event in self._scheduler.due(current_beat):
            self._enqueue(event)
            count += 1
        return count

    def reset(self) -> None:
        """Сброс планировщика (STOP транспорта).

        Очищает pending-события и водяной знак: после остановки не
        доставляется запланированное «прошлое».
        """
        self._scheduler.reset()

    def all_notes_off(self) -> None:
        """Panic: остановить все ноты этой дорожки."""
        if self._port_label is None:
            return
        self._scheduler.reset()
        self._enqueue(TransportEvent.all_notes_off(port_label=self._port_label))
        log.info("MelodicEngine %s: all notes off", self._track.name)

    # ------------------------------------------------------------------
    # Планирование
    # ------------------------------------------------------------------

    def _extend_horizon(self, current_beat: float) -> None:
        """Достроить расписание до ``current_beat + horizon``.

        Каждая итерация строит одно окно шириной H (при скачке позиции —
        несколько окон подряд).
        """
        target = current_beat + self._scheduler.horizon
        while self._scheduler.watermark < target - 1e-9:
            start = self._scheduler.watermark
            end = start + self._scheduler.horizon
            for event in self._build_window(start, end):
                self._scheduler.schedule(event)
            self._scheduler.advance(end)

    def _build_window(self, start: float, end: float) -> list[TransportEvent]:
        """Построить TransportEvent на окно [start, end) из паттерна.

        Паттерн (относительные beats) циклически повторяется с периодом
        ``pattern_length_for(ctx)``: абсолютный beat = относительный +
        k * period. Каждая нота даёт пару note_on (beat) / note_off
        (beat + длительность).

        Аргументы:
            start: Начало окна (beats, включительно).
            end: Конец окна (beats, исключительно).

        Returns:
            Список TransportEvent с абсолютными beats.
        """
        notes, pattern_len = self._pattern()
        if not notes or pattern_len <= 0:
            return []

        events: list[TransportEvent] = []
        # Обход по циклам (k снаружи) — abs beats неубывают; свинг
        # (stateful SwingApplier) получает позиции в музыкальном порядке.
        k = max(0, math.floor(start / pattern_len))
        while k * pattern_len < end - 1e-9:
            for note in notes:
                abs_beat = note.beat + k * pattern_len
                if start - 1e-9 <= abs_beat < end:
                    events.extend(self._note_to_events(note, abs_beat))
            k += 1
        return events

    def _pattern(self) -> tuple[list[NoteEvent], float]:
        """Ноты паттерна и его период через генераторы (C6).

        Окно аккордов — outbox дорожки, наполненный фазой
        ``Session.propagate_chords()`` перед тиками движков. Механизмы
        мутации — из MutationEngine (если подключён); без него дорожка
        играет базовый материал.
        """
        me = self._mutation_engine
        name = self._track.name
        ctx = GenerationContext(
            track=self._track,
            chord_window=tuple(self._track.outbox),
            note_drift=me.get_note_drift(name) if me else None,
            euclidean=me.get_euclidean_drift(name) if me else None,
            param_drift=me.get_param_drift(name) if me else None,
        )
        return generate_notes(ctx), pattern_length_for(ctx)

    def _note_to_events(self, note: NoteEvent, abs_beat: float) -> list[TransportEvent]:
        """NoteEvent → пара TransportEvent (note_on + note_off).

        Ступень резолвится в MIDI-номер через Harmony (октава дорожки +
        ``note.octave_offset`` — дрейф регистра); свинг применяется к
        длительности относительно абсолютного beat (парность шагов свинга
        следует музыкальной позиции, а не моменту доставки). Гейт уже
        применён генератором — здесь только свинг.

        Аргументы:
            note: Нота (ступень, звучащая длительность).
            abs_beat: Абсолютный beat на таймлайне.

        Returns:
            [note_on, note_off] с абсолютными beats.
        """
        midi_note = self._harmony.degree_to_note(
            note.degree, self._track.octave + note.octave_offset
        )
        duration = note.duration
        if self._swing.amount > 0.0:
            duration = self._swing.apply_duration(base=duration, beat=abs_beat)
        duration = max(duration, 0.0)

        return [
            TransportEvent.note_on(
                port_label=self._port_label or "default",
                channel=self._track.channel,
                note=midi_note,
                velocity=note.velocity,
                duration=duration,
                beat=abs_beat,
            ),
            TransportEvent.note_off(
                port_label=self._port_label or "default",
                channel=self._track.channel,
                note=midi_note,
                beat=abs_beat + duration,
            ),
        ]

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _enqueue(self, event: TransportEvent) -> None:
        """Положить событие в очередь, drop-oldest при переполнении."""
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(event)
            except queue.Empty:
                try:
                    self._queue.put_nowait(event)
                except queue.Full:
                    log.warning(
                        "MelodicEngine %s: queue full, event lost",
                        self._track.name,
                    )

    def __repr__(self) -> str:
        return f"MelodicEngine(track={self._track.name!r}, port={self._port_label!r})"
