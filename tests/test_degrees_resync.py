"""Ресинк механизмов мутации с треком по ``revision`` (этап B1).

Закрывает Д6 (NoteDrift держит снимок degrees) и Д7 (set_profile не
пересоздаёт механизм) из плана degrees_voicing_plan §2.
"""

from __future__ import annotations

import queue
import random

import pytest

from src.harmony.harmony import Harmony
from src.session.engine.generators import GenerationContext, generate_notes
from src.session.engine.melodic_engine import MelodicEngine
from src.session.model.melodic_track import MelodicTrack
from src.session.mutation.mutation_engine import MutationEngine
from src.session.mutation.note_drift import NoteDrift
from src.session.mutation.param_drift import ParamDrift


def _engine_with(track: MelodicTrack, mutate: float = 0.0) -> MutationEngine:
    me = MutationEngine(rng=random.Random(7))
    me.register_track(
        track.name,
        track.profile_name,
        mutate=mutate,
        degrees=list(track.degrees),
        gate=track.gate,
        track=track,
    )
    return me


# ---------------------------------------------------------------------------
# NoteDrift.set_base
# ---------------------------------------------------------------------------


class TestNoteDriftSetBase:
    def test_replaces_base_and_current(self) -> None:
        d = NoteDrift([0, 2, 4])
        d.drift_one(random.Random(1))
        d.set_base([5, 5, 5])
        assert d.base_degrees == [5, 5, 5]
        assert d.current_degrees == [5, 5, 5]
        assert d.drift_count == 0

    def test_length_change_does_not_break_drift_and_revert(self) -> None:
        d = NoteDrift([0, 2, 4, 2])
        d.drift_one(random.Random(1))
        d.set_base([1, 2])
        rng = random.Random(3)
        for _ in range(50):
            d.drift_one(rng)
            d.revert_one(rng)
        assert len(d.current_degrees) == 2

    def test_length_change_logs_info(self, caplog: pytest.LogCaptureFixture) -> None:
        d = NoteDrift([0, 2, 4])
        with caplog.at_level("INFO", logger="src.session.mutation.note_drift"):
            d.set_base([0, 1])
        assert any("длина базы" in r.message for r in caplog.records)

    def test_same_length_no_info_log(self, caplog: pytest.LogCaptureFixture) -> None:
        d = NoteDrift([0, 2, 4])
        with caplog.at_level("INFO", logger="src.session.mutation.note_drift"):
            d.set_base([1, 1, 1])
        assert not caplog.records

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            NoteDrift([0]).set_base([])

    def test_input_is_copied(self) -> None:
        d = NoteDrift([0])
        src = [3, 4]
        d.set_base(src)
        src.append(9)
        assert d.base_degrees == [3, 4]


# ---------------------------------------------------------------------------
# Д6: правка degrees у lead доходит до drift и до нот
# ---------------------------------------------------------------------------


class TestDegreesReachDrift:
    def test_lead_degrees_edit_reaches_drift_on_tick(self) -> None:
        t = MelodicTrack(name="L", profile_name="lead", degrees=[0, 2, 4])
        me = _engine_with(t)
        drift = me.get_note_drift("L")
        assert drift is not None
        t.degrees = [5, 5, 5]
        t.commit_pending_degrees()  # граница ступени (B2)
        assert drift.current_degrees == [0, 2, 4]  # до тика — старое
        me.tick(0.0, 120.0)
        assert drift.current_degrees == [5, 5, 5]
        assert me.get_note_drift("L") is drift  # тот же объект, не пересоздан

    def test_lead_degrees_edit_reaches_generated_notes(self) -> None:
        t = MelodicTrack(name="L", profile_name="lead", degrees=[0, 2, 4])
        me = _engine_with(t)
        t.degrees = [6, 6, 6]
        t.commit_pending_degrees()  # граница ступени (B2)
        me.tick(0.0, 120.0)
        ctx = GenerationContext(track=t, note_drift=me.get_note_drift("L"))
        assert {n.degree for n in generate_notes(ctx)} == {6}

    def test_texture_degrees_edit_reaches_notes(self) -> None:
        t = MelodicTrack(name="T", profile_name="texture", degrees=[0, 2])
        me = _engine_with(t)
        t.degrees = [4, 1]
        t.commit_pending_degrees()  # граница ступени (B2)
        me.tick(0.0, 120.0)
        ctx = GenerationContext(track=t, note_drift=me.get_note_drift("T"))
        assert [n.degree for n in generate_notes(ctx)] == [4]

    def test_length_change_does_not_crash_next_ticks(self) -> None:
        t = MelodicTrack(name="L", profile_name="lead", degrees=[0, 2, 4, 2])
        me = _engine_with(t, mutate=1.0)
        beat = 0.0
        for _ in range(5):
            beat += 1000.0
            me.tick(beat, 120.0)
        t.degrees = [1, 2]
        t.commit_pending_degrees()  # граница ступени (B2)
        for _ in range(20):
            beat += 1000.0
            me.tick(beat, 120.0)
        assert len(me.get_note_drift("L").current_degrees) == 2  # type: ignore[union-attr]

    def test_tick_without_edit_does_not_reset_drift(self) -> None:
        """Без правки degrees ресинк не вызывается и накопленный дрейф живёт."""
        t = MelodicTrack(name="L", profile_name="lead", degrees=[0, 2, 4])
        me = _engine_with(t, mutate=1.0)
        me.tick(0.0, 120.0)
        me.request_mutation("L", cycle_beats=4.0)
        me.tick(4.0, 120.0)  # ровно одна мутация (count 0 -> всегда drift)
        drift = me.get_note_drift("L")
        assert drift is not None
        assert drift.drift_count == 1  # дрейф накоплен
        cur = drift.current_degrees
        me.tick(5000.0, 120.0)  # без запроса мутации нет, revision не менялась -> ресинка нет
        assert drift.current_degrees == cur
        assert drift.base_degrees == [0, 2, 4]

    def test_pad_degrees_edit_does_not_create_drift(self) -> None:
        t = MelodicTrack(name="P", profile_name="pad", degrees=[0, 3])
        me = _engine_with(t)
        t.degrees = [1, 2, 3]
        t.commit_pending_degrees()  # граница ступени (B2)
        me.tick(0.0, 120.0)
        assert me.get_note_drift("P") is None
        assert me.get_param_drift("P") is not None

    def test_mutation_count_preserved_on_degrees_edit(self) -> None:
        t = MelodicTrack(name="L", profile_name="lead", degrees=[0, 2, 4])
        me = _engine_with(t, mutate=1.0)
        me.tick(1000.0, 120.0)
        count_state = me.get_state("L").mutation_count  # type: ignore[union-attr]
        count_track = t.mutation_count
        t.degrees = [1, 2, 3]
        t.commit_pending_degrees()  # граница ступени (B2)
        me.tick(0.0, 120.0)  # раньше next_mutation_beat — мутации нет
        assert me.get_state("L").mutation_count == count_state  # type: ignore[union-attr]
        assert t.mutation_count == count_track

    def test_frozen_track_stays_frozen_after_degrees_edit(self) -> None:
        t = MelodicTrack(name="L", profile_name="lead", degrees=[0, 2, 4])
        me = _engine_with(t, mutate=1.0)
        t.freeze()
        me.sync_mutate("L", t.mutate)
        t.degrees = [3, 3, 3]
        t.commit_pending_degrees()  # граница ступени (B2)
        me.tick(10_000.0, 120.0)
        drift = me.get_note_drift("L")
        assert drift is not None
        assert drift.current_degrees == [3, 3, 3]  # правка дошла...
        assert drift.drift_count == 0  # ...но мутации нет
        assert me.get_state("L").mutate == 0.0  # type: ignore[union-attr]
        assert t.mutate == 0.0

    def test_edit_on_frozen_track_does_not_unfreeze_over_many_ticks(self) -> None:
        t = MelodicTrack(name="L", profile_name="lead", degrees=[0, 2, 4])
        me = _engine_with(t, mutate=1.0)
        t.freeze()
        me.sync_mutate("L", t.mutate)
        t.degrees = [3, 3, 3]
        t.commit_pending_degrees()  # граница ступени (B2)
        beat = 0.0
        for _ in range(30):
            beat += 1000.0
            me.sync_mutate("L", t.mutate)
            me.tick(beat, 120.0)
        assert me.get_note_drift("L").current_degrees == [3, 3, 3]  # type: ignore[union-attr]

    def test_noop_edit_does_not_reset_drift(self) -> None:
        t = MelodicTrack(name="L", profile_name="lead", degrees=[0, 2, 4])
        me = _engine_with(t, mutate=1.0)
        beat = 0.0
        for _ in range(6):
            beat += 1000.0
            me.tick(beat, 120.0)
        drift = me.get_note_drift("L")
        assert drift is not None
        cur = drift.current_degrees
        t.degrees = [0, 2, 4]  # то же значение — revision не растёт
        me.tick(beat, 120.0)
        assert drift.current_degrees == cur


# ---------------------------------------------------------------------------
# Д7: set_profile пересоздаёт механизм
# ---------------------------------------------------------------------------


class TestSetProfileRebuildsMechanism:
    def test_lead_to_pad_becomes_param_drift(self) -> None:
        t = MelodicTrack(name="X", profile_name="lead", degrees=[0, 2, 4])
        me = _engine_with(t)
        assert isinstance(me.get_note_drift("X"), NoteDrift)
        t.set_profile("pad")
        me.tick(0.0, 120.0)
        assert me.get_note_drift("X") is None
        assert isinstance(me.get_param_drift("X"), ParamDrift)

    def test_pad_to_lead_becomes_note_drift_with_track_degrees(self) -> None:
        t = MelodicTrack(name="X", profile_name="pad", degrees=[1, 3, 5])
        me = _engine_with(t)
        t.set_profile("lead")
        me.tick(0.0, 120.0)
        assert me.get_param_drift("X") is None
        nd = me.get_note_drift("X")
        assert nd is not None
        assert nd.base_degrees == [1, 3, 5]  # degrees сохранены (§8.5)

    def test_to_euclidean_profile(self) -> None:
        t = MelodicTrack(name="X", profile_name="pad")
        me = _engine_with(t)
        t.set_profile("seq")
        me.tick(0.0, 120.0)
        assert me.get_param_drift("X") is None
        assert me.get_euclidean_drift("X") is not None

    def test_track_profile_registry_updated(self) -> None:
        t = MelodicTrack(name="X", profile_name="lead")
        me = _engine_with(t)
        t.set_profile("pad")
        me.tick(0.0, 120.0)
        assert me._track_profiles["X"] == "pad"

    def test_profile_change_resets_counters_and_logs(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        t = MelodicTrack(name="X", profile_name="lead", degrees=[0, 2, 4])
        me = _engine_with(t, mutate=1.0)
        me.tick(0.0, 120.0)
        me.request_mutation("X", cycle_beats=4.0)
        me.tick(4.0, 120.0)
        assert t.mutation_count >= 1
        t.set_profile("pad")
        with caplog.at_level("INFO", logger="src.session.mutation.mutation_engine"):
            me.tick(8.0, 120.0)
        assert t.mutation_count == 0
        assert me.get_state("X").mutation_count == 0  # type: ignore[union-attr]
        assert any("механизм пересоздан" in r.message for r in caplog.records)

    def test_profile_change_keeps_mutate_and_schedule(self) -> None:
        t = MelodicTrack(name="X", profile_name="lead")
        me = _engine_with(t, mutate=0.7)
        nxt = me.get_state("X").next_mutation_beat  # type: ignore[union-attr]
        t.set_profile("pad")
        me.tick(0.0, 120.0)
        st = me.get_state("X")
        assert st is not None
        assert st.mutate == 0.7
        assert st.next_mutation_beat == nxt

    def test_frozen_track_stays_frozen_after_set_profile(self) -> None:
        t = MelodicTrack(name="X", profile_name="lead")
        me = _engine_with(t, mutate=1.0)
        t.freeze()
        me.sync_mutate("X", t.mutate)
        t.set_profile("pad")
        me.tick(10_000.0, 120.0)
        assert me.get_state("X").mutate == 0.0  # type: ignore[union-attr]
        assert me.get_param_drift("X").drift_count == 0  # type: ignore[union-attr]

    def test_generation_after_profile_switch_uses_new_family(self) -> None:
        t = MelodicTrack(name="X", profile_name="lead", degrees=[0, 3])
        me = _engine_with(t)
        t.set_profile("pad")
        me.tick(0.0, 120.0)
        ctx = GenerationContext(
            track=t,
            note_drift=me.get_note_drift("X"),
            param_drift=me.get_param_drift("X"),
        )
        notes = generate_notes(ctx)
        assert len(notes) == 2 * 3  # 2 ступени x аккорд 1-3-5


# ---------------------------------------------------------------------------
# refresh_track напрямую / служебное
# ---------------------------------------------------------------------------


class TestRefreshTrack:
    def test_unknown_track_is_noop(self) -> None:
        MutationEngine().refresh_track("nope")

    def test_explicit_degrees_argument(self) -> None:
        t = MelodicTrack(name="L", profile_name="lead", degrees=[0, 2, 4])
        me = _engine_with(t)
        me.refresh_track("L", degrees=[1, 1], bpm=120.0)
        assert me.get_note_drift("L").base_degrees == [1, 1]  # type: ignore[union-attr]

    def test_track_without_registered_ref_is_not_synced(self) -> None:
        """Совместимость: register_track без track= работает как раньше."""
        me = MutationEngine()
        me.register_track("L", "lead", degrees=[0, 2, 4])
        me.tick(0.0, 120.0)
        assert me.get_note_drift("L").base_degrees == [0, 2, 4]  # type: ignore[union-attr]

    def test_unregister_clears_revision_state(self) -> None:
        t = MelodicTrack(name="L", profile_name="lead")
        me = _engine_with(t)
        me.unregister_track("L")
        assert "L" not in me._track_revision
        assert "L" not in me._reg_params
        me.tick(0.0, 120.0)  # не падает

    def test_revision_resync_is_idempotent(self) -> None:
        t = MelodicTrack(name="L", profile_name="lead")
        me = _engine_with(t)
        t.degrees = [1, 2]
        t.commit_pending_degrees()  # граница ступени (B2)
        me.tick(0.0, 120.0)
        d = me.get_note_drift("L")
        me.tick(0.0, 120.0)
        assert me.get_note_drift("L") is d


# ---------------------------------------------------------------------------
# Сквозной: MelodicEngine -> ноты
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_melodic_engine_pattern_follows_degrees_edit(self) -> None:
        h = Harmony("A", "dorian")
        q: queue.Queue = queue.Queue(maxsize=4096)
        t = MelodicTrack(name="L", profile_name="lead", degrees=[0, 2, 4, 2])
        me = _engine_with(t)
        eng = MelodicEngine(t, h, q, "default", mutation_engine=me)
        assert [n.degree for n in eng._pattern()[0]] == [0, 2, 4, 2]
        t.degrees = [5, 5, 5, 5]
        t.commit_pending_degrees()  # граница ступени (B2)
        me.tick(0.0, 120.0)
        assert [n.degree for n in eng._pattern()[0]] == [5, 5, 5, 5]

    def test_pad_pattern_follows_degrees_edit_immediately(self) -> None:
        """pad читает track.degrees напрямую — без ресинка, сразу."""
        h = Harmony("A", "dorian")
        q: queue.Queue = queue.Queue(maxsize=4096)
        t = MelodicTrack(name="P", profile_name="pad", degrees=[0, 3])
        me = _engine_with(t)
        eng = MelodicEngine(t, h, q, "default", mutation_engine=me)
        n0 = len(eng._pattern()[0])
        t.degrees = [0, 3, 4]
        t.commit_pending_degrees()  # граница ступени (B2)
        assert len(eng._pattern()[0]) == n0 + 3
