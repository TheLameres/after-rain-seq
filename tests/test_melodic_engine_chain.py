"""Цепочка модификаций в MelodicEngine — применение и live-swap (блок 3 tasks).

White-box по образцу test_melodic_engine.py: pad-дорожка (chord_source),
degrees=[0] → один аккорд из 3 нот на beat 0, период паттерна 1.0 beat.
"""

from __future__ import annotations

import queue

import pytest

from src.harmony.harmony import Harmony
from src.session.engine.melodic_engine import MelodicEngine
from src.session.events.note_event import NoteEvent
from src.session.model.chord_math import chord_degrees_for
from src.session.model.melodic_track import MelodicTrack
from src.session.modify.arpeggiate import ArpeggiateStage
from src.session.modify.chain import Chain
from src.sync.transport_event import EventKind, TransportEvent


def _make_engine(
    chain: Chain[NoteEvent] | None = None,
) -> tuple[MelodicEngine, MelodicTrack, queue.Queue[TransportEvent], Harmony]:
    """Движок pad-дорожки с одним аккордом (degrees=[0]) и очередью."""
    track = MelodicTrack(
        name="Pad 1",
        profile_name="pad",
        channel=0,
        voicing="1-3-5",
        octave=5,
        gate=0.9,
        degrees=[0],
    )
    if chain is not None:
        track.chain = chain
    harmony = Harmony("A", "dorian")
    q: queue.Queue[TransportEvent] = queue.Queue(maxsize=4096)
    engine = MelodicEngine(track, harmony, q, "default")
    return engine, track, q, harmony


def _drain(q: queue.Queue[TransportEvent]) -> list[TransportEvent]:
    events: list[TransportEvent] = []
    while not q.empty():
        events.append(q.get_nowait())
    return events


def _ons(events: list[TransportEvent]) -> list[tuple[float, float, int]]:
    """(beat, duration, note) всех NOTE_ON в порядке доставки."""
    return [
        (ev.beat, ev.duration or 0.0, ev.note or 0)
        for ev in events
        if ev.kind is EventKind.NOTE_ON
    ]


class TestEmptyChainIdentity:
    def test_empty_chain_keeps_schedule(self) -> None:
        """Пустая цепочка (явно присвоенная) — расписание как у дефолтной."""
        eng_a, _ta, qa, _h = _make_engine()
        eng_b, tb, qb, _h2 = _make_engine()
        tb.chain = Chain()
        for now in (0.0, 1.0, 2.0, 3.0, 4.0):
            eng_a.tick(now)
            eng_b.tick(now)
        assert _ons(_drain(qa)) == _ons(_drain(qb))


class TestChainAppliedToPattern:
    def test_arpeggio_expands_chord(self) -> None:
        """Арпеджиатор в цепочке разворачивает аккорд паттерна в ноты."""
        eng, _track, q, _h = _make_engine(chain=Chain((ArpeggiateStage(step=0.25),)))
        for now in (0.0, 0.25, 0.5, 0.75):
            eng.tick(now)
        ons_in_first_beat = [
            (beat, duration) for beat, duration, _note in _ons(_drain(q)) if beat < 1.0
        ]
        assert ons_in_first_beat == [(0.0, 0.25), (0.25, 0.25), (0.5, 0.25)]

    def test_arpeggio_order_matches_reference_chord(self) -> None:
        """Порядок нот арпеджио = ступени аккорда по возрастанию.

        ``BeatScheduler.due(now)`` доставляет только ``beat <= now``, поэтому
        оба движка тикают до 0.75: арпеджио раскладывает аккорд на 0/0.25/0.5
        (семантика движка та же, что у зелёного сиблинга
        ``test_arpeggio_expands_chord``).
        """
        ref, _t0, q_ref, _h0 = _make_engine()
        for now in (0.0, 0.25, 0.5, 0.75):
            ref.tick(now)
        chord_pitches = sorted(note for _b, _d, note in _ons(_drain(q_ref)))

        eng, _t1, q, _h1 = _make_engine(chain=Chain((ArpeggiateStage(step=0.25),)))
        for now in (0.0, 0.25, 0.5, 0.75):
            eng.tick(now)
        arpeggio_pitches = [note for _b, _d, note in _ons(_drain(q))]
        assert arpeggio_pitches == chord_pitches

    def test_chord_outbox_untouched(self) -> None:
        """Chord outbox (граф гармонии) цепочкой не модифицируется."""
        eng, track, _q, _h = _make_engine(chain=Chain((ArpeggiateStage(step=0.25),)))
        track.generate()
        before = list(track.outbox)
        assert before, "pad публикует ChordEvent"
        eng.tick(0.0)
        eng.tick(1.0)
        assert track.outbox == before


class TestLiveSwap:
    def test_swap_rebuilds_from_now(self) -> None:
        """Замена подхватывается со следующего тика: ноты после now — новые."""
        eng, track, q, _h = _make_engine()
        eng.tick(0.0)
        eng.tick(1.0)
        track.chain = Chain((ArpeggiateStage(step=0.25),))
        eng.tick(1.0)
        # Доставленное до/на момент подмены не тронуто: пустая цепочка (dur 0.9).
        delivered = [(beat, dur) for beat, dur, _n in _ons(_drain(q))]
        assert (0.0, 0.9) in delivered
        assert (1.0, 0.9) in delivered
        # Пересобранная часть играет арпеджио: нота на 1.0 (dur 0.25).
        assert (1.0, 0.25) in delivered
        # Хвост пересборки (1.25, 1.5) и следующая граница (2.0) доигрываются
        # дотиками: интроспекция scheduler.pending заменена доставкой.
        eng.tick(1.25)
        eng.tick(1.5)
        eng.tick(2.0)
        tail = [(beat, dur) for beat, dur, _n in _ons(_drain(q))]
        assert any(beat == pytest.approx(1.25) for beat, _d in tail)
        assert any(
            beat == pytest.approx(2.0) and dur == pytest.approx(0.25)
            for beat, dur in tail
        )
        assert eng.scheduler.pending_count > 0

    def test_swap_does_not_bump_revision(self) -> None:
        eng, track, _q, _h = _make_engine()
        before = track.revision
        track.chain = Chain((ArpeggiateStage(),))
        eng.tick(0.0)
        assert track.revision == before

    def test_same_chain_object_no_rebuild(self) -> None:
        """Повторный tick с той же цепочкой — watermark продолжает расти."""
        eng, track, _q, _h = _make_engine()
        eng.tick(0.0)
        track.chain = Chain((ArpeggiateStage(step=0.25),))
        eng.tick(0.5)
        watermark_after_swap = eng.scheduler.watermark
        assert watermark_after_swap == pytest.approx(4.5)
        eng.tick(1.0)
        # Тот же объект цепочки: пересборки не было, знак не откатывался.
        assert eng.scheduler.watermark >= watermark_after_swap


class TestChainAndPendingTogether:
    def test_progression_at_boundary_chain_from_now(self) -> None:
        """Оба механизма в одном тике: прогрессия — с границы, цепочка — от now."""
        eng, track, q, harmony = _make_engine()
        eng.tick(0.0)
        _drain(q)  # аккорд цикла 0 доставлен; дальше проверяем только новое
        track.degrees = (5,)  # уходит в pending_degrees (B2)
        track.chain = Chain((ArpeggiateStage(step=0.25),))
        eng.tick(0.5)
        # Пересборка от now (design §3/§4: окно строится от watermark=now,
        # без квантизации): хвост арпеджио ТЕКУЩЕГО цикла — третья нота на
        # beat 0.5 — доставлен на этом же тике; новый аккорд (степень 5)
        # не звучит до границы ступени 1.0.
        mid = _ons(_drain(q))
        assert mid, "хвост арпеджио текущего цикла доставлен на тике подмены"
        assert all(beat < 1.0 for beat, _d, _n in mid)
        eng.tick(1.0)
        # Хвост арпеджио новой ступени (1.25, 1.5) доигрывается дотиками:
        # интроспекция scheduler.pending заменена доставкой.
        eng.tick(1.25)
        eng.tick(1.5)
        # Граница ступени 1.0: новый аккорд (степень 5), арпеджио по ступеням.
        chord = sorted(chord_degrees_for(track, 5))
        expected = [
            (1.0 + i * 0.25, harmony.degree_to_note(deg, 5))
            for i, deg in enumerate(chord)
        ]
        delivered = [(b, n) for b, _d, n in _ons(_drain(q))]
        assert (expected[0][0], expected[0][1]) in delivered
        assert (expected[1][0], expected[1][1]) in delivered
        assert (expected[2][0], expected[2][1]) in delivered
        assert eng.scheduler.pending_count > 0
