"""Push 2 pad note and button CC constants.

Defines the 8×8 pad grid note layout (notes 36-99) and the button/encoder
CC mappings for decoding incoming MIDI and driving button LEDs.

CC numbers are from the Ableton Push 2 MIDI & Display Interface spec
(github.com/Ableton/push-interface, раздел «MIDI Mapping» / Implementation
Chart v2.0). Проверено по спеке 02.11.2026: добавлены все кнопки,
энкодеры исправлены (был сдвиг на −1: track 1 encoder — это CC 71, не 70;
swing encoder — CC 15; browse — CC 111, не 69).

Полная карта кнопок Push 2 ( pressured = CC on 127, release = CC off 0):

**Панель транспорта и глобальные (верхняя часть корпуса)**
- ``Tap Tempo`` (CC 3, белая) — резерв
- ``Metronome`` (CC 9, белая) — резерв
- ``Tempo Encoder`` (CC 14) — глобальный BPM (все экраны);
  касание (touch = note-on nn10) → flash-строка «BPM …» на 2 с (D2-5)
- ``Swing Encoder`` (CC 15) — глобальный свинг (все экраны);
  касание (note-on nn9) → flash-строка «SWING … %»
- ``Master Encoder`` (CC 79) — резерв

**Клавиши над дисплеем (RGB)**
- ``Upper Row 1–8`` (CC 102–109) — у нас: только ``Upper Row 5`` (CC 106) —
  экран PORTS; 1–4, 6–8 — резерв (D3+), не подсвечиваются

**Клавиши под дисплеем (RGB)**
- ``Lower Row 1–8`` (CC 20–27) — выбор дорожки на странице + вход в GEN;
  при вооружённом Delete — удаление дорожки по позиции

**Сцены/длительности — правый столбец (RGB)**
- ``1/4 … 1/32t`` (CC 36–43, в спеке «scene 1–8 buttons») — резерв (D3+)

**Навигация (RGB)**
- ``Left``/``Right``/``Up``/``Down`` (CC 44–47) — страницы/курсор/вход-выход
- ``Page Left``/``Page Right`` (CC 62–63) — резерв (альтернатива Left/Right)
- ``Shift`` (CC 49) — модификатор (Shift+Delete)
- ``Select`` (CC 48) — резерв (подтверждение в wizard-ах)
- ``Note`` (CC 50) — резерв; ``Session`` (CC 51) — экран TRACKS;
  ``Layout`` (CC 31, белая) — резерв

**Треки и устройства (RGB)**
- ``Add Device`` (CC 52) — резерв
- ``Add Track`` (CC 53) — wizard создания дорожки: вид (Melodic/Drum)
  → профиль melodic → route (порт: «—» или порт из снапшота)
- ``Master`` (CC 28) — резерв
- ``Stop Clip`` (CC 29) — резерв

**Питч/шкалы (RGB)**
- ``Octave Down``/``Octave Up`` (CC 54–55) — резерв
- ``Repeat`` (CC 56), ``Accent`` (CC 57) — резерв
- ``Scale`` (CC 58) — экран SCALE (корень/лад/свинг)

**Транспорт и клипы (RGB)**
- ``Play`` (CC 85) — старт/стоп транспорта
- ``Record`` (CC 86) — freeze (заморозить эволюцию)
- ``New`` (CC 87) — резерв
- ``Duplicate`` (CC 88) — резерв (было: создание pad-дорожки; перенесено на Add Track)
- ``Automate`` (CC 89), ``Fixed Length`` (CC 90) — резерв
- ``Quantize`` (CC 116), ``Double Loop`` (CC 117) — резерв
- ``Delete`` (CC 118) — вооружается; + Lower Row удаляет дорожку по позиции;
  Shift+Delete — удаление выбранной дорожки
- ``Undo`` (CC 119) — резерв

**Устройство/браузер (белые)**
- ``Setup`` (CC 30) — экран SETUP (настройки с суб-вкладками clock/midi/link)
- ``Convert`` (CC 35) — резерв
- ``Device`` (CC 110) — экран MACRO выбранной дорожки
- ``Browse`` (CC 111 — rescan портов на PORTS)
- ``Mix`` (CC 112) — резерв
- ``Clip`` (CC 113) — экран GEN выбранной дорожки

**Прочее железо**
- ``User`` (CC 59) — служебная (спека: всегда шлёт на оба порта)
- Пады: note on/off 36–99 (8×8, velocity)
- Touch strip: pitch bend (CC 1 modulation — конфигурируемо)
- Педали: CC 64/69 (конфигурируемо)
- Aftertouch: channel pressure + poly key pressure
"""

# ------------------------------------------------------------------
# Pad grid
# ------------------------------------------------------------------

PAD_NOTE_MIN = 36  # bottom-left pad
PAD_NOTE_MAX = 99  # top-right pad (36 + 8*8 - 1)

# ------------------------------------------------------------------
# button_name → CC. Полный набор кнопок из спеки (см. docstring выше).
# ------------------------------------------------------------------

PUSH2_BUTTON_NAME_TO_CC: dict[str, int] = {
    # Панель транспорта / глобальные
    "Tap Tempo": 3,
    "Metronome": 9,
    # Клавиши под дисплеем (track 1-8 buttons)
    "Lower Row 1": 20,
    "Lower Row 2": 21,
    "Lower Row 3": 22,
    "Lower Row 4": 23,
    "Lower Row 5": 24,
    "Lower Row 6": 25,
    "Lower Row 7": 26,
    "Lower Row 8": 27,
    "Master": 28,
    "Stop Clip": 29,
    # Белые кнопки устройства/браузера
    "Setup": 30,
    "Layout": 31,
    "Convert": 35,
    # Правый столбец (scene 1-8 buttons; физические подписи — длительности)
    "1/4": 36,
    "1/4t": 37,
    "1/8": 38,
    "1/8t": 39,
    "1/16": 40,
    "1/16t": 41,
    "1/32": 42,
    "1/32t": 43,
    # Навигация
    "Left": 44,
    "Right": 45,
    "Up": 46,
    "Down": 47,
    "Select": 48,
    "Shift": 49,
    "Note": 50,
    "Session": 51,
    # Треки и устройства
    "Add Device": 52,
    "Add Track": 53,
    "Octave Down": 54,
    "Octave Up": 55,
    "Repeat": 56,
    "Accent": 57,
    "Scale": 58,
    "User": 59,
    "Mute": 60,
    "Solo": 61,
    "Page Left": 62,
    "Page Right": 63,
    # Транспорт и клипы
    "Play": 85,
    "Record": 86,
    "New": 87,
    "Duplicate": 88,
    "Automate": 89,
    "Fixed Length": 90,
    # Клавиши над дисплеем (track 1-8 buttons above display)
    "Upper Row 1": 102,
    "Upper Row 2": 103,
    "Upper Row 3": 104,
    "Upper Row 4": 105,
    "Upper Row 5": 106,
    "Upper Row 6": 107,
    "Upper Row 7": 108,
    "Upper Row 8": 109,
    "Device": 110,
    "Browse": 111,
    "Mix": 112,
    "Clip": 113,
    "Quantize": 116,
    "Double Loop": 117,
    "Delete": 118,
    "Undo": 119,
}

# Reverse lookup: Push 2 CC → button name (for decoding incoming MIDI from Push 2)
PUSH2_CC_TO_BUTTON_NAME: dict[int, str] = {
    cc: name for name, cc in PUSH2_BUTTON_NAME_TO_CC.items()
}

# Encoder CC → encoder name (for decoding incoming relative CC from Push 2)
# Two's complement relative encoding: val 1-64 = positive, 65-127 = negative.
# По спеке: track 1-8 encoders = CC 71-78, master = 79, tempo = 14, swing = 15.
PUSH2_ENCODER_CC_TO_NAME: dict[int, str] = {
    14: "Tempo Encoder",
    15: "Swing Encoder",
    71: "Track1 Encoder",
    72: "Track2 Encoder",
    73: "Track3 Encoder",
    74: "Track4 Encoder",
    75: "Track5 Encoder",
    76: "Track6 Encoder",
    77: "Track7 Encoder",
    78: "Track8 Encoder",
    79: "Master Encoder",
}

# ------------------------------------------------------------------
# SysEx (bytes between F0 and F7, as mido expects)
#
# Display backlight (spec §"Display Backlight"): без этой команды кадры
# принимаются, но панель остаётся чёрной — подсветка выключена.
# Яркость кодируется 14-битным значением (LSB 7 бит + 1 старший бит),
# диапазон 0–255. Нюанс: при питании по USB железо ограничивает яркость
# до ~100, реальная подсветка ≈7% от максимума.
# ------------------------------------------------------------------

PUSH2_SYSEX_PREFIX: tuple[int, ...] = (0x00, 0x21, 0x1D, 0x01, 0x01)
PUSH2_SYSEX_DISPLAY_BACKLIGHT = 0x08


def sysex_display_brightness(brightness: int) -> tuple[int, ...]:
    """SysEx data для установки яркости подсветки дисплея (0–255)."""
    return (
        *PUSH2_SYSEX_PREFIX,
        PUSH2_SYSEX_DISPLAY_BACKLIGHT,
        brightness & 0x7F,
        (brightness >> 7) & 0x01,
    )
