import random

from src.session.mutation.mutation_engine import MutationEngine


def _engine() -> MutationEngine:
    eng = MutationEngine(rng=random.Random(1))
    eng.register_track("Lead", "lead", mutate=0.0, degrees=[0, 2, 4, 2])
    return eng


def _degrees(eng: MutationEngine) -> list[int]:
    return eng.get_note_drift("Lead").current_degrees


def _run(eng: MutationEngine, beats: list[float]) -> None:
    for b in beats:
        eng.tick(b)


def test_no_request_no_change_with_timer_disabled():
    eng = _engine()
    before = _degrees(eng)
    _run(eng, [i * 0.5 for i in range(200)])
    assert _degrees(eng) == before
    assert eng.get_state("Lead").mutation_count == 0


def test_request_applies_on_cycle_boundary_only():
    eng = _engine()
    before = _degrees(eng)
    eng.request_mutation("Lead", cycle_beats=4.0)
    _run(eng, [0.0, 0.5, 1.0, 2.0, 3.0, 3.5])
    assert _degrees(eng) == before
    assert eng.get_state("Lead").mutation_count == 0
    _run(eng, [4.0])
    assert _degrees(eng) != before
    assert eng.get_state("Lead").mutation_count == 1
    assert eng.get_state("Lead").last_mutation_beat == 4.0


def test_request_mid_cycle_waits_for_next_boundary():
    eng = _engine()
    _run(eng, [0.0, 1.0, 2.0])
    eng.request_mutation("Lead", cycle_beats=4.0)
    _run(eng, [3.0, 4.0])
    assert eng.get_state("Lead").mutation_count == 1
    eng.request_mutation("Lead", cycle_beats=4.0)
    _run(eng, [5.0, 6.0, 7.0])
    assert eng.get_state("Lead").mutation_count == 1
    _run(eng, [8.0])
    assert eng.get_state("Lead").mutation_count == 2


def test_two_requests_in_one_cycle_give_one_mutation():
    eng = _engine()
    _run(eng, [0.0, 1.0])
    eng.request_mutation("Lead", cycle_beats=4.0)
    eng.request_mutation("Lead", cycle_beats=4.0)
    _run(eng, [4.0])
    assert eng.get_state("Lead").mutation_count == 1


def test_request_on_exact_boundary_tick_fires_on_that_tick():
    eng = _engine()
    _run(eng, [3.5])
    eng.request_mutation("Lead", cycle_beats=4.0)
    _run(eng, [4.0])
    assert eng.get_state("Lead").mutation_count == 1
    assert eng.get_state("Lead").last_mutation_beat == 4.0


def test_request_for_unknown_track_is_dropped():
    eng = _engine()
    eng.request_mutation("Missing", cycle_beats=4.0)
    _run(eng, [0.0, 4.0, 8.0])
    assert eng.get_state("Missing") is None
    assert eng.get_state("Lead").mutation_count == 0


def test_backwards_beat_does_not_fire():
    eng = _engine()
    _run(eng, [5.0])
    eng.request_mutation("Lead", cycle_beats=4.0)
    _run(eng, [1.0])
    assert eng.get_state("Lead").mutation_count == 0


def test_tracks_with_different_cycles_fire_independently():
    eng = _engine()
    eng.register_track("Lead2", "lead", mutate=0.0, degrees=[0, 2, 4, 2])
    _run(eng, [0.0, 1.0])
    eng.request_mutation("Lead", cycle_beats=4.0)
    eng.request_mutation("Lead2", cycle_beats=2.0)
    _run(eng, [2.0])
    assert eng.get_state("Lead2").mutation_count == 1
    assert eng.get_state("Lead").mutation_count == 0
    _run(eng, [4.0])
    assert eng.get_state("Lead").mutation_count == 1


def test_ten_thousand_ticks_without_request_do_not_change_pattern():
    eng = MutationEngine(rng=random.Random(9))
    eng.register_track("Lead", "lead", mutate=1.0, degrees=[0, 2, 4, 2])
    before = _degrees(eng)
    for k in range(10_000):
        eng.tick(k * 0.25)
    assert _degrees(eng) == before
    assert eng.get_state("Lead").mutation_count == 0


def test_ten_thousand_ticks_without_request_do_not_change_pattern():
    eng = MutationEngine(rng=random.Random(9))
    eng.register_track("Lead", "lead", mutate=1.0, degrees=[0, 2, 4, 2])
    before = _degrees(eng)
    for k in range(10_000):
        eng.tick(k * 0.25, 120.0)
    assert _degrees(eng) == before
    assert eng.get_state("Lead").mutation_count == 0
