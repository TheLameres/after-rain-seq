"""B2: смена degrees применяется после проигрывания текущей ступени.

Сквозные тесты: MelodicEngine тикает, ноты читаются из очереди TransportEvent.
"""

from __future__ import annotations

import queue

from src.harmony.harmony import Harmony
from src.session.engine.melodic_engine import MelodicEngine
from src.session.model.melodic_track import MelodicTrack
from src.sync.transport_event import EventKind, TransportEvent

PORT = "p"


def _engine(
    profile: str, degrees: list[int]
) -> tuple[MelodicEngine, MelodicTrack, queue.Queue]:
    q: queue.Queue = queue.Queue(maxsize=10000)
    track = MelodicTrack(name="T", profile_name=profile, degrees=degrees)
    eng = MelodicEngine(track, Harmony("A", "dorian"), q, PORT)
    return eng, track, q


class _Clock:
    """Монотонное время тиков: каждый вызов продолжает с места остановки."""

    def __init__(self) -> None:
        self.beat = 0.0


_CLOCKS: dict[int, _Clock] = {}


def _run(
    eng: MelodicEngine, until: float, step: float = 1.0 / 24.0
) -> None:  # MIDI clock 24 ppq
    clock = _CLOCKS.setdefault(id(eng), _Clock())
    while clock.beat <= until + 1e-9:
        eng.tick(clock.beat)
        clock.beat += step


def _note_ons(q: queue.Queue) -> list[tuple[float, int]]:
    out: list[tuple[float, int]] = []
    while not q.empty():
        ev: TransportEvent = q.get_nowait()
        if ev.kind is EventKind.NOTE_ON:
            out.append((ev.beat, ev.note))
    return sorted(out)


class TestDeferredApplication:
    def test_change_waits_for_current_step_boundary(self) -> None:
        """Правка в середине ступени 1 не меняет её, а применяется с beat 2."""
        eng, track, _q = _engine("lead", [0, 0, 0, 0])
        _run(eng, 1.5)
        track.degrees = [4, 4, 4, 4]
        assert track.pending_degrees == (4, 4, 4, 4)
        assert track.degrees == (0, 0, 0, 0)

        _run(eng, 6.0)
        assert track.degrees == (4, 4, 4, 4)
        assert track.pending_degrees is None

    def test_notes_before_boundary_keep_old_degree(self) -> None:
        eng, track, q = _engine("lead", [0, 0, 0, 0])
        _run(eng, 1.5)
        track.degrees = [4, 4, 4, 4]
        _run(eng, 6.0)
        notes = _note_ons(q)
        before = [n for b, n in notes if b < 2.0 - 1e-6]
        after = [n for b, n in notes if b >= 2.0 - 1e-6]
        assert before and after
        assert len(set(before)) == 1 and len(set(after)) == 1
        assert before[0] != after[0]  # 0 и 4 ступени — разные ноты

    def test_scheduled_ahead_notes_are_replaced(self) -> None:
        """Лукахед уже поставил ноты с beat 2..4 по старой прогрессии — они заменены."""
        eng, track, q = _engine("lead", [0, 0, 0, 0])
        _run(eng, 1.5)  # horizon 4 — в очереди уже есть ноты до beat ~5.5
        track.degrees = [4, 4, 4, 4]
        _run(eng, 8.0)
        notes = _note_ons(q)
        after = {n for b, n in notes if b >= 2.0 - 1e-6}
        assert len(after) == 1
        assert after == {_pitch(eng, 4)}

    def test_no_note_is_left_hanging(self) -> None:
        """Каждая нота, которая включилась, получает свой note-off.

        Лишние note-off от отменённых вперёд нот допустимы (безвредны), поэтому
        проверка: по каждой высоте off не меньше on.
        """
        from collections import Counter

        eng, track, q = _engine("lead", [0, 0, 0, 0])
        _run(eng, 1.5)
        track.degrees = [4, 4, 4, 4]
        _run(eng, 12.0)
        ons: Counter[int] = Counter()
        offs: Counter[int] = Counter()
        while not q.empty():
            ev = q.get_nowait()
            if ev.kind is EventKind.NOTE_ON and ev.beat <= 10.0:
                ons[ev.note] += 1
            elif ev.kind is EventKind.NOTE_OFF:
                offs[ev.note] += 1
        for note, count in ons.items():
            assert offs[note] >= count, (note, count, offs[note])

    def test_revision_bumped_only_on_commit(self) -> None:
        eng, track, _ = _engine("lead", [0, 0, 0, 0])
        _run(eng, 1.5)
        rev = track.revision
        track.degrees = [4, 4, 4, 4]
        assert track.revision == rev  # пока ждём границу
        _run(eng, 2.5)
        assert track.revision == rev + 1

    def test_setting_back_to_playing_cancels_pending(self) -> None:
        eng, track, _ = _engine("lead", [0, 0, 0, 0])
        _run(eng, 1.5)
        track.degrees = [4, 4, 4, 4]
        track.degrees = [0, 0, 0, 0]
        assert track.pending_degrees is None

    def test_pad_chord_source_waits_for_its_step(self) -> None:
        """pad: ступень = 1 beat; правка в середине beat 1.5 применяется с beat 2."""
        eng, track, _ = _engine("pad", [0, 3])
        _run(eng, 1.5)
        track.degrees = [4, 4]
        assert track.degrees == (0, 3)
        _run(eng, 3.0)
        assert track.degrees == (4, 4)

    def test_not_ticking_yet_applies_immediately(self) -> None:
        """Движок ещё не стартовал: ступеней, которые можно пропустить, нет — сразу."""
        eng, track, _ = _engine("lead", [0, 0, 0, 0])
        track.degrees = [4, 4, 4, 4]
        eng.tick(0.0)
        assert track.degrees == (4, 4, 4, 4)
        assert track.pending_degrees is None

    def test_slicer_profile_applies_without_step(self) -> None:
        """Ступеней у slicer нет — прогрессия применяется сразу, фаза не сдвигается."""
        eng, track, _ = _engine("sub", [0, 3])
        _run(eng, 1.0)
        track.degrees = [2, 2]
        eng.tick(1.0)
        assert track.pending_degrees is None


def _pitch(eng: MelodicEngine, degree: int) -> int:
    return eng._harmony.degree_to_note(degree, eng.track.octave)
