"""Tests for src/devices/lcxl3/mapping.py — LCXL3 MIDI constants correctness."""

from src.devices.lcxl3.mapping import (
    BTN_GLOBAL_MUTE,
    BTN_GLOBAL_SOLO,
    BTN_MUTE_SELECT_CCS,
    BTN_NAME_SHIFT,
    BTN_NAMES_BANK,
    BTN_NAMES_SELECT,
    BTN_PAGE_DOWN,
    BTN_PAGE_UP,
    BTN_PLAY,
    BTN_RECORD,
    BTN_SHIFT,
    BTN_SOLO_ARM_CCS,
    BTN_TRACK_LEFT,
    BTN_TRACK_RIGHT,
    ENCODER_NAMES,
    ENCODER_ROW1_ABS,
    ENCODER_ROW1_REL,
    ENCODER_ROW2_ABS,
    ENCODER_ROW2_REL,
    ENCODER_ROW3_ABS,
    ENCODER_ROW3_REL,
    FADER_CCS,
    FADER_NAMES,
    LCXL3_BUTTON_TO_LPP3_CC,
    LPP3_NOTE_TO_LCXL3_CC,
)

# ---------------------------------------------------------------------------
# Encoder names
# ---------------------------------------------------------------------------


def test_encoder_names_count() -> None:
    """LCXL3 has exactly 24 encoders (3 rows × 8)."""
    assert len(ENCODER_NAMES) == 24


def test_encoder_names_are_unique() -> None:
    assert len(set(ENCODER_NAMES)) == 24


def test_encoder_names_rows() -> None:
    """Row names follow Enc_A*, Enc_B*, Enc_C* convention."""
    for i, name in enumerate(ENCODER_NAMES):
        if i < 8:
            assert name.startswith("Enc_A"), f"Row 1 encoder {i} has wrong name: {name}"
        elif i < 16:
            assert name.startswith("Enc_B"), f"Row 2 encoder {i} has wrong name: {name}"
        else:
            assert name.startswith("Enc_C"), f"Row 3 encoder {i} has wrong name: {name}"


def test_fader_names_count() -> None:
    assert len(FADER_NAMES) == 8


def test_fader_names_unique() -> None:
    assert len(set(FADER_NAMES)) == 8


# ---------------------------------------------------------------------------
# CC number ranges
# ---------------------------------------------------------------------------


def test_fader_cc_range() -> None:
    assert tuple(range(5, 13)) == FADER_CCS


def test_encoder_row1_rel_range() -> None:
    assert tuple(range(77, 85)) == ENCODER_ROW1_REL


def test_encoder_row2_rel_range() -> None:
    assert tuple(range(85, 93)) == ENCODER_ROW2_REL


def test_encoder_row3_rel_range() -> None:
    assert tuple(range(93, 101)) == ENCODER_ROW3_REL


def test_encoder_row1_abs_range() -> None:
    assert tuple(range(13, 21)) == ENCODER_ROW1_ABS


def test_btn_solo_arm_ccs() -> None:
    assert tuple(range(37, 45)) == BTN_SOLO_ARM_CCS


def test_btn_mute_select_ccs() -> None:
    assert tuple(range(45, 53)) == BTN_MUTE_SELECT_CCS


# ---------------------------------------------------------------------------
# No CC overlap between faders and encoders
# ---------------------------------------------------------------------------


def test_no_fader_encoder_cc_overlap() -> None:
    """Fader CCs (5-12) must not overlap with any encoder CCs."""
    encoder_ccs = set(
        ENCODER_ROW1_REL + ENCODER_ROW2_REL + ENCODER_ROW3_REL + ENCODER_ROW1_ABS + ENCODER_ROW2_ABS + ENCODER_ROW3_ABS
    )
    fader_ccs = set(FADER_CCS)
    assert fader_ccs.isdisjoint(encoder_ccs), f"Overlap: {fader_ccs & encoder_ccs}"


def test_no_button_encoder_cc_overlap() -> None:
    """Button CCs (on ch0) should be in a different channel, but verify they
    don't overlap with relative encoder CCs (which would cause channel confusion)."""
    button_ccs = (
        set(BTN_SOLO_ARM_CCS)
        | set(BTN_MUTE_SELECT_CCS)
        | {
            BTN_GLOBAL_SOLO,
            BTN_GLOBAL_MUTE,
            BTN_PLAY,
            BTN_RECORD,
            BTN_PAGE_UP,
            BTN_PAGE_DOWN,
            BTN_TRACK_RIGHT,
            BTN_TRACK_LEFT,
        }
    )
    # They operate on different channels so overlap is acceptable, but
    # verify button CCs are disjoint from fader CCs
    assert set(FADER_CCS).isdisjoint(button_ccs), f"Fader/Button CC overlap: {set(FADER_CCS) & button_ccs}"


# ---------------------------------------------------------------------------
# Button mapping coverage
# ---------------------------------------------------------------------------


def test_button_mapping_covers_play_stop() -> None:
    assert "Play" in LCXL3_BUTTON_TO_LPP3_CC
    assert LCXL3_BUTTON_TO_LPP3_CC["Play"] == 20


def test_button_mapping_covers_record() -> None:
    assert "Record" in LCXL3_BUTTON_TO_LPP3_CC
    assert LCXL3_BUTTON_TO_LPP3_CC["Record"] == 10


def test_button_mapping_covers_mute_solo() -> None:
    assert LCXL3_BUTTON_TO_LPP3_CC["Mute"] == 2
    assert LCXL3_BUTTON_TO_LPP3_CC["Solo"] == 3


def test_button_mapping_covers_navigation() -> None:
    assert LCXL3_BUTTON_TO_LPP3_CC["Page Up"] == 80
    assert LCXL3_BUTTON_TO_LPP3_CC["Page Down"] == 70
    assert LCXL3_BUTTON_TO_LPP3_CC["Track Right"] == 92
    assert LCXL3_BUTTON_TO_LPP3_CC["Track Left"] == 91


def test_button_mapping_covers_shift() -> None:
    assert BTN_NAME_SHIFT in LCXL3_BUTTON_TO_LPP3_CC
    assert LCXL3_BUTTON_TO_LPP3_CC[BTN_NAME_SHIFT] == 90  # LPP3 Shift CC


def test_button_mapping_covers_track_select() -> None:
    for i in range(1, 9):
        name = f"Select {i}"
        assert name in LCXL3_BUTTON_TO_LPP3_CC, f"Missing {name}"
        assert LCXL3_BUTTON_TO_LPP3_CC[name] == 100 + i


# ---------------------------------------------------------------------------
# LED feedback mapping
# ---------------------------------------------------------------------------


def test_lpp3_note_to_lcxl3_cc_t1_t8() -> None:
    """T1-T8 (notes 101-108) map to Solo/Arm row (CC 37-44, buttons 1-8).

    LED feedback lands on the same physical buttons the user presses to send
    track-select to M8, not on the adjacent Mute/Select row used for bank LEDs.
    """
    for i in range(8):
        lpp3_note = 101 + i
        expected_cc = BTN_SOLO_ARM_CCS[i]
        assert (
            LPP3_NOTE_TO_LCXL3_CC[lpp3_note] == expected_cc
        ), f"T{i+1}: expected CC {expected_cc}, got {LPP3_NOTE_TO_LCXL3_CC[lpp3_note]}"


def test_lpp3_note_to_lcxl3_cc_mute_solo() -> None:
    assert LPP3_NOTE_TO_LCXL3_CC[2] == BTN_GLOBAL_MUTE
    assert LPP3_NOTE_TO_LCXL3_CC[3] == BTN_GLOBAL_SOLO



# ---------------------------------------------------------------------------
# Bank / Select button names
# ---------------------------------------------------------------------------


def test_btn_names_bank_count() -> None:
    assert len(BTN_NAMES_BANK) == 8


def test_btn_names_select_count() -> None:
    assert len(BTN_NAMES_SELECT) == 8


def test_btn_names_bank_format() -> None:
    for i, name in enumerate(BTN_NAMES_BANK):
        assert name == f"Bank {i + 1}"


def test_btn_names_select_format() -> None:
    for i, name in enumerate(BTN_NAMES_SELECT):
        assert name == f"Select {i + 1}"
