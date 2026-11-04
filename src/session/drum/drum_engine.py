"""DrumEngine — мост между DrumTrack и транспортом.

Берёт ``list[DrumEvent]`` от :meth:`DrumTrack.generate()`, конвертирует
в :class:`TransportEvent` и кладёт в очередь. Применяет свинг к
длительностям. Обрабатывает мутацию по времени.
"""

from __future__ import annotations

import logging
import queue

from src.session.events.drum_event import DrumEvent
from src.session.model.drum_track import DrumTrack
from src.sync.transport_event import TransportEvent

log = logging.getLogger(__name__)


class DrumEngine:
    """Движок drum-машины — конвертация DrumEvent в TransportEvent.

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

        1. Проверить мутацию (maybe_mutate).
        2. Сгенерировать события (generate).
        3. Конвертировать в TransportEvent, положить в очередь.

        Аргументы:
            current_beat: Текущая позиция в тактах.
            bpm: Текущий темп. Передаётся снаружи (от часов) и не хранится:
                дорожка пересчитывает по нему интервал мутации.

        Returns:
            Количество событий, положенных в очередь.
        """
        if self._port_label is None:
            return 0
        port = self._port_label
        # Мутация по времени.
        self._track.maybe_mutate(current_beat, bpm)

        # Генерация.
        events = self._track.generate()

        # §4.6: mute дорожки не даёт событий, но мутация и генерация идут.
        if self._track.muted:
            return 0

        # Конвертация и доставка.
        count = 0
        for ev in events:
            transport_ev = self._to_transport_event(ev, current_beat, port)
            self._enqueue(transport_ev)
            count += 1
        return count

    def all_notes_off(self) -> None:
        """Panic: остановить все drum-ноты на этом порту."""
        if self._port_label is None:
            return
        self._enqueue(TransportEvent.all_notes_off(port_label=self._port_label))
        log.info("DrumEngine %s: all notes off", self._track.name)

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _to_transport_event(
        self, ev: DrumEvent, current_beat: float, port: str
    ) -> TransportEvent:
        """Конвертировать DrumEvent в TransportEvent.

        Аргументы:
            ev: Drum-событие.
            current_beat: Текущий beat (для свинга).
            port: Метка порта (tick() гарантирует не-None).

        Returns:
            TransportEvent для транспорта.
        """
        # Свинг здесь не применяется: он живёт в Transport (plan §4.2),
        # на моменте отправки в порт.
        duration = ev.duration

        return TransportEvent.note_on(
            port_label=port,
            channel=self._track.channel,
            note=ev.note,
            velocity=ev.velocity,
            duration=duration,
            beat=ev.beat,
        )

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
