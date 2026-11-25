"""DrumEngine — мост между DrumTrack и транспортом.

Переведён на lookahead-планировщик (:class:`BeatScheduler`, fix-drum-engine-
scheduling): события доставляются **однократно, в свой абсолютный бит**, а не
пачкой на каждый тик:

1. ``ensure(now)`` — ленивая инициализация водяного знака.
2. Достроение окна: пока ``watermark < now + H``, паттерн циклится через
   ``steps / 4`` битов (``generate()`` вызывается не чаще одного раза на
   цикл); каждый удар даёт пару note_on/note_off.
3. Доставка: всё, чей beat наступил (``<= now + ε``), — в event_queue;
   Transport забирает сразу после хука.

Правки lane-паттернов и mute lane'ов детектятся сравнением снимка
(``track.snapshot()`` + mute-состояния) на каждом тике; при изменении
запланированные вперёд note_on снимаются и окно перестраивается.

Свинг здесь не применяется: он живёт в Transport (plan §4.2) и сдвигает
только onset NOTE_ON.
"""

from __future__ import annotations

import logging
import math
import queue

from src.session.engine.beat_scheduler import BeatScheduler
from src.session.events.drum_event import DrumEvent
from src.session.model.drum_track import DrumTrack
from src.sync.transport_event import TransportEvent

log = logging.getLogger(__name__)


class DrumEngine:
    """Движок drum-машины — планирование DrumEvent → TransportEvent.

    Аргументы:
        drum_track: Drum-дорожка-источник.
        event_queue: Очередь для TransportEvent (разделяется с Transport).
        port_label: Метка MIDI-порта для событий.
    """

    def __init__(
        self,
        drum_track: DrumTrack,
        event_queue: queue.Queue[TransportEvent],
        port_label: str | None,
    ) -> None:
        self._track = drum_track
        self._queue = event_queue
        self._port_label = port_label
        self._scheduler = BeatScheduler(horizon=4.0)
        # Детект правки паттерна (design §4): снимок lane-паттернов и
        # mute-состояний lane'ов. None — ещё не снимали (первый тик).
        self._fingerprint: (
            tuple[tuple[tuple[int, ...], ...], tuple[bool, ...]] | None
        ) = None
        # Цепочка модификаций (track-modify-chain): drum-дорожки цепочку
        # игнорируют, но непустая цепочка — неожиданное состояние модели
        # (защита для прямого присвоения; через фасад недостижимо), поэтому
        # предупреждение в лог — однократно на дорожку.
        self._chain_warned: bool = False

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    @property
    def track(self) -> DrumTrack:
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

    def tick(self, current_beat: float, bpm: float) -> int:
        """Один тик drum-движка.

        1. Детект правки паттерна (fingerprint) — при изменении снятие
           запланированных вперёд note_on и перестройка окна.
        2. Ранний выход при ``port_label is None`` (до ``ensure`` —
           планировщик не движется, как у melodic).
        3. Инициализация знака (первый тик).
        4. Достроение окна циклами до ``current_beat + horizon``.
        5. Доставка всех событий, чей beat наступил.

        Аргументы:
            current_beat: Текущая позиция в тактах.
            bpm: Текущий темп. Сегодня не используется в теле (наследие
                удалённой автономной мутации); сохранён ради сигнатуры
                хука TICK (design §6).

        Returns:
            Количество событий, положенных в очередь.
        """
        # Цепочка модификаций (track-modify-chain): drum-дорожки цепочку
        # игнорируют; непустая цепочка — предупреждение однократно на дорожку.
        if self._track.chain and not self._chain_warned:
            self._chain_warned = True
            log.warning(
                "DrumEngine %s: непустая цепочка модификаций игнорируется "
                "(drum-дорожки цепочку не поддерживают)",
                self._track.name,
            )
        self._detect_pattern_change(current_beat)
        if self._port_label is None:
            return 0
        self._scheduler.ensure(current_beat)
        self._extend_window(current_beat)
        # §4.6: mute дорожки не даёт звука, но окно и планировщик
        # продолжают идти — снятие mute возвращает дорожку в такт.
        if self._track.muted:
            return 0
        count = 0
        for event in self._scheduler.due(current_beat):
            self._enqueue(event)
            count += 1
        return count

    def reset(self) -> None:
        """Сброс планировщика (STOP/START транспорта).

        Очищает pending-события и водяной знак: после остановки не
        доставляется запланированное «прошлое», после START расписание
        отсчитывается заново.
        """
        self._scheduler.reset()

    def all_notes_off(self) -> None:
        """Panic: остановить все drum-ноты на этом порту."""
        if self._port_label is None:
            return
        self._scheduler.reset()
        self._enqueue(TransportEvent.all_notes_off(port_label=self._port_label))
        log.info("DrumEngine %s: all notes off", self._track.name)

    # ------------------------------------------------------------------
    # Планирование
    # ------------------------------------------------------------------

    def _detect_pattern_change(self, current_beat: float) -> None:
        """Детект правки lane-паттернов и mute lane'ов (design §4).

        Сравнение дешёвое: снимок ``track.snapshot()`` — кортеж кортежей
        16×steps int'ов. При изменении (и на первом тике — fingerprint
        не инициализирован) запланированные вперёд note_on снимаются
        (``cancel_from(current_beat)`` — включая удар ровно на текущем
        бите), watermark возвращается на текущий бит (``rewind_to``);
        достройка окна (``_extend_window``) на этом же тике вернёт удары
        нового паттерна ровно один раз — дубля на границе нет.

        Аргументы:
            current_beat: Текущая позиция таймлайна в beats.
        """
        fingerprint: tuple[tuple[tuple[int, ...], ...], tuple[bool, ...]] = (
            self._track.snapshot(),
            tuple(lane.muted for lane in self._track.lanes),
        )
        if self._fingerprint == fingerprint:
            return
        self._fingerprint = fingerprint
        self._scheduler.cancel_from(current_beat)
        self._scheduler.rewind_to(current_beat)
        log.debug(
            "DrumEngine %s: правка паттерна, окно перестроено с beat %.3f",
            self._track.name,
            current_beat,
        )

    def _extend_window(self, current_beat: float) -> None:
        """Достроить расписание циклами до ``current_beat + horizon``.

        Каждый проход планирует весь цикл паттерна, поэтому pending может
        превышать ``now + horizon`` вплоть до границы цикла (design §2).
        ``generate()`` вызывается не чаще одного раза на цикл: outbox
        дорожки обновляется раз на цикл вместо каждого тика.

        Аргументы:
            current_beat: Текущая позиция таймлайна в beats.
        """
        cycle_len = self._track.steps / 4.0
        if cycle_len <= 0:
            return
        target = current_beat + self._scheduler.horizon
        while self._scheduler.watermark < target - 1e-9:
            k = math.floor(self._scheduler.watermark / cycle_len)
            cycle_start = k * cycle_len
            for ev in self._track.generate():
                abs_beat = cycle_start + ev.beat
                # Фильтр окна: первый тик после ensure (и ребилд с середины
                # цикла) не планирует удары в прошлом.
                if abs_beat >= self._scheduler.watermark - 1e-9:
                    for event in self._event_pair(ev, abs_beat):
                        self._scheduler.schedule(event)
            self._scheduler.advance(cycle_start + cycle_len)

    def _event_pair(self, ev: DrumEvent, abs_beat: float) -> list[TransportEvent]:
        """DrumEvent → пара TransportEvent (note_on + note_off).

        Note_off планируется на ``abs_beat + ev.duration``
        (DEFAULT_GATE = 0.25) — capture/SMF получают парные события,
        синтезатор не держит ноты. Свинг здесь не применяется: он живёт
        в Transport (plan §4.2), на моменте отправки в порт.

        Аргументы:
            ev: Drum-событие (относительный beat не используется —
                абсолютный передан отдельно).
            abs_beat: Абсолютный beat удара на таймлайне.

        Returns:
            [note_on, note_off] с абсолютными beats.
        """
        port = self._port_label or "default"
        return [
            TransportEvent.note_on(
                port_label=port,
                channel=self._track.channel,
                note=ev.note,
                velocity=ev.velocity,
                duration=ev.duration,
                beat=abs_beat,
            ),
            TransportEvent.note_off(
                port_label=port,
                channel=self._track.channel,
                note=ev.note,
                beat=abs_beat + ev.duration,
            ),
        ]

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
                        "DrumEngine %s: queue full, event lost",
                        self._track.name,
                    )

    def __repr__(self) -> str:
        return f"DrumEngine(track={self._track.name!r}, port={self._port_label!r})"
