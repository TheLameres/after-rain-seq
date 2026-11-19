# Tasks

> В этом конвейере тесты и линтеры не запускаются — их прогоняет исполнитель
> в задачах финализации (блок 4). Каждая задача ниже несёт критерий
> готовности, проверяемый её собственным тестом, когда прогон станет доступен.

## 1. DrumEngine: порт на lookahead-планировщик

- [x] 1.1 В `src/session/drum/drum_engine.py`: поле
  `self._scheduler = BeatScheduler(horizon=4.0)` (конструктор — без новых
  обязательных аргументов, сигнатуры `DrumEngine(...)`/`tick(current_beat,
  bpm)` сохраняются; docstring модуля и `tick` переписать: bpm сегодня не
  используется — design §6). Проверить отсутствие циклов: `session.engine`
  не импортирует `session.drum` (grep). Критерий: модуль проходит
  ruff/black/mypy без новых замечаний; слои не нарушены.
- [x] 1.2 Реализовать `tick()` по design §2: детект правки (1.3) →
  ранний `return 0` при `port_label is None` (**до** `ensure`, как у melodic) →
  `ensure(current_beat)` → достройка окна циклами
  (`cycle_len = steps/4`, `k = floor(watermark/cycle_len)`, `generate()`,
  маппинг `abs_beat = cycle_start + ev.beat`, фильтр
  `abs_beat >= watermark - 1e-9`, `advance(cycle_start + cycle_len)`; окно
  достраивается циклами — pending может превышать `now + horizon` до границы
  цикла, design §2) →
  mute-чек после достройки → `due(current_beat)` → `_enqueue`.
  `_to_transport_event` → `_event_pair(ev, abs_beat)`: note_on на `abs_beat`
  (с `duration=ev.duration`) + note_off на `abs_beat + ev.duration`
  (DEFAULT_GATE 0.25). Свинг в движок не переносить (§4.2 — живёт в
  Transport). Критерий: ревизия тестов блока 3 зелёная после финализации.
- [x] 1.3 Детект правки паттерна (design §4): поле
  `self._fingerprint: tuple[tuple[tuple[int, ...], ...], tuple[bool, ...]] |
  None`; на каждом тике до достройки — сравнение
  `(track.snapshot(), tuple(l.muted for l in track.lanes))`; при изменении
  (и на первом тике — fingerprint не инициализирован) —
  `scheduler.cancel_from(current_beat)` + `scheduler.rewind_to(current_beat)`
  + перестройка окна из текущего паттерна; fingerprint обновить. Дубль на
  границе цикла исключён: `cancel_from` снимает note_on с
  `beat >= current_beat - epsilon`, ребилд возвращает их ровно один раз.
- [x] 1.4 Публичный `reset()` (`scheduler.reset()`), `all_notes_off()` —
  добавить `scheduler.reset()` перед enqueue ALL_NOTES_OFF (как у melodic);
  публичный `scheduler` property для интроспекции/тестов (по образцу
  `MelodicEngine.scheduler`). Критерий: существующие тесты all_notes_off
  ревизии блока 3 зелёные.
- [x] 1.5 (ревизия post-implementation, design §9) В
  `src/session/model/drum_track.py` `_generate_lane`: `step_duration` с
  `1.0 / (self.steps / 4)` на фиксированные `0.25` (16-я нота всегда,
  независимо от steps; цикл паттерна — `steps/4` битов, как в
  MutationEngine); комментарий `# доля = 1/4 такта` исправить. Тест на
  позиции для steps=32/48/64: `beat = step × 0.25`, максимум шага в цикле —
  `(steps-1) × 0.25` < `steps/4`; тесты тестера `test_grid_32_and_64`
  зелёные. Критерий: генерация покрывает весь цикл `steps/4` на любой сетке
  (при steps=32 удары возможны в битах 4.0–7.75). Чекбокс отмечает кодер
  при выполнении.
- [x] 1.6 (документационный хвост design §9) README.md (строки ~335/348) и
  комментарий `examples/drum_dub.py`: формулировку «евклид на весь бар»
  уточнить до «на весь цикл паттерна» (при steps=16 цикл = такт; при
  steps≠16 цикл = 2/3/4 такта) — только текст, код компилятора не меняется.
  Чекбокс отмечает кодер при выполнении.

## 2. Хук приложения: reset drum-движков на START/STOP

- [x] 2.1 В `src/app/application.py` dispatch-хук (ветки START и STOP,
  строки ~522–534): добавить `for engine in drum_engines: engine.reset()`
  рядом с melodic. Комментарии веток дополнить (drum тоже сбрасывается).
  Критерий: интеграционный тест 3.4 зелёный; TICK-ветка не изменена
  (сигнатура `engine.tick(timeline.current_time, bpm_now)` сохранена).

## 3. Тесты: регресс дублирования, парность, правки, интеграция

- [x] 3.1 Ревизия `tests/test_drum_engine.py` под планировщик (фикстура
  `_make_engine` сохраняется): пустой паттерн → 0 событий на любом тике;
  один тик на бите 0 → по паре note_on/note_off на каждый hit (note_off на
  `+0.25`, тот же note/channel/port); поля события (note/velocity accent/
  channel/int-типы) — без изменений; queue full drop-oldest; свинг-тест
  (движок не сдвигает onset, пары одинаковой длины). Критерий: фиксирует
  контракт пар, а не пачечную доставку.
- [x] 3.2 Регресс-тест дублирования (главный критерий брифа): луп
  последовательных тиков таймлайна (480 PPQN) на 2+ цикла по образцу
  `TestBeatScheduling`
  (`tests/test_melodic_engine.py`) — on_map/off_map по битам после дренажа
  очереди на каждом тике: каждый активный шаг доставлен ровно один раз за
  цикл на своей абсолютной позиции; эталон позиций `examples/drum_dub.py`
  (kick 0/3/4/7, snare 4/12, closedhat чётные, shaker 0/6/12, conga 6/14 —
  как `REFERENCE` в `spikes/spike_midi_dump.py`); цикл 2 = цикл 1 +
  `steps/4`; сравнение бит — `pytest.approx`. Проверить и сетку 32/64
  (cycle_len 8/16, шаг 0.25 — 16-е ноты фиксированно, design §9; позиции
  `step × 0.25`, тесты тестера `test_grid_32_and_64` остаются красными до
  выполнения 1.5).
- [x] 3.3 Реакция на правки: (а) смена `lane.pattern` между тиками — с
  текущего тика доставляется новый паттерн, старые запланированные note_on
  сняты, дублей `(note, beat)` нет; (б) симуляция мутации на границе цикла
  (правка ровно на тике границы `steps/4`) — удар на границе доставлен ровно
  один раз (design §4); (в) lane.muted=True/False между тиками — lane
  исчезает/возвращается без дублей; (г) mute дорожки — тишина, outbox
  наполняется, unmute → возврат в такт без навёрстывания; (д) порт None →
  тишина, `set_port_label("aux")` → доставка на новый порт. Критерий: каждый
  сценарий фиксирует однократность после правки.
- [x] 3.4 Интеграционный тест START/STOP хука (по образцу hook-тестов
  `tests/test_midi_clock_in.py`): App с drum-дорожкой (можно
  `--simulate`-путь или ручная сборка как в `tests/test_app_routing.py`) —
  STOP → `drum_engines[*].scheduler.pending_count == 0` и инициализация
  сброшена; повторный START → события начинаются с нулевой фазы таймлайна,
  без «доигрывания прошлого». Критерий: фиксирует новый вызов reset в хуке.
- [x] 3.5 Сквозной тест через Transport + CaptureRecorder (по образцу
  `tests/test_engine_control_capture.py`): прогон 2–3 циклов drum-дорожки
  с паттернами `examples/drum_dub.py` → в capture: нет дублей одной ноты
  на одном тике, каждому note_on соответствует note_off на +0.25 бита,
  позиции шагов совпадают с эталоном drum_dub (программный аналог
  `spike_midi_dump.py --drum-dub`). Критерий: регресс воспроизводится до
  фикса (падает на старом коде), зелёный после.

## 4. Финализация (исполнитель/тестер)

> **Состояние на 2026-11-19** (циклы правки кодера исчерпаны 2/2; решение
> пользователя — остановиться без применения фикса, см. design:
> «Root cause падения hook-тестов (не устранён)»):

- [ ] 4.1 Прогнать `uv run pytest` — все тесты зелёные (1945 + новые блоки
  1–3), включая ревизию `tests/test_drum_engine.py`.
  **Текущее состояние: 2141 passed / 3 failed.** Незакрытые падения:
  - `tests/test_drum_engine_hook.py`: `test_restart_starts_from_zero_phase`
    (0 note_on вместо 1) и `test_ticks_deliver_once_per_beat` (`[]` вместо
    `[0.0, 4.0]`) — root cause задокументирован в design; фикс готов
    (~4 строки в `_init_clock_manager`), **не применён** — известная
    проблема с готовым фиксом на будущее;
  - `tests/test_scripting_runner.py`: 1 падение (scripting_runner) —
    вне скоупа этого change, не исследовано.
- [ ] 4.2 Линтеры без роста базы: `uv run ruff check src tests`,
  `uv run black --check src tests`, `uv run mypy src` — сравнить с базой
  2026-11-19: ruff 50, black 11 файлов, mypy 20.
  **Текущее состояние:** black не прогнан по
  `test_drum_engine_hook.py` / `test_drum_engine_capture.py` /
  `test_drum_track.py` (permission denied у кодера и тестера) —
  при следующем прогоне убедиться, что новых замечаний нет.
- [ ] 4.3 `openspec validate fix-drum-engine-scheduling` и
  `openspec status --change fix-drum-engine-scheduling` — все артефакты
  done, валидация без ошибок.
  **Текущее состояние:** `openspec validate` — permission denied, не
  выполнено.
- [ ] 4.4 Ручная приёмка (когда доступно железо/`--simulate`): запуск
  `script run examples/drum_dub.py` → бит звучит ровно (нет «дребезга»
  повторных ударов), capture-запись содержит пары и эталонные позиции;
  `spike_midi_dump.py <capture> --drum-dub` не показывает аномалий дублей
  и залипших note_on.
- [ ] 4.5 После реализации: `graphify update .` — граф не знает про новую
  структуру `DrumEngine` (планировщик, reset) и правку хука.
- [ ] 4.6 (отложено решением пользователя) Применить готовый фикс
  hook-тестов: ~4 строки в начале `App._init_clock_manager`
  (`application.py:438`) — `stop()` предыдущего ClockManager и
  `stop_worker()` предыдущего TickProxy (полный код и обоснование
  безопасности — design «Root cause падения hook-тестов (не устранён)» /
  «Готовый фикс (НЕ применён)»). Закрывает 2 падения из 4.1.

## Workflow follow-up

- Дельта затрагивает capability `drum-engine`, чья baseline-спека описана в
  `init-current-system` и дополнена `add-drum-pattern-api` (ещё не
  синхронизированы): синхронизировать все три change'а вместе
  (openspec-sync-specs) либо архивировать в согласованной очерёдности.
- После sync/archive обновить `plans/ROADMAP.md` и (если появится) раздел
  «Известные ограничения» AGENTS.md — пункт про дублирование drum-событий
  закрыт.
