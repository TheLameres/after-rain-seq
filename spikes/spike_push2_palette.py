#!/usr/bin/env python3
"""Spike: снять палитру LED Push 2 по sysex 0x04 (план §3.2б, шаг A0).

Зачем: пэды Push 2 адресуются индексом палитры 0..127, а не RGB. Без
таблицы «индекс → RGB» нельзя ни выбрать цвета дорожек, ни проверить, что
выбранный индекс не серый. Спека Ableton документирует команду чтения, но
не публикует полный набор значений — его надо снять с устройства.

Что делает:
    Для каждого индекса 0..127 шлёт sysex «Get LED Color Palette Entry»
    (ID 0x04), собирает ответ и печатает таблицу. Результат можно сверять
    с ``src/devices/push2/palette.py``.

Формат (спека Ableton Push 2 MIDI & Display Interface):

    запрос:  F0 00 21 1D 01 01 04 <index> F7
    ответ:   F0 00 21 1D 01 01 04 <index>
             <r_lsb> <r_msb> <g_lsb> <g_msb> <b_lsb> <b_msb> <w_lsb> <w_msb>
             F7

    Каждый компонент — 8 бит в двух байтах: младшие 7 бит + старший бит.

Запуск:
    # без железа — печатает таблицу из palette.py и сверяет якоря спеки
    python spikes/spike_push2_palette.py --dry-run

    # на устройстве
    python spikes/spike_push2_palette.py --port "Ableton Push 2"

Остановка: Ctrl+C (в режиме устройства; по таймауту всё равно завершится).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.devices.push2.palette import PALETTE, TRACK_PAD_INDICES

#: SysEx-префикс Ableton: производитель 00 21 1D, семейство 01, модель 01.
SYSEX_PREFIX = (0x00, 0x21, 0x1D, 0x01, 0x01)

#: ID команды «Get LED Color Palette Entry».
SYSEX_GET_PALETTE_ENTRY = 0x04

#: Якоря из официальной спеки — по ним проверяем, что сняли то самое.
SPEC_ANCHORS = {
    0: (0, 0, 0),
    117: (0, 0, 0),
    118: (89, 89, 89),
    121: (89, 89, 89),
    125: (0, 0, 255),
    126: (0, 255, 0),
    127: (255, 0, 0),
}


def request_entry(index: int) -> tuple[int, ...]:
    """Данные sysex (без F0/F7) для запроса записи палитры."""
    if not 0 <= index <= 127:
        raise ValueError(f"Индекс палитры {index} вне 0..127")
    return (*SYSEX_PREFIX, SYSEX_GET_PALETTE_ENTRY, index)


def decode_reply(data: tuple[int, ...]) -> tuple[int, tuple[int, int, int], int]:
    """Разобрать ответ на запрос записи палитры.

    Аргументы:
        data: Байты sysex без F0/F7.

    Returns:
        Кортеж ``(index, (r, g, b), white)``.

    Raises:
        ValueError: Если длина или префикс не те, то есть пришёл не тот ответ.
    """
    expected = len(SYSEX_PREFIX) + 1 + 1 + 8
    if len(data) < expected:
        raise ValueError(f"Короткий ответ: {len(data)} байт, ожидалось {expected}")
    if tuple(data[: len(SYSEX_PREFIX)]) != SYSEX_PREFIX:
        raise ValueError("Чужой sysex-префикс")
    if data[len(SYSEX_PREFIX)] != SYSEX_GET_PALETTE_ENTRY:
        raise ValueError("Ответ не на Get LED Color Palette Entry")

    index = data[len(SYSEX_PREFIX) + 1]
    payload = data[len(SYSEX_PREFIX) + 2 :]

    def component(lsb: int, msb: int) -> int:
        return (lsb & 0x7F) | ((msb & 0x01) << 7)

    r = component(payload[0], payload[1])
    g = component(payload[2], payload[3])
    b = component(payload[4], payload[5])
    w = component(payload[6], payload[7])
    return index, (r, g, b), w


def dump_static_palette() -> list[tuple[int, tuple[int, int, int]]]:
    """Таблица из модуля, без обращения к устройству."""
    return list(enumerate(PALETTE))


def check_anchors(table: dict[int, tuple[int, int, int]]) -> list[str]:
    """Сверить таблицу с якорями спеки. Возвращает список расхождений."""
    problems: list[str] = []
    for index, expected in sorted(SPEC_ANCHORS.items()):
        actual = table.get(index)
        if actual != expected:
            problems.append(f"  индекс {index:3d}: получено {actual}, спека {expected}")
    return problems


def read_from_device(port_name: str, timeout: float = 2.0) -> dict[int, tuple[int, int, int]]:
    """Снять все 128 записей с живого устройства.

    Каждый индекс запрашивается отдельно с таймаутом: гнать все 128 сразу,
    как делают некоторые реализации, ненадёжно — ответы теряются, и потом
    неясно, какой именно индекс не пришёл.
    """
    import mido

    table: dict[int, tuple[int, int, int]] = {}
    with mido.open_ioport(port_name) as port:
        for index in range(128):
            port.send(mido.Message("sysex", data=list(request_entry(index))))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                for msg in port.iter_pending():
                    if msg.type != "sysex":
                        continue
                    try:
                        got_index, rgb, _white = decode_reply(tuple(msg.data))
                    except ValueError:
                        continue
                    if got_index == index:
                        table[index] = rgb
                        break
                if index in table:
                    break
            else:
                print(f"[palette] индекс {index}: ответа нет", file=sys.stderr)
    return table


def main() -> int:
    parser = argparse.ArgumentParser(description="Снять палитру LED Push 2 по sysex 0x04")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="не трогать железо: напечатать таблицу из palette.py и сверить якоря",
    )
    parser.add_argument("--port", default="Ableton Push 2", help="имя MIDI-порта устройства")
    parser.add_argument("--timeout", type=float, default=2.0, help="таймаут на один индекс, с")
    args = parser.parse_args()

    if args.dry_run:
        entries = dump_static_palette()
        table = dict(entries)
        source = "src/devices/push2/palette.py"
    else:
        table = read_from_device(args.port, timeout=args.timeout)
        entries = sorted(table.items())
        source = f"устройство {args.port!r}"

    print(f"[palette] источник: {source}, записей: {len(entries)}")
    for index, (r, g, b) in entries:
        marker = " *" if index in TRACK_PAD_INDICES else ""
        print(f"{index:3d}  {r:3d} {g:3d} {b:3d}  #{r:02x}{g:02x}{b:02x}{marker}")

    problems = check_anchors(table)
    if len(table) != 128:
        problems.insert(0, f"  записей {len(table)}, ожидалось 128")
    if problems:
        print("[palette] РАСХОЖДЕНИЯ:", file=sys.stderr)
        for line in problems:
            print(line, file=sys.stderr)
        return 1

    print("[palette] все якоря спеки совпали")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
