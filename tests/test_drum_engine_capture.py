"""Сквозной тест: DrumEngine → Transport → CaptureRecorder (задача 3.5).

Программный аналог ручного разбора `spike_midi_dump.py --drum-dub`:
прогон 2 циклов drum-дорожки с паттернами examples/drum_dub.py через
реальный Transport с CaptureRecorder. В capture нет дублей одной ноты
на одном бите, каждому note_on соответствует note_off на +0.25 бита,
позиции шагов совпадают с эталоном drum_dub (kick 0/3/4/7, snare 4/12,
closedhat чётные, shaker 0/6/12, conga 6/14 — шаги в цикле 16).
"""

from __future__ import annotations

import queue
from unittest.mock import MagicMock

import pytest

from src.session.drum.drum_engine import DrumEngine
from src.session.model.drum_track import DrumTrack
from src.sync.capture_recorder import CaptureRecorder
from src.sync.swing import SwingApplier, SwingConfig
from src.sync.transport import Transport
from src.sync.transport_event import EventKind, TransportEvent

PPQN = 480

# Эталон позиций (шаги в цикле 16): lane индексы GM_DRUM_MAP.
DUB_STEPS: dict[int, list[int]] = {
    0: [0, 3, 4, 7],  # kick: x..x|x..x|....|....
    2: [4, 12],  # snare: ....|X...|....|X... (акценты)
    6: list(range(0, 16, 2)),  # closedhat: восьмые
    13: [0, 6, 12],  # shaker: евклид (3,8)
    15: [6, 14],  # conga: евклид (2,8,3)
}


def _make_setup() -> tuple[DrumEngine, Transport, CaptureRecorder]:
    """DrumEngine + Transport с мок-реестром и CaptureRecorder."""
    registry = MagicMock()
    adapter = MagicMock()
    adapter.label = "Synth A"
    registry.get_output.return_value = adapter
    registry.all_outputs.return_value = [adapter]
    q: queue.Queue[TransportEvent] = queue.Queue(maxsize=4096)
    transport = Transport(
        event_queue=q,
        port_registry=registry,
        swing=SwingApplier(SwingConfig(amount=0.0)),
    )
    recorder = CaptureRecorder()
    transport.set_capture_sink(recorder)

    track = DrumTrack(name="Drums", steps=16)
    for lane_idx, steps in DUB_STEPS.items():
        value = 2 if lane_idx == 2 else 1
        for step in steps:
            track.lanes[lane_idx].pattern[step] = value
    engine = DrumEngine(
        drum_track=track,
        event_queue=q,
        port_label="Synth A",
    )
    return engine, transport, recorder


def test_capture_no_duplicates_and_pairs() -> None:
    """Регресс брифа: без дублей, пары note_on/note_off, эталонные позиции."""
    engine, transport, recorder = _make_setup()
    # 2 цикла по 4 бита: тики 0..8.0 (исключая 8.0 — удар цикла 3 не берём).
    for k in range(2 * 4 * PPQN):
        beat = k / PPQN
        engine.tick(beat, 120.0)
        transport.process_events(current_beat=beat)
    entries = recorder.entries()
    ons = [e for e in entries if e.kind is EventKind.NOTE_ON]
    offs = [e for e in entries if e.kind is EventKind.NOTE_OFF]

    # Нет дублей одной ноты на одном бите (регресс: 285 608 note_on).
    on_keys = [(e.note, round(e.beat, 9)) for e in ons]
    assert len(on_keys) == len(set(on_keys))

    # Эталонные позиции: шаг s цикла 16 → бит s * 0.25, цикл 2 = +4.0.
    expected_by_note: dict[int, list[float]] = {}
    for lane_idx, steps in DUB_STEPS.items():
        note = 36 + lane_idx
        rel = [s * 0.25 for s in steps]
        expected_by_note[note] = sorted(rel + [b + 4.0 for b in rel])
    for note, expected in expected_by_note.items():
        delivered = sorted(e.beat for e in ons if e.note == note)
        assert delivered == pytest.approx(expected), f"note {note}"

    # Парность: каждому note_on соответствует note_off на +0.25.
    off_keys = {(e.note, round(e.beat, 9)) for e in offs}
    for entry in ons:
        if entry.beat + 0.25 >= 8.0:
            continue  # off за пределами лупа
        assert (entry.note, round(entry.beat + 0.25, 9)) in off_keys, (
            f"нет note_off для {entry.note}@{entry.beat}"
        )

    # Канал drum-дорожки — 9 (GM ch10).
    assert all(e.channel == 9 for e in entries)


def test_capture_still_clean_after_pattern_change() -> None:
    """Правка паттерна на границе цикла: в capture нет дублей и после неё."""
    engine, transport, recorder = _make_setup()
    for k in range(4 * PPQN):  # цикл 1
        beat = k / PPQN
        engine.tick(beat, 120.0)
        transport.process_events(current_beat=beat)
    # Мутация на границе цикла (бит 4.0): кик теряет шаг 3 (бит 0.75).
    engine.track.lanes[0].pattern[3] = 0
    for k in range(4 * PPQN, 8 * PPQN):  # цикл 2
        beat = k / PPQN
        engine.tick(beat, 120.0)
        transport.process_events(current_beat=beat)
    entries = recorder.entries()
    ons = [e for e in entries if e.kind is EventKind.NOTE_ON]
    on_keys = [(e.note, round(e.beat, 9)) for e in ons]
    assert len(on_keys) == len(set(on_keys))
    # Кик: бит 0.75 есть в цикле 1, отсутствует в цикле 2 (4.75).
    kick_beats = sorted(e.beat for e in ons if e.note == 36)
    assert 0.75 in kick_beats
    assert 4.75 not in kick_beats
