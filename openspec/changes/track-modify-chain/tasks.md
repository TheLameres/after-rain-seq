# Tasks

> В этом конвейере тесты и линтеры не запускаются — их прогоняет исполнитель
> в задачах финализации (блок 8). Каждая задача ниже несёт критерий готовности,
> проверяемый её собственным тестом, когда прогон станет доступен.

## 1. Фиксы modify/ (слой session.modify)

- [x] 1.1 Создать `src/session/model/density.py`: публичная
  `density_keep(index: int, density: float) -> bool` — тело без изменений из
  `generators._density_keep` (детерминированный фильтр D2 §3.6, docstring
  переносится). Модуль — листовой: только stdlib, никаких импортов из session/.
  Критерий: файл проходит ruff/black/mypy; `from src.session.model.density
  import density_keep` работает без побочных импортов.
- [x] 1.2 В `src/session/engine/generators.py`: удалить `_density_keep`,
  импортировать `density_keep` из `src.session.model.density`; обновить
  вызов в `_gen_free_mono` на `density_keep(i, track.density)`.
  Критерий: grep не находит `_density_keep` в `src/`; существующие тесты
  генераторов зелёные.
- [x] 1.3 В `src/session/modify/densify.py`: импорт из
  `src.session.model.density` (устраняет приватный кросс-модульный импорт).
  Критерий: `modify/densify.py` не импортирует ничего из `session.engine`.
- [x] 1.4 В `src/session/modify/densify.py`: `__post_init__` с валидацией
  `0.0 <= density <= 1.0` → `ValueError` с русским сообщением (по образцу
  `ArpeggiateStage`); типизация `process(self, batch: list[NoteEvent],
  ctx: StageContext) -> list[NoteEvent]`; docstring — контракт «Densify — до
  этапов, дробящих время» (после `ArpeggiateStage` ноты получают дробные биты,
  решение по `int(e.beat)` деградирует — документированное поведение).
  Критерий: mypy по `src/` не добавляет ошибок; docstring отражает контракт.
- [x] 1.5 В `src/session/modify/arpeggiate.py`: типизация
  `process(self, batch: list[NoteEvent], ctx: StageContext) -> list[NoteEvent]`
  (и внутренних `_group`/`_order` — `list[NoteEvent]`). Критерий: mypy по
  `src/` без новых ошибок.
- [x] 1.6 В `src/session/modify/chain.py`: `Chain` → frozen dataclass
  (`stages: Sequence[Stage[T]] = field(default_factory=tuple)`, остальное без
  изменений). Критерий: существующие тесты `test_modify_chain.py` зелёные
  без правок.
- [x] 1.7 Тесты `tests/test_modify_chain.py` (дополнение): frozen `Chain`
  (присвоение `stages` → `FrozenInstanceError`), дефолт пустого конструктора
  `Chain()` == `Chain([])`. Критерий: новые кейсы зелёные.
- [x] 1.8 Тесты `tests/test_modify_densify.py` (обновление + дополнение):
  импорт `density_keep` из `src.session.model.density`; валидация density
  (`-0.1`, `1.1` → `ValueError`, `0.0`/`1.0` — валидны); тест-инспекция
  `test_generator_already_thins_by_density` обновить: искомая строка
  `density_keep(i, track.density)` в исходнике генератора, docstring —
  «DEN остаётся в генераторе, DensifyStage в цепочке — отдельный механизм».
  Критерий: старый импорт `from src.session.engine.generators import
  _density_keep` отсутствует (фиксируется проверкой отсутствия).
- [x] 1.9 Тест `tests/test_modify_densify.py` (новый класс): документированное
  поведение после Arpeggiate — цепочка `[ArpeggiateStage(step=0.25),
  DensifyStage(0.0)]` на аккорде из 4 нот (beat 0): арпеджио разворачивается
  (ноты на 0/0.25/0.5/0.75), прореживание применяет решение по схлопнутым
  индексам (`int(0.25) == int(0.75) == 0`) — зафиксировать точный snapshot
  выживших нот; повторное применение на том же входе даёт тот же результат.
  Критерий: тест зелёный и документирует контракт из design §6.

## 2. Модель: Track и MelodicProfile

- [x] 2.1 В `src/session/model/track.py`: импорт `Chain` из
  `src.session.modify.chain`; в `Track.__init__` — `self._chain: Chain[NoteEvent]
  = Chain()`; property `chain` (getter/setter) с fail-fast валидацией: не
  `Chain` → `TypeError`; элемент `stages` без `name` (str) или без callable
  `process` → `ValueError`. Docstring атрибута в классе (дефолт — тождество).
  Критерий: `MelodicTrack`/`DrumTrack` создаются с пустой цепочкой; присвоение
  корректной цепочки работает.
- [x] 2.2 В `src/session/model/melodic_profile.py`: поле
  `chain: Chain[NoteEvent] = field(default_factory=Chain)` в `MelodicProfile`
  (docstring: «цепочка модификаций по умолчанию; дефолт реестра — пустая»).
  Критерий: `MelodicProfile` остаётся frozen; все 11 профилей реестра создаются.
- [x] 2.3 В `src/session/model/melodic_track.py`: в `__init__` после
  валидации профиля — `self.chain = profile.chain` (через сеттер базового
  класса); docstring `set_profile` — дополнить «не сбрасывает chain».
  Критерий: `MelodicTrack(profile_name="pad").chain` — пустая цепочка;
  присвоенная дорожке цепочка переживает `set_profile`.
- [x] 2.4 Тесты `tests/test_track_chain.py` (новый): дефолт пустой цепочки у
  `MelodicTrack` и `DrumTrack`; сеттер: не-`Chain` → `TypeError`, элемент без
  `process` → `ValueError`, корректная цепочка принимается; у **каждого**
  профиля в `PROFILES` `len(chain) == 0` (проверка реестра, не перечисления);
  `MelodicTrack` копирует `profile.chain` (ссылка — один и тот же объект);
  правка дорожки не меняет профиль; `set_profile` не сбрасывает цепочку;
  drum-дорожка хранит непустую цепочку без ошибок. Критерий: все кейсы зелёные.

## 3. Движок: MelodicEngine и DrumEngine

- [x] 3.1 В `src/session/modify/chain.py`: полю `StageContext.bpm` — дефолт
  `0.0` с docstring-пометкой «темп не подключён; движок не читает клок; этапы
  не используют». Docstring поля `beat` (строка 24) уточнить: сейчас читается
  как «текущая позиция тика», а на деле движок передаёт **фазу паттерна** —
  начало текущего цикла (абсолютный beat, `self._origin` движка). Критерий:
  существующие тесты с `StageContext(beat, bpm, track_name)` зелёные без правок.
- [x] 3.2 В `src/session/engine/melodic_engine.py` в `_pattern()`: после
  `generate_notes(ctx)` применить `self._track.chain.process(notes,
  StageContext(beat=self._origin, track_name=self._track.name))`; docstring
  дополнить: цепочка применяется к паттернному outbox (NoteEvent) единообразно
  для всех семей; chord outbox и `inject_sources` не трогаются.
  Критерий: пустая цепочка — результат `_pattern()` бит-в-бит прежний
  (существующие тесты движка зелёные).
- [x] 3.3 В `src/session/engine/melodic_engine.py`: атрибут
  `self._chain_seen: Chain[NoteEvent] | None = None`; в `tick()` после
  обработки pending-прогрессии и перед `_extend_horizon` — если
  `self._track.chain is not self._chain_seen`:
  `cancel_from(current_beat)` + `rewind_to(current_beat)` (только если
  watermark > now) + `self._chain_seen = self._track.chain`; docstring `tick`
  дополнить семантикой live-swap. Критерий: mypy по `src/` без новых ошибок.
- [x] 3.4 Тесты `tests/test_melodic_engine_chain.py` (новый):
  - пустая цепочка не меняет расписание (сравнение с движком без цепочки);
  - дорожка с `ArpeggiateStage` в цепочке: паттерн движка разворачивает
    аккорды (note_on позиции арпеджио), публичный chord outbox не меняется;
  - live-swap: запланировать с пустой цепочкой, заменить на арпеджиатор,
    `tick(now)` → события с `beat >= now` перестроены по новой цепочке,
    ноты с `beat < now` не тронуты;
  - смена цепочки не увеличивает `track.revision`;
  - повторный tick с той же цепочкой (идентичность) — без пересборки
    (watermark продолжает расти, счётчик снятий = 0);
  - оба механизма в одном тике: pending-прогрессия применяется на границе
    ступени, цепочка — от `now`.
  Критерий: все кейсы зелёные.
- [x] 3.5 В `src/session/drum/drum_engine.py` (или точке генерации drum):
  если `track.chain` непустая — лог-предупреждение однократно на дорожку
  (флаг в движке); генерация не меняется. Путь — защита для прямого
  присвоения цепочки в модель: через фасад (задача 4.4) недостижимо —
  фасад drum непустую цепочку не применяет (design §8). Критерий: повторные
  генерации не дублируют предупреждение.
- [x] 3.6 Тесты `tests/test_drum_engine_chain.py` (новый): drum-дорожка с
  непустой цепочкой — ритм идентичен дорожке с пустой; предупреждение в лог
  ровно одно (каптур лога), при повторной генерации — без новых записей.
  Критерий: кейсы зелёные.

## 4. Фасад: EngineControl + AppEngineControl

- [x] 4.1 Создать `src/session/modify/stage_registry.py`:
  `STAGE_FACTORIES: dict[str, Callable[[Mapping[str, str]], Stage[NoteEvent]]]`
  (`arpeggiate`: step=float, direction=str; `densify`: density=float,
  обязательный), `build_stage(name, params) -> Stage[NoteEvent]` — неизвестное
  имя → `ValueError` с перечнем доступных, неизвестный параметр / нечисловое
  значение → `ValueError` с русским сообщением; `format_stage(stage) -> str`
  (`arpeggiate step=0.25 direction=up`);
  `parse_stage_spec(spec: str) -> tuple[str, Mapping[str, str]]` — первая
  лексема — имя этапа, остальные — пары `k=v` (лексема без `=` или дубликат
  ключа → `ValueError` с русским сообщением; используется REPL-executor'ом и
  ScriptSession). Слой modify, импортов вверх нет.
  Критерий: файл проходит ruff/black/mypy.
- [x] 4.2 Тесты `tests/test_stage_registry.py` (новый): build_stage для обоих
  этапов (дефолты, явные параметры), ошибки (неизвестное имя с перечнем,
  неизвестный параметр, `step=abc`, отсутствующий обязательный `density`),
  format_stage для обоих, parse_stage_spec (круговая согласованность
  `parse_stage_spec(format_stage(s))`, ошибки: пустая строка, лексема без
  `=`, дубликат ключа). Критерий: кейсы зелёные.
- [x] 4.3 В `src/repl/engine_control.py`: не абстрактные методы
  `track_chain(name: str) -> EngineResult`,
  `track_chain_add(name: str, stage_name: str, params: Mapping[str, str]) ->
  EngineResult`, `track_chain_remove(name: str, index: int) -> EngineResult`
  с дефолтом `EngineResult.fail("track chain is not supported by this
  control")` (прецедент C1–C4). Критерий: мок-контролы в существующих тестах
  не ломаются.
- [x] 4.4 В `src/app/engine_control.py`: реализации через `_melodic_track`
  (ошибка «not found» — как у set_track_gate). Контракт данных:
  `track_chain` → `data["chain"]` (список строк `format_stage`),
  `track_chain_add` → `data["stage"]` (спецификация добавленного этапа) +
  `data["chain"]` (итоговая), `track_chain_remove` → `data["chain"]`.
  Melodic-дорожки: `track_chain` — сообщение `track "X": chain = <этапы
  через format_stage, через " → ">` или `chain = — (empty)`;
  `track_chain_add` — `build_stage` (`ValueError` → fail), присвоение
  `track.chain = Chain(stages + (stage,))`, итоговая цепочка в сообщении;
  `track_chain_remove` — индекс 1..len (иначе fail), пересборка
  `Chain(stages без элемента)`. Drum-дорожки: все три операции возвращают
  успешный результат с явным текстом-предупреждением «дорожка drum: цепочка
  игнорируется (спецификация не применена)» — спецификация не применяется,
  `track.chain` не изменяется, `data["chain"]` — пустой список.
  Критерий: присвоение через сеттер — валидация fail-fast на месте.
- [x] 4.5 Тесты `tests/test_engine_control_track_chain.py` (новый): happy path
  show/add/remove (с кавычечными именами), ошибки (нет сессии, нет дорожки,
  неизвестный этап, плохой параметр, индекс вне диапазона),
  неизменность цепочки при ошибке, мок-контроль возвращает дефолтный fail;
  drum-дорожка — успешный результат с предупреждением, цепочка не изменена,
  `data["chain"]` пустой.
  Критерий: кейсы зелёные.

## 5. Скрипты: ScriptSession (решение ревизии — входят в этот change)

- [x] 5.1 В `src/scripting/script_session.py`: плоские 1:1 обёртки над
  фасадными методами (в стиле `set_track_gate`/`set_drum_pattern`, через
  `_call`, `fatal: bool = True` по умолчанию):
  `show_track_chain(name)` → `track_chain` (структурированные данные в
  `EngineResult.data`: `data["chain"]` — список строк-спецификаций этапов,
  скрипт ветвится по `len(result.data["chain"])`);
  `track_chain_add(name, spec)` — `parse_stage_spec(spec)` из
  `src.session.modify.stage_registry` (`ValueError` → `EngineResult.fail`,
  при `fatal=True` — `ScriptError`) → фасадный `track_chain_add(name,
  stage_name, params)`; `track_chain_remove(name, index)` → фасадный
  `track_chain_remove`. Импорт `src.session.modify.stage_registry` —
  новое ребро `scripting → session.modify` (документированное исключение,
  design §11). Критерий: `_facade_methods()` рефлексией видит три новых
  метода — правок validator.py не требуется.
- [x] 5.2 Тесты `tests/test_script_session_chain.py` (новый): happy path
  show/add/remove через мок-контроль; контракт данных `data["chain"]` и
  `data["stage"]` (текст message — не контракт); ошибки (неизвестный этап,
  плохой параметр, некорректная спецификация — `fatal=True` → `ScriptError`,
  `fatal=False` → ошибочный результат, который скрипт ветвит сам);
  drum-дорожка: `fatal=True` НЕ бросает, результат успешен (error=False) с
  текстом-предупреждением, `data["chain"]` пустой, спецификация не
  применена. Критерий: кейсы зелёные.
- [x] 5.3 Тесты `tests/test_scripting_validator.py` (дополнение): новые
  методы видны в линте арности — вызов `track_chain_add` с одним аргументом
  вместо двух диагностируется до исполнения, `script check` без правок
  validator.py ловит неверную арность и неизвестный kwarg. Критерий:
  кейсы зелёные, validator.py не изменён.
- [x] 5.4 Тесты `tests/test_scripting_runner.py` (дополнение): скрипт,
  вызывающий `track_chain_add` на drum-дорожке, продолжает работу —
  предупреждение попадает в `output_lines` отчёта, `calls` растёт,
  `format_report` не меняется; скрипт, организующий строгий режим сам
  (`fatal=False` + проверка `result.error`), ветвится по результату.
  Критерий: кейсы зелёные, runner.py не изменён.

## 6. REPL: команды и автодополнение

- [x] 6.1 В `src/repl/parser.py`: `CommandSpec` `track chain` —
  `min_args=2, max_args=16, join_args=False`; usage
  `track chain <name> show | add <stage> [k=v ...] | remove <n>`;
  имена дорожек с пробелами — в кавычках (конвенция `track sources`).
- [x] 6.2 В `src/repl/executor.py`: `_cmd_track_chain` — `args[0]` дорожка,
  `args[1]` действие: `show` → `track_chain`; `add` → `args[2]` имя этапа,
  `args[3:]` пары `k=v` (нет `=` или дубликат ключа → `CommandResult(code=1)`)
  → `track_chain_add`; `remove` → `args[2]` как int (не число → ошибка) →
  `track_chain_remove`; неизвестное действие → ошибка с usage. Результат через
  `_feedback`. Критерий: ошибка → `CommandResult(code=1)`, цикл живёт.
- [x] 6.3 В `src/repl/completer.py` + `src/main.py`: динамический контекст —
  после `track chain` имена дорожек (как `track delete`); после `add` —
  провайдер `"stage"` (инжект из `main.py` из `STAGE_FACTORIES`; `repl/` не
  импортирует `session`). Статическое дерево действий пополняется из таблицы
  parser'а. Критерий: `track chain "Pad 1" <TAB>` → show/add/remove,
  `add ar<TAB>` → `arpeggiate`.
- [x] 6.4 Тесты `tests/test_repl_track_chain.py` (новый): парсинг всех форм
  (`show`, `add` с параметрами и без, `remove`), кавычечные имена, ошибки
  арности/действия/пар `k=v`; executor → вызовы мок-контроля (включая
  передачу параметров строками); дополнение дорожек/действий/этапов.
  Критерий: кейсы зелёные.

## 7. Документация

- [x] 7.1 `README.md`: раздел «Модификации на лету: цепочка этапов» после
  раздела о track-командах — команды `track chain` с примерами (`add
  arpeggiate step=0.25 direction=up`, `add densify density=0.5`, `remove`,
  `show`), таблица параметров этапов, контракт Densify (ставить до
  арпеджиатора), пометка «замена подхватывается со следующего тика» и
  «drum-дорожки цепочку игнорируют» (фасад возвращает успех с
  предупреждением, спецификация не применяется), пометка о двойном
  прореживании (макро-ось DEN + DensifyStage — осознанная комбинация).
  Там же — скриптовый фасад: обёртки `show_track_chain` /
  `track_chain_add(name, spec)` / `track_chain_remove` с примером скрипта
  (ветвление по `len(result.data["chain"])`, добавление строкой-спецификацией
  `"arpeggiate step=0.25 direction=up"`) и пометкой, что на drum-дорожке
  `track_chain_add` возвращает успех с предупреждением в отчёте.
  Критерий: примеры соответствуют фактическим сообщениям фасада.
- [x] 7.2 Обновить устаревающую документацию слоёв: docstring в
  `src/session/model/__init__.py` (строки 3–4, инвариант «Зависит только от
  `events/` и `src/harmony/`» перестанет быть точным — появятся рёбра
  `model.track → modify.chain`, новый листовой модуль `model/density.py` и
  `modify/stage_registry.py`) и описание слоёв `session/` в `AGENTS.md`
  (раздел «Архитектура и слои»: упомянуть поле `chain` в Track и новые
  модули). Критерий: docstring и AGENTS.md соответствуют фактическим
  импортам после реализации.

## 8. Финализация (исполнитель)

- [x] 8.1 Прогнать `uv run pytest` — все тесты зелёные, включая новые блоки
  1–6 (база 1945 passed не падает).
- [x] 8.2 Линтеры без роста базы: `uv run ruff check src tests`,
  `uv run black --check src tests`, `uv run mypy src` — сравнить с базой
  2026-11-19: ruff 50, black 11 файлов, mypy 20 ошибок.
- [x] 8.3 `openspec validate --change track-modify-chain` и
  `openspec status --change track-modify-chain` — артефакты валидны и done.
  Выполнено: 6 passed / 0 failed, 2 WARNING (некритично).
- [ ] 8.4 После реализации: `graphify update .` — граф не знает про
  `model/density.py`, `modify/stage_registry.py`, поле `chain` и домен
  `track chain` в REPL.

## Workflow follow-up

- Дельты затрагивают capabilities, чьи baseline-спеки описаны в
  `init-current-system` (ещё не синхронизирован): синхронизировать оба
  change'а вместе (openspec-sync-specs) либо архивировать в согласованной
  очерёдности.
- Дизайн цепочек для drum-дорожек — follow-up (модель хранит поле, движок
  игнорирует).
