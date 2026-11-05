"""Словарь ступеней: римские цифры <-> числа (src/harmony/degree_names.py)."""

from __future__ import annotations

import pytest

from src.harmony.degree_names import (
    DEGREE_TO_ROMAN,
    ROMAN_TO_DEGREE,
    format_degrees,
    parse_degree,
    parse_degrees,
)
from src.harmony.harmony import HarmonyError


class TestDictionary:
    def test_covers_full_range(self) -> None:
        assert sorted(DEGREE_TO_ROMAN) == list(range(14))

    def test_known_entries(self) -> None:
        assert DEGREE_TO_ROMAN[0] == "I"
        assert DEGREE_TO_ROMAN[3] == "IV"
        assert DEGREE_TO_ROMAN[6] == "VII"
        assert DEGREE_TO_ROMAN[7] == "VIII"
        assert DEGREE_TO_ROMAN[13] == "XIV"

    def test_roman_to_degree_is_inverse(self) -> None:
        for d, r in DEGREE_TO_ROMAN.items():
            assert ROMAN_TO_DEGREE[r] == d


class TestParseDegree:
    @pytest.mark.parametrize(
        ("token", "expected"),
        [("I", 0), ("IV", 3), ("V", 4), ("VII", 6), ("XIV", 13)],
    )
    def test_roman_upper(self, token: str, expected: int) -> None:
        assert parse_degree(token) == expected

    @pytest.mark.parametrize(("token", "expected"), [("iv", 3), ("vii", 6), ("i", 0)])
    def test_roman_lower(self, token: str, expected: int) -> None:
        assert parse_degree(token) == expected

    def test_whitespace_stripped(self) -> None:
        assert parse_degree("  IV  ") == 3

    @pytest.mark.parametrize(("token", "expected"), [("0", 0), ("7", 7), ("13", 13)])
    def test_numeric_fallback(self, token: str, expected: int) -> None:
        assert parse_degree(token) == expected

    @pytest.mark.parametrize("token", ["-1", "14", "99"])
    def test_numeric_out_of_range(self, token: str) -> None:
        with pytest.raises(HarmonyError, match="вне диапазона"):
            parse_degree(token)

    @pytest.mark.parametrize("token", ["XV", "abc", "I.V", "1.5"])
    def test_unknown_token(self, token: str) -> None:
        with pytest.raises(HarmonyError, match="Неизвестная"):
            parse_degree(token)

    def test_empty_token(self) -> None:
        with pytest.raises(HarmonyError):
            parse_degree("  ")


class TestParseDegrees:
    def test_progression(self) -> None:
        assert parse_degrees("I IV V I") == [0, 3, 4, 0]

    def test_lowercase_progression(self) -> None:
        assert parse_degrees("i iv v i") == [0, 3, 4, 0]

    def test_commas_as_separators(self) -> None:
        assert parse_degrees("I, IV, V") == [0, 3, 4]

    def test_mixed_roman_and_numeric(self) -> None:
        assert parse_degrees("I 7 IV 13") == [0, 7, 3, 13]

    def test_single(self) -> None:
        assert parse_degrees("V") == [4]

    @pytest.mark.parametrize("text", ["", "   ", " , "])
    def test_empty_raises(self, text: str) -> None:
        with pytest.raises(HarmonyError, match="Пустая"):
            parse_degrees(text)

    def test_bad_token_in_middle(self) -> None:
        with pytest.raises(HarmonyError):
            parse_degrees("I IV NOPE V")


class TestFormatDegrees:
    def test_roman(self) -> None:
        assert format_degrees([0, 3, 4, 0]) == "I IV V I"

    def test_high_degrees_roman(self) -> None:
        assert format_degrees([7, 13]) == "VIII XIV"

    def test_out_of_range_numeric(self) -> None:
        assert format_degrees([0, 99]) == "I 99"

    def test_empty(self) -> None:
        assert format_degrees([]) == ""

    def test_tuple_input(self) -> None:
        assert format_degrees((0, 3, 4)) == "I IV V"

    def test_roundtrip(self) -> None:
        seq = [0, 2, 4, 6, 8, 10, 12, 13]
        assert parse_degrees(format_degrees(seq)) == seq
