# Proposal: init-current-system

## Why

Проект уже инициализирован в OpenSpec (`schema: spec-driven`), но в `openspec/specs/`
пусто: всё зафиксированное поведение системы живёт только в разрозненных доках
(`AGENTS.md`, `docs/track-hierarchy.md`, `docs/mutation-manual-spec.md`,
`plans/ROADMAP.md`). Нет машиночитаемого источника истины «что система делает
сейчас», на который будущие изменения могли бы опираться дельтами. Нужен
baseline: спеки, описывающие текущее, реально реализованное поведение (тесты
1830 passed), чтобы дальнейшие работы (D3, E1/E2, хвост C2) шли как обычные
changes поверх него.

## What Changes

- Добавляется первый (baseline) набор capability-спек, фиксирующих **текущее**
  поведение системы по 8 областям. Каждая capability описана дельтой `ADDED`.
- Изменений кода нет: это purely документационный change. Описывается только
  реализованное поведение; известный техдолг (двойной свинг, on-demand
  дорожки вне MutationEngine, Mode B EXTERNAL, отложенное мигание дисплея)
  в требования не включается и фиксируется отдельно в design.md.
- Не описываются (не начаты): D3 — режимы падов CHORDS/NOTES/MORPH/DRUM;
  E1-хвост — персист выбора клока/портов в конфиг; E2 — systemd/8-часовой
  прогон; хвост C2 — валидация пары (лад, войсинг).

## Capabilities

### New Capabilities

- `harmony`: гармонический слой — Root+Scale (`Harmony`), валидация ладов,
  диатонические аккорды, войсинги (`VOICINGS`), обращения (`invert`),
  резолвинг ступени в MIDI-нотy.
- `track-graph`: модель дорожек и граф — `Track`/`MelodicTrack`/`DrumTrack`,
  профили как данные, `ChordEvent`-граф с топосортом и защитой от циклов,
  лимиты сессии, автоназначение каналов, стратегия B при удалении источника.
- `drum-engine`: drum-машина — 16 lane GM 36–51, евклидовы ритмы с кешем,
  сетка шагов, три уровня velocity, `step_to_note()`, мост в транспорт.
- `mutation`: ручная мутация и линейная история — `NEW`/`evolve` на границе
  цикла дорожки, pending-флаг, `VersionHistory` (стек, лимит 256, корень),
  undo/recall, счётчик как курсор, LED-индикация падов.
- `clock-sync`: клок и транспорт — три источника (internal/MIDI/Link) с
  квантизацией переключения на долю, watchdog recovery, TickProxy-очередь,
  свинг длительностями, MIDI clock out из таймлайна.
- `midi-routing`: порты и CC — логические лейблы (match/serial), статусы
  connected/disconnected/ambiguous, hot-plug polling ~2 c, `ports switch`,
  автоназначение MIDI-каналов (9 — drum), cc_map (логические имена, per-port
  переопределения, invert/range), троттлинг CC 30 Гц.
- `push2-ui`: дисплей и экраны Push 2 — рендерер BGR565 (FrameBuffer,
  DirtyTracker, GlyphCache), отправка кадра по dirty + keepalive, scene
  composer с frozen view-DTO, экраны TRACKS/TRACK/GLOBAL/SYNC/PORTS/VERSIONS,
  таб-бар, энкодеры, NEW/UNDO, сетка падов версий.
- `repl-control`: REPL и фасад управления — prompt_toolkit REPL (статус-бар
  ~2 Гц, история, автодополнение, подтверждения), `EngineControl` как
  единственный фасад доступа к движку, `StatusSnapshot`, команды status /
  clock / ports / track / evolve / undo / recall / history.

### Modified Capabilities

(пусто — спек ещё нет, это первый baseline)

## Impact

- Код: не затрагивается.
- Артефакты: `openspec/specs/` (создаётся 8 capability-спек после
  синхронизации дельт), `openspec/changes/init-current-system/` (этот change).
- Документация: после archive baseline в `openspec/specs/` — с этого момента
  новые изменения дают дельты относительно зафиксированного поведения.
- Зависимости: без изменений.
