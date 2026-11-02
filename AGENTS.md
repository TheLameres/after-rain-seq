# Планы и задачи: Генеративный MIDI-хост для Ambient Dub Techno

> Источник: `push2_dubtechno_plan_v5_4.md` (v6.0, 8–9 недель)
> Дата разбивки: 2026-10-31

---

## План A — Инфраструктура и железо (Фазы 0–1)

**Цель:** Подготовить Raspberry Pi 5, вырезать push2-m8, получить рабочий скелет.

### Задача A1: Спайк на RPi 5 (Фаза 0) — ✅ ЗАВЕРШЕНО

- **Агент:** `coder` (системный, железо)
- **Вход:** RPi 5, Push 2, LCXL3, USB-синт
- **Выход:** 5 цифр — fps, джиттер p99, температура, CPU%, ответ «работает ли CC→DIN в DAW-режиме»
- **Шаги:**
    1. ✅ RPi OS 64-bit, `libusb-1.0-0-dev`, udev-правило (`2982:1967`)
    2. ✅ Дисплей рисует, fps-каунтер, стоимость кадра
    3. ✅ Джиттер однопоточного планировщика
    4. ✅ `vcgencmd measure_temp` + `get_throttled` под нагрузкой 10 минут
    5. ✅ **Питание:** Push 2 + LCXL3 напрямую в USB-порты RPi 5 — стабильно, активный хаб не нужен
    6. ⏳ **LCXL3 в DAW-режиме: доходят ли CC до DIN Out?** — отложено, нет USB-синтезатора
- **Результаты (31.10.2026):**

| Метрика            | Значение     | Цель   | Статус        |
|--------------------|--------------|--------|---------------|
| FPS дисплея        | **102.1**    | ≥ 25   | ✅ 4x запас   |
| Стоимость кадра    | **9.82 мс**  | —      | ✅ Инфо       |
| Джиттер p99        | **0.059 мс** | < 5 мс | ✅ Отлично    |
| Температура (макс) | **51.8°C**   | < 80°C | ✅ Запас 28°C |
| CPU% (средний)     | **24.9%**    | < 70%  | ✅ Запас 45%  |
| Throttling         | **Нет**      | Нет    | ✅            |

- **Окружение:** Ubuntu 26.04 (resolute), kernel 7.0.0-1020-raspi, Python 3.14, pyusb + libusb-1.0
- **Вывод:** RPi 5 отлично подходит для проекта. Производительность с запасом, термостабильность подтверждена.
- **Файлы:** `spikes/spike_display.py`, `spikes/spike_jitter.py`, `spikes/spike_stress.py`

### Задача A2: Вырезание push2-m8 (Фаза 1) — ✅ ЗАВЕРШЕНО

- **Агент:** `coder` (рефакторинг)
- **Вход:** форк push2-m8 (TheLameres)
- **Выход:** `--no-gui` поднимается, дисплей рисует, LCXL3 открывается
- **Шаги:**
    1. ✅ Удалить `m8/`, `translation/`, `gui/` → минус ~2 400 строк
    2. ✅ **`lcxl3/` не удалять** — перепрофилирован: убрана привязка к M8, оставлены порты и DAW-режим
    3. ✅ Заменить `App` на скелет `transport.py`
    4. ✅ Прогнать оставшиеся тесты — 264 passed
- **Что сделано:**
    - Скопированы и очищены: `midi/`, `devices/` (push2 + lcxl3), `sync/`, `app/`
    - Создан `color_palette.py` вместо `m8/color_palette.py`
    - `binding.py` и `binding_definitions.py` удалены (M8-специфичные)
    - Python обновлён с 3.9 → 3.13
    - isobar 0.2.1 добавлен в зависимости

---

## План B — Движок: клок, порты, транспорт (Фаза 2)

**Цель:** Три источника клока с переключением в рантайме, обнаружение портов, троттлинг CC.

### Задача B1: ClockManager + TickProxy — ✅ ЗАВЕРШЕНО

- **Агент:** `coder` (конкурентность, MIDI)
- **Зависимости:** A2 (скелет transport.py)
- **Выход:** `src/sync/clock_manager.py`, `tick_proxy.py`, `clock_source.py`, `clock_state.py`
- **Ключевые требования:**
    - Квантизация переключения на долю (`_pending` → применить при `current_time % 1 == 0`)
    - `all_notes_off()` **до** смены источника
    - `TickProxy`: все источники кладут тик в одну очередь; рабочий поток забирает
    - Проверка наличия пакета `link` до переключения, явная ошибка на дисплее
    - Краевые случаи: `ISOBAR_DEFAULT_MIDI_IN` пусто, транспорт не запущен, быстрое переключение туда-обратно
- **Что сделано:**
    - `ClockSource` enum (INTERNAL/MIDI/LINK), `ClockManagerConfig` frozen dataclass
    - `TickProxy`: очередь `TickEvent` (TICK/RESET/START/STOP), worker thread, drop-oldest при переполнении
    - `ClockManager`: request_source () → квантизация на долю → all_notes_off → смена → восстановление фазы
    - `_LinkClockSource`: собственная обёртка над `link.Link` с корректной остановкой (isobar-овый
      `AbletonLinkClock.run()` — `while True:` без проверки `running`)
    - `ClockState` frozen dataclass для дисплея (source, pending, bpm, link_peers, link_active, error, running,
      clock_source property)
    - Фабрика `create_clock_source()` с обработкой ошибок (Link не установлен, MIDI порт не найден)
    - Fallback на internal при ошибке переключения
    - Интеграция в `App`: `_init_clock_manager()` создаёт Timeline + TickProxy + ClockManager
    - `SyncConfig` упрощён: `enabled`, `clock_source`, `midi_clock_device`, `bpm`
    - **Legacy-код удалён**: `SyncManager`, `ClockGenerator`, `ClockReceiver`, `LinkBridge`, `SyncState` + их тесты
- **Результат:** 48 тестов (tick_proxy + clock_manager + clock_source) passed, всего 398 тестов в проекте,
  ruff/mypy/black чисто
- **Файлы:** `src/sync/clock_manager.py`, `src/sync/tick_proxy.py`, `src/sync/clock_source.py`,
  `src/sync/clock_state.py`, `tests/test_tick_proxy.py`, `tests/test_clock_manager.py`, `tests/test_clock_source.py`,
  `plans/plan_b1_clock_manager.md`

### Задача B2: Порты — обнаружение, идентификация, hot-plug — ✅ ЗАВЕРШЕНО

- **Агент:** `coder` (MIDI, системный)
- **Зависимости:** A2
- **Выход:** `ports.py` + `routing.py`
- **Ключевые требования:**
    - Обнаружение в рантайме (не блокирует старт)
    - Идентификация: метка для человека, отпечаток для кода (`match`/`serial`)
    - Неоднозначность → явная ошибка, не угадывание
    - Hot-plug: появился порт — дорожки оживают; исчез — `all_notes_off`, переход в «молчит»
    - `MidiPortOutput` — адаптер порта под isobar
- **Что сделано:**
    - `src/sync/port_state.py` — `PortStatus` enum (CONNECTED/DISCONNECTED/AMBIGUOUS/ERROR) + `PortState` frozen
      dataclass
    - `src/sync/ports.py` — `PortConfig`, `PortsConfig`, `PortEvent`, `PortManager` (обнаружение, идентификация по
      match/serial, hot-plug polling)
    - `src/sync/routing.py` — `MidiPortOutput` (адаптер под isobar с `all_notes_off`, `int()` на numpy), `PortRegistry`
      (жизненный цикл портов)
    - `src/config.py` — добавлена секция `ports:` в `AppConfig`
    - `src/app/config.py` — `LoadedConfig` теперь несёт `ports_config`
    - `src/app/application.py` — `_init_port_manager()`, `_poll_ports()` в main loop (каждые 2 сек)
    - `config.yaml` — добавлена секция `ports:` (пустые outputs/inputs по умолчанию)
- **Результат:** 40 новых тестов (24 ports + 16 routing), всего 438 тестов в проекте, ruff/mypy/black чисто на новых
  файлах
- **Файлы:** `src/sync/port_state.py`, `src/sync/ports.py`, `src/sync/routing.py`, `tests/test_ports.py`,
  `tests/test_routing.py`

### Задача B3: CC-троттлинг и маппинг — ✅ ЗАВЕРШЕНО

- **Агент:** `coder` (алгоритмы, MIDI)
- **Зависимости:** B2
- **Выход:** `throttle.py` + `cc_map.py` + `cc_map_entry.py`
- **Ключевые требования:**
    - Троттлинг 30 Hz, ключ `(порт, канал, разрешённый_CC)`
    - `flush()` для последнего значения серии
    - Логические имена → номера по порту (`filter` → 74 или 22)
    - Инверсия и диапазон (`invert: true`, `range: [20, 110]`)
    - Ошибка при загрузке конфига, если параметр не найден
- **Что сделано:**
    - `src/sync/cc_map_entry.py` — `CCMapEntry` (frozen dataclass): cc, invert, range + `transform()`
    - `src/sync/cc_map.py` — `CCMapConfig` (pydantic), `CCMap` (resolve/is_automation_enabled/known_params),
      `DEFAULT_CC_PARAMS`, `CCMapError`
    - `src/sync/throttle.py` — `CCThrottle` (30 Hz, ключ `(порт, канал, CC)`), `flush()`, `reset()`
    - `src/sync/routing.py` — `MidiPortOutput.control()` (логические имена + маппинг + троттлинг), `flush()`,
      `all_notes_off()` сбрасывает троттлер
    - `src/sync/ports.py` — `PortConfig.no_automation` флаг
    - `src/config.py` — секция `cc_map:` в `AppConfig` + `DEFAULT_CONFIG_YAML`
    - `src/app/config.py` — `LoadedConfig.cc_map_config`
    - `src/app/application.py` — `_init_port_manager()` создаёт CCMap + CCThrottle, передаёт в PortRegistry
    - `config.yaml` — добавлена секция `cc_map:` с дефолтами GM
- **Результат:** 69 новых тестов (13 cc_map_entry + 27 cc_map + 16 throttle + 12 routing + 3 ports), всего 507 тестов в
  проекте, ruff/black чисто, mypy — только пре-существующие ошибки
- **Файлы:** `src/sync/cc_map_entry.py`, `src/sync/cc_map.py`, `src/sync/throttle.py`, `src/sync/routing.py`,
  `src/sync/ports.py`, `tests/test_cc_map_entry.py`, `tests/test_cc_map.py`, `tests/test_throttle.py`,
  `plans/plan_b3_cc_throttle.md`

### Задача B4: Транспорт и свинг — ✅ ЗАВЕРШЕНО

- **Агент:** `coder` (аудио-движок)
- **Зависимости:** B1
- **Выход:** `transport.py` + `swing.py` + `transport_event.py` + `capture_output.py`
- **Ключевые требования:**
    - Два режима: IsobarClock (A) и ExternalClock (B) под одним интерфейсом
    - Свинг через длительности (не wall-clock), работает при всех трёх клоках
    - `int()` на всех значениях из isobar (`numpy.int64` → `int`)
    - `all_notes_off` по панике и при потере порта
- **Что сделано:**
    - `src/sync/swing.py` — `SwingConfig` (frozen), `swing_duration()` чистая функция, `SwingApplier` (step tracking,
      auto-reset на разрывах)
    - `src/sync/transport_event.py` — `EventKind` enum + `TransportEvent` frozen dataclass (4 вида событий, convenience
      constructors, int () конвертация)
    - `src/sync/capture_output.py` — isobar OutputDevice, перехватывает note_on/note_off/control/all_notes_off в очередь
      TransportEvent, drop-oldest при переполнении
    - `src/sync/transport.py` — `TransportMode` enum (ISOBAR/EXTERNAL), `Transport` (process_events, all_notes_off, CC
      flush на границах тактов)
    - `src/sync/config.py` — `swing_amount: float` в SyncConfig
    - `src/app/application.py` — интеграция: CaptureOutput в timeline.output_devices, Transport hook в TickProxy
      dispatch, cleanup
    - Mode B (EXTERNAL) — интерфейс заложен, реализация отложена (NotImplementedError)
    - Маршрутизация по портам — один default label, полная маршрутизация при интеграции с C3
- **Результат:** 76 новых тестов (23 swing + 12 transport_event + 20 capture_output + 21 transport), всего 583 теста в
  проекте, ruff/black чисто на новых файлах
- **Файлы:** `src/sync/swing.py`, `src/sync/transport_event.py`, `src/sync/capture_output.py`, `src/sync/transport.py`,
  `tests/test_swing.py`, `tests/test_transport_event.py`, `tests/test_capture_output.py`, `tests/test_transport.py`,
  `plans/plan_b4_transport_swing.md`

---

## План C — Гармония и музыкальная логика (Фаза 3)

**Цель:** Диатоническая гармония, войсинги, обращения, граф дорожек, drum-машина, мутация.

### Задача C1: Гармонический слой — ✅ ЗАВЕРШЕНО

- **Агент:** `coder` (музыкальная теория, Python)
- **Зависимости:** нет (чистая логика)
- **Выход:** `src/harmony/harmony.py` (лад) + `src/harmony/voicings.py` (аккорды) + тесты
- **Разделение ответственности:**
    - `harmony.py` — только Root + Scale: `set_root`/`set_scale`, валидация лада, `degree_to_note`. Про аккорды **не
      знает**.
    - `voicings.py` — аккорды поверх `Harmony`: `chord_degrees`/`chord_notes`, качество, `DIATONIC_*`, `VOICINGS`,
      `to_offsets`, `invert`. Зависит от `Harmony`, не наоборот (нет цикла).
- **Ключевые требования:**
    - `Harmony` класс: Root + Scale как единая точка правды
    - `set_scale()` с валидацией: только лады, дающие min/maj/dim
    - `chord_degrees(degree, kind)` — ступени, не ноты
    - Диатонические таблицы (триады и септаккорды для 8 ладов)
- **Что сделано:**
    - `Harmony` владеет isobar `Key`, резолвит `degree`→MIDI-ноту (октавы переносит isobar)
    - `set_root()` / `set_scale()` пересоздают `Key`; смена лада/корня на ходу безопасна
    - Валидация: пентатоника/wholetone/chromatic отклоняются (`HarmonyError`)
    - `voicings.py`: `chord_degrees` (triad/7), `chord_notes`, `triad_quality`, `seventh_quality`,
      `voicing_degrees/notes`, `to_offsets`, `invert`
    - `DIATONIC_TRIADS` / `DIATONIC_SEVENTHS` для 8 ладов, `HARMONIC_SCALES`, `ChordQuality`
    - Сверено с планом: дорийский IV = доминантсепт (не min7); все 8 ладов покрыты тестами
- **⚠️ Баг в плане v5_4 (раздел 1.3):** формула `invert()` в плане содержит опечатку `d + (scale_len if i < k else 0)` —
  она даёт неверный аккорд. Правильно: поднимать на октаву **последние** k позиций повёрнутого кортежа (`i >= len - k`).
  Реализация исправлена, покрыта тестами.
- **Результат:** 56 тестов (harmony + voicings) passed, ruff/mypy/black чисто

### Задача C2: Войсинги и обращения

- **Агент:** `coder` (музыкальная теория)
- **Зависимости:** C1
- **Выход:** `voicings.py` (или в `harmony.py`)
- **Ключевые требования:**
    - `VOICINGS` dict: `(1-3-5)`, `(1-5)`, `(1-3-5-7)`, `(1-3-5-7-9)`, `(1-4-7)`, + вариации
    - `to_offsets(positions_1based)` — одна функция, одно место, покрыта тестом
    - `invert(degrees, k, scale_len=7)` — поворот с переносом октавы
    - Валидация пары (лад, войсинг), не лад сам по себе

### Задача C3: Граф дорожек и Session API — ✅ ЗАВЕРШЕНО

- **Агент:** `coder` (графы, архитектура)
- **Зависимости:** C1, C2
- **Выход:** `src/session/` — `track.py`, `melodic_track.py`, `drum_track.py`, `melodic_profile.py`, `drum_lane.py`,
  `chord_event.py`, `track_graph.py`, `session.py`
- **Ключевые требования (с учётом track-hierarchy.md):**
    - `Track(ABC)` базовый класс, `generate()` переопределяется
    - Ровно два наследника: `MelodicTrack` (профили как данные) + `DrumTrack`
    - `MelodicProfile` frozen dataclass + реестр `PROFILES` (11 профилей)
    - `ChordEvent(beat, degrees, duration, voicing)` — публикация по рёбрам графа
    - `TrackGraph`: топологическая сортировка (Kahn), защита от циклов, откат рёбер при цикле
    - Session API: создание/удаление дорожек, сброс источника у зависимых (стратегия B), лимит 16 дорожек / 2 drum / 2
      источника
    - Drum: `sources` заблокирован, `step_to_note()` — одна функция на проект
    - Автогенерация имён: "Pad 1", "Sub 2", "Drum 1"
- **Что сделано:**
    - `src/session/` — 8 файлов, зависит только от `src/harmony/`
    - `MelodicTrack`: один `generate()` для всех профилей, ветвление на уровне данных
    - `DrumTrack`: 16 lane GM 36–51, `sources` read-only, попытка назначить → ValueError
    - `TrackGraph`: Kahn's algorithm, детекция циклов с именами дорожек
    - `Session`: автонейминг, лимиты, стратегия B (зависимые получают `sources = ()`)
    - `inject_sources()` — механизм передачи ChordEvent от источника к наследнику
- **Результат:** 41 тест passed, ruff/mypy/black чисто, всего 361 тест в проекте

### Задача C4: Drum-машина — ✅ ЗАВЕРШЕНО

- **Агент:** `coder` (MIDI, алгоритмы)
- **Зависимости:** C3
- **Выход:** `drum_event.py`, `euclidean.py`, `drum_engine.py`, `drum_config.py`
- **Ключевые требования:**
    - Одна дорожка, 16 lane, GM 36–51, свой MIDI-канал (ch10)
    - Сетка 16 шагов, общая на все lane
    - Три уровня velocity: ghost (40–55), normal (90–100), accent (120–127) — сила нажатия пада
    - `step_to_note(step)` — одна функция на весь проект
    - Мутация: 1–2 изменения за 8–16 секунд (не такты!), деградация к базовому рисунку
    - `PEuclidean` с кешем (критично при 16 lane)
- **Что сделано:**
    - `DrumEvent` — frozen dataclass: beat, note, velocity, lane_index, duration
    - `PEuclideanCached` — обёртка с кешем (алгоритм Бресенхема, не Бьорклунд — проще и надёжнее)
    - `DrumTrack.generate()` — генерация `list[DrumEvent]` по сетке, три уровня velocity, мутация с деградацией, freeze
      ()
    - `DrumEngine` — мост в транспорт: конвертация DrumEvent → TransportEvent, свинг, drop-oldest очередь
    - `DrumConfig` — pydantic-схема в config.yaml (preview_on_select, preview_velocity, mutate_min/max_seconds)
    - Интеграция в `App`: `_init_drum_engines()` + hook в TickProxy dispatch
    - `Track.generate()` — сигнатура изменена на `-> list` (возвращает события)
- **Результат:** 63 новых теста (3 drum_event + 17 euclidean + 23 drum_track + 10 drum_engine + 7 drum_config + 3
  drum_lane), всего 643 теста в проекте, ruff/black чисто на новых файлах, mypy — только пре-существующие ошибки
  (mido/isobar без stubs)
- **Файлы:** `src/session/drum_event.py`, `src/session/euclidean.py`, `src/session/drum_engine.py`,
  `src/session/drum_config.py`, `src/session/drum_track.py`, `src/session/drum_lane.py`, `src/config.py`,
  `src/app/application.py`, `tests/test_drum_event.py`, `tests/test_euclidean.py`, `tests/test_drum_track.py`,
  `tests/test_drum_engine.py`, `tests/test_drum_config.py`, `plans/plan_c4_drum_machine.md`

### Задача C5: Мутация и эволюция — ✅ ЗАВЕРШЕНО

- **Агент:** `coder` (алгоритмы, генеративная музыка)
- **Зависимости:** C3, C4
- **Выход:** `mutation.py`, `melodic_engine.py`, `mutation_config.py`
- **Ключевые требования:**
    - Непрерывный дрейф, плавающий `PEuclidean`, дрейф диапазонов `PWhite`
    - Freeze/Evolve — мгновенная заморозка одной кнопкой
    - Счётчик изменений на дисплее
- **Что сделано:**
    - `src/session/mutation.py` — MutationState, NoteDrift, FloatingEuclidean, ParamDrift, MutationEngine
    - `src/session/melodic_engine.py` — мост MelodicTrack → TransportEvent через Harmony
    - `src/session/mutation_config.py` — pydantic-схема в config.yaml
    - `MelodicTrack` — + mutate, bpm, mutation_count, freeze ()
    - `Session` — + freeze_all (), evolve_all (), total_mutation_count
    - `App` — интеграция: MutationEngine + MelodicEngine в dispatch hook
    - Мутация clock-independent: операции в beats, пересчёт через bpm
    - Три механизма по профилю: lead/texture→NoteDrift, seq/arp→FloatingEuclidean, pad/atmos/bass→ParamDrift
- **Результат:** 83 новых теста (40 mutation + 7 config + 12 melodic_engine + 24 session), всего 726 тестов в проекте,
  ruff/black чисто на новых файлах, mypy — только пре-существующие ошибки (mido/isobar без stubs)
- **Файлы:** `src/session/mutation.py`, `src/session/mutation_config.py`, `src/session/melodic_engine.py`,
  `src/session/melodic_track.py`, `src/session/session.py`, `src/config.py`, `src/app/application.py`, `config.yaml`,
  `tests/test_mutation.py`, `tests/test_mutation_config.py`, `tests/test_melodic_engine.py`, `tests/test_session.py`,
  `plans/plan_c5_mutation_evolution.md`

### Задача C6: Профили ↔ isobar-паттерны (генераторы, граф, E2E) — ✅ ЗАВЕРШЕНО

- **Агент:** `coder` (генеративная музыка, MIDI, интеграция)
- **Зависимости:** C1–C5, B1–B4
- **Выход:** генераторы нот по профилям, оживление графа аккордов, мутация слышна в звуке, E2E-доказательство MIDI
- **Ключевые требования (критерии приёмки):**
    - Ноты доставляются однократно, в свой бит (R1 — без дублирования)
    - Мутация меняет звук: NoteDrift/FloatingEuclidean/ParamDrift реально влияют на генерацию (R2)
    - Граф дорожек оживает: sub/stab/seq/arp нарезают ChordEvent источников (R3)
    - Интервалы мутации в секундах — BPM проброшен из ClockManager (R4)
    - **E2E: MIDI-сигнал доходит до dummy-программы на mido** (R5)
- **Что сделано:**
    - `src/session/note_event.py` — `NoteEvent` (ступень → MIDI резолвит движок)
    - `src/session/beat_scheduler.py` — `BeatScheduler`: lookahead-горизонт, watermark, допуск опоздания 1/16
    - `src/session/melodic_engine.py` — переписан на планировщик: `ensure/extend_horizon/due`, обход паттерна по циклам
      k (монотонные beats — иначе дёргается stateful SwingApplier), `reset()` по STOP
    - `src/session/pattern_spec.py` — `PatternSpec` + семейства `chord_source/chord_slicer/free_mono/cc_only`; у всех 11
      профилей заполнен `pattern`
    - `src/session/generators.py` — чистые генераторы: `generate_notes(ctx)`, `GenerationContext` (track +
      chord_window + механизмы мутации), `chord_degrees_for` (общая математика войсинга+обращения для графа и звука),
      `pattern_length_for`; нарезка: sub/stab/seq/arp; гейт «печётся» в длительность
    - `src/session/session.py` — `propagate_chords()`: два прохода в топо-порядке (генерация → inject_sources),
      идемпотентна; фаза в dispatch-hook App до тиков движков
    - `src/session/mutation.py` — `PROFILE_MECHANISM` (lead/texture→note; seq/arp/stab→euclidean;
      pad/atmos/bass/sub→param), `PARAM_DRIFT_PARAMS` (у sub — только register+gate; база «gate» — актуальный гейт
      дорожки)
    - Проброс BPM: `DrumEngine.set_bpm()` (заглушка `_swing_bpm` удалена), в хуке раз в целый бит `engine.set_bpm()` /
      `mutation_engine.set_bpm_all()` (источник `cm.state.bpm or sync_bpm`)
    - **Баг B2 найден и исправлен:** `PortManager.start()` отбрасывал события начального скана — порт, подключённый до
      старта App, оставался без адаптера в PortRegistry (статус «connected», тишина). Теперь `start()` возвращает
      события, App диспетчеризует их в registry
    - `spikes/spike_midi_sink.py` — dummy-приёмник (виртуальный порт mido, печать сообщений)
    - `spikes/spike_e2e_midi_sink.py` — E2E в одном процессе: sink + App (simulate) + track/route/start через
      AppEngineControl
- **E2E-проверка (R5):** PASS — pad-дорожка (A dorian, внутренний клок 120 bpm) за 5 с: 31 note_on / 27 note_off в
  приёмнике; аккорды (69/72/76) бьют однократно, шаг такта 0.498 с, без задвоений
- **Фикс «слипания» дорожек в один канал (баг-репорт пользователя):** `create_melodic_track` всегда ставил `channel=0` —
  на одном порту все дорожки маршрутизировались в один MIDI-канал. Исправлено:
    - `Session.create_melodic_track(channel=None)` — автоназначение первого свободного канала; канал 9 (ch10)
      резервируется под drum, чтобы мелодика не слипалась с ударными; исчерпание каналов → ValueError; явный канал
      валидируется 0..15
    - REPL: `track add <profile> [channel]`, новая команда `track channel <name> <ch>` (движки читают `track.channel`
      live — переключение без рестарта)
    - E2E-регрессия: pad (ch0) + bass (ch1) на одном порту — в sink каналы [0, 1], слипания нет
- **Результат:** 948 тестов passed (новые: note_event, beat_scheduler, pattern_spec, generators, chord_slicer,
  TestPropagateChords, TestProfileMechanism, TestMutationIntegration, TestGraphIntegration, TestBeatScheduling,
  drum_engine.set_bpm, test_start_returns_initial_events, авто-назначение каналов ×5, track channel ×4); ruff/black/mypy
  чисто на новых/изменённых файлах
- **Известные ограничения (техдолг):**
    - Двойное применение свинга: длительность правится и в MelodicEngine при планировании, и в
      `Transport._deliver_note_off` (общий SwingApplier дрейфует step-счётчик). На звук почти не влияет (duration в
      адаптере порта игнорируется), парность свинга между дорожками может «плыть» — вынос свинга из Transport отдельной
      задачей
    - On-demand melodic-дорожки не регистрируются в MutationEngine (документировано в F1) — играют базовый материал
    - `set_profile` на живой дорожке не пересоздаёт механизм мутации
    - Автоназначение каналов — глобально по сессии (не per-port): дорожка на другом порту всё равно получает свой
      свободный канал; пересечения каналов на разных портах допустимы MIDI, но автоназначение их не использует
- **Файлы:** `src/session/note_event.py`, `src/session/beat_scheduler.py`, `src/session/pattern_spec.py`,
  `src/session/generators.py`, `src/session/melodic_engine.py`, `src/session/mutation.py`, `src/session/session.py`,
  `src/session/melodic_track.py`, `src/session/melodic_profile.py`, `src/sync/ports.py`, `src/session/drum_engine.py`,
  `src/app/application.py`, `spikes/spike_midi_sink.py`, `spikes/spike_e2e_midi_sink.py`, `tests/test_note_event.py`,
  `tests/test_beat_scheduler.py`, `tests/test_pattern_spec.py`, `tests/test_generators.py`,
  `tests/test_chord_slicer.py`, `tests/test_melodic_engine.py`, `tests/test_mutation.py`, `tests/test_drum_engine.py`,
  `tests/test_ports.py`, `tests/test_session.py`, `plans/plan_c6_isobar_profile_engine.md`

---

## План D — UI: дисплей и пады (Фаза 4)

**Цель:** Полное управление с Push 2, 25 fps, читаемость за 0.2 с.

### Задача D1: Рендерер дисплея — ✅ ЗАВЕРШЕНО

- **Агент:** `coder` (графика, оптимизация)
- **Зависимости:** A2 (дисплей из push2-m8)
- **Выход:** `renderer.py`
- **Ключевые требования:**
    - Примитивы на numpy, dirty rects, шрифты из push2-m8
    - 25 fps с запасом (потолок 551 fps)
- **Расширенный план:** `plans/plan_d1_renderer.md` (02.11.2026)
- **Ключевые решения плана:**
    - Diff-кадров по USB нет (офиц. мануал Ableton push-interface): заголовок фиксированный, кадр отображается только
      целиком; «reserved» форматы опасны (до перепрошивки)
    - Режим отправки: по факту dirty + keepalive раз в ~1 с (дисплей double-buffered, гашение после 2 с тишины);
      постоянный поток 25 fps не нужен
    - Dirty rects — CPU-оптимизация compose/encode (widget-rects, виджет перерисовывает свой bbox)
    - GlyphCache: PIL растеризует глиф один раз, горячий цикл — numpy-blit; LRU 512
    - FrameEncoder: предвыделенные буферы, 0 аллокаций; roundtrip-тест против legacy `_encode_frame`
    - `PushDisplay` → scene composer, публичный API без изменений; `display_fps: 15 → 25`
- **Что сделано:**
    - `renderer.py`: `DirtyTracker` (merge пересекающихся и смежных rect, clamp, деградация к full при >64),
      `FrameBuffer` (пиксели (W,H) uint16 BGR565; примитивы
      `fill_rect/rect/hline/vline/blit/text/text_centered/bar/grid_cell` — каждый инвалидирует bbox), `GlyphCache` (ключ
      `(char, font_key)` — цвет НЕ в ключе, маска L→masked write; PIL растеризует разово; LRU 512), `Colors` +
      `rgb_to_bgr565/lpp3_to_bgr565/brighten565`
    - `push2_display.py`: `FrameEncoder` — предвыделенный flat-буфер, запись построчно через `(LINES, FRAME_WIDTH)`
      view, 0 аллокаций в горячем цикле; байт-в-байт равен legacy `_encode_frame` (roundtrip-тест)
    - `display.py`: `PushDisplay` переписан как scene composer — 4 виджета (tabs/tracks/global/status) со своими rect;
      `update_state` сравнивает снапшоты по виджетам и инвалидирует только изменённые; `_compose` перерисовывает только
      грязные виджеты целиком (нет следов); `render_usb` шлёт по факту dirty + keepalive 1 с (спека: гашение через 2 с);
      превью для эмулятора — конвертация 565→888 только в simulate
    - `Push2Config.display_fps` 15→25 (default + `config.yaml` + `DEFAULT_CONFIG_YAML`)
    - Зафиксирован пред-существующий баг (не тронут): `_lpp3_color_to_rgb` в старом display.py звал несуществующий
      `Color.to_rgb_tuple` — путь не использовался, в renderer используется `lpp3_to_bgr565` через поля `.r/.g/.b`
    - Отклонение от плана (задокументировано): ключ GlyphCache без цвета — перекраска бесплатна, кеш проще
- **Бенч (`spikes/spike_renderer_bench.py`, macOS; RPi — при доступе к железу):**
    - Полный compose всех виджетов: **0.39 мс** (цель ≤ 5)
    - Типичный dirty-тик (BPM + энкодер): **0.32 мс** (цель ≤ 2)
    - Encode wire payload: **0.32 мс** (цель ≤ 2)
    - Сквозной тик compose+encode: средний 0.69 мс, **p99 1.72 мс** (бюджет 40 мс @25 fps) → потолок ~580 тиков/с, узкое
      место — USB-отправка (~10 мс/кадр по спайку A1), 25 fps с огромным запасом
- **Результат:** 62 новых теста (renderer dirty 11, primitives 20, glyph 13, encoder 4, push2_display 14), всего **1012
  passed**; ruff/black чисто на новых/изменённых файлах; mypy — только пре-существующие ошибки (usb без stubs,
  legacy-переприсваивание в `_encode_frame`)
- **Файлы:** `src/devices/push2/renderer.py`, `src/devices/push2/display.py`, `src/devices/push2/push2_display.py`,
  `src/devices/push2/config.py`, `src/config.py`, `config.yaml`, `tests/test_renderer_dirty.py`,
  `tests/test_renderer_primitives.py`, `tests/test_renderer_glyph_cache.py`, `tests/test_push2_display.py`,
  `tests/test_push2_usb_display.py`, `spikes/spike_renderer_bench.py`, `plans/plan_d1_renderer.md`

### Задача D2: Экраны и навигация — ✅ ЗАВЕРШЕНО

- **Агент:** `coder` (UI/UX)
- **Зависимости:** D1, B1 (SYNC), B2 (PORTS)
- **Выход:** `screens.py`
- **Расширенный план:** `plans/plan_d2_screens.md` (02.11.2026)
- **Ключевые требования:**
    - Банк дорожек с прокруткой (8 энкодеров, Page Left/Right)
    - 5 макро-осей: DEN, MUT, SPACE, DEPTH, TONE
    - Статус: Root/Scale/BPM/порт
    - Создание дорожки одним нажатием с дефолтами
    - `SOURCE`/`SOURCE2` на экране дорожки
    - Экран `SYNC`: выбор источника клока, устройства, статус
    - Экран `PORTS`: список портов, назначение, `SCAN`
- **Что сделано:**
    - `src/app/ui/`: каркас событий/состояния (`screen_id` — 5 экранов в tab_order; `ui_event` — frozen DTO
      button/encoder; `ui_queue` — thread-safe, capacity 64, drop-oldest + warning; `ui_state` — screen/page/selected/
      flash TTL/shift/macro_cc, константы DEFAULT_FLASH_SECONDS=3.0, PAGE_SIZE=8)
    - `src/app/ui/macro_axes.py`: ось DEN (плотность в generators), MUT (mutate), TONE/SPACE/DEPTH (CC через CCMap +
      троттлер 30 Hz); валидация `ui.macro_axes` в конфиге (неизвестный параметр/ось/пустая ось → ValueError);
      `UiConfig` (pydantic) в `src/config.py` + DEFAULT_CONFIG_YAML + LoadedConfig
    - `src/app/ui/screen_controller.py`: вся навигация и команды. Табы Upper Row 1–5; Right на TRACKS → следующая
      страница → TRACK выбранной; Left с TRACK → назад; SRC/SRC2 крутятся по свободным источникам (SRC2 ≠ SRC);
      DEN только при density_applicable; E6–E8 шлют CC при наличии порта, иначе значение копится в UiState («—» в view);
      PORTS: E1 — дорожка для назначения, E2 — порт (применение сразу); Tempo/Swing Encoder глобальны; ошибки «error:»
      → flash, Shift+Delete → flash с результатом (в т.ч. сброс зависимых); константы назначений — в одном модуле
    - `src/devices/display_state.py`: view-модели (StatusBar/TrackRow/TrackDetail/Sync/PortRow/Ports/Global/ScreenView)
      — frozen DTO, строки/числа; слой devices/ не импортирует session/sync/app (снапшот спускается из app)
    - `src/devices/push2/screens.py`: чистые draw-функции на FrameBuffer (header/status-bar/hints/tracks/track/global/
      sync/ports); локальные константы цветов FLASH/FLASH_ERROR
    - `src/devices/push2/display.py`: `update_screen(view)` — смена экрана = full invalidate (reset + clear prev),
      внутри экрана diff по регионам (header/body/status, value-compare frozen DTO); legacy `update_state` сохранён
    - `src/devices/push2/push2_device.py`: `render_display` маршрутизирует screen_view → update_screen; legacy-путь без
      изменений; `set_screen_tab_leds(active_tab)` — CC 102–106 (Upper Row 1–5), активный 127 / остальные 18
    - `src/app/display.py`: `build_display_state`/`render_frame` принимают опциональный `screen_view`
    - `src/app/application.py`: UI контроллер создаётся в run() (AppEngineControl — тот же фасад, что REPL); MIDI-поток
      только кладёт UiEvent в очередь (паттерн TickProxy), drain + handle + tab-LED в main loop; `_send_cc` через
      PortRegistry (логические имена CCMap); начальный render до main loop — legacy
    - `src/repl/status.py`: TrackSummary расширен аддитивно (gate/voicing/octave/mutate/density/density_applicable/
      channel; midi_clock_device у StatusSnapshot); `src/session/generators.py`: `_density_pulses` (round(base·(0.25+
      0.75·d)), кламп 1..steps) и `_density_keep` (детерминированный хэш) — density реально меняет звук слайсеров
      (chord_slicer, free_mono); chord_source/cc_only density не применяют (view «—»)
    - `EngineControl` ABC +7 аддитивных методов (create_drum_track, set_track_sources, set_track_gate, set_track_density,
      set_track_mutate, evolve_track, set_swing); `MelodicTrack.density = 1.0`; `SwingApplier.set_amount()`
- **Дефекты, найденные E2E-spike (и исправленные):**
    - **ClockManager: pending «висел» бесконечно на работающем транспорте** — квантизация проверяла точное float-
      равенство `current_time % 1.0 == 0.0`, при 480 tpq недостижимое. Теперь допуск `_BEAT_EPSILON = 0.001`
      (полтика). Регрессия: без фикса spike-сценарий 5 зависали
    - **ClockManager: recovery из тихого внешнего клока** — MIDI без устройства/Link без пиров не шлют тики, таймлайн
      мёртв, обратное переключение квантизировать некому. Добавлен watchdog: TickProxy зовёт `on_idle` при тишине
      worker'а (~0.1 с), ClockManager применяет pending без квантизации после ~0.5 с замерзшего таймлайна
    - **ScreenController: `_clamp_cursor` обнулял курсор на экранах без курсора** (`_cursor_limit` → 0 для TRACK/
      GLOBAL/SYNC) — Right на TRACKS всегда открывала дорожку 0. Кламп только при limit > 0; курсор переживает
      смену экранов
- **E2E-проверка (`spikes/spike_ui_simulate.py`, `App(--simulate)` + on_frame превью):**
    - Сценарии 1–6 из плана §5 — **PASS**: Duplicate ×2 (TRACKS 2 дорожки, «TRACKS 1-8/1»); TRACK Stab 1
      (E4 DEN: density 1.000→0.921; E6 TONE без порта → «—» в view, значение в UiState); PORTS (E1 выбор дорожки,
      E2 назначение main → TrackSummary.port); GLOBAL (E1 root A→A#, статус-бар = Harmony); SYNC (E1 → midi, pending
      виден, квантизация на доле, возврат internal через watchdog); Shift+Delete (Pad 1 удалена, Pad 2 sources=(),
      flash «deleted track …»)
    - PNG-дампы кадров 960×160: `spikes/out/ui_1_tracks.png` … `ui_6_after_delete.png` — все экраны читаемы

### Дополнение D2: карта кнопок по спеке + Add Track wizard (02.11.2026) — ✅ ЗАВЕРШЕНО

- **Запрос:** описать все кнопки Push 2; перенести создание трека с Duplicate на Add Track; wizard выбора Melodic/Drum
  и профиля. Спека: Ableton/push-interface (AbletonPush2MIDIDisplayInterface.asc)
- **Полная карта кнопок** — `src/devices/push2/mapping.py` переписан: docstring содержит карту всех групп (транспорт,
  Upper/Lower Row, правый столбец сцен, навигация, треки, питч, клипы, белые кнопки, прочее железо: пады 36–99,
  touch strip pitch bend, педали CC 64/69, aftertouch); `PUSH2_BUTTON_NAME_TO_CC` покрывает все 56 кнопок из
  Implementation Chart v2.0
- **⚠️ Найденные баги маппинга (были сдвинуты на реальном железе):** карта энкодеров была смещена на −1 — track 1–8
  = CC 71–78 (было 70–77); swing-энкодер CC 15 отсутствовал вообще (CC 78 ошибочно числился swing; master = 79);
  `Browse` был CC 69 (это foot pedal 2) → исправлен на CC 111
- **Создание трека:** ветка Duplicate в контроллере удалена (резерв); Add Track (CC 53 — «add track button» по спеке)
  открывает wizard. Результат всегда во flash
- **Wizard:** `ScreenId.WIZARD` (не в tab_order); шаг 1 — выбор melodic/drum, шаг 2 (melodic) — выбор профиля из
  PROFILES (9: pad, atmos, sub, stab, seq, arp, bass, lead, texture); drum создаётся сразу на шаге 1; навигация:
  Up/Down или E1 — выбор, Right/Select/Add Track — подтверждение, Left/Delete — отмена. Реализация: `WizardView` DTO
  в `src/devices/display_state.py` (+ поле `screen_view.wizard`), `draw_wizard` в `screens.py`, ветки в
  `display.py` (`_compose_screen`/`_invalidate_screen_regions`), константы `WIZARD_KINDS`/`MELODIC_PROFILES` в
  контроллере; LED-табы защищены (`App._update_tab_leds` пропускает WIZARD)
- **Тесты:** mapping сверен со спекой (`test_button_map_covers_all_spec_buttons` — все 56 CC, `test_button_map_key_assignments`,
  `test_encoder_map_matches_spec`, swing-энкодер и Add Track в midi-in dispatch); 8 wizard-тестов контроллера
  (duplicate не назначен, открытие, melodic/drum-флоу, отмена Left/Delete, E1, Select, ошибка во flash);
  2 пиксельных теста `draw_wizard`
- **E2E (spike, сценарий 7 добавлен, сценарий 1 переехал на wizard):** PASS 1–7 — wizard kind → Drum 1; melodic →
  profile (Down ×3 = stab) → Stab 2, flash «created track …». PNG: `ui_7_wizard_kind.png`, `ui_7b_wizard_profile.png`
- **Результат:** 1074 passed; ruff 59 ≤ 60; mypy — только пре-существующие import-untyped; black чисто

### Дополнение D2-2: переразметка кнопок + цвета + GEN/MACRO (02.11.2026) — ✅ ЗАВЕРШЕНО

- **Запрос:** TRACKS на кнопку Session; Lower Row назначает TRACK; цвета дорожек;
  TRACK разделить на 2 экрана (генерация — CLIP, макро-контроль — DEVICE)
- **Переразметка экранов** — `ScreenId`: табы Upper Row 1–5 теперь
  ``tab_order() = (TRACK_GEN, TRACK_MACRO, GLOBAL, SYNC, PORTS)``; TRACKS
  (кнопка ``Session``, CC 51) и WIZARD — вне табов; `ScreenId.TRACK` удалён
- **Навигация** (`screen_controller.py`): ``Session`` → TRACKS; ``Clip``
  (CC 113) → GEN выбранной дорожки; ``Device`` (CC 110) → MACRO; ``Lower Row
  1–8`` (CC 20–27) — курсор на слот страницы + вход в GEN (пустой слот —
  только курсор); Left: MACRO→GEN→TRACKS; Right на TRACKS: страница → GEN →
  стоп (TRACKS не таб, пустая сессия не уходит в кольцо)
- **GEN (генерация)**: SRC/SRC2 (E1/E2), GATE (E3), DEN (E4), MUT (E5),
  VOICING; CC-оси с GEN убраны. **MACRO**: TONE/SPACE/DEPTH на E1–E3
  (было E6–E8 на TRACK) — шлются через CCMap + троттлер при наличии порта,
  иначе значение копится в UiState («—» в view)
- **Цвета дорожек** — `src/devices/push2/track_colors.py`: 12 цветов
  BGR565 через ``rgb_to_bgr565``, ``track_color(abs_index)``; поле ``color``
  в TrackRowView (маркер 8×8 в списке TRACKS), TrackDetailView и
  TrackMacroView (полоса 4 px слева в body); цвет детерминирован индексом
  дорожки в сессии
- **View-модели** — `TrackMacroView` (name/kind/channel/port/macros/color)
  + поле ``ScreenView.track_macro``; из TrackDetailView убраны macros
- **Рендер** — `draw_track` = GEN (без макро-строки, +цветная полоса +
  подсказка «MACROS: DEVICE -> …»), новый `draw_track_macro` (порт/канал +
  три широких бара); маршрутизация и body-diff в `display.py`
- **LED-табы** — без изменений в механике: экраны вне tab_order (TRACKS,
  WIZARD) не переключают LED (`App._update_tab_leds`)
- **Тесты:** +18 (контроллер: Session/Clip/Device/Lower Row ×2, GEN↔MACRO
  табы, CC-оси на E1–E3, GEN без CC-осей, цвета в rows/macro view;
  рендер: маркеры цвета, полосы, draw_track_macro ×4; ui_state: values/tab_order)
- **E2E (spike, сценарии 1–8):** PASS — GEN (E4 DEN) + MACRO через Device
  (E1 TONE); Session → TRACKS с цветными маркерами; Lower Row 2 → GEN Stab 1;
  Lower Row 8 (пусто) — курсор перенесён. PNG: `ui_2_track_gen.png`,
  `ui_2b_track_macro.png`, `ui_8_session_tracks.png`
- **Результат:** 1088 passed; ruff 59 ≤ 60; mypy — только пре-существующие
  import-untyped; black чисто
- **Результат:** 1057 passed (было 1012 после D1; +45: ui-каркас 18, macro_axes 15, screens_render 20, screen_controller
  32, pushdisplay_screen 10, track_density 14, engine_control_d2, clock-регрессии 6, controller-регрессии 3; часть
  файлов создавалась вместе, суммы пересекаются); ruff 59 ≤ базиса 60 (чисто на новых/изменённых); mypy — только
  пре-существующие import-untyped (isobar/mido); black чисто
- **Известные ограничения (техдолг):**
    - Ручной прогон на железе (табы, LED, энкодеры, 25 fps) — при доступе к Push 2; в simulate проверено через превью
    - LCXL3-путь энкодеров в D2 не тронут (debug-лог), как и задумано планом; EncoderHandler не существует (удалён
      при очистке legacy как dead code)
    - Курсор PORTS переиспользует `selected` — при входе на PORTS курсор трека клампится к числу портов (дизайн плана,
      E1 всегда может выбрать дорожку явно)
    - CC-оси шлют значение только по факту поворота (не «догоняют» при route) — осознанное решение плана §7
- **Файлы:** `src/app/ui/` (screen_id, ui_event, ui_queue, ui_state, macro_axes, screen_controller),
  `src/devices/display_state.py`, `src/devices/push2/screens.py`, `src/devices/push2/display.py`,
  `src/devices/push2/push2_device.py`, `src/app/display.py`, `src/app/application.py`, `src/app/engine_control.py`,
  `src/app/config.py`, `src/config.py`, `src/session/generators.py`, `src/session/melodic_track.py`,
  `src/sync/swing.py`, `src/sync/clock_manager.py`, `src/sync/tick_proxy.py`, `src/repl/status.py`,
  `tests/test_ui_queue.py`, `tests/test_ui_state.py`, `tests/test_macro_axes.py`, `tests/test_screens_render.py`,
  `tests/test_screen_controller.py`, `tests/test_pushdisplay_screen.py`, `tests/test_track_density.py`,
  `tests/test_engine_control_d2.py`, `tests/test_clock_manager.py`, `spikes/spike_ui_simulate.py`, `plans/plan_d2_screens.md`

### Дополнение D2-3: SCALE/SETUP-кнопки, DEL+ROW, LED-подсветка (02.11.2026) — ✅ ЗАВЕРШЕНО

- **Запрос:** 1) экран GLOBAL вызывается кнопкой Scale (CC 58) и переименован в
  SCALE, дизайн — по образцу выбора шкалы Push 2; 2) экран SYNC вызывается
  кнопкой Setup (CC 30) + суб-вкладки настроек; 3) Delete вооружается и
  удаляет треки нажатием Delete + LOWER ROW 1–8; 4) подсвечивать все рабочие
  кнопки (LED Push 2)
- **Что сделано:**
  - `ScreenId`: `GLOBAL/SYNC` → `SCALE("scale")`/`SETUP("setup")`; табы
    Upper Row 1–5: GEN, MACRO, SCALE, SETUP, PORTS; TRACKS — кнопка Session
    (вне табов). Стрелки на SCALE: Left/Right — корень, Up/Down — лад
    (через `set_root`/`set_scale`); на SETUP Up/Down крутят `setup_tab`
    (clock/midi/link). Энкодеры: SCALE — E1 root / E2 scale / E3 swing;
    SETUP E1 меняет источник клока только на вкладке clock
  - `display_state.py`: `GlobalView` → `ScaleView(roots, scales, root_index,
    scale_index, swing)`; `SyncView` + `tab`/`tabs` ("clock", "midi", "link")
  - `screens.py`: `draw_scale` (ряд корней-заголовков сверху с белой заливкой
    выбранного, сетка ладов 4×2, выбранный лад — белой рамкой, панель свинга
    E3 в правом нижнем углу); `draw_setup` (тело активной вкладки + таб-бар
    внизу body, активная вкладка — белой заливкой с чёрным текстом)
  - **Delete:** без Shift тогглит `UiState.delete_armed` + flash "DELETE:
    press LOWER ROW 1-8" (LED Delete красный); `_lower_row_button` при armed
    снимает вооружение и удаляет трек по позиции (flash-фидбек); Shift+Delete
    — удаление выбранной (совместимость)
  - **LED-подсветка (п. 4):** `button_led_states(snap) -> dict[str, int]` в
    screen_controller: рабочие кнопки белые/серые (Session/Clip/Device/Scale/
    Setup/Add Track/Browse/стрелки/Select), Play — GREEN при running иначе
    WHITE, Record — RED, Shift — WHITE при удержании иначе DIM, Delete —
    RED при armed иначе DIM, Upper Row 1–5 — по активному табу, Lower Row
    1–8 — GREEN если выбран / WHITE если трек есть / отсутствует если пусто.
    Палитра по спеке: 0 off, 122 white, 126 green, 127 red (для белых кнопок
    значение = яркость). `Push2Device.set_button_leds(states)` шлёт CC
    name→CC из `PUSH2_BUTTON_NAME_TO_CC`; `App._update_button_leds()` диффит
    карту с прошлой и шлёт только изменившиеся
  - **Фикс рендера (найден по PNG):** `_GLYPH_THRESHOLD` 128 → 96 — у
    10px-глифов ('m' в major/minor) тонкие колонки имеют яркость 120 из-за
    антиалиасинга и при пороге 128 терялись
  - `mapping.py` docstring: Scale/Setup — назначены, Lower Row — удаление
    при armed Delete, табы переименованы
- **Тесты (+17, всего 1105):** test_ui_state (values/tab_order), test_screen_controller
  (test_tabs_step_gen_macro, test_scale_and_setup_buttons, test_scale_arrows_rotate_root_and_scale,
  test_setup_tabs_cycle_with_up_down, test_delete_arms_and_disarms, test_armed_delete_lower_row_removes_track,
  test_armed_delete_lower_row_empty_slot_noop, test_delete_without_shift_no_engine_call,
  test_setup_encoder_only_on_clock_tab, TestButtonLeds ×5), test_screens_render
  (TestDrawScale ×4, TestDrawSetup ×5), test_pushdisplay_screen (`set_button_leds` → CC)
- **E2E (spike, сценарии 1–9):** PASS — SCALE (Scale-кнопка, E1 root, стрелки);
  SETUP (вкладки clock/midi/link, E1 clock→midi→internal); DELETE+ROW (armed,
  LED красный, Lower Row 4 удаляет Stab 2). Фикс spike: `btn_up()` — Shift
  после сценария 6 не отпускался, из-за чего Delete шёл по Shift-ветке.
  PNG: `ui_4_scale.png`, `ui_5a_setup_midi.png`, `ui_5_setup.png`, `ui_9_delete_row.png`
- **Результат:** 1105 passed; ruff 59 ≤ базиса 60; mypy — только
  пре-существующие import-untyped (10); black чисто
- **Файлы:** `src/app/ui/screen_id.py`, `src/app/ui/ui_state.py`,
  `src/app/ui/screen_controller.py`, `src/devices/display_state.py`,
  `src/devices/push2/screens.py`, `src/devices/push2/display.py`,
  `src/devices/push2/push2_device.py`, `src/devices/push2/renderer.py` (порог),
  `src/devices/push2/mapping.py` (docstring), `src/app/application.py`,
  `tests/test_ui_state.py`, `tests/test_screen_controller.py`,
  `tests/test_screens_render.py`, `tests/test_pushdisplay_screen.py`,
  `spikes/spike_ui_simulate.py`

### Дополнение D2-4/D2-5: таб-бар под кнопками, 8-колоночный body, касания энкодеров (02.11.2026) — ✅ ЗАВЕРШЕНО

- **Запрос (видение пользователя):** глобальные экраны TRACKS/SCALE/SETUP
  (Session/Scale/Setup-кнопки) и дорожные GEN/MACRO/PORTS (Clip/Device/Upper
  Row 5); таб-бар в верхнем ряду дисплея — вкладка под своей кнопкой; body —
  8 колонок по шагу энкодеров (метка, крупное значение, бар) по образцу
  макета Ableton; нижний статус-бар убрать; BPM — по касанию Tempo Encoder
- **Что сделано:**
  - `screen_id.py`: `tab_order()` = (TRACK_GEN, TRACK_MACRO, PORTS) — кольцо
    Right/Left только между GEN ⇄ MACRO; от MACRO Right → PORTS; от PORTS
    стрелки ходят по списку портов; SCALE/SETUP/WIZARD — вне табов, стрелки
    туда не ходят (фикс латентного ValueError в `_step_screen`)
  - `screens.py`: body переразмечен — `BODY_Y0=36`, `BODY_Y1=160`, 8 колонок
    `COL_W=120` под E1–E8/Lower Row; `draw_tab_bar` (активная вкладка —
    белая заливка, ячейки GEN x≈906 / MACRO x≈800 / PORTS x≈540 — под своими
    кнопками по схеме спеки, проверить на железе); `_column()` (метка y+4 sm,
    значение y+22 lg, бар y+46); `draw_track` — E1 SRC / E2 SRC2 / E3 GATE /
    E4 DEN / E5 MUT + строка PORT/CH/PROFILE/VOICING; `draw_track_macro` —
    TONE/SPACE/DEPTH в % + «NO PORT — CC NOT SENT»; свинг на SCALE — колонка
    `SWING (E3)`; `draw_status_bar`/`draw_hints`/`_labeled_bar` удалены
  - `display_state.py`: `StatusBarView` удалён; у `ScreenView` убраны
    `status`/`hints`, добавлено `tab: str | None`
  - `display.py`: регион `_RECT_STATUS` удалён — dirty-регионы только
    header/body
  - `screen_controller.py`: `HINTS` и `_status_bar()` удалены;
    `PORTS_BUTTON = "Upper Row 5"`; LED: Upper Row 5 белая на PORTS / серая
    на прочих, Upper Row 1–4,6–8 не подсвечиваются (освобождены под D3+);
    **касания энкодеров**: Tempo Encoder → flash «BPM {bpm} {SOURCE}»,
    Swing Encoder → flash «SWING { %}», TTL 2 с (`ENCODER_TOUCH_TTL`)
  - `push2_device.py`: `_ENCODER_TOUCH_NOTES = {10: "Tempo Encoder",
    9: "Swing Encoder"}` — note-on/nn10 и note-off/nn9 идут через `_on_button`
    (без расширения базового интерфейса; касание E1–E8/nn0–8 не обрабатывается)
  - `mapping.py` docstring: Upper Row — только PORTS, остальные резерв;
    касания Tempo/Swing (nn10/nn9)
  - Spike: сценарий 4 — сверка root со статусом через `snap()` + касание
    Tempo → flash с BPM; docstring обновлён
- **Тесты (+8, всего 1113):** test_screen_controller (TestEncoderTouch ×5,
  test_tabs/test_tabs_step_gen_macro переписаны под Clip/Device/Upper Row 5,
  test_upper_row_leds_follow_active_tab, test_global_encoders/test_sync_
  encoder_cycles_source через Scale/Setup, тесты `view.status` удалены),
  test_push2_device (касания ×4: press/release/vel0/ignore nn0–8,11+),
  test_ui_state (test_tab_order_three_screens), test_pushdisplay_screen и
  test_screens_render обновлены под новый ScreenView
- **E2E (spike, сценарии 1–9):** PASS; PNG глазами: GEN/MACRO — колонки
  под энкодеры + таб-бар; SCALE — свинг-колонка + flash «BPM 120.0 INTERNAL»
  по касанию; PORTS — активная вкладка; статус-бара нет
- **Результат:** 1113 passed; ruff 56 ≤ базиса 59; mypy — только
  пре-существующие (10); black чисто
- **Открытое:** MACRO не переименовывал (пользователь писал «TRACK/GEN/PORTS»);
  x-центры вкладок (906/800/540) — оценка по схеме спеки, проверить на железе
- **Файлы:** `src/app/ui/screen_id.py`, `src/app/ui/screen_controller.py`,
  `src/devices/display_state.py`, `src/devices/push2/screens.py`,
  `src/devices/push2/display.py`, `src/devices/push2/push2_device.py`,
  `src/devices/push2/mapping.py` (docstring), `tests/test_ui_state.py`,
  `tests/test_screen_controller.py`, `tests/test_screens_render.py`,
  `tests/test_pushdisplay_screen.py`, `tests/test_push2_device.py`,
  `spikes/spike_ui_simulate.py`

### Дополнение D2-6: SCALE без свинга, имена дорожек внизу, wizard route (02.11.2026) — ✅ ЗАВЕРШЕНО

- **Запрос:** 1) убрать значение Swing из экрана SCALE; 2) внизу экрана —
  названия дорожек; 3) в wizard'е Add Track — шаг выбора route (порта)
- **Что сделано:**
  - **SCALE без свинга:** у `ScaleView` удалено поле `swing`; `draw_scale`
    рисует только корни + лады; E3 на SCALE не назначен (свинг крутит
    Swing Encoder на любом экране, значение — по касанию, flash). SWING_STEP
    остался для Swing Encoder
  - **Имена дорожек внизу (TRACKS):** `draw_tracks` — нижняя полоса
    (y = BODY_Y1−15): колонка i ровно под кнопкой Lower Row i+1 — цветной
    маркер + имя (обрезка по ширине колонки 120 px); пустой слот — «—» DIM.
    Строки списка уплотнены до 13 px (`_TRACK_ROW_H`), чтобы полоса не
    пересекалась со списком
  - **Wizard route:** шаги kind → profile (только melodic) → route.
    Варианты шага route: «—» (WIZARD_ROUTE_NONE, без порта) + порты
    снапшота; E1/Up/Down листают на любом шаге. Подтверждение route:
    создать (drum или melodic с сохранённым `UiState.wizard_profile`), имя
    новой дорожки — регуляркой из фидбека фасада
    (`_CREATED_TRACK_RE = ^created track "([^"]+)"` — формата держится
    AppEngineControl), затем `route_track(name, port)`; error роута
    перекрывает flash. Отмена (Left/Delete) сбрасывает и шаг, и профиль
  - `UiState.wizard_profile: str | None` — выбранный профиль между шагами
    (None — drum); `_wizard_options(snap)` / `_wizard_rotate(inc, snap)` —
    варианты зависят от снапшота (порты)
  - `draw_wizard`: метка шага через dict («KIND»/«PROFILE»/«ROUTE (PORT)»);
    заголовок «ADD TRACK: ROUTE»; docstring `WizardView` обновлён
- **Тесты (+7, всего 1120):** test_screen_controller (переписаны wizard-flow
  под route: melodic/drum/error; новые: route_assigns_port, route_port_cycle
  via encoder, route_error_flashes, cancel_resets_profile, E3 на SCALE — no-op,
  Swing Encoder всегда работает), test_screens_render (TestDrawScale:
  test_swing_bar → test_no_swing_panel; TestDrawTracks: высоты 13 px,
  test_bottom_names_under_lower_row, test_bottom_empty_slot_dash),
  test_pushdisplay_screen (`ScaleView` без swing)
- **E2E (spike, сценарии 1–9):** PASS — сценарий 1: третий Right на шаге
  route («—»); сценарий 7: drum → route main (Drum 1 создан и привязан),
  melodic stab → route «—» (Stab 2 без порта); PNG: имена внизу под Lower
  Row, SCALE без свинг-панели, wizard route-шаг
- **Результат:** 1120 passed; ruff 56 ≤ базиса 59; mypy — только
  пре-существующие (10); black чисто
- **Файлы:** `src/devices/display_state.py`, `src/devices/push2/screens.py`,
  `src/devices/push2/mapping.py` (docstring), `src/app/ui/ui_state.py`,
  `src/app/ui/screen_controller.py`, `tests/test_screen_controller.py`,
  `tests/test_screens_render.py`, `tests/test_pushdisplay_screen.py`,
  `spikes/spike_ui_simulate.py`

### Дополнение D2-7: классы Screen + UI-фреймворк виджетов (02.11.2026) — ✅ ЗАВЕРШЕНО

- **Запрос:** screens.py — класс для экранов с передачей текущего экрана;
  расширяемая структура новых экранов; UI-подобный фреймворк для сборки экрана
- **Что сделано:**
  - **Новый `widgets.py` (фреймворк):** контракт `Widget.render(fb, rect)`
    (Protocol) + `Rect` (x/y/w/h, cx, bottom, inset). Виджеты: `Label`
    (align l/c/r), `Marker` (цветной квадрат), `Bar` (0..1, frac=None — не
    рисуется), `Column` (метка + крупное значение + бар под значением —
    замена `_column()`), `ColumnGrid` (8 колонок по 120 px ровно под
    энкодерами E1–E8/Lower Row, `rect(i)`/`center_x(i)`), `TabStrip`
    (ячеики (метка, x-центр) под физическими кнопками, активная — белой
    заливкой). Виджеты frozen — сборка на кадр дёшево. Каноническая
    body-геометрия (`BODY_Y0/Y1`, `COL_W`) живёт здесь
  - **`screens.py` переписан в классы:** абстрактный `Screen`
    (`name: ClassVar[str]` = `ScreenId.value`, `view_attr: ClassVar[str]`
    = поле `ScreenView` с DTO тела; `draw_body(fb, body: Any)` в базе,
    конкретный DTO в наследниках; `draw(fb, view)` доставляет DTO из
    ScreenView). Семь экранов: `TracksScreen`, `TrackGenScreen`,
    `TrackMacroScreen`, `WizardScreen`, `ScaleScreen`, `SetupScreen`,
    `PortsScreen` — тела собраны из виджетов
  - **`Screens` (реестр + композитор):** `register()` (дубликат имени —
    ValueError), `names()`; `draw_header()` / `draw_body()` раздельно под
    dirty-регионы PushDisplay; `draw()` целиком. Неизвестный `view.screen`
    → body заливается фоном, без падения. Новый экран: подкласс Screen +
    `register()` (пример в `tests/test_widgets.py`)
  - **Module-level `draw_*`** — тонкие обёртки над `draw_body` (пиксельные
    тесты/spikes без ScreenView); `TAB_CELLS`/`BODY_*`/`COL_W` реэкспортируются
  - **`display.py`:** `_compose_screen` диспетчеризует через `Screens()`
    вместо цепочки if-elif по DTO; регионная инвалидация (header/body)
    не изменилась
  - Рефакторинг поведение не менял: PNG-дампы spike побайтово совпали
    с дорефакторными
- **Тесты (+24, всего 1144):** новый `tests/test_widgets.py` — Rect,
  Label (3 выравнивания), Marker, Bar (frac/None/clamp), Column,
  ColumnGrid (8×120, custom range), TabStrip (активная ячейка), Screens
  (реестр дефолтных, регистрация кастомного экрана, дубликат → ValueError,
  неизвестный экран → фон, DTO None → фон, header/draw целиком)
- **E2E (spike, сценарии 1–9):** PASS
- **Результат:** 1144 passed; ruff 56 ≤ базиса 59; mypy — только
  пре-существующие (10); black чисто
- **Файлы:** `src/devices/push2/widgets.py` (новый),
  `src/devices/push2/screens.py` (переписан), `src/devices/push2/display.py`,
  `tests/test_widgets.py` (новый)

### Задача D3: Пады — четыре режима

- **Агент:** `coder` (MIDI-контроллеры, UI)
- **Зависимости:** D2, C2 (войсинги), C4 (drum)
- **Выход:** `pads.py`
- **Ключевые требования:**
    - **CHORDS**: триады / септаккорды / 1-е обращение / 2-е обращение (4 ряда)
    - **NOTES**: клавиатура ступеней, вертикаль = октава
    - **MORPH**: поле 8×8, X = density, Y = mutate
    - **DRUM**: сетка 8×8 как Ableton Drum Rack, 16 lane, квадраты, плейхед
    - Цвет несёт функцию: тоника яркая, доминанта контрастная, уменьшённые тёмные
    - Предпрослушивание lane — в конфиге (`preview_on_select: true`)

---

## План E — Синхронизация и живучесть (Фазы 5–6)

**Цель:** Выбор клока/портов с Push 2, 8-часовой прогон без вмешательства.

### Задача E1: Экраны SYNC и PORTS

- **Агент:** `coder` (UI, интеграция)
- **Зависимости:** B1, B2, D2
- **Выход:** интеграция в `screens.py`
- **Ключевые требования:**
    - Переключение клока по кнопке, применение на ближайшей доле
    - Сохранение выбора в конфиг (переживает перезапуск)

### Задача E2: Живучесть и 8-часовой прогон

- **Агент:** `coder` (системный, DevOps)
- **Зависимости:** все предыдущие
- **Выход:** systemd-юнит, скрипты мониторинга
- **Ключевые требования:**
    - Hot-plug всех трёх USB-устройств
    - `systemd`-юнит, `Restart=always`
    - `isolcpus`, `SCHED_FIFO`, `performance`-губернатор
    - **8-часовой прогон** — нормальная длина сета, не стресс-тест
    - `tracemalloc` для поиска утечек

---

## План F — Терминальный интерфейс (REPL/TUI)

**Цель:** Мониторинг и лёгкий контроль движка из терминала (Mac dev, RPi по SSH) без Push 2.

### Задача F1: REPL на prompt_toolkit — ✅ ЗАВЕРШЕНО

- **Агент:** `coder` (CLI, конкурентность)
- **Зависимости:** A2, B1, B2, B3, B4, C1, C3, C4, C5 — все завершены
- **Выход:** `src/repl/` (12 модулей), `src/app/engine_control.py`, флаг `--repl`
- **Ключевые требования:**
    - Строчный REPL на prompt_toolkit (не полноэкранный TUI): история, автодополнение, bottom_toolbar
    - REPL-поток внутри процесса App, доступ только через `EngineControl` (ABC) + `StatusSnapshot`
    - Снапшот собирается в main loop, атомарная замена ссылки; REPL не читает движок напрямую
    - Деструктивные команды (`stop`, `track delete`) — подтверждение y/N, `--yes`/`-f`
    - Статус-бар ~2 Гц: bpm, clock (+pending/error), root/scale, tracks, mut, ports, link peers
    - Запуск только по `--repl`; без флага поведение не меняется (systemd-совместимо)
    - EOF (Ctrl+D/обрыв SSH) → `app.stop()`; `exit`/`quit` — то же
    - История в `<config_dir>/repl_history` (обрезка до 1000 строк, в `.gitignore`)
    - Логи: `LogBuffer` (logging.Handler, deque 500) — команда `logs [N]`
    - `ports switch <label> <match>` — рантайм-перенаправление порта на другое устройство: pending-заявка в PortManager,
      применяется на ближайшем poll (~2 с), PortRegistry закрывает старый выход (all_notes_off) и открывает новый;
      serial очищается; в config.yaml не пишется
    - `track route/unroute <name> [label]` — маршрутизация дорожек: старый порт глушится all_notes_off; движок создаётся
      on demand для дорожек, добавленных после старта; `track delete` теперь удаляет движок (раньше оставал «призрак»);
      TrackSummary несёт port; лимитация: on-demand melodic-дорожки не регистрируются в MutationEngine (базовый паттерн
      без дрейфа)
    - Багфикс статус-бара: plain-строка с ANSI-кодами в ``bottom_toolbar`` рендерилась как литеральный ``[32m``
      (prompt_toolkit вырезает control-символы) — обёртка в ``prompt_toolkit.formatted_text.ANSI``; регрессионный тест
      на тип toolbar'а
    - Не-цели v1 соблюдены: без TUI, без записи в config.yaml, без скриптов из файла
- **Что сделано:**
    - `src/repl/`: engine_control (ABC), status (frozen DTO), command, parser (git-стиль, таблица команд,
      difflib-подсказки), executor, confirm, log_buffer, history_store, completer (NestedCompleter + динамика через
      провайдеры), status_bar (ANSI, обрезание по ширине), repl (поток, цикл)
    - `src/app/engine_control.py` — `AppEngineControl`, единственный модуль с доступом к внутренностям App
    - `src/app/application.py` — read-only свойства, `set_sync_bpm()`, `_update_status_snapshot()` в main loop,
      `run(repl=...)`, cleanup REPL-потока первым в `_cleanup()`
    - `src/main.py` — флаг `--repl`, сборка Repl + LogBuffer
    - Зависимость `prompt_toolkit>=3.0` в pyproject.toml
    - Отклонения от плана (задокументированы): `freeze <drum>` разрешён (DrumTrack.freeze () осмысленен — сохраняет
      базовый паттерн, план предлагал ошибку); `log_error` в снапшот мёржится в AppEngineControl из LogBuffer, а не в
      App
- **Результат:** 83 новых теста (parser 22, executor 39, status_bar 16, smoke 6), всего 809 тестов passed; ruff/black
  чисто на новых/изменённых файлах; mypy — только пре-существующие ошибки (mido/isobar без stubs)
- **Дополнение (ports switch):** +12 тестов (ports 9, executor 3), всего 821; `PortManager.request_switch()` +
  `_apply_pending_switch()` в poll; `EngineControl.switch_port()`; e2e на виртуальных CoreMIDI-портах: `main` переключён
  One → Two на живом движке
- **Дополнение (track route/unroute):** +28 тестов (app_routing 17, melodic_engine 4, drum_engine 4, executor 3), всего
  849; `App.route_track/unroute_track/drop_track`, on-demand `App._create_engine_for()`; `port_label: str | None` в
  движках (None = тишина); e2e: add → route → reroute → unroute → delete на живом движке. Замечание: прогон `black src`
  отформатировал 16 пре-существующих файлов (devices/, harmony/voicings.py, midi/abc.py) — проект до этого не был
  black-чист целиком; 60 pre-existing замечаний ruff по старым файлам зафиксировано, не тронуто
- **Проверено руками:** `--repl --simulate` — status/clock/bpm/tracks/mutations/logs/help, переключение clock source
  (pending виден в `clock`), валидация root/scale (пентатоника отклонена), freeze/evolve; история пишется; config.yaml
  не тронут; без `--repl` SIGTERM → чистый shutdown, RC 0
- **Файлы:** `src/repl/*.py`, `src/app/engine_control.py`, `tests/test_repl_*.py`, `plans/plan_f1_repl.md`

---

## Зависимости между планами

```
A (инфраструктура)
├── A1 (спайк RPi) — независим, можно параллельно
└── A2 (вырезание) — блокирует B и D

B (движок)
├── B1 (клок) ← A2
├── B2 (порты) ← A2
├── B3 (CC) ← B2
└── B4 (транспорт) ← B1

C (гармония)
├── C1 (гармония) — независим, можно параллельно с B
├── C2 (войсинги) ← C1
├── C3 (граф) ← C1, C2
├── C4 (drum) ← C3
├── C5 (мутация) ← C3
└── C6 (профили↔isobar, E2E) ← C1–C5, B1–B4

D (UI)
├── D1 (рендерер) ← A2
├── D2 (экраны) ← D1, B1, B2
└── D3 (пады) ← D2, C2, C4

E (финал)
├── E1 (SYNC/PORTS) ← B1, B2, D2
└── E2 (живучесть) ← все

F (терминал)
└── F1 (REPL) ← A2, B1, B2, B4, C1, C3, C4, C5 — все завершены
```

---

## Рекомендации по запуску агентов

| Приоритет | План                        | Почему первым                                                                         |
|-----------|-----------------------------|---------------------------------------------------------------------------------------|
| 1         | ~~**A1** (спайк RPi)~~      | ✅ **ЗАВЕРШЕНО** — 102 fps, джиттер 0.059 мс, 51.8°C, 24.9% CPU                       |
| 2         | ~~**A2** (вырезание)~~      | ✅ **ЗАВЕРШЕНО** — 264 теста passed, Python 3.13, isobar 0.2.1                        |
| 3         | ~~**C1** (гармония)~~       | ✅ **ЗАВЕРШЕНО** — `src/harmony/`, 41 тест, 8 ладов, валидация                        |
| 4         | ~~**C3** (граф и Session)~~ | ✅ **ЗАВЕРШЕНО** — `src/session/`, 41 тест, Track→Melodic/Drum, топосорт, стратегия B |
| 5         | ~~**B1** (клок)~~           | ✅ **ЗАВЕРШЕНО** — ClockManager + TickProxy, 48 тестов, квантизация на долю           |
| 6         | **B2** (порты)              | Блокирует B3 и E1                                                                     |
| 7         | **C2, C4–C5**               | Музыкальная логика, можно параллельно с B после C1                                    |
| 8         | **D1–D3**                   | UI, зависит от всех                                                                   |
| 9         | **E1–E2**                   | Финальная интеграция                                                                  |
| 10        | ~~**F1** (REPL)~~           | ✅ **ЗАВЕРШЕНО** — `src/repl/` на prompt_toolkit, 83 теста, флаг `--repl`             |

---

## Риски, требующие внимания агентов

| Риск                                          | Какой план | Митигация                                                         |
|-----------------------------------------------|------------|-------------------------------------------------------------------|
| ~~Питание USB на RPi 5~~                      | A1         | ✅ **СНЯТО** — Push 2 + LCXL3 напрямую в RPi 5 работают стабильно |
| CC забивает DIN-шину                          | B3         | Троттлинг 30 Hz: 54% → 1.3%                                       |
| Разрыв фазы при переключении клока            | B1         | Квантизация на долю + `all_notes_off`                             |
| MIDI-колбэк из чужого потока                  | B1         | TickProxy через очередь                                           |
| Неоднозначное совпадение портов               | B2         | `serial` как ключ, явная ошибка                                   |
| Мутация уводит грув необратимо                | C4, C5     | 1–2 изменения за 8–16 с, деградация, Freeze                       |
| `PEuclidean` без кеша при 16 lane             | C4         | Обёртка с кешем                                                   |
| `numpy.int64` ломает mido                     | B4         | `int()` в обёртке                                                 |
| `octave` забыт → ноты 0–11                    | C3         | Валидация в пресетах                                              |
| Удаление дорожки-источника осиротит зависимые | C3         | Источник сбрасывается в `—`, дорожка молчит                       |

---

## Правила написания кода

### Структура файлов и классов

- **Один класс — один файл.** Каждый публичный класс проекта размещается в отдельном файле. Имя файла — `snake_case` от
  имени класса: `class ClockManager` → `clock_manager.py`.
- **Исключение — связанные DTO и типы.** Мелкие взаимозависимые типы (значения-объекты, frozen dataclass'ы,
  конфиг-схемы) можно группировать в одном модуле. Пример: `src/midi/abc.py` содержит `MidiChannel`, `MidiCC`,
  `MidiMessage` и ABC-интерфейсы — это единый типовой слой, а не набор независимых классов.
- **Приватные хелперы** (начинаются с `_`) могут жить в файле основного класса. Пример: `_NullGenerator` в
  `sync_manager.py`.

### Слои и зависимости

Архитектура строго иерархическая, **циркулярные зависимости запрещены**. Слой может импортировать только из слоёв ниже:

```
main.py
  └── app/          ← Application, DeviceManager, Display, EncoderHandler
        └── devices/    ← Push2, LCXL3, Registry, Definitions
              └── midi/     ← ABC, MidoImpl, Factory
                    └── (mido, rtmidi — внешние библиотеки)

sync/             ← автономный, зависит только от isobar и опционального link
session/          ← граф дорожек и движки (зависит от harmony/):
                      events/   ← ChordEvent, NoteEvent, DrumEvent (слой 0)
                      model/    ← Track, MelodicTrack, DrumTrack, профили,
                                  PatternSpec, PEuclideanCached, chord_math
                      mutation/ ← NoteDrift, FloatingEuclidean, ParamDrift,
                                  MutationEngine (+ таблицы, config)
                      graph/    ← TrackGraph
                      session.py← Session (model + graph)
                      drum/     ← DrumEngine, DrumConfig
                      engine/   ← BeatScheduler, generators, MelodicEngine
                      (корневой __init__.py — фасад публичного API)
config.py         ← конфигурация, зависит от devices/ и sync/
```

Правила:

- **Никаких циклов.** Если слою A нужен слой B, а слою B — слой A, значит нужен третий модуль ниже обоих, или нужно
  разорвать связь через протокол/ABC.
- **Типы для аннотаций** — через `TYPE_CHECKING` guard или в отдельном модуле ниже по иерархии.
- **Ленивые импорты** допустимы для разрыва циклов и ускорения старта, но не как способ обойти правило слоёв.

### Стиль

- `from __future__ import annotations` в каждом файле.
- Полная типизация: все параметры, возвращаемые значения, атрибуты классов.
- `snake_case` для функций и переменных, `PascalCase` для классов, `UPPER_SNAKE_CASE` для констант.
- Приватные члены — `_leading_underscore`.
- Docstrings — Google-style, на русском для бизнес-логики, на английском для технических модулей.
- Логирование: `log = logging.getLogger(__name__)` на уровне модуля.

---

## Артефакты для агентов

| Файл                           | Что это                                         | Какой план |
|--------------------------------|-------------------------------------------------|------------|
| `push2_dubtechno_plan_v5_4.md` | Полный план v6.0                                | все        |
| `spikes/spike_display.py`      | Тест дисплея Push 2: fps, стоимость кадра       | A1         |
| `spikes/spike_jitter.py`       | Тест джиттера планировщика                      | A1         |
| `spikes/spike_stress.py`       | Стресс-тест: температура, CPU%, throttling      | A1         |
| `spike_cc_throttle.py`         | Троттлинг: 3840 → 93 CC                         | B3         |
| `spike_chords.py`              | Синтаксис аккордов, мультипорт, gate            | C1, C3     |
| `harmony_model.md`             | Гармоническая модель подробно                   | C1, C2     |
| `track-hierarchy.md`           | Иерархия Track→Melodic/Drum, профили как данные | C3, C4     |
