"""Поток исходящего MIDI: буфер, команда REPL `midi`, отброшенные события."""

from __future__ import annotations

import queue

from src.app.application import App
from src.app.engine_control import AppEngineControl
from src.repl.executor import CommandExecutor
from src.session.session import Session
from src.sync.midi_trace import MidiTrace, MidiTraceEntry, format_entry
from src.sync.swing import SwingApplier, SwingConfig
from src.sync.transport import Transport
from src.sync.transport_event import EventKind, TransportEvent


class Sink:
    """Порт, который запоминает, что до него дошло."""

    label = "main"

    def __init__(self) -> None:
        self.notes_on: list[tuple[int, int]] = []
        self.notes_off: list[int] = []

    def note_on(self, channel: int, note: int, velocity: int) -> None:
        self.notes_on.append((note, velocity))

    def note_off(self, channel: int, note: int) -> None:
        self.notes_off.append(note)

    def control_change(self, **kwargs: int) -> None:
        pass

    def all_notes_off(self) -> None:
        pass

    def flush(self) -> None:
        pass


class Registry:
    def __init__(self, labels: tuple[str, ...] = ("main",)) -> None:
        self.sink = Sink()
        self._labels = set(labels)

    def get_output(self, label: str) -> Sink | None:
        return self.sink if label in self._labels else None

    def all_outputs(self) -> list[Sink]:
        return [self.sink]

    def flush_all(self) -> None:
        pass


def _transport(labels: tuple[str, ...] = ("main",)) -> tuple[Transport, Registry]:
    q: queue.Queue[TransportEvent] = queue.Queue(maxsize=1024)
    reg = Registry(labels)
    return Transport(q, reg, SwingApplier(SwingConfig(amount=0.0))), reg  # type: ignore[arg-type]


def _queue(transport: Transport) -> queue.Queue:
    return transport._queue  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Буфер
# ---------------------------------------------------------------------------


class TestMidiTraceBuffer:
    def test_disabled_by_default_writes_nothing(self) -> None:
        transport, _ = _transport()
        assert transport.trace is None
        _queue(transport).put_nowait(TransportEvent.note_on("main", 0, 60, 100))
        transport.process_events(0.0)
        assert transport.trace is None

    def test_records_delivered_event(self) -> None:
        transport, reg = _transport()
        trace = transport.enable_trace()
        _queue(transport).put_nowait(TransportEvent.note_on("main", 0, 60, 100))
        transport.process_events(0.0)
        assert reg.sink.notes_on == [(60, 100)]
        [entry] = trace.recent(10)
        assert (entry.kind, entry.note, entry.velocity) == ("note_on", 60, 100)
        assert entry.delivered is True

    def test_records_dropped_event(self) -> None:
        """Порт не найден — событие всё равно видно, с пометкой."""
        transport, _ = _transport(labels=())  # порта 'main' нет
        trace = transport.enable_trace()
        _queue(transport).put_nowait(TransportEvent.note_on("main", 0, 60, 100))
        transport.process_events(0.0)
        [entry] = trace.recent(10)
        assert entry.delivered is False
        assert "ОТБРОШЕНО" in format_entry(entry)

    def test_capacity_evicts_oldest(self) -> None:
        trace = MidiTrace(capacity=3)
        for i in range(5):
            trace.record(
                MidiTraceEntry(
                    beat=float(i), port="main", channel=0, kind="note_on", note=i
                )
            )
        beats = [e.beat for e in trace.recent(10)]
        assert beats == [2.0, 3.0, 4.0]
        assert len(trace) == 3

    def test_recent_zero_or_negative_is_empty(self) -> None:
        trace = MidiTrace()
        trace.record(MidiTraceEntry(beat=0.0, port="main", channel=0, kind="note_on"))
        assert trace.recent(0) == []
        assert trace.recent(-5) == []

    def test_clear(self) -> None:
        transport, _ = _transport()
        trace = transport.enable_trace()
        _queue(transport).put_nowait(TransportEvent.note_on("main", 0, 60, 100))
        transport.process_events(0.0)
        assert len(trace) == 1
        trace.clear()
        assert len(trace) == 0

    def test_disable_trace_stops_recording(self) -> None:
        transport, _ = _transport()
        trace = transport.enable_trace()
        _queue(transport).put_nowait(TransportEvent.note_on("main", 0, 60, 100))
        transport.process_events(0.0)
        assert len(trace) == 1

        transport.disable_trace()
        _queue(transport).put_nowait(TransportEvent.note_on("main", 0, 62, 100))
        transport.process_events(1.0)
        assert transport.trace is None
        assert len(trace) == 1  # старый буфер не пополняется


class TestEntryFromEvent:
    def test_cc_fields(self) -> None:
        ev = TransportEvent(
            kind=EventKind.CONTROL_CHANGE,
            port_label="main",
            channel=3,
            control=74,
            value=99,
        )
        entry = MidiTrace.entry_from(ev, delivered=True)
        assert (entry.kind, entry.control, entry.value) == ("cc", 74, 99)

    def test_all_notes_off(self) -> None:
        entry = MidiTrace.entry_from(
            TransportEvent.all_notes_off(port_label="main"), delivered=True
        )
        assert entry.kind == "all_notes_off"

    def test_note_off_has_no_velocity(self) -> None:
        entry = MidiTrace.entry_from(
            TransportEvent.note_off("main", 0, 60), delivered=True
        )
        assert entry.kind == "note_off"
        assert entry.velocity is None


class TestFormatEntry:
    def test_note_on_shows_velocity(self) -> None:
        line = format_entry(
            MidiTraceEntry(
                beat=1.5, port="main", channel=0, kind="note_on", note=60, velocity=100
            )
        )
        assert (
            "1.500" in line
            and "main" in line
            and "note_on" in line
            and "vel 100" in line
        )

    def test_track_name_appears(self) -> None:
        line = format_entry(
            MidiTraceEntry(
                beat=0.0, port="main", channel=0, kind="note_on", note=60, velocity=1
            ),
            "Pad 1",
        )
        assert "Pad 1" in line

    def test_no_track_is_dash(self) -> None:
        line = format_entry(
            MidiTraceEntry(beat=0.0, port="main", channel=0, kind="note_off", note=60)
        )
        assert "—" in line


# ---------------------------------------------------------------------------
# Фасад и команда REPL
# ---------------------------------------------------------------------------


def _app() -> tuple[App, AppEngineControl]:
    app = App(config_path="config.yaml", simulate=True)
    app._session = Session()
    app._event_queue = queue.Queue(maxsize=1024)
    app._transport = Transport(
        app._event_queue,
        Registry(),
        SwingApplier(SwingConfig(amount=0.0)),  # type: ignore[arg-type]
    )
    return app, AppEngineControl(app)


class TestFacade:
    def test_on_then_off(self) -> None:
        app, ctl = _app()
        assert not ctl.set_midi_trace(True).error
        assert app.transport.trace is not None  # type: ignore[union-attr]
        assert not ctl.set_midi_trace(False).error
        assert app.transport.trace is None  # type: ignore[union-attr]

    def test_clear_when_off_is_error(self) -> None:
        _, ctl = _app()
        assert ctl.clear_midi_trace().error

    def test_trace_empty_when_off(self) -> None:
        _, ctl = _app()
        assert ctl.midi_trace(10) == []

    def test_no_transport_is_error(self) -> None:
        ctl = AppEngineControl(App(config_path="config.yaml", simulate=True))
        assert ctl.set_midi_trace(True).error

    def test_events_reach_facade(self) -> None:
        app, ctl = _app()
        ctl.set_midi_trace(True)
        app._transport._queue.put_nowait(  # type: ignore[union-attr]
            TransportEvent.note_on("main", 0, 64, 90)
        )
        app._transport.process_events(0.0)  # type: ignore[union-attr]
        [entry] = ctl.midi_trace(5)
        assert isinstance(entry, MidiTraceEntry)
        assert entry.note == 64


def _repl() -> tuple[CommandExecutor, App, Session]:
    app, ctl = _app()
    return CommandExecutor(ctl), app, app._session


class TestMidiCommand:
    def test_lists_events_with_track_name(self) -> None:
        ex, app, session = _repl()
        track = session.create_melodic_track("pad")
        track.port = "main"
        track.channel = 0
        ex.execute("midi on")
        app._transport._queue.put_nowait(  # type: ignore[union-attr]
            TransportEvent.note_on("main", 0, 60, 100)
        )
        app._transport.process_events(0.0)  # type: ignore[union-attr]
        res = ex.execute("midi")
        assert res.code == 0
        assert "note_on" in res.output and "Pad 1" in res.output

    def test_n_limits_lines(self) -> None:
        ex, app, _ = _repl()
        ex.execute("midi on")
        for i in range(5):
            app._transport._queue.put_nowait(  # type: ignore[union-attr]
                TransportEvent.note_on("main", 0, 60 + i, 100)
            )
        app._transport.process_events(0.0)  # type: ignore[union-attr]
        res = ex.execute("midi 2")
        lines = res.output.splitlines()
        assert len(lines) == 2
        assert (
            "63" in lines[0] and "64" in lines[1]
        )  # последние две, в порядке отправки

    def test_empty_is_message_not_crash(self) -> None:
        ex, _, _ = _repl()
        res = ex.execute("midi")
        assert "no MIDI events" in res.output

    def test_on_off_clear(self) -> None:
        ex, _, _ = _repl()
        assert "enabled" in ex.execute("midi on").output
        assert "disabled" in ex.execute("midi off").output
        ex.execute("midi on")
        assert "cleared" in ex.execute("midi clear").output

    def test_bad_number(self) -> None:
        ex, _, _ = _repl()
        res = ex.execute("midi xyz")
        assert res.code == 1
        assert "not a number" in res.output

    def test_dropped_event_visible_in_repl(self) -> None:
        ex, app, _ = _repl()
        ex.execute("midi on")
        app._transport._queue.put_nowait(  # type: ignore[union-attr]
            TransportEvent.note_on("missing", 0, 60, 100)
        )
        app._transport.process_events(0.0)  # type: ignore[union-attr]
        res = ex.execute("midi")
        assert "ОТБРОШЕНО" in res.output
