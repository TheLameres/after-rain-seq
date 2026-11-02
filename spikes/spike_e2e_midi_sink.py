#!/usr/bin/env python3
"""
Spike: E2E — MIDI-сигнал доходит до dummy-приёмника (критерий приёмки C6).

Сценарий в одном процессе:
1. Открыть виртуальный MIDI-вход «ARS Sink» (mido/rtmidi).
2. Поднять App (simulate=True) с конфигом, где output «main» → match «ARS Sink».
3. Через AppEngineControl: создать pad-дорожку, замаршрутировать на «main»,
   запустить транспорт (internal clock, 120 bpm).
4. Принимать сообщения ~5 секунд, остановить, сверить: note_on/note_off
   пришли однократно и в такт.

Запуск:
    .venv/bin/python spikes/spike_e2e_midi_sink.py
"""

import tempfile
import threading
import time
from pathlib import Path

import mido

SINK_NAME = "ARS Sink"
MAIN_LABEL = "main"
COLLECT_SECONDS = 5.0

CONFIG_TEMPLATE = """\
logging:
  level:
    root: INFO

sync:
  enabled: true
  clock_source: "internal"
  midi_clock_device: null
  bpm: 120.0
  swing_amount: 0.0

ports:
  outputs:
    - label: "main"
      match: "ARS Sink"
      role: melodic
      serial: null
      no_automation: false
  inputs: []

cc_map:
  default:
    filter: 74
    resonance: 71
  ports: {}

mutation:
  enabled: true
  mutate_min_seconds: 8.0
  mutate_max_seconds: 16.0
  default_mutate: 0.5
  drift_step_gate: 0.05
  drift_step_density: 0.1
  drift_step_register: 1.0

devices:
  push2:
    enabled: false
    brightness: 100
    use_user_midi_port: false
    simulate: false
    display_enabled: false
    display_fps: 15
    encoder_banks: []
    global_encoders:
      tempo: null
      swing: null
      master: null
  lcxl3:
    enabled: false
    midi_in_port_name: "LCXL3 1 DAW Out"
    midi_out_port_name: "LCXL3 1 DAW In"
    encoder_banks: []
    faders: []
"""


def main() -> int:
    print(f"[e2e] открываю виртуальный порт-приёмник {SINK_NAME!r}…")
    sink = mido.open_input(SINK_NAME, virtual=True)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", prefix="ars_e2e_", delete=False
    ) as tmp:
        tmp.write(CONFIG_TEMPLATE)
    config_path = Path(tmp.name)
    print(f"[e2e] временный конфиг: {config_path}")

    from src.app.application import App
    from src.app.engine_control import AppEngineControl

    app = App(config_path=str(config_path), simulate=True)
    control = AppEngineControl(app)

    run_thread = threading.Thread(target=app.run, kwargs={"repl": None}, daemon=True)
    run_thread.start()

    received: list[tuple[float, object]] = []
    stop_collect = threading.Event()

    def collect() -> None:
        start = time.monotonic()
        while not stop_collect.is_set():
            for msg in sink.iter_pending():
                received.append((time.monotonic() - start, msg))
            time.sleep(0.002)

    collector = threading.Thread(target=collect, daemon=True)
    collector.start()

    try:
        # Ждём, пока PortManager обнаружит порт (poll ~2 c) и поднимет registry.
        time.sleep(3.0)
        print(f"[e2e] ports: {control.get_status().ports}")
        print(f"[e2e] create_track: {control.create_track('pad')}")
        print(f"[e2e] create_track: {control.create_track('bass')}")
        print(f"[e2e] route_track: {control.route_track('Pad 1', MAIN_LABEL)}")
        print(f"[e2e] route_track: {control.route_track('Bass 1', MAIN_LABEL)}")
        print(f"[e2e] start: {control.start_transport()}")

        time.sleep(COLLECT_SECONDS)

        # Отладка: состояние движка изнутри
        now_beat = app._tick_proxy._timeline.current_time
        for eng in app._melodic_engines:
            print(f"[e2e] engine track={eng.track.name!r} port={eng.port_label!r}")
        print(f"[e2e] event_queue size: {app._event_queue.qsize()}")
        print(f"[e2e] timeline beat: {now_beat}")

        # Проверка пути порта: registry-адаптер → sink напрямую.
        adapter = (
            app._port_registry.get_output(MAIN_LABEL)
            if app._port_registry
            else None
        )
        print(f"[e2e] adapter for {MAIN_LABEL!r}: {adapter!r}")
        if adapter is not None and adapter.is_open:
            adapter.note_on(channel=0, note=60, velocity=100)
            time.sleep(0.3)
            manual = [m for _t, m in received if m.type == "note_on"]
            print(f"[e2e] ручная нота дошла до sink: {len(manual) > 0}")

        notes_on = [m for _t, m in received if m.type == "note_on" and m.velocity > 0]
        notes_off = [m for _t, m in received if m.type == "note_off"]
        zero_vel = [m for _t, m in received if m.type == "note_on" and m.velocity == 0]

        print("\n[e2e] === сводка ===")
        print(f"[e2e] всего сообщений: {len(received)}")
        print(f"[e2e] note_on (vel>0): {len(notes_on)}")
        print(f"[e2e] note_off: {len(notes_off)}")
        print(f"[e2e] note_on vel=0: {len(zero_vel)}")
        chans = {m.channel for m in notes_on}
        print(f"[e2e] каналы среди note_on: {sorted(chans)}")
        for t, msg in received[:12]:
            print(f"[e2e] {t:7.3f}s  {msg}")

        # Критерий приёмки R5: сигнал доходит; фикс слипания: две дорожки
        # на одном порту звучат на РАЗНЫХ каналах. Ручная проверочная нота
        # (60/ch0) исключается из подсчёта.
        engine_notes = [m for m in notes_on if m.note != 60]
        distinct_engine_chans = {m.channel for m in engine_notes}
        ok = len(engine_notes) > 0 and len(distinct_engine_chans) >= 2
        if ok:
            print(
                f"\n[e2e] PASS: MIDI дошёл; дорожки на разных каналах "
                f"{sorted(distinct_engine_chans)}"
            )
        else:
            print("\n[e2e] FAIL: сигнала нет или дорожки слиплись в один канал")
            print("[e2e] последние логи движка:")
            for line in control.get_logs(30):
                print(f"    {line}")
        return 0 if ok else 1
    finally:
        stop_collect.set()
        control.stop_transport()
        app.stop()
        run_thread.join(timeout=5)
        sink.close()
        config_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
