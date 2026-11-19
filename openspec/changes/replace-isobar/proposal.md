# Proposal: replace-isobar

## Why

isobar 0.2.1 в рантайме проекта занят тремя ролями (таблица ладов + ступень→MIDI,
метроном/счётчик времени, легаси-адаптеры), каждая из которых на порядок меньше
самой библиотеки; она тянет фоновый поток статистики, «зомби»-клок, float-накопление
времени и стеночные часы (`time.time()`, уязвимые к NTP-скачку). Полная ликвидация
зависимости даёт контроль над клоком, убирает mypy-заглушки `import-untyped isobar`
и сужает поверхность зависимостей. Обоснование и сверка с кодом —
`docs/isobar-replacement-analysis.md` (утверждён пользователем 2026-11-19).

## What Changes

- **Гармония без isobar**: новый `src/harmony/scales.py` — статическая таблица ладов
  (8 канонических имён + алиасы `ionian`, `maj7` — решение 1), имена нот → pitch class,
  `resolve_scale()`; `harmony.py` переписывается без `Key`/`Scale`, удаляются
  неиспользуемые `Harmony.key` и `Harmony.apply(timeline)`. Семантика
  `degree_to_semitone`/`degree_to_note` сохраняется 1:1 (golden-фикстура, снятая
  с удаляемой библиотеки до её удаления).
- **Клок без isobar (вариант B)**: новый `src/sync/time_base.py` — `TimeBase`,
  единственный владелец времени (целочисленный счётчик тиков, `current_time` в битах
  float, `set_beats`, 480 PPQN); новый `src/sync/internal_clock.py` —
  `InternalClockSource` на `time.perf_counter()` (решение 3) с абсолютным
  планированием и догоном тиков. В `clock_source.py` duck-typed контракт источников
  формализуется в `ClockSourceProtocol`; INTERNAL-ветка фабрики создаёт
  `InternalClockSource`.
- **Плательщики времени переводятся на TimeBase**: `ClockManager` (`_timeline` →
  `_time_base`), `TickProxy`, хук `application.py`, `set_sync_bpm` через
  `ClockManager.set_tempo` (зомби-запись `timeline.tempo` исчезает).
- **all_notes_off CaptureOutput остаётся достижимым** (решение 4: CaptureOutput НЕ
  удаляется): `ClockManager._all_notes_off` переключается с обхода
  `timeline.output_devices` на notes-off-callback, привязанный приложением к
  `capture.all_notes_off`; хук воспроизводит сегодняшний порядок enqueue при STOP.
  STOP-артефакт (отложенный CC123-бёрст после рестарта) сохраняется и фиксируется
  как известное ограничение в design и `AGENTS.md`.
- **Чистка легаси**: докстринги без isobar (`tick_proxy`, `routing`, `transport`,
  `transport_event`, `swing`, `euclidean`, `melodic_engine`, `melodic_track`,
  `capture_output`, `voicings.py:20`, `param_drift.py:26`, `mutation/__init__.py:9`,
  `ISOBAR_DEFAULT_MIDI_IN` в докстрингах `config.py` / `clock_source.py` /
  `clock_manager.py` и в `README.md:59`); докстринги тест-файлов
  (`test_capture_output`, `test_routing`, `test_midi_clock_in`, `test_clock_source`);
  **BREAKING** — переименование enum-значения
  `TransportMode.ISOBAR` → `TransportMode.TICK_THREAD` (решение 2); удаление
  зависимости из `pyproject.toml` + `uv sync`; обновление `AGENTS.md`
  (стек, baseline линтеров, техдолг, известное ограничение STOP) и
  `plans/ROADMAP.md` (запись о change).
- **Свинг-хвост**: удаление устаревшего пункта техдолга «двойное применение свинга»
  из `AGENTS.md` (свинга-двойность уже нет — единственная точка `Transport._schedule`);
  сквозной регрессионный тест «свиг применяется ровно один раз».

## Capabilities

### New Capabilities

- `harmony`: таблица ладов и резолвинг ступени → MIDI (480-PPQN-независимая гармония:
  8 диатонических ладов + алиасы `ionian`/`maj7`, pitch-class корней, валидация
  терцовых качеств, эквивалентность `degree_to_note`/`degree_to_semitone` 1:1
  golden-фикстуре isobar).
- `clock-sync`: контракт времени и источников клока без isobar — 480 PPQN,
  `current_time` в битах float, целочисленный счётчик тиков, квантизация смены
  источника на границе доли, восстановление фазы (`set_beats`), INTERNAL-генератор
  на монотонных часах, notes-off при STOP/смене источника.

### Modified Capabilities

_(нет — каталог главных спек `openspec/specs/` пуст; обе capability добавляются как новые)_

## Impact

- **Код**: `src/harmony/harmony.py` (переписан), `src/harmony/voicings.py` (докстринг),
  новые `src/harmony/scales.py`,
  `src/sync/time_base.py`, `src/sync/internal_clock.py`; правки `src/sync/clock_source.py`,
  `clock_manager.py`, `tick_proxy.py`, `transport.py` (enum + докстринги),
  `transport_event.py`, `swing.py`, `routing.py`, `capture_output.py` (докстринги),
  `src/sync/config.py`, `src/sync/__init__.py` (реэкспорт новых модулей — по факту
  использования), `src/app/application.py`,
  `src/session/model/euclidean.py`, `melodic_track.py`,
  `src/session/engine/melodic_engine.py`, `src/session/mutation/param_drift.py`
  и `src/session/mutation/__init__.py` (докстринги), `src/sync/smf_writer.py` (докстринг).
- **README**: `README.md:59` — легаси env `ISOBAR_DEFAULT_MIDI_IN` (код его не читает)
  заменяется документацией `sync.midi_clock_device`.
- **Зависимости**: `pyproject.toml` — удаление `isobar>=0.2.1` и упоминания в
  description; `uv sync` пересобирает `uv.lock` (фаза 3, выполняет coder). numpy
  остаётся (push2 renderer/display).
- **Тесты**: обновление `test_harmony.py` (+ golden-фикстура),
  `test_clock_manager.py` (MockTimeline → TimeBase; epsilon-тесты квантизации
  переформулируются на целые тики), `test_tick_proxy.py`,
  `test_midi_clock_out.py`, `test_clock_source.py` (фабрика + докстринг),
  `test_transport.py` (имя enum); живая правка `test_midi_clock_in.py` —
  хелпер `_app()` возвращает `cm._time_base` вместо `cm._timeline`;
  докстринги без isobar в `test_capture_output.py`, `test_routing.py`,
  `test_midi_clock_in.py`; новые `test_time_base.py`, `test_internal_clock.py`,
  golden-фикстура `tests/fixtures/key_get_golden.py`; сквозной свинг-тест
  (фаза 4). Счёт тестов пересчитывается тестером (сейчас 1945 passed).
- **Документация**: `AGENTS.md` (зависимости, baseline линтеров, техдолг-список,
  известное ограничение STOP-артефакта), `docs/track-hierarchy.md` (2 строки),
  `plans/ROADMAP.md` (запись о change), `README.md` (легаси env-переменная).
- **Не меняется**: поведение трёх источников клока (MIDI/Link — только докстринги),
  транспортные инварианты (квантизация, watchdog, порядок событий), свинг-логика,
  numpy/mido-зависимости, железо (RPi5-прогон вне скоупа).
