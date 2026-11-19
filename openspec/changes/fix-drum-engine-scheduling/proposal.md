# Proposal: fix-drum-engine-scheduling

## Why

Дефект вскрылся при приёмке change `add-drum-pattern-api` (его финализация —
блок 9 — выполняется отдельно и в этот change не входит): разбор
`captures/capture_20261119_165602.mid` через `spikes/spike_midi_dump.py`
показал 285 608 note_on и 0 note_off — каждая позиция drum-паттерна
продублирована ровно 15 032 раза (= число тиков транспорта), синтезатор
держит залипшие ноты.

Диагноз (факт-чек по коду):

1. `DrumEngine.tick(current_beat, bpm)` (`src/session/drum/drum_engine.py:66`)
   вызывается на каждом TICK (хук `src/app/application.py:518`) и вызывает
   `DrumTrack.generate()` (`src/session/model/drum_track.py:99`), который
   регенерирует весь бар с паттерн-относительными битами (0..steps/4).
   `_to_transport_event` кладёт `TransportEvent.note_on(beat=ev.beat)` —
   `current_beat` игнорируется, события доставляются немедленно → каждый тик
   весь бар ударов уходит в порт заново.
2. Note_off для drum никто не планирует: `DrumEngine` кладёт только note_on
   с `duration=DEFAULT_GATE` (0.25), а Transport `duration` использует только
   для свинга.
3. Эталон решения уже есть: `MelodicEngine` переведён на lookahead-планировщик
   `BeatScheduler` (`src/session/engine/beat_scheduler.py`) — однократная
   доставка в свой бит, пары note_on/note_off, reset при STOP. DrumEngine этот
   перевод не проходил.

## What Changes

- `DrumEngine` переводится на `BeatScheduler` (переиспользование, без нового
  класса планировщика): достройка окна циклами, вплоть до границы цикла
  (design §2) — окно может превышать `now + horizon`; однократная доставка
  каждого удара в свой абсолютный бит, note_off-пары.
- Генерация циклами: паттерн циклится через `steps/4` битов (steps — сетка
  дорожки, 16/32/48/64); абсолютная позиция удара шага `s` цикла `k` —
  `k·(steps/4) + s·0.25` битов (шаг сетки — фиксированная 16-я, 0.25 бита,
  независимо от steps; правка `drum_track.py:136` — единственное изменение
  модели, design §9). Ссылка на генерацию — `DrumTrack.generate()`
  (не меняется, вызывается не чаще одного раза на цикл — outbox, который
  `generate()` очищает и заново наполняет при каждом вызове, обновляется
  реже, чем сегодня: раз на цикл вместо каждого тика; семантика §4.5
  сохраняется, потребителей outbox в `src/` нет); движок маппит
  паттерн-относительные биты в абсолютные и фильтрует уже покрытое окном.
- Планирование note_off на `beat + DEFAULT_GATE` (0.25) для каждого удара:
  capture/SMF получают парные события, синтезатор не держит ноты.
- Реакция на правку паттерна (pad-грид Push 2, `set_drum_pattern` из
  REPL/скрипта, мутация на границе цикла, undo/recall): движок детектит
  изменение снимка lane-паттернов и mute-состояний, снимает запланированные
  вперёд note_on (`cancel_from`) и перестраивает окно — применение сразу, как
  в мелодическом движке (B2).
- `DrumEngine.reset()` + вызов в START/STOP-ветке dispatch-хука
  `application.py` (сейчас reset получают только melodic-движки).
- Свинг не трогается: он живёт в Transport и применяется к NOTE_ON onset;
  движок отдаёт чистые биты, как сегодня.
- Регресс-тесты: луп тиков → каждый hit ровно один раз на абсолютной позиции
  (эталон позиций — `examples/drum_dub.py`); парность note_on/note_off;
  mute/порт/all_notes_off; сквозной тест через Transport+CaptureRecorder.

Из скоупа осознанно НЕ входит: пересмотр свинга (двойное применение —
отдельный техдолг), финализация `add-drum-pattern-api`, пересмотр
outbox-семантики §4.5, MutationEngine, Push 2 UI. Единственная правка
модели — точечная: `drum_track.py:136` (`step_duration` → фиксированные
0.25, design §9); контракты `generate()` (outbox, длина паттерна) не
меняются.

## Capabilities

### Modified Capabilities

- `drum-engine`: добавляются требования к доставке drum-событий в транспорт —
  однократная доставка в абсолютный бит (lookahead-планировщик), парные
  note_on/note_off, реакция на правку паттерна и mute/порт, сброс при
  STOP/START. Базовые требования capability (16 lane GM, сетка, евклид,
  velocity, one-shot, резолвинг, предпрослушка) не меняются.

Базовая спека capability описана change'ом `init-current-system` (пока не
синхронизирована в `openspec/specs/`); дельта написана как `ADDED` относительно
пустой main-спеки — имена требований не пересекаются с baseline.

## Impact

- Код: `src/session/drum/drum_engine.py` (порт на планировщик — основной
  объём), `src/app/application.py` (reset drum-движков в START/STOP-ветке
  хука), `src/session/model/drum_track.py` (точечно: `step_duration` →
  0.25, design §9). `MutationEngine`, Transport — без правок; README и
  `examples/` — только формулировка «весь бар» → «весь цикл» (задача 1.6,
  код примера не меняется).
- Тесты: `tests/test_drum_engine.py` переписывается под планировщик (сегодня
  фиксирует пачечную доставку); новые — луп тиков, парность, правки паттерна,
  hook START/STOP, сквозной тест capture. По образцу `TestBeatScheduling`
  (`tests/test_melodic_engine.py`) и `tests/test_engine_control_capture.py`.
- Зависимости: без изменений. `session.drum` начинает импортировать
  `session.engine.beat_scheduler` — циклов нет (`beat_scheduler` зависит только
  от `sync`). База линтеров (ruff 50 / black 11 / mypy 20, пре-существующие,
  baseline 2026-11-19) не должна вырасти.
