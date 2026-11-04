"""Tests for App.route_track / unroute_track (REPL track route/unroute).

White-box: App не запускается (run() не вызывается), приватные поля
заполняются напрямую — так же, как они заполняются в run() до старта
main loop.
"""

from __future__ import annotations

import queue

from src.app.application import App
from src.harmony.harmony import Harmony
from src.session.drum.drum_engine import DrumEngine
from src.session.engine.melodic_engine import MelodicEngine
from src.session.session import Session
from src.sync.ports import PortConfig, PortManager, PortsConfig
from src.sync.swing import SwingApplier, SwingConfig
from src.sync.transport_event import EventKind, TransportEvent


class FakeRegistry:
    """In-memory MidiPortRegistry для тестов."""

    def list_input_names(self) -> list[str]:
        return []

    def list_output_names(self) -> list[str]:
        return ["Bus One", "Bus Two"]


def make_app() -> tuple[App, object, object]:
    """App со сессией (melodic + drum), двумя портами и движками."""
    app = App(config_path="config.yaml", simulate=True)
    app._session = Session()
    melodic = app._session.create_melodic_track(profile="pad", channel=0, port="main")
    drum = app._session.create_drum_track(channel=9, port="main")
    pm = PortManager(
        PortsConfig(
            outputs=[
                PortConfig(label="main", match="one"),
                PortConfig(label="aux", match="two"),
            ]
        ),
        FakeRegistry(),
    )
    pm.start()
    app._port_manager = pm
    app._event_queue = queue.Queue(maxsize=256)
    swing = SwingApplier(SwingConfig(amount=0.0))
    app._swing_applier = swing
    app._melodic_engines = [
        MelodicEngine(
            track=melodic,
            harmony=Harmony("A", "dorian"),
            event_queue=app._event_queue,
            port_label="main",
        )
    ]
    app._drum_engines = [
        DrumEngine(
            drum_track=drum,
            event_queue=app._event_queue,
            port_label="main",
        )
    ]
    return app, melodic, drum


def drain(q: queue.Queue[TransportEvent]) -> list[TransportEvent]:
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    return events


class TestRouteTrack:
    """Привязка дорожки к порту."""

    def test_route_changes_engine_and_track(self):
        app, melodic, _ = make_app()
        result = app.route_track("Pad 1", "aux")
        assert result.startswith('track "Pad 1" → port "aux"')
        assert melodic.port == "aux"
        engine = app._melodic_engines[0]
        assert engine.port_label == "aux"
        assert "was" in result  # в фидбеке видно прежний порт

    def test_route_silences_old_port(self):
        app, _, _ = make_app()
        app.route_track("Pad 1", "aux")
        events = drain(app._event_queue)
        assert len(events) == 1
        assert events[0].kind is EventKind.ALL_NOTES_OFF
        assert events[0].port_label == "main"

    def test_route_same_port_no_all_notes_off(self):
        app, _, _ = make_app()
        app.route_track("Pad 1", "main")
        assert app._event_queue.empty()

    def test_route_unknown_port_rejected(self):
        app, melodic, _ = make_app()
        result = app.route_track("Pad 1", "nope")
        assert result.startswith("error:")
        assert "unknown port label" in result
        assert "main, aux" in result
        assert melodic.port == "main"  # состояние не тронуто

    def test_route_unknown_track_rejected(self):
        app, _, _ = make_app()
        result = app.route_track("Ghost", "aux")
        assert result.startswith("error:")
        assert "not found" in result

    def test_route_drum_track(self):
        app, _, drum = make_app()
        result = app.route_track("Drum 1", "aux")
        assert result.startswith('track "Drum 1"')
        assert drum.port == "aux"
        assert app._drum_engines[0].port_label == "aux"


class TestUnrouteTrack:
    """Отключение дорожки от порта."""

    def test_unroute_makes_silent(self):
        app, melodic, _ = make_app()
        result = app.unroute_track("Pad 1")
        assert result.startswith('track "Pad 1" disconnected')
        assert melodic.port is None
        assert app._melodic_engines[0].port_label is None

    def test_unroute_silences_old_port(self):
        app, _, _ = make_app()
        app.unroute_track("Pad 1")
        events = drain(app._event_queue)
        assert len(events) == 1
        assert events[0].kind is EventKind.ALL_NOTES_OFF
        assert events[0].port_label == "main"

    def test_unroute_twice_second_is_quiet(self):
        app, _, _ = make_app()
        app.unroute_track("Pad 1")
        drain(app._event_queue)  # слить all_notes_off первого отключения
        result = app.unroute_track("Pad 1")
        assert result.startswith('track "Pad 1" disconnected')
        assert app._event_queue.empty()  # второй раз глушить нечего

    def test_unroute_unknown_track(self):
        app, _, _ = make_app()
        result = app.unroute_track("Ghost")
        assert result.startswith("error:")


class TestRoutingEdgeCases:
    """Граничные случаи."""

    def test_event_queue_full_no_crash(self):
        app, _, _ = make_app()
        # Забить очередь до предела
        full = TransportEvent.all_notes_off(port_label="x")
        while True:
            try:
                app._event_queue.put_nowait(full)
            except queue.Full:
                break
        result = app.route_track("Pad 1", "aux")
        # Команда отработала, all_notes_off потерян с предупреждением
        assert result.startswith('track "Pad 1"')

    def test_track_without_engine_creates_one_on_demand(self):
        """Дорожка, созданная после старта: route создаёт движок on demand."""
        app, _, _ = make_app()
        bass = app._session.create_melodic_track(profile="bass", channel=1, port=None)
        assert len(app._melodic_engines) == 1  # только Pad 1
        result = app.route_track("Bass 1", "aux")
        assert result.startswith('track "Bass 1" → port "aux"')
        assert bass.port == "aux"
        assert len(app._melodic_engines) == 2
        new_engine = app._melodic_engines[-1]
        assert new_engine.port_label == "aux"
        # Старого порта не было — глушить нечего
        assert app._event_queue.empty()

    def test_route_drum_without_engine_on_demand(self):
        """Drum-дорожка без движка тоже получает его по route."""
        app, _, _ = make_app()
        drum2 = app._session.create_drum_track(channel=9, port=None)
        result = app.route_track("Drum 2", "aux")
        assert result.startswith('track "Drum 2"')
        assert drum2.port == "aux"
        assert app._drum_engines[-1].port_label == "aux"

    def test_unroute_without_engine_still_works(self):
        """Дорожка без движка: unroute просто снимает привязку."""
        app, _, _ = make_app()
        bass = app._session.create_melodic_track(profile="bass", channel=1, port="main")
        result = app.unroute_track("Bass 1")
        assert result.startswith('track "Bass 1" disconnected')
        assert bass.port is None


class TestDropTrack:
    """Удаление дорожки вместе с движком (REPL track delete)."""

    def test_drop_removes_engine_and_silences_port(self):
        app, _, _ = make_app()
        result = app.drop_track("Pad 1")
        assert result.startswith('deleted track "Pad 1"')
        assert len(app._melodic_engines) == 0
        events = drain(app._event_queue)
        assert len(events) == 1
        assert events[0].kind is EventKind.ALL_NOTES_OFF
        assert events[0].port_label == "main"

    def test_drop_silent_track_no_event(self):
        app, _, _ = make_app()
        app.unroute_track("Pad 1")
        drain(app._event_queue)
        app.drop_track("Pad 1")
        assert app._event_queue.empty()

    def test_drop_unknown_track_errors(self):
        app, _, _ = make_app()
        result = app.drop_track("Ghost")
        assert result.startswith("error:")
        assert len(app._melodic_engines) == 1  # ничего не удалено
