"""Tests for Voicing — аккорды, войсинги, обращения поверх Harmony."""

import pytest

from src.harmony import Harmony, HarmonyError, Voicing

# ---------------------------------------------------------------------------
# Диатонические таблицы (сверены с фактическим расчётом по полутонам)
# ---------------------------------------------------------------------------

EXPECTED_TRIADS = {
    "major": ("maj", "min", "min", "maj", "maj", "min", "dim"),
    "dorian": ("min", "min", "maj", "maj", "min", "dim", "maj"),
    "aeolian": ("min", "dim", "maj", "min", "min", "maj", "maj"),
    "phrygian": ("min", "maj", "maj", "min", "dim", "maj", "min"),
    "mixolydian": ("maj", "min", "dim", "maj", "min", "min", "maj"),
    "lydian": ("maj", "maj", "min", "dim", "maj", "min", "min"),
    "locrian": ("dim", "maj", "min", "min", "maj", "maj", "min"),
    "minor": ("min", "dim", "maj", "min", "min", "maj", "maj"),
}

EXPECTED_SEVENTHS = {
    "major": ("maj7", "min7", "min7", "maj7", "7", "min7", "m7b5"),
    "dorian": ("min7", "min7", "maj7", "7", "min7", "m7b5", "maj7"),
    "aeolian": ("min7", "m7b5", "maj7", "min7", "min7", "maj7", "7"),
    "phrygian": ("min7", "maj7", "7", "min7", "m7b5", "maj7", "min7"),
    "mixolydian": ("7", "min7", "m7b5", "maj7", "min7", "min7", "maj7"),
    "lydian": ("maj7", "7", "min7", "m7b5", "maj7", "min7", "min7"),
    "locrian": ("m7b5", "maj7", "min7", "min7", "maj7", "7", "min7"),
    "minor": ("min7", "m7b5", "maj7", "min7", "min7", "maj7", "7"),
}


def test_diatonic_triads_tables_match_plan():
    for scale, expected in EXPECTED_TRIADS.items():
        assert Voicing.DIATONIC_TRIADS[scale] == expected, f"{scale}"


def test_diatonic_sevenths_tables_match_plan():
    for scale, expected in EXPECTED_SEVENTHS.items():
        assert Voicing.DIATONIC_SEVENTHS[scale] == expected, f"{scale}"


def test_harmonic_scales_covers_eight_diatonic():
    assert Voicing.HARMONIC_SCALES == frozenset(EXPECTED_TRIADS.keys())
    assert len(Voicing.HARMONIC_SCALES) == 8


# ---------------------------------------------------------------------------
# chord_degrees — ступени, не ноты
# ---------------------------------------------------------------------------


def test_chord_degrees_triad():
    h = Harmony("A", "dorian")
    assert Voicing.chord_degrees(h, 0) == (0, 2, 4)
    assert Voicing.chord_degrees(h, 3) == (3, 5, 7)


def test_chord_degrees_seventh():
    h = Harmony("A", "dorian")
    assert Voicing.chord_degrees(h, 0, "7") == (0, 2, 4, 6)
    assert Voicing.chord_degrees(h, 2, "7") == (2, 4, 6, 8)


def test_chord_degrees_unknown_kind_raises():
    h = Harmony()
    with pytest.raises(HarmonyError):
        Voicing.chord_degrees(h, 0, "ninth")


# ---------------------------------------------------------------------------
# chord_notes — абсолютные MIDI-номера
# ---------------------------------------------------------------------------


def test_chord_notes_a_dorian_tonic():
    h = Harmony("A", "dorian")
    # Am = A(69) C(72) E(76)
    assert Voicing.chord_notes(h, 0, octave=5) == (69, 72, 76)


def test_chord_notes_a_dorian_seventh():
    h = Harmony("A", "dorian")
    # Am7 = A(69) C(72) E(76) G(79)
    assert Voicing.chord_notes(h, 0, "7", octave=5) == (69, 72, 76, 79)


def test_chord_notes_c_major_tonic():
    h = Harmony("C", "major")
    # C = C(60) E(64) G(67)
    assert Voicing.chord_notes(h, 0, octave=5) == (60, 64, 67)


# ---------------------------------------------------------------------------
# Качество аккордов выводится из лада (ключевая идея)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scale,expected", list(EXPECTED_TRIADS.items()))
def test_triad_quality_matches_table(scale, expected):
    h = Harmony("A", scale)
    for degree in range(7):
        assert Voicing.triad_quality(h, degree) == expected[degree], (
            f"{scale} ступень {degree}: {Voicing.triad_quality(h, degree)} != {expected[degree]}"
        )


@pytest.mark.parametrize("scale,expected", list(EXPECTED_SEVENTHS.items()))
def test_seventh_quality_matches_table(scale, expected):
    h = Harmony("A", scale)
    for degree in range(7):
        assert Voicing.seventh_quality(h, degree) == expected[degree], (
            f"{scale} ступень {degree}: {Voicing.seventh_quality(h, degree)} != {expected[degree]}"
        )


def test_same_degree_different_scale_changes_quality():
    """Один паттерн, разный лад — разная гармония."""
    triads = {}
    for scale in ("major", "dorian", "aeolian", "phrygian", "mixolydian"):
        h = Harmony("A", scale)
        triads[scale] = Voicing.triad_quality(h, 0)
    # I ступень: major/mixolydian -> maj; dorian/aeolian/phrygian -> min
    assert triads["major"] == "maj"
    assert triads["mixolydian"] == "maj"
    assert triads["dorian"] == "min"
    assert triads["aeolian"] == "min"
    assert triads["phrygian"] == "min"


def test_dorian_iv_is_dominant_not_minor():
    """Исправление из плана: в дорийском IV = D7 (доминантсепт), не Dm7."""
    h = Harmony("A", "dorian")
    assert Voicing.seventh_quality(h, 3) == Voicing.DOMINANT


# ---------------------------------------------------------------------------
# to_offsets — 1-based -> 0-based (главная ловушка)
# ---------------------------------------------------------------------------


def test_to_offsets_basic():
    assert Voicing.to_offsets((1, 3, 5)) == (0, 2, 4)
    assert Voicing.to_offsets((1, 5)) == (0, 4)
    assert Voicing.to_offsets((1, 3, 5, 7)) == (0, 2, 4, 6)
    assert Voicing.to_offsets((1, 3, 5, 7, 9)) == (0, 2, 4, 6, 8)
    assert Voicing.to_offsets((1, 4, 7)) == (0, 3, 6)


def test_voicings_table_is_0based():
    """VOICINGS хранит уже 0-based смещения (после to_offsets)."""
    assert Voicing.VOICINGS["1-3-5"] == (0, 2, 4)
    assert Voicing.VOICINGS["1-5"] == (0, 4)
    assert Voicing.VOICINGS["1-3-5-7"] == (0, 2, 4, 6)
    assert Voicing.VOICINGS["1-3-5-7-9"] == (0, 2, 4, 6, 8)
    assert Voicing.VOICINGS["1-4-7"] == (0, 3, 6)


# ---------------------------------------------------------------------------
# Войсинги поверх Harmony
# ---------------------------------------------------------------------------


def test_voicing_degrees():
    h = Harmony("A", "dorian")
    assert Voicing.voicing_degrees(h, 0, "1-3-5") == (0, 2, 4)
    assert Voicing.voicing_degrees(h, 0, "1-3-5-7") == (0, 2, 4, 6)
    assert Voicing.voicing_degrees(h, 3, "1-4-7") == (3, 6, 9)


def test_voicing_notes_a_dorian_tonic():
    h = Harmony("A", "dorian")
    # 1-3-5 на I ступени = Am = A(69) C(72) E(76)
    assert Voicing.voicing_notes(h, 0, "1-3-5", octave=5) == (69, 72, 76)


def test_voicing_unknown_raises():
    h = Harmony()
    with pytest.raises(HarmonyError):
        Voicing.voicing_degrees(h, 0, "no-such-voicing")


# ---------------------------------------------------------------------------
# Обращения (invert)
# ---------------------------------------------------------------------------


def test_invert_first():
    # A dorian, триада (0,2,4) = A C E -> 1-е обращение (2,4,7) = C E A
    assert Voicing.invert((0, 2, 4), 1) == (2, 4, 7)


def test_invert_second():
    # -> 2-е обращение (4,7,9) = E A C
    assert Voicing.invert((0, 2, 4), 2) == (4, 7, 9)


def test_invert_zero_is_identity():
    assert Voicing.invert((0, 2, 4), 0) == (0, 2, 4)


def test_invert_wraps_by_length():
    # k больше длины — по модулю
    assert Voicing.invert((0, 2, 4), 3) == (0, 2, 4)
    assert Voicing.invert((0, 2, 4), 4) == (2, 4, 7)


def test_invert_seventh_chord():
    # (0,2,4,6) -> 1-е обращение (2,4,6,7)
    assert Voicing.invert((0, 2, 4, 6), 1) == (2, 4, 6, 7)


def test_invert_quartal():
    # Квартовый (1-4-7) = (0,3,6) -> 1-е обращение (3,6,7)
    assert Voicing.invert((0, 3, 6), 1) == (3, 6, 7)


def test_invert_respects_scale_len():
    # scale_len=5 (пентатоника) — перенос на 5, не 7
    assert Voicing.invert((0, 2, 4), 1, scale_len=5) == (2, 4, 5)


# ---------------------------------------------------------------------------
# Словарь voicing'ов: единая точка чтения
# ---------------------------------------------------------------------------


def test_voicings_single_note_present():
    """``"1"`` — честное имя для «одна нота»: дефолт sub/bass/lead/texture."""
    assert Voicing.VOICINGS["1"] == (0,)


def test_offsets_known_voicing():
    assert Voicing.offsets("1-3-5") == (0, 2, 4)
    assert Voicing.offsets("1") == (0,)


def test_offsets_unknown_raises_harmony_error():
    with pytest.raises(HarmonyError):
        Voicing.offsets("no-such-voicing")


def test_offsets_empty_string_raises_harmony_error():
    """``""`` — значение cc_only-профиля, а не voicing: аккордов там нет."""
    with pytest.raises(HarmonyError):
        Voicing.offsets("")


def test_voicing_degrees_rejects_empty_string():
    h = Harmony("A", "dorian")
    with pytest.raises(HarmonyError):
        Voicing.voicing_degrees(h, 0, "")


# ---------------------------------------------------------------------------
# Словарь voicing'ов: единая точка чтения
# ---------------------------------------------------------------------------


def test_voicings_single_note_present():
    """``"1"`` — честное имя для «одна нота»: дефолт sub/bass/lead/texture."""
    assert Voicing.VOICINGS["1"] == (0,)


def test_offsets_known_voicing():
    assert Voicing.offsets("1-3-5") == (0, 2, 4)
    assert Voicing.offsets("1") == (0,)


def test_offsets_unknown_raises_harmony_error():
    with pytest.raises(HarmonyError):
        Voicing.offsets("no-such-voicing")


def test_offsets_empty_string_raises_harmony_error():
    """``""`` — значение cc_only-профиля, а не voicing: аккордов там нет."""
    with pytest.raises(HarmonyError):
        Voicing.offsets("")


def test_voicing_degrees_rejects_empty_string():
    h = Harmony("A", "dorian")
    with pytest.raises(HarmonyError):
        Voicing.voicing_degrees(h, 0, "")
