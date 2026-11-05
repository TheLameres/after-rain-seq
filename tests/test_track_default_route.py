"""Новые дорожки получают выход по умолчанию (первый настроенный порт).

Раньше дорожка создавалась с port=None, движок писал в несуществующий порт
"default", и транспорт молча отбрасывал все ноты.
"""

from __future__ import annotations

import queue

from src.app.application import App
from src.app.engine_control import AppEngineControl
from src.core.engine_result import EngineResult
from src.harmony.harmony import Harmony
from src.session.session import Session
from src.sync.ports import PortConfig, PortManager, PortsConfig
from src.sync.swing import SwingApplier, SwingConfig
from src.sync.transport import Transport


class _Out:
    def __init__(self) -> None:
        self.on: list[int] = []

    def note_on(self, channel: int, note: int, velocity: int) -> None:
        self.on.append(note)

    def note_off(self, channel: int, note: int) -> None:
        pass

    def all_notes_off(self) -> None:
        pass

    def control_change(self, **kwargs: int) -> None:
        pass

    def flush(self) -> None:
        pass


class _Registry:
    def __init__(self, label: str) -> None:
        self.out = _Out()
        self._label = label

    def get_output(self, label: str) -> _Out | None:
        return self.out if label == self._label else None

    def flush_all(self) -> None:
        pass


class _Fake:
    list_input_names: tuple[str, ...] = ()

    def list_output_names(self) -> list[str]:
        return ["Bus One", "Bus Two"]


def _app(outputs: tuple[str, ...] = ("main", "aux")) -> App:
    app = App(config_path="config.yaml", simulate=True)
    app._session = Session()
    app._port_manager = PortManager(
        PortsConfig(
            outputs=[
                PortConfig(label=label, match=f"x{i}")
                for i, label in enumerate(outputs)
            ]
        ),
        _Fake(),  # type: ignore[arg-type]
    )
    app._event_queue = queue.Queue(maxsize=4096)
    app._swing_applier = SwingApplier(SwingConfig(amount=0.0))
    app._harmony = Harmony("A", "dorian")
    return app


def _play_melodic(app: App, track_name: str, label: str) -> list[int]:
    """Прогнать движок дорожки через транспорт и вернуть доставленные ноты."""
    track = app._session.get_track(track_name)
    engine = next(e for e in app._melodic_engines if e.track is track)
    registry = _Registry(label)
    transport = Transport(app._event_queue, registry, app._swing_applier)  # type: ignore[arg-type]
    beat = 0.0
    while beat <= 4.0:
        engine.tick(beat)
        transport.process_events(current_beat=beat)
        beat += 1 / 24
    return registry.out.on


class TestCreateTrackRoutesToDefaultOutput:
    def test_new_melodic_track_is_routed_to_first_output(self) -> None:
        app = _app()
        result = AppEngineControl(app).create_track("lead")
        assert not result.error
        track = app._session.ordered_tracks()[-1]
        assert track.port == "main"

    def test_melodic_track_actually_sends_notes(self) -> None:
        app = _app()
        AppEngineControl(app).create_track("lead")
        track = app._session.ordered_tracks()[-1]
        notes = _play_melodic(app, track.name, "main")
        assert notes, "новая дорожка не отправила ни одной ноты на выход"

    def test_new_drum_track_is_routed_to_first_output(self) -> None:
        app = _app()
        AppEngineControl(app).create_drum_track()
        drum = app._session.ordered_tracks()[-1]
        assert drum.port == "main"

    def test_no_configured_output_leaves_track_unrouted(self) -> None:
        app = _app(outputs=())
        result = AppEngineControl(app).create_track("pad")
        assert not result.error
        assert app._session.ordered_tracks()[-1].port is None

    def test_route_failure_does_not_fail_creation(self) -> None:
        app = _app()
        app.route_track = lambda name, label: EngineResult.fail(  # type: ignore[method-assign]
            "port not available"
        )
        result = AppEngineControl(app).create_track("pad")
        assert not result.error
        assert app._session.ordered_tracks()[-1].port is None


class TestWizardNoneIsExplicitUnroute:
    """Мастер «—» означает «без порта»: созданную дорожку отвязываем явно."""

    def test_none_choice_unroutes_created_track(self) -> None:
        from src.core.engine_result import EngineResult
        from tests.test_screen_controller import MELODIC_PROFILES, btn, make_controller

        ctl, engine, _ = make_controller()
        engine.create_track = lambda profile, channel=None: EngineResult.ok(  # type: ignore[method-assign]
            "created", track="Stab 1"
        )
        btn(ctl, "Add Track")
        btn(ctl, "Right")  # kind: melodic
        for _ in range(MELODIC_PROFILES.index("stab")):
            btn(ctl, "Down")
        btn(ctl, "Right")  # profile: stab
        btn(ctl, "Right")  # route: «—» по умолчанию
        assert engine.called("unroute_track") == [("Stab 1",)]
        assert engine.called("route_track") == []
