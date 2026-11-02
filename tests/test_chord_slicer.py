"""Тесты для chord_slicer — нарезка ChordEvent источников (C6, шаг 3)."""

from __future__ import annotations

import random

import pytest

from src.session.engine.generators import (
    GenerationContext,
    chord_cycle,
    generate_notes,
    pattern_length_for,
)
from src.session.events.chord_event import ChordEvent
from src.session.model.melodic_track import MelodicTrack
from src.session.mutation.floating_euclidean import FloatingEuclidean


def _window(degrees: list[int] | None = None) -> tuple[ChordEvent, ...]:
    """Окно аккордов: outbox pad-дорожки после generate()."""
    pad = MelodicTrack(
        name="Pad 1",
        profile_name="pad",
        degrees=degrees if degrees is not None else [0, 3],
    )
    pad.generate()
    return tuple(pad.outbox)


def _track(profile: str) -> MelodicTrack:
    """Дорожка-slicer."""
    return MelodicTrack(name=f"{profile.title()} 1", profile_name=profile, channel=1)


class TestChordCycle:
    """Период цикла аккордов окна."""

    def test_cycle_from_window(self) -> None:
        """cycle = max(beat + duration): pad [0,3] → 2.0."""
        assert chord_cycle(_window()) == 2.0

    def test_cycle_empty(self) -> None:
        """Пустое окно → 0.0."""
        assert chord_cycle(()) == 0.0

    def test_pattern_length_for_slicer(self) -> None:
        """Slicer живёт циклом аккордов, не длиной degrees."""
        ctx = GenerationContext(track=_track("seq"), chord_window=_window())
        assert pattern_length_for(ctx) == 2.0

    def test_pattern_length_for_source_unchanged(self) -> None:
        """Несlicer-профиль не зависит от окна."""
        pad = MelodicTrack(name="Pad 1", profile_name="pad", degrees=[0, 3])
        ctx = GenerationContext(track=pad)
        assert pattern_length_for(ctx) == 2.0


class TestSub:
    """sub: корень аккорда со сдвигом."""

    def test_root_shifted(self) -> None:
        """Одна нота на аккорд: корень, старт на beat + 0.25 * duration."""
        ctx = GenerationContext(track=_track("sub"), chord_window=_window())
        notes = generate_notes(ctx)
        assert len(notes) == 2  # два аккорда в окне
        # Аккорд 0 (ступени 0,2,4) на beat 0: корень 0, старт 0.25
        n0 = next(n for n in notes if abs(n.beat - 0.25) < 1e-9)
        assert n0.degree == 0
        assert n0.duration == pytest.approx(1.0)  # gate sub = 1.0
        # Аккорд 1 (ступени 3,5,7) на beat 1: корень 3, старт 1.25
        n1 = next(n for n in notes if abs(n.beat - 1.25) < 1e-9)
        assert n1.degree == 3

    def test_respects_source_chords(self) -> None:
        """Ноты sub — корни именно аккордов источника."""
        window = _window([4, 0])  # аккорды от IV и I
        ctx = GenerationContext(track=_track("sub"), chord_window=window)
        notes = generate_notes(ctx)
        assert sorted(n.degree for n in notes) == [0, 4]


class TestStab:
    """stab: аккорд целиком на евклидовых шагах."""

    def test_euclid_hits_whole_chord(self) -> None:
        """Евклид(16,4): 4 удара × 3 ступени = 12 нот на аккорд, 24 на окно."""
        ctx = GenerationContext(track=_track("stab"), chord_window=_window())
        notes = generate_notes(ctx)
        assert len(notes) == 24
        # Первый шаг каждого аккорда акцентирован (velocity_accent stab = 115)
        accented_beats = {0.0, 1.0}  # старт аккордов окна
        assert all(
            n.velocity == (115 if n.beat in accented_beats else 95) for n in notes
        )

    def test_euclidean_drift_changes_hits(self) -> None:
        """FloatingEuclidean меняет паттерн ударов (мутация слышна)."""
        track = _track("stab")
        base = generate_notes(GenerationContext(track=track, chord_window=_window()))
        fe = FloatingEuclidean(steps=16, base_pulses=4)
        fe.drift(rng=random.Random(7))  # pulses 4 → 3 или 5
        drifted = generate_notes(
            GenerationContext(track=track, chord_window=_window(), euclidean=fe)
        )
        assert len(drifted) != len(base)


class TestSeq:
    """seq: ступени аккорда по сетке с паузами."""

    def test_cycles_chord_tones(self) -> None:
        """Каждый активный шаг играет следующую ступень аккорда."""
        ctx = GenerationContext(track=_track("seq"), chord_window=_window())
        notes = generate_notes(ctx)
        # Евклид(16,6): 6 активных шагов на аккорд × 2 аккорда
        assert len(notes) == 12
        # Шаги аккорда 0 (ступени 0,2,4) сортируются по beat: тоны обходятся
        chord0 = sorted((n for n in notes if n.beat < 1.0), key=lambda n: n.beat)
        assert [n.degree for n in chord0] == [0, 2, 4, 0, 2, 4]

    def test_rests_between_hits(self) -> None:
        """Паузы есть: не все 16 шагов играют."""
        ctx = GenerationContext(track=_track("seq"), chord_window=_window())
        notes = generate_notes(ctx)
        chord0 = [n for n in notes if n.beat < 1.0]
        assert len(chord0) == 6  # < 16 шагов


class TestArp:
    """arp: обход ступеней аккорда."""

    def test_up_cycles(self) -> None:
        """16 слотов на аккорд, обход вверх по кругу."""
        ctx = GenerationContext(track=_track("arp"), chord_window=_window())
        notes = generate_notes(ctx)
        assert len(notes) == 32  # 16 × 2 аккорда, пауз нет
        chord0 = sorted((n for n in notes if n.beat < 1.0), key=lambda n: n.beat)
        assert [n.degree for n in chord0[:6]] == [0, 2, 4, 0, 2, 4]

    def test_down_direction(self) -> None:
        """arp_direction="down" — обход в обратном порядке."""
        import dataclasses

        track = _track("arp")
        track.profile = dataclasses.replace(
            track.profile,
            pattern=dataclasses.replace(track.profile.pattern, arp_direction="down"),
        )
        ctx = GenerationContext(track=track, chord_window=_window())
        notes = generate_notes(ctx)
        chord0 = sorted((n for n in notes if n.beat < 1.0), key=lambda n: n.beat)
        assert [n.degree for n in chord0[:3]] == [4, 2, 0]


class TestSlicerSilence:
    """Slicer без окна — тишина (стратегия B)."""

    def test_no_window_silent(self) -> None:
        """Без propagate (пустой outbox) — нет нот, не падение."""
        for profile in ("sub", "stab", "seq", "arp"):
            track = _track(profile)
            assert generate_notes(GenerationContext(track=track)) == []
