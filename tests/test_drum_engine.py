"""Tests for DrumEngine — мост между DrumTrack и транспортом."""

import queue

from src.session.drum.drum_engine import DrumEngine
from src.session.model.drum_track import DrumTrack
from src.sync.transport_event import EventKind, TransportEvent


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


# ---------------------------------------------------------------------------
# Базовая доставка
# ---------------------------------------------------------------------------


def test_tick_empty_pattern():
    """Пустой паттерн → нет событий в очереди."""
    engine, q, _ = _make_engine()
    count = engine.tick(current_beat=0.0, bpm=120.0)
    assert count == 0
    assert q.empty()


def test_tick_with_pattern():
    """Паттерн с ударами → TransportEvent в очереди."""
    engine, q, dt = _make_engine()
    dt.lanes[0].pattern[0] = 1  # kick
    dt.lanes[2].pattern[4] = 1  # snare
    count = engine.tick(current_beat=0.0, bpm=120.0)
    assert count == 2
    events = _drain(q)
    assert len(events) == 2
    assert all(e.kind == EventKind.NOTE_ON for e in events)
    assert all(e.port_label == "Test Port" for e in events)


def test_tick_event_fields():
    """События содержат правильные note/velocity/channel."""
    engine, q, dt = _make_engine()
    dt.lanes[0].pattern[0] = 2  # accent
    engine.tick(current_beat=0.0, bpm=120.0)
    events = _drain(q)
    assert len(events) == 1
    ev = events[0]
    assert ev.note == 36  # Kick
    assert 120 <= ev.velocity <= 127  # accent
    assert ev.channel == 9  # default ch10


def test_tick_respects_channel():
    """События идут на channel дорожки."""
    engine, q, dt = _make_engine()
    dt.channel = 5
    dt.lanes[0].pattern[0] = 1
    engine.tick(current_beat=0.0, bpm=120.0)
    events = _drain(q)
    assert events[0].channel == 5


# ---------------------------------------------------------------------------
# Свинг
# ---------------------------------------------------------------------------


def test_engine_does_not_swing_durations():
    """§4.2: движок отдаёт чистые длительности, свинг живёт в Transport."""
    engine, q, dt = _make_engine()
    dt.lanes[0].pattern[0] = 1
    dt.lanes[0].pattern[1] = 1
    engine.tick(current_beat=0.0, bpm=120.0)
    events = _drain(q)
    assert len(events) == 2
    # Чётный и нечётный шаги одинаковы: движок ничего не сдвигает.
    assert events[0].duration == events[1].duration


def test_default_gate_duration():
    """Длительность удара — DEFAULT_GATE, без преобразований."""
    engine, q, dt = _make_engine()
    dt.lanes[0].pattern[0] = 1
    engine.tick(current_beat=0.0, bpm=120.0)
    events = _drain(q)
    assert events[0].duration == 0.25  # DEFAULT_GATE


# ---------------------------------------------------------------------------
# Очередь: переполнение
# ---------------------------------------------------------------------------


def test_queue_full_drop_oldest():
    """При переполнении очереди — drop-oldest, не блок."""
    engine, q, dt = _make_engine(maxsize=2)
    dt.lanes[0].pattern[0] = 1
    dt.lanes[1].pattern[0] = 1
    dt.lanes[2].pattern[0] = 1
    # 3 события, очередь на 2 — должно пройти без блокировки
    count = engine.tick(current_beat=0.0, bpm=120.0)
    assert count == 3
    assert q.qsize() == 2  # одно вытеснено


# ---------------------------------------------------------------------------
# All notes off
# ---------------------------------------------------------------------------


def test_all_notes_off():
    """all_notes_off кладёт ALL_NOTES_OFF в очередь."""
    engine, q, _ = _make_engine()
    engine.all_notes_off()
    events = _drain(q)
    assert len(events) == 1
    assert events[0].kind == EventKind.ALL_NOTES_OFF


# ---------------------------------------------------------------------------
# Мутация через tick
# ---------------------------------------------------------------------------


def test_tick_triggers_mutation():
    """tick вызывает maybe_mutate — мутация применяется при времени."""
    engine, _q, dt = _make_engine()
    dt.mutate = 1.0
    # current_beat достаточно большой — мутация должна примениться
    engine.tick(current_beat=0.0, bpm=120.0)
    engine.tick(current_beat=1000.0, bpm=120.0)
    assert dt.mutation_count > 0


def test_tick_bpm_sets_mutation_interval():
    """Темп приходит в tick: при 60 BPM мутация наступает через 8–16 beats."""
    engine, _q, dt = _make_engine()
    dt.mutate = 1.0
    engine.tick(current_beat=0.0, bpm=60.0)
    engine.tick(current_beat=7.9, bpm=60.0)
    assert dt.mutation_count == 0
    engine.tick(current_beat=16.1, bpm=60.0)
    assert dt.mutation_count > 0


# ---------------------------------------------------------------------------
# BPM (C6, R4)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# int() конвертация
# ---------------------------------------------------------------------------


def test_values_are_int():
    """Все значения в TransportEvent — plain int (не numpy)."""
    engine, q, dt = _make_engine()
    dt.lanes[0].pattern[0] = 1
    engine.tick(current_beat=0.0, bpm=120.0)
    events = _drain(q)
    ev = events[0]
    assert type(ev.note) is int
    assert type(ev.velocity) is int
    assert type(ev.channel) is int


# ---------------------------------------------------------------------------
# Смена порта в рантайме (track route/unroute)
# ---------------------------------------------------------------------------


def test_set_port_label_returns_old():
    """set_port_label возвращает предыдущую метку."""
    engine, _, _ = _make_engine()
    old = engine.set_port_label("aux")
    assert old == "Test Port"
    assert engine.port_label == "aux"


def test_tick_silent_when_no_port():
    """port_label=None — тишина: генерация и мутация приостановлены."""
    engine, q, dt = _make_engine()
    dt.lanes[0].pattern[0] = 1  # kick
    engine.set_port_label(None)
    count = engine.tick(current_beat=0.0, bpm=120.0)
    assert count == 0
    assert q.empty()


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


def test_muted_track_sends_nothing():
    """§4.6: mute дорожки останавливает доставку, генерация идёт."""
    engine, q, dt = _make_engine()
    dt.lanes[0].pattern[0] = 1
    dt.muted = True
    assert engine.tick(current_beat=0.0, bpm=120.0) == 0
    assert _drain(q) == []
    # генерация всё равно произошла — outbox наполнен (§4.5)
    assert len(dt.outbox) == 1

    dt.muted = False
    assert engine.tick(current_beat=1.0, bpm=120.0) == 1
    assert len(_drain(q)) == 1
