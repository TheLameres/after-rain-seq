# AGENTS.md — after-rain-seq

Генеративный MIDI-хост для Ambient Dub Techno: гармонический движок (лады, войсинги,
аккордовый граф дорожек), drum-машина (евклидовы ритмы, 16 lane GM), мутация паттернов.
Управление — с Ableton Push 2 или из REPL; MIDI-выход — на внешние синтезаторы.
Таргет — Raspberry Pi 5, разработка на macOS.

> **Планы работ, задачи агентов, история задач и риски — в [`plans/ROADMAP.md`](plans/ROADMAP.md).**
> Этот файл — только актуальная информация о проекте и правила написания кода.

## Стек и окружение

| Что | Значение |
|-----|----------|
| Язык | Python ≥ 3.13 (`requires-python`), целевой рантайм на RPi проверен на 3.14 |
| Зависимости | isobar 0.2.1, mido + python-rtmidi, numpy, pyyaml, pillow, pydantic ≥ 2, prompt_toolkit ≥ 3.0, pyusb, pyliblo3 |
| Опционально | Ableton Link — `uv sync --extra link` |
| Dev-инструменты | pytest, ruff, mypy, black, isort (`uv sync`) |
| Железо | Push 2 (дисплей 960×160 BGR565 + кнопки/пады/энкодеры по USB), LCXL3, USB-синт; udev `2982:1967`, libusb-1.0 |
| Спека Push 2 | Ableton/push-interface (`AbletonPush2MIDIDisplayInterface.asc`) |
| Управление пакетами | uv |

## Команды

```bash
uv sync                                  # зависимости + dev-инструменты
uv run pytest                            # на 2026-11-19: 1945 passed
uv run ruff check src tests
uv run black --check src tests
uv run mypy src
uv run python -m src.main --list-ports   # какие MIDI-порты видит система
uv run python -m src.main                # headless (config.yaml создастся сам)
uv run python -m src.main --simulate     # эмулятор Push 2, без железа
uv run python -m src.main --repl         # + интерактивный REPL
```

Флаги `main`: `--config FILE`, `--log-level LEVEL`, `--log-layer NAME=LEVEL` (повторяемый,
Spring Boot-стиль), `--simulate`, `--list-ports`, `--repl`. Пользовательская документация
(конфиг, порты, REPL, диагностика) — `README.md`.

## Состояние проекта (2026-11-19)

- **Тесты: 1945 passed.**
- Линтеры в момент проверки: ruff 50 замечаний, black 11 файлов не отформатированы
  (пре-существующие), mypy 20 ошибок (в осн. import-untyped isobar/mido + немного
  arg-type). Новые задачи: не добавлять новых замечаний.
- Завершены планы: A1–A2, B1–B4, C1, C3–C6, D1, D2 (+D2-2…D2-7), F1, **G2**
  (скриптовый движок: `src/scripting/` — ScriptSession/ScriptValidator/
  ScriptRunner, DTO `TrackProposal`/`DrumProposal` в core, degrees 0..13,
  REPL `script run/check`, config startup + `--script` CLI, fail-fast exit 1),
  а также ветка
  **«ручная мутация и линейная история»** (фазы A–E по
  `docs/mutation-manual-spec.md`: автономная мутация/freeze/mutate удалены,
  VersionHistory + undo/recall, REPL evolve/undo/recall/history, Push 2
  NEW CC 87 / UNDO CC 119 / экран VERSIONS на Duplicate CC 88, LED падов
  ch 0 статика / ch 14 мигание pending) — детали в спеке и `plans/ROADMAP.md`.
- Осталось: **D3** (пады: CHORDS/NOTES/MORPH/DRUM — режимы пада вне VERSIONS),
  **хвост E1** (сохранение выбора клока/портов в конфиг), **E2** (systemd,
  8-часовой прогон), **хвост C2** (валидация пары лад+войсинг); отложено:
  мигание дисплея TRACKS/VERSIONS (сейчас текстовый флаг), ручной прогон
  VERSIONS на железе.

## Архитектура и слои

Строго иерархическая, **циркулярные зависимости запрещены**: слой импортирует только
из слоёв ниже.

```
src/main.py            ← CLI (--simulate/--repl/--list-ports), сборка App

src/app/               ← Application (main loop, dispatch hook), DeviceManager, display
src/app/engine_control.py  ← EngineControl (ABC) + AppEngineControl — единственный фасад
                           доступа к движку: REPL и UI-контроллер работают только через него
src/app/ui/            ← screen_id, ui_event, ui_queue (thread-safe, drop-oldest),
                           ui_state, macro_axes, screen_controller

src/devices/           ← base/definition/registry, display_state (frozen view-DTO;
                           devices/ не импортирует session/sync/app — снапшот спускается из app)
src/devices/push2/     ← renderer (FrameBuffer/DirtyTracker/GlyphCache, BGR565),
                           display (scene composer, dirty-регионы), screens (классы Screen),
                           widgets (Label/Marker/Bar/Column/ColumnGrid/TabStrip),
                           mapping (карта всех кнопок/энкодеров — docstring),
                           push2_device, track_colors, layout, palette
src/devices/lcxl3/     ← LCXL3 (порты, DAW-режим)

src/midi/              ← ABC-интерфейсы (abc.py), MidoImpl, Factory
src/sync/              ← клок: ClockManager/TickProxy/clock_source/clock_state
                           (internal/MIDI/Link, квантизация переключения на долю);
                           порты: ports/routing/port_state (лейблы, match/serial, hot-plug);
                           CC: cc_map/cc_map_entry/throttle (логические имена, 30 Hz);
                           транспорт: transport/swing/transport_event/capture_output
src/session/           ← граф дорожек и движки (зависит от harmony/):
                             events/   ChordEvent, NoteEvent, DrumEvent (слой 0)
                             model/    Track, MelodicTrack, DrumTrack, профили,
                                       PatternSpec, euclidean, chord_math, version_history
                             graph/    TrackGraph (топосорт, детекция циклов)
                             mutation/ NoteDrift, FloatingEuclidean, ParamDrift,
                                       MutationEngine (+ drift_tables, config,
                                       track_version: снимки версий)
                             modify/   arpeggiate, chain, densify
                             drum/     DrumEngine, DrumConfig
                             engine/   BeatScheduler, generators, MelodicEngine
                             session.py  Session (модель+граф), propagate_chords()
src/scripting/         ← скриптовый движок (Python DSL, план G2): ScriptSession
                           (фасад над EngineControl ABC), ScriptValidator
                           (compile + AST-линт), ScriptRunner (+ format_report);
                           импортирует repl.ABC (engine_control), core, harmony,
                           session.model — строго вниз, ниже repl по зависимости
                           (исключение из порядка: тянется вверх к session/harmony и
                           вниз к repl — связь с repl разорвана через ABC EngineControl,
                           циклов на уровне модулей нет)
src/harmony/           ← Harmony (Root+Scale, валидация ладов), voicings (DIATONIC_*,
                           VOICINGS, invert), progressions, degree_names — чистая логика
src/core/              ← color, engine_result (базовые типы)
src/repl/              ← REPL на prompt_toolkit: parser/executor/completer/status_bar;
                           доступ к движку только через EngineControl + StatusSnapshot
src/config.py          ← pydantic AppConfig: logging, sync, ports, cc_map, drum, mutation,
                           devices (push2/lcxl3), ui
```

Правила слоёв:

- **Никаких циклов.** Если слою A нужен слой B, а слою B — слой A, значит нужен третий
  модуль ниже обоих, или нужно разорвать связь через протокол/ABC.
- **Типы для аннотаций** — через `TYPE_CHECKING` guard или в отдельном модуле ниже по
  иерархии.
- **Ленивые импорты** допустимы для разрыва циклов и ускорения старта, но не как способ
  обойти правило слоёв.
- **Кросс-поточное взаимодействие — через очереди** (паттерн TickProxy / UiQueue,
  drop-oldest при переполнении), не через разделяемые мутables.

## Правила написания кода

### Структура файлов и классов

- **Один класс — один файл.** Каждый публичный класс проекта размещается в отдельном
  файле. Имя файла — `snake_case` от имени класса: `class ClockManager` → `clock_manager.py`.
- **Исключение — связанные DTO и типы.** Мелкие взаимозависимые типы (значения-объекты,
  frozen dataclass'ы, конфиг-схемы) можно группировать в одном модуле. Пример:
  `src/midi/abc.py` содержит `MidiChannel`, `MidiCC`, `MidiMessage` и ABC-интерфейсы —
  это единый типовой слой, а не набор независимых классов.
- **Приватные хелперы** (начинаются с `_`) могут жить в файле основного класса.

### Стиль

- `from __future__ import annotations` в каждом файле.
- Полная типизация: все параметры, возвращаемые значения, атрибуты классов.
- `snake_case` для функций и переменных, `PascalCase` для классов, `UPPER_SNAKE_CASE`
  для констант. Приватные члены — `_leading_underscore`.
- Docstrings — Google-style, на русском для бизнес-логики, на английском для технических
  модулей.
- Логирование: `log = logging.getLogger(__name__)` на уровне модуля.
- Линтеры: ruff/black обязательны на новых/изменённых файлах; mypy — без новых ошибок
  (известные пре-существующие: isobar/mido/usb без stubs).

## MIDI-маппинг и дисплей Push 2 (важные факты)

- Полная карта кнопок/энкодеров — docstring в `src/devices/push2/mapping.py`, сверена
  со спекой (Implementation Chart v2.0, все 56 кнопок).
- Найденные и исправленные баги сдвига маппинга (важно при работе с энкодерами):
  track-энкодеры 1–8 = CC 71–78 (было 70–77); swing-энкодер = CC 15 (CC 78 — это master);
  `Browse` = CC 111 (CC 69 — foot pedal 2).
- Дисплей: кадр шлётся только целиком (dirty-диффа по USB нет), отправка по факту dirty
  + keepalive ~1 c (дисплей гаснет после 2 с тишины). Порог растеризации глифов
  `_GLYPH_THRESHOLD = 96`.
- LED-палитра кнопок по спеке: 0 off, 122 white, 126 green, 127 red (для белых кнопок
  значение = яркость).
- Касания энкодеров Tempo/Swing приходят как note-on/note-off nn10/nn9.

## Известные ограничения (техдолг)

- Двойное применение свинга: в MelodicEngine при планировании и в `Transport._deliver_note_off`;
  вынос свинга из Transport — отдельная задача.
- On-demand melodic-дорожки не регистрируются в MutationEngine (играют базовый материал).
- `set_profile` на живой дорожке пересоздаёт механизм мутации отложенно — по
  `revision` на следующем тике (`refresh_track`); история версий и счётчик при
  этом сбрасываются (spec §6).
- Автоназначение MIDI-каналов глобально по сессии, не per-port (канал 9 зарезервирован под drum).
- LCXL3-путь энкодеров не тронут (debug-лог); EncoderHandler удалён как dead code.
- Ручной прогон UI на железе (табы, LED, x-центры таб-бара 906/800/540) — при доступе к Push 2.
- Transport Mode B (EXTERNAL clock) — интерфейс заложен, реализация отложена.
- A1 п.6: LCXL3 DAW-режим CC→DIN Out — не проверено (нет USB-синта).

## Артефакты

| Файл | Что это |
|------|---------|
| `docs/push2_dubtechno_plan_v5_4.md` | Полный план v6.0 (источник дорожной карты) |
| `docs/track-hierarchy.md` | Иерархия Track→Melodic/Drum, профили как данные |
| `docs/display.md`, `docs/mutation-manual-spec.md` | Дисплей; спецификация ручной мутации (реализована, решения в шапке спеки) |
| `docs/project-status-2026-11-10.md` | Статус ветки ручной мутации (устарел: ветка завершена 2026-11-17) |
| `plans/ROADMAP.md` | Дорожная карта: планы A–F, статусы, риски |
| `plans/plan_*.md` | Детальные планы отдельных задач |
| `spikes/spike_display.py` | Дисплей Push 2: fps, стоимость кадра |
| `spikes/spike_stress.py` | Стресс: температура, CPU%, throttling |
| `spikes/spike_renderer_bench.py` | Бенч рендерера (compose/encode) |
| `spikes/spike_ui_simulate.py` | E2E UI в `--simulate` (сценарии 1–9, PNG-дампы) |
| `spikes/spike_midi_sink.py`, `spikes/spike_e2e_midi_sink.py` | Dummy-приёмник MIDI; E2E MIDI в одном процессе |
| `spikes/spike_push2_palette.py`, `spikes/spike_cairo_bench.py`, `spikes/spike_osc.py` | Палитра/бенч Cairo/OSC |

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- When graphify-out/graph.json exists, run `graphify query "<question>"` before your first grep, search or source-file read for a codebase question, and put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read already located. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. When the answer is under a Markdown heading, `graphify section "<heading>"` prints that section's text, so the .md need not be opened. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- A committed graphify-out/graph.json is rewritten whole on every build, so a large diff to it in a pull request is expected. Do not flag it as churn or suggest skipping the graph rebuild or its hooks.
