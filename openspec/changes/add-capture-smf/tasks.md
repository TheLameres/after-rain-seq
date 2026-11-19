# Tasks

> В этом конвейере тесты и линтеры не запускаются — их прогоняет исполнитель
> в задачах финализации (блок 8). Каждая задача ниже несёт критерий готовности,
> проверяемый её собственным тестом, когда прогон станет доступен.
> База: 2053 passed; линтеры ruff 50 / black 11 / mypy 20 (пре-существующие) —
> не наращивать. Тесты пишут файлы только в tmp_path.

## 1. Накопитель (слой sync)

- [x] 1.1 В `src/sync/capture_recorder.py`: DTO `CaptureEntry` (frozen
  dataclass: `kind: EventKind`, `channel: int`, `note: int`,
  `velocity: int | None`, `beat: float`) и класс `CaptureRecorder` —
  `record(kind, channel, note, velocity, beat)` (append в list),
  `entries() -> list[CaptureEntry]` (копия-снимок), `__len__`. Никаких
  импортов выше sync (кроме `transport_event`); mido не нужен. Потоки:
  атомарный append, снимок — новый список (design §4).
  Критерий: файл проходит ruff/black/mypy; импорты только вниз.
- [x] 1.2 Тесты `tests/test_capture_recorder.py`: запись/снимок/длина;
  снимок — независимая копия (дальнейшие record не меняют снимок);
  параллельные record из двух потоков не теряются и не роняют
  (smoke с threading).

## 2. Писатель SMF (слой sync)

- [x] 2.1 В `src/sync/smf_writer.py`: класс `SmfWriter`, метод
  `write(path: Path, entries: Sequence[CaptureEntry], bpm: float,
  ticks_per_beat: int = 480) -> None` — design §3: SMF type 0, один трек,
  меты track_name/set_tempo (`mido.bpm2tempo`)/time_signature 4/4,
  абсолютный тик `round(beat * ticks_per_beat)`, сортировка по составному
  ключу (абсолютный тик; tie-break: `note_off` раньше `note_on`; при равных
  тике и виде — порядок доставки), дельты (первая — от нуля), note_off
  настоящим `note_off` (0x80; velocity=None). Файл открывается
  `open(path, "xb")` — эксклюзивное создание; `FileExistsError`/`OSError`
  поднимаются как есть. Критерий: ruff/black/mypy чисто; импорты — только
  sync/mido.
- [x] 2.2 Тесты `tests/test_smf_writer.py` (round-trip через mido, всё в
  tmp_path): тип 0, ticks_per_beat, tempo-мета = bpm, размер 4/4; позиции
  (абс-тики) и каналы совпадают; note_off — 0x80; порядок/дельты при
  неупорядоченном входе (сортировка стабильна, отрицательных дельт нет);
  **tie-break: note_off и note_on одной ноты на одном тике (gate 0.25 =
  1/16, соседние удары lane) → в файле off раньше on независимо от порядка
  доставки входного списка — перекрытия одинаковых нот нет**; события на
  одном тике с разными видами/нотами сохраняют ожидаемый порядок; запись в
  занятый путь → `FileExistsError`; запись в несуществующий каталог →
  `OSError`; пустой список → валидный файл только с метами.

## 3. Точка захвата в Transport

- [x] 3.1 В `src/sync/transport.py`: ссылка `self._capture_sink`
  (None по умолчанию), свойство `capture_sink` и метод
  `set_capture_sink(sink: CaptureRecorder | None)` (атомарная замена,
  design §2); в `_deliver` после успешного резолва порта (рядом с trace)
  — `sink.record(...)` для `NOTE_ON`/`NOTE_OFF` с эффективным битом;
  `_deliver` получает параметр `capture_beat: float` (по умолчанию —
  `event.beat`); вызовы из `_schedule` (немедленная доставка —
  `event.beat`) и `_release_due` (сохранённый `deliver_at`) передают
  эффективный бит (design §1). Публичный контракт доставки и trace не
  меняются. Критерий: ruff/black/mypy чисто; существующие тесты
  транспорта зелёные.
- [x] 3.2 Тесты `tests/test_transport_capture.py` (или рядом): доставленные
  note_on/note_off пишутся с каналом и velocity; CC и ALL_NOTES_OFF не
  пишутся; событие без порта не пишется (trace-семантика не тронута);
  свинг: NOTE_ON, отложенный на deliver_at, записан с битом deliver_at,
  немедленный — с event.beat; замена sink на None посреди потока — новые
  события не пишутся; стоп из другого потока (тест с моком: sink снимается
  из стороннего потока во время доставки — без дедлока, recorder валиден).

## 4. Фасад: EngineControl + AppEngineControl

- [x] 4.1 В `src/repl/engine_control.py`: не абстрактные методы
  `capture_start(self, path: str | None) -> EngineResult`,
  `capture_stop(self) -> EngineResult`,
  `capture_status(self) -> EngineResult` с дефолтом
  `EngineResult.fail("capture is not supported by this control")`
  (прецедент C1–C4/`set_drum_pattern`); docstring по конвенции файла.
- [x] 4.2 В `src/app/application.py` и `src/app/engine_control.py`:
  протокол `AppPorts` пополняется членом `sync_bpm: float` (read-only
  свойство App, значение `self._sync_bpm`) — источник fallback-BPM для
  tempo-меты (design §5).
- [x] 4.3 В `src/app/engine_control.py`: состояние захвата
  (`_capture_recorder/_capture_path/_capture_bpm`, None по умолчанию).
  `capture_start`: транспорт недоступен → fail; уже активен → fail
  («capture already running»); путь None → автогенерация
  `captures/capture_YYYYmmdd_HHMMSS.mid` (+ суффикс `_NN` при коллизии),
  `mkdir(parents=True, exist_ok=True)`; явный путь существует → fail;
  BPM = `clock_manager.state.bpm or sync_bpm`; recorder прикрепляется
  `transport.set_capture_sink(...)`. Успех: путь + bpm, data `{"path": ...}`.
  `capture_stop`: не активен → fail; sink снимается, снимок →
  `SmfWriter.write` (FileExistsError/OSError → fail); успех: путь + N
  событий, data. `capture_status`: активен → путь/bpm/счётчик (ok);
  не активен → «capture is not active» (ok). Сообщения по design §6.
- [x] 4.4 Тесты `tests/test_engine_control_capture.py`: happy path
  (старт/статус/стоп, автогенерация в tmp_path через monkeypatch
  константы каталога), явный путь, ошибки (уже активен, стоп без захвата,
  файл существует на старте, транспорт недоступен), транспорт стоит —
  старт ok и файл на стопе пуст по нотам, мок-контроль возвращает
  дефолтный fail для всех трёх методов, tempo-мета = state.bpm и
  fallback sync_bpm при None.

## 5. REPL: команды и автодополнение

- [x] 5.1 В `src/repl/parser.py`: три `CommandSpec` домена `capture` —
  `capture` (bare, max_args=0, статус), `capture start [path]`
  (min_args=0, max_args=16, join_args=True), `capture stop`
  (min_args=0, max_args=0); usage/help по конвенции таблицы.
- [x] 5.2 В `src/repl/executor.py`: `_cmd_capture` → `capture_status()`,
  `_cmd_capture_start` → `capture_start(args[0] if args else None)`,
  `_cmd_capture_stop` → `capture_stop()`; результат через `_feedback`.
  Критерий: ошибка движка → `CommandResult(code=1)`, цикл живёт.
- [x] 5.3 Тесты: парсинг `capture`, `capture start`, `capture start takes/take1.mid`,
  `capture start "My Takes/take 1.mid"` (join), `capture stop`; ошибки
  арности (`capture start a b c …` > 16, `capture stop x`); executor →
  вызовы мок-контроля; автодополнение домена и действий (`capture st<TAB>`).

## 6. Скриптовый фасад

- [x] 6.1 В `src/scripting/script_session.py`: методы
  `capture_start(self, path: str | None = None, *, fatal: bool = True)
  -> EngineResult` и `capture_stop(self, *, fatal: bool = True)
  -> EngineResult` — обёртки 1:1 через `_call`. В `ScriptValidator` правок
  не требуется: `_facade_methods` строится рефлексией (design §8) — факт
  фиксируется тестом.
- [x] 6.2 Тесты `tests/test_scripting_session.py` (+ validator): обёртки
  прокидывают аргументы (path=None и явный); `ScriptValidator` пропускает
  `session.capture_start()`/`session.capture_start("x.mid")`/
  `session.capture_stop()` и ловит неверную арность
  (`capture_start("a", "b")`) и неизвестный kwarg.

## 7. Интеграция и документация

- [x] 7.1 Интеграционный тест фасад-путь с реальным Transport: очередь
  событий → Transport с прикреплённым recorder (как в App) → доставка
  note-событий двух «дорожек» (каналы 0 и 9) → стоп через AppEngineControl
  (мок App) → файл читается mido: каналы/ноты/позиции соответствуют
  доставленным, CC отсутствуют. Файл — в tmp_path.
- [x] 7.2 `README.md`: раздел «Запись в MIDI-файл (capture)» после раздела
  про REPL-команды — команды `capture`/`capture start [path]`/`capture stop`,
  автогенерация `captures/capture_YYYYmmdd_HHMMSS.mid`, запрет перезаписи,
  что пишется (note_on/note_off как доставляет транспорт, канал как есть)
  и что не пишется (CC/клок), tempo = BPM на старте (смена BPM не пишется),
  приёмка через `spikes/spike_midi_dump.py` (включая `--drum-dub`), вызовы
  из скриптов (`session.capture_start/capture_stop`).

## 8. Финализация (исполнитель)

- [ ] 8.1 Прогнать `uv run pytest` — все тесты зелёные, включая новые
  блоки 1–7.
- [ ] 8.2 Линтеры без роста базы: `uv run ruff check src tests`,
  `uv run black --check src tests`, `uv run mypy src` — сравнить с базой
  2026-11-19: ruff 50, black 11 файлов, mypy 20.
- [ ] 8.3 `openspec validate add-capture-smf` и
  `openspec status --change add-capture-smf` — все артефакты done,
  валидация без ошибок.
- [ ] 8.4 Ручная приёмка в `--simulate --repl`: `script run
  examples/drum_dub.py` → `capture start` → несколько баров → `capture stop`
  → `uv run python spikes/spike_midi_dump.py <файл> --drum-dub` →
  kick/snare/hat/shaker/conga OK (позиции на 16-й сетке, ch9,
  velocity-полосы 90–100/120–127). Повторный `capture start` с тем же
  путём → ошибка; `capture stop` без захвата → ошибка.
- [ ] 8.5 После реализации: `graphify update .` — граф не знает про новые
  модули `capture_recorder.py`/`smf_writer.py`, sink в Transport и домен
  `capture` в REPL.

## Workflow follow-up

- Дельта затрагивает `repl-control`, чей baseline описан в
  `init-current-system` (ещё не синхронизирован): синхронизировать оба
  change'а вместе (openspec-sync-specs) либо архивировать их в
  согласованной очерёдности; `capture-smf` — новая capability, ляжет в
  `openspec/specs/capture-smf/` при первом sync/archive.
- Отдельный баг «clock self-echo / runaway» зафиксирован в
  `plans/ROADMAP.md` как кандидат на следующий change — не входит в этот.
