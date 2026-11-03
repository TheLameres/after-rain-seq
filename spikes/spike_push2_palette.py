#!/usr/bin/env python3
"""Spike: вытащить палитру LED из Push 2 через sysex 0x04.

Вопрос, на который отвечает спайк
----------------------------------
Спека Ableton гарантирует только 7 индексов RGB-палитры (0, 122..127).
У нас MAX_TRACKS = 16. Хватает ли в реальной палитре устройства
16 различимых цветов, и какие именно индексы брать?

Как работает
------------
Спека, §"Get LED Color Palette Entry":

    Запрос:  F0 00 21 1D 01 01 04 <idx> F7
    Ответ:   F0 00 21 1D 01 01 04 <idx>
             <rLSB> <rMSB> <gLSB> <gMSB> <bLSB> <bMSB> <wLSB> <wMSB> F7

    Каждый компонент — 8 бит, разложенные на два 7-битных байта:
        value = LSB | (MSB << 7)

    Пример из спеки, индекс 125 (синий, white=126):
        запрос   [F0 00 21 1D 01 01 04 7D F7]
        ответ    [F0 00 21 1D 01 01 04 7D 00 00 00 00 7F 01 7E 00 F7]
        b = 0x7F | (0x01 << 7) = 255   ✓
        w = 0x7E | (0x00 << 7) = 126   ✓

Что выдаёт
----------
1. Полную таблицу 128 записей → `spikes/out/push2_palette.json`
2. Готовый Python-модуль → `spikes/out/push2_palette.py` (для копирования
   в `src/devices/push2/palette.py` после ревью)
3. Отчёт: сколько РАЗЛИЧИМЫХ цветов, какие 16 брать под дорожки,
   где палитра расходится с гарантированными 7 индексами

Запуск
------
    python spikes/spike_push2_palette.py --list        # какие порты есть
    python spikes/spike_push2_palette.py               # запросить все 128
    python spikes/spike_push2_palette.py --dry-run     # без железа: проверить парсер

Зависимости: mido + python-rtmidi (уже в pyproject).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import mido
except ImportError:  # pragma: no cover
    sys.exit("нужен mido: pip install mido python-rtmidi")

# ── sysex protocol ────────────────────────────────────────────────────────
# Префикс Ableton: 00 21 1D (вендор) 01 01 (product/device)
SYSEX_PREFIX = (0x00, 0x21, 0x1D, 0x01, 0x01)
CMD_GET_PALETTE_ENTRY = 0x04

# Ответ целиком (без F0/F7): prefix(5) + cmd(1) + idx(1) + 4 компонента × 2 байта
REPLY_LEN = 15

# Гарантированные спекой индексы — по ним валидируем парсер на железе.
GUARANTEED: dict[int, tuple[int, int, int]] = {
    0: (0, 0, 0),
    122: (204, 204, 204),
    123: (64, 64, 64),
    124: (20, 20, 20),
    125: (0, 0, 255),
    126: (0, 255, 0),
    127: (255, 0, 0),
}

PALETTE_SIZE = 128


# ── data ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PaletteEntry:
    """Одна запись палитры: индекс → RGB + white."""

    index: int
    r: int
    g: int
    b: int
    w: int

    @property
    def rgb(self) -> tuple[int, int, int]:
        return (self.r, self.g, self.b)

    def to_dict(self) -> dict[str, int]:
        return {"index": self.index, "r": self.r, "g": self.g, "b": self.b, "w": self.w}


# ── codec ─────────────────────────────────────────────────────────────────


def build_request(index: int) -> tuple[int, ...]:
    """Полный sysex-запрос с F0/F7 (mido ждёт data без обрамления)."""
    if not 0 <= index < PALETTE_SIZE:
        raise ValueError(f"индекс вне 0..127: {index}")
    return (*SYSEX_PREFIX, CMD_GET_PALETTE_ENTRY, index)


def parse_reply(data: tuple[int, ...] | list[int]) -> PaletteEntry | None:
    """Разобрать ответ на Get LED Color Palette Entry.

    Принимает data без F0/F7 (как отдаёт mido). Возвращает None, если это
    не наш ответ — на порт прилетают и другие сообщения.
    """
    d = tuple(data)
    if len(d) != REPLY_LEN:
        return None
    if d[:5] != SYSEX_PREFIX or d[5] != CMD_GET_PALETTE_ENTRY:
        return None

    idx = d[6]
    r = d[7] | (d[8] << 7)
    g = d[9] | (d[10] << 7)
    b = d[11] | (d[12] << 7)
    w = d[13] | (d[14] << 7)

    if not all(0 <= c <= 255 for c in (r, g, b, w)):
        return None
    return PaletteEntry(index=idx, r=r, g=g, b=b, w=w)


# ── colour science (для отчёта о различимости) ────────────────────────────


def _srgb_to_linear(c: int) -> float:
    s = c / 255.0
    return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4


def rgb_to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """sRGB → CIE L*a*b* (D65). Нужно для честной перцептивной дистанции."""
    r, g, b = (_srgb_to_linear(c) for c in rgb)
    # sRGB → XYZ (D65)
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    # нормализация на белый D65
    x /= 0.95047
    z /= 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t) + (16 / 116)

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    """CIE76 — просто и достаточно для «различимы ли два цвета на LED»."""
    a, b = rgb_to_lab(c1), rgb_to_lab(c2)
    return sum((p - q) ** 2 for p, q in zip(a, b)) ** 0.5


def pick_distinct(
    entries: list[PaletteEntry], count: int, min_delta_e: float = 25.0
) -> list[PaletteEntry]:
    """Greedy farthest-point: выбрать `count` максимально различимых цветов.

    Стартуем с самого насыщенного, каждый следующий — самый далёкий от уже
    выбранных. Возвращает меньше `count`, если палитра не даёт различимых.
    """
    # Отбрасываем почти-чёрные и почти-белые: на дорожку они не годятся
    # (чёрный = выключено, белый = текст).
    candidates = [
        e
        for e in entries
        if max(e.rgb) > 40 and min(e.rgb) < 235 and (sum(e.rgb) / 3) > 25
    ]
    if not candidates:
        return []

    # Первый — с максимальной насыщенностью (max-min каналов)
    candidates.sort(key=lambda e: (max(e.rgb) - min(e.rgb)), reverse=True)
    chosen = [candidates.pop(0)]

    while len(chosen) < count and candidates:
        best = max(
            candidates,
            key=lambda e: min(delta_e(e.rgb, c.rgb) for c in chosen),
        )
        d = min(delta_e(best.rgb, c.rgb) for c in chosen)
        if d < min_delta_e:
            break
        candidates.remove(best)
        chosen.append(best)

    return chosen


# ── hardware I/O ──────────────────────────────────────────────────────────


def _midi_names(kind: str) -> list[str]:
    """Имена портов; понятная ошибка вместо трейсбека, если бэкенда нет."""
    try:
        getter = mido.get_input_names if kind == "in" else mido.get_output_names
        return list(getter())
    except (ImportError, ModuleNotFoundError, OSError) as exc:
        print(
            f"MIDI-бэкенд недоступен ({exc}).\n"
            "Установите: pip install python-rtmidi\n"
            "На Linux дополнительно: apt install libasound2-dev",
            file=sys.stderr,
        )
        return []


def find_push2_ports() -> tuple[str | None, str | None]:
    """Найти вход и выход Push 2 по имени порта."""
    ins = [n for n in _midi_names("in") if "push" in n.lower()]
    outs = [n for n in _midi_names("out") if "push" in n.lower()]
    return (ins[0] if ins else None, outs[0] if outs else None)


def query_palette(in_name: str, out_name: str, timeout: float = 0.3) -> dict[int, PaletteEntry]:
    """Запросить все 128 записей. Возвращает то, что ответило устройство."""
    found: dict[int, PaletteEntry] = {}

    with mido.open_output(out_name) as out, mido.open_input(in_name) as inp:
        for index in range(PALETTE_SIZE):
            req = build_request(index)
            out.send(mido.Message("sysex", data=req))

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                for msg in inp.iter_pending():
                    if msg.type != "sysex":
                        continue
                    entry = parse_reply(msg.data)
                    if entry is not None and entry.index == index:
                        found[index] = entry
                        break
                if index in found:
                    break
                time.sleep(0.002)

            if index % 16 == 15:
                print(f"  … {index + 1}/{PALETTE_SIZE}", file=sys.stderr)

    return found


# ── reporting ─────────────────────────────────────────────────────────────


def report(entries: dict[int, PaletteEntry], picked: list[PaletteEntry]) -> None:
    print()
    print("=" * 74)
    print(f"Получено записей: {len(entries)} / {PALETTE_SIZE}")
    print("=" * 74)

    # 1. Сверка с гарантированными индексами
    print("\nГарантированные спекой индексы:")
    ok = True
    for idx, expected in GUARANTEED.items():
        got = entries.get(idx)
        if got is None:
            print(f"  [{idx:3}] НЕТ ОТВЕТА (ожидалось {expected})")
            ok = False
        elif got.rgb != expected:
            print(f"  [{idx:3}] РАСХОЖДЕНИЕ: {got.rgb!r} != {expected!r}")
            ok = False
        else:
            print(f"  [{idx:3}] ok  rgb={got.rgb}  w={got.w}")
    print("  → парсер корректен" if ok else "  → ПРОВЕРИТЬ ФОРМАТ")

    # 2. Сколько уникальных цветов
    uniq = {e.rgb for e in entries.values()}
    print(f"\nУникальных RGB: {len(uniq)} из {len(entries)} записей")

    # 3. Отбор под дорожки
    print(f"\nОтобрано {len(picked)} различимых цветов (ΔE ≥ 25):")
    for e in picked:
        print(f"  {e.index:3}  rgb={e.rgb!r:18} w={e.w:3}")

    if len(picked) < 16:
        print(f"\n  ВНИМАНИЕ: нашлось только {len(picked)} — меньше MAX_TRACKS=16.")
    else:
        print("\n  → 16 цветов есть, цикл по палитре не нужен.")

    # 4. Минимальная дистанция внутри отбора
    if len(picked) > 1:
        worst = min(
            delta_e(a.rgb, b.rgb)
            for i, a in enumerate(picked)
            for b in picked[i + 1 :]
        )
        print(f"  Минимальная ΔE внутри отбора: {worst:.1f}")


def emit_module(entries: dict[int, PaletteEntry], picked: list[PaletteEntry]) -> str:
    """Сгенерировать готовый Python-модуль палитры."""
    lines = [
        '"""Палитра LED Push 2 — СГЕНЕРИРОВАНО спайком.',
        "",
        "Не редактировать вручную: перегенерировать",
        "    python spikes/spike_push2_palette.py",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "#: Полная палитра устройства: индекс → (r, g, b, w).",
        "PUSH2_PALETTE: dict[int, tuple[int, int, int, int]] = {",
    ]
    for idx in sorted(entries):
        e = entries[idx]
        lines.append(f"    {idx:3}: ({e.r:3}, {e.g:3}, {e.b:3}, {e.w:3}),")
    lines += [
        "}",
        "",
        "#: Индексы для дорожек — различимые, в порядке предпочтения.",
        "TRACK_PAD_INDICES: tuple[int, ...] = (",
    ]
    for i in range(0, len(picked), 8):
        chunk = ", ".join(str(e.index) for e in picked[i : i + 8])
        lines.append(f"    {chunk},")
    lines += [")", ""]
    return "\n".join(lines)


# ── dry-run ───────────────────────────────────────────────────────────────


def dry_run() -> int:
    """Проверить кодек без железа по примеру из спеки."""
    print("DRY-RUN: проверка парсера на примере из спецификации\n")

    # Пример из спеки: индекс 125 (синий), white=126
    raw = [0x00, 0x21, 0x1D, 0x01, 0x01, 0x04, 0x7D,
           0x00, 0x00, 0x00, 0x00, 0x7F, 0x01, 0x7E, 0x00]
    entry = parse_reply(raw)

    checks = [
        ("парсер вернул запись", entry is not None),
        ("индекс = 125", entry is not None and entry.index == 125),
        ("rgb = (0,0,255)", entry is not None and entry.rgb == (0, 0, 255)),
        ("white = 126", entry is not None and entry.w == 126),
    ]

    # Запрос должен совпасть с примером из спеки (без F0/F7)
    req = build_request(125)
    checks.append(("запрос = 00 21 1D 01 01 04 7D", req == tuple(raw[:7])))

    # Мусор не должен парситься
    checks.append(("мусор отклонён", parse_reply([0x90, 0x3C, 0x64]) is None))
    checks.append(("чужой sysex отклонён",
                   parse_reply([0x00, 0x20, 0x29, 0x02, 0x0A, 0x04] + [0] * 9) is None))

    failed = 0
    for name, ok in checks:
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
        if not ok:
            failed += 1

    # Проверим отбор цветов на синтетической палитре
    print("\nПроверка отбора на синтетической палитре (128 цветов):")
    synth = []
    for i in range(PALETTE_SIZE):
        synth.append(
            PaletteEntry(
                index=i,
                r=(i * 37) % 256,
                g=(i * 91) % 256,
                b=(i * 53) % 256,
                w=0,
            )
        )
    picked = pick_distinct(synth, 16)
    print(f"  отобрано: {len(picked)} — {'ok' if len(picked) == 16 else 'FAIL'}")
    if len(picked) == 16:
        worst = min(
            delta_e(a.rgb, b.rgb)
            for i, a in enumerate(picked)
            for b in picked[i + 1 :]
        )
        print(f"  минимальная ΔE: {worst:.1f}")

    print(f"\n{'ВСЁ ОК' if failed == 0 else f'ПРОВАЛОВ: {failed}'}")
    return 0 if failed == 0 else 1


# ── main ──────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description="Вытащить палитру LED из Push 2")
    ap.add_argument("--list", action="store_true", help="только показать MIDI-порты")
    ap.add_argument("--dry-run", action="store_true", help="без железа: проверить парсер")
    ap.add_argument("--in-port", default=None, help="имя входного порта")
    ap.add_argument("--out-port", default=None, help="имя выходного порта")
    ap.add_argument("--timeout", type=float, default=0.3, help="таймаут на запись, сек")
    ap.add_argument("--out-dir", default="spikes/out", help="куда писать результат")
    args = ap.parse_args()

    if args.dry_run:
        return dry_run()

    if args.list:
        ins = _midi_names("in")
        outs = _midi_names("out")
        if not ins and not outs:
            return 2
        print("Входные порты:")
        for n in ins:
            print(f"  {n}")
        print("\nВыходные порты:")
        for n in outs:
            print(f"  {n}")
        return 0

    in_name, out_name = args.in_port, args.out_port
    if in_name is None or out_name is None:
        det_in, det_out = find_push2_ports()
        in_name = in_name or det_in
        out_name = out_name or det_out

    if not in_name or not out_name:
        print("Push 2 не найден. Доступные порты:", file=sys.stderr)
        for n in _midi_names("in"):
            print(f"  in : {n}", file=sys.stderr)
        for n in _midi_names("out"):
            print(f"  out: {n}", file=sys.stderr)
        print("\nУкажите явно: --in-port '...' --out-port '...'", file=sys.stderr)
        return 2

    print(f"вход:  {in_name}")
    print(f"выход: {out_name}")
    print(f"запрос {PALETTE_SIZE} записей, таймаут {args.timeout}s\n")

    entries = query_palette(in_name, out_name, args.timeout)

    if not entries:
        print("\nУстройство не ответило ни на один запрос.", file=sys.stderr)
        print("Проверить: Push 2 в режиме Live? Порт не занят DAW?", file=sys.stderr)
        return 1

    picked = pick_distinct(list(entries.values()), count=16)
    report(entries, picked)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "push2_palette.json"
    json_path.write_text(
        json.dumps(
            {
                "source": "spike_push2_palette.py",
                "entries": [entries[i].to_dict() for i in sorted(entries)],
                "track_indices": [e.index for e in picked],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    py_path = out_dir / "push2_palette.py"
    py_path.write_text(emit_module(entries, picked), encoding="utf-8")

    print(f"\nзаписано:\n  {json_path}\n  {py_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
