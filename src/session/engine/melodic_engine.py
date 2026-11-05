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
from src.session.model.pattern_spec import FAMILY_CHORD_SOURCE, FAMILY_FREE_MONO
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
        horizon: Горизонт планирования в beats (по умолчанию 1 такт).
    """

    def __init__(
        self,
        track: MelodicTrack,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        port_label: str | None,
        horizon: float = 4.0,
        mutation_engine: MutationEngine | None = None,
    ) -> None:
        self._track = track
        self._harmony = harmony
        self._queue = event_queue
        self._port_label = port_label
        self._scheduler = BeatScheduler(horizon=horizon)
        self._mutation_engine = mutation_engine
        # B2: фаза паттерна и сетки ступеней. Сдвигается только при применении
        # отложенной прогрессии (на границе ступени).
        self._origin: float = 0.0

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
        # B2: движок ещё не играет — правка применяется сразу, с текущей точки.
        if not self._scheduler.initialized and self._track.pending_degrees is not None:
            self._commit_pending(current_beat, move_origin=True)
        if self._port_label is None:
            return 0
        self._scheduler.ensure(current_beat)
        if self._track.pending_degrees is not None:
            self._apply_pending_at(current_beat)
        self._extend_horizon(current_beat)
        # §4.6: mute дорожки не даёт звука, но горизонт и планировщик
        # продолжают идти — снятие mute возвращает дорожку в такт.
        if self._track.muted:
            return 0
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
            pos = start
            while pos < end - 1e-9:
                # B2: окно режется по границе текущей ступени. Всё до границы
                # строится по старой прогрессии, после — по новой.
                cut = end
                boundary: float | None = None
                if self._track.pending_degrees is not None:
                    boundary = self._next_boundary(pos)
                    cut = min(max(boundary, pos), end)
                for event in self._build_window(pos, cut):
                    self._scheduler.schedule(event)
                if boundary is not None and boundary <= cut + 1e-9:
                    self._commit_pending(cut, move_origin=self._step_len() is not None)
                pos = cut
            self._scheduler.advance(end)

    def _apply_pending_at(self, now: float) -> None:
        """Подготовить применение отложенной прогрессии после текущей ступени (B2).

        Граница — первая граница ступени строго после ``now``. Ноты, уже
        запланированные вперёд с этой границы (лукахед), снимаются и строятся
        заново по новой прогрессии; звучащие ноты доигрывают.
        """
        step = self._step_len()
        if step is None:
            # Ступеней нет (slicer и т. п.): прогрессия на звук не влияет.
            self._commit_pending(now, move_origin=False)
            return
        index = math.floor((now - self._origin) / step + 1e-9)
        boundary = self._origin + (index + 1) * step
        cancelled = self._scheduler.cancel_from(boundary)
        if self._scheduler.watermark > boundary + 1e-9:
            self._scheduler.rewind_to(boundary)
        log.debug(
            "MelodicEngine %s: правка ступеней ждёт границы %.3f (снято %d событий)",
            self._track.name,
            boundary,
            cancelled,
        )

    def _step_len(self) -> float | None:
        """Длительность одной ступени в beats; ``None`` — ступени не используются.

        Для chord_source (pad, atmos) и free_mono (bass, lead, texture) ступень
        занимает ``change_every`` beats. Остальные семьи прогрессию не читают.
        """
        spec = self._track.profile.pattern
        if spec.family in (FAMILY_CHORD_SOURCE, FAMILY_FREE_MONO):
            return float(spec.change_every)
        return None

    def _next_boundary(self, pos: float) -> float:
        """Первая граница ступени не раньше ``pos``."""
        step = self._step_len()
        if step is None:
            return pos
        j = math.ceil((pos - self._origin) / step - 1e-9)
        return self._origin + max(j, 0) * step

    def _commit_pending(self, at: float, move_origin: bool) -> None:
        """Применить отложенную прогрессию трека с момента ``at`` (B2).

        Args:
            at: Граница, с которой новая прогрессия начинает играть.
            move_origin: Переставить фазу паттерна на ``at`` (для ступенчатых семей).
        """
        if not self._track.commit_pending_degrees():
            return
        if move_origin:
            self._origin = at
        log.info(
            "MelodicEngine %s: прогрессия применена с beat %.3f", self._track.name, at
        )
        if self._mutation_engine is not None:
            # Ресинк сразу, а не на следующем тике: окна до границы уже построены.
            self._mutation_engine.refresh_track(self._track.name)

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
        # без состояния: чётность берётся из abs_beat (§4.2).
        k = max(0, math.floor((start - self._origin) / pattern_len))
        while self._origin + k * pattern_len < end - 1e-9:
            for note in notes:
                abs_beat = self._origin + note.beat + k * pattern_len
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
        ``note.octave_offset`` — дрейф регистра). Гейт уже применён
        генератором; свинг намеренно оставлен Transport (plan §4.2), чтобы
        применялся ровно в одном месте — на отправке в порт.

        Аргументы:
            note: Нота (ступень, звучащая длительность).
            abs_beat: Абсолютный beat на таймлайне.

        Returns:
            [note_on, note_off] с абсолютными beats.
        """
        midi_note = self._harmony.degree_to_note(
            note.degree, self._track.octave + note.octave_offset
        )
        # Свинг здесь не применяется: он живёт в Transport (plan §4.2),
        # на моменте отправки в порт. Движок отдаёт чистую музыкальную позицию.
        duration = max(note.duration, 0.0)

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
