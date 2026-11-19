# Анализ замены isobar: полная ликвидация зависимости

**Дата:** 2026-11-19
**Статус:** на ревью
**Мотивация:** полный контроль над клоком — собственная реализация тик-генератора и базы
времени вместо `isobar.Timeline` / `isobar.Clock` (бриф согласован с пользователем 2026-11-19).
**Связанное:** `AGENTS.md` (правила слоёв/кода), `docs/push2_dubtechno_plan_v5_4.md` §3.1–3.5
(клок, ловушки isobar), `plans/ROADMAP.md` (история), `plans/plan_b1_clock_manager.md` /
`plan_b4_transport_swing.md` (как isobar попал в архитектуру).
**Следующий шаг:** после ревью — OpenSpec change `replace-isobar` (в этом документе change
НЕ создаётся).

Все ссылки на поведение isobar проверены по исходникам установленной версии 0.2.1
(`.venv/lib/python3.13/site-packages/isobar/`), ссылки на проект — по исходникам `src/` и `tests/`.

---

## 1. Резюме

isobar 0.2.1 в рантайме проекта занят тремя ролями, каждая из которых по объёму
**на порядок меньше** того, что тянет библиотека целиком:

1. **Гармония** — `Scale.byname()` (таблица ладов) и `Key.get()` (ступень → полутона
   с переносом октав). Заменяется статической таблицей из 8 диатонических ладов
   + `divmod`-резолвингом. Низкий риск: локальный хелпер `_degree_to_semitone` в
   `harmony.py` уже реализует ту же математику и уже используется валидацией.
2. **Клок** — `isobar.Timeline` (счётчик `current_time` + приём тиков) и `isobar.Clock`
   (тик-генератор только для INTERNAL-источника). MIDI- и Link-источники **уже свои**
   (`MidiClockInput`, `_LinkClockSource`). Заменяются двумя маленькими модулями:
   `TimeBase` (база времени) и `InternalClockSource` (тик-генератор).
3. **Легаси-интерфейсы** — duck-typed адаптеры под isobar (`CaptureOutput`,
   «isobar-интерфейс» `MidiPortOutput`, `int()`-конверсии `numpy.int64`).
   `CaptureOutput` в рантайме **фактически мёртв** (см. §6), но по решению 2026-11-19
   остаётся (§6.1) — меняются только докстринги; `all_notes_off` сохраняется через
   notes-off-callback (design D2 change `replace-isobar`).

Из брифа в процессе сверки не подтвердился один пункт: **двойного применения свинга
уже нет** — он вынесен в единственную точку (`Transport._schedule`) планом v5.4 §4.2;
запись в `AGENTS.md` об этом техдолге и докстринг `melodic_engine.py` устарели (§7).
Фаза «свинг» превращается в документационную чистку + регрессионный тест-страж.

Рекомендованный дизайн клока — **вариант B (§5.3)**: формализация существующего
duck-typed интерфейса источников в `Protocol`, новый `TimeBase` с целочисленным
счётчиком тиков, `InternalClockSource` на `time.perf_counter()`. Порядок фаз:
гармония → клок → чистка → свинг-хвост; каждая фаза независимо тестируема.

Оценка объёма: ~15 файлов в `src/` (3 с прямыми импортами), 1 новый файл в `src/harmony/`
и 2 в `src/sync/`, правка докстрингов `CaptureOutput` (модуль и тест остаются по решению 2026-11-19), обновление ~7 тест-файлов,
`pyproject.toml` + `AGENTS.md` + мелкие докстринги. Порядок: сотни строк нового кода,
минус пара сотен легаси.

---

## 2. Карта текущего использования isobar

### 2.1. Прямые импорты (проверено grep'ом по всему репозиторию)

Ровно **3 файла** импортируют isobar:

| Файл | Что используется | Кем вызывается | Что на замену |
|------|------------------|----------------|---------------|
| `src/harmony/harmony.py` (строки 23, 26) | `Key`, `Scale` (`Scale.byname`, `scale.semitones`, `Key(root, scale)`, `key.get(degree)`); `Timeline` — только под `TYPE_CHECKING` | `Harmony` сам; свойство `Harmony.key` и метод `Harmony.apply(timeline)` **не используются никем вне harmony.py** (проверено grep'ом) | Таблица ладов `src/harmony/scales.py` + `divmod`-резолвинг; удалить `key` и `apply` |
| `src/app/application.py` (строка 466, локальный импорт) | `Timeline(tempo, output_device=CaptureOutput, ticks_per_beat=480)`; чтения `timeline.current_time` (6 точек в хуке, строки 515–549); запись `timeline.tempo` (строка 966) | `TickProxy._dispatch` (`tick()`/`reset()`/`stop()`); `ClockManager` (`current_time` чтение+запись, `output_devices`); хук приложения (текущий бит во все движки) | `TimeBase` (`src/sync/time_base.py`); `timeline.tempo = value` — удалить (сегодня пишет в «зомби-клок», см. §5.1) |
| `src/sync/clock_source.py` (строка 246, локальный импорт) | `Clock(clock_target, tempo, ticks_per_beat)` — **только** ветка INTERNAL фабрики `create_clock_source` | `ClockManager._activate_source` → фабрика | `InternalClockSource` (`src/sync/internal_clock.py`) |

`schedule()`, `add_track()`, `add_output_device()` на Timeline из `src/` не вызываются
нигде (проверено grep'ом) — паттерны isobar на таймлайн не регистрируются со времён C6.

### 2.2. Косвенная связь (duck-typing, легаси-имена, докстринги)

| Файл | Связь с isobar | Замена |
|------|----------------|--------|
| `src/sync/tick_proxy.py` | Диспетчеризует `tick()/reset()/stop()` в Timeline; `ticks_per_beat` делегирует Timeline (читается isobar `Clock` при создании) | Диспетчеризация в `TimeBase`; `ticks_per_beat` от `TimeBase` |
| `src/sync/clock_manager.py` | Читает/пишет `current_time`; читает `output_devices` для `all_notes_off` | Те же операции над `TimeBase`; `all_notes_off` → notes-off-callback (design D2) |
| `src/sync/capture_output.py` | Полностью копирует интерфейс `OutputDevice` isobar (`note_on(note, velocity, channel)` и т. д.), `ticks_per_beat=None` под `make_clock_multiplier` | Оставить (решение 2026-11-19, §6.1); правятся только докстринги |
| `src/sync/routing.py` | `MidiPortOutput` — «isobar-compatible output device» (имена методов совпадают с ожиданиями isobar), `int()` против `numpy.int64` | Остаётся как собственный API порта; докстринги правятся; `int()` оставить (§6.3) |
| `src/sync/transport.py`, `src/sync/transport_event.py` | Докстринги «int() на всех значениях из isobar»; `TransportMode.ISOBAR` — имя enum-значения | Докстринги; переименование enum в скоупе (решение 2026-11-19: `TICK_THREAD`) |
| `src/sync/config.py` (:17), `src/sync/clock_source.py` (:54), `src/sync/clock_manager.py` (:165) | Докстринги упоминают env-переменную `ISOBAR_DEFAULT_MIDI_IN` (легаси isobar; в рантайме не читается — grep `environ/getenv` в sync-слое пуст) | Докстринги правятся (tasks 3.1) |
| `src/sync/swing.py` | Докстринг «isobar has no swing» (историческое обоснование) | Докстринг |
| `src/session/model/euclidean.py` | Докстринг «обёртка над isobar PEuclidean» — **устарел**: реализация полностью собственная, isobar не импортируется и не вызывается | Докстринг |
| `src/session/engine/melodic_engine.py` (строка 16), `src/session/model/melodic_track.py` (строка 282) | Устаревшие упоминания isobar-паттернов/свинга в докстрингах | Докстринги |
| `tests/` | isobar **не импортируется** (проверено grep'ом); но `test_clock_manager.py` (`MockTimeline`), `test_tick_proxy.py`, `test_midi_clock_out.py` (`_Timeline`) мокают интерфейс Timeline; `test_capture_output.py` тестирует `CaptureOutput` (остаётся по решению 2026-11-19); докстринги `test_midi_clock_in.py`, `test_clock_source.py`, `test_routing.py`, `test_transport.py` упоминают isobar | Моки → `TimeBase`; `test_capture_output.py` остаётся; докстринги |
| `pyproject.toml` | `"isobar>=0.2.1"` в dependencies + `isobar` в description-строке | Удалить; `uv sync` пересоберёт `uv.lock` |
| `AGENTS.md` | Строка зависимостей; baseline mypy «import-untyped isobar»; техдолг про свинг (устарел) | Обновить |
| `docs/track-hierarchy.md` (строки 85, 106) | Устаревшие упоминания isobar-паттернов | Обновить (опционально, исторический документ) |

Spikes (`spikes/*.py`), `src/main.py`, `src/repl/`, `src/scripting/`, `src/config.py`,
`src/midi/` — упоминаний и импортов isobar **нет** (проверено grep'ом).

### 2.3. Что isobar делает внутри сам (не видно по импортам проекта)

Из исходника `isobar/timelines/timeline.py` (0.2.1):

- `Timeline.__init__(clock_source=None)` **создаёт собственный `Clock`** с
  `clock_target=timeline` — в проекте он никогда не запускается («зомби-объект»);
  `Timeline.tempo` и `Timeline.ticks_per_beat` — property, делегирующие в этот зомби.
- `Timeline.__init__` **запускает фоновый поток статистики** (`_measure_events_per_second`,
  `while True: sleep(1.0)`) — фоновая нагрузка без пользы для проекта.
- `Timeline.current_time` — **публичный float-атрибут** (не property): запись из
  `clock_manager.py:330` — обычное присваивание атрибута.
- `Timeline.tick()` проходит пустые списки треков/LFO/действий, вызывает `device.tick()`
  у output-устройств и в конце делает `current_time += 1/ticks_per_beat` — float-накопление.
- `Timeline.stop()` вызывает `all_notes_off()` + `stop()` у всех output-устройств и
  `stop()` у зомби-клока.
- `Timeline` держит `clock_multipliers` по каждому output-устройству
  (`make_clock_multiplier(device.ticks_per_beat, timeline.ticks_per_beat)`;
  `CaptureOutput.ticks_per_beat = None` → множитель 1).

Из `isobar/timelines/clock.py`:

- `Clock.run()` — busy-цикл с `time.sleep(0.0001)` и абсолютным планированием
  (`clock0 += tick_duration`), догоняет пропущенные тики батчем; источник времени —
  **`time.time()`** (стено-часы: уязвим к NTP-скачку; отмечено ещё в плане v5.4 §5.1).
- `set_tempo` пересчитывает `tick_duration` на лету; `jitter = 0`; предупреждение
  при опоздании > `MIN_CLOCK_DELAY_WARNING_TIME`.
- Множитель тиков `make_clock_multiplier(target_tpb, own_tpb)` при 480/480 = 1:1
  (в проекте всегда единица — TickProxy отдаёт 480).

---

## 3. Сверка фактов брифа с исходниками

| Утверждение брифа | Статус |
|---|---|
| Прямые импорты — 3 файла | ✅ Подтверждено (§2.1) |
| `Timeline` используется только как метроном + счётчик | ✅ Подтверждено, с уточнением: ещё держит `output_devices` (внутри только `CaptureOutput`) и два невидимых зомби-объекта (§2.3) |
| `schedule()` не вызывается нигде | ✅ Подтверждено |
| `current_time` читается в application.py / clock_manager.py, запись в clock_manager ~330 | ✅ Подтверждено: единственная запись — `clock_manager.py:330` в `_apply_pending`, восстановление фазы после смены источника; покрытие уже есть (`test_clock_manager.py::test_phase_preserved_on_switch`) |
| `Clock` только для INTERNAL; MIDI/Link — свои | ✅ Подтверждено |
| `Harmony.key` не используется вне harmony.py; `apply(timeline)` — мёртвый код | ✅ Подтверждено (grep по `\.apply\(` и `.key`) |
| `PEuclideanCached` — собственная реализация, докстринг устарел | ✅ Подтверждено |
| Тесты isobar не импортируют | ✅ Подтверждено |
| int()-конверсии из-за `numpy.int64` от isobar | ⚠️ Уточнение: **исторический** мотив. Со времён C6 события генерируют собственные движки (`MelodicEngine`/`DrumEngine` кладут `TransportEvent` в очередь напрямую), isobar нот не производит. numpy в `src/` остался только в `devices/push2/`. Все `int()` — чистая защита (§6.3) |
| Двойное применение свинга (MelodicEngine + `Transport._deliver_note_off`) | ❌ **Не подтверждено**: уже устранено планом v5.4 §4.2. Единственная точка — `Transport._schedule` (`transport.py:258`); `MelodicEngine` свинг явно не применяет (`melodic_engine.py:313–314`); `_deliver_note_off` в коде не существует (grep — 0 совпадений). Устарели: запись в `AGENTS.md` (известные ограничения) и докстринг `melodic_engine.py:16` (§7) |
| spikes / main / scripting / repl / docs — без isobar-зависимостей | ✅ Подтверждено для кода (0 импортов); в `docs/` — только исторические упоминания в `track-hierarchy.md` и `push2_dubtechno_plan_v5_4.md` (последний не править — план-источник v6.0) |

Дополнительные находки, которых не было в брифе:

- **`CaptureOutput` фактически мёртв** как перехватчик: Timeline без треков не
  генерирует событий, движки кладут `TransportEvent` в очередь напрямую. Живут только
  `all_notes_off()` (путь STOP / смена источника) и запись `beat` в хуке (не читается).
- **`timeline.tempo = value` в `set_sync_bpm` — no-op**: пишет темп в зомби-клок,
  созданный внутри `Timeline.__init__`; реальный темп устанавливается следующей
  строкой в активный источник (`application.py:968`).
- **STOP-артефакт**: `TickProxy` STOP → `timeline.stop()` → `CaptureOutput.all_notes_off()`
  кладёт `ALL_NOTES_OFF` в очередь **после** того, как хук уже погасил всё и опустошил
  очередь; событие лежит до первого тика после рестарта и даёт лишний CC123-бёрст.

---

## 4. Замена гармонии

### 4.1. Таблица ладов

Валидация `set_scale` (`_validate_harmonic`) пропускает сегодня только лады, дающие
терцовые аккорды min/maj/dim. Из словаря ладов isobar под это условие подходят
**восемь канонических имён** (они же — ключи `DIATONIC_TRIADS` в `voicings.py`):

| Имя | Полутона от тоники |
|-----|--------------------|
| `major` | 0, 2, 4, 5, 7, 9, 11 |
| `dorian` (default) | 0, 2, 3, 5, 7, 9, 10 |
| `phrygian` | 0, 1, 3, 5, 7, 8, 10 |
| `lydian` | 0, 2, 4, 6, 7, 9, 11 |
| `mixolydian` | 0, 2, 4, 5, 7, 9, 10 |
| `aeolian` | 0, 2, 3, 5, 7, 8, 10 |
| `locrian` | 0, 1, 3, 5, 6, 8, 10 |
| `minor` | 0, 2, 3, 5, 7, 8, 10 (= aeolian) |

Квирк текущей реализации: имена-алиасы **`ionian`** (= major) и **`maj7`**
(= mixolydian) существуют в `Scale.dict` isobar с теми же полутонами и **сегодня тоже
проходят валидацию** `set_scale`. Чтобы поведение `set_scale("ionian")` /
`set_scale("maj7")` не изменилось, таблица на замену должна содержать и их
(алиасы указывают на те же кортежи). Рекомендация — сохранить оба алиаса
(вопрос 1, §10).

### 4.2. Конструкция замены

Новый модуль **`src/harmony/scales.py`** (чистые данные + функции, без классов):

- `SCALES: dict[str, tuple[int, ...]]` — таблица выше (алиасы дублируют кортежи).
- `ROOT_PITCH_CLASSES: dict[str, int]` — имена нот → pitch class: `C=0, C#=1, Db=1,
  D=2, D#=3, Eb=3, E=4, F=5, F#=6, Gb=6, G=7, G#=8, Ab=8, A=9, A#=10, Bb=10, B=11`
  (порядок и альтерации идентичны `isobar.util.note_names`). Isobar принимает ещё
  имена с октавой (`"A4"`) и составные (`"A dorian"`) — проект таких не передаёт;
  замена сужается до pitch class, незнакомое имя → `HarmonyError` (сегодня — тоже
  исключение, обёрнутое в `HarmonyError`).
- `resolve_scale(name) -> tuple[int, ...]` — lookup с ошибкой.

`src/harmony/harmony.py` переписывается без isobar:

- `semitones` / `scale_length` — прямо из таблицы;
- `degree_to_semitone(degree)` = `root_pc + scales-резолвинг`;
- `degree_to_note(degree, octave)` = `degree_to_semitone(degree) + 12 * octave`
  (формула и сегодня такая же, `harmony.py:126`);
- валидация `_validate_harmonic` уже isobar-независима — ей нужен только кортеж
  полутонов и локальный `_degree_to_semitone` (он остаётся, это ровно isobar-математика:
  `divmod` с floor-семантикой, отрицательные ступени работают так же).

**Обязательный нюанс совместимости:** `Harmony.degree_to_semitone` возвращает смещение,
в которое **уже включена тоника** (это pitch-class-смещение от MIDI 0, а не «от тоники»,
как говорит докстринг). Проверка: A dorian, ступень 0 → `9 + 0 = 9`; ступень 8 →
`9 + 14 = 23` (`test_degree_to_semitone_wraps_octave_for_ninth`). Замена обязана
сохранить эту семантику 1:1; докстринг при переписывании исправить.

**Ступень 8 = нона (+14)** — перенос октавы через `divmod(degree, 7)`:
`divmod(8, 7) → (1, 1) → semitones[1] + 12`. Для дорийского: `2 + 12 = 14`, плюс
тоника `9` → `23`. Совпадает с isobar `Scale.get` (`octave = n // len; degree = n % len`).

### 4.3. Совместимость с voicings.py и остальным

`voicings.py`, `chord_math.py`, `note_drift.py`, движки потребляют только
`degree_to_note`, `semitones`, `scale_length` и константы — **менять их не нужно**.
`scale_length=7` в `mutation_engine.py`/`note_drift.py` — хардкод, согласован со всеми
8 ладами. Диатонические таблицы `voicings.py` — справочные, источником истины остаётся
вывод качества из ступеней.

### 4.4. Тест эквивалентности (обязателен, снимается ДО удаления isobar)

Пока isobar ещё установлен, одной фазой 1:

1. **Golden-фикстура**: одноразовый прогон генерирует таблицу `Key(root, scale).get(d)`
   для сетки `{10 имён} × {12 корней} × {степени −7..+21}` и сохраняет её статичным
   файлом-фикстурой (например, `tests/fixtures/isobar_key_golden.py` — словарь
   `(root, scale, degree) → int`). После удаления isobar фикстура остаётся эталоном.
2. Тест гоняет `Harmony.degree_to_semitone` против фикстуры — полное совпадение
   обязан быть 1:1 по всем MIDI-значениям.
3. Плюс рукописные якоря (уже есть в `test_harmony.py`): A dorian 8 → 23,
   degree_to_note 8 → 83; C major 0/2/4 → 60/64/67; A4 → 69.

---

## 5. Замена синхронизации

### 5.1. Контракт, который реально потребляется от isobar сегодня

| Операция | Где | Семантика today |
|---|---|---|
| `timeline.tick()` | `TickProxy._dispatch` (TICK) | Пустые проходы + `device.tick()` устройств + `current_time += 1/480` |
| `timeline.reset()` | `TickProxy` (RESET и START) | `current_time = 0.0` (START сознательно мапится на reset — не запускает внутренние часы) |
| `timeline.stop()` | `TickProxy` (STOP) | `CaptureOutput.all_notes_off()` (enqueue) + `CaptureOutput.stop()` (no-op) + `stop()` зомби-клока |
| `timeline.current_time` чтение | хук приложения ×6 (`application.py:515–549`), `clock_manager.py` ×5 (104, 245, 265, 305, 315) | Текущая позиция в битах, float |
| `timeline.current_time` запись | `clock_manager.py:330` | Восстановление фазы после смены источника (§5.4) |
| `timeline.output_devices` | `clock_manager._all_notes_off` | Список из одного `CaptureOutput` |
| `timeline.ticks_per_beat` | `tick_proxy.py:77` | 480 (делегируется в зомби-клок) |
| `timeline.tempo` запись | `application.py:966` | Мимо — пишет в зомби-клок; реальный темп ставится в `clock_src.tempo` (968) |
| `Clock.run()` | поток isobar (INTERNAL) | Тик-генерация 480 PPQN (§2.3) |

Всё остальное (треки, LFO, actions, статистика, warp) проекту не нужно.

### 5.2. Цепочка, которая должна сохраниться

```
источник (INTERNAL / MIDI / LINK)
  └─ tick()/start()/stop()/reset()   ← duck-typed к TickProxy
       └─ TickProxy (очередь, drop-oldest, один worker-поток)
            └─ hooked_dispatch (application.py):
                 TICK:  cm.on_tick()  →  midi_clock.on_position(beats)
                        →  mutation/drum/melodic engine.tick(beats)
                        →  session.propagate_chords()
                 затем original_dispatch → TimeBase.tick()   ← биты += 1/480
                 затем transport.process_events(beats)
```

Инварианты, которые нельзя нарушить: один worker-поток на всё время;
квантизация смены источника на границе доли (`on_tick` с допуском полтика
`_BEAT_EPSILON = 0.001`); watchdog `on_idle` (4 раунда ~0.4–0.5 с без прогресса →
переключение без квантизации); `all_notes_off` перед каждой сменой источника;
события Start/Stop транспорта уходят слушателям до активации/после остановки источника.

### 5.3. Варианты дизайна

**Вариант A — минимальный клон.** Свой `BeatClock` + «глупый» `TimeBase`, точно
воспроизводящий duck-typed интерфейс Timeline (включая `output_devices`, `tempo`).
Минимум диффа (~150 строк), `ClockManager`/`TickProxy`/хуки не меняются.
Минусы: легаси-поверхность сохраняется (`output_devices` на счётчике времени,
`tempo`-делегация в никуда), duck-typing остаётся неформализованным, Mode B
реализовать труднее.

**Вариант B — формализованный Protocol + TimeBase (рекомендация).**

- `src/sync/clock_source.py`: объявить **`ClockSource` Protocol** (ABC) — фиксация уже
  существующего duck-typed контракта всех трёх источников:
  `clock_target`, `ticks_per_beat`, `tempo` (get/set), `run()`, `stop()`, `background()`.
  `MidiClockInput.tempo` возвращает `float | None` — Protocol это допускает
  (см. `ClockState.bpm: float | None`). `_LinkClockSource` и `MidiClockInput`
  остаются как есть, INTERNAL ветка фабрики создаёт новый класс.
- **`src/sync/time_base.py`** — класс `TimeBase`, единственный владелец времени:
  - целочисленный счётчик тиков `_ticks: int`;
  - `current_time` — property `= _ticks / ticks_per_beat` (контракт «биты float»
    сохранён; на границе доли значение точное — float-дрейф накопления исчезает);
  - `tick()` (инкремент), `reset()` (→ 0), `stop()` (no-op: тишину делает
    `Transport.all_notes_off()` в хуке; enqueue `ALL_NOTES_OFF` через
    `CaptureOutput.all_notes_off()` сохраняется решением 2026-11-19 — см. §6.1);
  - `set_beats(beats)` — для восстановления фазы (§5.4);
  - `ticks_per_beat: int = 480` (константа контракта; `smf_writer` уже использует 480).
  Никаких `output_devices`: `ClockManager._all_notes_off` переключается на
  notes-off-callback (`ClockManager` получает `notes_off: Callable[[], None] | None`,
  приложение привязывает к `capture.all_notes_off` — design D2).
- **`src/sync/internal_clock.py`** — класс `InternalClockSource`: тот же алгоритм, что
  isobar `Clock` (абсолютное планирование `tick_start += duration`, догон пропущенных
  тиков батчем, `background()` в daemon-потоке, live-пересчёт длительности при смене
  `tempo`), но:
  - источник времени — `time.perf_counter()` вместо `time.time()`
    (монотонность; устраняет NTP-риск из плана v5.4 §5.1 — вопрос 3, §10);
  - множитель тиков — целочисленное деление `target_tpb // own_tpb` с проверкой
    делимости (в проекте всегда 1), вместо генератора `make_clock_multiplier`;
  - `stop()` через `Event` (как у `_LinkClockSource`).
- `ClockManager`: вместо `self._timeline` — `self._time_base`; tempo-установку
  приложения (`set_sync_bpm`) направлять в `ClockManager.set_tempo(value)` → активный
  источник (убирает зомби-запись `timeline.tempo`); остальная логика (pending,
  квантизация, watchdog, слушатели транспорта, fallback на internal) — без изменений.
- `TickProxy`: диспетчеризация в `TimeBase`; `ticks_per_beat` от `TimeBase`.

Плюсы: циклы исключены по построению (`time_base` и `internal_clock` не зависят ни от
кого в `src/`; `clock_source` тянется к `midi_clock_in` и лениво к `link`, как сегодня);
«один класс — один файл» соблюдён (`time_base.py`, `internal_clock.py`); duck-typing
становится явным контрактом; поведение источников MIDI/Link не меняется вовсе.
Минусы: чуть больше диффа, чем в A (~4 файла правок).

**Вариант C — полноценный BeatClock/TimeBase-домен.** Целочисленные тики везде,
пересчёт секунды↔биты с базой `perf_counter_ns`, подготовка к look-ahead Mode B,
события доли/такта. Избыточен сейчас: Mode B лишь заложен интерфейсом
(`TransportMode.EXTERNAL`, `NotImplementedError`), а события доли не нужны ни одному
потребителю. Элементы C (пересчёт секунд↔биты) понадобятся только при реализации
Mode B — зафиксировать как ориентир, не делать в этом change.

**Рекомендация: B.** Он убирает зомби-объекты и поток статистики isobar, формализует
интерфейс вместо duck-typing, минимально меняет поведение (только точность времени
становится лучше) и не блокирует будущий Mode B.

### 5.4. Запись `timeline.current_time = saved_beats` (clock_manager)

Место: `ClockManager._apply_pending`, шаг 5 восстановления фазы:

1. `saved_beats = self._timeline.current_time` (до остановки старого источника);
2. `_activate_source(...)` — новый источник стартует (для INTERNAL тики начинают
   приходить сразу, для MIDI возможен Start от устройства, который через
   `TickProxy.START → reset()` обнулил бы позицию);
3. `self._timeline.current_time = saved_beats` — фаза откатывается к сохранённой,
   тики, просочившиеся в окно активации (включая чужой reset), отбрасываются.

В isobar это присваивание публичного атрибута — на замене **`TimeBase.set_beats(beats)`**
делает ровно то же (публичный атрибут или метод — на усмотрение реализации; метод
явнее и проще типизируется). Потокобезопасность сохраняется автоматически: `_apply_pending`
выполняется в worker-потоке TickProxy (через `on_tick`/`on_idle`), то есть все записи
время-базы сериализуются с тиками. Тест `test_phase_preserved_on_switch` продолжает
работать против мока/реального `TimeBase`.

Смена BPM и `current_time`: isobar хранит время **в битах**, поэтому смена темпа не
требует пересчёта позиции (меняется только длительность тика в секундах). В замене —
то же: `current_time` остаётся битовым; смена BPM меняет лишь шаг потока тиков
INTERNAL-источника. Целочисленный счётчик дополнительно убирает накопленный
float-дрейф (сегодня `4.9995/5.0005` — «на доле» только благодаря допуску).

---

## 6. Чистка duck-typed адаптеров

### 6.1. `CaptureOutput` — оставить (решение пользователя, 2026-11-19)

Доказательства мёртвости:

- Timeline не имеет треков (`schedule()`/`add_track()` не вызываются) →
  `note_on/note_off/control` устройства **никогда не вызываются в рантайме**
  (только из тестов).
- Генерация событий идёт мимо него: `MelodicEngine._enqueue` и `DrumEngine` кладут
  `TransportEvent` прямо в тот же `event_queue`, который «захватывает» CaptureOutput.
- Живых обязанностей две: `all_notes_off()` (enqueue `ALL_NOTES_OFF` при STOP и смене
  источника) и `beat`-сеттер в хуке (`application.py:548`, значение никем не читается).

Последствия решения:

- `ClockManager._all_notes_off` → notes-off-callback: `ClockManager.__init__` принимает
  `notes_off: Callable[[], None] | None`, приложение привязывает к `capture.all_notes_off`
  (семантика enqueue в транспортную очередь — 1:1); в хуке `hooked_dispatch` ветка STOP
  после `original_dispatch` вызывает `capture.all_notes_off()` — точное воспроизведение
  сегодняшнего порядка enqueue-после-drain.
- STOP-артефакт §3 (отложенный CC123-бёрст после рестарта) ОСТАЁТСЯ — фиксируется как
  известное ограничение в AGENTS.md (фаза 3).
- Экспорт из `src/sync/__init__.py`, поле `self._capture` в `application.py` и
  `tests/test_capture_output.py` остаются; докстринги модуля переписываются без
  легаси-упоминаний isobar (tasks 3.1).

### 6.2. `MidiPortOutput` — остаётся, переосмысляется как собственный API

Адаптер никогда не регистрировался в `timeline.output_devices` — его «isobar-совместимость»
сводится к именам методов, общим с `CaptureOutput` (`note_on(channel, note, velocity)` и т. д.),
которые вызывают `Transport` и `ClockManager`. После удаления isobar это просто API
выходного порта: докстринги «isobar output device interface» → «интерфейс выходного порта».
Логика CC-маппинга/троттлинга/`send_realtime` не меняется.

### 6.3. int()-конверсии: что остаётся

Места с `int()`: конструкторы `TransportEvent` (`transport_event.py`), `MidiPortOutput`
(`routing.py`: `note_on/note_off/control_change/control/flush`), `Transport._deliver`/
`_deliver_note_on` (`transport.py`), `CaptureOutput` (модуль сохранён по решению 2026-11-19, `int()` остаются).

После удаления isobar **numpy в sync-слой не заходит** (numpy остаётся только в
`devices/push2/` — renderer/display, зависимость из pyproject не уходит). Все `int()`
становятся чистой защитой. Рекомендация: **оставить** их в `TransportEvent` и
`MidiPortOutput` — нулевая стоимость, страховка от будущих numpy-протечек (например,
при интеграции push2-данных в дорожки); убрать только комментарии «from isobar»
в докстрингах. У `Transport._deliver` защиту можно сохранить из `TransportEvent`
(дублирование `int()` там — вопрос вкуса, менять не обязательно).

---

## 7. Свинг: фактическое состояние

Схема (сверено по коду, plan v5.4 §4.2 реализован):

- **Единственная точка применения** — `Transport._schedule`
  (`transport.py:258: delay = self._swing.shift(event.beat)`): сдвигаются только
  NOTE_ON; отложенные события ждут в буфере `_held`, выпускаются `_release_due`.
  NOTE_OFF не сдвигается — длина пары сохраняется.
- `MelodicEngine._note_to_events` свинг **не применяет** (`melodic_engine.py:313–314`:
  «Свинг здесь не применяется: он живёт в Transport»). Отсутствие применения —
  комментарием и кодом, не только словом.
- `Transport._deliver_note_off` **не существует** (grep — 0 совпадений).
- Свинг действует на все дорожки (melodic + drum) — by design (`swing.py`).
- Состояние свинга сбрасывается в `Transport.all_notes_off()` и `SwingApplier.reset()`.

Что остаётся сделать в фазе «свинг»:

1. **Документационная чистка устаревших записей**: `AGENTS.md` → «Известные ограничения»
   (пункт про двойное применение свинга и `Transport._deliver_note_off` удалить);
   докстринг `melodic_engine.py:16` («gate и свинг применяются к длительности до
   планирования» — устаревшая фраза, свинг там не применяется); историческая строка
   `transport.py:25` («int() на всех значениях из isobar»); докстринг `swing.py:3`.
2. **Регрессионный тест-страж** «двойного применения нет»: для события, прошедшего
   через движок и транспорт, `onset_фактический − beat == shift(beat)` ровно один раз
   (частично покрыто `test_swing.py`/`test_transport.py` — добавить явный сквозной
   тест melodic_engine → transport).
3. Вынос «свинга из Transport» как миграции (из старого техдолга) — **не требуется**:
   единственная точка уже соответствует цели. Режим Mode B (свой поток отправки)
   остаётся вне скоупа.

---

## 8. Порядок фаз

Обоснование: гармония изолирована и не влияет на клок — делаем первой, чтобы
(a) снять golden-фикстуру с живого isobar до его удаления, (b) сразу уменьшить
mypy-baseline. Клок — самая рискованная часть, идёт второй при уже чистой гармонии.
Чистка — только после того, как рантайм больше не трогает isobar. Свинг — хвост,
потому что это документация + тест, зависящие от финального вида transport-слоя.

| Фаза | Содержание | Критерий готовности |
|------|-----------|---------------------|
| **1. Гармония** | Golden-фикстура из isobar `Key.get`; `src/harmony/scales.py`; переписать `harmony.py` (без `Key`/`Scale`/`Timeline`, удалить `key`/`apply`, исправить докстринг `degree_to_semitone`); тест эквивалентности против фикстуры | Тесты зелёные; эквивалентность 1:1; ruff/black чисто; mypy без новых (baseline улучшится: −2 import-untyped isobar) |
| **2. Клок** | `src/sync/time_base.py`, `src/sync/internal_clock.py`; `ClockSource` Protocol; фабрика INTERNAL → `InternalClockSource`; `ClockManager` на `TimeBase`, `_all_notes_off` → notes-off-callback (design D2), `set_tempo()`; `TickProxy` → `TimeBase`; хук `application.py` на `time_base.current_time`; `set_sync_bpm` через `ClockManager` | Тесты зелёные (обновлённые + новые `test_time_base`, `test_internal_clock`); smoke `--simulate`; контракт времени: 480 PPQN, `current_time` в битах float; квантизация/фаза/idle-watchdog не деградировали |
| **3. Чистка** | Докстринги `capture_output.py` без легаси-isobar (модуль и тест остаются); экспорты `src/sync/__init__.py` без изменений; докстринги (`tick_proxy`, `routing`, `transport`, `transport_event`, `swing`, `euclidean`, `melodic_engine:16`, `melodic_track:282`); `TransportMode.ISOBAR` → `TICK_THREAD` (решение 2026-11-19); `pyproject.toml` (зависимость + description); `AGENTS.md` (стек, baseline линтеров, техдолг-список, известное ограничение STOP-артефакта, env `ISOBAR_DEFAULT_MIDI_IN` в докстрингах sync); `docs/track-hierarchy.md` (2 строки); `uv sync` для `uv.lock` | `grep -r isobar src tests pyproject.toml` — 0 совпадений; тесты зелёные; линтеры без новых замечаний |
| **4. Свинг-хвост** | Удалить устаревший пункт техдолга из `AGENTS.md`; сквозной регрессионный тест «свиг применяется один раз»; финальный smoke `--simulate` | Тест зелёный; `AGENTS.md` согласован с кодом |

После фазы 2 isobar в рантайме уже не участвует (все три роли заменены), но удалять
зависимость из `pyproject.toml` — только в фазе 3, вместе с чисткой упоминаний.

---

## 9. Оценка объёма

### 9.1. Новые модули

| Путь | Содержание | Оценка строк |
|------|-----------|--------------|
| `src/harmony/scales.py` | Таблица 8 ладов (+2 алиаса), имена нот → pitch class, `resolve_scale` | ~90 |
| `src/sync/time_base.py` | Класс `TimeBase` (счётчик тиков, `current_time`, `set_beats`, `ticks_per_beat`) | ~110 |
| `src/sync/internal_clock.py` | Класс `InternalClockSource` (perf_counter, догон, tempo, background/stop) | ~130 |

Слои: оба новых модуля `src/sync/` — stdlib-only, ниже `clock_source`/`clock_manager`;
`src/harmony/` остаётся чистым. Циклов нет.

### 9.2. Изменения в существующих файлах

| Файл | Тип правки | Оценка дельты |
|------|-----------|---------------|
| `src/harmony/harmony.py` | переписать (177 строк) | ±40 |
| `src/sync/clock_source.py` (285) | Protocol + INTERNAL ветка + докстринги | +60 / −20 |
| `src/sync/clock_manager.py` (402) | `_timeline` → `_time_base`, `_all_notes_off` → notes-off-callback (design D2), `set_tempo` | +25 / −15 |
| `src/sync/tick_proxy.py` (186) | время-база + докстринги | ±10 |
| `src/app/application.py` (1010) | `_init_clock_manager`, хук, `set_sync_bpm`, `_capture` остаётся (решение 2026-11-19) + notes-off-callback + ветка STOP в хуке | +35 / −35 |
| `src/sync/capture_output.py` (189) | докстринги (модуль остаётся) | ±10 |
| `src/sync/__init__.py` | экспорты | ±5 |
| `src/sync/transport.py` (352) | докстринги + опц. переименование enum | ±10 |
| `src/sync/transport_event.py` (146), `src/sync/routing.py` (401), `src/sync/swing.py` (~150) | докстринги | ±15 |
| `src/session/model/euclidean.py` (120), `src/session/engine/melodic_engine.py` (356), `src/session/model/melodic_track.py` | докстринги | ±10 |
| `pyproject.toml`, `AGENTS.md`, `docs/track-hierarchy.md`, `uv.lock` | конфиг/доки/лок | ±10 |

Итого: ~12 файлов `src/` с содержательными правками (из них 3 — с прямыми импортами),
3 новых модуля, 1 удалённый. Новый код порядка 350–400 строк, удаление ~250–300,
докстринги ~50.

### 9.3. Тесты

| Тест | Действие |
|------|----------|
| `tests/test_harmony.py` | Расширить: golden-фикстура (сетка имена × корни × степени), якорные значения уже есть |
| `tests/test_time_base.py` | **Новый**: счёт тиков, точность на границе доли, `reset`, `set_beats`, `ticks_per_beat` |
| `tests/test_internal_clock.py` | **Новый**: темп (get/set), генерация тиков по fake-цели, догон пропущенных, `stop`/`background`, множитель 480/480 |
| `tests/test_clock_source.py` | Обновить: фабрика INTERNAL создаёт `InternalClockSource` (докстринг «isobar.Clock» устарел); MIDI/LINK тесты не меняются |
| `tests/test_clock_manager.py` | `MockTimeline` → фейковый `TimeBase`; тесты фазы (`test_phase_preserved_on_switch`, epsilon-границы, watchdog) сохраняются; тест `all_notes_off` → notes-off-callback |
| `tests/test_tick_proxy.py` | Обновить мок Timeline → TimeBase |
| `tests/test_capture_output.py` | Остаётся (решение 2026-11-19); проверка notes-off-callback ClockManager добавляется рядом |
| `tests/test_midi_clock_in.py`, `tests/test_midi_clock_out.py`, `tests/test_routing.py`, `tests/test_transport.py` | Докстринги; `test_transport` — опционально имя enum; `_Timeline`/`_Proxy` стабы → `TimeBase` |
| `tests/test_swing.py` / `test_transport.py` | Добавить сквозной тест «свиг применяется ровно один раз» (фаза 4) |

Прогресс тестов по плану: сейчас 1945 passed; после фазы 3 счёт изменится
(+2 новых файла: `test_time_base`, `test_internal_clock`; `test_capture_output` остаётся) — пересчитать и обновить `AGENTS.md`.

---

## 10. Риски и открытые вопросы

### 10.1. Риски

| Риск | Оценка | Митигация |
|------|--------|-----------|
| Точность/jitter своего тик-потока vs isobar `Clock` | Низкая | Алгоритм переносится 1:1 (абсолютное планирование + догон). `perf_counter` вместо `time.time()` — строго лучше (монотонность). Sleep-гранулярность та же (0.1 мс). Проверка в `--simulate`; железо (RPi5) — вне скоупа, есть спайки `spike_stress.py`/`spike_display.py` для последующего прогона |
| Поведение `current_time` при смене BPM | Низкая | Время в битах в обеих реализациях — пересчёт не нужен; целочисленный счётчик убирает накопленный float-дрейф (сейчас epsilon-допуск маскирует дрейф; допуск сохраняем — на случай внешних источников) |
| Тонкие эффекты смены источника (окно активации, idle-watchdog) | Средняя | Логика `ClockManager` не меняется; меняется только объект времени. Покрытие уже есть (фазовые тесты, watchdog, порядок событий транспорта в `test_midi_clock_out.py`) |
| Скрытые зависимости от поведения `Timeline.stop()` (enqueue `ALL_NOTES_OFF`) | Низкая | Enqueue сохраняется через notes-off-callback (design D2); STOP-артефакт — известное ограничение; `Transport.all_notes_off()` в хуке делает тишину синхронно |
| Golden-фикстура не покрывает будущие лады | Низкая | Фикстура генерируется для полного текущего набора (10 имён); расширение набора — отдельное решение (валидация `_validate_harmonic` остаётся воротами) |
| Линтеры/типы: сдвиг baseline | Низкая | mypy теряет import-untyped isobar (~3–4 ошибки) — baseline зафиксировать заново после фазы 1 и фазы 3; правило «без новых замечаний» сохраняется |
| `uv.lock` и окружение RPi | Низкая | `uv sync` после правки `pyproject.toml`; на RPi5 пересинхронизация — при следующем деплое (вне скоупа) |
| Регрессии в E2E-сценариях `spike_ui_simulate` (сценарии 1–9 включают смены клока) | Низкая | Smoke-прогон `--simulate` в фазах 2 и 4 обязателен |

### 10.2. Открытые вопросы к пользователю

> **Решения (2026-11-19):**
> 1. Алиасы ладов `ionian`/`maj7` — сохранить в таблице.
> 2. `TransportMode.ISOBAR` — переименовать в `TICK_THREAD` (в скоупе).
> 3. `InternalClockSource` — на `time.perf_counter()`.
> 4. `CaptureOutput` — оставить (докстринги правятся, модуль и тест не удаляются); STOP-артефакт остаётся известным ограничением.

1. **Алиасы ладов**: сохранить `ionian`/`maj7` в таблице (сегодня проходят `set_scale`,
   рекомендация — сохранить, чтобы не менять поведение), или сузить до 8 канонических имён?
2. **Переименование `TransportMode.ISOBAR`**: имя enum-значения — легаси. Рекомендация —
   переименовать в `TransportMode.TICK_THREAD` (смысл: доставка в потоке TickProxy);
   допускается оставить имя до реализации Mode B.
3. **`time.perf_counter()` в `InternalClockSource`** вместо `time.time()` isobar:
   рекомендация — да (монотонность, устранение NTP-риска из плана v5.4); альтернатива —
   побайтно повторить isobar со стенными часами.
4. **Удаление `CaptureOutput`** меняет поведение STOP (исчезает отложенный CC123-бёрст,
   §3/§6.1). Рекомендация — принять; подтверждение не критично, но фиксируем как
   осознанное изменение.

---

## 11. Критерии приёмки

Финальный чек-лист (из брифа):

- [ ] `grep -r isobar src/ tests/` — 0 импортов и 0 упоминаний в коде;
- [ ] `pyproject.toml`: зависимости и description-строка без `isobar`; `uv.lock` пересобран (`uv sync`);
- [ ] все тесты проходят (пересчитанный счёт зафиксирован в `AGENTS.md`);
- [ ] ruff/black/mypy — без НОВЫХ замечаний (baseline переснят после фаз 1 и 3;
      ожидается улучшение mypy на import-untyped isobar);
- [ ] smoke-прогон `python -m src.main --simulate` (фазы 2 и 4);
- [ ] контракт времени сохранён: 480 PPQN, `current_time` в битах (float),
      квантизация смены источника на границе доли работает, фаза восстанавливается
      (`test_phase_preserved_on_switch`);
- [ ] три источника клока (internal/MIDI/Link) работают: юнит-тесты фабрики и
      источников; MIDI/Link-код не изменялся (кроме докстрингов);
- [ ] `Harmony.degree_to_note`/`degree_to_semitone` эквивалентны isobar `Key.get`
      1:1 на golden-фикстуре;
- [ ] numpy остаётся в зависимостях (push2 renderer/display) — из pyproject не удалять.

Вне скоупа (не трогать в этом change): numpy; mido/python-rtmidi; мигание дисплея
TRACKS/VERSIONS (текстовый флаг); D3 (режимы пада), хвосты E1/E2/C2; реализация
Transport Mode B (только заложенный интерфейс); ручной прогон UI на железе и
RPi5-прогон (спайки — отдельная работа); LCXL3 DAW-режим CC→DIN Out (A1 п.6);
исторические документы `docs/push2_dubtechno_plan_v5_4.md` и `plans/*.md`.

---

## 12. Следующий шаг

После ревью этого документа — OpenSpec change `replace-isobar` (корень `openspec/`
существует): proposal с фазами §8, дельта-spec на контракт времени (480 PPQN,
`current_time` в битах, квантизация, восстановление фазы) и на таблицу ладов
(§4), design с выбором варианта B и tasks по фазам. Этот документ остаётся
обоснованием решений.