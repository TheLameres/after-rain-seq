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
        """Положить событие в очередь (поток MIDI-колбэка)."""
        with self._lock:
            if len(self._items) >= self._capacity:
                dropped = self._items.popleft()
                self.dropped += 1
                log.warning(
                    "UiEventQueue overflow (%d pending) — dropped oldest: %s",
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
