"""Исходящий MIDI Clock и транспорт (Start / Continue / Stop).

Когда приложение — мастер (внутренние часы или Link), оно шлёт во внешние
устройства System Real-Time сообщения:

- **Start** (0xFA) — запуск с нулевой позиции (первый Play, такт 1);
- **Continue** (0xFB) — возобновление с позиции остановки;
- **Stop** (0xFC) — остановка;
- **Clock** (0xF8) — 24 импульса на четверть ноты.

Импульсы считаются по позиции таймлайна в битах, а не по реальному времени:
поэтому они совпадают с нотами при любом темпе и при смене BPM.

Модуль не знает о портах и mido. Отправка передаётся функцией ``send`` —
это позволяет тестировать логику без железа.
"""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Callable, Iterable, Mapping
from typing import Protocol

from src.midi.abc import MidiMessage

log = logging.getLogger(__name__)

PPQ: int = 24
"""Импульсов MIDI Clock на четверть ноты (стандарт MIDI)."""

MAX_CATCHUP: int = 4 * PPQ
"""Больше стольких импульсов за один тик не досылаем: после провала тиков
(подвис, отладка) лучше пропустить такты, чем выплеснуть очередь."""

_EPS: float = 1e-6

SendFn = Callable[[MidiMessage], None]


class SupportsRealtime(Protocol):
    """Выход, который умеет слать real-time сообщения (``MidiPortOutput``)."""

    def send_realtime(self, msg: MidiMessage) -> None: ...


class MidiClockOutput:
    """Генератор исходящих Clock/Start/Continue/Stop.

    Args:
        send: Куда отправить сообщение (все нужные порты).
        is_master: Возвращает True, когда приложение ведёт тайминг
            (внутренние часы или Link). Во внешнем MIDI-режиме возвращает False:
            тогда часы приходят снаружи и свои мы не шлём.
    """

    def __init__(self, send: SendFn, is_master: Callable[[], bool]) -> None:
        self._send = send
        self._is_master = is_master
        self._lock = threading.Lock()
        self._running = False
        self._next_index = 0  # номер следующего импульса (в 1/24 бита)

    @property
    def running(self) -> bool:
        """True между Start/Continue и Stop."""
        return self._running

    def start(self, beat: float) -> None:
        """Запустить транспорт из позиции ``beat``.

        Отправляет Start (FA), если позиция — ноль, иначе Continue (FB).
        Импульсы начинаются с первой позиции не раньше ``beat``.
        """
        with self._lock:
            if not self._is_master():
                return
            msg = MidiMessage.start() if abs(beat) < _EPS else MidiMessage.continue_()
            self._running = True
            self._next_index = max(0, math.ceil(beat * PPQ - _EPS))
            self._send(msg)

    def stop(self) -> None:
        """Остановить транспорт: отправить Stop (FC), импульсы прекращаются."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            if self._is_master():
                self._send(MidiMessage.stop())

    def on_position(self, beat: float) -> int:
        """Отправить импульсы Clock, попавшие в интервал до ``beat``.

        Вызывается на каждом тике таймлайна. Возвращает число отправленных
        импульсов (для тестов и диагностики).
        """
        with self._lock:
            if not self._running or not self._is_master():
                return 0
            target = math.floor(beat * PPQ + _EPS)
            if target < self._next_index:
                return 0
            if target - self._next_index >= MAX_CATCHUP:
                log.warning(
                    "MIDI clock: пропущено %d импульсов после провала тиков",
                    target - self._next_index,
                )
                self._next_index = target - MAX_CATCHUP + 1
            sent = 0
            for _ in range(self._next_index, target + 1):
                self._send(MidiMessage.clock())
                sent += 1
            self._next_index = target + 1
            return sent


def make_clock_sender(
    outputs: Callable[[], Mapping[str, SupportsRealtime]] | None,
    labels: Iterable[str],
) -> SendFn:
    """Собрать функцию отправки для портов с ``clock: true``.

    Args:
        outputs: Возвращает открытые выходы по метке (``label -> port``, где
            у порта есть ``send_realtime``). Вызывается на каждую отправку,
            чтобы hot-plug учитывался без перезапуска.
        labels: Метки портов, которым шлём clock.

    Returns:
        Функция ``send(msg)``, которая раздаёт сообщение по этим портам.
        Порт, который сейчас не открыт, пропускается.
    """
    wanted = frozenset(labels)

    def send(msg: MidiMessage) -> None:
        if outputs is None or not wanted:
            return
        for label, port in outputs().items():
            if label in wanted:
                port.send_realtime(msg)

    return send
