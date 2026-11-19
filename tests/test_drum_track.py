"""Tests for DrumTrack — генерация, velocity, мутация."""

import pytest

from src.session.events.drum_event import DrumEvent
from src.session.model.drum_track import (
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
    assert events[1].beat == pytest.approx(4.0)  # шаг 16 × 0.25 = середина цикла (8 битов)


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


def test_apply_mutation_changes_pattern():
    """Шаг мутации (_apply_mutation) меняет хотя бы один lane.

    Автономного таймера больше нет: применение — только по явному запросу
    (MutationEngine, граница цикла). Счётчик ведёт движок через историю
    версий (spec §7), сам шаг его не трогает.
    """
    dt = DrumTrack(name="Drum 1")
    dt.lanes[0].pattern[0] = 1
    before = [list(lane.pattern) for lane in dt.lanes]
    dt._apply_mutation()
    after = [list(lane.pattern) for lane in dt.lanes]
    assert before != after
    assert dt.mutation_count == 0


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


def test_generate_publishes_to_outbox():
    """§4.5: drum-события попадают в outbox, current()/history() работают."""
    dt = DrumTrack(name="Drum 1")
    dt.lanes[0].pattern[0] = 1
    dt.lanes[0].pattern[8] = 1
    events = dt.generate()
    assert len(events) == 2
    assert len(dt.outbox) == 2
    assert dt.current() is not None
    assert dt.current().beat == 2.0
    assert len(dt.history(1.0)) == 1


# ---------------------------------------------------------------------------
# resolve_lane: адресация индексом / GM-номером / именем (design §6)
# ---------------------------------------------------------------------------


class TestResolveLane:
    def test_by_index(self):
        dt = DrumTrack(name="Drum 1")
        assert dt.resolve_lane("0") == 0
        assert dt.resolve_lane("15") == 15

    def test_by_gm_number(self):
        dt = DrumTrack(name="Drum 1")
        assert dt.resolve_lane("36") == 0
        assert dt.resolve_lane("51") == 15
        assert dt.resolve_lane("42") == 6  # ClosedHat

    def test_by_name_case_insensitive(self):
        dt = DrumTrack(name="Drum 1")
        assert dt.resolve_lane("kick") == 0
        assert dt.resolve_lane("Kick") == 0
        assert dt.resolve_lane("KICK") == 0
        assert dt.resolve_lane("snare") == 2

    def test_criterion_all_forms_equal(self):
        """Критерий задачи: kick == Kick == "36" == 0."""
        dt = DrumTrack(name="Drum 1")
        assert dt.resolve_lane("kick") == dt.resolve_lane("Kick")
        assert dt.resolve_lane("Kick") == dt.resolve_lane("36")
        assert dt.resolve_lane("36") == 0

    def test_number_outside_both_ranges_is_error(self):
        dt = DrumTrack(name="Drum 1")
        with pytest.raises(ValueError, match="вне диапазонов"):
            dt.resolve_lane("20")
        with pytest.raises(ValueError, match="вне диапазонов"):
            dt.resolve_lane("-3")
        with pytest.raises(ValueError, match="вне диапазонов"):
            dt.resolve_lane("52")

    def test_unknown_name_is_error(self):
        dt = DrumTrack(name="Drum 1")
        with pytest.raises(ValueError, match="не индекс"):
            dt.resolve_lane("cowbellissimo")

    def test_step_to_note_unchanged(self):
        """Переименование GM-карты не изменило step_to_note."""
        assert DrumTrack.step_to_note(0) == 36
        assert DrumTrack.step_to_note(15) == 51
