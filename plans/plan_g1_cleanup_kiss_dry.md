# Расширенный план G1: Cleanup — удаление и рефакторинг по KISS/DRY

> Дата: 2026-11-17. Статус: ⬜ НЕ НАЧАТО.
> Основа: инвентаризация кодовой базы (замеры, мёртвый код, дубли, конфиг) — факты
> раздела 2 собраны grep'ом и прогонами линтеров на состоянии 1830 passed.

## 0. Зафиксированные решения (шапка)

1. **KISS приоритетнее DRY.** Дедупликация — только дословного/почти дословного
   дублирования с риском расхождения. Спорные случаи остаются дублированными;
   устранение дублирования не должно порождать новые абстракции/слои.
2. **Строго без изменения поведения.** «Удаление» = только мёртвый и неиспользуемый
   код. Единственное явное исключение — батч G1-6 (нечитаемые ключи конфига:
   меняется валидация, принято отдельным решением).
3. **Тесты зелёные после каждого батча.** Число тестов может упасть только за счёт
   тестов удалённого мёртвого кода (политика: код и его тесты удаляются вместе).
4. **Скоуп:** `src/` + `tests/`. `spikes/` не трогается (мёртвых спайков нет —
   проверено). `docs/` и `plans/` не трогаются; единственное исключение —
   `AGENTS.md` в финальном батче G1-8 (файл актуальных фактов) и README в части
   удалённых ключей конфига (G1-6).
5. **Поведенческий техдолг вне плана:** on-demand дорожки вне MutationEngine,
   отложенное пересоздание при `set_profile`, глобальное автоназначение каналов,
   Mode B (EXTERNAL). Это отдельные задачи.
6. **Ритм батчей:** каждый батч — отдельный коммит; `uv run pytest` зелёный;
   ruff/black чисто на изменённых файлах; после изменения кода — `graphify update .`.
7. **Перед удалением каждого символа — повторный grep** по src+tests+spikes
   (инвентарь мог устареть к моменту исполнения).

## 1. Замеры «до» (2026-11-17)

| Метрика | Значение |
|---|---|
| `src/` | 20 316 строк, 123 файла |
| `tests/` | 20 084 строки, 79 файлов, 1830 collected |
| ruff | 50 замечаний (fixable: 10) |
| black | 11 файлов не отформатированы |
| mypy | 20 ошибок: 10 import-untyped (isobar/mido/usb), 9 arg-type, 1 return-value |
| TODO/FIXME/XXX/HACK в src | 3 (application.py:293, application.py:385, transport.py:56) |

Слои: session 4 609/38, devices 4 317/23, app 3 618/14, sync 3 583/19,
repl 2 051/13, midi 776/4, harmony 617/5, core 219/3, config 247, main 141,
logging_config 138.

Гиганты (wc -l): `app/ui/screen_controller.py` 1229 · `app/application.py` 995 ·
`devices/push2/screens.py` 868 · `app/engine_control.py` 715 ·
`session/mutation/mutation_engine.py` 564 · `midi/abc.py` 531 · `repl/parser.py` 523.

## 2. Инвентарь (факты)

### 2.1. Полностью мёртвые символы (0 вхождений вне определения)

| Файл:строка | Символ |
|---|---|
| `src/config.py:240` | `save_config()` |
| `src/config.py:96` | `AppConfig.set_device_config()` |
| `src/devices/push2/screens.py:138` | `_percent()` |
| `src/devices/push2/screens.py:641` | `DemoScreen._bottom_name()` |
| `src/devices/registry.py:33` | `create_device()` |
| `src/sync/cc_map.py:235` | `create_cc_map()` |

### 2.2. Мёртвые в проде, живые только в тестах (0 вызовов в src)

| Группа | Символы |
|---|---|
| mutation | `MutationEngine.unregister_track()` (mutation_engine.py:289); `revert_one()` (note_drift.py:81, param_drift.py:85); `drift_count()` (note_drift.py:120, param_drift.py:140); `get_base()` (param_drift.py:125) |
| session/model | `DrumTrack.step_to_note()` (drum_track.py:234); `Session.track_count()` (session.py:251) |
| session/engine | property `MelodicEngine.scheduler` (melodic_engine.py:89) |
| sync/cc_map | `is_automation_enabled()` (:199), `known_params()` (:206), `automation_ports()` (:210 — вызывается только из `__repr__` :226) |
| sync/ports, routing | `pending_switch()` (ports.py:252), `resolve_output()` (ports.py:260), `is_open()` (routing.py:237), `flush_port()` (routing.py:313) |
| harmony | `voicing_notes()` (voicings.py:208), `triad_quality()` (:218), `seventh_quality()` (:224), `roman()` (progressions.py:24) |
| push2/renderer | `blit()` (:327), `is_full()` (:101), `grid_cell()` (:399) |
| push2/widgets | `Widget` (Protocol, :66), `Column` (:145) |
| push2_device | `set_display_frame_callback()` (:328) |
| screens.py | модульные `draw_header/draw_tracks/draw_track/draw_track_macro/draw_wizard/draw_scale/draw_setup/draw_ports/draw_versions/draw_demo` (:821–867) — тонкие делегаты, прод идёт через `Screens` (display.py:251) |
| app/repl | `track_sources()` (app/engine_control.py:361 и repl/engine_control.py:163; REPL зовёт `set_track_sources`) |
| midi | `sysex_with_framing()` (abc.py:246) |

Отсечены как ложные срабатывания: pydantic-валидаторы `_validate_*`/`_deserialize_devices`,
`__post_init__`/dunders, `_cmd_*` executor'а (getattr-диспетчеризация), Protocols
`ClockSink`/`SupportsRealtime`, `add_transport_listener`.

### 2.3. Дублирование (≥ 10 строк, подтверждено)

| Что | Где | Оценка |
|---|---|---|
| `_enqueue` drop-oldest (try/put→Full→get+put→Empty→retry) | tick_proxy.py:138–152 · capture_output.py:168–183 · drum_engine.py:135–146 · melodic_engine.py:338–349 | ~14 строк ×4, дословно |
| `port_label` + `set_port_label` | drum_engine.py:47–63 ≡ melodic_engine.py:85–102 | ~16 строк, дословно (тела и docstring) |
| Кортеж 12 нот «C…B» | screen_controller.py:122–135 (`ROOTS`) ≡ repl/completer.py:34–46 (`NOTES`) | одинаковые значения |

Не дедуплицируется (решение по KISS): guard `send_midi` в lcxl3_device.py:275–281 ≈
push2_device.py:212–219 (мелкий паттерн с вариациями); docstring `poll()` ×2
(abc.py:407, mido_impl.py:73). Устаревший комментарий `widgets.py:23–24`
(«дублирует screens.py» — импорт констант уже идёт из widgets, screens.py:56–60).

### 2.4. Нечитаемые ключи конфига (определены, не читаются нигде)

- `drum.preview_on_select`, `drum.preview_velocity` (drum_config.py:20–21,
  DEFAULT_CONFIG_YAML config.py:169–170)
- `mutation.drift_step_gate`, `drift_step_density`, `drift_step_register`
  (mutation_config.py:23–25, DEFAULT_CONFIG_YAML config.py:174–176;
  `MutationEngine()` создаётся без аргументов, из MutationConfig читается только `.enabled`)

### 2.5. Модули без прямых тестов (справочно, в план не входит)

device_manager, repl/completer, repl/history_store, repl/log_buffer,
logging_config, app/config, sync/config, main.py — принимаются как есть;
добавление тестов не входит в скоуп cleanup'а.

### 2.6. Актуальность техдолга из AGENTS.md (проверка по коду)

- **«Двойное применение свинга» — НЕ АКТУАЛЬНО:** в src/session/ нет ни одного
  вхождения «swing»; свиг применяется только в `src/sync/transport.py`
  (`_swing.shift`, transport.py:236–247). Снять пункт в G1-8.
- Остальные пункты подтверждены: on-demand дорожки не регистрируются в
  MutationEngine (`_init_mutation` только на старте, `refresh_track` — no-op для
  незарегистрированных); `set_profile` — отложенное пересоздание по revision;
  каналы — глобально по сессии (session.py:109–121); LCXL3 EncoderHandler удалён.

## 3. Батчи

Порядок — от безопасного к рискованному. Каждый батч самодостаточен: зелёный
pytest, ruff/black на изменённых файлах, отдельный коммит.

### G1-1: Полностью мёртвый код — 6 символов

1. Повторный grep каждого символа (src, tests, spikes) — 0 вхождений вне определения.
2. Удалить: `save_config()`, `set_device_config()`, `_percent()`,
   `DemoScreen._bottom_name()`, `create_device()`, `create_cc_map()`.
3. `pytest` зелёный (изменений в тестах не ожидается).

Риск: нулевой. Объём: ~6 деклараций + докстринги.

### G1-2: Мёртвый в проде — код и тесты удаляются вместе

Политика (YAGNI): символ без вызовов в проде удаляется вместе с покрывающими его
тестами; история остаётся в git. Порядок внутри батча — по группам из 2.2,
один коммит на группу:

1. mutation (5 символов) и session/model/engine (3).
   **Нюанс:** `unregister_track()` выглядит как *пропущенная проводка* (при
   `remove_track` мутационное состояние дорожки остаётся в MutationEngine до
   перезапуска). Удаляем метод по политике, а саму дыру фиксируем как наблюдение
   в техдолге (G1-8) — чинить в этом плане нельзя (изменение поведения).
2. sync: cc_map-автоматизация (3 метода + чистка `__repr__`), ports/routing (4).
3. harmony-хелперы: `voicing_notes`, `triad_quality`, `seventh_quality`, `roman`
   (+ их тесты; `voicing_degrees`/`to_offsets`/`invert`/`VOICINGS` не трогаем).
4. push2: renderer (3), widgets `Widget`/`Column`, `set_display_frame_callback()`.
   `Widget` — runtime_checkable Protocol без единого использования: удалить
   (виджеты на утиной типизации — `render(fb, rect)` по факту).
5. `screens.py:821–867` — модульные `draw_*`-делегаты и их пиксельные тесты:
   тесты из `test_screens_render.py`, привязанные к делегатам, переписать на
   `Screens().draw_body(...)`/Screen-классы; тесты, дублирующие `test_widgets.py`,
   удалить. Рендер не меняется — PNG-дампы spike байтово совпадают.
6. app/repl: пара `track_sources()`, `sysex_with_framing()` из ABC.

Риск: низкий; главный объём — переписывание пиксельных тестов (п. 5).

### G1-3: Срез библиотечных API до используемого

1. `src/core/color.py`: grep фактического использования в src; почти весь API
   (`to_rgb565/from_rgb565/to_bgr565/from_bgr565/to_hex/from_hex/chroma/saturation/
   is_achromatic/is_chromatic/relative_luminance`) живёт только в tests/test_color.py.
   Оставить используемое подмножество, остальное удалить вместе с тестами.
   Переносов (например, в palette.py) не делать — KISS.
2. Проверить, что после среза `core/` не остался модулем-пустышкой (219 строк →
   ожидаемо < 100).

Риск: низкий. Спорная точка плана — если color/harmony считаются публичным API
«на вырост», батч пропускается целиком (решение зафиксировано: срезаем).

### G1-4: Гигиена линтеров

1. **black:** отформатировать 11 файлов (ui_queue, color, palette, widgets,
   clock_manager, layout + 5 тестовых).
2. **ruff (50):** автофикс 10; вручную:
   - F811 ×8 — дубли определений в тестах, удалить старые копии;
   - BLE001 ×17 (push2_device, clock_manager, clock_source, lcxl3_device,
     device_manager, display, config) — по месту: сузить тип исключения или
     заменить на `log.exception`/явную обработку; поведение не менять;
   - PYI034 ×4, UP037 ×4, UP046 ×1, C408 ×1, I001 ×4, RUF059 ×3, SIM117 ×2,
     S110 ×2, TRY004 ×2, F401 ×2 — механические правки.
3. **mypy:** исправить 9 arg-type (melodic_track ×3, generators ×3,
   push2_display ×3, application ×2, остальные по 1) и 1 return-value, где это
   дёшево; 10 import-untyped (isobar/mido/usb — внешние библиотеки без stubs)
   не трогать.
4. Новая база: ruff 0, black 0, mypy ≤ 20 и без новых.

### G1-5: Дедупликация (только дословные дубли)

1. `_enqueue` drop-oldest ×4 → одна функция в новом модуле `src/core/`
   (например `core/enqueue_drop_oldest.py`, generic по типу элемента). Импортируют
   tick_proxy, capture_output, drum_engine, melodic_engine. Поведение очередей
   (drop-oldest при Full, retry при Empty) не меняется — регрессия существующими
   тестами tick_proxy/capture_output/движков.
2. `port_label`/`set_port_label` ×2 → общая база для Melodic/DrumEngine
   (миксин или базовый класс в `session/engine/`; при исполнении выбрать
   наименьшую абстракцию, разделяющую состояние `port_label`).
3. Кортеж 12 нот → `NOTE_NAMES` в `harmony/` (слой ниже app и repl);
   `ROOTS` (screen_controller) и `NOTES` (completer) импортируют.
4. Поправить устаревший комментарий `widgets.py:23–24`.
5. Анти-цели: `send_midi` guard, docstring `poll()` — не трогаем (решение KISS).

Риск: низкий; всё покрыто существующими тестами.

### G1-6: Конфиг — нечитаемые ключи (явное исключение из «без поведения»)

1. Проверка безопасности: `model_config`/`extra` в схемах не заданы → pydantic v2
   default `extra='ignore'`; убедиться тестом, что конфиг с удалёнными ключами
   грузится без ошибок (маленький регресс-тест на обратную совместимость —
   единственное *добавление* теста в плане).
2. Удалить `preview_on_select`/`preview_velocity` из `DrumConfig`,
   `drift_step_*` из `MutationConfig`, те же ключи из `DEFAULT_CONFIG_YAML` и из
   `config.yaml` (корневого), а также упоминания из README, если есть.
3. ROADMAP/исторические упоминания (C4) не переписываются — история планов.

Риск: низкий; обратная совместимость сохранена через `extra='ignore'`.

### G1-7: Разбивка гигантов (последний структурный батч)

Кандидаты после G1-2 (объёмы пересчитать): `screen_controller.py` 1229,
`application.py` 995, `screens.py` 868 (после удаления делегатов может уже не быть
гигантом), `engine_control.py` 715.

1. Правило: только механический перенос по принципу «один класс — один файл»
   (AGENTS.md) — константы/LED-карты/вью-хелперы уходят в соседние модули своего
   же слоя; никакой новой логики, никаких новых слоёв.
2. Импорты обновляются точечно; кольца запрещены — при появлении цикла перенос
   откатывается и фиксируется как «оставлено намеренно».
3. Регрессия рендера: PNG-дампы `spike_ui_simulate` байтово совпадают.

Риск: средний (большие диффы). Смягчение: батч последний, до начала D3 —
иначе D3 снова раздует `screen_controller.py`.

### G1-8: Документация итогов

1. `AGENTS.md`: снять неактуальный пункт «двойное применение свинга» (п. 2.6),
   добавить наблюдение про `unregister_track` (см. G1-2), обновить счётчики
   (тесты, ruff/black/mypy, строки src).
2. `plans/ROADMAP.md`: статусы батчей G1, замеры «после».
3. `graphify update .`.

## 4. Критерии приёмки всего плана

- `uv run pytest` зелёный после каждого батча; финальное число тестов фиксируется
  (ожидаемо < 1830 — падение только за счёт тестов удалённого мёртвого кода,
  разница обосновывается построчно в G1-8).
- ruff: 0 на src+tests (было 50); black: 0 файлов (было 11); mypy: без новых,
  цель ≤ 20.
- Поведение не изменилось: сценарии 1–9 `spike_ui_simulate` PASS, PNG-дампы
  без изменений; E2E MIDI (`spike_e2e_midi_sink`) PASS.
- Замер «после» в ROADMAP: строки/файлы src до/после (ожидание −400…−800 строк
  src — справочно, не целевая метрика).
- Каждый из дублей 2.3 имеет единственный источник; 6+~30 мёртвых символов
  удалены; 5 ключей конфига удалены с сохранением обратной совместимости.

## 5. Риски

| Риск | Митигация |
|---|---|
| Инвентарь устареет к моменту исполнения | Повторный grep каждого символа перед удалением (шапка, п. 7) |
| Тесты используют мёртвый символ как инфраструктуру | Прогон pytest внутри каждой группы; падение — пересмотр символа, не «подгонка» теста |
| `draw_*`-делегаты держат пиксельные тесты | Переписать на `Screens` API; дубли test_widgets — удалить; рендер не трогаем |
| BLE001: часть широких catch — осознанная защита на границах железа | По месту: сузить тип или `log.exception`; без изменения поведения |
| pydantic отвергнет старые конфиги | Проверка `extra='ignore'` + регресс-тест до удаления ключей (G1-6) |
| Разбивка гигантов конфликтует с будущими ветками | G1-7 последним; весь G1 рекомендуется завершить до D3 |
| Удаление скроет пропущенную проводку (`unregister_track`) | Дыра фиксируется в техдолге (G1-8), не «чинится» молча |
