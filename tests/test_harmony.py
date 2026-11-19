"""Tests for Harmony — Root + Scale как единая точка правды (лад, не аккорды)."""

import pytest

from src.harmony import Harmony, HarmonyError
from src.harmony.scales import resolve_scale

# ---------------------------------------------------------------------------
# Инициализация и свойства
# ---------------------------------------------------------------------------


def test_default_is_a_dorian():
    h = Harmony()
    assert h.root == "A"
    assert h.scale_name == "dorian"
    assert h.scale_length == 7


def test_properties_reflect_state():
    h = Harmony("C", "major")
    assert h.root == "C"
    assert h.scale_name == "major"
    assert h.scale_length == 7


def test_semitones_property():
    h = Harmony("A", "dorian")
    assert h.semitones == (0, 2, 3, 5, 7, 9, 10)


# ---------------------------------------------------------------------------
# Резолвинг ступеней в ноты
# ---------------------------------------------------------------------------


def test_degree_to_note_a4():
    h = Harmony("A", "dorian")
    # A4 = MIDI 69
    assert h.degree_to_note(0, octave=5) == 69


def test_degree_to_semitone_wraps_octave_for_ninth():
    h = Harmony("A", "dorian")
    # Ступень 8 в семиступенном ладу = нона = +14 полутонов от корня.
    # A(9) + 14 = 23.
    assert h.degree_to_semitone(8) == 23


def test_degree_to_note_wraps_octave_for_ninth():
    h = Harmony("A", "dorian")
    # A(69) + 14 = 83.
    assert h.degree_to_note(8, octave=5) == 83


def test_degree_to_note_c_major():
    h = Harmony("C", "major")
    assert h.degree_to_note(0, octave=5) == 60  # C4
    assert h.degree_to_note(2, octave=5) == 64  # E4
    assert h.degree_to_note(4, octave=5) == 67  # G4


# ---------------------------------------------------------------------------
# Валидация лада
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_scale", ["minorPenta", "majorPenta", "wholetone", "chromatic"]
)
def test_non_diatonic_scales_rejected(bad_scale):
    h = Harmony()
    with pytest.raises(HarmonyError):
        h.set_scale(bad_scale)


def test_unknown_scale_rejected():
    h = Harmony()
    with pytest.raises(HarmonyError):
        h.set_scale("no_such_scale")


def test_invalid_root_rejected():
    with pytest.raises(HarmonyError):
        Harmony("not_a_note", "major")


def test_rejected_scale_does_not_change_state():
    h = Harmony("A", "dorian")
    with pytest.raises(HarmonyError):
        h.set_scale("wholetone")
    assert h.scale_name == "dorian"
    assert h.root == "A"


# ---------------------------------------------------------------------------
# Таблица ладов: алиасы ionian/maj7 и резолвинг имён
# ---------------------------------------------------------------------------


def test_alias_ionian_gives_major_semitones():
    h = Harmony("C", "ionian")
    assert h.semitones == (0, 2, 4, 5, 7, 9, 11)
    assert h.scale_name == "ionian"


def test_alias_maj7_gives_mixolydian_semitones():
    h = Harmony("C", "maj7")
    assert h.semitones == (0, 2, 4, 5, 7, 9, 10)
    assert h.scale_name == "maj7"


@pytest.mark.parametrize(
    ("alias", "canonical"), [("ionian", "major"), ("maj7", "mixolydian")]
)
def test_alias_matches_canonical_resolution(alias, canonical):
    # Алиас задаёт тот же лад: полутона и резолвинг ступеней (включая
    # отрицательные и перенос октавы, сетка -7..+21) совпадают 1:1.
    base = Harmony("A", canonical)
    aliased = Harmony("A", alias)
    assert aliased.semitones == base.semitones
    for degree in range(-7, 22):
        assert aliased.degree_to_semitone(degree) == base.degree_to_semitone(degree)


def test_set_scale_accepts_aliases():
    h = Harmony()
    h.set_scale("ionian")
    assert h.semitones == (0, 2, 4, 5, 7, 9, 11)
    h.set_scale("maj7")
    assert h.semitones == (0, 2, 4, 5, 7, 9, 10)


def test_resolve_scale_unknown_name_raises():
    with pytest.raises(ValueError):
        resolve_scale("no_such_scale")


# ---------------------------------------------------------------------------
# Смена лада/корня на ходу
# ---------------------------------------------------------------------------


def test_set_scale_changes_key():
    h = Harmony("A", "dorian")
    h.set_scale("major")
    assert h.scale_name == "major"
    # C# в A major (ступень 2) vs C в A dorian
    assert h.degree_to_note(2, octave=5) == 73  # C#5


def test_set_root_keeps_scale():
    h = Harmony("A", "dorian")
    h.set_root("C")
    assert h.root == "C"
    assert h.scale_name == "dorian"
    # C dorian тоника = C4 = 60
    assert h.degree_to_note(0, octave=5) == 60


def test_set_scale_then_root_combination():
    h = Harmony("A", "dorian")
    h.set_scale("major")
    h.set_root("D")
    assert h.root == "D"
    assert h.scale_name == "major"
    # D major тоника = D4 = 62
    assert h.degree_to_note(0, octave=5) == 62
