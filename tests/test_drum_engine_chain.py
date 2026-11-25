"""DrumEngine игнорирует непустую цепочку — предупреждение однократно (3.5/3.6).

Через фасад drum-дорожка непустую цепочку не получает (design §8); тест
проверяет защиту для прямого присвоения в модель: ритм не меняется, в логе
ровно одно предупреждение на дорожку.
"""

from __future__ import annotations

import logging
import queue

import pytest

from src.session.drum.drum_engine import DrumEngine
from src.session.model.drum_track import DrumTrack
from src.session.modify.arpeggiate import ArpeggiateStage
from src.session.modify.chain import Chain
from src.sync.transport_event import EventKind, TransportEvent

GM_KICK = 36


def _make_engine(
    chain_empty: bool,
) -> tuple[DrumEngine, queue.Queue[TransportEvent], DrumTrack]:
    """DrumEngine с kick-паттерном; chain_empty → пустая цепочка."""
    dt = DrumTrack(name="Drum 1", steps=16)
    for step in (0, 3, 4, 7):
        dt.lanes[0].pattern[step] = 1
    if not chain_empty:
        dt.chain = Chain((ArpeggiateStage(),))
    q: queue.Queue[TransportEvent] = queue.Queue(maxsize=256)
    engine = DrumEngine(drum_track=dt, event_queue=q, port_label="Test Port")
    return engine, q, dt


def _drain(q: queue.Queue[TransportEvent]) -> list[tuple[float, int]]:
    """NOTE_ON как (beat, note) — ритм дорожки."""
    out: list[tuple[float, int]] = []
    while not q.empty():
        ev = q.get_nowait()
        if ev.kind is EventKind.NOTE_ON:
            out.append((ev.beat, ev.note or 0))
    return out


def _run_rhythm(
    engine: DrumEngine,
    q: queue.Queue[TransportEvent],
) -> list[tuple[float, int]]:
    """Прогнать тики по одному циклу (4 beats) и забрать NOTE_ON."""
    for beats in (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0):
        engine.tick(beats, 120.0)
    return _drain(q)


class TestDrumIgnoresChain:
    def test_rhythm_identical_to_empty_chain(self) -> None:
        """Непустая цепочка не меняет ритм: события как у пустой цепочки."""
        eng_ref, q_ref, _t_ref = _make_engine(chain_empty=True)
        eng_chain, q_chain, _t_chain = _make_engine(chain_empty=False)
        assert _run_rhythm(eng_ref, q_ref) == _run_rhythm(eng_chain, q_chain)


class TestSingleWarning:
    def test_warning_logged_once(self, caplog: pytest.LogCaptureFixture) -> None:
        eng, _q, _t = _make_engine(chain_empty=False)
        with caplog.at_level(logging.WARNING, logger="src.session.drum.drum_engine"):
            eng.tick(0.0, 120.0)
            eng.tick(1.0, 120.0)
            eng.tick(2.0, 120.0)
        records = [r for r in caplog.records if "цепочка" in r.message]
        assert len(records) == 1

    def test_empty_chain_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        eng, _q, _t = _make_engine(chain_empty=True)
        with caplog.at_level(logging.WARNING, logger="src.session.drum.drum_engine"):
            eng.tick(0.0, 120.0)
            eng.tick(1.0, 120.0)
        assert not [r for r in caplog.records if "цепочка" in r.message]
