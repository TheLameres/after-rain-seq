"""Tests for swing — groove through duration modification."""

from __future__ import annotations

import pytest

from src.sync.swing import SwingApplier, SwingConfig, swing_duration


class TestSwingConfig:
    """Tests for SwingConfig dataclass."""

    def test_frozen(self):
        """SwingConfig is immutable."""
        cfg = SwingConfig(amount=0.3)
        with pytest.raises(AttributeError):
            cfg.amount = 0.5  # type: ignore[misc]

    def test_default_amount_is_zero(self):
        """Default amount is 0.0 (no swing)."""
        cfg = SwingConfig()
        assert cfg.amount == 0.0

    def test_default_grid_is_eighth(self):
        """Default grid is 2 (1/8 notes)."""
        cfg = SwingConfig()
        assert cfg.grid == 2

    def test_amount_zero_valid(self):
        """Amount 0.0 is valid (passthrough)."""
        cfg = SwingConfig(amount=0.0)
        assert cfg.amount == 0.0

    def test_amount_one_valid(self):
        """Amount 1.0 is valid (maximum swing)."""
        cfg = SwingConfig(amount=1.0)
        assert cfg.amount == 1.0

    def test_amount_negative_raises(self):
        """Negative amount raises ValueError."""
        with pytest.raises(ValueError, match="0.0.*1.0"):
            SwingConfig(amount=-0.1)

    def test_amount_above_one_raises(self):
        """Amount > 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="0.0.*1.0"):
            SwingConfig(amount=1.5)

    def test_grid_below_two_raises(self):
        """Grid < 2 raises ValueError."""
        with pytest.raises(ValueError, match="grid"):
            SwingConfig(grid=1)


class TestSwingDuration:
    """Tests for the pure swing_duration function."""

    def test_zero_amount_passthrough(self):
        """Amount 0 returns base unchanged."""
        assert swing_duration(base=0.5, step_index=0, amount=0.0) == 0.5
        assert swing_duration(base=0.5, step_index=1, amount=0.0) == 0.5

    def test_even_step_shortened(self):
        """Even step is shortened."""
        result = swing_duration(base=0.5, step_index=0, amount=0.5)
        assert result < 0.5

    def test_odd_step_lengthened(self):
        """Odd step is lengthened."""
        result = swing_duration(base=0.5, step_index=1, amount=0.5)
        assert result > 0.5

    def test_pair_sum_preserved(self):
        """Sum of even + odd = 2 * base (tempo does not drift)."""
        base = 0.5
        amount = 0.5
        even = swing_duration(base, 0, amount)
        odd = swing_duration(base, 1, amount)
        assert even + odd == pytest.approx(2 * base)

    def test_full_amount_halves_and_doubles(self):
        """Amount=1.0: even = base*0.5, odd = base*1.5."""
        base = 0.5
        assert swing_duration(base, 0, 1.0) == pytest.approx(0.25)
        assert swing_duration(base, 1, 1.0) == pytest.approx(0.75)

    def test_half_amount_quarter_shift(self):
        """Amount=0.5: shift = base * 0.25."""
        base = 0.5
        assert swing_duration(base, 0, 0.5) == pytest.approx(0.375)
        assert swing_duration(base, 1, 0.5) == pytest.approx(0.625)

    def test_step_index_modulo(self):
        """Step index wraps: step 2 behaves like step 0."""
        base = 0.5
        amount = 0.5
        assert swing_duration(base, 0, amount) == pytest.approx(
            swing_duration(base, 2, amount)
        )
        assert swing_duration(base, 1, amount) == pytest.approx(
            swing_duration(base, 3, amount)
        )


class TestSwingApplier:
    """Tests for the SwingApplier class."""

    def test_zero_amount_passthrough(self):
        """Amount 0 returns base unchanged and does not track state."""
        applier = SwingApplier(SwingConfig(amount=0.0))
        assert applier.apply_duration(base=0.5, beat=0.0) == 0.5
        assert applier.apply_duration(base=0.5, beat=0.5) == 0.5

    def test_alternating_short_long(self):
        """Consecutive calls alternate short/long."""
        applier = SwingApplier(SwingConfig(amount=0.5))
        d0 = applier.apply_duration(base=0.5, beat=0.0)
        d1 = applier.apply_duration(base=0.5, beat=0.5)
        d2 = applier.apply_duration(base=0.5, beat=1.0)
        d3 = applier.apply_duration(base=0.5, beat=1.5)
        assert d0 < 0.5  # even, short
        assert d1 > 0.5  # odd, long
        assert d2 < 0.5  # even, short
        assert d3 > 0.5  # odd, long

    def test_reset_clears_state(self):
        """Reset starts swing from step 0."""
        applier = SwingApplier(SwingConfig(amount=0.5))
        applier.apply_duration(base=0.5, beat=0.0)  # step 0
        applier.apply_duration(base=0.5, beat=0.5)  # step 1
        applier.reset()
        d = applier.apply_duration(base=0.5, beat=0.0)
        assert d < 0.5  # back to even (short)

    def test_backward_beat_resets(self):
        """Beat jumping backwards resets step counter."""
        applier = SwingApplier(SwingConfig(amount=0.5))
        applier.apply_duration(base=0.5, beat=4.0)  # some step
        applier.apply_duration(base=0.5, beat=0.0)  # jumped back
        # After backward jump, step resets → even (short)
        d = applier.apply_duration(base=0.5, beat=0.5)
        assert d > 0.5  # odd (long) — confirms reset happened

    def test_large_forward_jump_resets(self):
        """Beat jumping forward > 8 beats resets step counter."""
        applier = SwingApplier(SwingConfig(amount=0.5))
        applier.apply_duration(base=0.5, beat=0.0)  # step 0
        # Jump forward by more than 2 bars
        d = applier.apply_duration(base=0.5, beat=16.0)
        # After jump, step resets → even (short)
        assert d < 0.5

    def test_properties(self):
        """amount and grid properties return config values."""
        applier = SwingApplier(SwingConfig(amount=0.3, grid=4))
        assert applier.amount == 0.3
        assert applier.grid == 4

    def test_repr(self):
        """repr includes amount, grid, and step."""
        applier = SwingApplier(SwingConfig(amount=0.3))
        r = repr(applier)
        assert "0.3" in r
        assert "2" in r  # grid

    def test_grid_four_sixteenth_notes(self):
        """Grid=4 applies swing to 1/16 steps."""
        applier = SwingApplier(SwingConfig(amount=0.5, grid=4))
        d0 = applier.apply_duration(base=0.25, beat=0.0)
        d1 = applier.apply_duration(base=0.25, beat=0.25)
        d2 = applier.apply_duration(base=0.25, beat=0.5)
        d3 = applier.apply_duration(base=0.25, beat=0.75)
        assert d0 < 0.25  # step 0, even
        assert d1 > 0.25  # step 1, odd
        assert d2 < 0.25  # step 2, even
        assert d3 > 0.25  # step 3, odd
