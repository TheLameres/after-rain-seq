"""Тесты UiEventQueue: FIFO, потокобезопасность, переполнение."""

from __future__ import annotations

import logging
import threading

import pytest

from src.app.ui.ui_event import UiEvent
from src.app.ui.ui_queue import UiEventQueue


class TestPutDrain:
    def test_put_drain_fifo(self) -> None:
        q = UiEventQueue()
        q.put(UiEvent.button("Play", True))
        q.put(UiEvent.encoder("Track1 Encoder", 1))
        q.put(UiEvent.button("Play", False))

        drained = list(q.drain())

        assert [e.name for e in drained] == ["Play", "Track1 Encoder", "Play"]
        assert [e.value for e in drained] == [1, 1, 0]
        assert len(q) == 0

    def test_drain_empties_queue(self) -> None:
        q = UiEventQueue()
        q.put(UiEvent.button("Up", True))
        list(q.drain())
        assert list(q.drain()) == []

    def test_drain_empty_queue_yields_nothing(self) -> None:
        q = UiEventQueue()
        assert list(q.drain()) == []

    def test_capacity_must_be_positive(self) -> None:
        try:
            UiEventQueue(capacity=0)
        except ValueError:
            pass
        else:  # pragma: no cover - защита от регрессии
            raise AssertionError("expected ValueError for capacity=0")


class TestThreaded:
    def test_concurrent_puts_no_losses(self) -> None:
        n_threads = 4
        n_per_thread = 250
        # Ёмкость с запасом: здесь проверяем отсутствие потерь, переполнение —
        # отдельный тест.
        q = UiEventQueue(capacity=n_threads * n_per_thread + 16)

        def worker(tid: int) -> None:
            for i in range(n_per_thread):
                q.put(UiEvent.encoder("Track1 Encoder", tid * n_per_thread + i))

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        drained = list(q.drain())
        assert len(drained) == n_threads * n_per_thread
        # Порядок внутри одного потока сохранён: значения каждого потока
        # идут строго по возрастанию.
        by_thread: dict[int, list[int]] = {}
        for e in drained:
            tid, seq = divmod(e.value, n_per_thread)
            by_thread.setdefault(tid, []).append(seq)
        for tid in range(n_threads):
            assert by_thread[tid] == list(range(n_per_thread))


class TestOverflow:
    def test_overflow_drops_oldest_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        q = UiEventQueue(capacity=3)
        with caplog.at_level(logging.WARNING, logger="src.app.ui.ui_queue"):
            for i in range(5):
                q.put(UiEvent.button(f"B{i}", True))

        drained = list(q.drain())
        # Два старейших выброшены; остались B2..B4 в порядке FIFO.
        assert [e.name for e in drained] == ["B2", "B3", "B4"]
        assert q.dropped == 2
        assert any("overflow" in r.message for r in caplog.records)


class TestShiftCoalesce:
    """Overflow: отпускание Shift не теряется (залипший Shift ломал навигацию)."""

    def test_shift_release_survives_overflow(self) -> None:
        q = UiEventQueue(capacity=3)
        q.put(UiEvent.button("Shift", True))
        q.put(UiEvent.encoder("Track1 Encoder", 1))
        q.put(UiEvent.encoder("Track1 Encoder", 1))
        # Переполнение: отпускание Shift должно попасть в очередь.
        q.put(UiEvent.button("Shift", False))
        drained = list(q.drain())
        shift_states = [e.value for e in drained if e.name == "Shift"]
        # Последнее состояние Shift — отпущен; оно не потеряно и не залипло.
        assert shift_states[-1] == 0

    def test_button_coalesced_by_name_on_overflow(self) -> None:
        q = UiEventQueue(capacity=2)
        q.put(UiEvent.button("Play", True))
        q.put(UiEvent.encoder("Track1 Encoder", 1))
        q.put(UiEvent.button("Play", False))  # overflow: заменяет старый Play
        drained = list(q.drain())
        plays = [e.value for e in drained if e.name == "Play"]
        assert plays == [0]

    def test_fifo_preserved_without_overflow(self) -> None:
        q = UiEventQueue(capacity=8)
        q.put(UiEvent.button("Play", True))
        q.put(UiEvent.encoder("Track1 Encoder", 1))
        q.put(UiEvent.button("Play", False))
        assert [e.name for e in q.drain()] == ["Play", "Track1 Encoder", "Play"]
