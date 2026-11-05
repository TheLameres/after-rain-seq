"""Словарь ступеней: римские цифры <-> числовые ступени лада.

Числовая ступень ``0..13`` (две октавы семиступенного лада) записывается
римской цифрой ``I..XIV``: ``0 -> I``, ``3 -> IV``, ``13 -> XIV``.

    parse_degrees("I IV V I")  -> [0, 3, 4, 0]
    format_degrees([0, 3, 4])  -> "I IV V"

Ввод принимает римские цифры в любом регистре (``iv``, ``IV``) и, как запасной
вариант, числа ``0..13``. Разделители — пробелы и запятые.
"""

from __future__ import annotations

from src.harmony.harmony import HarmonyError

DEGREE_MIN = 0
DEGREE_MAX = 13  # включительно; совпадает с MelodicTrack.MAX_DEGREE - 1

_ROMAN: tuple[str, ...] = (
    "I",
    "II",
    "III",
    "IV",
    "V",
    "VI",
    "VII",
    "VIII",
    "IX",
    "X",
    "XI",
    "XII",
    "XIII",
    "XIV",
)  # индекс = ступень

DEGREE_TO_ROMAN: dict[int, str] = dict(enumerate(_ROMAN))
ROMAN_TO_DEGREE: dict[str, int] = {r: i for i, r in enumerate(_ROMAN)}


def parse_degree(token: str) -> int:
    """Распарсить одну ступень: ``"IV"`` -> 3, ``"iv"`` -> 3, ``"5"`` -> 5.

    Raises:
        HarmonyError: Неизвестный токен или ступень вне ``0..13``.
    """
    raw = token.strip()
    if not raw:
        raise HarmonyError("Пустая ступень")
    upper = raw.upper()
    if upper in ROMAN_TO_DEGREE:
        return ROMAN_TO_DEGREE[upper]
    try:
        value = int(raw)
    except ValueError:
        raise HarmonyError(
            f"Неизвестная ступень: {raw!r}. Ожидается римская цифра I..XIV "
            f"или число {DEGREE_MIN}..{DEGREE_MAX}."
        ) from None
    if not DEGREE_MIN <= value <= DEGREE_MAX:
        raise HarmonyError(f"Ступень {value} вне диапазона {DEGREE_MIN}..{DEGREE_MAX}.")
    return value


def parse_degrees(text: str) -> list[int]:
    """Распарсить прогрессию: ``"I IV V I"`` -> ``[0, 3, 4, 0]``.

    Raises:
        HarmonyError: Пустая строка или хотя бы один неверный токен.
    """
    tokens = text.replace(",", " ").split()
    if not tokens:
        raise HarmonyError("Пустая прогрессия")
    return [parse_degree(t) for t in tokens]


def format_degrees(degrees: tuple[int, ...] | list[int]) -> str:
    """Отформатировать прогрессию: ``[0, 3, 4]`` -> ``"I IV V"``.

    Ступени вне ``0..13`` выводятся числом, чтобы не потерять информацию.
    """
    return " ".join(DEGREE_TO_ROMAN.get(d, str(d)) for d in degrees)
