"""Накопитель захваченных MIDI-событий для записи в SMF.

Наполняется из :meth:`src.sync.transport.Transport._deliver` — только
реально доставленные note-события (design add-capture-smf §1, §4). Пишет
worker-поток TickProxy, читает REPL-поток на ``capture stop``:
``list.append`` атомарен под GIL (прецедент ``MidiTrace``), снимок —
новый список, без locks на горячем пути.

Никакого mido здесь нет: накопление отделено от формата
(:class:`src.sync.smf_writer.SmfWriter`).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.sync.transport_event import EventKind


@dataclass(frozen=True)
class CaptureEntry:
    """Одно захваченное событие вывода (design add-capture-smf §4).

    Атрибуты:
        kind: Вид события (только NOTE_ON/NOTE_OFF попадают сюда).
        channel: MIDI-канал 0..15, как доставил транспорт.
        note: Номер ноты 0..127.
        velocity: Velocity note_on; для note_off — ``None`` (writer
            пишет note_off без velocity).
        beat: Эффективная позиция в битах (для отложенных свингом —
            момент фактической доставки).
    """

    kind: EventKind
    channel: int
    note: int
    velocity: int | None
    beat: float


class CaptureRecorder:
    """Потокобезопасный накопитель захваченных событий (design §2, §4).

    Пишет транспортный поток (:meth:`record`), снимок забирает REPL-поток
    (:meth:`entries`) — атомарный append под GIL + неизменяемая копия
    списка, без блокировок.
    """

    def __init__(self) -> None:
        self._entries: list[CaptureEntry] = []

    def record(
        self,
        kind: EventKind,
        channel: int,
        note: int,
        velocity: int | None,
        beat: float,
    ) -> None:
        """Добавить событие (транспортный поток).

        Args:
            kind: Вид события (NOTE_ON/NOTE_OFF).
            channel: MIDI-канал 0..15.
            note: Номер ноты.
            velocity: Velocity note_on или ``None`` для note_off.
            beat: Эффективная позиция в битах.
        """
        self._entries.append(
            CaptureEntry(
                kind=kind,
                channel=int(channel),
                note=int(note),
                velocity=velocity,
                beat=float(beat),
            )
        )

    def entries(self) -> list[CaptureEntry]:
        """Неизменяемый снимок накопителя (новый список)."""
        return list(self._entries)

    def __len__(self) -> int:
        """Текущее число накопленных событий."""
        return len(self._entries)
