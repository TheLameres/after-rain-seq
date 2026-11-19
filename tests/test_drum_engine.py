"""Tests for DrumEngine — мост между DrumTrack и транспортом.

Ревизия под lookahead-планировщик (fix-drum-engine-scheduling): события
доставляются однократно в свой абсолютный бит, парами note_on/note_off.
"""

import queue

import pytest

from src.session.drum.drum_engine import DrumEngine
from src.session.model.drum_track import DrumTrack
from src.sync.transport_event import EventKind, TransportEvent

GM_KICK = 36
GM_SNARE = 38
GM_CLOSED_HAT = 42
GM_SHAKER = 49
GM_CONGA = 51

# Эталон позиций examples/drum_dub.py: шаги в цикле 16 → rel-биты × 0.25
# (kick 0/3/4/7, snare 4/12, closedhat чётные, shaker 0/6/12, conga 6/14).
DUB_REFERENCE: dict[int, list[float]] = {
    GM_KICK: [0.0, 0.75, 1.0, 1.75],
    GM_SNARE: [1.0, 3.0],
    GM_CLOSED_HAT: [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
    GM_SHAKER: [0.0, 1.5, 3.0],
    GM_CONGA: [1.5, 3.5],
}


def _make_engine(
    steps: int = 16,
    maxsize: int = 256,
) -> tuple[DrumEngine, queue.Queue[TransportEvent], DrumTrack]:
    """Создать DrumEngine с тестовой очередью."""
    dt = DrumTrack(name="Drum 1", steps=steps)
    q: queue.Queue[TransportEvent] = queue.Queue(maxsize=maxsize)
    engine = DrumEngine(
        drum_track=dt,
        event_queue=q,
        port_label="Test Port",
    )
    return engine, q, dt


def _drain(q: queue.Queue[TransportEvent]) -> list[TransportEvent]:
    """Забрать все события из очереди."""
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    return events


def _set_steps(
    track: DrumTrack, lane_idx: int, steps: list[int], value: int = 1
) -> None:
    """Проставить удары в lane-паттерн."""
    for step in steps:
        track.lanes[lane_idx].pattern[step] = value


def _setup_dub_patterns(track: DrumTrack) -> None:
    """Паттерны как в examples/drum_dub.py (эталон позиций)."""
    _set_steps(track, 0, [0, 3, 4, 7])  # kick
    _set_steps(track, 2, [4, 12], value=2)  # snare (X = accent)
    _set_steps(track, 6, list(range(0, 16, 2)))  # closedhat восьмыми
    _set_steps(track, 13, [0, 6, 12])  # shaker (3,8)
    _set_steps(track, 15, [6, 14])  # conga (2,8,3)


def _run_tick_loop(
    engine: DrumEngine,
    q: queue.Queue[TransportEvent],
    beats: list[float],
) -> tuple[dict[float, list[int]], dict[float, list[int]]]:
    """Луп последовательных тиков с дренажом очереди после каждого тика.

    Возвращает (on_map, off_map): beat → список note.
    """
    on_map: dict[float, list[int]] = {}
    off_map: dict[float, list[int]] = {}
    for beat in beats:
        engine.tick(beat, 120.0)
        for ev in _drain(q):
            if ev.kind == EventKind.NOTE_ON:
                on_map.setdefault(ev.beat, []).append(ev.note)
            elif ev.kind == EventKind.NOTE_OFF:
                off_map.setdefault(ev.beat, []).append(ev.note)
    return on_map, off_map


def _note_beats(mapping: dict[float, list[int]], note: int) -> list[float]:
    """Биты, на которых звучала нота (в одном из on/off словарей)."""
    return sorted(beat for beat, notes in mapping.items() if note in notes)


# ---------------------------------------------------------------------------
# Базовая доставка (3.1)
# ---------------------------------------------------------------------------


def test_tick_empty_pattern():
    """Пустой паттерн → нет событий на любом тике."""
    engine, q, _ = _make_engine()
    assert engine.tick(current_beat=0.0, bpm=120.0) == 0
    assert q.empty()
    assert engine.tick(current_beat=1.0, bpm=120.0) == 0
    assert q.empty()


def test_tick_delivers_due_hits_only():
    """Один тик на бите 0 → только hits бита 0; off приходит на +0.25."""
    engine, q, dt = _make_engine()
    _set_steps(dt, 0, [0])  # kick на бите 0
    _set_steps(dt, 2, [4])  # snare на бите 1.0
    count = engine.tick(current_beat=0.0, bpm=120.0)
    events = _drain(q)
    # Доставлен только note_on kick (beat 0.0); snare ещё не наступил.
    assert count == 1
    assert len(events) == 1
    assert events[0].kind == EventKind.NOTE_ON
    assert events[0].beat == pytest.approx(0.0)
    # Бит 0.25: note_off kick (пара), note_on snare ещё нет.
    assert engine.tick(current_beat=0.25, bpm=120.0) == 1
    off = _drain(q)
    assert len(off) == 1
    assert off[0].kind == EventKind.NOTE_OFF
    assert off[0].beat == pytest.approx(0.25)
    # Бит 1.0: note_on snare.
    assert engine.tick(current_beat=1.0, bpm=120.0) == 1
    on = _drain(q)
    assert len(on) == 1
    assert on[0].kind == EventKind.NOTE_ON
    assert on[0].note == GM_SNARE


def test_pair_same_note_channel_port():
    """Пара note_on/note_off: тот же note/channel/port, off на +0.25."""
    engine, q, dt = _make_engine()
    dt.channel = 5
    _set_steps(dt, 0, [0])
    engine.tick(current_beat=0.0, bpm=120.0)
    on = _drain(q)
    assert len(on) == 1
    assert engine.tick(current_beat=0.25, bpm=120.0) == 1
    off = _drain(q)
    assert len(off) == 1
    assert on[0].note == off[0].note == GM_KICK
    assert on[0].channel == off[0].channel == 5
    assert on[0].port_label == off[0].port_label == "Test Port"
    assert off[0].beat == pytest.approx(on[0].beat + 0.25)


def test_tick_event_fields():
    """События содержат правильные note/velocity/channel."""
    engine, q, dt = _make_engine()
    _set_steps(dt, 0, [0], value=2)  # accent
    engine.tick(current_beat=0.0, bpm=120.0)
    events = _drain(q)
    assert len(events) == 1
    ev = events[0]
    assert ev.note == GM_KICK
    assert 120 <= ev.velocity <= 127  # accent
    assert ev.channel == 9  # default ch10


def test_tick_respects_channel():
    """События идут на channel дорожки."""
    engine, q, dt = _make_engine()
    dt.channel = 5
    _set_steps(dt, 0, [0])
    engine.tick(current_beat=0.0, bpm=120.0)
    events = _drain(q)
    assert events[0].channel == 5


def test_tick_does_not_mutate_without_request():
    """Барабаны без ручного запроса не мутируют по времени."""
    engine, _q, dt = _make_engine()
    engine.tick(current_beat=0.0, bpm=120.0)
    engine.tick(current_beat=1000.0, bpm=120.0)
    assert dt.mutation_count == 0


def test_values_are_int():
    """Все значения в TransportEvent — plain int (не numpy)."""
    engine, q, dt = _make_engine()
    _set_steps(dt, 0, [0])
    engine.tick(current_beat=0.0, bpm=120.0)
    ev = _drain(q)[0]
    assert type(ev.note) is int
    assert type(ev.velocity) is int
    assert type(ev.channel) is int


def test_queue_full_drop_oldest():
    """При переполнении очереди — drop-oldest, не блок."""
    engine, q, dt = _make_engine(maxsize=2)
    _set_steps(dt, 0, [0])
    _set_steps(dt, 1, [0])
    _set_steps(dt, 2, [0])
    # 3 события, очередь на 2 — должно пройти без блокировки
    count = engine.tick(current_beat=0.0, bpm=120.0)
    assert count == 3
    assert q.qsize() == 2  # одно вытеснено


# ---------------------------------------------------------------------------
# Свинг (3.1): движок не сдвигает onset, пары одинаковой длины
# ---------------------------------------------------------------------------


def test_engine_does_not_swing_durations():
    """§4.2: движок отдаёт чистые биты и DEFAULT_GATE, свинг живёт в Transport."""
    engine, q, dt = _make_engine()
    _set_steps(dt, 0, [0, 1])  # чётный и нечётный шаги
    engine.tick(current_beat=0.0, bpm=120.0)
    ons = _drain(q)
    assert len(ons) == 1
    assert ons[0].duration == 0.25  # DEFAULT_GATE
    engine.tick(current_beat=0.25, bpm=120.0)
    events = _drain(q)
    # note_off первой пары + note_on второй — onset на точной позиции сетки.
    assert len(events) == 2
    off = [e for e in events if e.kind == EventKind.NOTE_OFF]
    on = [e for e in events if e.kind == EventKind.NOTE_ON]
    assert len(off) == 1 and len(on) == 1
    assert off[0].beat == pytest.approx(0.25)  # 0.0 + 0.25
    assert on[0].beat == pytest.approx(0.25)  # шаг 1, без свингового сдвига
    assert on[0].duration == 0.25
    # Пары одинаковой длины.
    assert on[0].duration == ons[0].duration


def test_default_gate_duration():
    """Длительность удара — DEFAULT_GATE, без преобразований."""
    engine, q, dt = _make_engine()
    _set_steps(dt, 0, [0])
    engine.tick(current_beat=0.0, bpm=120.0)
    events = _drain(q)
    assert events[0].duration == 0.25  # DEFAULT_GATE


# ---------------------------------------------------------------------------
# All notes off / reset (3.1)
# ---------------------------------------------------------------------------


def test_all_notes_off():
    """all_notes_off кладёт ALL_NOTES_OFF в очередь и сбрасывает pending."""
    engine, q, dt = _make_engine()
    _set_steps(dt, 0, [0])
    engine.tick(current_beat=0.0, bpm=120.0)
    _drain(q)
    assert engine.scheduler.pending_count > 0
    engine.all_notes_off()
    events = _drain(q)
    assert len(events) == 1
    assert events[0].kind == EventKind.ALL_NOTES_OFF
    assert engine.scheduler.pending_count == 0


def test_reset_clears_pending():
    """reset() очищает pending и знак: STOP-ветка хука не доигрывает прошлое."""
    engine, q, dt = _make_engine()
    _set_steps(dt, 0, [0])
    engine.tick(current_beat=0.0, bpm=120.0)
    _drain(q)
    assert engine.scheduler.pending_count > 0
    engine.reset()
    assert engine.scheduler.pending_count == 0
    assert not engine.scheduler.initialized
    # Свежий старт: прошлое (бит 0.0) не навёрстывается, следующий hit — бит 4.0.
    assert engine.tick(current_beat=1.0, bpm=120.0) == 0
    assert _drain(q) == []
    assert engine.tick(current_beat=4.0, bpm=120.0) == 1
    events = _drain(q)
    assert [e.beat for e in events if e.kind == EventKind.NOTE_ON] == pytest.approx(
        [4.0]
    )


# ---------------------------------------------------------------------------
# Смена порта (3.1)
# ---------------------------------------------------------------------------


def test_set_port_label_returns_old():
    """set_port_label возвращает предыдущую метку."""
    engine, _, _ = _make_engine()
    old = engine.set_port_label("aux")
    assert old == "Test Port"
    assert engine.port_label == "aux"


def test_tick_silent_when_no_port():
    """port_label=None — тишина, планировщик не двигается (как у melodic)."""
    engine, q, dt = _make_engine()
    _set_steps(dt, 0, [0])
    engine.set_port_label(None)
    assert engine.tick(current_beat=0.0, bpm=120.0) == 0
    assert q.empty()
    assert not engine.scheduler.initialized
    assert engine.scheduler.pending_count == 0


def test_all_notes_off_noop_when_no_port():
    """all_notes_off без порта — no-op (нечего глушить)."""
    engine, q, _ = _make_engine()
    engine.set_port_label(None)
    engine.all_notes_off()
    assert q.empty()


def test_all_notes_off_uses_current_label():
    """all_notes_off шлётся на текущий порт."""
    engine, q, _ = _make_engine()
    engine.all_notes_off()
    events = _drain(q)
    assert len(events) == 1
    assert events[0].port_label == "Test Port"


# ---------------------------------------------------------------------------
# Регресс дублирования (3.2): луп тиков, эталон drum_dub
# ---------------------------------------------------------------------------


class TestBeatScheduling:
    """Луп тиков таймлайна (480 PPQN): каждый hit ровно один раз на позиции."""

    PPQN = 480

    def _beats(self, total_beats: float) -> list[float]:
        """Последовательные тики таймлайна 0..total_beats включительно."""
        return [k / self.PPQN for k in range(int(total_beats * self.PPQN) + 1)]

    def test_hits_delivered_exactly_once(self) -> None:
        """Каждый активный шаг доставлен ровно один раз на своей позиции."""
        engine, q, dt = _make_engine()
        _setup_dub_patterns(dt)
        on_map, _off_map = _run_tick_loop(engine, q, self._beats(8.0))
        for note, ref_beats in DUB_REFERENCE.items():
            expected = sorted(ref_beats + [b + 4.0 for b in ref_beats])
            delivered = [b for b in _note_beats(on_map, note) if b < 8.0]
            assert delivered == pytest.approx(expected)
            # Дублей (note, beat) нет.
            for beat in delivered:
                assert on_map[beat].count(note) == 1

    def test_cycle2_equals_cycle1_plus_cycle_len(self) -> None:
        """Позиции цикла 2 = позиции цикла 1 + steps/4 битов."""
        engine, q, dt = _make_engine()
        _setup_dub_patterns(dt)
        on_map, _off_map = _run_tick_loop(engine, q, self._beats(8.0))
        for note, ref_beats in DUB_REFERENCE.items():
            delivered = _note_beats(on_map, note)
            first = [b for b in delivered if b < 4.0]
            second = [b for b in delivered if 4.0 <= b < 8.0]
            assert sorted(first) == pytest.approx(sorted(ref_beats))
            assert sorted(second) == pytest.approx(sorted(b + 4.0 for b in ref_beats))

    def test_note_off_pairs_with_on(self) -> None:
        """Каждому note_on соответствует note_off на +0.25, тот же note."""
        engine, q, dt = _make_engine()
        _setup_dub_patterns(dt)
        on_map, off_map = _run_tick_loop(engine, q, self._beats(8.0))
        for beat, notes in on_map.items():
            if beat + 0.25 > 8.0:
                continue  # off за пределами лупа
            for note in notes:
                off_beats = [b for b in off_map if abs(b - (beat + 0.25)) < 1e-9]
                assert len(off_beats) == 1
                assert off_map[off_beats[0]].count(note) == 1

    @pytest.mark.parametrize("steps", [32, 64])
    def test_grid_32_and_64(self, steps: int) -> None:
        """Сетки 32/64: cycle_len 8/16 битов, шаг 0.25 (16-я фиксированная)."""
        engine, q, dt = _make_engine(steps=steps)
        _set_steps(dt, 0, [0, 1, steps // 2])  # шаги 0, 1 и середина цикла
        cycle_len = steps / 4.0
        step_dur = 0.25
        on_map, _off_map = _run_tick_loop(engine, q, self._beats(2 * cycle_len))
        delivered = [b for b in _note_beats(on_map, GM_KICK) if b < 2 * cycle_len]
        rel = [0.0, step_dur, cycle_len / 2]
        expected = sorted(rel + [b + cycle_len for b in rel])
        assert delivered == pytest.approx(expected)
        for beat in delivered:
            assert on_map[beat].count(GM_KICK) == 1


# ---------------------------------------------------------------------------
# Реакция на правки (3.3)
# ---------------------------------------------------------------------------


class TestPatternEdits:
    """Правки паттерна/mute/порта применяются с текущего тика, без дублей."""

    def test_pattern_change_applies_from_current_tick(self) -> None:
        """(а) Смена lane.pattern между тиками: новый паттерн с текущего тика."""
        engine, q, dt = _make_engine()
        _set_steps(dt, 0, [0, 3])  # kick: биты 0, 0.75 на цикл
        on_map, _off_map = _run_tick_loop(engine, q, [0.0])
        assert _note_beats(on_map, GM_KICK) == pytest.approx([0.0])
        # Правка ровно на тике 2.0: старые запланированные note_on сняты.
        _set_steps(dt, 0, [0, 4])  # kick: биты 0, 1.0 на цикл
        dt.lanes[0].pattern[3] = 0
        beats = [k * 0.25 for k in range(1, 33)]  # 0.25..8.0
        on_map2, _off_map2 = _run_tick_loop(engine, q, beats)
        kick_ons = [b for b in _note_beats(on_map2, GM_KICK) if b < 8.0]
        # Цикл 0: остаток по новому паттерну (hit на rel 1.0); цикл 1: 4.0, 5.0.
        assert kick_ons == pytest.approx([1.0, 4.0, 5.0])
        for notes in on_map2.values():
            assert len(notes) == len(set(notes))

    def test_mutation_at_cycle_boundary_delivered_once(self) -> None:
        """(б) Правка ровно на тике границы цикла: удар на границе без дубля."""
        engine, q, dt = _make_engine()
        _set_steps(dt, 0, [0, 3])  # kick: биты 0, 0.75 на цикл
        beats = [k * 0.25 for k in range(33)]  # 0..8.0
        on_map: dict[float, list[int]] = {}
        for beat in beats:
            if beat == 4.0:  # мутация на границе цикла (steps/4)
                dt.lanes[0].pattern[3] = 0
                dt.lanes[0].pattern[4] = 1  # kick: биты 0, 1.0 на цикл
            engine.tick(beat, 120.0)
            for ev in _drain(q):
                if ev.kind == EventKind.NOTE_ON:
                    on_map.setdefault(ev.beat, []).append(ev.note)
        kick_ons = _note_beats(on_map, GM_KICK)
        # Цикл 0 по старому паттерну, с границы — по новому; дублей нет.
        assert kick_ons == pytest.approx([0.0, 0.75, 4.0, 5.0, 8.0])
        for beat, notes in on_map.items():
            assert len(notes) == len(set(notes))

    def test_lane_mute_unmute_no_dups(self) -> None:
        """(в) lane.muted True/False между тиками: lane исчезает/возвращается."""
        engine, q, dt = _make_engine()
        _set_steps(dt, 0, [0, 3])  # kick: биты 0, 0.75
        _set_steps(dt, 2, [4, 12])  # snare: биты 1.0, 3.0
        beats = [k * 0.25 for k in range(49)]  # 0..12.0
        on_map: dict[float, list[int]] = {}
        for beat in beats:
            if beat == 5.0:
                dt.lanes[0].muted = True
            if beat == 8.0:
                dt.lanes[0].muted = False
            engine.tick(beat, 120.0)
            for ev in _drain(q):
                if ev.kind == EventKind.NOTE_ON:
                    on_map.setdefault(ev.beat, []).append(ev.note)
        kick_ons = _note_beats(on_map, GM_KICK)
        snare_ons = _note_beats(on_map, GM_SNARE)
        # Kick: цикл 0, начало цикла 1 до mute, после unmute — циклы 2–3.
        assert kick_ons == pytest.approx([0.0, 0.75, 4.0, 4.75, 8.0, 8.75, 12.0])
        # Snare не мутируется: все циклы, включая перестроенные.
        assert snare_ons == pytest.approx([1.0, 3.0, 5.0, 7.0, 9.0, 11.0])
        for beat, notes in on_map.items():
            assert len(notes) == len(set(notes))

    def test_muted_track_sends_nothing(self) -> None:
        """(г) §4.6: mute дорожки — тишина, планирование идёт; unmute без навёрстывания."""
        engine, q, dt = _make_engine()
        _set_steps(dt, 0, [0])  # kick на бите 0 каждого цикла
        dt.muted = True
        assert engine.tick(current_beat=0.0, bpm=120.0) == 0
        assert _drain(q) == []
        # Планирование всё равно произошло — outbox наполнен (§4.5).
        assert len(dt.outbox) == 1
        assert engine.tick(current_beat=1.0, bpm=120.0) == 0
        assert _drain(q) == []
        dt.muted = False
        # Пропущенное (бит 0.0) не навёрстывается: опоздавшее отбрасывается.
        assert engine.tick(current_beat=1.0, bpm=120.0) == 0
        assert _drain(q) == []
        # Возврат в такт: kick цикла 1 (бит 4.0).
        assert engine.tick(current_beat=4.0, bpm=120.0) == 1
        events = _drain(q)
        assert [e.beat for e in events if e.kind == EventKind.NOTE_ON] == pytest.approx(
            [4.0]
        )

    def test_no_port_then_re_route(self) -> None:
        """(д) порт None → тишина; set_port_label("aux") → доставка на новый порт."""
        engine, q, dt = _make_engine()
        _set_steps(dt, 0, [0, 3])  # kick: биты 0, 0.75
        engine.set_port_label(None)
        assert engine.tick(current_beat=0.0, bpm=120.0) == 0
        assert engine.tick(current_beat=1.0, bpm=120.0) == 0
        assert not engine.scheduler.initialized
        assert engine.scheduler.pending_count == 0
        old = engine.set_port_label("aux")
        assert old is None
        # Watermark отстал: окно достраивается от него, опоздавшее отбрасывается.
        assert engine.tick(current_beat=4.0, bpm=120.0) == 1
        events = _drain(q)
        assert len(events) == 1
        assert events[0].port_label == "aux"
        assert events[0].beat == pytest.approx(4.0)
        assert events[0].kind == EventKind.NOTE_ON
