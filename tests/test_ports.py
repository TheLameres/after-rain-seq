"""Tests for PortManager — discovery, identification, hot-plug."""

from __future__ import annotations

from src.sync.port_state import PortStatus
from src.sync.ports import PortConfig, PortEvent, PortManager, PortsConfig

# ---------------------------------------------------------------------------
# Fake registry
# ---------------------------------------------------------------------------


class FakeRegistry:
    """In-memory MidiPortRegistry for testing."""

    def __init__(
        self,
        input_names: list[str] | None = None,
        output_names: list[str] | None = None,
    ) -> None:
        self._input_names = input_names or []
        self._output_names = output_names or []

    def set_inputs(self, names: list[str]) -> None:
        self._input_names = names

    def set_outputs(self, names: list[str]) -> None:
        self._output_names = names

    def list_input_names(self) -> list[str]:
        return list(self._input_names)

    def list_output_names(self) -> list[str]:
        return list(self._output_names)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_manager(
    outputs: list[PortConfig] | None = None,
    inputs: list[PortConfig] | None = None,
    registry: FakeRegistry | None = None,
) -> PortManager:
    cfg = PortsConfig(outputs=outputs or [], inputs=inputs or [])
    reg = registry or FakeRegistry()
    return PortManager(cfg, reg)


# ---------------------------------------------------------------------------
# Identification tests
# ---------------------------------------------------------------------------


class TestPortIdentification:
    """Tests for the _identify static method."""

    def test_single_match_connected(self):
        """One matching port → CONNECTED."""
        pm = make_manager(
            outputs=[PortConfig(label="A", match="Synth")],
            registry=FakeRegistry(output_names=["My Synth Out"]),
        )
        pm.start()
        state = pm.get_state("A")
        assert state is not None
        assert state.status is PortStatus.CONNECTED
        assert state.resolved_name == "My Synth Out"

    def test_start_returns_initial_events(self):
        """start() возвращает события начального скана (connected порты).

        Регрессия: события, отброшенные при старте, не доходили до
        PortRegistry — порт, подключённый до старта App, молчал.
        """
        pm = make_manager(
            outputs=[PortConfig(label="A", match="Synth")],
            registry=FakeRegistry(output_names=["My Synth Out"]),
        )
        events = pm.start()
        assert len(events) == 1
        assert events[0].new_status is PortStatus.CONNECTED
        assert events[0].resolved_name == "My Synth Out"
        # Повторный start без изменений — без событий.
        assert pm.start() == []

    def test_no_match_disconnected(self):
        """Zero matches → DISCONNECTED, not an error."""
        pm = make_manager(
            outputs=[PortConfig(label="A", match="Nonexistent")],
            registry=FakeRegistry(output_names=["Some Port"]),
        )
        pm.start()
        state = pm.get_state("A")
        assert state is not None
        assert state.status is PortStatus.DISCONNECTED
        assert state.resolved_name is None
        assert state.error is None

    def test_multiple_matches_ambiguous(self):
        """Multiple matches without serial → AMBIGUOUS with error."""
        pm = make_manager(
            outputs=[PortConfig(label="A", match="LCXL3")],
            registry=FakeRegistry(output_names=["LCXL3 1 DAW In", "LCXL3 2 DAW In"]),
        )
        pm.start()
        state = pm.get_state("A")
        assert state is not None
        assert state.status is PortStatus.AMBIGUOUS
        assert state.resolved_name is None
        assert state.error is not None
        assert "serial" in state.error.lower()

    def test_multiple_matches_with_serial(self):
        """Multiple matches + serial → CONNECTED to the right one."""
        pm = make_manager(
            outputs=[PortConfig(label="A", match="LCXL3", serial="8021")],
            registry=FakeRegistry(
                output_names=["LCXL3 1 DAW In 8021A3B4", "LCXL3 2 DAW In 9999C9D9"]
            ),
        )
        pm.start()
        state = pm.get_state("A")
        assert state is not None
        assert state.status is PortStatus.CONNECTED
        assert state.resolved_name == "LCXL3 1 DAW In 8021A3B4"

    def test_multiple_matches_serial_not_found(self):
        """Serial specified but not found → DISCONNECTED."""
        pm = make_manager(
            outputs=[PortConfig(label="A", match="LCXL3", serial="XXXX")],
            registry=FakeRegistry(output_names=["LCXL3 1 DAW In", "LCXL3 2 DAW In"]),
        )
        pm.start()
        state = pm.get_state("A")
        assert state is not None
        assert state.status is PortStatus.DISCONNECTED

    def test_case_insensitive_match(self):
        """Match is case-insensitive."""
        pm = make_manager(
            outputs=[PortConfig(label="A", match="synth")],
            registry=FakeRegistry(output_names=["My SYNTH Out"]),
        )
        pm.start()
        state = pm.get_state("A")
        assert state is not None
        assert state.status is PortStatus.CONNECTED

    def test_name_changes_on_reconnect(self):
        """Port name gets suffix on reconnect — still found by match."""
        registry = FakeRegistry(output_names=["Synth Out"])
        pm = make_manager(
            outputs=[PortConfig(label="A", match="Synth")],
            registry=registry,
        )
        pm.start()
        assert pm.get_state("A").status is PortStatus.CONNECTED  # type: ignore[union-attr]

        # Simulate reconnect with suffix
        registry.set_outputs(["Synth Out 2"])
        events = pm.poll()
        assert len(events) == 1
        assert events[0].new_status is PortStatus.CONNECTED
        assert events[0].resolved_name == "Synth Out 2"


# ---------------------------------------------------------------------------
# PortManager lifecycle tests
# ---------------------------------------------------------------------------


class TestPortManagerLifecycle:
    """Tests for start/poll/stop behaviour."""

    def test_start_no_ports_configured(self):
        """Start with empty config — no errors."""
        pm = make_manager()
        pm.start()  # should not raise
        assert pm.all_states() == []

    def test_start_no_physical_ports(self):
        """Start when no MIDI ports exist — all DISCONNECTED, no exception."""
        pm = make_manager(
            outputs=[PortConfig(label="A", match="Synth")],
            registry=FakeRegistry(output_names=[]),
        )
        pm.start()
        state = pm.get_state("A")
        assert state is not None
        assert state.status is PortStatus.DISCONNECTED

    def test_poll_detects_connect(self):
        """Port appears between polls → CONNECTED event."""
        registry = FakeRegistry(output_names=[])
        pm = make_manager(
            outputs=[PortConfig(label="A", match="Synth")],
            registry=registry,
        )
        pm.start()
        assert pm.poll() == []

        registry.set_outputs(["Synth Out"])
        events = pm.poll()
        assert len(events) == 1
        assert events[0].label == "A"
        assert events[0].direction == "output"
        assert events[0].old_status is PortStatus.DISCONNECTED
        assert events[0].new_status is PortStatus.CONNECTED
        assert events[0].resolved_name == "Synth Out"

    def test_poll_detects_disconnect(self):
        """Port disappears between polls → DISCONNECTED event."""
        registry = FakeRegistry(output_names=["Synth Out"])
        pm = make_manager(
            outputs=[PortConfig(label="A", match="Synth")],
            registry=registry,
        )
        pm.start()
        assert pm.get_state("A").status is PortStatus.CONNECTED  # type: ignore[union-attr]

        registry.set_outputs([])
        events = pm.poll()
        assert len(events) == 1
        assert events[0].old_status is PortStatus.CONNECTED
        assert events[0].new_status is PortStatus.DISCONNECTED
        assert events[0].resolved_name is None

    def test_poll_detects_ambiguous_transition(self):
        """Second matching port appears → AMBIGUOUS event."""
        registry = FakeRegistry(output_names=["LCXL3 1 DAW In"])
        pm = make_manager(
            outputs=[PortConfig(label="A", match="LCXL3")],
            registry=registry,
        )
        pm.start()
        assert pm.get_state("A").status is PortStatus.CONNECTED  # type: ignore[union-attr]

        registry.set_outputs(["LCXL3 1 DAW In", "LCXL3 2 DAW In"])
        events = pm.poll()
        assert len(events) == 1
        assert events[0].new_status is PortStatus.AMBIGUOUS

    def test_poll_no_change_no_event(self):
        """Nothing changed → empty event list."""
        registry = FakeRegistry(output_names=["Synth Out"])
        pm = make_manager(
            outputs=[PortConfig(label="A", match="Synth")],
            registry=registry,
        )
        pm.start()
        assert pm.poll() == []
        assert pm.poll() == []

    def test_poll_multiple_ports(self):
        """Multiple configured ports produce independent events."""
        registry = FakeRegistry(output_names=["Synth A Out"])
        pm = make_manager(
            outputs=[
                PortConfig(label="A", match="Synth A"),
                PortConfig(label="B", match="Synth B"),
            ],
            registry=registry,
        )
        pm.start()
        assert pm.get_state("A").status is PortStatus.CONNECTED  # type: ignore[union-attr]
        assert pm.get_state("B").status is PortStatus.DISCONNECTED  # type: ignore[union-attr]

        registry.set_outputs(["Synth A Out", "Synth B Out"])
        events = pm.poll()
        assert len(events) == 1
        assert events[0].label == "B"

    def test_poll_registry_error_returns_empty(self):
        """Registry raises → poll returns empty list, no crash."""
        registry = FakeRegistry(output_names=["Synth Out"])

        def _boom() -> list[str]:
            raise RuntimeError("MIDI subsystem error")

        registry.list_output_names = _boom  # type: ignore[method-assign]
        pm = make_manager(
            outputs=[PortConfig(label="A", match="Synth")],
            registry=registry,
        )
        pm.start()  # should not raise
        events = pm.poll()
        assert events == []


# ---------------------------------------------------------------------------
# Query API tests
# ---------------------------------------------------------------------------


class TestQueryAPI:
    """Tests for resolve_output, resolve_input, get_state, all_states."""

    def test_resolve_output_connected(self):
        """resolve_output returns the system name when connected."""
        pm = make_manager(
            outputs=[PortConfig(label="A", match="Synth")],
            registry=FakeRegistry(output_names=["My Synth Out"]),
        )
        pm.start()
        assert pm.resolve_output("A") == "My Synth Out"

    def test_resolve_output_disconnected(self):
        """resolve_output returns None when disconnected."""
        pm = make_manager(
            outputs=[PortConfig(label="A", match="Synth")],
            registry=FakeRegistry(output_names=[]),
        )
        pm.start()
        assert pm.resolve_output("A") is None

    def test_resolve_output_ambiguous(self):
        """resolve_output returns None when ambiguous."""
        pm = make_manager(
            outputs=[PortConfig(label="A", match="LCXL3")],
            registry=FakeRegistry(output_names=["LCXL3 1 DAW In", "LCXL3 2 DAW In"]),
        )
        pm.start()
        assert pm.resolve_output("A") is None

    def test_resolve_output_unknown_label(self):
        """resolve_output returns None for unconfigured label."""
        pm = make_manager()
        pm.start()
        assert pm.resolve_output("Nonexistent") is None

    def test_resolve_input_connected(self):
        """resolve_input works for input ports."""
        pm = make_manager(
            inputs=[PortConfig(label="Clock", match="LCXL3", role="clock")],
            registry=FakeRegistry(input_names=["LCXL3 1 DAW Out"]),
        )
        pm.start()
        assert pm.resolve_input("Clock") == "LCXL3 1 DAW Out"

    def test_resolve_input_wrong_direction(self):
        """resolve_input returns None for output-only labels."""
        pm = make_manager(
            outputs=[PortConfig(label="A", match="Synth")],
            registry=FakeRegistry(output_names=["Synth Out"]),
        )
        pm.start()
        assert pm.resolve_input("A") is None

    def test_get_state_unknown_label(self):
        """get_state returns None for unconfigured label."""
        pm = make_manager()
        pm.start()
        assert pm.get_state("Nonexistent") is None

    def test_all_states_includes_direction(self):
        """all_states returns both outputs and inputs."""
        pm = make_manager(
            outputs=[PortConfig(label="Out1", match="A")],
            inputs=[PortConfig(label="In1", match="B", role="clock")],
            registry=FakeRegistry(
                output_names=["A Port"],
                input_names=["B Port"],
            ),
        )
        pm.start()
        states = pm.all_states()
        assert len(states) == 2
        by_label = {s.label: s for s in states}
        assert by_label["Out1"].direction == "output"
        assert by_label["In1"].direction == "input"
        assert by_label["In1"].role == "clock"


# ---------------------------------------------------------------------------
# PortEvent tests
# ---------------------------------------------------------------------------


class TestPortConfigNoAutomation:
    """Tests for the no_automation flag on PortConfig."""

    def test_no_automation_default_false(self):
        """no_automation defaults to False."""
        pc = PortConfig(label="A", match="Synth")
        assert pc.no_automation is False

    def test_no_automation_true(self):
        """no_automation can be set to True."""
        pc = PortConfig(label="LCXL3", match="LCXL3", no_automation=True)
        assert pc.no_automation is True

    def test_no_automation_from_dict(self):
        """no_automation deserialises from YAML dict."""
        pc = PortConfig.model_validate(
            {"label": "LCXL3", "match": "LCXL3", "no_automation": True}
        )
        assert pc.no_automation is True


class TestPortEvent:
    """Tests for the PortEvent dataclass."""

    def test_frozen(self):
        """PortEvent is immutable."""
        ev = PortEvent(
            label="A",
            direction="output",
            role="melodic",
            old_status=PortStatus.DISCONNECTED,
            new_status=PortStatus.CONNECTED,
            resolved_name="Synth Out",
        )
        try:
            ev.label = "B"  # type: ignore[misc]
            raised = False
        except AttributeError:
            raised = True
        assert raised


class TestPortSwitch:
    """Tests for the runtime switch (REPL `ports switch` machinery)."""

    def _started_manager(self):
        """Manager with one connected output on 'Bus One'."""
        reg = FakeRegistry(output_names=["Bus One", "Bus Two"])
        pm = make_manager(
            outputs=[PortConfig(label="main", match="one")],
            registry=reg,
        )
        pm.start()
        return pm, reg

    def test_unknown_label_raises(self):
        pm, _ = self._started_manager()
        try:
            pm.request_switch("nope", "two")
            raised = False
        except ValueError:
            raised = True
        assert raised

    def test_empty_match_raises(self):
        pm, _ = self._started_manager()
        try:
            pm.request_switch("main", "   ")
            raised = False
        except ValueError:
            raised = True
        assert raised

    def test_pending_switch_visible_until_poll(self):
        pm, _ = self._started_manager()
        assert pm.pending_switch is None
        pm.request_switch("main", "two")
        assert pm.pending_switch == ("main", "two")
        pm.poll()
        assert pm.pending_switch is None

    def test_switch_applies_match_and_clears_serial(self):
        reg = FakeRegistry(output_names=["Bus One", "Bus Two"])
        pm = make_manager(
            outputs=[PortConfig(label="main", match="one", serial="s1")],
            registry=reg,
        )
        pm.start()
        state = pm.get_state("main")
        assert state is not None
        assert state.match == "one"
        assert state.serial == "s1"

        pm.request_switch("main", "two")
        pm.poll()

        state = pm.get_state("main")
        assert state is not None
        assert state.match == "two"
        assert state.serial is None
        assert state.status is PortStatus.CONNECTED
        assert state.resolved_name == "Bus Two"

    def test_switch_emits_event_with_new_name(self):
        """CONNECTED → CONNECTED with a new name — PortRegistry reopens on it."""
        pm, _ = self._started_manager()
        pm.request_switch("main", "two")
        events = pm.poll()
        assert len(events) == 1
        ev = events[0]
        assert ev.label == "main"
        assert ev.direction == "output"
        assert ev.old_status is PortStatus.CONNECTED
        assert ev.new_status is PortStatus.CONNECTED
        assert ev.resolved_name == "Bus Two"

    def test_switch_to_missing_device_disconnects(self):
        pm, _ = self._started_manager()
        pm.request_switch("main", "nonexistent")
        events = pm.poll()
        assert len(events) == 1
        assert events[0].new_status is PortStatus.DISCONNECTED
        assert events[0].resolved_name is None

    def test_last_request_wins(self):
        pm, _ = self._started_manager()
        pm.request_switch("main", "nonexistent")
        pm.request_switch("main", "two")
        pm.poll()
        state = pm.get_state("main")
        assert state is not None
        assert state.match == "two"
        assert state.status is PortStatus.CONNECTED

    def test_input_ports_switchable(self):
        reg = FakeRegistry(input_names=["Keys One", "Keys Two"])
        pm = make_manager(
            inputs=[PortConfig(label="keys", match="one")],
            registry=reg,
        )
        pm.start()
        pm.request_switch("keys", "two")
        pm.poll()
        state = pm.get_state("keys")
        assert state is not None
        assert state.match == "two"
        assert state.status is PortStatus.CONNECTED
        assert state.resolved_name == "Keys Two"

    def test_no_event_when_resolves_to_same_device(self):
        """Switching to an equivalent match must not close/reopen the port."""
        pm, _ = self._started_manager()
        pm.request_switch("main", "bus one")  # same device, different case
        events = pm.poll()
        assert events == []
        state = pm.get_state("main")
        assert state is not None
        assert state.resolved_name == "Bus One"
