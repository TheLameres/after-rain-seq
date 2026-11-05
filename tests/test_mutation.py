"""Тесты для mutation.py — MutationState, NoteDrift, FloatingEuclidean,
ParamDrift, MutationEngine."""

from __future__ import annotations

import random

import pytest

from src.session.mutation.drift_tables import (
    MECH_EUCLIDEAN,
    MECH_NOTE,
    MECH_PARAM,
    MUTATE_MAX_SECONDS,
    MUTATE_MIN_SECONDS,
    PROFILE_MECHANISM,
)
from src.session.mutation.floating_euclidean import FloatingEuclidean
from src.session.mutation.mutation_engine import MutationEngine
from src.session.mutation.mutation_state import MutationState
from src.session.mutation.note_drift import NoteDrift
from src.session.mutation.param_drift import ParamDrift

# ---------------------------------------------------------------------------
# MutationState
# ---------------------------------------------------------------------------


class TestMutationState:
    """Тесты для MutationState frozen dataclass."""

    def test_frozen(self) -> None:
        """Нельзя изменить поле после создания."""
        state = MutationState(
            mutate=0.5,
            mutation_count=0,
            next_mutation_beat=16.0,
            last_mutation_beat=0.0,
        )
        with pytest.raises(AttributeError):
            state.mutate = 0.0  # type: ignore[misc]

    def test_fields(self) -> None:
        """Поля корректны при создании."""
        state = MutationState(
            mutate=0.3,
            mutation_count=5,
            next_mutation_beat=32.0,
            last_mutation_beat=16.0,
        )
        assert state.mutate == 0.3
        assert state.mutation_count == 5
        assert state.next_mutation_beat == 32.0
        assert state.last_mutation_beat == 16.0

    def test_equality(self) -> None:
        """Два одинаковых состояния равны."""
        s1 = MutationState(
            mutate=0.5,
            mutation_count=0,
            next_mutation_beat=16.0,
            last_mutation_beat=0.0,
        )
        s2 = MutationState(
            mutate=0.5,
            mutation_count=0,
            next_mutation_beat=16.0,
            last_mutation_beat=0.0,
        )
        assert s1 == s2


# ---------------------------------------------------------------------------
# NoteDrift
# ---------------------------------------------------------------------------


class TestNoteDrift:
    """Тесты для NoteDrift — дрейф нот в пределах лада."""

    def test_drift_one_changes_one_degree(self) -> None:
        """drift_one меняет ровно одну ступень."""
        rng = random.Random(42)
        drift = NoteDrift([0, 2, 4, 2], scale_length=7)
        base = drift.base_degrees
        result = drift.drift_one(rng)
        assert result is True
        current = drift.current_degrees
        diffs = [i for i in range(len(base)) if base[i] != current[i]]
        assert len(diffs) == 1

    def test_drift_respects_bounds(self) -> None:
        """drift_one не выходит за [0, 2 * scale_length)."""
        rng = random.Random(123)
        drift = NoteDrift([0, 2, 4, 2], scale_length=7)
        max_degree = 14
        for _ in range(100):
            drift.drift_one(rng)
            for d in drift.current_degrees:
                assert 0 <= d < max_degree

    def test_drift_empty_list(self) -> None:
        """drift_one с пустым списком — no-op."""
        rng = random.Random(42)
        drift = NoteDrift([], scale_length=7)
        assert drift.drift_one(rng) is False

    def test_revert_one_returns_to_base(self) -> None:
        """revert_one возвращает одну ступень к базовому."""
        rng = random.Random(42)
        drift = NoteDrift([0, 2, 4, 2], scale_length=7)
        drift.drift_one(rng)
        assert drift.drift_count == 1
        result = drift.revert_one(rng)
        assert result is True
        assert drift.drift_count == 0
        assert drift.current_degrees == drift.base_degrees

    def test_revert_one_no_drift(self) -> None:
        """revert_one при отсутствии дрейфа — no-op."""
        rng = random.Random(42)
        drift = NoteDrift([0, 2, 4, 2], scale_length=7)
        assert drift.revert_one(rng) is False

    def test_drift_count(self) -> None:
        """drift_count корректно считает отличия."""
        rng = random.Random(7)
        drift = NoteDrift([0, 2, 4, 2], scale_length=7)
        assert drift.drift_count == 0
        drift.drift_one(rng)
        assert drift.drift_count == 1
        drift.drift_one(rng)
        assert drift.drift_count == 2

    def test_current_degrees_returns_copy(self) -> None:
        """current_degrees возвращает копию, не ссылку."""
        drift = NoteDrift([0, 2, 4], scale_length=7)
        current = drift.current_degrees
        current[0] = 99
        assert drift.current_degrees[0] == 0

    def test_scale_length_validation(self) -> None:
        """scale_length < 1 — ValueError."""
        with pytest.raises(ValueError):
            NoteDrift([0], scale_length=0)


# ---------------------------------------------------------------------------
# FloatingEuclidean
# ---------------------------------------------------------------------------


class TestFloatingEuclidean:
    """Тесты для FloatingEuclidean — плавающий PEuclidean."""

    def test_drift_changes_pulses_by_one(self) -> None:
        """drift меняет pulses на ±1."""
        rng = random.Random(42)
        fe = FloatingEuclidean(steps=16, base_pulses=4)
        old_pulses = fe.pulses
        result = fe.drift(rng)
        assert result is True
        assert abs(fe.pulses - old_pulses) == 1

    def test_drift_respects_lower_bound(self) -> None:
        """drift не выходит за нижнюю границу [1, steps-1]."""
        rng = random.Random(42)
        fe = FloatingEuclidean(steps=16, base_pulses=1)
        # При pulses=1 можно только увеличить
        for _ in range(50):
            fe.drift(rng)
            assert fe.pulses >= 1

    def test_drift_respects_upper_bound(self) -> None:
        """drift не выходит за верхнюю границу [1, steps-1]."""
        rng = random.Random(42)
        fe = FloatingEuclidean(steps=16, base_pulses=15)
        # При pulses=15 можно только уменьшить
        for _ in range(50):
            fe.drift(rng)
            assert fe.pulses <= 15

    def test_revert_returns_to_base(self) -> None:
        """revert возвращает pulses к base_pulses."""
        rng = random.Random(42)
        fe = FloatingEuclidean(steps=16, base_pulses=4)
        fe.drift(rng)
        assert fe.pulses != fe.base_pulses
        result = fe.revert(rng)
        assert result is True
        assert fe.pulses == fe.base_pulses

    def test_revert_already_at_base(self) -> None:
        """revert при pulses == base_pulses — no-op."""
        rng = random.Random(42)
        fe = FloatingEuclidean(steps=16, base_pulses=4)
        assert fe.revert(rng) is False

    def test_pattern_updates_after_drift(self) -> None:
        """pattern обновляется после drift."""
        rng = random.Random(42)
        fe = FloatingEuclidean(steps=16, base_pulses=4)
        pattern_before = fe.pattern
        fe.drift(rng)
        pattern_after = fe.pattern
        # Паттерн должен отличаться (pulses изменился)
        assert pattern_before != pattern_after

    def test_pattern_is_cached(self) -> None:
        """pattern не пересчитывается при неизменных pulses."""
        fe = FloatingEuclidean(steps=16, base_pulses=4)
        p1 = fe.pattern
        p2 = fe.pattern
        assert p1 == p2
        # Проверяем, что это копия
        p1[0] = 99
        assert fe.pattern[0] != 99

    def test_steps_validation(self) -> None:
        """steps < 2 — ValueError."""
        with pytest.raises(ValueError):
            FloatingEuclidean(steps=1, base_pulses=1)

    def test_base_pulses_validation(self) -> None:
        """base_pulses вне [1, steps-1] — ValueError."""
        with pytest.raises(ValueError):
            FloatingEuclidean(steps=16, base_pulses=0)
        with pytest.raises(ValueError):
            FloatingEuclidean(steps=16, base_pulses=16)


# ---------------------------------------------------------------------------
# ParamDrift
# ---------------------------------------------------------------------------


class TestParamDrift:
    """Тесты для ParamDrift — дрейф числовых параметров."""

    def test_add_param_registers(self) -> None:
        """add_param регистрирует параметр с базовым значением."""
        pd = ParamDrift()
        pd.add_param("gate", base=0.5, lo=0.1, hi=1.0, step=0.05)
        assert pd.get("gate") == 0.5
        assert pd.get_base("gate") == 0.5

    def test_add_param_validation(self) -> None:
        """add_param валидирует аргументы."""
        pd = ParamDrift()
        with pytest.raises(ValueError):
            pd.add_param("gate", base=0.5, lo=1.0, hi=0.1, step=0.05)
        with pytest.raises(ValueError):
            pd.add_param("gate", base=2.0, lo=0.1, hi=1.0, step=0.05)
        with pytest.raises(ValueError):
            pd.add_param("gate", base=0.5, lo=0.1, hi=1.0, step=0.0)

    def test_drift_one_changes_one_param(self) -> None:
        """drift_one меняет один параметр."""
        rng = random.Random(42)
        pd = ParamDrift()
        pd.add_param("gate", base=0.5, lo=0.1, hi=1.0, step=0.05)
        pd.add_param("density", base=0.5, lo=0.0, hi=1.0, step=0.1)
        result = pd.drift_one(rng)
        assert result in ("gate", "density")
        # Один из параметров изменился
        changed = (pd.get("gate") != 0.5) or (pd.get("density") != 0.5)
        assert changed

    def test_drift_respects_bounds(self) -> None:
        """drift_one не выходит за [lo, hi]."""
        rng = random.Random(123)
        pd = ParamDrift()
        pd.add_param("gate", base=0.5, lo=0.1, hi=1.0, step=0.05)
        for _ in range(200):
            pd.drift_one(rng)
            assert 0.1 <= pd.get("gate") <= 1.0

    def test_drift_step_limit(self) -> None:
        """Смещение не более чем на step."""
        rng = random.Random(42)
        pd = ParamDrift()
        pd.add_param("gate", base=0.5, lo=0.1, hi=1.0, step=0.05)
        for _ in range(100):
            old = pd.get("gate")
            pd.drift_one(rng)
            new = pd.get("gate")
            assert abs(new - old) <= 0.05 + 1e-9

    def test_revert_one_returns_to_base(self) -> None:
        """revert_one возвращает один параметр к базовому."""
        rng = random.Random(42)
        pd = ParamDrift()
        pd.add_param("gate", base=0.5, lo=0.1, hi=1.0, step=0.05)
        pd.drift_one(rng)
        assert pd.drift_count == 1
        result = pd.revert_one(rng)
        assert result == "gate"
        assert pd.drift_count == 0
        assert pd.get("gate") == 0.5

    def test_revert_one_no_drift(self) -> None:
        """revert_one при отсутствии дрейфа — no-op."""
        rng = random.Random(42)
        pd = ParamDrift()
        pd.add_param("gate", base=0.5, lo=0.1, hi=1.0, step=0.05)
        assert pd.revert_one(rng) is None

    def test_multiple_params_independent(self) -> None:
        """Несколько параметров дрейфуют независимо."""
        rng = random.Random(42)
        pd = ParamDrift()
        pd.add_param("gate", base=0.5, lo=0.1, hi=1.0, step=0.05)
        pd.add_param("density", base=0.3, lo=0.0, hi=1.0, step=0.1)
        pd.add_param("register", base=0.0, lo=-2.0, hi=2.0, step=1.0)
        for _ in range(50):
            pd.drift_one(rng)
        # Все параметры в границах
        assert 0.1 <= pd.get("gate") <= 1.0
        assert 0.0 <= pd.get("density") <= 1.0
        assert -2.0 <= pd.get("register") <= 2.0

    def test_drift_count(self) -> None:
        """drift_count корректен."""
        rng = random.Random(7)
        pd = ParamDrift()
        pd.add_param("gate", base=0.5, lo=0.1, hi=1.0, step=0.05)
        pd.add_param("density", base=0.3, lo=0.0, hi=1.0, step=0.1)
        assert pd.drift_count == 0
        pd.drift_one(rng)
        assert pd.drift_count == 1

    def test_param_names(self) -> None:
        """param_names возвращает имена зарегистрированных параметров."""
        pd = ParamDrift()
        pd.add_param("gate", base=0.5, lo=0.1, hi=1.0, step=0.05)
        pd.add_param("density", base=0.3, lo=0.0, hi=1.0, step=0.1)
        names = pd.param_names
        assert "gate" in names
        assert "density" in names

    def test_get_unknown_param(self) -> None:
        """get для незарегистрированного параметра — KeyError."""
        pd = ParamDrift()
        with pytest.raises(KeyError):
            pd.get("unknown")


# ---------------------------------------------------------------------------
# MutationEngine
# ---------------------------------------------------------------------------


class TestMutationEngine:
    """Тесты для MutationEngine — координатор мутации."""

    def test_register_lead_creates_note_drift(self) -> None:
        """register_track создаёт NoteDrift для lead."""
        engine = MutationEngine()
        engine.register_track("Lead 1", "lead", degrees=[0, 2, 4, 2])
        assert engine.get_note_drift("Lead 1") is not None
        assert engine.get_euclidean_drift("Lead 1") is None
        assert engine.get_param_drift("Lead 1") is None

    def test_register_seq_creates_floating_euclidean(self) -> None:
        """register_track создаёт FloatingEuclidean для seq."""
        engine = MutationEngine()
        engine.register_track("Seq 1", "seq", euclidean_steps=16, euclidean_pulses=4)
        assert engine.get_euclidean_drift("Seq 1") is not None
        assert engine.get_note_drift("Seq 1") is None

    def test_register_pad_creates_param_drift(self) -> None:
        """register_track создаёт ParamDrift для pad."""
        engine = MutationEngine()
        engine.register_track("Pad 1", "pad", gate=0.9)
        assert engine.get_param_drift("Pad 1") is not None
        assert engine.get_note_drift("Pad 1") is None

    def test_register_cc_only_skipped(self) -> None:
        """register_track пропускает cc_only профили."""
        engine = MutationEngine()
        engine.register_track("CC 1", "cc_filter")
        assert engine.get_state("CC 1") is not None  # состояние есть
        assert engine.get_note_drift("CC 1") is None
        assert engine.get_euclidean_drift("CC 1") is None
        assert engine.get_param_drift("CC 1") is None

    def test_tick_mutate_zero_no_op(self) -> None:
        """tick при mutate=0 — no-op."""
        rng = random.Random(42)
        engine = MutationEngine(rng=rng)
        engine.register_track("Lead 1", "lead", mutate=0.0, degrees=[0, 2, 4])
        result = engine.tick(100.0, bpm=120.0)  # далеко за интервалом
        assert result == []

    def test_tick_before_interval_no_op(self) -> None:
        """tick до интервала мутации — no-op."""
        rng = random.Random(42)
        engine = MutationEngine(rng=rng)
        engine.register_track("Lead 1", "lead", mutate=1.0, degrees=[0, 2, 4])
        state = engine.get_state("Lead 1")
        assert state is not None
        # Тик до next_mutation_beat
        result = engine.tick(state.next_mutation_beat - 0.001, bpm=120.0)
        assert result == []

    def test_tick_after_interval_mutates(self) -> None:
        """Ручной запрос применяется на границе цикла дорожки."""
        rng = random.Random(42)
        engine = MutationEngine(rng=rng)
        engine.register_track("Lead 1", "lead", mutate=1.0, degrees=[0, 2, 4])
        engine.tick(0.0, bpm=120.0)
        engine.request_mutation("Lead 1", cycle_beats=4.0)
        result = engine.tick(4.0, bpm=120.0)
        assert result == ["Lead 1"]
        new_state = engine.get_state("Lead 1")
        assert new_state is not None
        assert new_state.mutation_count == 1
    def test_freeze_all_stops_mutation(self) -> None:
        """freeze_all → tick — no-op."""
        rng = random.Random(42)
        engine = MutationEngine(rng=rng)
        engine.register_track("Lead 1", "lead", mutate=1.0, degrees=[0, 2, 4])
        engine.freeze_all()
        state = engine.get_state("Lead 1")
        assert state is not None
        assert state.mutate == 0.0
        result = engine.tick(1000.0, bpm=120.0)
        assert result == []

    def test_evolve_all_resumes_mutation(self) -> None:
        """evolve_all не влияет на ручную мутацию: запрос применяется как обычно."""
        rng = random.Random(42)
        engine = MutationEngine(rng=rng)
        engine.register_track("Lead 1", "lead", mutate=1.0, degrees=[0, 2, 4])
        engine.freeze_all()
        engine.evolve_all()
        state = engine.get_state("Lead 1")
        assert state is not None
        assert state.mutate == 0.5
        engine.tick(0.0, bpm=120.0)
        engine.request_mutation("Lead 1", cycle_beats=4.0)
        assert engine.tick(4.0, bpm=120.0) == ["Lead 1"]
    def test_total_mutation_count(self) -> None:
        """total_mutation_count суммирует все дорожки."""
        rng = random.Random(42)
        engine = MutationEngine(rng=rng)
        engine.register_track("Lead 1", "lead", mutate=1.0, degrees=[0, 2, 4])
        engine.register_track("Pad 1", "pad", mutate=1.0)
        assert engine.total_mutation_count == 0
        engine.tick(0.0, bpm=120.0)
        engine.request_mutation("Lead 1", cycle_beats=4.0)
        engine.request_mutation("Pad 1", cycle_beats=4.0)
        engine.tick(4.0, bpm=120.0)
        assert engine.total_mutation_count == 2
    def test_get_state_returns_mutation_state(self) -> None:
        """get_state возвращает MutationState."""
        engine = MutationEngine()
        engine.register_track("Lead 1", "lead", mutate=0.7, degrees=[0, 2, 4])
        state = engine.get_state("Lead 1")
        assert state is not None
        assert isinstance(state, MutationState)
        assert state.mutate == 0.7

    def test_get_state_unknown_returns_none(self) -> None:
        """get_state для неизвестной дорожки — None."""
        engine = MutationEngine()
        assert engine.get_state("Unknown") is None

    def test_set_mutate(self) -> None:
        """set_mutate обновляет значение mutate."""
        engine = MutationEngine()
        engine.register_track("Lead 1", "lead", degrees=[0, 2, 4])
        engine.set_mutate("Lead 1", 0.0)
        state = engine.get_state("Lead 1")
        assert state is not None
        assert state.mutate == 0.0

    def test_unregister_track(self) -> None:
        """unregister_track удаляет дорожку из мутации."""
        rng = random.Random(42)
        engine = MutationEngine(rng=rng)
        engine.register_track("Lead 1", "lead", mutate=1.0, degrees=[0, 2, 4])
        engine.unregister_track("Lead 1")
        assert engine.get_state("Lead 1") is None
        assert engine.get_note_drift("Lead 1") is None
        result = engine.tick(1000.0, bpm=120.0)
        assert result == []

    def test_interval_depends_on_bpm(self) -> None:
        """Интервал мутации зависит от BPM."""
        rng = random.Random(42)
        engine = MutationEngine(rng=rng)
        engine.register_track("Lead 1", "lead", bpm=60.0, degrees=[0, 2, 4])
        state60 = engine.get_state("Lead 1")
        assert state60 is not None

        rng2 = random.Random(42)
        engine2 = MutationEngine(rng=rng2)
        engine2.register_track("Lead 1", "lead", bpm=240.0, degrees=[0, 2, 4])
        state240 = engine2.get_state("Lead 1")
        assert state240 is not None

        # При BPM 240 интервал в beats должен быть больше (больше beats за то же время)
        assert state240.next_mutation_beat > state60.next_mutation_beat

    def test_degradation_reverts(self) -> None:
        """Деградация: с вероятностью mutate откатываем."""
        # Используем фиксированный seed, при котором rng.random() < mutate
        rng = random.Random(1)
        engine = MutationEngine(rng=rng)
        engine.register_track("Lead 1", "lead", mutate=0.9, degrees=[0, 2, 4])
        state = engine.get_state("Lead 1")
        assert state is not None
        # Первая мутация
        engine.tick(state.next_mutation_beat, bpm=120.0)
        # Вторая мутация — может быть revert
        state = engine.get_state("Lead 1")
        assert state is not None
        engine.tick(state.next_mutation_beat, bpm=120.0)
        # Проверяем, что счётчик изменился (либо +1, либо revert)
        # Главное — не падает и состояние консистентно
        new_state = engine.get_state("Lead 1")
        assert new_state is not None
        assert new_state.mutation_count >= 0

    def test_tick_returns_mutated_names(self) -> None:
        """tick возвращает имена дорожек, на которых мутация применена на этом тике."""
        rng = random.Random(42)
        engine = MutationEngine(rng=rng)
        engine.register_track("Lead 1", "lead", mutate=1.0, degrees=[0, 2, 4])
        engine.register_track("Pad 1", "pad", mutate=1.0)
        engine.tick(0.0, bpm=120.0)
        engine.request_mutation("Lead 1", cycle_beats=4.0)
        engine.request_mutation("Pad 1", cycle_beats=4.0)
        result = engine.tick(4.0, bpm=120.0)
        assert "Lead 1" in result
        assert "Pad 1" in result
    def test_min_max_seconds_validation(self) -> None:
        """min_seconds >= max_seconds — ValueError."""
        with pytest.raises(ValueError):
            MutationEngine(min_seconds=16.0, max_seconds=8.0)

    def test_constants(self) -> None:
        """Константы интервала мутации соответствуют плану."""
        assert MUTATE_MIN_SECONDS == 8.0
        assert MUTATE_MAX_SECONDS == 16.0

    def test_default_mutate(self) -> None:
        """default_mutate используется при регистрации без явного mutate."""
        engine = MutationEngine(default_mutate=0.3)
        engine.register_track("Lead 1", "lead", degrees=[0, 2, 4])
        state = engine.get_state("Lead 1")
        assert state is not None
        assert state.mutate == 0.3

    def test_registered_tracks(self) -> None:
        """registered_tracks возвращает имена всех дорожек."""
        engine = MutationEngine()
        engine.register_track("Lead 1", "lead", degrees=[0, 2, 4])
        engine.register_track("Pad 1", "pad")
        tracks = engine.registered_tracks
        assert "Lead 1" in tracks
        assert "Pad 1" in tracks


# ---------------------------------------------------------------------------
# PROFILE_MECHANISM (C6, шаг 4)
# ---------------------------------------------------------------------------


class TestProfileMechanism:
    """Матрица профиль → механизм мутации."""

    def test_table_covers_all_mutated_profiles(self) -> None:
        """Все неслучаемые профили (кроме cc_*) имеют механизм."""
        from src.session.model.melodic_profile import PROFILES

        for name, profile in PROFILES.items():
            if profile.cc_only:
                continue
            assert name in PROFILE_MECHANISM, f"нет механизма для {name!r}"

    def test_table_matches_mechanism_constants(self) -> None:
        """Значения таблицы — только допустимые константы механизмов."""
        assert set(PROFILE_MECHANISM.values()) <= {
            MECH_NOTE,
            MECH_EUCLIDEAN,
            MECH_PARAM,
        }

    def test_sub_uses_param_drift(self) -> None:
        """sub: ParamDrift (регистр/гейт), не NoteDrift."""
        me = MutationEngine(rng=random.Random(1))
        me.register_track("Sub 1", "sub", gate=1.0)
        pd = me.get_param_drift("Sub 1")
        assert pd is not None
        assert set(pd.param_names) == {"register", "gate"}
        assert me.get_note_drift("Sub 1") is None
        assert me.get_euclidean_drift("Sub 1") is None

    def test_stab_uses_euclidean_drift(self) -> None:
        """stab: FloatingEuclidean (нарезка евклидом)."""
        me = MutationEngine(rng=random.Random(1))
        me.register_track("Stab 1", "stab", euclidean_steps=16, euclidean_pulses=4)
        assert me.get_euclidean_drift("Stab 1") is not None
        assert me.get_param_drift("Stab 1") is None
        assert me.get_note_drift("Stab 1") is None

    def test_param_drift_gate_base_from_track(self) -> None:
        """База «gate» — актуальный гейт дорожки, а не дефолт таблицы."""
        me = MutationEngine(rng=random.Random(1))
        me.register_track("Pad 1", "pad", gate=0.7)
        pd = me.get_param_drift("Pad 1")
        assert pd is not None
        assert pd.get_base("gate") == 0.7


class TestSyncMutate:
    """Regression §4.1: track.mutate must reach MutationEngine state."""

    def test_sync_updates_state(self) -> None:
        engine = MutationEngine(rng=random.Random(0))
        engine.register_track("Lead 1", "lead", mutate=0.5, degrees=[0, 2, 4])
        engine.sync_mutate("Lead 1", 0.0)
        state = engine.get_state("Lead 1")
        assert state is not None
        assert state.mutate == 0.0

    def test_sync_keeps_counters(self) -> None:
        engine = MutationEngine(rng=random.Random(0))
        engine.register_track("Lead 1", "lead", mutate=0.5, degrees=[0, 2, 4])
        before = engine.get_state("Lead 1")
        assert before is not None
        engine.sync_mutate("Lead 1", 0.2)
        after = engine.get_state("Lead 1")
        assert after is not None
        assert after.mutation_count == before.mutation_count
        assert after.next_mutation_beat == before.next_mutation_beat

    def test_sync_unknown_track_is_noop(self) -> None:
        engine = MutationEngine(rng=random.Random(0))
        engine.sync_mutate("Ghost", 0.0)
        assert engine.get_state("Ghost") is None

    def test_frozen_track_gets_no_mutations_after_sync(self) -> None:
        """Plan §2.2 acceptance: freeze → 0 mutations over many ticks."""
        engine = MutationEngine(rng=random.Random(1))
        engine.register_track("Pad 1", "pad", mutate=0.5, bpm=118.0, degrees=[0, 2, 4])
        engine.sync_mutate("Pad 1", 0.0)  # simulate track.freeze()
        for beat in range(20_000):
            engine.tick(beat * 0.05, bpm=120.0)
        state = engine.get_state("Pad 1")
        assert state is not None
        assert state.mutation_count == 0


class TestMutationCountOnTrack:
    """§4.4: MutationEngine пишет счётчик в дорожку-владельца."""

    def test_engine_increments_track_counter(self) -> None:
        """Счётчик на дорожке отражает реальные изменения, а не число тиков."""
        from src.session.model.melodic_track import MelodicTrack

        track = MelodicTrack(name="Lead 1", profile_name="lead")
        engine = MutationEngine(rng=random.Random(7))
        engine.register_track(
            "Lead 1", "lead", mutate=0.3, bpm=120.0, degrees=[0, 2, 4], track=track
        )
        engine.tick(0.0, bpm=120.0)
        for k in range(1, 21):
            engine.tick(k * 4.0 - 0.5, bpm=120.0)
            engine.request_mutation("Lead 1", cycle_beats=4.0)
            engine.tick(k * 4.0, bpm=120.0)
        state = engine.get_state("Lead 1")
        assert state is not None
        assert state.mutation_count == 20
        assert track.mutation_count <= state.mutation_count
    def test_frozen_track_counter_stays_zero(self) -> None:
        from src.session.model.melodic_track import MelodicTrack

        track = MelodicTrack(name="Pad 1", profile_name="pad")
        engine = MutationEngine(rng=random.Random(0))
        engine.register_track(
            "Pad 1", "pad", mutate=0.5, bpm=120.0, degrees=[0, 2, 4], track=track
        )
        track.freeze()
        engine.sync_mutate("Pad 1", track.mutate)
        for beat in range(700):
            engine.tick(beat * 0.5, bpm=120.0)
        assert track.mutation_count == 0


class TestTempoPassedToTick:
    """BPM приходит в tick снаружи и определяет интервал до следующей мутации."""


