#!/usr/bin/env python3
"""
Spike: MIDI Sink — dummy-приёмник для E2E-проверки (критерий приёмки C6).

Создаёт виртуальный MIDI-входной порт и печатает все входящие сообщения
с монотонным таймстампом. Позволяет убедиться, что движок реально шлёт
note_on/note_off/CC наружу, а не только внутрь своих очередей.

Запуск:
    .venv/bin/python spikes/spike_midi_sink.py [--port SINK]

Другой терминал (движок):
    # config.yaml: ports.outputs с match на имя порта, затем
    .venv/bin/python -m src.main --repl --simulate

Остановка: Ctrl+C.
"""

import argparse
import time

import mido


def main() -> None:
    parser = argparse.ArgumentParser(description="Dummy MIDI-приёмник (mido)")
    parser.add_argument(
        "--port",
        default="ARS Sink",
        help="Имя виртуального входного порта (default: %(default)s)",
    )
    args = parser.parse_args()

    with mido.open_input(args.port, virtual=True) as port:
        print(f"[sink] виртуальный порт открыт: {port.name!r}")
        print("[sink] жду сообщений… (Ctrl+C для выхода)")
        start = time.monotonic()
        try:
            while True:
                for msg in port.iter_pending():
                    t = time.monotonic() - start
                    print(f"[sink] {t:9.3f}s  {msg}")
                time.sleep(0.002)
        except KeyboardInterrupt:
            print("\n[sink] остановлен")


if __name__ == "__main__":
    main()
