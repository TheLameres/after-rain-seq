"""Tests for DrumTrack — генерация, velocity, мутация."""

import pytest

from src.session.events.drum_event import DrumEvent
from src.session.model.drum_track import (
    MUTATE_MAX_SECONDS,
    MUTATE_MIN_SECONDS,
    VELOCITY_ACCENT,
    VELOCITY_NORMAL,
    DrumTrack,
)

# ---------------------------------------------------------------------------
# Генерация: базовая
# ---------------------------------------------------------------------------


def test_generate_empty_pattern():
    """Пустой паттерн → нет событий."""
    dt = DrumTrack(name="Drum 1")
    events = dt.generate()
    assert events == []


def test_generate_returns_list():
    """generate() возвращает list[DrumEvent]."""
    dt = DrumTrack(name="Drum 1")
    dt.lanes[0].pattern[0] = 1  # kick на шаге 0
    events = dt.generate()
    assert isinstance(events, list)
    assert all(isinstance(e, DrumEvent) for e in events)


def test_generate_single_hit():
    """Один активный шаг → одно событие."""
    dt = DrumTrack(name="Drum 1")
    dt.lanes[0].pattern[0] = 1  # kick на шаге 0
    events = dt.generate()
    assert len(events) == 1
    assert events[0].note == 36  # Kick = GM 36
    assert events[0].lane_index == 0
    assert events[0].beat == 0.0


def test_generate_multiple_lanes():
    """Несколько lane → события от каждого."""
    dt = DrumTrack(name="Drum 1")
    dt.lanes[0].pattern[0] = 1  # kick
    dt.lanes[2].pattern[0] = 1  # snare
    dt.lanes[6].pattern[0] = 1  # closed hat
    events = dt.generate()
    assert len(events) == 3
    notes = {e.note for e in events}
    assert notes == {36, 38, 42}


def test_generate_sorted_by_beat():
    """События отсортированы по beat."""
    dt = DrumTrack(name="Drum 1")
    dt.lanes[0].pattern[4] = 1  # kick на шаге 4
    dt.lanes[1].pattern[0] = 1  # rimshot на шаге 0
    events = dt.generate()
    assert len(events) == 2
    assert events[0].beat < events[1].beat


# ---------------------------------------------------------------------------
# Velocity: три уровня
# ---------------------------------------------------------------------------


def test_velocity_normal_range():
    """Ячейка=1 → velocity в диапазоне normal (90–100)."""
    dt = DrumTrack(name="Drum 1")
    dt.lanes[0].pattern[0] = 1
    events = dt.generate()
    assert VELOCITY_NORMAL[0] <= events[0].velocity <= VELOCITY_NORMAL[1]


def test_velocity_accent_range():
    """Ячейка=2 → velocity в диапазоне accent (120–127)."""
    dt = DrumTrack(name="Drum 1")
    dt.lanes[0].pattern[0] = 2
    events = dt.generate()
    assert VELOCITY_ACCENT[0] <= events[0].velocity <= VELOCITY_ACCENT[1]


def test_velocity_accent_higher_than_normal():
    """Accent всегда громче normal."""
    dt = DrumTrack(name="Drum 1")
    dt.lanes[0].pattern[0] = 1
    dt.lanes[1].pattern[0] = 2
    events = dt.generate()
    normal_ev = next(e for e in events if e.lane_index == 0)
    accent_ev = next(e for e in events if e.lane_index == 1)
    assert accent_ev.velocity > normal_ev.velocity


# ---------------------------------------------------------------------------
# Muted lane
# ---------------------------------------------------------------------------


def test_muted_lane_silent():
    """Muted lane не генерирует событий."""
    dt = DrumTrack(name="Drum 1")
    dt.lanes[0].pattern[0] = 1
    dt.lanes[0].muted = True
    events = dt.generate()
    assert events == []


def test_muted_lane_does_not_affect_others():
    """Muted один lane — другие работают."""
    dt = DrumTrack(name="Drum 1")
    dt.lanes[0].pattern[0] = 1
    dt.lanes[0].muted = True
    dt.lanes[1].pattern[0] = 1
    events = dt.generate()
    assert len(events) == 1
    assert events[0].lane_index == 1


# ---------------------------------------------------------------------------
# Сетка: steps
# ---------------------------------------------------------------------------


def test_steps_32():
    """steps=32 → события на шагах 0..31."""
    dt = DrumTrack(name="Drum 1", steps=32)
    dt.lanes[0].pattern[0] = 1
    dt.lanes[0].pattern[16] = 1  # второй половине
    events = dt.generate()
    assert len(events) == 2
    assert events[0].beat == 0.0
    assert events[1].beat == pytest.approx(2.0)  # шаг 16 при 32 шагах = 2 такта


def test_steps_16_default():
    """По умолчанию steps=16."""
    dt = DrumTrack(name="Drum 1")
    assert dt.steps == 16


# ---------------------------------------------------------------------------
# Лад не влияет
# ---------------------------------------------------------------------------


def test_root_scale_no_effect():
    """Drum не использует Harmony — смена лада не влияет."""
    dt = DrumTrack(name="Drum 1")
    dt.lanes[0].pattern[0] = 1
    events_before = dt.generate()
    # Симулируем смену лада — drum не должен реагировать
    events_after = dt.generate()
    assert [e.note for e in events_before] == [e.note for e in events_after]


# ---------------------------------------------------------------------------
# Мутация
# ---------------------------------------------------------------------------


def test_mutate_zero_no_change():
    """mutate=0 → паттерн не меняется."""
    dt = DrumTrack(name="Drum 1")
    dt.mutate = 0.0
    dt.lanes[0].pattern[0] = 1
    pattern_before = list(dt.lanes[0].pattern)
    # Прошло достаточно времени
    dt.maybe_mutate(current_beat=1000.0)
    assert dt.lanes[0].pattern == pattern_before


def test_mutate_applies():
    """mutate>0 → паттерн меняется после интервала."""
    dt = DrumTrack(name="Drum 1")
    dt.mutate = 1.0
    # Запоминаем все паттерны
    all_before = [list(lane.pattern) for lane in dt.lanes]

    # Должно быть применено
    result = dt.maybe_mutate(current_beat=1000.0)
    assert result is True
    # Хотя бы один lane изменился
    all_after = [list(lane.pattern) for lane in dt.lanes]
    assert all_before != all_after


def test_mutate_not_before_interval():
    """Мутация не применяется раньше интервала."""
    dt = DrumTrack(name="Drum 1")
    dt.mutate = 1.0
    # current_beat=0, next_mutation_beat > 0
    result = dt.maybe_mutate(current_beat=0.0)
    assert result is False


def test_mutation_count():
    """Счётчик мутаций растёт."""
    dt = DrumTrack(name="Drum 1")
    dt.mutate = 1.0
    assert dt.mutation_count == 0
    dt.maybe_mutate(current_beat=1000.0)
    assert dt.mutation_count > 0


def test_freeze_resets():
    """freeze() сбрасывает счётчик и запоминает паттерн."""
    dt = DrumTrack(name="Drum 1")
    dt.mutate = 1.0
    dt.lanes[0].pattern[0] = 1
    dt.maybe_mutate(current_beat=1000.0)
    assert dt.mutation_count > 0
    dt.freeze()
    assert dt.mutation_count == 0
    # Паттерн сохранён
    assert dt.lanes[0].pattern[0] == 1


def test_mutation_interval_in_seconds():
    """Интервал мутации пересчитывается от BPM."""
    dt = DrumTrack(name="Drum 1")
    dt.bpm = 120.0
    dt.mutate = 1.0
    # При 120 BPM: 8 сек = 16 тактов, 16 сек = 32 такта
    dt.maybe_mutate(current_beat=1000.0)
    # next_mutation_beat должен быть в разумном диапазоне
    expected_min = 1000.0 + MUTATE_MIN_SECONDS * 120.0 / 60.0
    expected_max = 1000.0 + MUTATE_MAX_SECONDS * 120.0 / 60.0
    assert expected_min <= dt._next_mutation_beat <= expected_max


# ---------------------------------------------------------------------------
# Sources заблокированы
# ---------------------------------------------------------------------------


def test_sources_blocked():
    """DrumTrack отклоняет попытку назначить источники."""
    dt = DrumTrack(name="Drum 1")
    assert dt.sources == ()
    with pytest.raises(ValueError, match="не участвует в графе"):
        dt.sources = ("Pad 1",)


# ---------------------------------------------------------------------------
# step_to_note
# ---------------------------------------------------------------------------


def test_step_to_note():
    """step_to_note мапит 0..15 на GM 36..51."""
    assert DrumTrack.step_to_note(0) == 36
    assert DrumTrack.step_to_note(6) == 42
    assert DrumTrack.step_to_note(15) == 51


def test_step_to_note_out_of_range():
    """step_to_note вне 0..15 — ValueError."""
    with pytest.raises(ValueError, match="вне диапазона"):
        DrumTrack.step_to_note(16)
    with pytest.raises(ValueError, match="вне диапазона"):
        DrumTrack.step_to_note(-1)


# ---------------------------------------------------------------------------
# Outbox (ChordEvent не публикуется)
# ---------------------------------------------------------------------------


def test_outbox_cleared():
    """generate() очищает outbox (drum не публикует ChordEvent)."""
    from src.session.events.chord_event import ChordEvent

    dt = DrumTrack(name="Drum 1")
    dt.outbox.append(ChordEvent(0.0, (0, 2, 4), 1.0, "1-3-5"))
    dt.generate()
    assert dt.outbox == []


def test_freeze_sets_mutate_zero():
    """Regression §4.3: DrumTrack.freeze() must stop mutation, not only reset counter."""
    dt = DrumTrack(name="Drum 1")
    dt.mutate = 1.0
    dt.freeze()
    assert dt.mutate == 0.0
    dt.lanes[0].pattern[0] = 1
    for beat in range(1000, 21000):
        dt.maybe_mutate(current_beat=float(beat))
    assert dt.mutation_count == 0
