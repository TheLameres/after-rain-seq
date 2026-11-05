"""Исходящий MIDI Clock и Start/Continue/Stop (src/sync/midi_clock_out.py)."""

from __future__ import annotations

import pytest

from src.midi.abc import MidiMessage
from src.sync.midi_clock_out import (
    MAX_CATCHUP,
    PPQ,
    MidiClockOutput,
    make_clock_sender,
)
from src.sync.ports import PortConfig


class Sink:
    """Записывает отправленные сообщения по порядку."""

    def __init__(self) -> None:
        self.msgs: list[str] = []

    def __call__(self, msg: MidiMessage) -> None:
        self.msgs.append(msg.type)

    def count(self, kind: str) -> int:
        return self.msgs.count(kind)


def _make(master: bool = True) -> tuple[MidiClockOutput, Sink]:
    sink = Sink()
    return MidiClockOutput(sink, is_master=lambda: master), sink


# ---------------------------------------------------------------------------
# Start / Continue / Stop
# ---------------------------------------------------------------------------


class TestTransportMessages:
    def test_start_from_zero_sends_start(self) -> None:
        out, sink = _make()
        out.start(0.0)
        assert sink.msgs == ["start"]
        assert out.running

    def test_resume_from_position_sends_continue(self) -> None:
        out, sink = _make()
        out.start(0.0)
        out.stop()
        out.start(1.5)
        assert sink.msgs == ["start", "stop", "continue"]

    def test_stop_sends_stop_once(self) -> None:
        out, sink = _make()
        out.start(0.0)
        out.stop()
        out.stop()  # повторный стоп ничего не шлёт
        assert sink.count("stop") == 1
        assert not out.running

    def test_stop_without_start_is_silent(self) -> None:
        out, sink = _make()
        out.stop()
        assert sink.msgs == []

    def test_start_precedes_first_clock_pulse(self) -> None:
        out, sink = _make()
        out.start(0.0)
        out.on_position(0.0)
        assert sink.msgs[0] == "start"
        assert sink.msgs[1] == "clock"


# ---------------------------------------------------------------------------
# Clock pulses
# ---------------------------------------------------------------------------


class TestClockPulses:
    def test_24_pulses_per_beat(self) -> None:
        out, sink = _make()
        out.start(0.0)
        out.on_position(0.999999)  # позиции 0..23 — ровно один бит
        assert sink.count("clock") == PPQ

    def test_pulses_do_not_repeat_on_same_position(self) -> None:
        out, sink = _make()
        out.start(0.0)
        out.on_position(2.0)
        before = sink.count("clock")
        assert out.on_position(2.0) == 0
        assert sink.count("clock") == before

    def test_pulses_follow_beat_not_call_count(self) -> None:
        """Количество импульсов зависит только от позиции, а не от числа тиков."""
        out, sink = _make()
        out.start(0.0)
        beat = 0.0
        while beat < 3.0:
            out.on_position(beat)
            beat += 0.013  # произвольный шаг тиков
        out.on_position(3.0)
        assert sink.count("clock") == 3 * PPQ + 1  # 0..72 включительно

    def test_continue_starts_on_next_grid_point(self) -> None:
        """После Continue с 1.5 бита первый импульс — ровно на 1.5 (индекс 36)."""
        out, sink = _make()
        out.start(0.0)
        out.stop()  # до этого on_position не вызывался — импульсов не было
        out.start(1.5)
        assert out.on_position(1.5) == 1  # только позиция 1.5, без догонки 0..35
        assert sink.count("clock") == 1

    def test_no_pulses_after_stop(self) -> None:
        out, sink = _make()
        out.start(0.0)
        out.on_position(0.5)
        out.stop()
        before = sink.count("clock")
        assert out.on_position(4.0) == 0
        assert sink.count("clock") == before

    def test_catchup_is_bounded(self) -> None:
        out, sink = _make()
        out.start(0.0)
        out.on_position(0.0)
        base = sink.count("clock")
        out.on_position(20.0)  # провал тиков на 20 бит
        assert sink.count("clock") - base == MAX_CATCHUP


# ---------------------------------------------------------------------------
# Master gating (внешний MIDI-клок — ничего не шлём)
# ---------------------------------------------------------------------------


class TestMasterGating:
    def test_external_clock_sends_nothing(self) -> None:
        out, sink = _make(master=False)
        out.start(0.0)
        out.on_position(4.0)
        out.stop()
        assert sink.msgs == []
        assert not out.running

    def test_master_switch_mid_run_stops_pulses(self) -> None:
        flag = {"master": True}
        sink = Sink()
        out = MidiClockOutput(sink, is_master=lambda: flag["master"])
        out.start(0.0)
        out.on_position(1.0)
        flag["master"] = False
        out.on_position(2.0)
        assert sink.count("clock") == PPQ + 1  # индексы 0..24, дальше тишина


# ---------------------------------------------------------------------------
# make_clock_sender: только порты с clock: true, открытые сейчас
# ---------------------------------------------------------------------------


class FakePort:
    def __init__(self) -> None:
        self.received: list[str] = []

    def send_realtime(self, msg: MidiMessage) -> None:
        self.received.append(msg.type)


class TestClockSender:
    def test_sends_only_to_wanted_labels(self) -> None:
        a, b = FakePort(), FakePort()
        send = make_clock_sender(lambda: {"main": a, "drums": b}, labels=["main"])
        send(MidiMessage.clock())
        assert a.received == ["clock"]
        assert b.received == []

    def test_closed_port_is_skipped(self) -> None:
        """Порт, которого нет в открытых выходах (hot-plug), пропускается без ошибки."""
        a = FakePort()
        send = make_clock_sender(lambda: {"main": a}, labels=["main", "missing"])
        send(MidiMessage.start())
        assert a.received == ["start"]

    def test_no_labels_sends_nothing(self) -> None:
        a = FakePort()
        send = make_clock_sender(lambda: {"main": a}, labels=[])
        send(MidiMessage.clock())
        assert a.received == []

    def test_no_outputs_callable_is_safe(self) -> None:
        send = make_clock_sender(None, labels=["main"])
        send(MidiMessage.clock())  # не падает

    def test_sender_reads_outputs_each_call(self) -> None:
        """Hot-plug: новый выход появляется без пересборки отправителя."""
        current: dict[str, FakePort] = {}
        send = make_clock_sender(lambda: current, labels=["late"])
        send(MidiMessage.clock())
        late = FakePort()
        current["late"] = late
        send(MidiMessage.clock())
        assert late.received == ["clock"]


# ---------------------------------------------------------------------------
# Конфиг и адаптер порта
# ---------------------------------------------------------------------------


class TestConfigAndAdapter:
    def test_clock_defaults_to_true(self) -> None:
        assert PortConfig(label="main", match="IAC").clock is True

    def test_clock_can_be_disabled(self) -> None:
        assert PortConfig(label="drums", match="IAC", clock=False).clock is False

    def test_send_realtime_bypasses_throttle(self) -> None:
        from src.sync.routing import MidiPortOutput

        class RawPort:
            def __init__(self) -> None:
                self.sent: list[str] = []

            def send(self, msg: MidiMessage) -> None:
                self.sent.append(msg.type)

        raw = RawPort()
        adapter = MidiPortOutput("main", raw)  # type: ignore[arg-type]
        adapter.send_realtime(MidiMessage.clock())
        adapter.send_realtime(MidiMessage.start())
        assert raw.sent == ["clock", "start"]


# ---------------------------------------------------------------------------
# Порядок событий у ClockManager
# ---------------------------------------------------------------------------


class _Timeline:
    current_time = 0.0


class _Proxy:
    def set_on_idle(self, cb) -> None:
        pass


class TestClockManagerTransportEvents:
    @pytest.fixture()
    def cm(self, monkeypatch: pytest.MonkeyPatch):
        from src.sync.clock_manager import ClockManager
        from src.sync.clock_source import ClockManagerConfig, ClockSource

        order: list[str] = []
        manager = ClockManager(
            _Timeline(),  # type: ignore[arg-type]
            _Proxy(),  # type: ignore[arg-type]
            ClockManagerConfig(
                initial_source=ClockSource.INTERNAL,
                initial_bpm=120.0,
                ticks_per_beat=480,
            ),
        )
        monkeypatch.setattr(
            manager, "_activate_source", lambda *a: order.append("activate")
        )
        monkeypatch.setattr(
            manager, "_stop_current_source", lambda: order.append("source-stop")
        )
        manager._order = order  # type: ignore[attr-defined]
        return manager

    def test_start_notifies_before_source_activation(self, cm) -> None:
        events: list[tuple[str, float]] = []
        cm.add_transport_listener(lambda e, b: events.append((e, b)))
        cm._order.append("listener-check")
        cm.start()
        assert events == [("start", 0.0)]
        assert cm._order.index("activate") > 0

    def test_stop_notifies_before_source_stop(self, cm) -> None:
        seen: list[str] = []
        cm.add_transport_listener(lambda e, _b: seen.append(e))
        cm.start()
        cm.stop()
        assert seen == ["start", "stop"]
        assert cm._order.index("source-stop") > cm._order.index("activate")

    def test_listener_error_does_not_break_transport(self, cm) -> None:
        def boom(_e: str, _b: float) -> None:
            raise RuntimeError("port gone")

        cm.add_transport_listener(boom)
        cm.start()  # не падает
        assert cm.state.running


class TestAppWiring:
    """Проводка в App: только порты с clock: true, старт/стоп из ClockManager."""

    def _app(self, labels: set[str], source_name: str = "INTERNAL"):
        from src.app.application import App
        from src.sync.clock_source import ClockSource

        class FakeOut:
            def __init__(self, label: str) -> None:
                self.label = label
                self.received: list[str] = []

            def send_realtime(self, msg: MidiMessage) -> None:
                self.received.append(msg.type)

        outs = {lbl: FakeOut(lbl) for lbl in ("main", "drums", "off")}

        class FakeRegistry:
            def all_outputs(self):
                return list(outs.values())

        class FakeCM:
            current_source = getattr(ClockSource, source_name)

            def __init__(self) -> None:
                self.listeners: list = []

            def add_transport_listener(self, fn) -> None:
                self.listeners.append(fn)

        app = App.__new__(App)
        app._clock_labels = frozenset(labels)  # type: ignore[attr-defined]
        app._port_registry = FakeRegistry()  # type: ignore[attr-defined]
        app._clock_manager = FakeCM()  # type: ignore[attr-defined]
        app._midi_clock = None  # type: ignore[attr-defined]
        app._init_midi_clock_out()  # type: ignore[attr-defined]
        return app, outs

    def test_only_clock_labels_receive_messages(self) -> None:
        app, outs = self._app({"main"})
        app._on_transport_clock("start", 0.0)  # type: ignore[attr-defined]
        app._midi_clock.on_position(0.0)  # type: ignore[attr-defined]
        assert outs["main"].received == ["start", "clock"]
        assert outs["drums"].received == []
        assert outs["off"].received == []

    def test_stop_from_clock_manager_reaches_port(self) -> None:
        app, outs = self._app({"main"})
        app._on_transport_clock("start", 0.0)  # type: ignore[attr-defined]
        app._on_transport_clock("stop", 0.0)  # type: ignore[attr-defined]
        assert outs["main"].received == ["start", "stop"]

    def test_no_labels_means_no_clock_output(self) -> None:
        app, _outs = self._app(set())
        assert app._midi_clock is None  # type: ignore[attr-defined]
        app._on_transport_clock("start", 0.0)  # type: ignore[attr-defined]  # не падает

    def test_external_midi_source_disables_output(self) -> None:
        app, outs = self._app({"main"}, source_name="MIDI")
        app._on_transport_clock("start", 0.0)  # type: ignore[attr-defined]
        app._midi_clock.on_position(4.0)  # type: ignore[attr-defined]
        assert outs["main"].received == []


class TestHookWiring:
    """Регрессия: хук тика ставится в _init_clock_manager, а клок создаётся позже.

    Раньше хук захватывал _midi_clock=None и импульсы не уходили никуда.
    """

    def test_tick_hook_sends_clock_created_after_hook_install(self) -> None:
        import queue
        from types import SimpleNamespace

        from src.app.application import App
        from src.session.session import Session
        from src.sync.swing import SwingApplier, SwingConfig

        class Out:
            def __init__(self, label: str) -> None:
                self.label = label
                self.received: list[str] = []

            def send_realtime(self, msg: MidiMessage) -> None:
                self.received.append(msg.type)

            def flush(self) -> None:
                pass

        main, off = Out("main"), Out("off")

        class Reg:
            def all_outputs(self):
                return [main, off]

            def flush_all(self) -> None:
                pass

            def get_output(self, label: str):
                return {"main": main, "off": off}.get(label)

        class Cfg:
            enabled = True
            clock_source = "internal"
            midi_clock_device = None
            bpm = 120.0
            swing_amount = 0.0

        app = App(config_path="config.yaml", simulate=True)
        app._session = Session()
        app._port_registry = Reg()
        app._swing_applier = SwingApplier(SwingConfig(amount=0.0))
        app._event_queue = queue.Queue()
        app._clock_labels = frozenset({"main"})
        app._init_clock_manager(Cfg())  # хук ставится здесь
        app._init_midi_clock_out()  # клок создаётся уже после установки хука
        assert app._midi_clock is not None
        cm = app._clock_manager
        cm._activate_source = lambda *a, **k: None  # без реального устройства
        cm._stop_current_source = lambda *a, **k: None
        cm.start()

        hook = app._tick_proxy._dispatch
        hook(SimpleNamespace(name="TICK"))

        assert main.received[:2] == ["start", "clock"]
        assert off.received == []
