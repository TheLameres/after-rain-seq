"""set_drum_pattern в EngineControl — фасад (design §7), блок 4 tasks.

White-box по образцу test_engine_control_mutation.py: App не запускается,
``_session`` заполняется напрямую, MutationEngine инициализируется
``_init_mutation`` (или не инициализируется — сценарий disabled).
"""

from __future__ import annotations

from src.app.application import App
from src.app.engine_control import AppEngineControl
from src.core.engine_result import EngineResult
from src.repl.engine_control import EngineControl
from src.repl.status import StatusSnapshot, TrackSummary
from src.session.model.drum_track import DrumTrack
from src.session.mutation.mutation_config import MutationConfig
from src.session.session import Session


def make_control(
    init_mutation: bool = True,
) -> tuple[AppEngineControl, App]:
    """App с сессией (drum-дорожка на старте) и, опционально, движком."""
    app = App(config_path="config.yaml", simulate=True)
    app._session = Session()
    app._session.create_drum_track()
    if init_mutation:
        app._init_mutation(MutationConfig())
    return AppEngineControl(app), app


class MinimalControl(EngineControl):
    """Мок без переопределения set_drum_pattern — проверка дефолта."""

    def get_status(self) -> StatusSnapshot:
        return StatusSnapshot(
            running=False,
            bpm=120.0,
            swing=0.0,
            clock_source="internal",
            clock_pending=None,
            clock_error=None,
            link_active=False,
            link_peers=0,
            root="A",
            scale="dorian",
            tracks=(),
            total_mutations=0,
            ports=(),
            log_error=None,
        )

    def get_logs(self, n: int) -> list[str]:
        return []

    def start_transport(self) -> EngineResult:
        return EngineResult.ok("start ok")

    def stop_transport(self) -> EngineResult:
        return EngineResult.ok("stop ok")

    def set_bpm(self, bpm: float) -> EngineResult:
        return EngineResult.ok("bpm ok")

    def set_swing(self, amount: float) -> EngineResult:
        return EngineResult.ok("swing ok")

    def request_clock_source(self, source: str) -> EngineResult:
        return EngineResult.ok("clock ok")

    def rescan_ports(self) -> EngineResult:
        return EngineResult.ok("rescan ok")

    def switch_port(self, label: str, match: str) -> EngineResult:
        return EngineResult.ok("switch ok")

    def set_root(self, root: str) -> EngineResult:
        return EngineResult.ok("root ok")

    def set_scale(self, name: str) -> EngineResult:
        return EngineResult.ok("scale ok")

    def list_tracks(self) -> list[TrackSummary]:
        return []

    def create_track(
        self, profile: str, channel: int | None = None, name: str | None = None
    ) -> EngineResult:
        return EngineResult.ok("create ok")

    def set_track_channel(self, name: str, channel: int) -> EngineResult:
        return EngineResult.ok("channel ok")

    def remove_track(self, name: str) -> EngineResult:
        return EngineResult.ok("remove ok")

    def route_track(self, name: str, label: str) -> EngineResult:
        return EngineResult.ok("route ok")

    def unroute_track(self, name: str) -> EngineResult:
        return EngineResult.ok("unroute ok")

    def create_drum_track(self, name: str | None = None) -> EngineResult:
        return EngineResult.ok("drum ok")

    def set_track_sources(self, name: str, *sources: str) -> EngineResult:
        return EngineResult.ok("sources ok")

    def set_track_gate(self, name: str, gate: float) -> EngineResult:
        return EngineResult.ok("gate ok")

    def set_track_density(self, name: str, density: float) -> EngineResult:
        return EngineResult.ok("density ok")

    def request_mutation(self, name: str | None = None) -> EngineResult:
        return EngineResult.ok("evolve ok")

    def undo_mutation(self, name: str) -> EngineResult:
        return EngineResult.ok("undo ok")

    def recall_version(self, name: str, index: int) -> EngineResult:
        return EngineResult.ok("recall ok")

    def mutation_history(self, name: str) -> EngineResult:
        return EngineResult.ok("history ok")


class TestSetDrumPatternHappyPath:
    def test_by_lane_name(self) -> None:
        ctl, app = make_control()
        result = ctl.set_drum_pattern("Drum 1", "kick", "x..x|x..x|....|....")
        assert not result.error
        drum = app._session.get_track("Drum 1")
        assert drum.lanes[0].pattern == [1, 0, 0, 1, 1, 0, 0, 1] + [0] * 8
        assert "Drum 1" in result.message
        assert "lane 0 (Kick)" in result.message
        assert "4 active step(s)" in result.message

    def test_by_index(self) -> None:
        ctl, app = make_control()
        result = ctl.set_drum_pattern("Drum 1", "2", "X..x")
        assert not result.error
        drum = app._session.get_track("Drum 1")
        assert drum.lanes[2].pattern == [2, 0, 0, 1] + [0] * 12

    def test_by_gm_number(self) -> None:
        ctl, app = make_control()
        result = ctl.set_drum_pattern("Drum 1", "42", "x.x.")
        assert not result.error
        drum = app._session.get_track("Drum 1")
        assert drum.lanes[6].pattern == [1, 0, 1, 0] + [0] * 12

    def test_padding_shorter_than_grid(self) -> None:
        ctl, app = make_control()
        result = ctl.set_drum_pattern("Drum 1", "kick", "x...")
        assert not result.error
        drum = app._session.get_track("Drum 1")
        assert len(drum.lanes[0].pattern) == 16
        assert drum.lanes[0].pattern[4:] == [0] * 12

    def test_empty_pattern_clears_lane(self) -> None:
        ctl, app = make_control()
        drum = app._session.get_track("Drum 1")
        drum.lanes[0].pattern = [1] * 16
        result = ctl.set_drum_pattern("Drum 1", "kick", "")
        assert not result.error
        assert drum.lanes[0].pattern == [0] * 16

    def test_records_version(self) -> None:
        ctl, app = make_control()
        engine = app.mutation_engine
        before = engine.history_len("Drum 1")
        ctl.set_drum_pattern("Drum 1", "kick", "x..x")
        assert engine.history_len("Drum 1") == before + 1


class TestSetDrumPatternErrors:
    def test_no_session_is_error(self) -> None:
        app = App(config_path="config.yaml", simulate=True)
        ctl = AppEngineControl(app)
        result = ctl.set_drum_pattern("Drums", "kick", "x..x")
        assert result.error
        assert "session" in result.message

    def test_unknown_track_is_error(self) -> None:
        ctl, _app = make_control()
        result = ctl.set_drum_pattern("Nope", "kick", "x..x")
        assert result.error
        assert "not found" in result.message

    def test_melodic_track_is_error(self) -> None:
        ctl, app = make_control()
        app._session.create_melodic_track("pad")
        result = ctl.set_drum_pattern("Pad 1", "kick", "x..x")
        assert result.error
        assert "not a drum track" in result.message

    def test_bad_lane_is_error(self) -> None:
        ctl, _app = make_control()
        result = ctl.set_drum_pattern("Drum 1", "cowbellissimo", "x..x")
        assert result.error
        assert "lane" in result.message

    def test_bad_notation_is_error(self) -> None:
        ctl, _app = make_control()
        result = ctl.set_drum_pattern("Drum 1", "kick", "x.kx")
        assert result.error
        assert "неожиданный символ" in result.message

    def test_pattern_too_long_is_error(self) -> None:
        ctl, _app = make_control()
        result = ctl.set_drum_pattern("Drum 1", "kick", "x" * 20)
        assert result.error
        assert "длиннее сетки" in result.message

    def test_pattern_unchanged_on_error(self) -> None:
        ctl, app = make_control()
        drum = app._session.get_track("Drum 1")
        before = list(drum.lanes[0].pattern)
        ctl.set_drum_pattern("Drum 1", "kick", "x.kx")
        ctl.set_drum_pattern("Drum 1", "kick", "x" * 20)
        assert drum.lanes[0].pattern == before


class TestMutationDisabled:
    def test_note_when_engine_missing(self) -> None:
        ctl, app = make_control(init_mutation=False)
        result = ctl.set_drum_pattern("Drum 1", "kick", "x..x")
        assert not result.error
        assert "note:" in result.message
        assert "not recorded" in result.message
        drum = app._session.get_track("Drum 1")
        assert drum.lanes[0].pattern[0] == 1  # паттерн применён

    def test_create_drum_track_disabled_no_registration(self) -> None:
        ctl, app = make_control(init_mutation=False)
        result = ctl.create_drum_track("Extra")
        assert not result.error
        assert "note:" in result.message
        assert app.mutation_engine is None
        assert isinstance(app._session.get_track("Extra"), DrumTrack)


class TestRegistrationOnCreate:
    def test_created_track_is_registered(self) -> None:
        ctl, app = make_control()
        result = ctl.create_drum_track("Drums 2")
        assert not result.error
        engine = app.mutation_engine
        assert "Drums 2" in engine.registered_tracks
        # история отвечает без «not mutable»
        result = ctl.mutation_history("Drums 2")
        assert not result.error
        assert "not mutable" not in result.message

    def test_runtime_track_set_undo_recall(self) -> None:
        """Создал → задал → undo → recall (главный сценарий брифа)."""
        ctl, app = make_control()
        ctl.create_drum_track("Live")
        assert ctl.set_drum_pattern("Live", "kick", "x..x").error is False
        drum = app._session.get_track("Live")
        assert drum.lanes[0].pattern[0] == 1
        assert ctl.undo_mutation("Live").error is False
        assert drum.lanes[0].pattern == [0] * 16
        assert ctl.recall_version("Live", 1).error is False
        assert drum.lanes[0].pattern[0] == 1


class TestDefaultStub:
    def test_minimal_control_returns_default_fail(self) -> None:
        ctl = MinimalControl()
        result = ctl.set_drum_pattern("Drums", "kick", "x..x")
        assert result.error
        assert result.message == "drum pattern is not supported by this control"
