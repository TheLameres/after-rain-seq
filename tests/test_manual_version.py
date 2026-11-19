"""record_manual_version — ручная правка паттерна как версия (design §7).

MutationEngine напрямую (без App): drum-дорожка + правка lane.pattern.
"""

from __future__ import annotations

import random

from src.session.model.drum_track import DrumTrack
from src.session.mutation.mutation_engine import MutationEngine


def _engine_with_drum() -> tuple[MutationEngine, DrumTrack]:
    track = DrumTrack(name="Drums")
    engine = MutationEngine(rng=random.Random(1))
    engine.register_drum_track("Drums", track)
    return engine, track


class TestRecordManualVersion:
    def test_records_version_after_pattern_edit(self) -> None:
        engine, track = _engine_with_drum()
        track.lanes[0].pattern = [1, 0, 0, 1] + [0] * 12
        assert engine.record_manual_version("Drums") is True
        assert engine.history_len("Drums") == 2
        assert engine.current_version("Drums") == 1

    def test_syncs_counter(self) -> None:
        engine, track = _engine_with_drum()
        track.lanes[0].pattern = [1] + [0] * 15
        engine.record_manual_version("Drums")
        assert engine.get_state("Drums").mutation_count == 1
        assert track.mutation_count == 1

    def test_snapshot_equals_post_edit_state(self) -> None:
        """В историю уходит состояние после правки (spec mutation)."""
        engine, track = _engine_with_drum()
        track.lanes[0].pattern = [1, 0, 0, 1] + [0] * 12
        engine.record_manual_version("Drums")
        head = engine._histories["Drums"].current
        assert head.lanes == track.snapshot()

    def test_unregistered_track_is_false(self) -> None:
        engine, _track = _engine_with_drum()
        assert engine.record_manual_version("Nope") is False

    def test_same_pattern_twice_no_duplicate(self) -> None:
        """Повторная установка того же паттерна — дедупликация, False."""
        engine, track = _engine_with_drum()
        track.lanes[0].pattern = [1, 0, 0, 1] + [0] * 12
        assert engine.record_manual_version("Drums") is True
        assert engine.history_len("Drums") == 2
        # Тот же паттерн заново (новый список, тот же контент).
        track.lanes[0].pattern = [1, 0, 0, 1] + [0] * 12
        assert engine.record_manual_version("Drums") is False
        assert engine.history_len("Drums") == 2

    def test_return_to_old_pattern_creates_new_version(self) -> None:
        """Возврат к прежнему паттерну после промежуточной правки — новая версия."""
        engine, track = _engine_with_drum()
        first = [1, 0, 0, 1] + [0] * 12
        track.lanes[0].pattern = list(first)
        engine.record_manual_version("Drums")
        track.lanes[0].pattern = [1] + [0] * 15  # промежуточная правка
        engine.record_manual_version("Drums")
        assert engine.history_len("Drums") == 3
        track.lanes[0].pattern = list(first)  # возврат к первому паттерну
        assert engine.record_manual_version("Drums") is True
        assert engine.history_len("Drums") == 4


class TestUndoRecallAfterManualEdit:
    def test_undo_returns_previous_pattern(self) -> None:
        engine, track = _engine_with_drum()
        manual = [1, 0, 0, 1] + [0] * 12
        track.lanes[0].pattern = list(manual)
        engine.record_manual_version("Drums")
        assert engine.undo("Drums") is True
        assert track.lanes[0].pattern == [0] * 16
        assert track.mutation_count == 0

    def test_recall_restores_manual_edit(self) -> None:
        engine, track = _engine_with_drum()
        manual = [1, 0, 0, 1] + [0] * 12
        track.lanes[0].pattern = list(manual)
        engine.record_manual_version("Drums")
        engine.undo("Drums")
        assert engine.recall("Drums", 1) is True
        assert track.lanes[0].pattern == manual
        assert track.mutation_count == 1


class TestEvolveAfterManualEdit:
    def test_evolve_applies_drift_and_cuts_future(self) -> None:
        """evolve после ручной правки: дрейф поверх, будущее отрезается."""
        engine, track = _engine_with_drum()
        manual = [1, 0, 0, 1] + [0] * 12
        track.lanes[0].pattern = list(manual)
        engine.record_manual_version("Drums")
        manual_snapshot = track.snapshot()
        # Откат к корню, затем evolve: push отрезает ручную версию (v1).
        engine.undo("Drums")
        engine.request_mutation("Drums", cycle_beats=4.0)
        engine.tick(0.0)
        engine.tick(4.0)
        assert engine.history_len("Drums") == 2
        assert engine.current_version("Drums") == 1
        # Текущая версия — дрейф от корня, не отрезанная ручная правка.
        assert track.snapshot() != manual_snapshot
        assert engine.get_state("Drums").mutation_count == 1

    def test_evolve_drifts_from_manual_pattern(self) -> None:
        """Без отката: дрейф применяется к установленному вручную паттерну."""
        engine, track = _engine_with_drum()
        manual = [1, 0, 0, 1] + [0] * 12
        track.lanes[0].pattern = list(manual)
        engine.record_manual_version("Drums")
        manual_snapshot = track.snapshot()
        engine.request_mutation("Drums", cycle_beats=4.0)
        engine.tick(0.0)
        engine.tick(4.0)
        # Мутация меняет 1–2 ячейки по всей сетке (lane выбирается из всех
        # 16 rng'ом самой дорожки), поэтому расхождение считается по
        # снимку целиком — детерминированно.
        after = track.snapshot()
        changed = sum(
            1
            for lane_after, lane_manual in zip(after, manual_snapshot, strict=True)
            for cell_after, cell_manual in zip(lane_after, lane_manual, strict=True)
            if cell_after != cell_manual
        )
        assert 1 <= changed <= 2
        assert engine.history_len("Drums") == 3
