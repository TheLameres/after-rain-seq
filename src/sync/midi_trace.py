"""Кольцевой буфер отправленных MIDI-событий для диагностики из REPL.

Пишется в :meth:`src.sync.transport.Transport._deliver` — то есть ровно в той
точке, где событие уходит в порт (или отбрасывается, если порта нет). Поэтому
в буфере видно и реально отправленное, и потерянное.

deque-операции потокобезопасны под GIL: пишет поток TickProxy, читает REPL.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.sync.transport_event import TransportEvent

DEFAULT_CAPACITY: int = 500


@dataclass(frozen=True)
class MidiTraceEntry:
    """Одно событие на выходе транспорта.

    Атрибуты:
        beat: Позиция на таймлайне в битах.
        port: Метка порта из конфига.
        channel: MIDI-канал 0..15.
        kind: ``note_on`` / ``note_off`` / ``cc`` / ``all_notes_off``.
        note: Номер ноты (для note_on/note_off) или ``None``.
        velocity: Скорость ноты или ``None``.
        control: Номер контроллера (для CC) или ``None``.
        value: Значение контроллера (для CC) или ``None``.
        delivered: ``False``, если порт не найден и событие отброшено.
    """

    beat: float
    port: str
    channel: int
    kind: str
    note: int | None = None
    velocity: int | None = None
    control: int | None = None
    value: int | None = None
    delivered: bool = True


class MidiTrace:
    """Кольцевой буфер последних событий выхода.

    Args:
        capacity: Сколько последних событий хранить.
    """

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        self._entries: deque[MidiTraceEntry] = deque(maxlen=capacity)

    def record(self, entry: MidiTraceEntry) -> None:
        """Добавить событие (старые вытесняются по capacity)."""
        self._entries.append(entry)

    def recent(self, n: int) -> list[MidiTraceEntry]:
        """Последние ``n`` событий в порядке отправки (n <= 0 → пусто)."""
        if n <= 0:
            return []
        return list(self._entries)[-n:]

    def clear(self) -> None:
        """Очистить буфер."""
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    @staticmethod
    def entry_from(event: TransportEvent, delivered: bool) -> MidiTraceEntry:
        """Преобразовать событие транспорта в запись для буфера."""
        from src.sync.transport_event import EventKind

        kind = {
            EventKind.NOTE_ON: "note_on",
            EventKind.NOTE_OFF: "note_off",
            EventKind.CONTROL_CHANGE: "cc",
            EventKind.ALL_NOTES_OFF: "all_notes_off",
        }.get(event.kind, event.kind.name.lower())
        return MidiTraceEntry(
            beat=float(event.beat),
            port=event.port_label,
            channel=int(event.channel),
            kind=kind,
            note=int(event.note) if event.note is not None else None,
            velocity=int(event.velocity) if event.velocity is not None else None,
            control=int(event.control) if event.control is not None else None,
            value=int(event.value) if event.value is not None else None,
            delivered=delivered,
        )


def format_entry(entry: MidiTraceEntry, track_name: str | None = None) -> str:
    """Строка для REPL: beat, порт, канал, тип, параметры, имя дорожки.

    Args:
        entry: Запись из буфера.
        track_name: Дорожка, определённая по порту и каналу, или ``None``.
    """
    who = track_name or "—"
    head = f"{entry.beat:9.3f}  {entry.port:<10} ch{entry.channel:<3} {entry.kind:<13}"
    if entry.kind in ("note_on", "note_off"):
        body = f"{entry.note if entry.note is not None else '—':>3}"
        if entry.kind == "note_on":
            body += f" vel {entry.velocity if entry.velocity is not None else '—':>3}"
    elif entry.kind == "cc":
        body = f"cc {entry.control} = {entry.value}"
    else:
        body = ""
    tail = "" if entry.delivered else "  ← ОТБРОШЕНО: порт не найден"
    return f"{head} {body:<12} {who}{tail}"
