"""Tests for swing — onset delay computed from musical position."""

from __future__ import annotations

import pytest

from src.sync.swing import SwingApplier, SwingConfig, swing_shift


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


class TestSwingShift:
    """Pure function: delay of an onset, in beats."""

    def test_zero_amount_is_zero_delay(self):
        assert swing_shift(beat=0.0, grid=2, amount=0.0) == 0.0
        assert swing_shift(beat=0.5, grid=2, amount=0.0) == 0.0

    def test_even_step_has_no_delay(self):
        assert swing_shift(beat=0.0, grid=2, amount=0.5) == 0.0
        assert swing_shift(beat=1.0, grid=2, amount=0.5) == 0.0
        assert swing_shift(beat=4.0, grid=2, amount=0.5) == 0.0

    def test_odd_step_is_delayed(self):
        # (1/grid) * amount * 0.5 = 0.5 * 0.5 * 0.5
        assert swing_shift(beat=0.5, grid=2, amount=0.5) == pytest.approx(0.125)
        assert swing_shift(beat=1.5, grid=2, amount=0.5) == pytest.approx(0.125)

    def test_pair_sum_preserved(self):
        """Two consecutive intervals still sum to one pair -> no drift."""
        grid, amount = 2, 0.5
        onset_even = 0.0
        onset_odd = 0.5 + swing_shift(0.5, grid, amount)
        next_even = 1.0

        first = onset_odd - onset_even
        second = next_even - onset_odd
        assert first > 0.5 > second  # odd long, next even short
        assert first + second == pytest.approx(1.0)

    def test_finer_grid_scales_delay(self):
        """grid=4 (1/16) yields half the delay of grid=2 for the same amount."""
        fine = swing_shift(beat=0.25, grid=4, amount=0.5)
        coarse = swing_shift(beat=0.5, grid=2, amount=0.5)
        assert fine == pytest.approx(coarse / 2)

    def test_grid_below_two_is_noop(self):
        assert swing_shift(beat=0.5, grid=1, amount=0.5) == 0.0

    def test_beat_just_below_grid_line_still_swings(self):
        """Floating point must not drop a beat that belongs to the odd step."""
        # 0.5 computed just below the grid line — epsilon puts it back on it.
        assert swing_shift(beat=0.5 - 1e-12, grid=2, amount=0.5) > 0.0
        assert swing_shift(beat=0.5, grid=2, amount=0.5) > 0.0


class TestSwingApplier:
    """SwingApplier — onset delay for the Transport."""

    def test_zero_amount_passthrough(self):
        applier = SwingApplier(SwingConfig(amount=0.0))
        assert applier.shift(0.0) == 0.0
        assert applier.shift(0.5) == 0.0

    def test_alternates_by_position(self):
        applier = SwingApplier(SwingConfig(amount=0.5))
        assert applier.shift(0.0) == 0.0  # even, on time
        assert applier.shift(0.5) > 0.0  # odd, delayed
        assert applier.shift(1.0) == 0.0  # even again
        assert applier.shift(1.5) > 0.0  # odd again

    def test_properties(self):
        applier = SwingApplier(SwingConfig(amount=0.3, grid=4))
        assert applier.amount == 0.3
        assert applier.grid == 4

    def test_set_amount_keeps_grid(self):
        applier = SwingApplier(SwingConfig(amount=0.0, grid=4))
        applier.set_amount(0.5)
        assert applier.amount == 0.5
        assert applier.grid == 4

    def test_repr(self):
        applier = SwingApplier(SwingConfig(amount=0.3))
        assert "SwingApplier" in repr(applier)
        assert "0.3" in repr(applier)

    def test_duration_api_is_gone(self):
        """§4.2: swing no longer rewrites durations anywhere."""
        applier = SwingApplier(SwingConfig(amount=0.5))
        assert not hasattr(applier, "apply_duration")
        assert not hasattr(applier, "apply_step")


class TestSwingIsStateless:
    """§4.2 acceptance: same beat → same result, always."""

    def test_identical_inputs_identical_output(self):
        applier = SwingApplier(SwingConfig(amount=0.5))
        first = applier.shift(0.5)
        for _ in range(10):
            applier.shift(0.25)
        assert applier.shift(0.5) == first

    def test_two_tracks_do_not_disturb_each_other(self):
        """Interleaved calls (two tracks) keep per-position parity."""
        applier = SwingApplier(SwingConfig(amount=0.5))
        alone_a = [applier.shift(b) for b in (0.0, 0.5, 1.0, 1.5)]

        applier2 = SwingApplier(SwingConfig(amount=0.5))
        interleaved: list[float] = []
        for b in (0.0, 0.5, 1.0, 1.5):
            # вторая дорожка «шумит» между шагами первой
            applier2.shift(b + 0.25)
            interleaved.append(applier2.shift(b))

        assert interleaved == alone_a
        assert interleaved[1] > 0.0 > -1  # odd step delayed, even not

    def test_beat_position_determines_parity(self):
        applier = SwingApplier(SwingConfig(amount=0.5))
        assert applier.shift(4.0) == 0.0
        assert applier.shift(2.0) == 0.0
        assert applier.shift(1.5) > 0.0
