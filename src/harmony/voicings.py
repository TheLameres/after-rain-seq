"""Аккорды, войсинги и обращения — поверх :class:`src.harmony.Harmony`.

Всё, что касается аккордов, сгруппировано в классе :class:`Voicing`. Это
класс-утилита без состояния: :class:`Harmony` передаётся первым
аргументом каждой операции, никакого скрытого контекста.

Аккорд не задаётся («это min7»), а **выводится** из ступеней лада: берём
ступени через одну, качество получается само. Запись ``(1-3-5)`` — это
не интервалы, а какие ступени лада взять от корня аккорда; одна запись
работает во всех ладах.

Пример (A dorian)::

    h = Harmony("A", "dorian")
    Voicing.chord_degrees(h, 0)          # (0, 2, 4)     -> A C E   -> Am
    Voicing.chord_degrees(h, 0, "7")     # (0, 2, 4, 6)  -> A C E G -> Am7
    Voicing.chord_notes(h, 0, octave=5)  # (69, 72, 76)

Главная ловушка — 1-based против 0-based: музыкант говорит «первая,
третья, пятая», индексы isobar с нуля. Разница в шаг молча даёт другой
аккорд, поэтому конверсия — один метод, одно место, покрыта тестом:
:meth:`Voicing.to_offsets`.
"""

from __future__ import annotations

from typing import ClassVar

from src.harmony.harmony import (
    FIFTH_DIMINISHED,
    FIFTH_PERFECT,
    THIRD_MAJOR,
    THIRD_MINOR,
    Harmony,
    HarmonyError,
)

_SEVENTH_MINOR = 10
_SEVENTH_MAJOR = 11


class Voicing:
    """Аккорды, войсинги и обращения поверх :class:`Harmony`.

    Класс-утилита без состояния: все операции — статические методы,
    принимающие :class:`Harmony` первым аргументом. Константы
    (диатонические таблицы, словарь войсингов) — атрибуты класса.
    """

    # ------------------------------------------------------------------
    # Качество аккорда (строковые константы, совпадают с нотацией)
    # ------------------------------------------------------------------

    MAJOR = "maj"
    MINOR = "min"
    DIMINISHED = "dim"
    DOMINANT = "7"
    MAJOR_SEVENTH = "maj7"
    MINOR_SEVENTH = "min7"
    HALF_DIMINISHED = "m7b5"
    UNKNOWN = "?"

    # ------------------------------------------------------------------
    # Диатонические таблицы (рассчитаны наслоением терций)
    # ------------------------------------------------------------------
    # Индекс = ступень (0-based). Движок вычисляет качество сам через
    # chord_notes(); эти таблицы — для справки, UI и тестов, не источник истины.

    DIATONIC_TRIADS: ClassVar[dict[str, tuple[str, ...]]] = {
        "major": ("maj", "min", "min", "maj", "maj", "min", "dim"),
        "dorian": ("min", "min", "maj", "maj", "min", "dim", "maj"),
        "phrygian": ("min", "maj", "maj", "min", "dim", "maj", "min"),
        "lydian": ("maj", "maj", "min", "dim", "maj", "min", "min"),
        "mixolydian": ("maj", "min", "dim", "maj", "min", "min", "maj"),
        "aeolian": ("min", "dim", "maj", "min", "min", "maj", "maj"),
        "locrian": ("dim", "maj", "min", "min", "maj", "maj", "min"),
        "minor": ("min", "dim", "maj", "min", "min", "maj", "maj"),
    }

    DIATONIC_SEVENTHS: ClassVar[dict[str, tuple[str, ...]]] = {
        "major": ("maj7", "min7", "min7", "maj7", "7", "min7", "m7b5"),
        "dorian": ("min7", "min7", "maj7", "7", "min7", "m7b5", "maj7"),
        "phrygian": ("min7", "maj7", "7", "min7", "m7b5", "maj7", "min7"),
        "lydian": ("maj7", "7", "min7", "m7b5", "maj7", "min7", "min7"),
        "mixolydian": ("7", "min7", "m7b5", "maj7", "min7", "min7", "maj7"),
        "aeolian": ("min7", "m7b5", "maj7", "min7", "min7", "maj7", "7"),
        "locrian": ("m7b5", "maj7", "min7", "min7", "maj7", "7", "min7"),
        "minor": ("min7", "m7b5", "maj7", "min7", "min7", "maj7", "7"),
    }

    # Лады, пригодные для гармонии (семиступенные, дающие min/maj/dim).
    HARMONIC_SCALES: frozenset[str] = frozenset(DIATONIC_TRIADS.keys())

    # ------------------------------------------------------------------
    # Войсинги: аккорд как позиции ступеней (0-based смещения)
    # ------------------------------------------------------------------

    VOICINGS: ClassVar[dict[str, tuple[int, ...]]] = {
        "1": (0,),
        "1-3-5": (0, 2, 4),
        "1-5": (0, 4),
        "1-3-5-7": (0, 2, 4, 6),
        "1-3-5-7-9": (0, 2, 4, 6, 8),
        "1-4-7": (0, 3, 6),
        # вариации
        "1-3-9": (0, 2, 8),
        "1-5-9": (0, 4, 8),
        "1-3-7": (0, 2, 6),
        "1-4-5": (0, 3, 4),
    }

    # ------------------------------------------------------------------
    # Доступ к словарю voicing'ов
    # ------------------------------------------------------------------

    @staticmethod
    def offsets(voicing: str) -> tuple[int, ...]:
        """Смещения ступеней для имени voicing'а — единственная точка чтения словаря.

        Одно место вместо ``VOICINGS[name]``: неизвестное имя даёт ``HarmonyError``,
        а не ``KeyError``. Пустая строка (``""``) — легальное значение профилей
        ``cc_only``, но не voicing: она тоже отвергается здесь, потому что аккордов
        у такой дорожки нет и математика аккордов к ней не применима.

        Аргументы:
            voicing: Имя из :attr:`VOICINGS`.

        Raises:
            HarmonyError: Если имени нет в словаре (включая ``""``).
        """
        try:
            return Voicing.VOICINGS[voicing]
        except KeyError:
            raise HarmonyError(f"Неизвестный voicing: {voicing!r}") from None

    # ------------------------------------------------------------------
    # Конверсия 1-based -> 0-based
    # ------------------------------------------------------------------

    @staticmethod
    def to_offsets(positions_1based: tuple[int, ...]) -> tuple[int, ...]:
        """Конвертировать 1-based позиции ступеней в 0-based индексы.

        Одно место — чтобы «1-3-5» не превратилось молча в ``(1,3,5)``
        (другой аккорд). Покрыта тестом.
        """
        return tuple(p - 1 for p in positions_1based)

    # ------------------------------------------------------------------
    # Обращения
    # ------------------------------------------------------------------

    @staticmethod
    def invert(degrees: tuple[int, ...], k: int, scale_len: int = 7) -> tuple[int, ...]:
        """Повернуть аккорд на k шагов влево, завернувшиеся поднять на октаву.

        Обращение — тот же аккорд, но нижняя нота другая. В ступенях это
        поворот кортежа влево с добавлением ``scale_len`` (октава в
        семиступенном ладу) к элементам, переехавшим из начала в конец.

        Работает для любого войсинга, включая ``(1-3-5-7-9)`` и квартовый
        ``(1-4-7)``, — опирается только на длину лада, не на структуру аккорда.

        Примечание: в плане v5_4 (раздел 1.3) формула содержит опечатку
        (``i < k``) — она даёт неверный аккорд. Правильно поднимать
        **последние** k позиций повёрнутого кортежа (``i >= len - k``).
        """
        k = k % len(degrees)
        rotated = degrees[k:] + degrees[:k]
        return tuple(
            d + (scale_len if i >= len(degrees) - k else 0)
            for i, d in enumerate(rotated)
        )

    # ------------------------------------------------------------------
    # Построение аккордов поверх Harmony
    # ------------------------------------------------------------------

    @staticmethod
    def chord_degrees(
        harmony: Harmony, degree: int, kind: str = "triad"
    ) -> tuple[int, ...]:
        """Ступени аккорда от данной ступени, не ноты.

        ``kind="triad"`` даёт ``(d, d+2, d+4)``, ``kind="7"`` —
        ``(d, d+2, d+4, d+6)``. Качество выводится из лада автоматически.
        """
        stack = Voicing._stack_size(kind)
        return tuple(degree + 2 * k for k in range(stack))

    @staticmethod
    def chord_notes(
        harmony: Harmony, degree: int, kind: str = "triad", octave: int = 5
    ) -> tuple[int, ...]:
        """Абсолютные MIDI-номера аккорда от данной ступени."""
        return tuple(
            harmony.degree_to_note(d, octave)
            for d in Voicing.chord_degrees(harmony, degree, kind)
        )

    @staticmethod
    def voicing_degrees(harmony: Harmony, degree: int, voicing: str) -> tuple[int, ...]:
        """Ступени аккорда по имени войсинга (например, ``"1-3-5-7"``)."""
        offsets = Voicing.offsets(voicing)
        return tuple(degree + off for off in offsets)

    @staticmethod
    def voicing_notes(
        harmony: Harmony, degree: int, voicing: str, octave: int = 5
    ) -> tuple[int, ...]:
        """Абсолютные MIDI-номера аккорда по имени войсинга."""
        return tuple(
            harmony.degree_to_note(d, octave)
            for d in Voicing.voicing_degrees(harmony, degree, voicing)
        )

    @staticmethod
    def triad_quality(harmony: Harmony, degree: int) -> str:
        """Качество триады на данной ступени (вычисляется из лада)."""
        notes = Voicing.chord_notes(harmony, degree, "triad")
        return Voicing._quality_from_intervals(notes, seventh=False)

    @staticmethod
    def seventh_quality(harmony: Harmony, degree: int) -> str:
        """Качество септаккорда на данной ступени (вычисляется из лада)."""
        notes = Voicing.chord_notes(harmony, degree, "7")
        return Voicing._quality_from_intervals(notes, seventh=True)

    # ------------------------------------------------------------------
    # Внутренние хелперы
    # ------------------------------------------------------------------

    @staticmethod
    def _stack_size(kind: str) -> int:
        if kind in ("triad", "3"):
            return 3
        if kind in ("7", "seventh"):
            return 4
        raise HarmonyError(f"Неизвестный тип аккорда: {kind!r}")

    @staticmethod
    def _quality_from_intervals(notes: tuple[int, ...], seventh: bool) -> str:
        root = notes[0]
        third = notes[1] - root
        fifth = notes[2] - root
        if seventh:
            return Voicing._seventh_quality(third, fifth, notes[3] - root)
        return Voicing._triad_quality(third, fifth)

    @staticmethod
    def _triad_quality(third: int, fifth: int) -> str:
        if third == THIRD_MINOR and fifth == FIFTH_PERFECT:
            return Voicing.MINOR
        if third == THIRD_MAJOR and fifth == FIFTH_PERFECT:
            return Voicing.MAJOR
        if third == THIRD_MINOR and fifth == FIFTH_DIMINISHED:
            return Voicing.DIMINISHED
        return Voicing.UNKNOWN

    @staticmethod
    def _seventh_quality(third: int, fifth: int, seventh: int) -> str:
        triad = Voicing._triad_quality(third, fifth)
        if triad == Voicing.MAJOR and seventh == _SEVENTH_MAJOR:
            return Voicing.MAJOR_SEVENTH
        if triad == Voicing.MAJOR and seventh == _SEVENTH_MINOR:
            return Voicing.DOMINANT
        if triad == Voicing.MINOR and seventh == _SEVENTH_MINOR:
            return Voicing.MINOR_SEVENTH
        if triad == Voicing.DIMINISHED and seventh == _SEVENTH_MINOR:
            return Voicing.HALF_DIMINISHED
        return Voicing.UNKNOWN
