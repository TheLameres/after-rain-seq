"""Тесты для PatternSpec — спецификация генерации паттерна как данные."""

from __future__ import annotations

import pytest

from src.session.model.pattern_spec import (
    FAMILY_CC_ONLY,
    FAMILY_CHORD_SLICER,
    FAMILY_CHORD_SOURCE,
    FAMILY_FREE_MONO,
    PatternSpec,
)


class TestPatternSpec:
    """Тесты для PatternSpec."""

    def test_defaults(self) -> None:
        """Дефолты полей."""
        spec = PatternSpec(family=FAMILY_CHORD_SOURCE)
        assert spec.steps == 16
        assert spec.base_pulses == 4
        assert spec.change_every == 1
        assert spec.velocity_base == 100
        assert spec.velocity_accent == 100
        assert spec.sub_shift == 0.25
        assert spec.arp_direction == "up"

    def test_families_accepted(self) -> None:
        """Все четыре семейства принимаются."""
        for family in (
            FAMILY_CHORD_SOURCE,
            FAMILY_CHORD_SLICER,
            FAMILY_FREE_MONO,
            FAMILY_CC_ONLY,
        ):
            spec = PatternSpec(family=family)
            assert spec.family == family

    def test_unknown_family_rejected(self) -> None:
        """Неизвестное семейство — ValueError."""
        with pytest.raises(ValueError, match="семейств"):
            PatternSpec(family="nope")

    def test_invalid_steps(self) -> None:
        """steps < 2 — ValueError."""
        with pytest.raises(ValueError, match="steps"):
            PatternSpec(family=FAMILY_CHORD_SOURCE, steps=1)

    def test_invalid_change_every(self) -> None:
        """change_every < 1 — ValueError."""
        with pytest.raises(ValueError, match="change_every"):
            PatternSpec(family=FAMILY_CHORD_SOURCE, change_every=0)

    def test_invalid_velocity_base(self) -> None:
        """velocity_base вне [0,127] — ValueError."""
        with pytest.raises(ValueError, match="velocity_base"):
            PatternSpec(family=FAMILY_FREE_MONO, velocity_base=200)

    def test_invalid_velocity_accent(self) -> None:
        """velocity_accent вне [0,127] — ValueError."""
        with pytest.raises(ValueError, match="velocity_accent"):
            PatternSpec(family=FAMILY_FREE_MONO, velocity_accent=-1)

    def test_frozen(self) -> None:
        """PatternSpec — frozen dataclass."""
        spec = PatternSpec(family=FAMILY_CHORD_SOURCE)
        with pytest.raises(AttributeError):
            spec.steps = 32  # type: ignore[misc]
