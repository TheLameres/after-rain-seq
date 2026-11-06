"""Приём внешнего MIDI Clock и транспорта (Start / Continue / Stop / Song Position).

Внешнее устройство присылает 24 импульса на четверть ноты. Таймлайн работает
с ``ticks_per_beat`` тиками на бит, поэтому каждый импульс превращается в
``ticks_per_beat // 24`` тиков. Без этого воспроизведение шло бы в 20 раз
медленнее внешних часов.

- **Start** (0xFA) — перезапуск с нуля и приём импульсов;
- **Continue** (0xFB) — приём импульсов с текущей позиции;
- **Stop** (0xFC) — импульсы игнорируются, звук гасится;
- **Song Position** (0xF2) — только позиция 0 (перезапуск по позиции).

Внутренние часы таймлайна не запускаются: тики дают только импульсы клока.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Protocol

import mido

log = logging.getLogger(__name__)

MIDI_PPQ: int = 24
"""Импульсов MIDI Clock на четверть ноты (стандарт MIDI)."""

_TEMPO_GAP_RESET: float = 0.5
"""Пауза между импульсами (с), после которой оценка темпа начинается заново."""


class ClockSink(Protocol):
    """Куда направляется транспорт: :class:`TickProxy`."""

    def tick(self) -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def reset(self) -> None: ...


class MidiClockInput:
    """MIDI-вход, управляющий таймлайном по внешним часам.

    Args:
        sink: Получатель тиков и транспорта (обычно TickProxy).
        device_name: Имя системного MIDI-входа.
        ticks_per_beat: Тиков таймлайна на бит (должно делиться на 24).
    """

    def __init__(self, sink: ClockSink, device_name: str, ticks_per_beat: int) -> None:
        if ticks_per_beat % MIDI_PPQ:
            raise ValueError(
                f"ticks_per_beat={ticks_per_beat} должно делиться на {MIDI_PPQ}"
            )
        self._sink = sink
        self._device_name = device_name
        self._ticks_per_pulse = ticks_per_beat // MIDI_PPQ
        self._port: Any = None
        self._running = False
        self._last_pulse: float | None = None
        self._tempo: float | None = None
        self._lock = threading.Lock()

    @property
    def tempo(self) -> float | None:
        """Оценка темпа по импульсам внешнего клока (BPM) или ``None``."""
        return self._tempo

    @property
    def running(self) -> bool:
        """True между Start/Continue и Stop."""
        return self._running

    def background(self) -> None:
        """Открыть вход; дальше сообщения приходят из потока mido."""
        if self._port is not None:
            return
        try:
            self._port = mido.open_input(self._device_name, callback=self._on_message)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError(
                f"Cannot open MIDI clock input {self._device_name!r}: {exc}"
            ) from exc
        log.info("MIDI clock input открыт: %s", self._device_name)

    def stop(self) -> None:
        """Закрыть вход. Если транспорт шёл по внешнему клоку, остановить его."""
        with self._lock:
            was_running = self._running
            self._running = False
            port, self._port = self._port, None
        if port is not None:
            port.close()
        if was_running:
            self._sink.stop()

    def _on_message(self, msg: mido.Message) -> None:
        if msg.type == "clock":
            self._on_pulse()
        elif msg.type == "start":
            with self._lock:
                self._running = True
            self._sink.start()
        elif msg.type == "continue":
            with self._lock:
                self._running = True
        elif msg.type == "stop":
            with self._lock:
                was_running = self._running
                self._running = False
            if was_running:
                self._sink.stop()
        elif msg.type == "songpos":
            if msg.pos == 0:
                self._sink.reset()
            else:
                log.warning(
                    "MIDI Song Position %d не поддерживается (только 0)", msg.pos
                )

    def _on_pulse(self) -> None:
        now = time.monotonic()
        if self._last_pulse is not None:
            dt = now - self._last_pulse
            if 0 < dt <= _TEMPO_GAP_RESET:
                estimate = 60.0 / (MIDI_PPQ * dt)
                self._tempo = (
                    estimate
                    if self._tempo is None
                    else 0.9 * self._tempo + 0.1 * estimate
                )
        self._last_pulse = now
        if not self._running:
            return
        for _ in range(self._ticks_per_pulse):
            self._sink.tick()
