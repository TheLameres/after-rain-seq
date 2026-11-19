"""Tests for CaptureRecorder — накопитель захвата (tasks add-capture-smf 1.2)."""

from __future__ import annotations

import threading

from src.sync.capture_recorder import CaptureEntry, CaptureRecorder
from src.sync.transport_event import EventKind


def _entry(note: int, beat: float, kind: EventKind = EventKind.NOTE_ON) -> CaptureEntry:
    """Тестовая запись."""
    velocity = 100 if kind is EventKind.NOTE_ON else None
    return CaptureEntry(kind=kind, channel=0, note=note, velocity=velocity, beat=beat)


class TestRecordAndSnapshot:
    def test_record_appends(self) -> None:
        recorder = CaptureRecorder()
        recorder.record(EventKind.NOTE_ON, 9, 36, 120, 0.0)
        recorder.record(EventKind.NOTE_OFF, 9, 36, None, 0.25)
        assert len(recorder) == 2
        entries = recorder.entries()
        assert entries[0].kind is EventKind.NOTE_ON
        assert entries[0].channel == 9
        assert entries[0].note == 36
        assert entries[0].velocity == 120
        assert entries[0].beat == 0.0
        assert entries[1].kind is EventKind.NOTE_OFF
        assert entries[1].velocity is None
        assert entries[1].beat == 0.25

    def test_snapshot_is_independent_copy(self) -> None:
        recorder = CaptureRecorder()
        recorder.record(EventKind.NOTE_ON, 0, 60, 100, 0.0)
        snapshot = recorder.entries()
        recorder.record(EventKind.NOTE_ON, 0, 62, 100, 1.0)
        assert len(snapshot) == 1
        assert len(recorder) == 2

    def test_snapshot_type(self) -> None:
        recorder = CaptureRecorder()
        recorder.record(EventKind.NOTE_ON, 0, 60, 100, 0.0)
        snapshot = recorder.entries()
        assert isinstance(snapshot, list)
        assert all(isinstance(e, CaptureEntry) for e in snapshot)

    def test_empty(self) -> None:
        recorder = CaptureRecorder()
        assert len(recorder) == 0
        assert recorder.entries() == []


class TestConcurrentRecord:
    def test_parallel_records_not_lost(self) -> None:
        """Smoke: record из двух потоков — события не теряются и не роняют."""
        recorder = CaptureRecorder()
        errors: list[Exception] = []

        def worker(note_base: int) -> None:
            try:
                for i in range(200):
                    recorder.record(EventKind.NOTE_ON, 0, note_base + i, 100, float(i))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(0,)),
            threading.Thread(target=worker, args=(100,)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10.0)
        assert errors == []
        assert len(recorder) == 400
        notes = sorted(entry.note for entry in recorder.entries())
        assert notes[0] == 0
        assert notes[-1] == 299
