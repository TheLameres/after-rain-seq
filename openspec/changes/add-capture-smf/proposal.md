# Proposal: add-capture-smf

## Why

Верификация бита сегодня требует DAW: пользователь записывал вывод приложения
в Ableton Live 12 и получил «ковёр» из ~98k событий — Live-экспорт объясняет
формат (ch0/vel64/96tpb), но сам поток был ~50× плотнее нормы из-за разгона
клока (петля self-echo: clock-out и clock-in в config.yaml указывают на одну
IAC-шину; транспорт самостартовал от эха — «transport already running»).
Разгон клока — отдельный открытый баг (зафиксирован в `plans/ROADMAP.md`,
вне этого change'а). Нужен штатный способ записать вывод приложения в SMF
(.mid) с реальными таймингами и проверить бит без DAW — существующим спайком
`spikes/spike_midi_dump.py` (секции структуры/аномалий/`--drum-dub`).

## What Changes

- Новый накопитель событий `CaptureRecorder` (слой `src/sync/`): Transport
  при доставке note_on/note_off пишет в него событие с эффективной позицией
  в битах (для отложенных свингом — момент фактической отправки). CC,
  ALL_NOTES_OFF и real-time клок не пишутся (расширения будущего).
- Новый писатель SMF `SmfWriter` (слой `src/sync/`, первая точка использования
  mido для записи в `src/`): один трек (SMF type 0), PPQ 480 (как
  `ticks_per_beat` Timeline), меты track_name/set_tempo/time_signature 4/4,
  tempo = BPM на момент старта захвата. Файл создаётся на `capture stop`
  эксклюзивно (`xb`) — перезапись существующего запрещена.
- Методы фасада `EngineControl.capture_start(path)` / `capture_stop()` /
  `capture_status()` — не абстрактные с дефолтом `fail` (прецедент C1–C4 и
  `set_drum_pattern`) + реализация в `AppEngineControl` (автогенерация имени
  `captures/capture_YYYYmmdd_HHMMSS.mid` с созданием каталога; состояние
  захвата живёт в фасаде, Transport получает/теряет sink атомарной заменой
  ссылки).
- REPL-команды домена `capture`: `capture` (статус), `capture start [path]`,
  `capture stop`; парсер/executor/completer по образцу домена `drum`.
- Обёртки `ScriptSession.capture_start`/`capture_stop`; валидатор подхватывает
  методы рефлексией (как в add-drum-pattern-api) — фиксируется тестом.
- Раздел README «Запись в MIDI-файл (capture)».
- Вне кода: в `plans/ROADMAP.md` зафиксирован открытый баг «clock self-echo /
  runaway» как кандидат на следующий change.

Из SCOPE осознанно НЕ входит: CC/автоматизация и real-time клок в SMF,
отслеживание смены BPM во время захвата (один set_tempo на старте),
переключение захвата из Push 2 UI, секция `capture` в config.yaml
(каталог по умолчанию — константа; конфиг — расширение будущего),
починка разгона клока (отдельный баг в ROADMAP).

## Capabilities

### New Capabilities

- `capture-smf`: запись вывода приложения в SMF — состав потока (note_on/
  note_off как доставляет Transport), тайминг (реальные позиции в битах,
  PPQ, tempo-мета старта), управление записью (start/stop/статус, старт при
  стоящем транспорте), файловая семантика (автогенерация имени, запрет
  перезаписи), верифицируемость спайком.

### Modified Capabilities

- `repl-control`: добавляются требования к методам фасада `capture_start`/
  `capture_stop`/`capture_status`, REPL-командам домена `capture` и
  автодополнению; скриптовый фасад получает те же операции.

Базовые спеки capabilities описаны change'ом `init-current-system` (пока не
синхронизирован в `openspec/specs/`); дельта `repl-control` написана как
`ADDED` относительно baseline, требования не пересекаются с ним по именам.

## Impact

- Код: `src/sync/capture_recorder.py` и `src/sync/smf_writer.py` (новые
  модули, один класс — один файл), `src/sync/transport.py` (sink-точка рядом
  с trace, без изменения публичного контракта доставки), `src/repl/
  engine_control.py` + `src/app/engine_control.py` (фасад; протокол
  `AppPorts` пополняется членом `sync_bpm` для tempo-меты), `src/repl/
  parser.py`/`executor.py` (completer — статическое дерево из таблицы),
  `src/scripting/script_session.py`, `README.md`.
- Тесты: unit-тесты писателя (round-trip через mido), накопителя, sink-точек
  Transport (включая свинг и отброшенные события), фасада, REPL,
  ScriptSession, конкурентный стоп из другого потока; файлы — только в
  `tmp_path`.
- Зависимости: без изменений (mido уже в зависимостях). База линтеров
  (ruff 50 / black 11 / mypy 20, пре-существующие) не должна вырасти.
- Состояние базы: 2053 passed (2026-11-19).
