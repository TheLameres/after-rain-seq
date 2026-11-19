"""Tests for SmfWriter — round-trip через mido (tasks add-capture-smf 2.2)."""

from __future__ import annotations

from pathlib import Path

import mido
import pytest

from src.sync.capture_recorder import CaptureEntry
from src.sync.smf_writer import SmfWriter
from src.sync.transport_event import EventKind


def _entry(
    kind: EventKind,
    note: int,
    beat: float,
    channel: int = 0,
    velocity: int | None = None,
) -> CaptureEntry:
    """Сделать CaptureEntry с дефолтным каналом."""
    return CaptureEntry(
        kind=kind, channel=channel, note=note, velocity=velocity, beat=beat
    )


def _write(path: Path, entries: list[CaptureEntry], bpm: float = 120.0) -> None:
    """Записать файл дефолтным writer'ом."""
    SmfWriter().write(path, entries, bpm=bpm)


def _read(path: Path) -> mido.MidiFile:
    """Прочитать файл обратно."""
    return mido.MidiFile(path)


def _notes(mid: mido.MidiFile) -> list[mido.Message]:
    """Несистемные note-сообщения единственного трека."""
    return [msg for msg in mid.tracks[0] if msg.type in ("note_on", "note_off")]


def _absolute(mid: mido.MidiFile) -> list[tuple[int, mido.Message]]:
    """Абсолютные тики note-сообщений трека."""
    result: list[tuple[int, mido.Message]] = []
    tick = 0
    for msg in mid.tracks[0]:
        tick += msg.time
        if msg.type in ("note_on", "note_off"):
            result.append((tick, msg))
    return result


class TestHeader:
    """Метаданные файла: type 0, PPQ, tempo, размер."""

    def test_type0_ppq480(self, tmp_path: Path) -> None:
        path = tmp_path / "cap.mid"
        _write(path, [_entry(EventKind.NOTE_ON, 60, 0.0, velocity=100)])
        mid = _read(path)
        assert mid.type == 0
        assert mid.ticks_per_beat == 480

    def test_tempo_meta_matches_bpm(self, tmp_path: Path) -> None:
        path = tmp_path / "cap.mid"
        _write(path, [_entry(EventKind.NOTE_ON, 60, 0.0, velocity=100)], bpm=96.0)
        mid = _read(path)
        tempos = [msg.tempo for msg in mid.tracks[0] if msg.type == "set_tempo"]
        assert tempos == [mido.bpm2tempo(96.0)]

    def test_time_signature_4_4_and_track_name(self, tmp_path: Path) -> None:
        path = tmp_path / "cap.mid"
        _write(path, [])
        mid = _read(path)
        track = mid.tracks[0]
        names = [msg.name for msg in track if msg.type == "track_name"]
        assert names == ["after-rain-seq capture"]
        signatures = [
            (msg.numerator, msg.denominator)
            for msg in track
            if msg.type == "time_signature"
        ]
        assert signatures == [(4, 4)]

    def test_empty_entries_meta_only(self, tmp_path: Path) -> None:
        path = tmp_path / "cap.mid"
        _write(path, [])
        mid = _read(path)
        note_msgs = _notes(mid)
        assert note_msgs == []
        # меты присутствуют
        types = {msg.type for msg in mid.tracks[0]}
        assert {"track_name", "set_tempo", "time_signature"} <= types


class TestNotesAndTiming:
    """Позиции, каналы, форма note_off."""

    def test_positions_and_channels_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "cap.mid"
        entries = [
            _entry(EventKind.NOTE_ON, 36, 0.0, channel=9, velocity=120),
            _entry(EventKind.NOTE_OFF, 36, 0.25, channel=9),
            _entry(EventKind.NOTE_ON, 60, 1.0, channel=0, velocity=90),
            _entry(EventKind.NOTE_OFF, 60, 2.0, channel=0),
        ]
        _write(path, entries)
        absolute = _absolute(_read(path))
        assert [(tick, msg.type, msg.channel, msg.note) for tick, msg in absolute] == [
            (0, "note_on", 9, 36),
            (120, "note_off", 9, 36),
            (480, "note_on", 0, 60),
            (960, "note_off", 0, 60),
        ]

    def test_note_off_is_real_0x80(self, tmp_path: Path) -> None:
        path = tmp_path / "cap.mid"
        _write(
            path,
            [
                _entry(EventKind.NOTE_ON, 60, 0.0, velocity=100),
                _entry(EventKind.NOTE_OFF, 60, 1.0),
            ],
        )
        msgs = _notes(_read(path))
        assert msgs[1].type == "note_off"
        assert msgs[1].velocity == 0

    def test_unordered_input_sorted_no_negative_deltas(self, tmp_path: Path) -> None:
        path = tmp_path / "cap.mid"
        entries = [
            _entry(EventKind.NOTE_OFF, 60, 2.0),
            _entry(EventKind.NOTE_ON, 48, 0.5, velocity=80),
            _entry(EventKind.NOTE_ON, 60, 0.0, velocity=100),
            _entry(EventKind.NOTE_OFF, 48, 0.75),
        ]
        _write(path, entries)
        mid = _read(path)
        absolute = _absolute(mid)
        ticks = [tick for tick, _ in absolute]
        assert ticks == sorted(ticks)
        # порядок доставки при равных (тик, вид) сохранён — вход
        # уже уникален по (тик, вид), поэтому просто проверяем содержимое
        assert [(msg.type, msg.note) for _, msg in absolute] == [
            ("note_on", 60),
            ("note_on", 48),
            ("note_off", 48),
            ("note_off", 60),
        ]
        # дельты неотрицательны по построению: пересчитаем напрямую
        deltas = [msg.time for msg in mid.tracks[0]]
        assert all(d >= 0 for d in deltas)

    def test_same_tick_and_kind_keeps_delivery_order(self, tmp_path: Path) -> None:
        path = tmp_path / "cap.mid"
        first = _entry(EventKind.NOTE_ON, 60, 1.0, velocity=100)
        second = _entry(EventKind.NOTE_ON, 64, 1.0, velocity=100)
        _write(path, [second, first])
        absolute = _absolute(_read(path))
        # при равных тике и виде — порядок доставки входного списка
        assert [(msg.note, msg.velocity) for _, msg in absolute] == [
            (64, 100),
            (60, 100),
        ]


class TestTieBreakOffBeforeOn:
    """Гейт 0.25 = 1/16: системная коллизия off/on на одном тике."""

    def test_delivery_order_off_first(self, tmp_path: Path) -> None:
        path = tmp_path / "cap.mid"
        entries = [
            _entry(EventKind.NOTE_ON, 36, 0.0, channel=9, velocity=120),
            _entry(EventKind.NOTE_OFF, 36, 0.25, channel=9),
            _entry(EventKind.NOTE_ON, 36, 0.25, channel=9, velocity=120),
            _entry(EventKind.NOTE_OFF, 36, 0.5, channel=9),
        ]
        _write(path, entries)
        absolute = _absolute(_read(path))
        assert [(msg.type, msg.note) for _, msg in absolute] == [
            ("note_on", 36),
            ("note_off", 36),  # off удара 1 раньше on удара 2
            ("note_on", 36),
            ("note_off", 36),
        ]

    def test_delivery_order_on_first_still_off_first(self, tmp_path: Path) -> None:
        """Независимо от порядка доставки: on удара 2 пришёл раньше off удара 1."""
        path = tmp_path / "cap.mid"
        entries = [
            _entry(EventKind.NOTE_ON, 36, 0.0, channel=9, velocity=120),
            _entry(EventKind.NOTE_ON, 36, 0.25, channel=9, velocity=120),
            _entry(EventKind.NOTE_OFF, 36, 0.5, channel=9),
            _entry(EventKind.NOTE_OFF, 36, 0.25, channel=9),
        ]
        _write(path, entries)
        absolute = _absolute(_read(path))
        assert [(msg.type, msg.note) for _, msg in absolute] == [
            ("note_on", 36),
            ("note_off", 36),  # off удара 1 (тик 120) раньше on удара 2
            ("note_on", 36),
            ("note_off", 36),
        ]
        # перекрытия одинаковых нот нет: off стоит сразу после пары on
        assert absolute[1][0] == absolute[2][0] == 120

    def test_same_tick_different_notes_order(self, tmp_path: Path) -> None:
        """Разные ноты на одном тике: off раньше on, внутри вида — доставка."""
        path = tmp_path / "cap.mid"
        entries = [
            _entry(EventKind.NOTE_ON, 38, 0.25, channel=9, velocity=100),
            _entry(EventKind.NOTE_ON, 42, 0.25, channel=9, velocity=90),
            _entry(EventKind.NOTE_OFF, 36, 0.25, channel=9),
        ]
        _write(path, entries)
        absolute = _absolute(_read(path))
        assert [(msg.type, msg.note) for _, msg in absolute] == [
            ("note_off", 36),
            ("note_on", 38),
            ("note_on", 42),
        ]


class TestExclusiveWrite:
    """Эксклюзивное создание и ошибки пути."""

    def test_existing_file_raises_file_exists(self, tmp_path: Path) -> None:
        path = tmp_path / "cap.mid"
        path.write_bytes(b"old")
        with pytest.raises(FileExistsError):
            _write(path, [])

    def test_missing_directory_raises_oserror(self, tmp_path: Path) -> None:
        path = tmp_path / "no_such_dir" / "cap.mid"
        with pytest.raises(OSError):
            _write(path, [])

    def test_existing_file_not_modified_on_error(self, tmp_path: Path) -> None:
        path = tmp_path / "cap.mid"
        path.write_bytes(b"old")
        with pytest.raises(FileExistsError):
            _write(path, [_entry(EventKind.NOTE_ON, 60, 0.0, velocity=100)])
        assert path.read_bytes() == b"old"
