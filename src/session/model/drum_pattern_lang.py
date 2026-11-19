"""Компилятор строки-нотации drum-паттерна в ячейки lane-сетки (0/1/2).

Грамматика v1 (design.md §2):

    notation  := cells | euclid
    cells     := cell*
    cell      := "x" | "X" | "." | "~"
    euclid    := "(" pulses "," segs [ "," offset ] ")"

- ``x`` = норма (1), ``X`` = акцент (2), ``.`` и ``~`` = выкл (0);
- пробелы и ``|`` игнорируются (визуальная группировка);
- нотация — либо литеральные ячейки, либо ровно одна евклид-группа;
  смесь литералов с евклидом запрещена;
- евклид-группа ``(p,s)`` — ``p`` ударов на весь бар: сетка делится на
  ``s`` равных сегментов, удар ставится на старт активного сегмента;
  какие из ``s`` сегментов активны — bjorklund-паттерн ``base`` через
  :class:`PEuclideanCached` (тот же слой, без дублирования алгоритма
  Бьорклунда); позиция сегмента ``i`` на сетке — ``(i * steps) // s``
  (floor; коллизий нет при ``s <= steps``);
- ``offset`` — сдвиг вправо по времени (roll) к номерам сегментов ДО
  растягивания: ячейка сегмента ``i`` = ``base[(i - offset) % s]``;
- литеральная нотация длиннее сетки — ошибка, короче — паддинг нулями;
  пустая нотация — все нули (очистка lane'а).

Операторы вероятности ``?`` и альтернативы ``a|b`` в v1 не входят
(осознанный non-goal, design.md §3). Слой ``session.model``: вверх
(repl/app) ничего не импортирует.
"""

from __future__ import annotations

from src.session.model.euclidean import PEuclideanCached

# Ячейки-литералы: символ → значение ячейки.
_CELL_VALUES: dict[str, int] = {"x": 1, "X": 2, ".": 0, "~": 0}

# Символы, игнорируемые как визуальная группировка.
_SEPARATORS: str = " \t|"


class DrumPatternCompiler:
    """Компилятор нотации паттерна lane'а в список ячеек 0/1/2."""

    @staticmethod
    def compile(pattern: str, steps: int) -> list[int]:
        """Разобрать строку-нотацию в ячейки lane-сетки.

        Аргументы:
            pattern: Нотация — литеральные ячейки либо одна евклид-группа
                (разделители игнорируются). Пустая/из одних разделителей —
                все нули.
            steps: Размер сетки дорожки (16/32/48/64).

        Returns:
            Список из ровно ``steps`` ячеек (0/1/2).

        Raises:
            ValueError: Некорректная нотация — неожиданный символ
                (с позицией), незакрытая группа, нецелый или недопустимый
                параметр евклида, смесь литералов с евклид-группой,
                ``s`` больше сетки, литеральная нотация длиннее сетки.
        """
        if steps < 1:
            raise ValueError(f"steps должно быть >= 1, got {steps}")
        cells = DrumPatternCompiler._parse(pattern, steps)
        if len(cells) > steps:
            raise ValueError(
                f"нотация длиннее сетки: {len(cells)} ячеек при steps={steps}"
            )
        cells.extend(0 for _ in range(steps - len(cells)))
        return cells

    # ------------------------------------------------------------------
    # Разбор
    # ------------------------------------------------------------------

    @staticmethod
    def _mixture_message(char: str, pos: int) -> str:
        """Текст ошибки запрещённой смеси литералов и евклид-группы."""
        return (
            "смесь литеральных ячеек и евклид-группы запрещена: "
            "евклид-группа должна быть единственным элементом нотации "
            f"(символ {char!r} в позиции {pos})"
        )

    @staticmethod
    def _parse(pattern: str, steps: int) -> list[int]:
        """Нисходящий разбор нотации (без регулярки на всю строку).

        Нотация — либо литеральные ячейки, либо ровно одна евклид-группа
        (design §2): смесь запрещена. Евклид-группа разворачивается сразу
        на всю сетку, поэтому для неё результат уже длины ``steps``.
        """
        cells: list[int] = []
        euclid_cells: list[int] | None = None
        i = 0
        n = len(pattern)
        while i < n:
            char = pattern[i]
            if char in _SEPARATORS:
                i += 1
                continue
            if euclid_cells is not None:
                # После евклид-группы допустимы только разделители.
                raise ValueError(DrumPatternCompiler._mixture_message(char, i))
            if char in _CELL_VALUES:
                cells.append(_CELL_VALUES[char])
                i += 1
                continue
            if char == "(":
                if cells:
                    raise ValueError(DrumPatternCompiler._mixture_message(char, i))
                euclid_cells, i = DrumPatternCompiler._parse_euclid(pattern, i, steps)
                continue
            raise ValueError(f"неожиданный символ {char!r} в позиции {i}")
        return euclid_cells if euclid_cells is not None else cells

    @staticmethod
    def _parse_euclid(pattern: str, start: int, steps: int) -> tuple[list[int], int]:
        """Разобрать евклид-группу и развернуть её на всю сетку.

        Аргументы:
            pattern: Вся нотация.
            start: Позиция открывающей скобки.
            steps: Размер сетки дорожки.

        Returns:
            Пара (ячейки сетки длины ``steps``, позиция после закрывающей
            скобки).

        Raises:
            ValueError: Незакрытая скобка, нецелые параметры, ``p > s``,
                ``s > steps``, отрицательные значения, ``offset`` вне
                ``0..s-1``.
        """
        end = pattern.find(")", start)
        if end == -1:
            raise ValueError(f"незакрытая группа '(' в позиции {start}")
        inner = pattern[start + 1 : end]
        parts = [part.strip() for part in inner.split(",")]
        if len(parts) not in (2, 3):
            raise ValueError(
                f"евклид-группа в позиции {start}: ожидается (p,s) или "
                f"(p,s,offset), получено {len(parts)} параметр(ов)"
            )
        numbers: list[int] = []
        for index, part in enumerate(parts):
            try:
                numbers.append(int(part))
            except ValueError:
                raise ValueError(
                    f"евклид-группа в позиции {start}: параметр {index + 1} "
                    f"{part!r} — не целое число"
                ) from None
        pulses, group_steps = numbers[0], numbers[1]
        offset = numbers[2] if len(numbers) == 3 else 0
        if group_steps < 1:
            raise ValueError(
                f"евклид-группа в позиции {start}: steps должно быть >= 1, "
                f"got {group_steps}"
            )
        if group_steps > steps:
            raise ValueError(
                f"евклид-группа в позиции {start}: сегментов ({group_steps}) "
                f"больше, чем шагов сетки ({steps})"
            )
        if not 0 <= pulses <= group_steps:
            raise ValueError(
                f"евклид-группа в позиции {start}: pulses ({pulses}) "
                f"вне диапазона 0..{group_steps}"
            )
        if not 0 <= offset < group_steps:
            raise ValueError(
                f"евклид-группа в позиции {start}: offset ({offset}) "
                f"вне диапазона 0..{group_steps - 1}"
            )
        base = PEuclideanCached(steps=group_steps, pulses=pulses).pattern
        # ``(p,s)`` — p ударов на весь бар: сетка делится на s равных
        # сегментов, удар — на старте активного сегмента. Ролл offset
        # сдвигает номера сегментов ДО растягивания: ячейка сегмента i
        # = base[(i - offset) % s]; позиция сегмента i на сетке —
        # (i * steps) // s (floor; коллизий нет при s <= steps).
        cells = [0] * steps
        for segment in range(group_steps):
            cells[(segment * steps) // group_steps] = base[
                (segment - offset) % group_steps
            ]
        return cells, end + 1
