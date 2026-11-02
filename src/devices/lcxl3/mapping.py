"""Novation Launch Control XL 3 MIDI constants for DAW mode.

All channel values are 0-indexed (mido convention).
"""

# ── SysEx (bytes between F0 and F7, as mido expects) ─────────────────────────
SYSEX_DAW_MODE_ENTER: tuple[int, ...] = (0x00, 0x20, 0x29, 0x02, 0x15, 0x02, 0x7F)
SYSEX_DAW_MODE_EXIT: tuple[int, ...] = (0x00, 0x20, 0x29, 0x02, 0x15, 0x02, 0x00)
SYSEX_RGB_PREFIX: tuple[int, ...] = (0x00, 0x20, 0x29, 0x02, 0x15, 0x01, 0x53)

# ── MIDI channels (0-indexed mido convention) ─────────────────────────────────
CH_ANALOG_OUT = 15  # encoders + faders → host (MIDI ch16)
CH_BUTTON_OUT = 0  # buttons → host         (MIDI ch1)
CH_LED_IN = 0  # LED colours ← host     (MIDI ch1)
CH_FEATURE_SEND = 6  # feature controls ← host (MIDI ch7)

# ── Feature control CCs (sent on CH_FEATURE_SEND) ─────────────────────────────
FEAT_MODE_SELECT = 30  # 1=DAW Mixer, 2=DAW Control
FEAT_ROW1_RELATIVE = 69  # enable relative output for encoder row 1
FEAT_ROW2_RELATIVE = 72  # enable relative output for encoder row 2
FEAT_ROW3_RELATIVE = 73  # enable relative output for encoder row 3

# ── Encoder CC numbers ────────────────────────────────────────────────────────
ENCODER_ROW1_ABS: tuple[int, ...] = tuple(range(13, 21))  # 13-20
ENCODER_ROW2_ABS: tuple[int, ...] = tuple(range(21, 29))  # 21-28
ENCODER_ROW3_ABS: tuple[int, ...] = tuple(range(29, 37))  # 29-36

ENCODER_ROW1_REL: tuple[int, ...] = tuple(range(77, 85))  # 77-84
ENCODER_ROW2_REL: tuple[int, ...] = tuple(range(85, 93))  # 85-92
ENCODER_ROW3_REL: tuple[int, ...] = tuple(range(93, 101))  # 93-100

ENCODER_PIVOT = 64  # relative mode: value 64 = no movement

# All absolute encoder CCs (used for display target addressing)
ALL_ENCODER_ABS_CCS: tuple[int, ...] = (
    ENCODER_ROW1_ABS + ENCODER_ROW2_ABS + ENCODER_ROW3_ABS
)

# ── Fader CC numbers ──────────────────────────────────────────────────────────
FADER_CCS: tuple[int, ...] = tuple(range(5, 13))  # 5-12

# ── Button CC numbers (all on CH_BUTTON_OUT = ch0) ────────────────────────────
BTN_SOLO_ARM_CCS: tuple[int, ...] = tuple(range(37, 45))  # CC 37-44 -> buttons 1-8
BTN_MUTE_SELECT_CCS: tuple[int, ...] = tuple(range(45, 53))  # CC 45-52 -> buttons 9-16
BTN_GLOBAL_SOLO = 65
BTN_GLOBAL_MUTE = 66
BTN_PLAY = 116
BTN_RECORD = 118
BTN_PAGE_UP = 106
BTN_PAGE_DOWN = 107
BTN_TRACK_RIGHT = 103
BTN_TRACK_LEFT = 102
BTN_SHIFT = 63  # Shift button sends on CH_FEATURE_SEND (ch6), not CH_BUTTON_OUT

# ── Button name strings (used in on_button callbacks) ─────────────────────────
# Names for buttons 1-8 (Solo/Arm row) -- forwarded to M8
BTN_NAMES_SELECT: tuple[str, ...] = tuple(f"Select {i}" for i in range(1, 9))
# Names for buttons 9-16 (Mute/Select row) -- intercepted for bank switching
BTN_NAMES_BANK: tuple[str, ...] = tuple(f"Bank {i}" for i in range(1, 9))

BTN_NAME_SOLO = "Solo"
BTN_NAME_MUTE = "Mute"
BTN_NAME_PLAY = "Play"
BTN_NAME_RECORD = "Record"
BTN_NAME_PAGE_UP = "Page Up"
BTN_NAME_PAGE_DOWN = "Page Down"
BTN_NAME_TRACK_RIGHT = "Track Right"
BTN_NAME_TRACK_LEFT = "Track Left"
BTN_NAME_SHIFT = "Shift"

# ── Display SysEx constants ────────────────────────────────────────────────────
SYSEX_DISPLAY_CFG_PREFIX: tuple[int, ...] = (0x00, 0x20, 0x29, 0x02, 0x15, 0x04)
SYSEX_DISPLAY_TEXT_PREFIX: tuple[int, ...] = (0x00, 0x20, 0x29, 0x02, 0x15, 0x06)

TARGET_STATIONARY = 0x35  # 53 -- permanent display
ARRANGEMENT_3LINE = 0x02  # 3 fields: Title | Name | Text Value, no auto-trigger
ARRANGEMENT_CTRL = 0x64  # auto-trigger on change/touch, arrangement 4 (Name+Num)

# ── Encoder name strings (24 total) ──────────────────────────────────────────
ENCODER_NAMES: tuple[str, ...] = (
    *(f"Enc_A{i}" for i in range(1, 9)),  # Row 1, indices 0-7
    *(f"Enc_B{i}" for i in range(1, 9)),  # Row 2, indices 8-15
    *(f"Enc_C{i}" for i in range(1, 9)),  # Row 3, indices 16-23
)
FADER_NAMES: tuple[str, ...] = tuple(f"Fader{i}" for i in range(1, 9))

# ── LED values ────────────────────────────────────────────────────────────────
LED_ON = 127  # palette index -> full bright
LED_DIM = 40  # palette index -> dim (inactive bank buttons)
LED_OFF = 0  # off

# Maps LCXL3 button names -> LPP3 CC sent to M8
LCXL3_BUTTON_TO_LPP3_CC: dict[str, int] = {
    BTN_NAME_PLAY: 20,  # LPP3 left col row 2 (Play/Stop)
    BTN_NAME_RECORD: 10,  # LPP3 left col row 1 (Edit/Rec)
    BTN_NAME_MUTE: 2,  # LPP3 function row CC 2
    BTN_NAME_SOLO: 3,  # LPP3 function row CC 3
    BTN_NAME_SHIFT: 90,  # LPP3 Shift CC (matches Push 2 Shift)
    # Cursor navigation -> M8 directional controls
    BTN_NAME_PAGE_UP: 80,  # LPP3 CC 80 -> M8 Up / scroll up
    BTN_NAME_PAGE_DOWN: 70,  # LPP3 CC 70 -> M8 Down / scroll down
    BTN_NAME_TRACK_RIGHT: 92,  # LPP3 CC 92 -> M8 Right / select next track
    BTN_NAME_TRACK_LEFT: 91,  # LPP3 CC 91 -> M8 Left / select prev track
    # Track select T1-T8
    "Select 1": 101,
    "Select 2": 102,
    "Select 3": 103,
    "Select 4": 104,
    "Select 5": 105,
    "Select 6": 106,
    "Select 7": 107,
    "Select 8": 108,
}

# Maps LPP3 button notes -> LCXL3 button CC for LED feedback
# T1-T8 (LPP3 notes 101-108) -> Solo/Arm row (CC 37-44, buttons 1-8)
#   These are the same physical buttons that send "Select 1-8" to M8.
# Mute/Solo mode LEDs (notes 2, 3) -> Global buttons (CC 66, 65)
# Play/Rec LEDs (notes 20, 10) -> Play/Rec buttons (CC 116, 118)
# BTN_MUTE_SELECT_CCS (CC 45-52, buttons 9-16) are reserved for bank LEDs only.
LPP3_NOTE_TO_LCXL3_CC: dict[int, int] = {
    2: BTN_GLOBAL_MUTE,  # LPP3 Mute mode -> LCXL3 global Mute LED
    3: BTN_GLOBAL_SOLO,  # LPP3 Solo mode -> LCXL3 global Solo LED
    10: BTN_RECORD,  # LPP3 Rec LED -> LCXL3 Record button
    20: BTN_PLAY,  # LPP3 Play LED -> LCXL3 Play button
    101: BTN_SOLO_ARM_CCS[0],  # T1 -> Solo/Arm button 1
    102: BTN_SOLO_ARM_CCS[1],  # T2
    103: BTN_SOLO_ARM_CCS[2],
    104: BTN_SOLO_ARM_CCS[3],
    105: BTN_SOLO_ARM_CCS[4],
    106: BTN_SOLO_ARM_CCS[5],
    107: BTN_SOLO_ARM_CCS[6],
    108: BTN_SOLO_ARM_CCS[7],  # T8 -> Solo/Arm button 8
}
