"""Tests for render_toolbar — сегменты, цвета, pending/error, обрезание."""

from __future__ import annotations

from src.repl.status import PortSummary, StatusSnapshot, TrackSummary
from src.repl.status_bar import render_toolbar


def make_snapshot(**overrides) -> StatusSnapshot:
    """Снапшот с дефолтами + overrides."""
    base: dict[str, object] = {
        "running": True,
        "bpm": 120.0,
        "swing": 0.0,
        "clock_source": "internal",
        "clock_pending": None,
        "clock_error": None,
        "link_active": False,
        "link_peers": 0,
        "root": "A",
        "scale": "dorian",
        "tracks": (
            TrackSummary("Pad 1", "melodic", "pad", (), 0, False),
            TrackSummary("Drum 1", "drum", "drum", (), 0, False),
        ),
        "total_mutations": 12,
        "ports": (PortSummary("Synth A", "connected", "IAC Bus 1"),),
        "log_error": None,
    }
    base.update(overrides)
    return StatusSnapshot(**base)  # type: ignore[arg-type]


class TestSegments:
    """Состав и порядок сегментов."""

    def test_running_bar(self):
        bar = render_toolbar(make_snapshot(), 200, color=False)
        assert bar.startswith("> 120.0 bpm")
        assert "clock: internal" in bar
        assert "A dorian" in bar
        assert "tracks 2" in bar
        assert "mut 12" in bar
        assert "ports 1/1 ok" in bar

    def test_paused_bar(self):
        bar = render_toolbar(make_snapshot(running=False), 200, color=False)
        assert bar.startswith("|| 120.0 bpm")

    def test_pending_clock(self):
        bar = render_toolbar(
            make_snapshot(clock_source="internal", clock_pending="midi"),
            200,
            color=False,
        )
        assert "clock: midi (pending)" in bar

    def test_clock_error_segment(self):
        bar = render_toolbar(
            make_snapshot(clock_error="no midi device"),
            200,
            color=False,
        )
        assert "clock err: no midi device" in bar

    def test_bad_port_segment(self):
        bar = render_toolbar(
            make_snapshot(
                ports=(PortSummary("Synth A", "ambiguous", "multiple matches"),)
            ),
            200,
            color=False,
        )
        assert "port Synth A: ambiguous" in bar

    def test_link_peers(self):
        bar = render_toolbar(
            make_snapshot(link_active=True, link_peers=2),
            200,
            color=False,
        )
        assert "link: 2 peers" in bar

    def test_no_ports(self):
        bar = render_toolbar(make_snapshot(ports=()), 200, color=False)
        assert "ports —" in bar


class TestColors:
    """ANSI-цвета при color=True и чистый ASCII при color=False."""

    def test_color_wraps_segments(self):
        bar = render_toolbar(make_snapshot(), 200, color=True)
        assert "\x1b[32m" in bar  # green
        assert "\x1b[0m" in bar  # reset

    def test_no_color_is_ascii_only(self):
        bar = render_toolbar(make_snapshot(), 200, color=False)
        assert "\x1b" not in bar

    def test_pending_is_yellow(self):
        snap = make_snapshot(clock_pending="midi")
        bar = render_toolbar(snap, 200, color=True)
        assert "\x1b[33m" in bar  # yellow

    def test_error_is_red(self):
        snap = make_snapshot(clock_error="boom")
        bar = render_toolbar(snap, 200, color=True)
        assert "\x1b[31m" in bar  # red

    def test_paused_is_gray(self):
        bar = render_toolbar(make_snapshot(running=False), 200, color=True)
        assert "\x1b[90m" in bar  # gray


class TestTruncation:
    """Обрезание по ширине: приоритет слева направо."""

    def test_fits_exactly(self):
        bar = render_toolbar(make_snapshot(), 200, color=False)
        assert len(bar) <= 200

    def test_truncates_from_right(self):
        full = render_toolbar(make_snapshot(), 500, color=False)
        narrow = render_toolbar(make_snapshot(), 40, color=False)
        assert len(narrow) <= 40
        assert narrow.startswith("> 120.0 bpm")
        # Хвост отрезан: последний сегмент полной версии отсутствует
        last_segment = full.split(" | ")[-1]
        if len(last_segment) + len(full) - len(last_segment) > 40:
            assert last_segment not in narrow

    def test_tiny_width_still_renders(self):
        bar = render_toolbar(make_snapshot(), 10, color=False)
        assert bar
        assert len(bar) <= 12  # обрезка + многоточие
        assert bar.startswith(">")

    def test_narrow_width_ascii_only(self):
        bar = render_toolbar(make_snapshot(), 25, color=False)
        assert "\x1b" not in bar
        assert len(bar) <= 27
