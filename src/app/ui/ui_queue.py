"""Потокобезопасная очередь UI-событий: MIDI-поток → main loop.

Паттерн TickProxy (B1): MIDI-колбэк только кладёт событие (O(1), не
блокирует); drain и обработка — в main loop App. При переполнении —
drop oldest + ``log.warning`` (не молча).
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Iterator

from src.app.ui.ui_event import UiEvent

log = logging.getLogger(__name__)

_DEFAULT_CAPACITY = 64


class UiEventQueue:
    """Thread-safe FIFO для :class:`UiEvent` с лимитом на глубину.

    Parameters
    ----------
    capacity:
        Максимальное число необработанных событий. При переполнении
        самое старое событие выбрасывается с warning в лог.
    """

    def __init__(self, capacity: int = _DEFAULT_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity}")
        self._capacity = capacity
        self._items: deque[UiEvent] = deque()
        self._lock = threading.Lock()
        self.dropped = 0
        """Счётчик выброшенных при переполнении событий (для тестов/метрик)."""

    def put(self, event: UiEvent) -> None:
        """Положить событие в очередь (поток MIDI-колбэка).

        Без переполнения — строгий FIFO. При переполнении:

        * кнопочное событие коалесцируется по имени: более раннее событие
          той же кнопки удаляется, новое встаёт в конец (последнее состояние
          побеждает; отпускание Shift не может потеряться);
        * иначе выбрасывается самый старый энкодерный шаг; кнопочные события
          не выбрасываются, потому что потерянное отпускание Shift оставляет
          модификатор залипшим (Left/Right листают по 8 дорожек).
        """
        with self._lock:
            if len(self._items) < self._capacity:
                self._items.append(event)
                return
            self.dropped += 1
            if event.kind == "button":
                for i, queued in enumerate(self._items):
                    if queued.kind == "button" and queued.name == event.name:
                        del self._items[i]
                        log.warning(
                            "UiEventQueue overflow (%d pending) — coalesced button %s",
                            self._capacity,
                            event.name,
                        )
                        self._items.append(event)
                        return
            victim = next((i for i, e in enumerate(self._items) if e.kind == "encoder"), None)
            if victim is None:
                # Нет энкодеров — выбрасываем самую старую кнопку, но не Shift:
                # его отпускание удерживает модификатор.
                victim = next(
                    (i for i, e in enumerate(self._items) if e.name != "Shift"),
                    0,
                )
            dropped = self._items[victim]
            del self._items[victim]
            log.warning(
                "UiEventQueue overflow (%d pending) — dropped: %s",
                self._capacity,
                dropped,
            )
            self._items.append(event)

    def drain(self) -> Iterator[UiEvent]:
        """Забрать все накопленные события (main loop). Очередь пустеет."""
        with self._lock:
            items = list(self._items)
            self._items.clear()
        return iter(items)

    def __len__(self) -> int:
        """Число необработанных событий."""
        with self._lock:
            return len(self._items)
