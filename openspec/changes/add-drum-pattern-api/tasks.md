# Tasks

> В этом конвейере тесты и линтеры не запускаются — их прогоняет исполнитель
> в задачах финализации (блок 9). Каждая задача ниже несёт критерий готовности,
> проверяемый её собственным тестом, когда прогон станет доступен.

## 1. Компилятор нотации (слой session.model)

- [x] 1.1 (ревизия: модуль уже создан по первой редакции design — переработать
  разворачивание евклида) В `src/session/model/drum_pattern_lang.py`: класс
  `DrumPatternCompiler` со статическим методом `compile(pattern: str, steps: int) -> list[int]`.
  Грамматика — design.md §2: нотация — либо литеральные ячейки `x X . ~`
  (пробелы и `|` игнорируются; пустая нотация → все нули), либо ровно одна
  евклид-группа `(p,s[,offset])` — смесь с литералами → `ValueError`.
  Евклид: `p` ударов на весь бар — базовый bjorklund-паттерн длины `s` строится
  через `PEuclideanCached` (не дублировать `_bjorklund`), сегмент `i`
  растягивается на позицию `idx_i = (i * steps) // s` (floor; коллизий нет при
  `s ≤ steps`), ячейка `idx_i` = `base[(i - offset) % s]` (offset-roll до
  растягивания). Валидация: `0 ≤ p ≤ s ≤ steps`, `0 ≤ offset < s`;
  `s > steps` → `ValueError`. Литералы: длиннее `steps` → `ValueError`,
  короче — паддинг нулями. Ошибки — `ValueError` с русским сообщением и
  позицией символа. Критерий: файл проходит ruff/black/mypy, не импортирует
  ничего выше session.model.
- [x] 1.2 (ревизия под новую семантику) Тесты `tests/test_drum_pattern_lang.py`:
  литералы (включая `X`), синонимы `.`/`~`, игнорирование пробелов и `|`,
  пустая строка; евклид: **`(3,8)`@16 → удары на шагах 0, 6, 12**;
  **`test_full_pulses` переписать: `(8,8)`@16 → `[1,0]*8` (восьмые 0,2,…,14),
  НЕ `[1]*16`**; `(4,4)`@16 → четверти 0/4/8/12; `(16,16)`@16 → `[1]*16`;
  неравномерное деление `(5,5)`@16 → 0/3/6/9/12; `(0,8)` → все нули;
  offset (`(3,8,1)`@16 → 2/8/14; отрицательный/≥ s → ошибка);
  `s > steps` (`(3,32)`@16) → ошибка; смесь `x.x. (2,8)` → ошибка;
  литерал длиннее сетки → ошибка, паддинг короткого; неизвестный символ
  с позицией, незакрытая скобка, нецелые параметры.
  Критерий: все случаи из таблицы примеров design.md §2 покрыты.

## 2. Модель: адресация lane

- [x] 2.1 В `src/session/model/drum_track.py`: переименовать `_GM_DRUM_MAP` →
  публичную `GM_DRUM_MAP` (обновить использования внутри файла и в тестах, если
  есть), добавить метод `resolve_lane(spec: str) -> int` — целое 0–15 → индекс,
  36–51 → GM-номер, иначе имя lane'а без учёта регистра; прочее → `ValueError`.
  Критерий: `resolve_lane("kick") == resolve_lane("Kick") == resolve_lane("36") == 0`;
  существующее поведение `step_to_note` не изменилось.
- [x] 2.2 Тесты в `tests/test_drum_track.py` (или рядом): resolve_lane по
  индексу/GM/имени (регистр), ошибки вне диапазонов и по неизвестному имени.

## 3. История версий: запись ручной правки

- [x] 3.1 В `src/session/mutation/mutation_engine.py`: публичный метод
  `record_manual_version(track_name: str) -> bool` — снимок `DrumVersion`
  (drum) или `_snapshot_melodic` → сравнение с головой истории
  (`history.current`; совпадение → без push, «без изменений») →
  `history.push()` → `_sync_counter()`; без шага дрейфа; незарегистрированная
  дорожка → `False`. Семантика — design §7.
- [x] 3.2 В `src/session/model/version_history.py`: `threading.Lock` вокруг
  составных операций `push`/`undo`/`recall` (страховка от гонки REPL-поток ↔
  main loop, design §7). Критерий: существующие тесты истории зелёные.
- [x] 3.3 Тесты: `record_manual_version` пишет версию после правки lane.pattern,
  синхронизирует счётчик, `undo` возвращает прежний бит, `evolve` после ручной
  правки отрезает будущее; повторная установка того же паттерна не создаёт
  дубликат версии (сравнение с головой), возврат к прежнему паттерну после
  промежуточной правки создаёт новую версию; незарегистрированная → `False`.

## 4. Фасад: EngineControl + AppEngineControl

- [x] 4.1 В `src/repl/engine_control.py`: не абстрактный метод
  `set_drum_pattern(self, name: str, lane: str, pattern: str) -> EngineResult`
  с дефолтом `EngineResult.fail("drum pattern is not supported by this control")`
  (прецедент C1–C4 — заглушки не ломаются); docstring по конвенции файла.
- [x] 4.2 Регистрация при создании (design §7): в `src/app/engine_control.py`
  метод `create_drum_track` после успешного создания и `_route_new_track`
  регистрирует дорожку в движке мутации
  (`engine.register_drum_track(track.name, track)`), если движок есть; при
  `mutation.enabled=false` (движка нет) — создание работает без истории.
  Закрывает разрыв «рантайм-drum вне MutationEngine» только для drum
  (melodic on-demand — известный техдолг из AGENTS.md, не трогаем). Критерий:
  после `create_drum_track` из REPL дорожка в `registered_tracks` движка,
  `mutation_history` отвечает без «not mutable».
- [x] 4.3 В `src/app/engine_control.py`: реализация `set_drum_pattern` —
  session существует → дорожка найдена → `isinstance(DrumTrack)` →
  `resolve_lane` → компиляция (`DrumPatternCompiler.compile(pattern,
  track.steps)`, `ValueError` → fail) → замена `lane.pattern` новым списком
  (reference swap) → `record_manual_version` (движок есть; иначе note в
  сообщении). Сообщение ok: имя дорожки, lane, число активных шагов; при
  дедупликации — «без изменений (уже в этой версии)».
- [x] 4.4 Тесты `tests/test_engine_control_drum_pattern.py`: happy path по всем
  трём адресациям lane, ошибки (нет сессии/дорожки, не drum, неверный lane,
  неверная нотация), неизменность паттерна при ошибке, note при отсутствии
  движка мутации, регистрация при `create_drum_track` (mutation enabled —
  дорожка в `registered_tracks`; disabled — создаётся без регистрации),
  мок-контроль возвращает дефолтный fail.

## 5. REPL: команды и автодополнение

- [x] 5.1 В `src/repl/parser.py`: две `CommandSpec` домена `drum` —
  `drum add [name]` (max_args=16, join_args=True) и
  `drum pattern <track> <lane> [<notation…>]` (min_args=2, max_args=64,
  join_args=False; два аргумента = очистка lane'а); usage/help по конвенции
  таблицы.
- [x] 5.2 В `src/repl/executor.py`: `_cmd_drum_add` → `create_drum_track`;
  `_cmd_drum_pattern` → `args[0]` дорожка, `args[1]` lane,
  `" ".join(args[2:])` нотация (пусто при двух аргументах — очистка) →
  `set_drum_pattern`; результат через `_feedback`. Критерий: ошибка установки
  → `CommandResult(code=1)`, цикл живёт.
- [x] 5.3 В `src/repl/completer.py`: динамические контексты — после
  `drum pattern` имена дорожек (как `track delete`), следующий токен —
  провайдер `"lane"`; в `src/main.py` — провайдер `"lane"` из `GM_DRUM_MAP`
  (имена lane'ов). Статическое дерево дополняется само из таблицы parser'а.
- [x] 5.4 Тесты: парсинг `drum add`, `drum add "Big Drums"`,
  `drum pattern Drums kick x..x`, `drum pattern "My Drums" 38 (3,8,1)`,
  `drum pattern Drums kick` (два аргумента → пустая нотация-очистка),
  ошибки арности/действия; executor → вызовы мок-контроля (включая очистку);
  дополнение lane'ов и дорожек.

## 6. Скриптовый фасад

- [x] 6.1 В `src/scripting/script_session.py`: метод
  `set_drum_pattern(self, name: str, lane: str, pattern: str, *, fatal: bool = True) -> EngineResult`
  — обёртка 1:1 через `_call("set_drum_pattern", ...)`. В `ScriptValidator`
  правок не требуется: `_facade_methods` строится рефлексией (design §8) —
  зафиксировать это комментарием не нужно, факт фиксируется тестом.
- [x] 6.2 Тесты `tests/test_scripting_session.py` (+ validator): обёртка
  прокидывает аргументы; `ScriptValidator` пропускает
  `session.set_drum_pattern("Drums", "kick", "x..x")` и ловит неверную арность
  и неизвестный kwarg.

## 7. Интеграция: скрипт → правка → undo/recall

- [x] 7.1 Интеграционный тест в App-окружении — **дорожка создаётся в
  рантайме** (после `_init_mutation`: `AppEngineControl.create_drum_track`
  из REPL-сценария или `session.add_drum` скрипта; НЕ по образцу фикстур,
  где треки создаются до `_init_mutation` — это маскировало бы разрыв
  регистрации): `create_drum_track` → `set_drum_pattern` → бит изменился →
  `undo_mutation` вернул стартовый (пустой) бит → `recall_version` вернул
  правку; счётчик мутаций согласован; `mutation_history` до правки отвечает
  без «not mutable». Критерий: главный сценарий брифа «создал → задал →
  undo» покрыт тестом на рантайм-пути.
- [x] 7.2 Дополнительно (регресс существующих сценариев): drum-дорожка,
  существовавшая на старте (до `_init_mutation`), — `set_drum_pattern` →
  `undo`/`recall` работают как раньше; повторная установка того же паттерна
  не добавляет версию в `history`.

## 8. Пример и документация

- [x] 8.1 Создать `examples/drum_dub.py` для ScriptRunner: `session.add_drum(...)`,
  kick/snare/hat литеральными нотациями, евклид на перкуссии (shaker/conga),
  `session.set_bpm(...)`, `session.start()`. Структура — как canonical-фикстура
  в `tests/test_scripting_runner.py`; каждая инструкция проходит валидатор.
- [x] 8.2 Тест по образцу `test_canonical_script_fixture`: `examples/drum_dub.py`
  проходит `validate_source` без диагностик и исполняется на мок-контроле с
  ожидаемой последовательностью вызовов.
- [x] 8.3 `README.md`: раздел «Drum-паттерны из REPL и скриптов» после раздела
  «Скрипты» — таблица синтаксиса нотации (x/X/./~/`|`/евклид/offset), очистка
  lane'а (пустая нотация; из REPL — `drum pattern <track> <lane>` без
  нотации), примеры REPL-команд (`drum add`, `drum pattern` с кавычками и
  без), пример скрипта (ссылка на `examples/drum_dub.py`), правила длины
  относительно сетки, пометка об истории версий (правка записывается версией,
  undo/recall работают; при `mutation.enabled=false` — без истории) и об
  отложенных операторах `?`/альтернативе (см. design §3).
- [x] 8.4 (после смены семантики евклида, ревизия 8.1–8.3) Проверить и при
  необходимости поправить уже созданное:
  - `examples/drum_dub.py` и его тест 8.2: число ударов для `(p,s)` не меняется
    (сообщения «N active step(s)» остаются валидными), меняются позиции —
    убедиться, что ожидания теста примера не завязаны на конкретные шаги сетки;
    если завязаны — обновить под новую раскладку (`(3,8)`@16 → удары 0/6/12;
    `(2,8)`@16 → активные сегменты bjorklund(2,8) = {0, 4} → удары на шагах 0 и 8).
  - `README.md` (раздел из 8.3): синхронизировать примеры позиций/числа
    ударов евклида с новой семантикой — «(3,8) на сетке 16: удары на шагах
    0, 6, 12; (8,8): восьмые 0,2,…,14, не сплошная сетка»; правило
    `s > steps` → ошибка; смесь литералов с евклидом → ошибка.

## 9. Финализация (исполнитель)

- [ ] 9.1 Прогнать `uv run pytest` — все тесты зелёные, включая новые блоки 1–8.
- [ ] 9.2 Линтеры без роста базы: `uv run ruff check src tests`,
  `uv run black --check src tests`, `uv run mypy src` — сравнить с базой
  2026-11-19: ruff 50, black 11 файлов, mypy 20.
- [ ] 9.3 `openspec validate add-drum-pattern-api` и
  `openspec status --change add-drum-pattern-api` — все артефакты done,
  валидация без ошибок.
- [ ] 9.4 Ручная приёмка на железе/`--simulate` (когда доступно): из REPL
  `drum add` → `drum pattern <имя> kick x..x|x..x|....|....` → запуск
  транспорта → послушать; `undo` возвращает стартовый (пустой) бит —
  полный главный сценарий брифа на рантайм-дорожке. Прогон примера
  `script run examples/drum_dub.py`.
- [ ] 9.5 После реализации: `graphify update .` — граф не знает про новый
  модуль `drum_pattern_lang.py` и домен `drum` в REPL.

## Workflow follow-up

- Дельты затрагивают capabilities, чьи baseline-спеки описаны в
  `init-current-system` (ещё не синхронизирован): синхронизировать оба change'а
  вместе (openspec-sync-specs) либо архивировать их в согласованной очерёдности.
- После sync/archive обновить `plans/ROADMAP.md` (новый план завершён) и
  раздел «Артефакты» в `AGENTS.md`, если появится `examples/` как постоянное
  место для скриптов-примеров.
