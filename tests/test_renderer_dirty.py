"""Tests for DirtyTracker — region invalidation in src/devices/push2/renderer.py."""

from src.devices.push2.renderer import DirtyTracker


def test_single_rect() -> None:
    t = DirtyTracker(960, 160)
    t.invalidate(10, 20, 30, 40)
    assert t.rects() == ((10, 20, 40, 60),)
    assert not t.is_full


def test_merge_overlap() -> None:
    """Two overlapping rects merge into one."""
    t = DirtyTracker(960, 160)
    t.invalidate(0, 0, 10, 10)
    t.invalidate(5, 5, 10, 10)
    assert t.rects() == ((0, 0, 15, 15),)


def test_merge_adjacent() -> None:
    """Directly touching rects merge (gap <= 1 px)."""
    t = DirtyTracker(960, 160)
    t.invalidate(0, 0, 10, 10)
    t.invalidate(10, 0, 10, 10)
    assert len(t.rects()) == 1
    assert t.rects() == ((0, 0, 20, 10),)


def test_disjoint_stay_separate() -> None:
    t = DirtyTracker(960, 160)
    t.invalidate(0, 0, 10, 10)
    t.invalidate(100, 100, 10, 10)
    assert len(t.rects()) == 2


def test_clamp_to_frame() -> None:
    """Rects outside the frame are clipped; fully outside are ignored."""
    t = DirtyTracker(960, 160)
    t.invalidate(-10, -10, 20, 20)
    t.invalidate(950, 150, 100, 100)
    t.invalidate(-100, 0, 50, 50)  # fully outside after clamp
    assert t.rects() == ((0, 0, 10, 10), (950, 150, 960, 160))


def test_zero_and_negative_size_ignored() -> None:
    t = DirtyTracker(960, 160)
    t.invalidate(10, 10, 0, 10)
    t.invalidate(10, 10, 10, -5)
    assert t.rects() == ()


def test_overflow_degrades_to_full() -> None:
    """More than max_rects disjoint invalidations → full frame."""
    t = DirtyTracker(960, 160, max_rects=4)
    for i in range(5):
        t.invalidate(i * 100, 0, 10, 10)
    assert t.is_full
    assert t.rects() == ((0, 0, 960, 160),)


def test_full_short_circuits_new_invalidations() -> None:
    t = DirtyTracker(960, 160, max_rects=1)
    t.invalidate(0, 0, 10, 10)
    t.invalidate(500, 0, 10, 10)  # second disjoint rect → full
    assert t.is_full
    t.invalidate(100, 100, 10, 10)  # must not raise, stays full
    assert t.rects() == ((0, 0, 960, 160),)


def test_take_clears() -> None:
    t = DirtyTracker(960, 160)
    t.invalidate(0, 0, 10, 10)
    rects = t.take()
    assert rects == ((0, 0, 10, 10),)
    assert t.rects() == ()
    assert not t.is_full


def test_clear() -> None:
    t = DirtyTracker(960, 160)
    t.invalidate(0, 0, 10, 10)
    t.clear()
    assert t.rects() == ()


def test_chained_merge() -> None:
    """Merging can cascade: new rect bridges two existing ones."""
    t = DirtyTracker(960, 160)
    t.invalidate(0, 0, 10, 10)
    t.invalidate(30, 0, 10, 10)
    t.invalidate(10, 0, 20, 10)  # touches both
    assert t.rects() == ((0, 0, 40, 10),)
