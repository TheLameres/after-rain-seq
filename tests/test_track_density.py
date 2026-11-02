"""Макро-ось DEN: density влияет на generators (план D2 §3.6).

- chord_slicer (stab): число pulses евклида масштабируется на density,
  кламп 1..steps; DEN=1 → базовый рисунок, DEN=0 → 25% базовой плотности.
- free_mono (bass/lead): детерминированное разрежение шагов по индексу.
"""

from __future__ import annotations

from src.session.engine.generators import (
    GenerationContext,
    _density_pulses,
    generate_notes,
)
from src.session.events.chord_event import ChordEvent
from src.session.model.melodic_track import MelodicTrack


def _stab_ctx(density: float) -> GenerationContext:
    track = MelodicTrack("Stab 1", profile_name="stab")
    track.density = density
    window = (ChordEvent(beat=0.0, degrees=(0, 2, 4), duration=4.0, voicing="1-3-5"),)
    return GenerationContext(track=track, chord_window=window)


def _bass_track(density: float) -> MelodicTrack:
    track = MelodicTrack("Bass 1", profile_name="bass")
    track.density = density
    track.degrees = [0, 1, 2, 3]
    return track


class TestDensityPulses:
    def test_full_density_is_base(self) -> None:
        assert _density_pulses(base_pulses=4, steps=16, density=1.0) == 4

    def test_zero_density_is_quarter(self) -> None:
        assert _density_pulses(base_pulses=4, steps=16, density=0.0) == 1

    def test_clamped_at_least_one(self) -> None:
        assert _density_pulses(base_pulses=1, steps=16, density=0.0) == 1

    def test_clamped_at_steps(self) -> None:
        assert _density_pulses(base_pulses=20, steps=16, density=1.0) == 16

    def test_half_density(self) -> None:
        # round(4 * (0.25 + 0.375)) = round(2.5) = 2
        assert _density_pulses(base_pulses=4, steps=16, density=0.5) == 2


class TestSlicerDensity:
    def test_full_density_plays_base_pattern(self) -> None:
        notes = generate_notes(_stab_ctx(density=1.0))
        # pulses=4 → 4 активных шага × 3 ступени аккорда
        assert len(notes) == 12

    def test_zero_density_thins_to_quarter(self) -> None:
        notes = generate_notes(_stab_ctx(density=0.0))
        # pulses=1 → 1 активный шаг × 3 ступени
        assert len(notes) == 3

    def test_density_between_scales_linearly(self) -> None:
        half = generate_notes(_stab_ctx(density=0.5))
        assert len(half) == 6  # pulses=2 × 3 ступени

    def test_deterministic_across_regenerations(self) -> None:
        a = generate_notes(_stab_ctx(density=0.4))
        b = generate_notes(_stab_ctx(density=0.4))
        assert [(n.beat, n.degree) for n in a] == [(n.beat, n.degree) for n in b]


class TestFreeMonoDensity:
    def test_full_density_keeps_all_notes(self) -> None:
        track = _bass_track(density=1.0)
        notes = generate_notes(GenerationContext(track=track))
        assert len(notes) == 4

    def test_zero_density_keeps_accent_only(self) -> None:
        track = _bass_track(density=0.0)
        notes = generate_notes(GenerationContext(track=track))
        # Только акцент (индекс 0); остальные проходят порог 0.25 случайно,
        # но детерминированно — для 4 нот хэш даёт ровно одну.
        assert len(notes) >= 1
        assert all(n.velocity == track.profile.pattern.velocity_accent for n in notes)

    def test_zero_density_thins_not_silences(self) -> None:
        """DEN=0 — «почти пусто», но не тишина: акцент всегда играет."""
        track = _bass_track(density=0.0)
        notes = generate_notes(GenerationContext(track=track))
        assert len(notes) >= 1
        assert notes[0].beat == 0.0

    def test_deterministic_across_regenerations(self) -> None:
        a = generate_notes(GenerationContext(track=_bass_track(0.3)))
        b = generate_notes(GenerationContext(track=_bass_track(0.3)))
        assert [(n.beat, n.degree) for n in a] == [(n.beat, n.degree) for n in b]

    def test_default_density_unchanged(self) -> None:
        """По умолчанию density=1.0 — звук не меняется для существующих сессий."""
        track = MelodicTrack("Bass 1", profile_name="bass")
        track.degrees = [0, 1, 2, 3]
        assert track.density == 1.0
        notes = generate_notes(GenerationContext(track=track))
        assert len(notes) == 4


class TestChordSourceIgnoresDensity:
    """chord_source (pad/atmos) не применяет density — план D2 §3.5."""

    def test_pad_ignores_density(self) -> None:
        track = MelodicTrack("Pad 1", profile_name="pad")
        track.density = 0.0
        full = generate_notes(GenerationContext(track=track))
        track.density = 1.0
        assert generate_notes(GenerationContext(track=track)) == full
