#!/usr/bin/env python3
"""
Spike: MIDI Dump — диагностический разбор .mid файла.

Секции вывода:
  1. СТРУКТУРА — SMF type, ticks_per_beat, число треков, длительность,
     размер файла; track_name/set_tempo (bpm)/time_signature по трекам.
  2. EVENTS — все note_on/note_off с абсолютными тиками и пересчётом:
     bar.beat.tick | abs | beats | step (16-сетка) | type | note | vel | ch.
     Печатаются первые --max-events строк + счётчик остальных.
  3. SUMMARY ПО НОТАМ — для каждой ноты: количество, каналы, позиции
     steps % 16 (округление 4 знака), диапазон velocity, диапазон
     длительностей (в тиках и в битах).
  4. АНОМАЛИИ — ноты вне 36..51, залипшие note_on (без парного note_off),
     сиротские note_off, перекрытия одинаковых нот, удары вне 16-й сетки,
     канал != 9 (GM drums), дубли одной ноты на одном тике, слишком
     плотные серии (интервал < 1/32 бара), странные длительности
     (<= 0 или > 1 бара).
  5. (--drum-dub) DRUM-DUB — сравнение наблюдаемых steps % 16 с эталоном
     examples/drum_dub.py: kick(36)={0,3,4,7}, snare(38)={4,12},
     closedhat(42)={0,2,...,14}, shaker(49)={0,6,12}, conga(51)={6,14}.

Запуск:
    uv run python spikes/spike_midi_dump.py
    uv run python spikes/spike_midi_dump.py "examples/drum track bug.mid" --drum-dub
    uv run python spikes/spike_midi_dump.py take1.mid --max-events 120

note_on с velocity 0 трактуется как note_off (обычная практика SMF).
Инструмент только читает файл и печатает отчёт — ничего не записывает.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict, deque
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

import mido

DEFAULT_PATH = "examples/drum track bug.mid"
MAX_LIST_ITEMS = 20  # сколько элементов каждой аномалии печатать полностью
GRID_EPS = 1e-6  # допуск на дробность шага при проверке 16-й сетки
STEPS_PER_BAR = 16  # 16-я сетка при 4/4
BEATS_PER_BAR = 4
GM_DRUM_CHANNEL = 9  # 0-базный канал GM drums (канал 10 в 1-базной нотации)
NOTE_MIN = 36  # нижняя граница типичных drum lane'ов проекта
NOTE_MAX = 51  # верхняя граница
DENSE_GAP_BEATS = BEATS_PER_BAR / 32  # 1/32 бара = 1/8 бита = половина 16-го шага

# Эталон examples/drum_dub.py: pitch -> (имя lane'а, позиции в такте steps % 16).
REFERENCE: dict[int, tuple[str, frozenset[int]]] = {
    36: ("kick", frozenset({0, 3, 4, 7})),
    38: ("snare", frozenset({4, 12})),
    42: ("closedhat", frozenset(range(0, STEPS_PER_BAR, 2))),
    49: ("shaker", frozenset({0, 6, 12})),
    51: ("conga", frozenset({6, 14})),
}


@dataclass(frozen=True)
class NoteEvent:
    """note_on/note_off-событие с абсолютным тиком и пересчётом в сетку."""

    track: int
    abs_tick: int
    kind: str  # "on" | "off" (note_on с velocity 0 => "off")
    note: int
    velocity: int
    channel: int
    ticks_per_beat: int

    @property
    def beats(self) -> float:
        """Абсолютная позиция в битах (четвертных долях)."""
        return self.abs_tick / self.ticks_per_beat

    @property
    def step(self) -> float:
        """Абсолютная позиция в шагах 16-й сетки (дробная — вне сетки)."""
        return self.abs_tick * STEPS_PER_BAR / (self.ticks_per_beat * BEATS_PER_BAR)

    @property
    def bar(self) -> int:
        """Номер такта, 1-базный."""
        return int(self.step // STEPS_PER_BAR) + 1

    @property
    def position(self) -> float:
        """Позиция внутри такта: steps % 16, округление до 4 знаков."""
        return round(self.step % STEPS_PER_BAR, 4)


@dataclass(frozen=True)
class NotePair:
    """Пара note_on/note_off одной ноты (FIFO по каналу и питчу)."""

    on: NoteEvent
    off: NoteEvent

    @property
    def duration_ticks(self) -> int:
        """Длительность в тиках."""
        return self.off.abs_tick - self.on.abs_tick

    @property
    def duration_beats(self) -> float:
        """Длительность в битах."""
        return self.duration_ticks / self.on.ticks_per_beat


@dataclass(frozen=True)
class NoteGroup:
    """Группа одинаковых note_on на одном тике (для детекции дублей)."""

    abs_tick: int
    note: int
    events: tuple[NoteEvent, ...]


@dataclass(frozen=True)
class DensePair:
    """Слишком плотная серия: два удара одной ноты с интервалом < 1/32 бара."""

    prev: NoteEvent
    curr: NoteEvent

    @property
    def gap_beats(self) -> float:
        """Интервал между ударами в битах."""
        return (self.curr.abs_tick - self.prev.abs_tick) / self.prev.ticks_per_beat


def load_midi(path: str) -> mido.MidiFile:
    """Читает MIDI-файл; при ошибке печатает внятное сообщение и завершает процесс."""
    if not os.path.isfile(path):
        print(f"Ошибка: файл не найден: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        return mido.MidiFile(path)
    # mido на битых/обрезанных/не-MIDI файлах бросает OSError (нет MThd/MTrk),
    # ValueError (битые меты), EOFError (обрезанный чанк) или KeySignatureError.
    except (OSError, ValueError, EOFError, mido.KeySignatureError) as err:
        print(
            f"Ошибка: не удалось прочитать MIDI-файл {path!r} "
            f"(это точно .mid?): {err}",
            file=sys.stderr,
        )
        sys.exit(1)


def _with_abs_ticks(track: mido.MidiTrack) -> Iterator[tuple[int, mido.Message]]:
    """Итерирует трек, попутно накапливая абсолютный тик каждого сообщения."""
    tick = 0
    for msg in track:
        tick += msg.time
        yield tick, msg


def _track_meta(track: mido.MidiTrack) -> str:
    """Однострочное описание меты трека: имя, темп(ы), размеры."""
    names = [msg.name for msg in track if msg.type == "track_name"]
    tempos = [
        f"{mido.tempo2bpm(msg.tempo):.1f} bpm @ tick {tick}"
        for tick, msg in _with_abs_ticks(track)
        if msg.type == "set_tempo"
    ]
    signatures = [
        f"{msg.numerator}/{msg.denominator} @ tick {tick}"
        for tick, msg in _with_abs_ticks(track)
        if msg.type == "time_signature"
    ]
    parts: list[str] = []
    if names:
        parts.append(f"name={names[0]!r}")
    if tempos:
        parts.append("tempo: " + ", ".join(tempos))
    if signatures:
        parts.append("time_signature: " + ", ".join(signatures))
    return "; ".join(parts) if parts else "(меты нет)"


def print_structure(midi_file: mido.MidiFile, path: str) -> None:
    """Секция 1: заголовок SMF и меты по трекам."""
    size = os.path.getsize(path)
    print("=== СТРУКТУРА ===")
    print(f"Файл: {path} ({size} байт)")
    print(
        f"SMF type: {midi_file.type}, ticks_per_beat: {midi_file.ticks_per_beat}, "
        f"треков: {len(midi_file.tracks)}"
    )
    try:
        print(f"Длительность: {midi_file.length:.3f} c")
    except ValueError:
        print("Длительность: n/a (SMF type 2)")
    for index, track in enumerate(midi_file.tracks):
        print(f"Трек {index}: {_track_meta(track)}")
    print()


def collect_note_events(midi_file: mido.MidiFile) -> list[NoteEvent]:
    """Собирает все note_on/note_off из всех треков, сортирует по абсолютному тику.

    note_on с velocity 0 записывается как kind="off" (эквивалент note_off).
    Сортировка стабильна: при равных тике и треке сохраняется порядок файла.
    """
    tpq = midi_file.ticks_per_beat
    events: list[NoteEvent] = []
    for track_idx, track in enumerate(midi_file.tracks):
        for tick, msg in _with_abs_ticks(track):
            if msg.type not in ("note_on", "note_off"):
                continue
            is_on = msg.type == "note_on" and msg.velocity > 0
            events.append(
                NoteEvent(
                    track=track_idx,
                    abs_tick=tick,
                    kind="on" if is_on else "off",
                    note=msg.note,
                    velocity=msg.velocity,
                    channel=msg.channel,
                    ticks_per_beat=tpq,
                )
            )
    events.sort(key=lambda ev: (ev.abs_tick, ev.track))
    return events


def _fmt_num(value: float) -> str:
    """Число без лишних нулей: 0 -> '0', 2.5 -> '2.5', 0.125 -> '0.125'."""
    return f"{value:g}"


def _format_event(ev: NoteEvent) -> str:
    """Строка таблицы событий: bar.beat.tick | abs | beats | step | ..."""
    steps_per_beat = STEPS_PER_BAR // BEATS_PER_BAR
    beat = int(ev.step % STEPS_PER_BAR // steps_per_beat) + 1
    tick_in_beat = ev.abs_tick % ev.ticks_per_beat
    pos = f"{ev.bar}.{beat}.{tick_in_beat}"
    return (
        f"{pos:<11} | {ev.abs_tick:>8} | {ev.beats:>7.3f} | {ev.step:>8.4f}"
        f" | {ev.kind:<4} | {ev.note:>4} | {ev.velocity:>3} | {ev.channel:>2}"
    )


def print_events(events: list[NoteEvent], max_events: int) -> None:
    """Секция 2: таблица note-событий (первые max_events строк + счётчик остальных)."""
    header = (
        f"{'bar.beat.tick':<11} | {'abs':>8} | {'beats':>7} | {'step':>8}"
        f" | {'type':<4} | {'note':>4} | {'vel':>3} | {'ch':>2}"
    )
    print(f"=== EVENTS ({len(events)} note-событий) ===")
    print("(note_on с velocity 0 показан как off)")
    if not events:
        print("(нет note-событий)")
        print()
        return
    print(header)
    for ev in events[:max_events]:
        print(_format_event(ev))
    if len(events) > max_events:
        hidden = len(events) - max_events
        print(f"  … +{hidden} ещё (всего {len(events)}; увеличьте --max-events)")
    print()


def pair_notes(
    events: list[NoteEvent],
) -> tuple[list[NotePair], list[NoteEvent], list[NoteEvent], list[NoteEvent]]:
    """Парит note_on/note_off FIFO по ключу (канал, нота).

    Возвращает (пары, залипшие note_on, сиротские note_off, перекрытия).
    Перекрытие — note_on при незакрытой предыдущей той же ноте.
    """
    pairs: list[NotePair] = []
    stuck: list[NoteEvent] = []
    orphans: list[NoteEvent] = []
    overlaps: list[NoteEvent] = []
    open_notes: dict[tuple[int, int], deque[NoteEvent]] = defaultdict(deque)
    for ev in events:
        key = (ev.channel, ev.note)
        queue = open_notes[key]
        if ev.kind == "on":
            if queue:
                overlaps.append(ev)
            queue.append(ev)
        elif not queue:
            orphans.append(ev)
        else:
            pairs.append(NotePair(on=queue.popleft(), off=ev))
    for queue in open_notes.values():
        stuck.extend(queue)
    stuck.sort(key=lambda ev: (ev.abs_tick, ev.note))
    return pairs, stuck, orphans, overlaps


def print_note_summary(events: list[NoteEvent], pairs: list[NotePair]) -> None:
    """Секция 3: сводка по нотам — количество, каналы, позиции, velocity, длительности."""
    print("=== SUMMARY ПО НОТАМ ===")
    ons = [ev for ev in events if ev.kind == "on"]
    if not ons:
        print("(нет note_on-событий)")
        print()
        return
    durations: dict[int, list[NotePair]] = defaultdict(list)
    for pair in pairs:
        durations[pair.on.note].append(pair)
    print(
        "note | count | ch | vel | duration (ticks) | duration (beats)"
        " | positions (steps % 16)"
    )
    for note in sorted({ev.note for ev in ons}):
        note_ons = [ev for ev in ons if ev.note == note]
        channels = ", ".join(str(c) for c in sorted({ev.channel for ev in note_ons}))
        vel_min = min(ev.velocity for ev in note_ons)
        vel_max = max(ev.velocity for ev in note_ons)
        positions = ", ".join(
            _fmt_num(p) for p in sorted({ev.position for ev in note_ons})
        )
        if durations[note]:
            dticks = sorted(p.duration_ticks for p in durations[note])
            dbeats = sorted(p.duration_beats for p in durations[note])
            dur = (
                f"{dticks[0]}..{dticks[-1]} | "
                f"{_fmt_num(dbeats[0])}..{_fmt_num(dbeats[-1])}"
            )
        else:
            dur = "n/a | n/a"
        print(
            f"{note:>4} | {len(note_ons):>5} | {channels:<3} | "
            f"{vel_min}..{vel_max:<3} | {dur} | {positions}"
        )
    print()


def find_out_of_range(events: list[NoteEvent]) -> list[NoteEvent]:
    """Удары вне диапазона 36..51 (типичные GM drum lane'ы проекта)."""
    return [
        ev for ev in events if ev.kind == "on" and not NOTE_MIN <= ev.note <= NOTE_MAX
    ]


def find_off_grid(events: list[NoteEvent]) -> list[NoteEvent]:
    """Удары вне 16-й сетки (дробный шаг)."""
    return [
        ev
        for ev in events
        if ev.kind == "on" and abs(ev.step - round(ev.step)) > GRID_EPS
    ]


def find_wrong_channel(events: list[NoteEvent]) -> list[NoteEvent]:
    """Удары не на GM drum-канале (9, 0-базный)."""
    return [ev for ev in events if ev.kind == "on" and ev.channel != GM_DRUM_CHANNEL]


def find_duplicates(events: list[NoteEvent]) -> list[NoteGroup]:
    """Дубли: несколько note_on одной ноты на одном тике."""
    grouped: dict[tuple[int, int], list[NoteEvent]] = defaultdict(list)
    for ev in events:
        if ev.kind == "on":
            grouped[(ev.abs_tick, ev.note)].append(ev)
    return [
        NoteGroup(abs_tick=tick, note=note, events=tuple(evs))
        for (tick, note), evs in grouped.items()
        if len(evs) > 1
    ]


def find_too_dense(events: list[NoteEvent]) -> list[DensePair]:
    """Слишком плотные серии: подряд идущие удары одной ноты ближе 1/32 бара."""
    last_by_key: dict[tuple[int, int], NoteEvent] = {}
    dense: list[DensePair] = []
    for ev in events:
        if ev.kind != "on":
            continue
        key = (ev.channel, ev.note)
        prev = last_by_key.get(key)
        if (
            prev is not None
            and ev.abs_tick - prev.abs_tick < prev.ticks_per_beat * DENSE_GAP_BEATS
        ):
            dense.append(DensePair(prev=prev, curr=ev))
        last_by_key[key] = ev
    return dense


def find_weird_durations(pairs: list[NotePair]) -> list[NotePair]:
    """Странные длительности: <= 0 или больше 1 бара (4 бита)."""
    return [
        pair
        for pair in pairs
        if pair.duration_ticks <= 0
        or pair.duration_ticks > pair.on.ticks_per_beat * BEATS_PER_BAR
    ]


def _print_anomaly_list(title: str, lines: list[str]) -> None:
    """Печатает пункт аномалий: список строк (с обрезкой) или 'none'."""
    print(f"{title}:")
    if not lines:
        print("  none")
        return
    for line in lines[:MAX_LIST_ITEMS]:
        print(f"  {line}")
    if len(lines) > MAX_LIST_ITEMS:
        print(f"  … ещё {len(lines) - MAX_LIST_ITEMS} (всего {len(lines)})")


def print_anomalies(
    events: list[NoteEvent],
    stuck: list[NoteEvent],
    orphans: list[NoteEvent],
    overlaps: list[NoteEvent],
    pairs: list[NotePair],
) -> None:
    """Секция 4: девять проверок аномалий, каждая — список или 'none'."""
    print("=== АНОМАЛИИ ===")
    _print_anomaly_list(
        "1) ноты вне 36..51",
        [
            f"tick {ev.abs_tick}, note {ev.note}, vel {ev.velocity}, ch {ev.channel}"
            for ev in find_out_of_range(events)
        ],
    )
    _print_anomaly_list(
        "2) залипшие note_on (без парного note_off)",
        [
            f"tick {ev.abs_tick}, note {ev.note}, ch {ev.channel}, track {ev.track}"
            for ev in stuck
        ],
    )
    _print_anomaly_list(
        "3) сиротские note_off",
        [
            f"tick {ev.abs_tick}, note {ev.note}, ch {ev.channel}, track {ev.track}"
            for ev in orphans
        ],
    )
    _print_anomaly_list(
        "4) перекрытие одинаковых нот (note_on при незакрытой предыдущей)",
        [f"tick {ev.abs_tick}, note {ev.note}, ch {ev.channel}" for ev in overlaps],
    )
    _print_anomaly_list(
        "5) удары вне 16-й сетки (дробный шаг)",
        [
            f"tick {ev.abs_tick}, step {_fmt_num(ev.step)}, note {ev.note}"
            for ev in find_off_grid(events)
        ],
    )
    _print_anomaly_list(
        "6) канал != 9 (GM drums)",
        [
            f"tick {ev.abs_tick}, note {ev.note}, ch {ev.channel}"
            for ev in find_wrong_channel(events)
        ],
    )
    _print_anomaly_list(
        "7) дубли одной ноты на одном тике",
        [
            f"tick {group.abs_tick}, note {group.note}, x{len(group.events)} "
            f"(vel {[ev.velocity for ev in group.events]}, "
            f"ch {sorted({ev.channel for ev in group.events})})"
            for group in find_duplicates(events)
        ],
    )
    _print_anomaly_list(
        "8) слишком плотные серии (интервал < 1/32 бара)",
        [
            f"ticks {pair.prev.abs_tick} -> {pair.curr.abs_tick}, "
            f"gap {_fmt_num(pair.gap_beats)} бита, note {pair.curr.note}, "
            f"ch {pair.curr.channel}"
            for pair in find_too_dense(events)
        ],
    )
    _print_anomaly_list(
        "9) странные длительности (<= 0 или > 1 бара)",
        [
            f"tick {pair.on.abs_tick}, note {pair.on.note}, "
            f"duration {pair.duration_ticks} тиков ({_fmt_num(pair.duration_beats)} бита)"
            for pair in find_weird_durations(pairs)
        ],
    )
    print()


def print_drum_dub(events: list[NoteEvent]) -> None:
    """Секция 5 (--drum-dub): сравнение steps % 16 с эталоном examples/drum_dub.py."""
    print("=== DRUM-DUB (эталон examples/drum_dub.py) ===")
    observed: dict[int, set[float]] = defaultdict(set)
    bars: dict[int, set[int]] = defaultdict(set)
    for ev in events:
        if ev.kind == "on":
            observed[ev.note].add(ev.position)
            bars[ev.note].add(ev.bar)

    ok_count = 0
    diff_count = 0
    unknown_count = 0
    for note in sorted(set(REFERENCE) | set(observed)):
        bar_count = len(bars[note])
        actual = observed.get(note, set())
        actual_str = ", ".join(_fmt_num(p) for p in sorted(actual)) or "-"
        if note not in REFERENCE:
            unknown_count += 1
            print(
                f"{note:>4} {'?':<10} баров {bar_count:>2}: {actual_str}  (нет в эталоне)"
            )
            continue
        name, expected = REFERENCE[note]
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        expected_str = ", ".join(_fmt_num(p) for p in sorted(expected))
        if missing or extra:
            diff_count += 1
            status = "DIFF"
        else:
            ok_count += 1
            status = "OK"
        print(
            f"{note:>4} {name:<10} баров {bar_count:>2}: {actual_str}"
            f"  | эталон: {expected_str}  | {status}"
        )
        if missing:
            print(f"      не хватает: {', '.join(_fmt_num(p) for p in missing)}")
        if extra:
            print(f"      лишние: {', '.join(_fmt_num(p) for p in extra)}")
    print(f"Итого: {ok_count} OK, {diff_count} DIFF, {unknown_count} не из эталона")
    print()


def _parse_non_negative_int(value: str) -> int:
    """argparse type: неотрицательное целое."""
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"ожидалось целое число, получено: {value!r}"
        ) from None
    if parsed < 0:
        raise argparse.ArgumentTypeError("ожидалось неотрицательное число")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разбор аргументов командной строки."""
    parser = argparse.ArgumentParser(
        prog="spike_midi_dump",
        description=(
            "Диагностический разбор MIDI-файла: структура SMF, таблица "
            "note-событий в 16-й сетке, сводка по нотам, поиск аномалий "
            "(залипшие/сиротские события, перекрытия, дубли, вне сетки)."
        ),
        epilog=(
            "Примеры:\n"
            "  uv run python spikes/spike_midi_dump.py\n"
            '  uv run python spikes/spike_midi_dump.py "examples/drum track bug.mid" --drum-dub\n'
            "  uv run python spikes/spike_midi_dump.py take1.mid --max-events 120"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=DEFAULT_PATH,
        help="Путь к .mid файлу (default: %(default)s)",
    )
    parser.add_argument(
        "--max-events",
        type=_parse_non_negative_int,
        default=60,
        metavar="N",
        help="Сколько строк таблицы событий печатать полностью (default: %(default)s)",
    )
    parser.add_argument(
        "--drum-dub",
        action="store_true",
        help=(
            "Сравнить позиции ударов (steps % 16) с эталоном "
            "examples/drum_dub.py: kick/snare/closedhat/shaker/conga"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Точка входа: читает файл, печатает все секции отчёта."""
    args = parse_args(argv)
    midi_file = load_midi(args.path)
    print_structure(midi_file, args.path)
    events = collect_note_events(midi_file)
    pairs, stuck, orphans, overlaps = pair_notes(events)
    print_events(events, args.max_events)
    print_note_summary(events, pairs)
    print_anomalies(events, stuck, orphans, overlaps, pairs)
    if args.drum_dub:
        print_drum_dub(events)


if __name__ == "__main__":
    main()
