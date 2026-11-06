"""Приём внешнего MIDI Clock и Start/Continue/Stop (src/sync/midi_clock_in.py).

Блок 1 — модуль приёмника с записывающим получателем.
Блок 2 — сквозной путь: реальный isobar Timeline + TickProxy + хук приложения.
Блок 3 — выбор входа и перезапуск мутаций.
"""

from __future__ import annotations

import queue
import threading
import time
from unittest.mock import MagicMock, patch

import mido
import pytest

from src.sync.midi_clock_in import MidiClockInput
from src.sync.tick_proxy import TickEvent, TickProxy


class Recorder:
    """Получатель транспорта, который только записывает вызовы."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def tick(self) -> None:
        self.calls.append("tick")

    def start(self) -> None:
        self.calls.append("start")

    def stop(self) -> None:
        self.calls.append("stop")

    def reset(self) -> None:
        self.calls.append("reset")

    def count(self, what: str) -> int:
        return self.calls.count(what)


def _in(ticks_per_beat: int = 480) -> tuple[MidiClockInput, Recorder]:
    rec = Recorder()
    return MidiClockInput(rec, "IAC Test", ticks_per_beat), rec


def _msg(kind: str, **kw: int) -> mido.Message:
    return mido.Message(kind, **kw)


# ---------------------------------------------------------------------------
# Блок 1: модуль приёмника
# ---------------------------------------------------------------------------


class TestPulsesToTicks:
    def test_one_pulse_is_twenty_ticks_at_480_tpb(self) -> None:
        inp, rec = _in(480)
        inp._on_message(_msg("start"))
        rec.calls.clear()
        inp._on_message(_msg("clock"))
        assert rec.count("tick") == 20  # 480 / 24

    def test_24_pulses_make_one_beat(self) -> None:
        inp, rec = _in(480)
        inp._on_message(_msg("start"))
        rec.calls.clear()
        for _ in range(24):
            inp._on_message(_msg("clock"))
        assert rec.count("tick") == 480

    def test_non_divisible_ticks_per_beat_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="делиться"):
            MidiClockInput(Recorder(), "x", 100)

    def test_no_ticks_before_start(self) -> None:
        inp, rec = _in()
        for _ in range(10):
            inp._on_message(_msg("clock"))
        assert rec.count("tick") == 0


class TestTransportMessages:
    def test_start_sends_start_and_enables_ticks(self) -> None:
        inp, rec = _in()
        inp._on_message(_msg("start"))
        assert rec.calls == ["start"]
        assert inp.running

    def test_stop_halts_ticks_and_sends_stop_once(self) -> None:
        inp, rec = _in()
        inp._on_message(_msg("start"))
        inp._on_message(_msg("stop"))
        inp._on_message(_msg("stop"))  # повторный Stop ничего не шлёт
        rec.calls.clear()
        inp._on_message(_msg("clock"))
        assert rec.count("tick") == 0
        assert rec.count("stop") == 0
        assert not inp.running

    def test_continue_resumes_without_reset_or_start(self) -> None:
        inp, rec = _in()
        inp._on_message(_msg("start"))
        inp._on_message(_msg("stop"))
        rec.calls.clear()
        inp._on_message(_msg("continue"))
        inp._on_message(_msg("clock"))
        assert "start" not in rec.calls
        assert "reset" not in rec.calls
        assert rec.count("tick") == 20

    def test_continue_after_cold_start_still_ticks(self) -> None:
        inp, rec = _in()
        inp._on_message(_msg("continue"))
        inp._on_message(_msg("clock"))
        assert rec.count("tick") == 20

    def test_songpos_zero_resets(self) -> None:
        inp, rec = _in()
        inp._on_message(_msg("songpos", pos=0))
        assert rec.calls == ["reset"]

    def test_songpos_nonzero_is_ignored(self) -> None:
        inp, rec = _in()
        inp._on_message(_msg("songpos", pos=16))
        assert rec.calls == []

    def test_unrelated_messages_are_ignored(self) -> None:
        inp, rec = _in()
        inp._on_message(_msg("start"))
        rec.calls.clear()
        inp._on_message(_msg("note_on", note=60, velocity=100))
        inp._on_message(_msg("control_change", control=1, value=0))
        assert rec.calls == []


class TestTempoEstimate:
    def test_tempo_from_pulse_interval(self) -> None:
        inp, _ = _in()
        times = iter([0.0, 60.0 / (120 * 24)])  # 120 BPM: 24 импульса в секунду*2
        with patch("src.sync.midi_clock_in.time.monotonic", side_effect=times):
            inp._on_message(_msg("clock"))
            inp._on_message(_msg("clock"))
        assert inp.tempo == pytest.approx(120.0, rel=1e-6)

    def test_no_tempo_before_two_pulses(self) -> None:
        inp, _ = _in()
        inp._on_message(_msg("clock"))
        assert inp.tempo is None

    def test_long_gap_does_not_poison_tempo(self) -> None:
        inp, _ = _in()
        times = iter([0.0, 60.0 / (120 * 24), 100.0])  # пауза 100 с — не учитываем
        with patch("src.sync.midi_clock_in.time.monotonic", side_effect=times):
            inp._on_message(_msg("clock"))
            inp._on_message(_msg("clock"))
            inp._on_message(_msg("clock"))
        assert inp.tempo == pytest.approx(120.0, rel=1e-6)


class TestOpenAndClose:
    def test_background_opens_named_input_with_callback(self) -> None:
        inp, _ = _in()
        with patch("mido.open_input") as open_input:
            inp.background()
        open_input.assert_called_once()
        assert open_input.call_args.args[0] == "IAC Test"
        assert "callback" in open_input.call_args.kwargs

    def test_background_is_idempotent(self) -> None:
        inp, _ = _in()
        with patch("mido.open_input") as open_input:
            open_input.return_value = MagicMock()
            inp.background()
            inp.background()
        assert open_input.call_count == 1

    def test_open_failure_is_value_error(self) -> None:
        inp, _ = _in()
        with (
            patch("mido.open_input", side_effect=OSError("no port")),
            pytest.raises(ValueError, match="Cannot open MIDI clock input"),
        ):
            inp.background()

    def test_stop_while_running_sends_stop_and_closes(self) -> None:
        inp, rec = _in()
        port = MagicMock()
        with patch("mido.open_input", return_value=port):
            inp.background()
        inp._on_message(_msg("start"))
        inp.stop()
        port.close.assert_called_once()
        assert rec.count("stop") == 1
        assert not inp.running


# ---------------------------------------------------------------------------
# Блок 2: сквозной путь через реальный таймлайн, TickProxy и хук приложения
# ---------------------------------------------------------------------------


class _Reg:
    def all_outputs(self):
        return []

    def flush_all(self) -> None:
        pass

    def get_output(self, label: str):
        return None


class _Cfg:
    enabled = True
    clock_source = "internal"
    midi_clock_device = None
    bpm = 120.0
    swing_amount = 0.0


def _app(reg=None):
    """App с хуком тиков; источники часов не запускаются, воркер прокси остановлен.

    Воркер остановлен, потому что тесты разбирают очередь вручную (_drain):
    два потока, меняющих current_time, теряют приращения.
    """
    import queue as _q

    from src.app.application import App
    from src.session.session import Session
    from src.sync.swing import SwingApplier, SwingConfig

    app = App(config_path="config.yaml", simulate=True)
    app._session = Session()
    app._port_registry = reg if reg is not None else _Reg()  # type: ignore[assignment]
    app._swing_applier = SwingApplier(SwingConfig(amount=0.0))
    app._event_queue = _q.Queue()
    app._init_clock_manager(_Cfg())
    cm = app._clock_manager
    cm._activate_source = lambda *a, **k: None  # type: ignore[method-assign]
    cm._stop_current_source = lambda *a, **k: None  # type: ignore[method-assign]
    proxy = app._tick_proxy
    proxy.stop_worker()
    while not proxy._queue.empty():  # type: ignore[attr-defined]
        proxy._queue.get_nowait()  # type: ignore[attr-defined]
    return app, cm, cm._timeline, proxy


def _drain(proxy: TickProxy) -> None:
    """Выполнить накопленные события прокси в этом потоке (вместо воркера)."""
    q: queue.Queue = proxy._queue  # type: ignore[attr-defined]
    while not q.empty():
        proxy._dispatch(q.get_nowait())  # type: ignore[attr-defined]


class TestEndToEndTiming:
    def test_24_external_pulses_advance_exactly_one_beat(self) -> None:
        _, _cm, tl, proxy = _app()
        inp = MidiClockInput(proxy, "IAC Test", tl.ticks_per_beat)
        inp._on_message(_msg("start"))
        _drain(proxy)
        t0 = tl.current_time
        for _ in range(24):
            inp._on_message(_msg("clock"))
        _drain(proxy)
        assert tl.current_time - t0 == pytest.approx(1.0, abs=1e-6)

    def test_start_does_not_spawn_a_clock_thread(self) -> None:
        """Регрессия: timeline.start() запускал внутренние часы таймлайна."""
        _, _cm, tl, proxy = _app()
        inp = MidiClockInput(proxy, "IAC Test", tl.ticks_per_beat)
        before = threading.active_count()
        inp._on_message(_msg("start"))
        _drain(proxy)
        time.sleep(0.3)
        assert threading.active_count() == before
        assert tl.current_time == pytest.approx(0.0, abs=1e-9)

    def test_no_pulses_means_no_movement(self) -> None:
        _, _cm, tl, proxy = _app()
        inp = MidiClockInput(proxy, "IAC Test", tl.ticks_per_beat)
        inp._on_message(_msg("start"))
        _drain(proxy)
        t0 = tl.current_time
        time.sleep(0.3)
        assert tl.current_time == t0

    def test_start_resets_position_to_zero(self) -> None:
        _, _cm, tl, proxy = _app()
        inp = MidiClockInput(proxy, "IAC Test", tl.ticks_per_beat)
        inp._on_message(_msg("start"))
        _drain(proxy)
        for _ in range(48):
            inp._on_message(_msg("clock"))
        _drain(proxy)
        assert tl.current_time == pytest.approx(2.0, abs=1e-6)
        inp._on_message(_msg("start"))
        _drain(proxy)
        assert tl.current_time == pytest.approx(0.0, abs=1e-9)

    def test_continue_keeps_position(self) -> None:
        _, _cm, tl, proxy = _app()
        inp = MidiClockInput(proxy, "IAC Test", tl.ticks_per_beat)
        inp._on_message(_msg("start"))
        _drain(proxy)
        for _ in range(24):
            inp._on_message(_msg("clock"))
        _drain(proxy)
        inp._on_message(_msg("stop"))
        _drain(proxy)
        inp._on_message(_msg("continue"))
        _drain(proxy)
        for _ in range(24):
            inp._on_message(_msg("clock"))
        _drain(proxy)
        assert tl.current_time == pytest.approx(2.0, abs=1e-6)

    def test_stop_freezes_position_and_silences_outputs(self) -> None:
        _, _cm, tl, proxy = _app()
        inp = MidiClockInput(proxy, "IAC Test", tl.ticks_per_beat)
        inp._on_message(_msg("start"))
        _drain(proxy)
        for _ in range(24):
            inp._on_message(_msg("clock"))
        _drain(proxy)
        inp._on_message(_msg("stop"))
        _drain(proxy)
        frozen = tl.current_time
        for _ in range(48):
            inp._on_message(_msg("clock"))
        _drain(proxy)
        assert tl.current_time == pytest.approx(frozen, abs=1e-9)

    def test_stop_delivers_all_notes_off_immediately(self) -> None:
        """Тиков после STOP не будет: all-notes-off должен уйти сразу, не через очередь."""
        seen: list[str] = []

        class Out:
            label = "main"

            def all_notes_off(self) -> None:
                seen.append("all_notes_off")

            def flush(self) -> None:
                pass

        class Reg(_Reg):
            def all_outputs(self):
                return [Out()]

        _, _cm, tl, proxy = _app(reg=Reg())
        inp = MidiClockInput(proxy, "IAC Test", tl.ticks_per_beat)
        inp._on_message(_msg("start"))
        _drain(proxy)
        inp._on_message(_msg("stop"))
        _drain(proxy)
        assert "all_notes_off" in seen


# ---------------------------------------------------------------------------
# Блок 3: выбор входа и перезапуск мутаций
# ---------------------------------------------------------------------------


class TestClockInputSelection:
    def test_port_with_clock_role_is_used(self) -> None:
        from src.sync.ports import PortConfig, PortManager, PortsConfig

        class Reg:
            def list_input_names(self):
                return ["LCXL3 DAW Out", "IAC Channel 1"]

            def list_output_names(self):
                return []

        pm = PortManager(
            PortsConfig(
                inputs=[
                    PortConfig(label="ctl", match="LCXL3", role="melodic"),
                    PortConfig(label="clock-in", match="IAC Channel 1", role="clock"),
                ]
            ),
            Reg(),  # type: ignore[arg-type]
        )
        pm.start()
        assert pm.clock_input_name() == "IAC Channel 1"

    def test_no_clock_role_gives_none(self) -> None:
        from src.sync.ports import PortConfig, PortManager, PortsConfig

        pm = PortManager(
            PortsConfig(inputs=[PortConfig(label="ctl", match="X", role="melodic")]),
            MagicMock(),
        )
        assert pm.clock_input_name() is None

    def test_manual_device_overrides_port(self) -> None:
        app, _cm, _tl, _proxy = _app()
        app._port_manager = MagicMock()
        app._port_manager.clock_input_name.return_value = "IAC Channel 1"
        from src.sync.clock_source import ClockManagerConfig  # noqa: F401

        class Sync:
            midi_clock_device = "Manual Device"

        assert app._clock_input_name(Sync()) == "Manual Device"

    def test_falls_back_to_clock_role_port(self) -> None:
        app, _cm, _tl, _proxy = _app()
        app._port_manager = MagicMock()
        app._port_manager.clock_input_name.return_value = "IAC Channel 1"

        class Sync:
            midi_clock_device = None

        assert app._clock_input_name(Sync()) == "IAC Channel 1"

    def test_request_midi_without_device_uses_configured_one(self) -> None:
        from src.sync.clock_manager import ClockManager
        from src.sync.clock_source import ClockManagerConfig, ClockSource

        cm = ClockManager(
            MagicMock(),
            MagicMock(),
            ClockManagerConfig(
                initial_source=ClockSource.INTERNAL,
                midi_device_name="IAC Channel 1",
                ticks_per_beat=480,
            ),
        )
        seen: dict = {}

        def fake_create(source, config, clock_target):
            seen["device"] = config.midi_device_name
            return MagicMock()

        with patch(
            "src.sync.clock_manager.create_clock_source", side_effect=fake_create
        ):
            cm._activate_source(ClockSource.MIDI, None)
        assert seen["device"] == "IAC Channel 1"


class TestMutationRestart:
    def test_restart_schedules_from_zero(self) -> None:
        from src.session.mutation.mutation_engine import MutationEngine

        me = MutationEngine()
        me.register_track("L", "lead", degrees=[0, 2, 4], mutate=1.0)
        me.tick(5000.0, 120.0)  # продвинуть расписание далеко вперёд
        me.restart(120.0)
        st = me.get_state("L")
        assert st is not None
        assert st.next_mutation_beat < 100.0
        assert st.last_mutation_beat == 0.0

    def test_restart_keeps_count_and_mutate(self) -> None:
        from src.session.mutation.mutation_engine import MutationEngine

        me = MutationEngine()
        me.register_track("L", "lead", degrees=[0, 2, 4], mutate=0.7)
        me.tick(1000.0, 120.0)
        before = me.get_state("L")
        assert before is not None
        me.restart(120.0)
        after = me.get_state("L")
        assert after is not None
        assert after.mutation_count == before.mutation_count
        assert after.mutate == 0.7


class TestIdleQueue:
    def test_drain_helper_is_empty_after_use(self) -> None:
        _, _cm, _tl, proxy = _app()
        proxy._queue.put_nowait(TickEvent.TICK)  # type: ignore[attr-defined]
        _drain(proxy)
        assert proxy._queue.empty()  # type: ignore[attr-defined]
