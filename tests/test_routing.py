"""Tests for MidiPortOutput adapter and PortRegistry."""

from __future__ import annotations

from src.midi.abc import MidiMessage
from src.sync.cc_map import CCMap, CCMapConfig, CCParamOverride
from src.sync.port_state import PortStatus
from src.sync.ports import PortConfig, PortEvent, PortManager, PortsConfig
from src.sync.routing import MidiPortOutput, PortRegistry
from src.sync.throttle import CCThrottle

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeOutPort:
    """Records sent messages instead of writing to hardware."""

    def __init__(self) -> None:
        self.sent: list[MidiMessage] = []
        self.opened_name: str | None = None
        self.closed: bool = False

    def open(self, name: str) -> None:
        self.opened_name = name

    def close(self) -> None:
        self.closed = True

    def send(self, msg: MidiMessage) -> None:
        self.sent.append(msg)


class FakeRegistry:
    """In-memory MidiPortRegistry for testing."""

    def __init__(
        self,
        input_names: list[str] | None = None,
        output_names: list[str] | None = None,
    ) -> None:
        self._input_names = input_names or []
        self._output_names = output_names or []

    def set_outputs(self, names: list[str]) -> None:
        self._output_names = names

    def list_input_names(self) -> list[str]:
        return list(self._input_names)

    def list_output_names(self) -> list[str]:
        return list(self._output_names)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_connected_registry(
    label: str = "Synth A",
    match: str = "Synth",
    resolved_name: str = "Synth Out",
) -> tuple[PortManager, PortRegistry, FakeOutPort]:
    """Build a PortManager + PortRegistry with one connected output port."""
    fake_registry = FakeRegistry(output_names=[resolved_name])
    pm = PortManager(
        PortsConfig(outputs=[PortConfig(label=label, match=match)]),
        fake_registry,
    )
    pm.start()

    fake_port = FakeOutPort()
    pr = PortRegistry(pm, out_port_factory=lambda: fake_port)
    return pm, pr, fake_port


def make_event(
    label: str,
    direction: str = "output",
    role: str = "melodic",
    old_status: PortStatus = PortStatus.DISCONNECTED,
    new_status: PortStatus = PortStatus.CONNECTED,
    resolved_name: str | None = "Synth Out",
) -> PortEvent:
    return PortEvent(
        label=label,
        direction=direction,
        role=role,
        old_status=old_status,
        new_status=new_status,
        resolved_name=resolved_name,
    )


# ---------------------------------------------------------------------------
# MidiPortOutput tests
# ---------------------------------------------------------------------------


class TestMidiPortOutput:
    """Tests for the isobar-compatible output adapter."""

    def test_all_notes_off_sends_cc123_all_channels(self):
        """all_notes_off sends CC 123 on all 16 channels."""
        fake = FakeOutPort()
        out = MidiPortOutput(label="A", port=fake)  # type: ignore[arg-type]
        out.all_notes_off()

        assert len(fake.sent) == 16
        for ch in range(16):
            msg = fake.sent[ch]
            assert msg.type == "control_change"
            assert msg.channel == ch
            assert msg.control == 123
            assert msg.value == 0

    def test_note_on_sends_correct_message(self):
        """note_on produces a MidiMessage.note_on."""
        fake = FakeOutPort()
        out = MidiPortOutput(label="A", port=fake)  # type: ignore[arg-type]
        out.note_on(channel=0, note=60, velocity=100)

        assert len(fake.sent) == 1
        msg = fake.sent[0]
        assert msg.type == "note_on"
        assert msg.channel == 0
        assert msg.note == 60
        assert msg.velocity == 100

    def test_note_off_sends_correct_message(self):
        """note_off produces a MidiMessage.note_off."""
        fake = FakeOutPort()
        out = MidiPortOutput(label="A", port=fake)  # type: ignore[arg-type]
        out.note_off(channel=1, note=64)

        assert len(fake.sent) == 1
        msg = fake.sent[0]
        assert msg.type == "note_off"
        assert msg.channel == 1
        assert msg.note == 64

    def test_control_change_sends_correct_message(self):
        """control_change produces a MidiMessage.cc."""
        fake = FakeOutPort()
        out = MidiPortOutput(label="A", port=fake)  # type: ignore[arg-type]
        out.control_change(channel=2, control=74, value=64)

        assert len(fake.sent) == 1
        msg = fake.sent[0]
        assert msg.type == "control_change"
        assert msg.channel == 2
        assert msg.control == 74
        assert msg.value == 64

    def test_numpy_int64_converted_to_int(self):
        """numpy.int64 values are converted to plain int."""
        import numpy as np

        fake = FakeOutPort()
        out = MidiPortOutput(label="A", port=fake)  # type: ignore[arg-type]
        out.note_on(
            channel=np.int64(0),
            note=np.int64(60),
            velocity=np.int64(100),
        )

        msg = fake.sent[0]
        # numpy.int64 is a subclass of int, so isinstance check confirms
        # the value was accepted; the important thing is no TypeError.
        assert isinstance(msg.channel, int)
        assert not isinstance(msg.channel, np.integer)
        assert msg.channel == 0
        assert msg.note == 60
        assert msg.velocity == 100

    def test_label_stored(self):
        """Adapter stores the human-readable label."""
        fake = FakeOutPort()
        out = MidiPortOutput(label="Синт A", port=fake)  # type: ignore[arg-type]
        assert out.label == "Синт A"


# ---------------------------------------------------------------------------
# MidiPortOutput.control() tests — CC mapping + throttling
# ---------------------------------------------------------------------------


def make_cc_map(**kwargs) -> CCMap:
    """Build a CCMap with sensible defaults for testing."""
    config = CCMapConfig(
        default={"filter": 74, "volume": 7},
        **kwargs,
    )
    return CCMap(config)


class TestControl:
    """Tests for MidiPortOutput.control() — logical names + throttling."""

    def test_control_resolves_name_to_cc(self):
        """control() resolves logical name via CCMap."""
        fake = FakeOutPort()
        cc_map = make_cc_map()
        out = MidiPortOutput(label="A", port=fake, cc_map=cc_map)  # type: ignore[arg-type]
        out.control(param_name="filter", channel=0, value=64)

        assert len(fake.sent) == 1
        msg = fake.sent[0]
        assert msg.type == "control_change"
        assert msg.control == 74
        assert msg.value == 64

    def test_control_port_override(self):
        """control() uses port-specific CC override."""
        fake = FakeOutPort()
        cc_map = make_cc_map(
            ports={"A": {"filter": 22}},
        )
        out = MidiPortOutput(label="A", port=fake, cc_map=cc_map)  # type: ignore[arg-type]
        out.control(param_name="filter", channel=0, value=64)

        msg = fake.sent[0]
        assert msg.control == 22

    def test_control_invert(self):
        """control() applies invert from CCMapEntry."""
        fake = FakeOutPort()
        cc_map = make_cc_map(
            ports={"A": {"filter": CCParamOverride(cc=74, invert=True)}},
        )
        out = MidiPortOutput(label="A", port=fake, cc_map=cc_map)  # type: ignore[arg-type]
        out.control(param_name="filter", channel=0, value=0)

        msg = fake.sent[0]
        assert msg.value == 127  # inverted

    def test_control_range(self):
        """control() applies range from CCMapEntry."""
        fake = FakeOutPort()
        cc_map = make_cc_map(
            ports={"A": {"filter": CCParamOverride(cc=74, range=(20, 110))}},
        )
        out = MidiPortOutput(label="A", port=fake, cc_map=cc_map)  # type: ignore[arg-type]
        out.control(param_name="filter", channel=0, value=0)

        msg = fake.sent[0]
        assert msg.value == 20  # mapped to range lo

    def test_control_no_automation_port_ignored(self):
        """control() on _no_automation port sends nothing."""
        fake = FakeOutPort()
        cc_map = make_cc_map(
            ports={"LCXL3": {"_no_automation": True}},  # type: ignore[dict-item]
        )
        out = MidiPortOutput(label="LCXL3", port=fake, cc_map=cc_map)  # type: ignore[arg-type]
        out.control(param_name="filter", channel=0, value=64)

        assert len(fake.sent) == 0

    def test_control_unknown_param_ignored(self):
        """control() with unknown param sends nothing (warning logged)."""
        fake = FakeOutPort()
        cc_map = make_cc_map()
        out = MidiPortOutput(label="A", port=fake, cc_map=cc_map)  # type: ignore[arg-type]
        out.control(param_name="nonexistent", channel=0, value=64)

        assert len(fake.sent) == 0

    def test_control_no_cc_map_ignored(self):
        """control() without CCMap sends nothing."""
        fake = FakeOutPort()
        out = MidiPortOutput(label="A", port=fake)  # type: ignore[arg-type]
        out.control(param_name="filter", channel=0, value=64)

        assert len(fake.sent) == 0

    def test_control_with_throttle_deferred(self):
        """control() with throttle defers rapid sends to flush()."""
        fake = FakeOutPort()
        cc_map = make_cc_map()
        throttle = CCThrottle(max_rate_hz=30.0)
        out = MidiPortOutput(
            label="A", port=fake, cc_map=cc_map, throttle=throttle
        )  # type: ignore[arg-type]

        out.control(param_name="filter", channel=0, value=64)
        assert len(fake.sent) == 1  # first goes through

        out.control(param_name="filter", channel=0, value=80)
        assert len(fake.sent) == 1  # throttled

        out.flush()
        assert len(fake.sent) == 2  # flush delivers
        assert fake.sent[1].value == 80

    def test_control_without_throttle_sends_immediately(self):
        """control() without throttle sends immediately."""
        fake = FakeOutPort()
        cc_map = make_cc_map()
        out = MidiPortOutput(label="A", port=fake, cc_map=cc_map)  # type: ignore[arg-type]

        out.control(param_name="filter", channel=0, value=64)
        out.control(param_name="filter", channel=0, value=80)
        assert len(fake.sent) == 2  # no throttling

    def test_flush_no_throttle_noop(self):
        """flush() without throttle is a no-op."""
        fake = FakeOutPort()
        out = MidiPortOutput(label="A", port=fake)  # type: ignore[arg-type]
        out.flush()  # should not raise

    def test_all_notes_off_resets_throttle(self):
        """all_notes_off() resets the throttle."""
        fake = FakeOutPort()
        cc_map = make_cc_map()
        throttle = CCThrottle(max_rate_hz=30.0)
        out = MidiPortOutput(
            label="A", port=fake, cc_map=cc_map, throttle=throttle
        )  # type: ignore[arg-type]

        out.control(param_name="filter", channel=0, value=64)
        out.control(param_name="filter", channel=0, value=80)
        assert throttle.pending_count() == 1

        # Clear sent messages to count only new ones
        fake.sent.clear()
        out.all_notes_off()
        assert throttle.pending_count() == 0


# ---------------------------------------------------------------------------
# PortRegistry tests
# ---------------------------------------------------------------------------


class TestPortRegistry:
    """Tests for the port lifecycle registry."""

    def test_get_output_none_when_disconnected(self):
        """get_output returns None when port is not connected."""
        fake_registry = FakeRegistry(output_names=[])
        pm = PortManager(
            PortsConfig(outputs=[PortConfig(label="A", match="Synth")]),
            fake_registry,
        )
        pm.start()
        pr = PortRegistry(pm, out_port_factory=lambda: FakeOutPort())
        assert pr.get_output("A") is None

    def test_get_output_returns_adapter_when_connected(self):
        """get_output returns MidiPortOutput after CONNECTED event."""
        _pm, pr, fake_port = make_connected_registry()
        pr.handle_port_event(make_event("Synth A"))

        adapter = pr.get_output("Synth A")
        assert adapter is not None
        assert adapter.label == "Synth A"
        assert fake_port.opened_name == "Synth Out"

    def test_handle_connect_event_opens_port(self):
        """CONNECTED event opens the port."""
        _pm, pr, fake_port = make_connected_registry()
        pr.handle_port_event(make_event("Synth A"))

        assert fake_port.opened_name == "Synth Out"
        assert pr.get_output("Synth A") is not None

    def test_handle_disconnect_event_closes_port(self):
        """DISCONNECTED event sends all_notes_off and closes the port."""
        _pm, pr, fake_port = make_connected_registry()
        pr.handle_port_event(make_event("Synth A"))
        assert pr.get_output("Synth A") is not None

        # Simulate disconnect
        pr.handle_port_event(
            make_event(
                "Synth A",
                old_status=PortStatus.CONNECTED,
                new_status=PortStatus.DISCONNECTED,
                resolved_name=None,
            )
        )

        assert pr.get_output("Synth A") is None
        assert fake_port.closed is True
        # all_notes_off was called before close (16 CC 123 messages)
        cc123_count = sum(
            1 for m in fake_port.sent if m.type == "control_change" and m.control == 123
        )
        assert cc123_count == 16

    def test_handle_ambiguous_event_closes_port(self):
        """AMBIGUOUS event sends all_notes_off and closes the port."""
        _pm, pr, fake_port = make_connected_registry()
        pr.handle_port_event(make_event("Synth A"))

        pr.handle_port_event(
            make_event(
                "Synth A",
                old_status=PortStatus.CONNECTED,
                new_status=PortStatus.AMBIGUOUS,
                resolved_name=None,
            )
        )

        assert pr.get_output("Synth A") is None
        assert fake_port.closed is True

    def test_handle_input_event_ignored(self):
        """Input-direction events are ignored by the registry."""
        _pm, pr, fake_port = make_connected_registry()
        pr.handle_port_event(
            make_event("Synth A", direction="input", resolved_name="In Port")
        )
        assert pr.get_output("Synth A") is None
        assert fake_port.opened_name is None

    def test_all_outputs_returns_active_adapters(self):
        """all_outputs returns a list of active adapters."""
        fake_registry = FakeRegistry(output_names=["Synth A Out", "Synth B Out"])
        pm = PortManager(
            PortsConfig(
                outputs=[
                    PortConfig(label="A", match="Synth A"),
                    PortConfig(label="B", match="Synth B"),
                ]
            ),
            fake_registry,
        )
        pm.start()

        fake_a = FakeOutPort()
        fake_b = FakeOutPort()
        ports_created = [fake_a, fake_b]
        pr = PortRegistry(pm, out_port_factory=lambda: ports_created.pop(0))

        pr.handle_port_event(make_event("A", resolved_name="Synth A Out"))
        pr.handle_port_event(make_event("B", resolved_name="Synth B Out"))

        outputs = pr.all_outputs()
        assert len(outputs) == 2
        labels = {o.label for o in outputs}
        assert labels == {"A", "B"}

    def test_stop_closes_all_ports(self):
        """stop() closes all active ports."""
        _pm, pr, fake_port = make_connected_registry()
        pr.handle_port_event(make_event("Synth A"))
        assert pr.get_output("Synth A") is not None

        pr.stop()
        assert pr.get_output("Synth A") is None
        assert fake_port.closed is True

    def test_reconnect_closes_old_port(self):
        """Reconnect (CONNECTED when already open) closes the old port first."""
        _pm, pr, fake_port = make_connected_registry()
        pr.handle_port_event(make_event("Synth A"))
        assert fake_port.opened_name == "Synth Out"

        # Simulate reconnect with a different resolved name
        fake_port2 = FakeOutPort()
        pr._factory = lambda: fake_port2  # type: ignore[attr-defined]
        pr.handle_port_event(make_event("Synth A", resolved_name="Synth Out 2"))

        assert fake_port.closed is True
        assert fake_port2.opened_name == "Synth Out 2"
        assert pr.get_output("Synth A") is not None

    def test_open_failure_no_crash(self):
        """Failed port open is logged, no adapter created."""
        fake_registry = FakeRegistry(output_names=["Synth Out"])
        pm = PortManager(
            PortsConfig(outputs=[PortConfig(label="A", match="Synth")]),
            fake_registry,
        )
        pm.start()

        def failing_factory() -> FakeOutPort:
            port = FakeOutPort()

            def _boom(name: str) -> None:
                raise RuntimeError("Cannot open")

            port.open = _boom  # type: ignore[method-assign]
            return port

        pr = PortRegistry(pm, out_port_factory=failing_factory)
        pr.handle_port_event(make_event("A"))

        assert pr.get_output("A") is None


# ---------------------------------------------------------------------------
# PortRegistry with CCMap and CCThrottle tests
# ---------------------------------------------------------------------------


class TestPortRegistryWithCC:
    """Tests for PortRegistry integration with CCMap and CCThrottle."""

    def test_opened_port_receives_cc_map_and_throttle(self):
        """Ports opened by the registry have cc_map and throttle."""
        _pm, pr, _fake_port = make_connected_registry()
        cc_map = make_cc_map()
        throttle = CCThrottle(max_rate_hz=30.0)
        pr._cc_map = cc_map  # type: ignore[attr-defined]
        pr._throttle = throttle  # type: ignore[attr-defined]

        pr.handle_port_event(make_event("Synth A"))
        adapter = pr.get_output("Synth A")
        assert adapter is not None
        assert adapter._cc_map is cc_map  # type: ignore[attr-defined]
        assert adapter._throttle is throttle  # type: ignore[attr-defined]

    def test_flush_all_flushes_all_ports(self):
        """flush_all() calls flush on every active adapter."""
        fake_registry = FakeRegistry(output_names=["Synth A Out", "Synth B Out"])
        pm = PortManager(
            PortsConfig(
                outputs=[
                    PortConfig(label="A", match="Synth A"),
                    PortConfig(label="B", match="Synth B"),
                ]
            ),
            fake_registry,
        )
        pm.start()

        fake_a = FakeOutPort()
        fake_b = FakeOutPort()
        ports = [fake_a, fake_b]
        cc_map = make_cc_map()
        throttle = CCThrottle(max_rate_hz=30.0)
        pr = PortRegistry(
            pm,
            out_port_factory=lambda: ports.pop(0),
            cc_map=cc_map,
            throttle=throttle,
        )

        pr.handle_port_event(make_event("A", resolved_name="Synth A Out"))
        pr.handle_port_event(make_event("B", resolved_name="Synth B Out"))

        # Send CC on both ports (first goes through, second is throttled)
        adapter_a = pr.get_output("A")
        adapter_b = pr.get_output("B")
        assert adapter_a is not None
        assert adapter_b is not None
        adapter_a.control(param_name="filter", channel=0, value=64)
        adapter_b.control(param_name="filter", channel=0, value=64)

        pr.flush_all()

        # Both ports should have received their CC
        assert len(fake_a.sent) == 1
        assert len(fake_b.sent) == 1

    def test_flush_port_flushes_specific_port(self):
        """flush_port() calls flush on a specific adapter."""
        _pm, pr, fake_port = make_connected_registry()
        cc_map = make_cc_map()
        throttle = CCThrottle(max_rate_hz=30.0)
        pr._cc_map = cc_map  # type: ignore[attr-defined]
        pr._throttle = throttle  # type: ignore[attr-defined]

        pr.handle_port_event(make_event("Synth A"))
        adapter = pr.get_output("Synth A")
        assert adapter is not None

        adapter.control(param_name="filter", channel=0, value=64)
        adapter.control(param_name="filter", channel=0, value=80)

        pr.flush_port("Synth A")
        assert len(fake_port.sent) == 2

    def test_flush_port_unknown_label_noop(self):
        """flush_port() with unknown label does not raise."""
        _pm, pr, _fake_port = make_connected_registry()
        pr.flush_port("Nonexistent")  # should not raise
