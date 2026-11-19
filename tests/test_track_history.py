"""Линейная история версий в MutationEngine (spec «ручная мутация», §6–§8).

Проверяют: undo/recall восстанавливают снимок в объекты дрейфа, мутация
после undo отрезает будущее, счётчик = номер версии от корня, вытеснение
старых версий при лимите, drum-дорожки и переживание pending перезапуска.
"""

from __future__ import annotations

import random

from src.session.model.drum_track import DrumTrack
from src.session.model.melodic_track import MelodicTrack
from src.session.mutation.mutation_engine import MutationEngine


def _engine(track: MelodicTrack | None = None) -> MutationEngine:
    eng = MutationEngine(rng=random.Random(42))
    eng.register_track(
        "L",
        "lead",
        degrees=[0, 2, 4, 2],
        track=track,
    )
    return eng


def _run(eng: MutationEngine, beats: list[float]) -> None:
    for b in beats:
        eng.tick(b)


def _step_once(eng: MutationEngine) -> None:
    """Одна ручная мутация: тик-точка, запрос, тик до границы цикла 4.0."""
    base = eng.get_state("L").last_mutation_beat
    _run(eng, [base])  # фиксируем prev на текущей позиции
    eng.request_mutation("L", cycle_beats=4.0)
    _run(eng, [base + 4.0])  # пересекаем границу цикла


class TestUndoRecall:
    def test_undo_restores_previous_degrees(self) -> None:
        eng = _engine()
        before = list(eng.get_note_drift("L").current_degrees)
        _step_once(eng)
        assert eng.get_note_drift("L").current_degrees != before
        assert eng.undo("L") is True
        assert eng.get_note_drift("L").current_degrees == before

    def test_undo_at_root_refused(self) -> None:
        eng = _engine()
        assert eng.undo("L") is False
        assert eng.current_version("L") == 0

    def test_undo_unknown_track_refused(self) -> None:
        eng = _engine()
        assert eng.undo("Nope") is False

    def test_mutation_after_undo_truncates_future(self) -> None:
        eng = _engine()
        _step_once(eng)  # версия 1
        _step_once(eng)  # версия 2
        assert eng.history_len("L") == 3
        assert eng.undo("L") is True  # курсор на версии 1
        _step_once(eng)  # мутация отрезает старую версию 2 и заменяет новой
        assert eng.history_len("L") == 3
        assert eng.current_version("L") == 2
        # Откат ведёт на версию 1 (старой версии 2 больше нет).
        assert eng.undo("L") is True
        assert eng.current_version("L") == 1

    def test_mutation_after_recall_truncates_future(self) -> None:
        eng = _engine()
        _step_once(eng)  # версия 1
        _step_once(eng)  # версия 2
        assert eng.recall("L", 0) is True
        _step_once(eng)  # мутация от корня отрезает версии 1 и 2
        assert eng.history_len("L") == 2
        assert eng.current_version("L") == 1

    def test_recall_any_version(self) -> None:
        eng = _engine()
        root = list(eng.get_note_drift("L").current_degrees)
        _step_once(eng)
        _step_once(eng)
        assert eng.recall("L", 0) is True
        assert eng.get_note_drift("L").current_degrees == root
        assert eng.current_version("L") == 0

    def test_recall_keeps_future(self) -> None:
        eng = _engine()
        _step_once(eng)
        _step_once(eng)
        eng.recall("L", 0)
        # Будущее не отрезано: recall обратно на версию 2 возможен
        assert eng.recall("L", 2) is True
        assert eng.current_version("L") == 2

    def test_recall_bad_index_refused(self) -> None:
        eng = _engine()
        assert eng.recall("L", 5) is False
        assert eng.recall("L", -1) is False
        assert eng.recall("Nope", 0) is False

    def test_counter_equals_cursor(self) -> None:
        track = MelodicTrack(name="L", profile_name="lead")
        eng = MutationEngine(rng=random.Random(42))
        eng.register_track("L", "lead", degrees=[0, 2, 4, 2], track=track)
        _step_once(eng)
        _step_once(eng)
        assert track.mutation_count == 2
        assert eng.get_state("L").mutation_count == 2
        eng.undo("L")
        assert track.mutation_count == 1
        eng.undo("L")
        assert track.mutation_count == 0

    def test_history_len_and_current_version_api(self) -> None:
        eng = _engine()
        assert eng.history_len("L") == 1
        assert eng.current_version("Nope") == -1
        assert eng.history_len("Nope") == 0
        _step_once(eng)
        assert eng.history_len("L") == 2
        assert eng.current_version("L") == 1


class TestRestoreDrift:
    def test_note_drift_next_step_from_restored(self) -> None:
        eng = _engine()
        root = list(eng.get_note_drift("L").current_degrees)
        _step_once(eng)
        drifted = list(eng.get_note_drift("L").current_degrees)
        assert drifted != root
        eng.undo("L")
        # Следующий шаг дрейфа идёт от восстановленного значения:
        # после undo текущее = корню; мутация от корня уводит его снова.
        _step_once(eng)
        now = eng.get_note_drift("L").current_degrees
        assert now != root  # дрейф продолжился от восстановленного
        assert eng.current_version("L") == 1

    def test_euclidean_restore(self) -> None:
        eng = MutationEngine(rng=random.Random(3))
        eng.register_track("S", "seq", euclidean_steps=16, euclidean_pulses=4)
        eng.tick(0.0)
        eng.request_mutation("S", cycle_beats=4.0)
        eng.tick(4.0)
        drifted = eng.get_euclidean_drift("S").pulses
        assert drifted in (3, 5)
        eng.undo("S")
        assert eng.get_euclidean_drift("S").pulses == 4

    def test_param_drift_restore(self) -> None:
        eng = MutationEngine(rng=random.Random(5))
        eng.register_track("P", "pad", gate=0.5)
        eng.tick(0.0)
        eng.request_mutation("P", cycle_beats=4.0)
        eng.tick(4.0)
        eng.undo("P")
        assert eng.get_param_drift("P").get("gate") == 0.5


class TestEviction:
    def test_257th_version_evicts_second_root_stays(self) -> None:
        eng = _engine()
        root = list(eng.get_note_drift("L").current_degrees)
        for _ in range(257):
            _step_once(eng)
        assert eng.history_len("L") == 256
        assert eng.current_version("L") == 255
        # Корень (версия 0) не вытесняется: recall(0) возвращает базу.
        assert eng.recall("L", 0) is True
        assert eng.get_note_drift("L").current_degrees == root


class TestDrumHistory:
    def _drum(self) -> tuple[MutationEngine, DrumTrack]:
        dt = DrumTrack(name="Drum 1")
        dt.lanes[0].pattern[0] = 1
        eng = MutationEngine(rng=random.Random(11))
        eng.register_drum_track("Drum 1", track=dt)
        return eng, dt

    def test_drum_request_applies_on_cycle_boundary(self) -> None:
        eng, dt = self._drum()
        before = dt.snapshot()
        eng.request_mutation("Drum 1", cycle_beats=4.0)  # steps=16 → 16/4
        eng.tick(2.0)
        assert dt.snapshot() == before  # не на границе
        eng.tick(4.0)
        assert dt.snapshot() != before
        assert eng.history_len("Drum 1") == 2

    def test_drum_undo_restores_lanes(self) -> None:
        eng, dt = self._drum()
        before = dt.snapshot()
        eng.tick(0.0)
        eng.request_mutation("Drum 1", cycle_beats=4.0)
        eng.tick(4.0)
        assert dt.snapshot() != before
        assert eng.undo("Drum 1") is True
        assert dt.snapshot() == before

    def test_drum_counter_synced(self) -> None:
        eng, dt = self._drum()
        eng.tick(0.0)
        eng.request_mutation("Drum 1", cycle_beats=4.0)
        eng.tick(4.0)
        assert dt.mutation_count == 1
        eng.undo("Drum 1")
        assert dt.mutation_count == 0


class TestPendingFlag:
    def test_commit_clears_pending_flag(self) -> None:
        track = MelodicTrack(name="L", profile_name="lead")
        eng = MutationEngine(rng=random.Random(42))
        eng.register_track("L", "lead", degrees=[0, 2, 4, 2], track=track)
        track.pending = True  # ставит фасад (NEW/evolve)
        eng.request_mutation("L", cycle_beats=4.0)
        eng.tick(0.0)
        assert track.pending is True  # ещё не на границе
        eng.tick(4.0)
        assert track.pending is False  # применена — мигание снято


class TestHistoryResets:
    def test_profile_change_resets_history(self) -> None:
        track = MelodicTrack(name="L", profile_name="lead")
        eng = MutationEngine(rng=random.Random(42))
        eng.register_track("L", "lead", degrees=[0, 2, 4, 2], track=track)
        _step_once(eng)
        assert eng.history_len("L") == 2
        track.set_profile("pad")
        eng.refresh_track("L")
        assert eng.history_len("L") == 1
        assert eng.current_version("L") == 0
        assert track.mutation_count == 0

    def test_degrees_edit_resets_history(self) -> None:
        track = MelodicTrack(name="L", profile_name="lead")
        eng = MutationEngine(rng=random.Random(42))
        eng.register_track("L", "lead", degrees=[0, 2, 4, 2], track=track)
        _step_once(eng)
        assert eng.history_len("L") == 2
        track.degrees = (4, 4, 4, 4)  # пользовательская правка
        eng.refresh_track("L")
        assert eng.history_len("L") == 1
        assert track.mutation_count == 0
