"""Тесты для generators — генерация нот по профилям (C6, шаг 2)."""

from __future__ import annotations

import pytest

from src.session.engine.generators import (
    GenerationContext,
    chord_degrees_for,
    generate_notes,
    pattern_length,
)
from src.session.model.melodic_track import MelodicTrack
from src.session.mutation.note_drift import NoteDrift
from src.session.mutation.param_drift import ParamDrift


def _pad(degrees: list[int] | None = None) -> MelodicTrack:
    """Pad-дорожка с дефолтными параметрами профиля."""
    return MelodicTrack(
        name="Pad 1",
        profile_name="pad",
        channel=0,
        degrees=degrees if degrees is not None else [0, 3],
    )


class TestChordDegreesFor:
    """Общая математика войсинга + обращения."""

    def test_triad_from_tonic(self) -> None:
        """Триада 1-3-5 от тоники: (0, 2, 4)."""
        assert chord_degrees_for(_pad(), 0) == (0, 2, 4)

    def test_triad_from_degree(self) -> None:
        """Триада от ступени 3: (3, 5, 7)."""
        assert chord_degrees_for(_pad(), 3) == (3, 5, 7)

    def test_inversion_applied(self) -> None:
        """Обращение поднимает нижние ступени на октаву."""
        track = _pad()
        track.inversion = 1
        assert chord_degrees_for(track, 0) == (2, 4, 7)


class TestPatternLength:
    """Длина паттерна по спецификации профиля."""

    def test_pad(self) -> None:
        """pad: число ступеней прогрессии."""
        assert pattern_length(_pad([0, 3, 2, 0])) == 4.0

    def test_atmos(self) -> None:
        """atmos: n ступеней × change_every (8) — один аккорд надолго."""
        track = MelodicTrack(name="Atmos 1", profile_name="atmos", degrees=[0, 3])
        assert pattern_length(track) == 16.0

    def test_texture(self) -> None:
        """texture: change_every (8) — редкая одиночная нота."""
        track = MelodicTrack(name="Texture 1", profile_name="texture")
        assert pattern_length(track) == 8.0

    def test_cc_only_zero(self) -> None:
        """cc_only: 0.0 (нет паттерна нот)."""
        track = MelodicTrack(name="CC 1", profile_name="cc_filter")
        assert pattern_length(track) == 0.0

    def test_empty_degrees_zero(self) -> None:
        """Пустая прогрессия запрещена сеттером (A2, §8.2): тишина — это mute.

        Защитная ветка ``pattern_length == 0.0`` остаётся для повреждённого
        состояния в обход сеттера.
        """
        with pytest.raises(ValueError):
            _pad([])
        track = _pad()
        track._degrees = ()
        assert pattern_length(track) == 0.0


class TestChordSource:
    """Генератор chord_source (pad, atmos)."""

    def test_pad_chords_and_gates(self) -> None:
        """pad: аккорд на каждую ступень, длительность = гейт."""
        notes = generate_notes(GenerationContext(track=_pad()))
        # 2 ступени × триада 1-3-5
        assert len(notes) == 6
        assert sorted({n.beat for n in notes}) == [0.0, 1.0]
        # Длительность = слот (1.0) × гейт (0.9)
        assert all(n.duration == pytest.approx(0.9) for n in notes)
        # Ступени аккордов
        beats0 = sorted(n.degree for n in notes if n.beat == 0.0)
        beats1 = sorted(n.degree for n in notes if n.beat == 1.0)
        assert beats0 == [0, 2, 4]
        assert beats1 == [3, 5, 7]

    def test_pad_velocity_accent_on_downbeat(self) -> None:
        """Первая нота паттерна акцентирована, остальные базовые."""
        notes = generate_notes(GenerationContext(track=_pad()))
        by_beat: dict[float, list[int]] = {}
        for n in notes:
            by_beat.setdefault(n.beat, []).append(n.velocity)
        assert set(by_beat[0.0]) == {92}  # velocity_accent профиля pad
        assert set(by_beat[1.0]) == {78}  # velocity_base

    def test_atmos_long_chords(self) -> None:
        """atmos: аккорд держится change_every=8 beats, паттерн 16."""
        track = MelodicTrack(name="Atmos 1", profile_name="atmos", degrees=[0, 3])
        notes = generate_notes(GenerationContext(track=track))
        assert len(notes) == 8  # 2 ступени × септаккорд 1-3-5-7
        assert sorted({n.beat for n in notes}) == [0.0, 8.0]
        assert all(n.duration == pytest.approx(8.0) for n in notes)  # gate 1.0

    def test_param_drift_gate_and_register(self) -> None:
        """ParamDrift меняет гейт и регистр (канал мутации R2)."""
        import random

        drift = ParamDrift()
        drift.add_param("gate", base=0.9, lo=0.1, hi=1.0, step=0.05)
        drift.add_param("density", base=0.5, lo=0.0, hi=1.0, step=0.1)
        drift.add_param("register", base=0.0, lo=-2.0, hi=2.0, step=1.0)
        rng = random.Random(42)
        for _ in range(5):
            drift.drift_one(rng)  # дрейфуем — как MutationEngine.tick()
        notes = generate_notes(GenerationContext(track=_pad(), param_drift=drift))
        # Гейт нот = текущий (возможно продугий) гейт из дрейфа
        assert all(n.duration == pytest.approx(drift.get("gate")) for n in notes)
        # Регистр = округлённый сдвиг октавы
        assert all(n.octave_offset == round(drift.get("register")) for n in notes)


class TestFreeMono:
    """Генератор free_mono (bass, lead, texture)."""

    def test_bass_roots(self) -> None:
        """bass: одна нота на ступень, короткий гейт, акцент на первой."""
        track = MelodicTrack(name="Bass 1", profile_name="bass", degrees=[0, 3, 2, 0])
        notes = generate_notes(GenerationContext(track=track))
        assert len(notes) == 4
        assert [n.degree for n in notes] == [0, 3, 2, 0]
        assert [n.beat for n in notes] == [0.0, 1.0, 2.0, 3.0]
        assert all(n.duration == pytest.approx(0.8) for n in notes)  # gate 0.8
        assert notes[0].velocity == 110  # акцент
        assert all(n.velocity == 100 for n in notes[1:])  # базовая

    def test_lead_uses_note_drift(self) -> None:
        """lead: ступени из NoteDrift, не из базовой прогрессии."""
        track = MelodicTrack(name="Lead 1", profile_name="lead", degrees=[0, 2, 4, 2])
        drift = NoteDrift(base_degrees=[0, 2, 4, 2], scale_length=7)
        drift._current = [1, 2, 5, 2]  # продугие ступени
        notes = generate_notes(GenerationContext(track=track, note_drift=drift))
        assert [n.degree for n in notes] == [1, 2, 5, 2]

    def test_texture_sparse(self) -> None:
        """texture: одна нота на паттерн длиной change_every."""
        track = MelodicTrack(name="Texture 1", profile_name="texture")
        notes = generate_notes(GenerationContext(track=track))
        assert len(notes) == 1
        assert notes[0].beat == 0.0
        assert notes[0].duration == pytest.approx(8.0 * 0.5)  # 8 beats × gate 0.5


class TestSlicerAndCcOnly:
    """Slicer (шаг 3) и cc_only — сейчас молчат."""

    def test_slicer_without_window_silent(self) -> None:
        """chord_slicer без окна аккордов — тишина (стратегия B)."""
        track = MelodicTrack(name="Sub 1", profile_name="sub")
        assert generate_notes(GenerationContext(track=track)) == []

    def test_cc_only_no_notes(self) -> None:
        """cc_only — нот нет."""
        track = MelodicTrack(name="CC 1", profile_name="cc_filter")
        assert generate_notes(GenerationContext(track=track)) == []

    def test_empty_progression_silent(self) -> None:
        """Повреждённое состояние (пустой degrees в обход сеттера) — тишина, не падение."""
        track = _pad()
        track._degrees = ()
        assert generate_notes(GenerationContext(track=track)) == []
