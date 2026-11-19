# План: рефакторинг пакета `../src/session` на подпакеты

> Дата: 02.11.2026
> Статус: план, к выполнению
> Тип: чистый рефакторинг — **никаких изменений логики и поведения**

---

## 1. Проблема

`../src/session` — плоский пакет из **20 модулей, 3 462 строки**. За него отвечают
пять задач (C3–C6, F1-дополнения), и границы между доменами размыты:

| Симптом                                                        | Где                                                                               | Почему плохо                                                                                 |
|----------------------------------------------------------------|-----------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------|
| `mutation.py` — 714 строк, 5 классов + 2 таблицы в одном файле | `mutation.py`                                                                     | Нарушает правило «один класс — один файл» из AGENTS.md                                       |
| Lazy-import как костыль против цикла                           | `melodic_track.py:90,158` (`from src.session.generators import …` внутри методов) | `chord_degrees_for`/`pattern_length_for` — чистая математика, которую модель тянет из движка |
| Евклидова математика лежит рядом с дорожками                   | `euclidean.py` на корне                                                           | Используется мутацией и генераторами, к дорожкам отношения не имеет                          |
| События, модель, движки, мутация, граф — всё в одной куче      | корень пакета                                                                     | Невозможно понять layering, не прочитав все импорты                                          |

## 2. Цели и не-цели

**Цели:**

- 6 подпакетов со строгим layering (импорты только вниз).
- `mutation.py` разбит по классам.
- Lazy-импорты из `melodic_track` устранены переносом математики вниз по слоям.
- Публичный API пакета **не меняется** — `../src/session/__init__.py` остаётся фасадом.
- Все 1012+ тестов зелёные после каждой фазы.

**Не-цели:**

- Никаких изменений поведения, алгоритмов, публичных сигнатур.
- Не решаем техдолг из C6 (двойной свинг, on-demand мутация) — отдельные задачи.
- Не трогаем `../src/sync`, `src/harmony/`, `src/app/` кроме обновления импортов.

## 3. Целевая структура

```
src/session/
├── __init__.py              # ФАСАД: реэкспорт публичного API (содержимое — как сейчас + новые имена)
├── events/                  # слой 0: события (ни от кого не зависят)
│   ├── __init__.py
│   ├── chord_event.py       # ChordEvent        (перенос)
│   ├── note_event.py        # NoteEvent         (перенос)
│   └── drum_event.py        # DrumEvent         (перенос)
├── model/                   # слой 1: доменная модель дорожек (зависит от events, harmony)
│   ├── __init__.py
│   ├── track.py             # Track ABC         (перенос)
│   ├── melodic_track.py     # MelodicTrack      (перенос, минус lazy-импорты)
│   ├── drum_track.py        # DrumTrack         (перенос)
│   ├── drum_lane.py         # DrumLane          (перенос)
│   ├── melodic_profile.py   # MelodicProfile + PROFILES (перенос)
│   ├── pattern_spec.py      # PatternSpec       (перенос)
│   ├── euclidean.py         # PEuclideanCached  (перенос — чистая математика ритма)
│   └── chord_math.py        # НОВЫЙ: chord_degrees_for, pattern_length_for
│                            #        (выделено из generators.py)
├── mutation/                # слой 2: дрейф параметров (зависит только от model/euclidean)
│   ├── __init__.py
│   ├── mutation_state.py    # MutationState     (выделено)
│   ├── note_drift.py        # NoteDrift         (выделено)
│   ├── floating_euclidean.py# FloatingEuclidean (выделено)
│   ├── param_drift.py       # ParamDrift + _DriftParam (выделено)
│   ├── drift_tables.py      # PROFILE_MECHANISM, PARAM_DRIFT_PARAMS, MECH_*, MUTATE_*_SECONDS (выделено)
│   ├── mutation_engine.py   # MutationEngine    (выделено)
│   └── mutation_config.py   # MutationConfig    (перенос)
├── graph/                   # слой 2: граф зависимостей (никого не импортирует, работает с именами)
│   ├── __init__.py
│   └── track_graph.py       # TrackGraph        (перенос)
├── session.py               # слой 3: Session — корневой класс (model + graph)
├── drum/                    # слой 4: drum-движок (events, model, sync)
│   ├── __init__.py
│   ├── drum_engine.py       # DrumEngine        (перенос)
│   └── drum_config.py       # DrumConfig        (перенос)
└── engine/                  # слой 4: мелодические движки (events, model, mutation, sync)
    ├── __init__.py
    ├── beat_scheduler.py    # BeatScheduler     (перенос)
    ├── generators.py        # generate_notes, GenerationContext, нарезка sub/stab/seq/arp
    │                        # (минус chord_degrees_for/pattern_length_for — ушли в model/chord_math)
    └── melodic_engine.py    # MelodicEngine     (перенос)
```

### Layering (импорты только вниз)

```
events  →  ∅
model   →  events, harmony
mutation → model/euclidean          (текущий mutation.py импортирует только euclidean — сохраняем)
graph   →  ∅
session.py → model, graph, events
drum/   →  events, model, sync
engine/ →  events, model, mutation, sync
```

Проверено по реальному графу импортов: циклов не возникает. Единственная
существующая петля (`melodic_track` ↔ `generators`) разрывается переносом
`chord_degrees_for`/`pattern_length_for` в `model/chord_math.py`.

### Разбивка `mutation.py` (714 строк)

| Новый файл              | Содержимое                                                                    | Строк |
|-------------------------|-------------------------------------------------------------------------------|-------|
| `drift_tables.py`       | `MUTATE_MIN/MAX_SECONDS`, `MECH_*`, `PROFILE_MECHANISM`, `PARAM_DRIFT_PARAMS` | ~45   |
| `mutation_state.py`     | `MutationState` (frozen dataclass)                                            | ~20   |
| `note_drift.py`         | `NoteDrift`                                                                   | ~90   |
| `floating_euclidean.py` | `FloatingEuclidean`                                                           | ~90   |
| `param_drift.py`        | `_DriftParam` + `ParamDrift`                                                  | ~135  |
| `mutation_engine.py`    | `MutationEngine` (регистрация, тик, freeze/evolve, доступ)                    | ~280  |

`MutationEngine` продолжает выбирать механизм по таблицам из `drift_tables.py`.

### Устранение lazy-импортов

- `model/chord_math.py` — новый модуль: `chord_degrees_for()` и `pattern_length_for()`
  переносятся из `generators.py` **без изменений кода** (обе — чистые функции,
  зависят только от track-полей и `../src/harmony/voicings.py`).
- `generators.py` импортирует их из `model.chord_math` и реэкспортирует (совместимость для тестов `test_generators.py`/
  `test_chord_slicer.py`
  — либо тесты обновляются, см. фазу 5).
- `melodic_track.py` — lazy-импорты заменяются на обычный
  `from src.session.model.chord_math import …`.

## 4. Публичный API и внешние точки входа

**Фасад `../src/session/__init__.py`** — реэкспортирует всё, что сейчас, плюс
`NoteDrift`, `FloatingEuclidean`, `ParamDrift`, `MutationEngine`, `MutationState`,
`MelodicEngine`, `DrumEngine`, `BeatScheduler`, `NoteEvent`, `DrumEvent`.
Внешний код может продолжать `from src.session import Session, …`.

**Канонические пути — глубокие** (по аналогии с `../src/sync`, `src/repl/`).
Обновляются импорты в:

- `../src/app/application.py` (9 импортов из session)
- `../src/app/engine_control.py` (3)
- `../src/app/config.py`, `src/config.py` (drum_config, mutation_config)
- `../tests` — 17 файлов (глубокие импорты `from src.session.X import …`)

## 5. Фазы выполнения

Каждая фаза: `git mv` → поправить импорты → `pytest` → `ruff`/`black`/`mypy` → коммит.

**Фаза 0 — подготовка (5 мин)**

- `git status` чистый, все тесты зелёные (baseline ~1012).
- Удалить `__pycache__` под пакетом (git mv по директориям с кешем мешает).

**Фаза 1 — `events/` + `graph/` (переносы, риск ≈ 0)**

- `git mv` шести файлов, создать `__init__.py` с реэкспортом.
- Обновить импорты: `track.py`, `melodic_track.py`, `drum_track.py`,
  `drum_engine.py`, `session.py`, `__init__.py`, тесты.
- Зелёные тесты → коммит.

**Фаза 2 — `model/` + `chord_math` (ключевая фаза)**

- `git mv` семи файлов модели + `euclidean.py`.
- Создать `chord_math.py`: перенести `chord_degrees_for`, `pattern_length_for`
  из `generators.py` (копия кода, сигнатуры не менять).
- `generators.py`: удалить тела, оставить `from …chord_math import …`
  (временный реэкспорт; убрать в фазе 5 вместе с правкой тестов).
- `melodic_track.py`: заменить два lazy-импорта обычными.
- Зелёные тесты → коммит. **Проверить explicitly:** `test_chord_slicer.py`,
  `test_generators.py`, `test_session.py` (propagate_chords).

**Фаза 3 — разбивка `mutation/`**

- Создать каталог, разбить `mutation.py` по таблице из §3 (копии кода, порядок
  классов сохранить, единый `log` на модуль).
- `euclidean.py` — `git mv` из model (если решено держать его в mutation —
  см. §6, вариант B).
- Перенести `mutation_config.py`.
- `__init__.py` подпакета реэкспортирует всё (тесты `test_mutation.py`
  импортируют несколько имён одной строкой).
- Зелёные тесты → коммит.

**Фаза 4 — `drum/` + `engine/`**

- `git mv` drum_engine, drum_config → `drum/`; beat_scheduler, generators,
  melodic_engine → `engine/`.
- Обновить импорты в `application.py`, `engine_control.py`, тестах.
- Зелёные тесты → коммит.

**Фаза 5 — фасад и финализация**

- Дополнить корневой `__init__.py` (список из §4).
- Убрать реэкспорт `chord_math` из `generators.py`; обновить тесты
  `test_generators.py`/`test_chord_slicer.py` на импорт из `model.chord_math`.
- Обновить оставшиеся глубокие импорты в `../tests` на канонические пути.
- Полный прогон: `pytest` (все), `ruff check src tests`, `black --check`,
  `mypy src` (только пре-существующие ошибки), E2E-спайк
  `../spikes/spike_e2e_midi_sink.py` (R5-регрессия).
- Обновить docstring в корневом `__init__.py` и раздел «Слои» в AGENTS.md.

## 6. Открытые решения (выбрать до старта)

**A. Где жить `session.py` и `track_graph.py`?**

- Вариант 1 (в плане): `session.py` на корне (главный класс пакета,
  как `transport.py` в `sync/`), `track_graph.py` в `graph/`.
- Вариант 2: `core/` с обоими. Не нужен — двухфайловый подпакет.

**B. Где жить `euclidean.py`?**

- Вариант 1: `model/` (в плане) — чистая математика рядом с моделью;
  мутация и engine импортируют из model (вниз — легально).
- Вариант 2: `mutation/` — по истории (C4) это drum-математика, но drum
  её сейчас не использует; engine→mutation зависимость уже существует.
- Рекомендация: вариант 1, `model/euclidean.py`.

**C. Реэкспорты в подпакетных `__init__.py`?**

- Рекомендация: да, каждый подпакет реэкспортирует свои имена — тесты и app
  импортируют оттуда, корневой фасад — только для внешнего потребителя.

## 7. Риски и митигация

| Риск                                            | Митигация                                                                 |
|-------------------------------------------------|---------------------------------------------------------------------------|
| Потеря git-истории при переезде                 | Только `git mv`; фазы атомарны, коммит после каждой                       |
| Цикл импортов после фазы 2                      | `chord_math` — ниже model; прогон mypy и полного pytest в фазе 2          |
| Рассинхрон тестовых импортов                    | Один проход `grep -rn "from src.session" tests/` в фазе 5, checklist в §4 |
| Частичное применение (упавшие тесты в середине) | Каждая фаза заканчивается зелёным прогоном; откат = один коммит           |
| `__pycache__` ломает `git mv`                   | Очистка в фазе 0                                                          |

## 8. Критерии приёмки

- [ ] Структура каталогов соответствует §3.
- [ ] `grep -rn "from src.session.generators import.*chord_degrees_for\|pattern_length" src/session/model/` — нет
  lazy-импортов в model.
- [ ] `pytest` — все тесты passed, счётчик не ниже baseline.
- [ ] `ruff`/`black` чисто; `mypy` — только пре-существующие ошибки.
- [ ] `../spikes/spike_e2e_midi_sink.py` — PASS (MIDI доходит, каналы не слипаются).
- [ ] Публичный API фасада:
  `from src.session import (Session, Track, MelodicTrack, DrumTrack, MelodicProfile, PROFILES, TrackGraph, ChordEvent, DrumLane, NoteDrift, FloatingEuclidean, ParamDrift, MutationEngine, MutationState, NoteEvent, DrumEvent)` —
  работает.
