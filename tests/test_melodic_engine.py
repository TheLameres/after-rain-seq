"""Тесты для MelodicEngine — мост MelodicTrack → Transport."""

from __future__ import annotations

import queue
import random

import pytest

from src.harmony.harmony import Harmony
from src.session.engine.melodic_engine import MelodicEngine
from src.session.model.melodic_track import MelodicTrack
from src.session.mutation.mutation_engine import MutationEngine
from src.session.session import Session
from src.sync.swing import SwingApplier, SwingConfig
from src.sync.transport_event import EventKind, TransportEvent


@pytest.fixture()
def harmony() -> Harmony:
    """Гармония по умолчанию (A dorian)."""
    return Harmony("A", "dorian")


@pytest.fixture()
def event_queue() -> queue.Queue[TransportEvent]:
    """Очередь событий."""
    return queue.Queue(maxsize=4096)


@pytest.fixture()
def no_swing() -> SwingApplier:
    """SwingApplier без свинга."""
    return SwingApplier(SwingConfig(amount=0.0))


@pytest.fixture()
def pad_track() -> MelodicTrack:
    """Pad-дорожка с профилем pad."""
    return MelodicTrack(
        name="Pad 1",
        profile_name="pad",
        channel=0,
        voicing="1-3-5",
        octave=5,
        gate=0.9,
        degrees=[0, 3],
    )


class TestMelodicEngine:
    """Тесты для MelodicEngine."""

    def test_tick_empty_cc_only(
        self,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """tick() с cc_only профилем — 0 событий."""
        track = MelodicTrack(name="CC 1", profile_name="cc_filter", channel=0)
        engine = MelodicEngine(track, harmony, event_queue, "default", no_swing)
        count = engine.tick(0.0)
        assert count == 0
        assert event_queue.empty()

    def test_tick_generates_events(
        self,
        pad_track: MelodicTrack,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """tick() с pad-дорожкой — TransportEvent в очереди."""
        engine = MelodicEngine(pad_track, harmony, event_queue, "default", no_swing)
        count = engine.tick(0.0)
        assert count > 0
        assert not event_queue.empty()

    def test_degrees_resolve_to_midi_notes(
        self,
        pad_track: MelodicTrack,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """degrees резолвятся в правильные MIDI-ноты."""
        engine = MelodicEngine(pad_track, harmony, event_queue, "default", no_swing)
        engine.tick(0.0)

        events: list[TransportEvent] = []
        while not event_queue.empty():
            events.append(event_queue.get_nowait())

        # Все события — NOTE_ON
        assert all(ev.kind == EventKind.NOTE_ON for ev in events)
        # Все ноты в диапазоне MIDI
        assert all(0 <= ev.note <= 127 for ev in events if ev.note is not None)

    def test_gate_applied_to_duration(
        self,
        pad_track: MelodicTrack,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """gate применяется к длительности."""
        engine = MelodicEngine(pad_track, harmony, event_queue, "default", no_swing)
        engine.tick(0.0)

        events: list[TransportEvent] = []
        while not event_queue.empty():
            events.append(event_queue.get_nowait())

        # duration = ev.duration * gate = 1.0 * 0.9 = 0.9
        for ev in events:
            if ev.duration is not None:
                assert ev.duration == pytest.approx(0.9)

    def test_swing_applied(
        self,
        pad_track: MelodicTrack,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
    ) -> None:
        """Свинг применяется к длительностям."""
        swing = SwingApplier(SwingConfig(amount=0.5))
        engine = MelodicEngine(pad_track, harmony, event_queue, "default", swing)
        engine.tick(0.0)

        events: list[TransportEvent] = []
        while not event_queue.empty():
            events.append(event_queue.get_nowait())

        # При swing=0.5 длительности должны отличаться от базовых
        # (чётные шаги укорачиваются, нечётные удлиняются)
        durations = [ev.duration for ev in events if ev.duration is not None]
        assert len(durations) > 0
        # Не все длительности равны (свинг изменил некоторые)
        assert len(set(durations)) > 1

    def test_all_notes_off(
        self,
        pad_track: MelodicTrack,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """all_notes_off() шлёт ALL_NOTES_OFF."""
        engine = MelodicEngine(pad_track, harmony, event_queue, "default", no_swing)
        engine.all_notes_off()

        assert not event_queue.empty()
        ev = event_queue.get_nowait()
        assert ev.kind == EventKind.ALL_NOTES_OFF
        assert ev.port_label == "default"

    def test_port_label(
        self,
        pad_track: MelodicTrack,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """События несут правильный port_label."""
        engine = MelodicEngine(pad_track, harmony, event_queue, "synth_a", no_swing)
        engine.tick(0.0)

        ev = event_queue.get_nowait()
        assert ev.port_label == "synth_a"

    def test_channel(
        self,
        pad_track: MelodicTrack,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """События несут правильный channel."""
        pad_track.channel = 5
        engine = MelodicEngine(pad_track, harmony, event_queue, "default", no_swing)
        engine.tick(0.0)

        ev = event_queue.get_nowait()
        assert ev.channel == 5

    def test_queue_full_drop_oldest(
        self,
        pad_track: MelodicTrack,
        harmony: Harmony,
        no_swing: SwingApplier,
    ) -> None:
        """При переполнении очереди — drop-oldest."""
        small_queue: queue.Queue[TransportEvent] = queue.Queue(maxsize=2)
        engine = MelodicEngine(pad_track, harmony, small_queue, "default", no_swing)

        # Заполняем очередь
        small_queue.put_nowait(TransportEvent.all_notes_off(port_label="default"))
        small_queue.put_nowait(TransportEvent.all_notes_off(port_label="default"))

        # tick() должен drop-oldest, не блокироваться
        engine.tick(0.0)
        assert small_queue.qsize() == 2  # всё ещё полная, но не заблокирован

    def test_repr(
        self,
        pad_track: MelodicTrack,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """repr содержит имя дорожки."""
        engine = MelodicEngine(pad_track, harmony, event_queue, "default", no_swing)
        r = repr(engine)
        assert "Pad 1" in r


class TestPortRouting:
    """Тесты для смены порта в рантайме (track route/unroute)."""

    def test_set_port_label_returns_old(
        self,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
        pad_track: MelodicTrack,
    ) -> None:
        """set_port_label возвращает предыдущую метку."""
        engine = MelodicEngine(pad_track, harmony, event_queue, "main", no_swing)
        old = engine.set_port_label("aux")
        assert old == "main"
        assert engine.port_label == "aux"

    def test_tick_silent_when_no_port(
        self,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
        pad_track: MelodicTrack,
    ) -> None:
        """port_label=None — тишина: tick() ничего не генерирует."""
        engine = MelodicEngine(pad_track, harmony, event_queue, None, no_swing)
        count = engine.tick(0.0)
        assert count == 0
        assert event_queue.empty()

    def test_all_notes_off_noop_when_no_port(
        self,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
        pad_track: MelodicTrack,
    ) -> None:
        """all_notes_off без порта — no-op (нечего глушить)."""
        engine = MelodicEngine(pad_track, harmony, event_queue, None, no_swing)
        engine.all_notes_off()
        assert event_queue.empty()

    def test_all_notes_off_uses_current_label(
        self,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
        pad_track: MelodicTrack,
    ) -> None:
        """all_notes_off шлётся на текущий порт."""
        engine = MelodicEngine(pad_track, harmony, event_queue, "main", no_swing)
        engine.all_notes_off()
        events = []
        while not event_queue.empty():
            events.append(event_queue.get_nowait())
        assert len(events) == 1
        assert events[0].port_label == "main"


def _drain(q: queue.Queue[TransportEvent]) -> list[TransportEvent]:
    """Забрать все события из очереди."""
    events: list[TransportEvent] = []
    while not q.empty():
        events.append(q.get_nowait())
    return events


class TestBeatScheduling:
    """C6 шаг 1: события доставляются однократно, в свой бит."""

    def test_notes_delivered_exactly_once(
        self,
        pad_track: MelodicTrack,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """Каждая нота — ровно один раз: нет дублей на тик (R1)."""
        engine = MelodicEngine(pad_track, harmony, event_queue, "default", no_swing)
        on_beats: list[float] = []
        for k in range(9):  # тики 0.0 .. 4.0 шагом 0.5
            engine.tick(k * 0.5)
            for ev in _drain(event_queue):
                if ev.kind == EventKind.NOTE_ON:
                    on_beats.append(ev.beat)
        # beats 0..4 × триада 1-3-5 = 15 note_on, без повторов
        assert len(on_beats) == 15
        for b in (0.0, 1.0, 2.0, 3.0, 4.0):
            assert on_beats.count(b) == 3

    def test_note_off_pairs_with_on(
        self,
        pad_track: MelodicTrack,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """Каждому note_on соответствует note_off на beat + длительность."""
        engine = MelodicEngine(pad_track, harmony, event_queue, "default", no_swing)
        on_map: dict[float, list[int]] = {}
        off_map: dict[float, list[int]] = {}
        tick = 1.0 / 32.0  # как реальные тики (1/32 доли и чаще)
        for k in range(int(3.0 / tick) + 1):
            engine.tick(k * tick)
            for ev in _drain(event_queue):
                if ev.kind == EventKind.NOTE_ON:
                    on_map.setdefault(ev.beat, []).append(ev.note)
                elif ev.kind == EventKind.NOTE_OFF:
                    off_map.setdefault(ev.beat, []).append(ev.note)
        # ons на целых beats 0..3, offs на beat + 0.9 (gate 0.9)
        assert sorted(on_map) == [0.0, 1.0, 2.0, 3.0]
        assert sorted(off_map) == [0.9, 1.9, 2.9]
        for b in (0.0, 1.0, 2.0):
            assert sorted(off_map[b + 0.9]) == sorted(on_map[b])

    def test_pattern_repeats_each_cycle(
        self,
        pad_track: MelodicTrack,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """Паттерн цикличен: ноты на 0.0 == на 2.0, на 1.0 == на 3.0."""
        engine = MelodicEngine(pad_track, harmony, event_queue, "default", no_swing)
        on_map: dict[float, list[int]] = {}
        for k in range(7):  # тики 0.0 .. 3.0 шагом 0.5
            engine.tick(k * 0.5)
            for ev in _drain(event_queue):
                if ev.kind == EventKind.NOTE_ON:
                    on_map.setdefault(ev.beat, []).append(ev.note)
        assert sorted(on_map[0.0]) == sorted(on_map[2.0])
        assert sorted(on_map[1.0]) == sorted(on_map[3.0])
        # И аккорды разные: прогрессия [0, 3]
        assert sorted(on_map[0.0]) != sorted(on_map[1.0])

    def test_reset_clears_pending(
        self,
        pad_track: MelodicTrack,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """STOP/reset: запланированное «прошлое» не доставляется."""
        engine = MelodicEngine(pad_track, harmony, event_queue, "default", no_swing)
        engine.tick(0.0)  # расписано [0, 4)
        assert engine.scheduler.pending_count > 0
        _drain(event_queue)  # delivered-события не смешиваем с проверкой reset
        engine.reset()
        assert engine.scheduler.pending_count == 0
        assert not engine.scheduler.initialized
        count = engine.tick(1.0)  # свежий старт с 1.0
        events = _drain(event_queue)
        on_beats = [ev.beat for ev in events if ev.kind == EventKind.NOTE_ON]
        assert on_beats == [1.0, 1.0, 1.0]
        assert all(ev.kind != EventKind.NOTE_OFF for ev in events)
        assert count == 3

    def test_no_port_does_not_schedule(
        self,
        pad_track: MelodicTrack,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """port_label=None — планировщик не трогаем вообще."""
        engine = MelodicEngine(pad_track, harmony, event_queue, None, no_swing)
        assert engine.tick(0.0) == 0
        assert not engine.scheduler.initialized
        assert engine.scheduler.pending_count == 0

    def test_watermark_advances_with_horizon(
        self,
        pad_track: MelodicTrack,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """Watermark держится на now + horizon, достраивается по мере надобности."""
        engine = MelodicEngine(pad_track, harmony, event_queue, "default", no_swing)
        engine.tick(0.0)
        assert engine.scheduler.watermark == 4.0  # 0 + H
        engine.tick(1.0)
        assert engine.scheduler.watermark == 8.0  # 1 + H
        engine.tick(3.9)  # 3.9 + 4 = 7.9 < 8.0 — достраивать не нужно
        assert engine.scheduler.watermark == 8.0
        engine.tick(4.5)  # 4.5 + 4 = 8.5 > 8.0 — новое окно
        assert engine.scheduler.watermark == 12.0

    def test_cc_only_nothing_scheduled(
        self,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """cc_only-профиль — планировщик пуст."""
        track = MelodicTrack(name="CC 1", profile_name="cc_filter", channel=0)
        engine = MelodicEngine(track, harmony, event_queue, "default", no_swing)
        assert engine.tick(0.0) == 0
        assert engine.scheduler.pending_count == 0
        assert event_queue.empty()

    def test_reads_source_without_sources_silent(
        self,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """reads_source без источников (стратегия B) — тишина, не падение."""
        track = MelodicTrack(name="Sub 1", profile_name="sub", channel=1)
        engine = MelodicEngine(track, harmony, event_queue, "default", no_swing)
        assert engine.tick(0.0) == 0
        assert engine.scheduler.pending_count == 0
        assert event_queue.empty()


class TestGraphIntegration:
    """C6 шаг 3: движок играет материал из графа (propagate_chords)."""

    def _session_pad_seq(self) -> tuple[Session, MelodicTrack]:
        """Сессия Pad 1 → Seq 1 с выполненной фазой propagate."""
        session = Session()
        session.create_melodic_track(profile="pad", degrees=[0, 3])
        session.create_melodic_track(profile="seq", channel=1)
        session.set_sources("Seq 1", "Pad 1")
        session.propagate_chords()
        seq = session.get_track("Seq 1")
        assert isinstance(seq, MelodicTrack)
        return session, seq

    def test_seq_plays_pad_chords(
        self,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """seq нарезает ChordEvent Pad 1: ноты — ступени аккордов источника."""
        _, seq = self._session_pad_seq()
        engine = MelodicEngine(seq, harmony, event_queue, "default", no_swing)
        engine.tick(0.0)
        events = _drain(event_queue)
        ons = [ev for ev in events if ev.kind == EventKind.NOTE_ON]
        assert ons  # seq играет
        # Только ступени аккордов Pad 1: (0,2,4) и (3,5,7), октава 5
        chord_tones = {harmony.degree_to_note(d, 5) for d in (0, 2, 4, 3, 5, 7)}
        assert {ev.note for ev in ons} <= chord_tones
        assert all(ev.channel == 1 for ev in ons)

    def test_seq_silent_before_propagate(
        self,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """До propagate_chords outbox пуст — движок молчит (стратегия B)."""
        session = Session()
        session.create_melodic_track(profile="pad", degrees=[0, 3])
        session.create_melodic_track(profile="seq", channel=1)
        session.set_sources("Seq 1", "Pad 1")
        seq = session.get_track("Seq 1")
        assert isinstance(seq, MelodicTrack)
        engine = MelodicEngine(seq, harmony, event_queue, "default", no_swing)
        assert engine.tick(0.0) == 0
        assert event_queue.empty()

    def test_lost_source_goes_silent(
        self,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """Удаление источника: после propagate окно пустое — тишина."""
        session, seq = self._session_pad_seq()
        engine = MelodicEngine(seq, harmony, event_queue, "default", no_swing)
        session.remove_track("Pad 1")  # стратегия B: sources Seq 1 сброшены
        session.propagate_chords()
        assert engine.tick(0.0) == 0
        assert event_queue.empty()


class TestMutationIntegration:
    """C6 шаг 4: мутация влияет на звук (канал MutationEngine → генерация)."""

    def _mutate_now(self, me: MutationEngine, name: str) -> None:
        """Форсировать мутацию дорожки на её следующем mutation beat."""
        state = me.get_state(name)
        assert state is not None
        me.tick(state.next_mutation_beat)

    def test_lead_note_drift_changes_pattern(
        self,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """NoteDrift меняет ступени lead после мутации."""
        track = MelodicTrack(name="Lead 1", profile_name="lead", degrees=[0, 2, 4, 2])
        me = MutationEngine(rng=random.Random(1))
        me.register_track(
            track_name="Lead 1", profile_name="lead", degrees=[0, 2, 4, 2]
        )
        engine = MelodicEngine(
            track, harmony, event_queue, "default", no_swing, mutation_engine=me
        )
        before = [n.degree for n in engine._pattern()[0]]
        self._mutate_now(me, "Lead 1")
        after = [n.degree for n in engine._pattern()[0]]
        assert after != before

    def test_pad_param_drift_changes_pattern(
        self,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """ParamDrift меняет гейт/регистр pad после мутации."""
        track = MelodicTrack(name="Pad 1", profile_name="pad", degrees=[0, 3])
        me = MutationEngine(rng=random.Random(3))
        me.register_track(
            track_name="Pad 1", profile_name="pad", degrees=[0, 3], gate=0.9
        )
        engine = MelodicEngine(
            track, harmony, event_queue, "default", no_swing, mutation_engine=me
        )
        before = engine._pattern()[0]
        self._mutate_now(me, "Pad 1")
        after = engine._pattern()[0]
        # Гейт или регистр (октава) изменились
        assert [n.duration for n in after] != [n.duration for n in before] or [
            n.octave_offset for n in after
        ] != [n.octave_offset for n in before]

    def test_euclidean_drift_changes_seq(
        self,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """FloatingEuclidean меняет нарезку seq после мутации."""
        session = Session()
        session.create_melodic_track(profile="pad", degrees=[0, 3])
        session.create_melodic_track(profile="seq", channel=1)
        session.set_sources("Seq 1", "Pad 1")
        session.propagate_chords()
        seq = session.get_track("Seq 1")
        assert isinstance(seq, MelodicTrack)

        me = MutationEngine(rng=random.Random(5))
        me.register_track(
            track_name="Seq 1",
            profile_name="seq",
            euclidean_steps=16,
            euclidean_pulses=6,
        )
        engine = MelodicEngine(
            seq, harmony, event_queue, "default", no_swing, mutation_engine=me
        )
        before = engine._pattern()[0]
        self._mutate_now(me, "Seq 1")
        after = engine._pattern()[0]
        assert len(after) != len(before) or [n.beat for n in after] != [
            n.beat for n in before
        ]

    def test_freeze_stops_drift(
        self,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        no_swing: SwingApplier,
    ) -> None:
        """freeze: мутация остановлена — паттерн не меняется."""
        track = MelodicTrack(name="Lead 1", profile_name="lead", degrees=[0, 2, 4, 2])
        me = MutationEngine(rng=random.Random(1))
        me.register_track(
            track_name="Lead 1", profile_name="lead", degrees=[0, 2, 4, 2]
        )
        engine = MelodicEngine(
            track, harmony, event_queue, "default", no_swing, mutation_engine=me
        )
        me.freeze_all()
        before = [n.degree for n in engine._pattern()[0]]
        state = me.get_state("Lead 1")
        assert state is not None
        me.tick(state.next_mutation_beat)  # mutate=0 — мутации нет
        after = [n.degree for n in engine._pattern()[0]]
        assert after == before
