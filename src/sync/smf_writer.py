"""Писатель SMF-файла из накопленных событий захвата.

Первая точка использования mido для *записи* в ``src/`` (design
add-capture-smf §3): один трек (SMF type 0), PPQ 480 (= ``ticks_per_beat``
Timeline), меты track_name/set_tempo/time_signature 4/4, note_off
настоящим 0x80. Файл создаётся эксклюзивно (``xb``) — перезапись
существующего запрещена.

Сортировка составным ключом решает системную коллизию гейта 0.25 бита:
note_off удара ``k`` и note_on удара ``k+1`` одной lane попадают на один
тик — off записывается раньше on независимо от порядка доставки
(design §3, tie-break).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import mido  # type: ignore[import-untyped]

from src.sync.capture_recorder import CaptureEntry
from src.sync.transport_event import EventKind

TRACK_NAME: str = "after-rain-seq capture"
"""Имя трека в метах SMF."""


class SmfWriter:
    """Запись накопителя захвата в SMF type 0 (design §3)."""

    def write(
        self,
        path: Path,
        entries: Sequence[CaptureEntry],
        bpm: float,
        ticks_per_beat: int = 480,
    ) -> None:
        """Записать снимок событий в SMF-файл.

        Аргументы:
            path: Путь файла; существующий файл — ``FileExistsError``
                (эксклюзивное создание, перезапись запрещена).
            entries: Снимок накопителя (не обязан быть отсортирован).
            bpm: BPM на момент старта захвата (одна tempo-мета на тик 0).
            ticks_per_beat: Тиков на бит (PPQ), по умолчанию 480.

        Raises:
            FileExistsError: Файл уже существует.
            OSError: Ошибка записи или несуществующий каталог.
        """
        midi = mido.MidiFile(type=0, ticks_per_beat=ticks_per_beat)
        track = mido.MidiTrack()
        midi.tracks.append(track)

        track.append(mido.MetaMessage("track_name", name=TRACK_NAME, time=0))
        track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
        track.append(
            mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0)
        )

        ordered = self._sorted(entries, ticks_per_beat)
        previous_tick = 0
        for tick, entry in ordered:
            delta = tick - previous_tick
            previous_tick = tick
            if entry.kind is EventKind.NOTE_OFF:
                track.append(
                    mido.Message(
                        "note_off",
                        channel=entry.channel,
                        note=entry.note,
                        velocity=0,
                        time=delta,
                    )
                )
            else:
                track.append(
                    mido.Message(
                        "note_on",
                        channel=entry.channel,
                        note=entry.note,
                        velocity=entry.velocity if entry.velocity is not None else 0,
                        time=delta,
                    )
                )

        with open(path, "xb") as fp:
            midi.save(file=fp)

    @staticmethod
    def _sorted(
        entries: Sequence[CaptureEntry], ticks_per_beat: int
    ) -> list[tuple[int, CaptureEntry]]:
        """Абсолютные тики в порядке файла (design §3).

        Первичный ключ — абсолютный тик (``round(beat * ticks_per_beat)``);
        вторичный — вид события (note_off раньше note_on); при равных тике
        и виде — порядок доставки (стабильная сортировка по индексу).
        """
        decorated = [
            (
                round(entry.beat * ticks_per_beat),
                0 if entry.kind is EventKind.NOTE_OFF else 1,
                index,
                entry,
            )
            for index, entry in enumerate(entries)
            if entry.kind in (EventKind.NOTE_ON, EventKind.NOTE_OFF)
        ]
        decorated.sort(key=lambda item: (item[0], item[1], item[2]))
        return [(tick, entry) for tick, _rank, _index, entry in decorated]
