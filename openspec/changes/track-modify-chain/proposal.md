# Proposal: track-modify-chain

## Why

Библиотека модификаций `src/session/modify/` (`Chain`, `ArpeggiateStage`,
`DensifyStage`) реализована и протестирована (B1–B4), но ни одна дорожка её
не использует: `Track` не хранит цепочку, генераторы не применяют её, в REPL
нет команд управления. События дорожки нельзя модифицировать на лету —
арпеджиатор и прореживание доступны только как встроенные механизмы
генераторов, а не как пользовательская надстройка. Одновременно в modify/
есть известные дефекты: приватный импорт `_density_keep` из
`engine/generators.py` (нарушение слоёв) и усечение `int(e.beat)` в
`DensifyStage`, ломающее решение по позиции после этапов, дробящих время.

## What Changes

- **Модель**: базовый `Track` (ABC, `src/session/model/track.py`) получает
  поле `chain` — `Chain[NoteEvent]`, дефолт пустой (тождественная цепочка),
  property с fail-fast валидацией в сеттере. `MelodicProfile` получает
  frozen-поле `chain` (дефолт пустой); `MelodicTrack.__init__` копирует
  `profile.chain` в атрибут дорожки. Все профили реестра `PROFILES` получают
  пустую цепочку по умолчанию (решение в design.md §3).
- **Движок**: `MelodicEngine` применяет `track.chain.process(batch, ctx)` к
  паттернному outbox генератора (`generate_notes`) после генерации, единообразно
  для всех семей. Chord outbox (`ChordEvent`) и копии `inject_sources` не
  трогаются. Семантика «на лету» (вариант B): замена цепочки подхватывается со
  следующего тика — без квантизации на границу ступени, через снятие
  запланированных вперёд note-on и пересборку горизонта. `revision` не трогается.
- **Drum**: `DrumEngine` игнорирует непустую цепочку drum-дорожки с
  лог-предупреждением (однократно на дорожку); дизайн цепочек для drum —
  вне скоупа.
- **Фиксы modify/**:
  - вынос `_density_keep` из `engine/generators.py` в новый модуль
    `src/session/model/density.py` (публичная `density_keep`); `generators.py`
    и `modify/densify.py` импортируют оттуда — циклов нет;
  - контракт `DensifyStage` «до этапов, дробящих время» зафиксирован в
    docstring + тест на документированное поведение после `Arpeggiate`;
  - валидация `density` 0.0..1.0 в `DensifyStage.__post_init__`;
  - типизация этапов — `Stage[NoteEvent]`-совместимые сигнатуры;
  - `Chain` — frozen dataclass (этапы уже frozen).
- **Фасад**: не абстрактные методы `EngineControl` `track_chain`,
  `track_chain_add`, `track_chain_remove` (прецедент C1–C4) + реализация в
  `AppEngineControl` через новый реестр этапов `src/session/modify/stage_registry.py`.
- **REPL**: команды `track chain <name> show|add|remove`; автодополнение
  дорожек, действий и имён этапов (провайдер `"stage"`).
- **Скрипты** (решение ревизии): `ScriptSession` получает плоские 1:1
  обёртки над фасадными методами — `show_track_chain(name)` (список этапов
  в `data["chain"]`), `track_chain_add(name, spec)` (строка-спецификация
  `"arpeggiate step=0.25 direction=up"` через `parse_stage_spec`),
  `track_chain_remove(name, index)`. Drum-дорожки: успешный результат с
  текстом-предупреждением (не fail-fast). `ScriptValidator`/`ScriptRunner`
  не меняются (рефлексия арности + `__getattr__`-обёртка).
- **README**: раздел «Модификации на лету: цепочка этапов».

Из SCOPE осознанно НЕ входит: новые этапы (Transpose, Drop и др.), REPL-команда
`set` (полная замена — эмулируется remove+add), цепочки для drum-дорожек,
статическая проверка литеральных спецификаций этапов в `ScriptValidator`
(например «arpeggiate:step=0.25») — семантика спецификаций проверяется
рантаймом через реестр этапов, отображение цепочки в `track show`/StatusSnapshot,
укорочение последней ноты арпеджио на эпсилон (дизайн-заметка, design.md §9).

## Capabilities

### Modified Capabilities

- `track-graph`: добавляются требования — поле `chain` у дорожки (источник —
  профиль, дальше только дорожка), применение цепочки движком к паттернному
  outbox (NoteEvent) с семантикой «на лету», игнорирование drum-дорожкой,
  контракт этапов библиотеки modify (frozen, валидация, порядок Densify).
- `repl-control`: добавляются требования — методы фасада `track_chain` /
  `track_chain_add` / `track_chain_remove`, REPL-команды `track chain …`,
  автодополнение дорожек/действий/этапов, скриптовый фасад `ScriptSession`
  (обёртки show/add/remove со стабильным контрактом данных `data["chain"]`/
  `data["stage"]`; drum-дорожки — успешный результат с предупреждением).
  Отдельной capability `scripting` в baseline нет (план G2 её не создавал) —
  скриптовые требования идут в `repl-control` по прецеденту change
  `add-drum-pattern-api` (требование «Скриптовый фасад установки паттерна»).

Базовые спеки этих capabilities описаны change'ом `init-current-system` (пока
не синхронизирован в `openspec/specs/`); дельты здесь написаны как `ADDED`
относительно пустых main-спек, требования не пересекаются с baseline по именам
и после синхронизации обоих change'ов сходятся в единые спеки без конфликтов.

## Impact

- Код: `src/session/modify/` (`chain.py`, `densify.py`, `arpeggiate.py`,
  новый `stage_registry.py`), `src/session/model/` (новый `density.py`,
  `track.py`, `melodic_profile.py`, `melodic_track.py`),
  `src/session/engine/` (`generators.py`, `melodic_engine.py`, `drum_engine.py`),
  `src/repl/engine_control.py` + `src/app/engine_control.py`,
  `src/scripting/script_session.py` (новые обёртки; validator.py/runner.py
  не меняются),
  `src/repl/parser.py`/`executor.py`/`completer.py` + `src/main.py`, `README.md`.
- Тесты: обновления `tests/test_modify_*.py`, новые `tests/test_track_chain.py`,
  `tests/test_melodic_engine_chain.py`, `tests/test_engine_control_track_chain.py`,
  `tests/test_repl_track_chain.py`, `tests/test_script_session_chain.py`;
  обновления `tests/test_scripting_validator.py`, `tests/test_scripting_runner.py`,
  `tests/test_stage_registry.py`.
- Зависимости: без изменений. База линтеров (ruff 50 / black 11 / mypy 20,
  пре-существующие) не должна вырасти.
