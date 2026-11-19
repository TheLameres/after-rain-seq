"""Tests for DrumPatternCompiler — грамматика нотации v1 (design.md §2)."""

from __future__ import annotations

import pytest

from src.session.model.drum_pattern_lang import DrumPatternCompiler


class TestLiterals:
    """Ячейки-литералы и синонимы реста."""

    def test_normal_and_rest(self) -> None:
        assert DrumPatternCompiler.compile("x...", 4) == [1, 0, 0, 0]

    def test_accent(self) -> None:
        assert DrumPatternCompiler.compile("X..x", 4) == [2, 0, 0, 1]

    def test_tilde_is_rest_synonym(self) -> None:
        assert DrumPatternCompiler.compile("x~~~", 4) == [1, 0, 0, 0]
        assert DrumPatternCompiler.compile("x...", 4) == DrumPatternCompiler.compile(
            "x~~~", 4
        )

    def test_exact_grid_length(self) -> None:
        assert DrumPatternCompiler.compile("x.x.", 4) == [1, 0, 1, 0]


class TestSeparators:
    """Пробелы и ``|`` игнорируются (визуальная группировка)."""

    def test_bars_ignored(self) -> None:
        assert DrumPatternCompiler.compile(
            "x..x|x..x|....|....", 16
        ) == DrumPatternCompiler.compile("x..xx..x....", 16)

    def test_spec_example_kick(self) -> None:
        assert DrumPatternCompiler.compile("x..x|x..x|....|....", 16) == [
            1,
            0,
            0,
            1,
            1,
            0,
            0,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ]

    def test_spaces_ignored(self) -> None:
        assert DrumPatternCompiler.compile(
            "X..x X..x X..x X..x", 16
        ) == DrumPatternCompiler.compile("X..xX..xX..xX..x", 16)

    def test_tabs_ignored(self) -> None:
        assert DrumPatternCompiler.compile("x\tx", 2) == [1, 1]


class TestEmpty:
    """Пустая нотация = очистка lane (все нули)."""

    def test_empty_string(self) -> None:
        assert DrumPatternCompiler.compile("", 16) == [0] * 16

    def test_only_separators(self) -> None:
        assert DrumPatternCompiler.compile(" | | ", 8) == [0] * 8


class TestEuclid:
    """Евклид-группы: растягивание сегментов на сетку, offset, крайние."""

    def test_three_of_eight(self) -> None:
        # (3,8)@16: активные сегменты bjorklund(3,8) = {0, 3, 6}; позиция
        # сегмента i на сетке — (i*16)//8 → удары на шагах 0, 6, 12.
        assert DrumPatternCompiler.compile("(3,8)", 16) == [
            1,
            0,
            0,
            0,
            0,
            0,
            1,
            0,
            0,
            0,
            0,
            0,
            1,
            0,
            0,
            0,
        ]

    def test_zero_pulses(self) -> None:
        assert DrumPatternCompiler.compile("(0,8)", 16) == [0] * 16

    def test_full_pulses(self) -> None:
        # (8,8)@16 — восьмые: 8 сегментов на 16 шагов → шаги 0, 2, ..., 14
        # (НЕ сплошная сетка: сплошная была бы (16,16), design §2).
        assert DrumPatternCompiler.compile("(8,8)", 16) == [1, 0] * 8

    def test_quarters(self) -> None:
        # (4,4)@16 — четверти: шаги 0, 4, 8, 12.
        assert DrumPatternCompiler.compile("(4,4)", 16) == [1, 0, 0, 0] * 4

    def test_all_segments(self) -> None:
        # (16,16)@16 — сегмент на каждый шаг: сплошная сетка [1]*16.
        assert DrumPatternCompiler.compile("(16,16)", 16) == [1] * 16

    def test_uneven_division(self) -> None:
        # (5,5)@16: позиции (i*16)//5 → шаги 0, 3, 6, 9, 12.
        assert DrumPatternCompiler.compile("(5,5)", 16) == [
            1,
            0,
            0,
            1,
            0,
            0,
            1,
            0,
            0,
            1,
            0,
            0,
            1,
            0,
            0,
            0,
        ]

    def test_two_of_eight(self) -> None:
        # (2,8)@16: активные сегменты bjorklund(2,8) = {0, 4} → шаги 0 и 8.
        assert DrumPatternCompiler.compile("(2,8)", 16) == [
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ]

    def test_offset_roll_right(self) -> None:
        # (3,8,1)@16: ролл к номерам сегментов ДО растягивания → активные
        # сегменты {1, 4, 7} → удары на шагах 2, 8, 14 (design §2).
        assert DrumPatternCompiler.compile("(3,8,1)", 16) == [
            0,
            0,
            1,
            0,
            0,
            0,
            0,
            0,
            1,
            0,
            0,
            0,
            0,
            0,
            1,
            0,
        ]

    def test_offset_zero_equals_no_offset(self) -> None:
        assert DrumPatternCompiler.compile(
            "(3,8,0)", 16
        ) == DrumPatternCompiler.compile("(3,8)", 16)

    def test_spaces_inside_group(self) -> None:
        assert DrumPatternCompiler.compile("(3, 8)", 16) == DrumPatternCompiler.compile(
            "(3,8)", 16
        )

    def test_offset_negative_is_error(self) -> None:
        with pytest.raises(ValueError, match="offset"):
            DrumPatternCompiler.compile("(3,8,-1)", 16)

    def test_offset_too_large_is_error(self) -> None:
        with pytest.raises(ValueError, match="offset"):
            DrumPatternCompiler.compile("(3,8,8)", 16)

    def test_pulses_too_large_is_error(self) -> None:
        with pytest.raises(ValueError, match="pulses"):
            DrumPatternCompiler.compile("(9,8)", 16)

    def test_pulses_negative_is_error(self) -> None:
        with pytest.raises(ValueError, match="pulses"):
            DrumPatternCompiler.compile("(-1,8)", 16)

    def test_steps_zero_is_error(self) -> None:
        with pytest.raises(ValueError, match="steps"):
            DrumPatternCompiler.compile("(3,0)", 16)

    def test_segs_over_grid_is_error(self) -> None:
        # s > steps → ошибка: сегментов больше, чем шагов сетки.
        with pytest.raises(ValueError, match="больше, чем шагов сетки"):
            DrumPatternCompiler.compile("(3,32)", 16)


class TestMixture:
    """Смесь литеральных ячеек и евклид-группы запрещена (design §2)."""

    def test_literal_then_euclid_is_error(self) -> None:
        with pytest.raises(ValueError, match="евклид-группа"):
            DrumPatternCompiler.compile("x.x. (2,8)", 16)

    def test_euclid_after_bars_is_error(self) -> None:
        with pytest.raises(ValueError, match="евклид-группа"):
            DrumPatternCompiler.compile("x...|(2,4)", 8)

    def test_euclid_then_literal_is_error(self) -> None:
        with pytest.raises(ValueError, match="евклид-группа"):
            DrumPatternCompiler.compile("(2,8) x", 16)

    def test_two_groups_are_error(self) -> None:
        with pytest.raises(ValueError, match="евклид-группа"):
            DrumPatternCompiler.compile("(2,8)(2,8)", 16)


class TestLength:
    """Длина относительно сетки: длиннее — ошибка, короче — паддинг."""

    def test_longer_than_grid_is_error(self) -> None:
        with pytest.raises(ValueError, match="длиннее сетки"):
            DrumPatternCompiler.compile("x" * 20, 16)

    def test_padding_with_zeros(self) -> None:
        assert DrumPatternCompiler.compile("x...", 16) == [
            1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ]

    def test_error_message_mentions_counts(self) -> None:
        with pytest.raises(ValueError, match=r"17.*16"):
            DrumPatternCompiler.compile("x" * 17, 16)


class TestErrors:
    """Человекочитаемые ошибки с позицией символа."""

    def test_unknown_symbol_with_position(self) -> None:
        with pytest.raises(ValueError, match="неожиданный символ 'k' в позиции 2"):
            DrumPatternCompiler.compile("x.kx", 16)

    def test_unclosed_group(self) -> None:
        # "x(3,8" теперь перехватывается правилом запрета смеси; чистая
        # незакрытая группа проверяется без литералов.
        with pytest.raises(ValueError, match="незакрытая группа"):
            DrumPatternCompiler.compile("(3,8", 16)

    def test_non_integer_param(self) -> None:
        with pytest.raises(ValueError, match="не целое"):
            DrumPatternCompiler.compile("(3,a)", 16)

    def test_too_many_params(self) -> None:
        with pytest.raises(ValueError, match="параметр"):
            DrumPatternCompiler.compile("(3,8,1,2)", 16)

    def test_empty_group(self) -> None:
        with pytest.raises(ValueError, match="параметр"):
            DrumPatternCompiler.compile("(,)", 16)

    def test_invalid_steps_value_is_error(self) -> None:
        with pytest.raises(ValueError, match="steps"):
            DrumPatternCompiler.compile("x", 0)
