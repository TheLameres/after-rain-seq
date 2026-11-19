# C6: Профили ↔ Isobar-паттерны: генерация, бит-планировщик, механизмы мутации

> Задача C6 (план C, Фаза 3, продолжение). Дата плана: 2026-11-02.
> Зависимости: C1–C5, B1–B4 — все завершены.
> Связанные документы: `../track-hierarchy.md`, `AGENTS.md` (C3/C5), `push2_dubtechno_plan_v5_4.md` (§1.4, §4.1, §5.1, §6).

---

## 1. Цель

Связать профили мелодических дорожек (`MelodicProfile`) с реальной генерацией
музыкального материала: isobar-паттерны (как генераторы значений), чтение
гармонии из графа дорожек и три механизма мутации (NoteDrift / FloatingEuclidean /
ParamDrift). Сейчас всё это существует по отдельности, но не соединено.

**Результат:** дорожка с профилем `seq` играет нарезку аккордов Pad 1 по
евклидову паттерну, дрейфующему от FloatingEuclidean; мутация слышна; события
доставляются точно в бит, без дублирования.

---

## 2. Текущее состояние и разрывы

Что уже есть (проверено чтением кода):

- `MelodicTrack.generate()` — заглушка: `emits_chords` играет целые аккорды
  из `degrees` (без паттернов), `reads_source` не нарезает, а `inject_sources()`
  просто копирует чужой outbox.
- `MelodicEngine.tick()` — конвертирует `ChordEvent → TransportEvent` и кладёт
  в очередь; velocity захардкожена 100.
- `MutationEngine` — три механизма тикают, их состояние **никто не читает**
  (геттеры `get_note_drift()` и т.д. есть, вызовов нет).
- `Transport.process_events()` — доставляет всё из очереди **немедленно**,
  без учёта `beat` события.
- isobar в проекте — только `Key`/`Scale`/`Timeline` (клок + гармония).
  Паттерн-классы (`PSequence`, `PLoop`, `PWhite`, `PEuclidean`) не используются.
  На Timeline не зарегистрирован ни один паттерн.

### Найденные разрывы

| # | Разрыв | Симптом |
|---|--------|---------|
| R1 | Нет бит-планирования | `MelodicEngine.tick()` вызывается на каждый MIDI-тик (480 PPQN) и каждый раз кладёт в очередь **весь паттерн целиком**; Transport доставляет немедленно → дублирование нот, события не попадают в свой бит |
| R2 | Мутация не влияет на звук | NoteDrift/FloatingEuclidean/ParamDrift дрейфуют внутри MutationEngine, генератор читает только `track.degrees`/`track.gate` |
| R3 | Граф мёртв в рантайме | `inject_sources()` вызывается только из тестов; в `hooked_dispatch` (application.py) фазы инжекции нет → sub/stab/seq/arp не получают `ChordEvent` источников |
| R4 | Пробелы в матрице профиль→механизм | `sub` и `stab` не имеют механизма мутации; velocity всегда 100; `DrumEngine._swing_bpm()` — заглушка 120.0 (TODO в коде) |

---

## 3. Архитектурные решения

### 3.1. isobar — библиотека паттернов, не планировщик

**Решение:** использовать isobar pattern-классы как чистые генераторы значений
(ручной `next()`), а **не** регистрировать паттерны на isobar Timeline.

Обоснование:
- Уже построен собственный стек доставки: TickProxy → движки → Transport →
  PortRegistry со swing, CC-троттлингом и `all_notes_off`. Планировщик isobar
  продублировал бы его и конфликтовал со свингом (свой, бит-точный) и троттлингом.
- Timeline остаётся источником тиков и владельцем `current_time` — как сейчас.
- Горизонт планирования и точность доставки под нашим контролем.

### 3.2. Бит-планировщик с lookahead (исправляет R1)

В `MelodicEngine` — окно планирования **H = 1 такт (4 beats)**:

1. Атомарный «вотермарк» `scheduled_until` на дорожку.
2. На каждом тике: доставить все pending-события с `beat <= current_beat + ε`,
   затем, если `current_beat + H > scheduled_until`, достроить расписание
   `[scheduled_until, current_beat + H)`.
3. События с `beat < current_beat - ε` (опоздавшие) — пропускать с логом,
   не играть пачкой.
4. Планирование в beats, не в секундах — смена BPM не ломает расписание.

Задержка применения мутации ≤ 1 такт (пересборка на границе горизонта) —
музыкально корректно: изменения вступают на тактовой границе.

### 3.3. Профили — данные, генерация — функции (согласно track-hierarchy.md)

Класс на профиль **не создаём**. Расширяем `MelodicProfile` полями спецификации
паттерна; `generate()` остаётся один, ветвление — на уровне данных через
таблицу семейств генераторов. Семейств ровно четыре (структурно разные способы
порождения нот):

| Семейство | Профили | Суть |
|-----------|---------|------|
| `chord_source` | pad, atmos | Собственная прогрессия `degrees` → аккорды целиком; публикуют `ChordEvent` в outbox (граф) |
| `chord_slicer` | sub, stab, seq, arp | Читают `ChordEvent` источников, нарезают/переозвучивают своим паттерном |
| `free_mono` | bass, lead, texture | Одна линия из собственных ступеней, без чтения источников |
| `cc_only` | cc_filter, cc_space | Нот нет; CC в отдельной задаче (см. §9) |

### 3.4. Матрица профиль → поведение → механизм мутации (исправляет R4)

| Профиль | Семейство | Паттерн (isobar-классы) | Механизм мутации |
|---------|-----------|--------------------------|------------------|
| `pad` | chord_source | `PLoop(degrees)`, 1 аккорд/такт, длит. = такт × gate | ParamDrift (gate, density, register) |
| `atmos` | chord_source | `PLoop(degrees)`, смена аккорда раз в `change_every` тактов (дефолт 8) | ParamDrift (gate, register) |
| `sub` | chord_slicer | Корень (`degrees[0]`) аккорда источника, октава 1–2, сдвиг на долю аккорда, gate ≈ 1.0 | **ParamDrift (register, gate)** — новое |
| `stab` | chord_slicer | Аккорд источника целиком, нарезка евклидом 16 шагов, gate 0.1–0.3, смещение `PWhite` | **FloatingEuclidean (16, 3–5)** — новое |
| `seq` | chord_slicer | Ступени аккорда источника по сетке 16, паузы по `PEuclidean`, плотность из density | FloatingEuclidean |
| `arp` | chord_slicer | Обход ступеней аккорда вверх/вниз (`PSeq` + реверс), 1/8–1/16 | FloatingEuclidean |
| `bass` | free_mono | `PLoop(degrees)` короткими нотами (степень = корень аккорда) | ParamDrift (gate, register) |
| `lead` | free_mono | `PWalk`-дрейф в пределах лада (NoteDrift.current_degrees) | NoteDrift |
| `texture` | free_mono | Редкие одиночные ступени/кластеры, раз в 8–16 тактов | NoteDrift |
| `cc_*` | cc_only | — (отдельная задача) | пропуск, как сейчас |

Смена root/scale через `Harmony` не трогает паттерны — ступени резолвятся
в ноты в момент конвертации (`Harmony.degree_to_note`), как сейчас.

### 3.5. Оживление графа (исправляет R3)

Фаза распространения гармонии — часть достраивания горизонта, в топологическом
порядке (уже есть `Session.ordered_tracks()`):

1. Источники (`emits_chords`) генерируют `ChordEvent` на окно `[watermark, watermark+H)`.
2. `Session` инжектит их наследникам (`inject_sources()` — уже написан).
3. Наследники нарезают полученные `ChordEvent` своими генераторами.

Оркестратор — не MelodicEngine (у него нет доступа к соседям), а координатор
на уровне App/Session: в `hooked_dispatch` перед тиками движков одна фаза
`session.propagate_chords(until_beat=...)`, затем каждый движок достраивает
своё расписание.

### 3.6. Канал мутации → генерация (исправляет R2)

`MelodicEngine` при достраивании горизонта собирает контекст:

```
GenerationContext(
    track=...,                # статичные параметры (профиль, voicing, octave, …)
    chord_window=[...],       # ChordEvent источников на окно (у slicer'ов)
    note_drift=...,           # от MutationEngine.get_note_drift(name)
    euclidean=...,            # от get_euclidean_drift(name)
    param_drift=...,          # от get_param_drift(name)
)
```

Генераторы — чистые функции `generate_notes(ctx) -> list[NoteEvent]`,
читающие **текущее** состояние механизмов (`current_degrees`, `pattern`,
`get("gate")`). Freeze (`mutate=0`) — механизмы перестают дрейфовать, паттерн
играет замершим — бесплатно из существующей семантики.

---

## 4. Новые и изменяемые файлы

| Файл | Действие | Содержимое |
|------|----------|------------|
| `src/session/note_event.py` | **новый** | `NoteEvent` frozen dataclass: `beat, degree, velocity, duration` — одна нота в ступенях лада; одна точка конвертации degree→MIDI (через Harmony, в движке) |
| `src/session/pattern_spec.py` | **новый** | Расширение профилей как данные: `PatternSpec` (family, steps, base_pulses, change_every, velocity_base, velocity_accent, sub_shift, arp_direction) + дефолты; `MelodicProfile` получает поле `pattern: PatternSpec` |
| `src/session/generators.py` | **новый** | Таблица `GENERATORS: family → fn(ctx) -> list[NoteEvent]` + четыре функции семейств; isobar-паттерны создаются/шагаются здесь; кеширование паттерна до следующей мутации |
| `src/session/beat_scheduler.py` | **новый** | `BeatScheduler`: pending-события по beat, `due(now)`, `extend(until)`, watermark, пропуск опоздавших; без потоков — вызывается из dispatch-хука |
| `src/session/melodic_track.py` | изменить | `generate()` делегирует в `generators.py`; публикация `ChordEvent` в outbox производится отсюда же (источники); чтение механизмов — нет (только контекст) |
| `src/session/melodic_engine.py` | изменить | BeatScheduler внутри; сборка `GenerationContext` из MutationEngine; velocity из события (не 100); резолв degree→note через Harmony при доставке |
| `src/session/mutation.py` | изменить | Маппинг `sub → ParamDrift(register, gate)`, `stab → FloatingEuclidean`; константы-таблица `PROFILE_MECHANISM` вместо размазанных `in`-проверок |
| `../src/session/session.py` | изменить | `propagate_chords(until_beat)`: источники генерируют на окно → `inject_sources()` по топо-порядку; idempotent-защита от двойного инжекта на том же окне |
| `../src/app/application.py` | изменить | В `hooked_dispatch`: фаза `propagate_chords` перед тиками движков; проброс реального bpm (`ClockManager`/timeline) в DrumEngine и MutationEngine |
| `src/session/drum_engine.py` | изменить | Убрать заглушку `_swing_bpm()` — bpm приходит извне (аргумент `tick()` или сеттер) |
| `../spikes/spike_midi_sink.py` | **новый** | Dummy MIDI-приёмник на mido: виртуальный порт + печать входящих сообщений с метками времени; служит критерию приёмки №5 |
| Тесты | **новые** | `../tests/test_note_event.py`, `tests/test_beat_scheduler.py`, `tests/test_generators.py`, правки `test_melodic_engine.py`, `test_mutation.py`, `test_session.py` |

---

## 5. Этапы реализации

### Шаг 1: NoteEvent + BeatScheduler + починка дублирования (R1)

- `note_event.py`, `beat_scheduler.py`.
- `MelodicEngine` переписан на «доставить due → достроить горизонт».
- Генерация на шаге 1 — текущая (целые аккорды), но уже **по расписанию**:
  одна нота — один раз, в свой бит.
- Тесты: watermark не дублирует; due выбирает по beat; опоздавшие
  пропускаются; горизонт достраивается один раз на окно; H=4 beats.

### Шаг 2: Генераторы профилей (chord_source + free_mono)

- `pattern_spec.py` + `generators.py`: семейства `chord_source` и `free_mono`.
- pad/atmos/bass/lead/texture играют осмысленный материал: гейты, change_every
  у atmos, PWalk у lead, velocity base/accent вместо 100.
- Тесты: каждый профиль даёт ноты в ожидаемых битах; границы gate;
  NoteDrift.current_degrees влияют на lead.

### Шаг 3: Оживление графа (R3) + chord_slicer

- `Session.propagate_chords()` + фаза в `hooked_dispatch`.
- Генераторы `chord_slicer`: sub (корень + сдвиг), stab (евклид + короткий
  gate), seq (ступени по сетке), arp (обход вверх/вниз).
- Тесты: sub/stab/seq/arp молчат без источников (стратегия B); с источником —
  нарезка совпадает с аккордами; сдвиг sub на долю; смена аккорда меняет нарезку.

### Шаг 4: Мутация, влияющая на звук (R2) + матрица механизмов (R4)

- Контекст в MelodicEngine; `PROFILE_MECHANISM` с sub/stab.
- Тесты: после `MutationEngine.tick()` ноты lead меняются; pulses меняют
  нарезку stab/seq; gate из ParamDrift меняет длительности pad; freeze
  останавливает изменения.

### Шаг 5: Проброс BPM, dummy MIDI-приёмник и приёмка

- bpm из ClockManager в DrumEngine/MutationEngine (R4, TODO в коде).
- **E2E-проверка через dummy-программу на mido** (`../spikes/spike_midi_sink.py`):
  1. Приёмник создаёт виртуальный порт (`mido.open_input(..., virtual=True)`,
     macOS/RTMidi) и печатает все входящие сообщения (note_on/note_off/
     control_change) с меткой времени.
  2. В `../config.yaml` добавляется output-порт с `match` на имя виртуального
     порта; дорожки маршрутизируются на него (`track route`).
  3. Приложение запускается (на Mac — без Push 2, через `--simulate`/`--repl`),
     приёмник — в соседнем терминале.
  4. Проверяется: ноты доходят (note_on с ожидаемыми channel/note/velocity),
     события идут **однократно** (нет дублей на тик), ритм попадает в бит
     (по меткам времени и bpm), `freeze`/`evolve` меняют поток сообщений.
- Ручная проверка `main --repl --simulate`: паттерны идут, нет дублирования,
  `track mutate`/`freeze` слышны (по логам событий).
- Регрессия: весь pytest зелёный, ruff/mypy/black чисто.

---

## 6. Краевые случаи

- **Смена профиля на лету** (`set_profile`): пересоздание механизма в
  MutationEngine (`unregister/register`), сброс watermark → пересборка с
  нового такта; `all_notes_off` не нужен (гейт затихает сам), но pending
  старого профиля вычищается.
- **Потеря/удаление источника** (стратегия B): после текущего горизонта —
  тишина; дорожка не падает, настройки сохраняются.
- **Смена BPM**: расписание в beats — не ломается; интервалы мутации
  пересчитываются (уже есть `set_bpm*`).
- **Смена root/scale**: degrees неизменны, резолв через Harmony — смена
  лада мгновенно слышна на всех дорожках (достоинство degree-модели).
- **Полная очередь**: drop-oldest (уже везде), лог warning.
- **Быстрый стоп/старт транспорта**: reset watermark и pending при STOP,
  чтобы не играть «прошлое».
- **Цикл в графе**: ловится на сборке (`ordered_tracks()`), до первого тика —
  без изменений.

---

## 7. Критерии приёмки

1. Каждая нота доставляется ровно один раз, в свой бит (тест BeatScheduler +
   e2e-лог событий в `--simulate`).
2. Мутация слышна: после серии тиков MutationEngine материал lead/stab/seq/pad
   отличается от базового (тесты + ручной прогон).
3. sub/stab/seq/arp играют из ChordEvent источников; без источника — тишина.
4. Все существующие тесты зелёные; ~80 новых; ruff/mypy/black чисто.
5. **E2E: MIDI-сигнал доходит до dummy-программы на mido.** Приёмник
   (`../spikes/spike_midi_sink.py`, виртуальный порт) получает note_on/note_off
   от приложения: ожидаемые channel/note/velocity, однократно (без дублей),
   в бит (по меткам времени и bpm); `freeze`/`evolve` меняют поток сообщений.
6. `--repl --simulate`: `status`, `track mutate <name> 0/1`, `freeze`/`evolve`
   меняют звук (по логам), без Push 2.

---

## 8. Не-цели (явно исключено)

- Регистрация паттернов на isobar Timeline (двойной планировщик) — нет.
- Transport Mode B (EXTERNAL) — без изменений, отложено.
- UI (D2/D3): экраны и пады — позже, эта задача даёт им материал для
  отображения (плейхед, density).
- Генерация CC для `cc_filter`/`cc_space` (паттерны значений + CCMap) —
  отдельная задача; здесь профили остаются молчащими, как сейчас.
- Пользовательские паттерны/редактор сеток — не требуется.
