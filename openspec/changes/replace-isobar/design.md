# Design: replace-isobar

## Context

isobar 0.2.1 обслуживает три роли: таблица ладов (`Scale.byname`/`Key.get`),
метроном+счётчик (`Timeline` для INTERNAL, включая `isobar.Clock`), легаси-адаптеры
(`CaptureOutput`, докстринги, `int()`-защиты). Полная карта и сверка с кодом —
`docs/isobar-replacement-analysis.md` (утверждён 2026-11-19; все координаты
подтверждены при подготовке этого change). Ограничения: слои `src/` без циклов,
«один класс — один файл», кросс-поточное взаимодействие через очереди, baseline
линтеров из AGENTS.md не ухудшается. По mypy: импорты isobar в `harmony.py:23/26`
уже подавлены `# type: ignore[import-untyped]` и в baseline 20 не входят;
unsuppressed-импорты — только `clock_source.py:246` и `application.py:466`.
Решения пользователя 2026-11-19 обязательны: алиасы ладов включаются;
`TransportMode.ISOBAR` → `TICK_THREAD`; `InternalClockSource` на
`time.perf_counter()`; `CaptureOutput` остаётся.

## Goals / Non-Goals

**Goals:**

- Ноль импортов и упоминаний isobar в `src/`, `tests/`, `pyproject.toml`
  (включая докстринги и легаси-отсылки `ISOBAR_DEFAULT_MIDI_IN`/`PWhite`).
- Время — единственный владелец `TimeBase` (целочисленные тики, биты float);
  INTERNAL-генератор на `perf_counter()`.
- Поведение сохранено 1:1: контракт времени (480 PPQN, биты, квантизация,
  восстановление фазы), таблица ладов (включая алиасы), тишина при STOP/смене
  источника, STOP-артефакт остаётся (осознанно).
- Каждая фаза независимо тестируема: зелёные тесты и линтеры в конце фазы.

**Non-Goals:**

- Реализация Transport Mode B (свой поток отправки) — только заложенный интерфейс.
- Устранение STOP-артефакта (отложенный CC123-бёрст после рестарта) — фиксируется
  как известное ограничение, чинится отдельно.
- numpy, mido/python-rtmidi, мигание дисплея, D3/E1/E2/C2, RPi5-прогон, спайки.
- События доли/такта и пересчёт секунд↔биты (элементы варианта C — ориентир для
  будущего Mode B).

## Decisions

### D1. Вариант B: Protocol + TimeBase + InternalClockSource (вместо минимального клона)

Формализуем duck-typed контракт источников в протокол **`ClockSourceProtocol`** в
`src/sync/clock_source.py` (имя разграничено с существующим enum `ClockSource`
того же модуля): `clock_target`, `ticks_per_beat`, `tempo` — **только чтение**
(`float | None`; Protocol фиксирует то, что потребляет система; запись темпа —
свойство конкретных источников INTERNAL/Link), `run()`, `stop()`, `background()`.
`ClockManager.set_tempo(value)` направляет значение только источникам, у которых
есть сеттер (MIDI read-only пропускается) — это соответствует дельте `clock-sync`
(требование «Контракт источника клока»). Новые модули stdlib-only:
`src/sync/time_base.py` (`TimeBase`: `_ticks: int`, `current_time` property
`= _ticks / ticks_per_beat`, `tick()`, `reset()`, `stop()` no-op,
`set_beats(beats)` с округлением до ближайшего тика
(`_ticks = round(beats * ticks_per_beat)`), `ticks_per_beat = 480`) и
`src/sync/internal_clock.py` (`InternalClockSource`: алгоритм isobar `Clock` 1:1 —
абсолютное планирование `tick_start += duration`, догон пропущенных батчем,
daemon-поток через `background()`, live-пересчёт длительности при смене `tempo`,
`stop()` через `Event`; источник времени — module-level indirection
`_now = time.perf_counter`, вызов через `_now()`, чтобы тесты патчили точку
времени детерминированно; множитель тиков `target_tpb // own_tpb` с проверкой
делимости; экспонирует `_thread`, как `_LinkClockSource`).

*Альтернативы:* вариант A (минимальный клон duck-typed Timeline — сохраняет
легаси-поверхность `output_devices`/`tempo`-делегацию и неформализованный
контракт); вариант C (полный BeatClock-домен с событиями доли и секунд↔биты —
избыточен до Mode B). B выбран как рекомендация анализа: убирает зомби-объекты
и фоновый поток статистики isobar, делает контракт явным, не блокирует Mode B.

*Осознанное небольшое улучшение остановки:* сегодня `ClockManager._stop_current_source`
(`clock_manager.py:387`) делает `src._thread.join(...)`, но у isobar `Clock`
атрибута `_thread` нет — join является no-op. `InternalClockSource` экспонирует
`_thread` (как `_LinkClockSource:106`), поэтому join становится осмысленным:
stop-гейт ждёт завершения потока генерации до восстановления фазы.

### D2. `all_notes_off` CaptureOutput: notes-off-callback в ClockManager (решение 4)

CaptureOutput остаётся; после удаления Timeline у `TimeBase` нет
`output_devices`, поэтому сегодняшний путь `ClockManager._all_notes_off →
timeline.output_devices` исчезает. Выбран способ: **`ClockManager.__init__`
принимает `notes_off: Callable[[], None] | None = None`**; приложение
привязывает его к `capture.all_notes_off` в `_init_clock_manager` (создание
capture остаётся там же, где раньше создавался Timeline); `_all_notes_off()`
вызывает callback — семантика enqueue `ALL_NOTES_OFF` в транспортную очередь
сохраняется 1:1 (асинхронная доставка при следующем тике, как сегодня).
Хук `hooked_dispatch` при STOP после `original_dispatch(event)` добавляет
`capture.all_notes_off()` — точное воспроизведение сегодняшнего порядка
(enqueue ПОСЛЕ того, как хук уже погасил порты транспортной тишиной и опустошил
очередь), то есть STOP-артефакт остаётся ровно сегодняшним (решение 4:
артефакт сохраняется, фиксируется ниже).

*Альтернативы:* (1) `PortRegistry.all_outputs()` из ClockManager — синхронная
доставка в порты меняет семантику (сегодня — enqueue через транспортную очередь),
дублирует `Transport.all_notes_off()`, зависит от открытости портов
(`all_outputs()` возвращает только активные адаптеры) и требует второй ссылки
(registry + capture) в ClockManager — отвергнуто; (2) типизированная ссылка на
`CaptureOutput` в ClockManager — связывает ядро клока с транспортным
capture-модулем импортом; callback слабее по связности, тестируется фейковым
callable, ClockManager не узнаёт о существовании очереди TransportEvent —
выбрано; (3) `TimeBase.stop()` с хуком — тянет транспортную ответственность в
счётчик времени, против единственной роли TimeBase — отвергнуто.

### D3. Golden-фикстура гармонии (снимается до удаления библиотеки)

Фаза 1 генерирует `tests/fixtures/key_get_golden.py` — словарь
`(root, scale, degree) → int` для сетки `{10 имён} × {12 корней} × {степени
−7..+21}` прогоном живого `isobar.Key.get` (isobar ещё установлен на этой
фазе). Имя файла и его докстринг — без подстроки «isobar»: статический импорт
фикстуры в `test_harmony.py` попал бы иначе в исходник теста и провалил бы
гейт фазы 3 (`grep -r isobar tests` — 0). Провенанс формулируется как «эталон,
снятый с удаляемой библиотеки до её удаления» (полные детали — в
`docs/isobar-replacement-analysis.md` §4.4, файл вне гейтов); одноразовый
генератор фикстуры коммиту не подлежит — снимается временно и в git не попадает.
Тест `Harmony.degree_to_semitone` против фикстуры обязан совпадать 1:1
(имя теста и докстринг — без подстроки «isobar»);
рукописные якоря `test_harmony.py` (A dorian 8 → 23; degree_to_note 8 → 83;
C major → 60/64/67; A4 → 69) остаются. Фикстура статична — после удаления isobar
остаётся эталоном; расширение набора ладов — отдельное решение за
`_validate_harmonic`. Семантика сохраняется точно: смещение включает pitch
class корня («от MIDI 0», не «от тоники» — докстринг исправляется), перенос
октавы `divmod(degree, 7)`, `degree_to_note = semitone + 12·octave`.

### D4. Слои и импорты без циклов

`time_base.py` и `internal_clock.py` — stdlib-only, никого не импортируют из
`src/`; ниже `clock_source`/`clock_manager`. `clock_source.py` объявляет
`ClockSourceProtocol` и фабрику; INTERNAL-ветка фабрики импортирует
`InternalClockSource` локально (как сегодня импортирует isobar.Clock).
`ClockManager` — `_time_base` вместо `_timeline`; `set_sync_bpm` приложения
идёт через `ClockManager.set_tempo(value)` → активный источник с сеттером
(зомби-запись `timeline.tempo` исчезает; проверка `cm.state.running` и
`current_source is ClockSource.INTERNAL` сохраняется в приложении).
`TickProxy` диспетчеризует в `TimeBase`, `ticks_per_beat` читает у него.
Хук приложения читает `time_base.current_time` (6 точек). Экспорты
`src/sync/__init__.py` обновляются по факту использования: `TimeBase`/
`InternalClockSource` реэкспортируются, только если их импортируют из-за пределов
sync-слоя (сегодня потребители вроде `application.py` импортируют модульные пути
напрямую) — лишних экспортов не появляется, задачи 2.1/2.2 владеют этим пунктом.
Потокобезопасность
фазы сохраняется автоматически: `_apply_pending` выполняется в worker-потоке
TickProxy — все записи TimeBase сериализованы с тиками.

### D5. Переименование `TransportMode.ISOBAR` → `TICK_THREAD` (решение 2)

Enum-значение переименовывается в фазе 3 (чистка), а не в фазе 2: фаза 2 не
трогает транспорт, и атомарность «имя enum + все докстринги transport-слоя
без isobar» — один шаг. Затронуто: `transport.py` (определение, дефолт
конструктора, сообщение об ошибке EXTERNAL), `test_transport.py`
(`test_default_mode_is_isobar`, `test_set_mode_isobar`). Внешнего API-контракта
на строковом имени нет (значение не сериализуется в конфиг) — ломающего
изменения для пользователя нет; для кода — переименование enum-значения,
отмечено **BREAKING** в proposal.

### D6. Порядок фаз и mypy-baseline: гармония → клок → чистка → свинг-хвост

Гармония изолирована от клока; golden-фикстуру снимаем с живого isobar до его
удаления. По mypy: обе import-строки `harmony.py:23/26` уже подавлены
`# type: ignore[import-untyped]` — фаза 1 счёт mypy **не меняет** (гейт: «без
новых ошибок»); улучшение −2 от baseline 20 происходит в **фазе 2**, когда
уходят единственные unsuppressed `import-untyped isobar` (`clock_source.py:246`,
`application.py:466`). Зависимость из pyproject удаляется только в фазе 3
(после фазы 2 isobar в рантайме не участвует). `uv sync` (пересборка `uv.lock`)
— на фазе 3, выполняет coder. Свинг-хвост — документация + сквозной тест,
зависящий от финального вида transport-слоя. Фазы независимы: каждая
заканчивается зелёными тестами и линтерами (baseline AGENTS.md: ruff 50 /
black 11 / mypy 20 — не ухудшать; тест-прогресс пересчитывает tester).

Полная карта упоминаний isobar (гейты задач по фазам не сужаются, критерий
«0 упоминаний в src, tests, pyproject.toml» остаётся): прямые импорты —
`harmony.py`, `application.py`, `clock_source.py` (фазы 1–2); докстринги —
`voicings.py:20` (фаза 1), `tick_proxy`/`routing`/`transport`/`transport_event`/
`swing`/`capture_output`/`config.py`/`clock_manager.py` + README.md:59 +
`smf_writer.py:5` («PPQ 480 (= ticks_per_beat Timeline)» — ссылка на
несуществующий после замены объект; слова isobar нет, правится явно)
(фаза 3), `euclidean.py`/`melodic_engine.py:16`/`melodic_track.py:282`/
`param_drift.py:26`/`mutation/__init__.py:9` (фаза 3), тест-файлы
`test_clock_manager.py:29` (MockTimeline переписывается в 2.4),
`test_capture_output.py`, `test_routing.py:103`, `test_midi_clock_in.py:4`,
`test_clock_source.py:88` (фазы 2–3). Правки `voicings.py:20` и
тест-докстрингов вынесены в отдельные трекуемые пункты (1.4, 3.2) — выбор:
отдельные пункты вместо вложения в соседние задачи, чтобы каждый файл имел
собственную проверяемую строку гейта grep.

### D7. Квантизация на целочисленной базе времени

`current_time = ticks / 480` всегда кратно 1/480, поэтому позиции между
тиками недостижимы: ближайшая вне-долевая позиция 479/480 отстоит от границы
на 1/480 ≈ 0.00208, что больше `_BEAT_EPSILON = 0.001` (`clock_manager.py:38`).
Сегодняшние epsilon-тесты (позиции 4.9995/5.0005, шаг += 0.002 в
`test_clock_manager.py`) с честным целочисленным фейком неисполнимы и
переформулируются на целые тики: 2399/480 → заявка pending висит; 2400/480 →
применяется. Поведение не деградирует: переключение происходит на граничном
тике, сдвиг ≤ 1 тик (~1.04 мс при 120 BPM против float-накопленного
4.9995/5.0005 у isobar, которое лишь случайно проходило допуск). `_BEAT_EPSILON`
остаётся в коде предохранителем на случай внешних источников с субтиковой
позицией. Восстановление фазы через `set_beats` округляется до ближайшего тика
(`round(beats * 480)`) — позиция после смены источника всегда тиковая.

## Risks / Trade-offs

- **Jitter собственного тик-потока vs isobar Clock** → алгоритм переносится 1:1
  (абсолютное планирование + догон); `perf_counter` строго лучше (`time.time()`
  уязвим к NTP-скачку); sleep-гранулярность та же (0.1 мс); точка времени
  `_now` — module-level indirection, тесты патчат её (детерминизм). Проверка
  smoke `--simulate` в фазах 2 и 4; железо (RPi5) — вне скоупа.
- **STOP-артефакт остаётся (известное ограничение)** → `CaptureOutput.all_notes_off`
  при STOP кладёт `ALL_NOTES_OFF` в очередь после того, как хук уже погасил всё
  и опустошил её; событие лежит до первого тика после рестарта и даёт лишний
  CC123-бёрст. По решению пользователя артефакт не устраняется: воспроизводится
  1:1 (D2), фиксируется в «Известных ограничениях» `AGENTS.md` в фазе 3.
  Устранение — отдельная задача вне этого change.
- **Тонкие эффекты окна активации при смене источника** → логика `ClockManager`
  не меняется (pending, epsilon-квантизация, watchdog, слушатели транспорта,
  fallback на internal); меняется только объект времени; тесты квантизации
  переформулируются на целые тики (D7); покрытие уже есть
  (`test_phase_preserved_on_switch`, watchdog, порядок событий транспорта в
  `test_midi_clock_out.py`).
- **Живая зависимость тестов от Timeline** → `tests/test_midi_clock_in.py`
  хелпер `_app()` строит реальный App и возвращает `cm._timeline`
  (чтения `current_time`/`ticks_per_beat`) — правится в 2.6 на `cm._time_base`,
  чтения сохраняются; не только докстринги.
- **Дрейф baseline линтеров** → после фаз 1 и 3 baseline переснимается; правило
  «без новых замечаний» сохраняется; mypy улучшается на −2 в фазе 2 (D6).
- **Golden-фикстура может не покрыть будущие лады** → фикстура снимается для
  полного текущего набора (10 имён); новые лады — отдельное решение.

## Migration Plan

1. Фаза 1 (гармония): golden-фикстура → `scales.py` → переписать `harmony.py`
   (удалить `key`/`apply`) → докстринг `voicings.py:20` → тест эквивалентности.
   Откат: revert фазы, isobar ещё установлен.
2. Фаза 2 (клок): `TimeBase` + `InternalClockSource` + `ClockSourceProtocol` →
   фабрика → `ClockManager`/`TickProxy`/хук (включая `_app()` в
   `test_midi_clock_in.py` и тиковые тесты квантизации) → smoke `--simulate`.
   Откат: revert; isobar ещё установлен.
3. Фаза 3 (чистка): докстринги (src + тест-файлы), переименование enum,
   `pyproject.toml` − isobar, `uv sync`, `AGENTS.md` (+ известное ограничение
   STOP), README.md:59, ROADMAP-запись. Откат после `uv sync`: вернуть
   зависимость в pyproject и повторить `uv sync`.
4. Фаза 4 (свинг-хвост): чистка техдолга AGENTS.md, сквозной свинг-тест,
   финальный smoke. Тест-прогресс пересчитывает tester.

## Archive Ordering

Порядок архивации с открытым change'ом `init-current-system`: главные спеки
(`openspec/specs/`) пусты и появятся при архивации. Архивировать сначала
`init-current-system` (создаст `clock-sync`, `harmony` и прочие), затем
`replace-isobar` — его ADDED-требования лягут в те же capability. Имена
требований выбраны непересекающимися; семантические дубли устранены: дельты
`replace-isobar` расширяют, а не дублируют init-current-system («All-notes-off
без isobar Timeline» уточняет «Гарантированную остановку нот», «START как сброс
позиции» уточняет «Очередь тиков», «Набор валидных ладов не меняется» — в
составе «Таблицы ладов без isobar» со ссылкой на «Валидацию ладов»); перекрёстные
ссылки в текстах сценариев допустимы. При конфликте имён при архивации —
переименовать требование в дельте `replace-isobar`.

## Open Questions

Нет — все четыре вопроса анализа закрыты решениями пользователя 2026-11-19
(зафиксированы в `docs/isobar-replacement-analysis.md` §10.2).
