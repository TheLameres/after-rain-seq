# План G2: скриптовый движок (Python DSL) — детальный

> Дата: 2026-11-17. Согласовано в сессии grilling (ROUND 1–5, вопросы Q1–Q23).
> **Ревизия 2026-11-19 после валидации:** исправлены конвенция degrees (BLOCK),
> пример `proposal_script.py` и критерий этапа 2, интеграция `main.py`,
> мелкие (minor) — обёртка клока, gate/density, сигнатуры-опечатки, статус задач.
> **Ревизия 2 (2026-11-19, сверка с кодом):** код опережал снимок ревизии 1 —
> `runner.py`, тесты `test_scripting_{validator,session,runner}.py` и этап 4 (REPL)
> уже реализованы; чекбоксы §5 пересверены с кодом; переоткрыты 2.2–2.4
> (остатки миграции degrees 1..7 → 0..13 и обёрток фасада); сниппеты §3.7/§3.10
> и формулировка 3.1 приведены к факту.
> **Ревизия 3 (2026-11-19, финальная сверка состояния):** 5.1 → [x]
> (config.py:76–85, 103, 203–206); 5.2 → [x] — факт валидатора устарел,
> прокидывание и `_run_scripts` уже в коде (main.py:61–66, 101–107, 110–116,
> 142–166); 5.3 → [x] (test_scripting_startup.py покрывает таблицу 5.3);
> сигнатуры сниппета §3.7 дописаны до `-> EngineResult` полностью.
> Пункт дорожной карты: **G2** в `plans/ROADMAP.md` (раздел добавить при старте; G1 занят cleanup — KISS/DRY).
> Нумерация сверена с `plans/ROADMAP.md` (2026-11-19): в серии G занята только G1
> (cleanup, `plans/plan_g1_cleanup_kiss_dry.md`) — «G2: скриптовый движок» конфликта
> не имеет; файл плана — `plans/scripting_api.md`.
> **Статус: реализация завершена 2026-11-19 (pytest 1945 passed, линтеры на базовой линии).**

---

## 0. Резюме

Python 3-скрипты, исполняемые движком приложения как **синхронный батч** типизированных
вызовов. Скрипт поднимает сессию: дорожки, гармония, роутинг, транспорт. Не
перформанс-язык: без музыкального времени, без ожиданий, без команд истории версий.

Модель скрипта (пример — `proposal_script.py` в корне):

```python
pad = TrackProposal(name="Track 1", profile_name="atmos",
                    voicing="1-3-5-7", degrees=[6, 5, 4])
session.add_track(pad)
session.start()
```

Зафиксированные решения:

| # | Решение | Раунд |
|---|---|---|
| — | Уровень: макро-раннер (без музыкального времени в v1) | Q1 |
| — | Субстрат: встроенный Python 3 + валидация | Q2 |
| — | Типизированные обёртки, **не** `run("строка")` | Q7 |
| — | Синхронный батч на потоке вызывающего | Q3/Q10 |
| — | Новый пакет `src/scripting/` | Q4 |
| — | Запуски: startup из config · `--script` CLI · `script run/check` из REPL | Q5/Q11 |
| — | Всё через `EngineControl` ABC; DTO не знают о session | Q14/Q15 |
| — | DTO в `src/core/` ⇒ семантика не в конструкторе DTO | Q21 |
| — | Валидация: `compile()` + AST-линт, отчёт до исполнения | Q16 |
| — | Ошибки: `ScriptError` → стоп; отказ через `fatal=False` | Q18 |
| — | `EngineControl.create_track(..., name=None)` — расширение движка | Q17 |
| — | Скооп v1 = построение сессии, **без** evolve/undo/recall/history | Q19/Q20 |
| — | Провал startup / `--script` = **аварийное завершение старта** | Q22/Q23 |
| — | Деструктивные в скриптах — авто-подтверждение | Q12 |
| — | Имена инжектируются в globals, импортов в скриптах нет | — |
| — | Ступени `degrees` — конвенция движка **0..13** (0-based, две октавы семиступенного лада): DTO/валидатор/фасад без конверсии; консистентно с `MelodicTrack._validate_degrees` (`MAX_DEGREE=14`), `degree_names.py` (`DEGREE_MIN=0/DEGREE_MAX=13`) и REPL `track degrees` (0..13). Файл `src/core/proposal.py` правится с 1..7 → 0..13 | из ревизии (BLOCK) |
| — | Обёртка клока в `ScriptSession` — имя **`request_clock_source`** (совпадает с ABC без переименования; queued-семантика в имени). Код (`set_clock_source`, script_session.py:129) и тест (`test_scripting_session.py:288`) приводятся к плану — план источник истины | из ревизии 2 |

---

## 1. Существующая база (факты, проверены 2026-11-17)

- **ABC** `src/repl/engine_control.py` — `EngineControl`, методы возвращают
  `EngineResult` (frozen, `ok(message, **data)` / `fail(message)`; `message` без
  префикса, `error: bool`). Релевантные для скоопа методы:
  - транспорт/клок: `start_transport`, `stop_transport`, `set_bpm`, `set_swing`,
    `request_clock_source`
  - порты: `rescan_ports`, `switch_port(label, match)`
  - гармония: `set_root(root: str)`, `set_scale(name: str)`
  - сессия: `list_tracks`, `create_track(profile, channel=None)` *(расширяем)*,
    `set_track_channel`, `remove_track`, `route_track`, `unroute_track`,
    `create_drum_track()` *(расширяем)*, `set_track_sources(name, *sources)`,
    `set_track_gate`, `set_track_density`
  - «не-абстрактные» с дефолт-фейлом: `set_track_degrees`, `set_track_voicing`,
    `set_track_octave`, `set_track_inversion`, `set_track_profile`
- **Конвенция степеней**: `MelodicTrack._validate_degrees` — `0 <= d < MAX_DEGREE`
  при `MAX_DEGREE = 14` (`src/session/model/melodic_track.py:28,167–169`), т.е.
  **0..13** (0-based, две октавы семиступенного лада); `src/harmony/degree_names.py:17–18`
  — `DEGREE_MIN=0, DEGREE_MAX=13`; REPL `track degrees` принимает «числа 0..13»
  (`src/repl/parser.py:130`). Скриптовый DSL использует ту же конвенцию — см. §0.
- **Реестры**:
  - `PROFILES: dict[str, MelodicProfile]` — `src/session/model/melodic_profile.py`
  - `Voicing.VOICINGS: dict[str, tuple[int, ...]]` (формат `"1-3-5"`, 10 ключей),
    `Voicing.HARMONIC_SCALES: frozenset[str]` — `src/harmony/voicings.py`
- **Session** `src/session/session.py`:
  `create_melodic_track(profile="pad", channel=None, port=None, **kwargs)` —
  имя генерирует `_next_name(profile)` (счётчик `Pad 1/2/…`), канал `None` →
  `_alloc_channel()` (9 зарезервирован), лимит `_check_limit()`,
  ошибки — `ValueError` с русским текстом.
- **REPL**: `parser.py` — таблица `CommandSpec` (домен/действие/usage/min-max/
  choices/destructive); `executor.py` — `CommandExecutor.execute(line) ->
  CommandResult`, диспетчер `_cmd_<name>`; `command.py` — `Command`/`CommandResult`
  (`output`/`code`/`exit`).
- **REPL-поток**: `Repl.start()` поднимает daemon-поток — `AppEngineControl`
  уже легально зовётся не из главного потока. Раннеру менять потоковую модель не надо.
- **`src/main.py`**: `_run_headless(config_path, simulate, repl)` — `App(...)` →
  `app.run(repl=...)` (блокируется до `stop()`). CLI-флаги в `argparse`.
- **Config** `src/config.py`: `AppConfig(BaseModel)` c секциями
  (`logging/sync/ports/cc_map/drum/mutation/ui/devices`). Секция `scripting` — новая.
- **DTO-слой проекта**: `src/core/` (сейчас `color.py`, `engine_result.py`,
  `__init__.py`; `proposal.py` уже создан в рамках подготовки G2 —
  структурно соответствует §3.1, но degrees-валидация 1..7 требует правки
  под 0..13, см. задачу 1.1).

---

## 2. Архитектура

```
скрипт .py ──────────────┐
                          │  exec( globals: session, TrackProposal, DrumProposal )
src/scripting/            │
  runner.py ──────────────┤  ScriptRunner (compile → validate → exec → report)
  validator.py ────────────┤  AST-линт против модели фасада и реестров
  script_session.py ──────┤  ScriptSession: обёртки над EngineControl ABC
  error.py ───────────────┘  ScriptError, ScriptDiagnostic
        │            │
        ▼            ▼
src/repl/engine_control.py (ABC)      src/core/proposal.py (frozen DTO)
        │                                   ▲
        ▼                                   │ импорт
AppEngineControl → App/Session         src/scripting/*, (позже repl/config)
```

Правила слоёв (из AGENTS.md, проверены для этого плана):

- scripting → repl (только ABC-модуль `engine_control`), core, harmony, session.model
  (реестры для валидатора) — **вниз**, циклов нет;
- scripting **не** импортирует `app/` — как и весь `repl/`;
- core не импортирует ничего из harmony/session ⇒ **семантическая валидация не может
  жить в DTO** (следствие решения Q21) — она в `validator.py` + рантайме фасада;
- REPL (executor) импортирует scripting — это вверх от repl? **Нет**: scripting —
  sibling, app-слой уже импортирует ABC из repl (`src/app/engine_control.py`
  импортирует `EngineControl` из `src/repl/engine_control.py`); `src.repl` →
  `src.scripting` допустим, т.к. scripting ниже repl по зависимости (scripting
  зависит только от ABC и core/harmony). Зафиксировать в docstring
  `src/scripting/__init__.py`.

---

## 3. Спецификации файлов

### 3.1 `src/core/proposal.py` — frozen-DTO (NEW; файл уже создан — правится в задаче 1.1)

```python
"""Скриптовые proposal-объекты: замысел дорожки как данные.

Живут в core, ниже harmony/session, поэтому проверяют только структуру;
семантику (профиль/voicing/лад) проверяет scripting.validator и фасад.
"""

@dataclass(frozen=True, slots=True)
class TrackProposal:
    """Замысел melodic-дорожки для скрипта."""

    profile_name: str            # не "" (существование — не здесь)
    name: str | None = None      # None → автоимя движка; иначе непустое
    voicing: str | None = None   # формат "1-3-5" (реестр — не здесь)
    degrees: tuple[int, ...] | None = None  # ступени 0..13 (конвенция движка)
    channel: int | None = None   # MIDI 0..15 или None (автоназначение)

@dataclass(frozen=True, slots=True)
class DrumProposal:
    """Замысел drum-дорожки для скрипта."""

    name: str | None = None
```

`__post_init__` (структурно, `ValueError`):

- `profile_name` — непустая `str`;
- `name is not None` ⇒ непустая `str`;
- `channel is not None` ⇒ `int 0..15`;
- `degrees is not None` ⇒ ints `0..13`, непустой кортеж (конвенция движка,
  см. §1 и решение в таблице §0 — «из ревизии»);
- `voicing` — `str` или `None`.

Списки в аргументах скрипта (`degrees=[6, 5, 4]`) → в `__post_init__` нормализовать
`tuple(degrees)` через `object.__setattr__` (frozen), принимать
`Sequence[int]` (`degrees: Sequence[int] | None`, поле хранится tuple — тип-хинт
в dataclass объявляем как `tuple[int, ...] | None`, а валидатор фасада принимает
sequence; проще: параметр `degrees: Sequence[int] | None` и
`__post_init__` приводит к tuple. Исполнить как `dataclass` с полем
`degrees: tuple[int, ...] | None` + конструктор-классметод не нужен: скрипт
пишет `degrees=[6,5,4]`, dataclass примет list как есть — `__post_init__` сконвертирует).

⚠️ Из ревизии (BLOCK): файл `src/core/proposal.py` уже существует с проверкой
degrees `1..7` — правка задачи 1.1 затрагивает существующий файл: конвенция
движка **0..13** (0-based), без конверсии 1-based → 0-based. Канонический пример
VII–VI–V в 1-based нотации переписывается как `degrees=[6, 5, 4]`
(0-based: 6=VII, 5=VI, 4=V); тоника — `degrees=[0]`. Документировать в docstring
поля: «0-based, две октавы семиступенного лада, ср. `degree_names.py`».

### 3.2 EDIT `src/repl/engine_control.py` — расширить ABC

```python
@abstractmethod
def create_track(self, profile: str, channel: int | None = None,
                 name: str | None = None) -> EngineResult:
    """Создать melodic-дорожку. ``name=None`` — автоимя."""

@abstractmethod
def create_drum_track(self, name: str | None = None) -> EngineResult:
    """Создать drum-дорожку. ``name=None`` — автоимя."""
```

Обновить docstring-примечание про направление зависимостей. Все прочие методы ABC
скоопа уже существуют — **новых методов в ABC не добавляем**, кроме `name=`.

### 3.3 EDIT `src/session/session.py` — имя дорожки

`create_melodic_track(..., name: str | None = None)` и
`create_drum_track(..., name: str | None = None)`:

```python
if name is None:
    name = self._next_name(profile)
else:
    name = str(name).strip()
    if not name:
        raise ValueError("Имя дорожки не может быть пустым")
    if name in self._tracks:
        raise ValueError(f"Дорожка уже существует: {name!r}")
```

Автосчётчик при явном имени **не** инкрементируется.

### 3.4 EDIT `src/app/engine_control.py` — `AppEngineControl`

- `create_track(profile, channel=None, name=None)` — прокинуть `name`;
  при `name=None` — как сейчас (автоимя, `_route_new_track` в первый настроенный
  выход — сохранить поведение);
- `create_drum_track(name=None)` — прокинуть;
- сообщения фидбека — существующего формата (`created track "..."`).

### 3.5 NEW `src/scripting/error.py`

```python
@dataclass(frozen=True)
class ScriptDiagnostic:
    """Одно замечание валидации: файл, строка, колонка, текст."""
    filename: str
    line: int          # 1-based
    col: int            # 0-based
    message: str

class ScriptError(Exception):
    """Ошибка исполнения вызова фасада (движок вернул error)."""
    def __init__(self, message: str, line: int | None = None): ...
    # str(exc) → "line N: <message>" либо "<message>"
```

### 3.6 NEW `src/scripting/validator.py`

Модель для линта — собственная таблица `(_NAME, spec)` фасада (см. 3.7):
имя метода → `(positional: tuple[str, ...], keywords: frozenset[str],
defaults: dict[str, bool] /*optional*/)`. Строится из `inspect.signature(ScriptSession)`
на публичных методах — **таблицу не дублируем вручную**, выводим рефлексией.

```python
class ScriptValidator:
    """Двухступенчатая проверка скрипта: compile → AST-линт."""

    def __init__(self) -> None: ...          # реестры: PROFILES, VOICINGS, HARMONIC_SCALES

    def validate_source(self, source: str, filename: str) -> list[ScriptDiagnostic]:
        """Ступень 1: compile() → SyntaxError как diagnostic.
        Ступень 2: ast.walk:
          - Call(Attribute(Name('session'), m)) → m ∈ facade; kwarg ∈ keywords;
            позиционных аргументов ≤ positional; лишних kwarg нет;
            результат не используется как значение (предупреждение? — нет, v1 молча);
          - Call(Name('TrackProposal'|'DrumProposal')) → поля DTO + семантика
            литералов: profile_name ∈ PROFILES, voicing ∈ VOICINGS,
            degrees ⊆ 0..13 (конвенция движка, «из ревизии»), channel 0..15,
            name непустое;
          - не-литеральные аргументы пропускаются (runtime проверит фасад);
          - имена session/TrackProposal/DrumProposal, переопределённые в скрипте
            присваиванием, — diagnostic «переопределение инжектированного имени».
        """
```

Отчёт сортируется по `(line, col)`. Пустой список — валидно.

### 3.7 NEW `src/scripting/script_session.py`

```python
class ScriptSession:
    """Объект ``session``, видимый скрипту. Все вызовы — через EngineControl ABC."""

    def __init__(self, control: EngineControl) -> None: ...

    # — сессия (раскладка proposal → примитивы ABC) —
    def add_track(self, proposal: TrackProposal, *, fatal: bool = True) -> EngineResult:
        """create_track(profile, channel, name) → voicing → degrees (что задано).
        Шаг цепочки неудачен ⇒ ScriptError (если fatal) / вернуть EngineResult."""

    def add_drum(self, proposal: DrumProposal, *, fatal: bool = True) -> EngineResult: ...

    # — 1:1 обёртки (private helper _call(self, method, *a, **kw)) —
    def start(self, *, fatal: bool = True) -> EngineResult
    def stop(self, *, fatal: bool = True) -> EngineResult          # деструктив: авто-confirm
    def set_bpm(self, bpm: float, *, fatal: bool = True) -> EngineResult
    def set_swing(self, amount: float, *, fatal: bool = True) -> EngineResult
    def request_clock_source(self, source: str, *, fatal: bool = True) -> EngineResult  # internal|midi|link; queued-семантика движка
    def set_root(self, root: str, *, fatal: bool = True) -> EngineResult
    def set_scale(self, name: str, *, fatal: bool = True) -> EngineResult
    def remove_track(self, name: str, *, fatal: bool = True) -> EngineResult  # деструктив: авто-confirm
    def set_track_channel(self, name: str, channel: int, *, fatal: bool = True) -> EngineResult
    def route_track(self, name: str, label: str, *, fatal: bool = True) -> EngineResult
    def unroute_track(self, name: str, *, fatal: bool = True) -> EngineResult
    def set_track_sources(self, name: str, *sources: str, fatal: bool = True) -> EngineResult
    def set_track_gate(self, name: str, gate: float, *, fatal: bool = True) -> EngineResult
    def set_track_density(self, name: str, density: float, *, fatal: bool = True) -> EngineResult
    def set_track_degrees(self, name: str, degrees: Sequence[int], *, fatal: bool = True) -> EngineResult
    def set_track_voicing(self, name: str, voicing: str, *, fatal: bool = True) -> EngineResult
    def set_track_octave(self, name: str, octave: int, *, fatal: bool = True) -> EngineResult
    def set_track_inversion(self, name: str, k: int, *, fatal: bool = True) -> EngineResult
    def set_track_profile(self, name: str, profile_name: str, *, fatal: bool = True) -> EngineResult
    def rescan_ports(self, *, fatal: bool = True) -> EngineResult
    def switch_port(self, label: str, match: str, *, fatal: bool = True) -> EngineResult
```

Правила:

- `fatal=True` (по умолчанию): `EngineResult.error` ⇒ `raise ScriptError(message)`.
- `fatal=False`: вернуть `EngineResult` как есть, скрипт сам решает.
- «Деструктив» (`stop`, `remove_track`) — подтверждение **не спрашивается**:
  эквивалент `--yes`; в лог пишется `script: auto-confirmed destructive <op>`
  (`log = logging.getLogger(__name__)` в runner/session).
- `add_track` шаги (proposal с заданными voicing/degrees):
  1. `create_track(profile_name, channel, name)` — ошибка ⇒ стоп;
  2. `set_track_voicing(name, voicing)` — если `voicing is not None`;
  3. `set_track_degrees(name, degrees)` — если задано.
  Имя дорожки для шагов 2–3 — `result.data["track"]` (фасад уже кладёт имя)
  либо `proposal.name` — взять из `data`, надёжнее.
- методы **не** печатают ничего; вывод — забота раннера/REPL.
- `request_clock_source` — обёртка 1:1 над `EngineControl.request_clock_source`
  (ABC, `src/repl/engine_control.py:59`): движок применяет переключение
  **на ближайшей доле** (queued, AppEngineControl:158–176), обёртка не ждёт
  фактического переключения — имя метода совпадает с ABC без переименования.
- `set_track_degrees` / `TrackProposal.degrees` — конвенция движка **0..13**
  (0-based), без конверсии («из ревизии»); обёртка 1:1 передаёт аргумент как есть.
- docstrings на русском (бизнес-логика), Google-style, полная типизация.

`@overload`/перегрузки не нужны: возвращаемый тип единый — **`EngineResult`**;
`fatal=True` при ошибке бросает `ScriptError`, `fatal=False` возвращает
`EngineResult` как есть.

⚠️ Из ревизии 2/3: сниппет выше приведён к единому `-> EngineResult` (раньше
`EngineResult | None` и сокращённые `-> ...` — внутреннее противоречие с этим
правилом); код (`script_session.py:48` и далее) уже соответствует.

### 3.8 NEW `src/scripting/runner.py`

```python
@dataclass(frozen=True)
class ScriptRunReport:
    """Итог исполнения скрипта."""
    filename: str
    diagnostics: tuple[ScriptDiagnostic, ...]   # preflight (для check)
    lines_executed: int                          # сколько вызовов фасада прошло
    output_lines: tuple[str, ...]                # фидбек движка по порядку
    error: str | None                            # текст первой ошибки или None

class ScriptRunner:
    """Исполнение скрипта: compile → validate → exec (синхронно)."""

    def __init__(self, control: EngineControl) -> None: ...

    def check_file(self, path: Path) -> list[ScriptDiagnostic]:
        """Только валидация (script check)."""

    def run_file(self, path: Path) -> ScriptRunReport:
        """validate → при ошибках: отчёт без исполнения;
        exec в globals {__name__: "afterrain.script", __file__, session,
                        TrackProposal, DrumProposal};
        ScriptError поймать → отчёт (lines_executed, output_lines, error);
        прочие исключения скрипта → отчёт с traceback-текстом в error;
        каждый успешный вызов: message движка → output_lines + log.info."""
```

- Синхронно, в потоке вызывающего (REPL-поток / поток main при загрузке).
- ⚠️ Из ревизии 2: форматтер отчёта — **публичная module-level функция
  `format_report(report) -> str` в `runner.py`** (не приватный `_format` и
  не `render.py`; факт: `runner.py:93`, экспорт в `__init__.py:23,31`).
  Формат: заголовок `script <file>:`, при diagnostics —
  `validation: N diagnostic(s)` + строки `file:line: message`, иначе
  `NNN| <message движка>` и завершение `ok: N call(s)` / `error: ...`.
- `__builtins__` — стандартные (песочницы нет, решение Q8).
- Если валидация нашла diagnostics — **исполнение не начинается**, отчёт целиком
  из diagnostics (это и есть «валидация скрипта» до побочных эффектов).
- Файл не найден / не читается ⇒ `ScriptRunReport.error = "..."` без diagnostics
  (или диагностик с message; единообразно — diagnostic line=0).

### 3.9 NEW `src/scripting/__init__.py`

Экспорт: `ScriptRunner`, `ScriptSession`, `TrackProposal`-реэкспорт не нужен
(скрипты получают DTO из инжекции). Docstring про слой и направление
зависимостей (см. §2).

### 3.10 EDIT REPL: `parser.py`, `executor.py`, `completer.py`

parser — две спецификации:

```python
CommandSpec(name="script run", domain="script", action="run",
            usage="script run <file>", help="Исполнить скрипт (синхронный батч)",
            min_args=1, max_args=1),
CommandSpec(name="script check", domain="script", action="check",
            usage="script check <file>", help="Валидация скрипта без исполнения",
            min_args=1, max_args=1),
```

executor (`CommandExecutor` имеет `self._control`) — сниппет приведён к факту
(ревизия 2; `src/repl/executor.py:337–354`):

```python
def _cmd_script_run(self, command: Command) -> CommandResult:
    report = ScriptRunner(self._control).run_file(Path(command.args[0]))
    code = 1 if report.error is not None or report.diagnostics else 0
    return CommandResult(output=format_report(report), code=code)

def _cmd_script_check(self, command: Command) -> CommandResult:
    diagnostics = ScriptRunner(self._control).check_file(Path(command.args[0]))
    if not diagnostics:
        return CommandResult(output=f"script {command.args[0]}: ok")
    lines = [f"script {command.args[0]}: {len(diagnostics)} diagnostic(s)"]
    lines.extend(d.format() for d in diagnostics)
    return CommandResult(output="\n".join(lines), code=1)
```

(`format_report` — публичная функция раннера, §3.8; completer: dynamic_provider
"file" не нужен — у repl есть path-completion?)

⚠️ Факт: completer — `prompt_toolkit` + `dynamic_providers` из `main._build_repl`;
пути в v1 не дополняются автоматически, но `script` должен попасть в список
команд `help`-группы (completer читает таблицу спек — проверю при исполнении).
Формат отчёта — `status`-стиль: заголовок, строки `NNN| <message движка>`,
ошибки с `file:line: message`.

REPL после провала `script run` живёт (это не загрузочная точка) — уже гарантировано
паттерном `execute()` (ловит исключения в `code=1`).

### 3.11 EDIT `src/config.py`

```python
class ScriptingConfig(BaseModel):
    """Скриптовый движок: стартовый скрипт (пусто = выключено)."""
    startup: str = ""

class AppConfig(BaseModel):
    ...
    scripting: ScriptingConfig = Field(default_factory=ScriptingConfig)
```

Default YAML-снипет в `DEFAULT_CONFIG_YAML` (`src/config.py:137`, по образцу секций):

```yaml
scripting:
  # Стартовый скрипт: исполняется после сборки App, до main loop.
  # Провал (валидация или исполнение) = приложение не стартует.
  startup: ""
```

### 3.12 EDIT `src/main.py`

```python
parser.add_argument("--script", default=None, metavar="FILE",
                    help="Run a Python script (after startup-script) before the main loop")
```

В `_run_headless` (после `App(...)`, до `app.run`) — с прокидыванием аргументов
из `main()` (`cfg` загружается в `main()` на `src/main.py:62`, `args.script`
парсится там же — в `_run_headless` они не видны и передаются явно):

```python
# main():
_run_headless(args.config, args.simulate, repl=args.repl,
              startup=cfg.scripting.startup, script=args.script)

# _run_headless(config_path, simulate, repl=False, startup="", script=None):
def _run_headless(config_path: str, simulate: bool, repl: bool = False,
                  startup: str = "", script: str | None = None) -> None:
    ...
    app = App(config_path=config_path, simulate=simulate)
    ...
    from src.app.engine_control import AppEngineControl
    control = AppEngineControl(app)   # лог-буфер не нужен: none
    paths = [p for p in (startup, script) if p]
    _run_scripts(app, control, *paths)
    app.run(repl=...)
    # провал в _run_scripts → log.error + app.stop() (очистка) + sys.exit(1)
```

Новая функция `_run_scripts(app, control, *paths) -> None` (без raise: печатает
отчёт, при error — cleanup + `sys.exit(1)`). Порядок: **startup из config →
`--script` из CLI** (решение Q11; порядок сохраняется порядком фильтрации
`paths`). Прочий порядок не менять.

Для `-–script` в `--simulate`: работает без изменений (App в simulate — тот же
интерфейс), добавить smoke-тест.

`--script` требует наличия файла — ошибка CLI: отчёт раннера «file not found»
и `sys.exit(1)` (единый механизм, отдельной ветки argparse не нужно).

---

## 4. Что НЕ входит (скоуп-стражи)

- `run("track add pad 3")` — командные строки как API (отвергнуто в Q7);
- evolve/undo/recall/history в скриптах (Q20: история — REPL-зона);
- музыкальное время / ожидания / параллельность (Q1: макро-раннер);
- песочница/allowlist AST (Q8: только compile+линт);
- Push 2 UI для скриптов (нет);
- транзакционность/откат скрипта (нет: `track delete` в VersionHistory не пишется);
- ренейм живой дорожки (`TrackProposal.name` — только при создании; Q17 —
  «расширение create_track», не rename);
- one-shot-режим `--script` (после скриптов приложение продолжает работать).

---

## 5. Этапы и задачи

### Этап 1 — DTO и имя дорожки (core + движок)

- [x] 1.1 ⚠️ правка существующего файла — `src/core/proposal.py`:
      `TrackProposal`, `DrumProposal` (frozen, slots) — **из ревизии (BLOCK):
      degrees-валидация 1..7 → 0..13** (конвенция движка, docstring поля —
      «0-based, две октавы, ср. degree_names.py»), нормализация `degrees` → tuple.
      *Выполнено (2026-11-19): `proposal.py:92` — `0 <= degree <= 13`, сообщение
      «ступени — целые 0..13», docstring поля обновлён.*
- [x] 1.2 `src/session/session.py`: `name: str | None = None` в
      `create_melodic_track` / `create_drum_track`; коллизия/пустое имя — `ValueError`;
      счётчик не трогается при явном имени.
      *Выполнено (подтверждено кодом: `session.py:52,138`).*
- [x] 1.3 ABC `create_track/create_drum_track` + `AppEngineControl` — прокинуть
      `name`; фидбек-сообщения не менять по формату.
      *Выполнено (подтверждено кодом: ABC `engine_control.py:105–107,139`;
      `app/engine_control.py:282–283,349–359`).*
- [x] 1.4 Тесты (`tests/test_core_proposal.py` — файл уже создан; **из ревизии:
      обновить degrees-кейсы под 0..13**; дополнить существующие
      session/engine_control тесты):
      - DTO: валидный кейс из `proposal_script.py` (после правки degrees →
        `[6, 5, 4]`); пустое имя профиля; `channel=16`/`-1`; `degrees=[14]`
        (вне 0..13), `degrees=[-1]`, пустые degrees, list→tuple;
        `degrees=[0]` (тоника — валидно, «из ревизии»), `degrees=None`,
        `voicing=None` — ок; мутабельность → FrozenInstanceError.
      - Session: явное имя создаётся; дубликат имени → ValueError; автосчётчик
        не сдвинулся; `create_drum_track(name="Kick")`.
      - EngineControl/ABC: мок/стаб принимает `name`; AppEngineControl
        (существующие e2e-фикстуры) — сообщение содержит имя.
      *DTO-кейсы переписаны (2026-11-19): `[14]`/`[-1]`/`[3, 20]` — reject,
      границы `(0,)`/`(13,)` — ok, canonical `[6, 5, 4]`. Session/ABC-кейсы
      подтверждены кодом ранее (тесты `test_scripting_session.py` — мок
      принимает `name`).*

**Критерий:** `uv run pytest` зелёный; линтеры без новых замечаний.

### Этап 2 — валидатор (scripting появляется)

- [x] 2.1 `src/scripting/__init__.py`, `error.py` (`ScriptDiagnostic`, `ScriptError`).
      *Выполнено (подтверждено кодом: оба файла существуют; `format_report`
      экспортирован в `__init__` вместе с раннером).*
- [x] 2.2 ⚠️ переоткрыто (ревизия 2): `script_session.py` выполнен по до-ревизионной
      спеке — остатки до §3.7:
      - **(а) добавить обёртки `set_track_gate(name, gate)` / `set_track_density(name, density)`** —
        ABC их декларирует (`engine_control.py:196,200`; реализация
        `app/engine_control.py:441,459`), рефлексивный валидатор их не знает ⇒
        скрипт сейчас **не может** задать gate/density;
      - **(б) переименовать обёртку клока `set_clock_source` → `request_clock_source`**
        (script_session.py:129; решение в таблице §0 «из ревизии 2») вместе с
        тестом `test_scripting_session.py:288` (`session.set_clock_source("midi")`).
      Остальное по §3.7 (`add_track`/`add_drum`, `_call`, авто-confirm + лог) —
      подтверждено кодом.
      *Выполнено (2026-11-19): обёртки `set_track_gate`/`set_track_density` добавлены
      после `set_track_profile` (1:1, `fatal`), валидатор подхватит их рефлексией;
      обёртка клока переименована в `request_clock_source` (docstring — queued
      семантика); тест `test_scripting_session.py` обновлён (добавлен вызов
      `request_clock_source`, тест `test_track_operations` дополнен gate/density —
      мок-стаб уже реализует оба).*
- [x] 2.3 ⚠️ выполнено по до-ревизионной спеке — **требует доработки под 0..13**
      (ревизия 2): `validator.py` реализует §3.6 (compile + AST-линт, рефлексия
      `ScriptSession`, `dataclasses.fields`), но `validator.py:347,353` всё ещё
      `not 1 <= degree <= 7` / «degrees out of 1..7» — переписать на 0..13
      (тоника `[0]` валидна, вне — `[14]`).
      *Выполнено (2026-11-19): `validator.py` — `0 <= degree <= 13`, сообщение
      «degrees out of 0..13: ...».*
- [x] 2.4 ⚠️ выполнено по до-ревизионной спеке — **требует доработки под 0..13**
      (ревизия 2): `tests/test_scripting_validator.py:103–105`
      (`test_degrees_out_of_range`) фиксирует `degrees=[0]` →
      «degrees out of 1..7: 0» — переписать: `[0]` → ок (тоника),
      `[14]` → diagnostic «degrees out of 0..13»; fixture-скрипт в тесте
      (`:86`, `degrees=[7, 6, 5]`) → `[6, 5, 4]`.
      *Выполнено (2026-11-19): `[0]` — ок, `[14]`/`[-1]` — diagnostic
      «degrees out of 0..13», fixture `degrees=[6, 5, 4]`.*

| Сценарий | Ожидание |
|---|---|
| `session.add_track(pad)` | нет diagnostics |
| `session.unknown_op()` | diagnostic «unknown session method» с line |
| `session.set_bpm()` (мало позиционных) | diagnostic про аргументы |
| `session.set_bpm(bpm=120)` | ок (kwarg входит в keywords) |
| `TrackProposal(profile_name="nope")` | diagnostic «unknown profile», реестр PROFILES |
| `TrackProposal(voicing="1-2-3-5-7")` | diagnostic (в VOICINGS нет) — **инлайн-скрипт** (исторический кейс из proposal_script.py до правки 6.5) |
| `TrackProposal(degrees=[14])` | diagnostic «degrees out of 0..13» (конвенция движка, «из ревизии») |
| `TrackProposal(degrees=[0])` | нет diagnostics — тоника валидна (0-based, «из ревизии») |
| `TrackProposal(degrees=[x])` (переменная) | нет diagnostics; runtime проверит |
| `session = 5` (переопределение) | diagnostic «injected name reassigned» |
| SyntaxError | diagnostic line/col из compile |
| Динамика: `set_bpm(120)` без кавычек, любое выражение | пропускается |

**Критерий:** валидатор ловит инлайн-скрипт (в т.ч. voicing вне реестра и
degrees вне 0..13) **до** исполнения, с точным file:line — на текущем
`proposal_script.py` это не проверяется: файл уже переписан под DSL
(`TrackProposal` + `voicing="1-3-5-7"` из реестра), кривой voicing остался
только в историческом кейсе теста.

### Этап 3 — раннер и отчёты

- [x] 3.1 `runner.py`: `ScriptRunner.check_file`, `run_file`,
      `ScriptRunReport`; инжекция globals; форматтер отчёта.
      *Выполнено (подтверждено кодом: `runner.py` целиком реализует §3.8, включая
      `_TracedSession`-обёртку и `_script_line`; форматтер — **публичная
      module-level функция `format_report(report) -> str` в `runner.py:93`**,
      экспорт в `__init__.py:23,31` — вариант «render.py» и «приватный `_format`»
      не реализовывались; формулировка до-ревизионного плана заменена на факт,
      см. §3.8).*
- [x] 3.2 Тесты `tests/test_scripting_runner.py` на **мок-EngineControl**
      (фасад в тестах — существующий паттерн `tests/`):
      *Выполнено (подтверждено кодом: файл существует, покрывает таблицу ниже).*

| Сценарий | Ожидание |
|---|---|
| валидный скрипт: add_track + start | output_lines по порядку; error=None; старт вызван |
| провал 2-й из 4 команд (fatal по умолчанию) | ScriptError пойман; error=«file:line: <текст>»; 3-я команда НЕ исполнена (мок не звался) |
| `fatal=False` | возвращен EngineResult; 3-я команда исполнена |
| diagnostics от валидатора | исполнение не начиналось; отчёт только diagnostics |
| runtime-провал (переменная-профиль) | error из EngineResult, линия — из текущего вызова |
| исключение в теле скрипта (ZeroDivisionError) | error=«<class>: <text>», приложение раннера не падает |
| `stop()` в скрипте | вызвано без confirm (мок не спрашивает), в логе auto-confirmed |
| файл не найден | error=«file not found», exit-кода нет в отчёте |

**Критерий:** e2e-скрипт поднимает сессию на моке за один `run_file`.

### Этап 4 — REPL-домен `script`

- [x] 4.1 `parser.py`: 2 CommandSpec (§3.10); `executor.py`: `_cmd_script_run`,
      `_cmd_script_check` (+ в `_dispatch` — ничего менять, имя
      `script_run`/`script_check` → методы по конвенции `_cmd_<name>`).
      *Выполнено (подтверждено кодом: `parser.py:328,337` — обе спеки 1:1 с §3.10;
      `executor.py:337–354` — оба метода, check возвращает `script <file>: ok`
      при чистой валидации; сниппет §3.10 приведён к факту, ревизия 2).*
- [x] 4.2 `completer.py`: команды `script run/check` — из таблицы спек автоматически.
      *Выполнено (подтверждено кодом: в `completer.py` упоминаний `script` нет —
      ожидаемо для автоматического механизма из таблицы спек; `help` выводит
      usage обеих команд — `test_repl_parser.py:224–227`).*
- [x] 4.3 Тесты `tests/test_repl_parser.py`, `tests/test_repl_executor.py` —
      добавлены.
      *Выполнено (подтверждено кодом: `test_repl_parser.py:189–227` —
      parse/usage/difflib/help; `test_repl_executor.py:502–557` — check valid/invalid,
      run valid/failed, «REPL живёт» (`:530–539`), без аргумента, missing file,
      canonical fixture `proposal_script.py` (`:552–557`)).*

| Сценарий | Ожидание |
|---|---|
| `script check valid.arain.py` | code=0, пустой отчёт-«OK» |
| `script check bad.arain.py` | code=1, строки `file:line: message` |
| `script run <файл>` на моке | code=0, вывод фидбека движка |
| `script run` провалился | code=1, REPL живёт (следующая execute — работает) |
| `script run` без аргумента | usage-строка, code=1 |
| `script` | список похожих (difflib) — из parser, бесплатно |

**Критерий:** `help` показывает обе команды; парсер-таблица синхронна с executor.

### Этап 5 — точки запуска (config + CLI)

- [x] 5.1 `src/config.py`: `ScriptingConfig`, поле `scripting` в `AppConfig`;
      DEFAULT_CONFIG_YAML-сниппет §3.11.
      *Выполнено (подтверждено кодом: `ScriptingConfig` с полем `startup` и
      docstring про fail-fast Q22 — `config.py:76–85`; поле `scripting` в
      `AppConfig` — `config.py:103`; секция `scripting` в DEFAULT_CONFIG_YAML —
      `config.py:203–206`; 1:1 с §3.11).*
- [x] 5.2 `src/main.py`: флаг `--script=FILE`; `main()` прокидывает
      `startup=cfg.scripting.startup, script=args.script` в `_run_headless`
      (см. §3.12); `_run_scripts(app, control, *paths)` после `App(...)`,
      до `app.run`; порядок startup→CLI; **провал → отчёт в лог/консоль + `app.stop()`
      + `sys.exit(1)`** (решения Q22/Q23).
      *Выполнено (подтверждено кодом: флаг `--script` — `main.py:61–66`;
      прокидывание `startup=..., script=...` — `main.py:101–107`; сигнатура
      `_run_headless(..., startup="", script=None)` — `main.py:110–116`;
      `_run_scripts(app, control, *paths)` с отчётом + `app.stop()` + `sys.exit(1)`
      — `main.py:142–166`).*
      ⚠️ Факт финальной валидации («флаг объявлен, но не используется;
      прокидывания нет») устарел: код выполнил прокидывание после валидации.
      Реализатору дублировать нечего — эта задача закрыта.
- [x] 5.3 Тесты `tests/test_scripting_startup.py` (+ CLI-тесты, если есть паттерн):
      *Выполнено (подтверждено кодом: файл существует, покрывает все 7 строк
      таблицы ниже — empty startup, валидный startup, невалидный voicing → exit,
      провал на 3-й строке без rollback, порядок startup→CLI, missing file,
      `--simulate` e2e-сессия на моках — плюс canonical fixture
      `proposal_script.py` через `_run_scripts`).*

| Сценарий | Ожидание |
|---|---|
| `scripting.startup=""` | ничего не исполняется |
| startup валидный | исполнен до main loop; приложение стартует |
| startup невалидный (voicing) | приложение **не** стартует: exit до `app.run`; лог ERROR |
| startup исполняется, провалился на 3-й строке | выход; 1–2 применённые команды не откатываются (осознанно) |
| `--script` + startup оба | порядок: startup, потом CLI |
| `--script` без файла | exit 1, сообщение |
| `--script` + `--simulate` | работает (e2e-сессия на моках) |

**Критерий:** RPi-сценарий «устройство всегда включается» — **осознанно
нарушен** (решение Q22): кривой startup теперь не стартует. Зафиксировать в README.

### Этап 6 — polish

- [x] 6.1 `README.md`: раздел «Скрипты» — пример, `script check`, startup,
      `--script`, семантика провалов (fail-fast), `fatal=False`.
      *Выполнено (2026-11-19): раздел «Скрипты» добавлен (после REPL): пример,
      `script check/run`, формат отчёта, точки запуска (startup из config +
      `--script`), fail-fast семантика (exit 1, без отката), `fatal=False`;
      `--script FILE` добавлен в список флагов, `script run|check` — в список
      команд REPL.*
- [x] 6.2 `plans/ROADMAP.md`: план G2 — статус, ссылка на этот файл.
      *Выполнено (2026-11-19): строка в сводке статусов, раздел «План G2»
      (цель, что сделано, статус) между Планом G и «Зависимости между планами»,
      ветка G2 в диаграмме зависимостей.*
- [x] 6.3 Линтеры: `uv run pytest` (базa 1830 + новые), `uv run ruff check src tests`,
      `uv run black --check src tests`, `uv run mypy src` — **без новых замечаний**
      (пре-существующие перечислены в AGENTS.md; новые файлы будут чистыми).
      *Выполнено 2026-11-19: ruff 50 (базовая линия), mypy 20 (базовая линия),
      black — G2-файлы отформатированы; pytest 1945 passed (было 1830, +115);
      graphify update — граф пересобран.*
- [x] 6.4 `graphify update .` — обновить граф после всех правок.
      *Выполнено 2026-11-19: граф пересобран.*
- [x] 6.5 `proposal_script.py` в корне: файл уже переписан под DSL
      (`TrackProposal` + `session.add_track`, `voicing="1-3-5-7"` — из реестра);
      остаток — **согласовать с конвенцией degrees 0..13 «из ревизии»**:
      нисходящая VII–VI–V в 1-based (`[7, 6, 5]`) → `[6, 5, 4]` в 0-based,
      и использовать как canonical-пример в README/тестах.
      *Выполнено (2026-11-19): `degrees=[6, 5, 4]`; canonical-пример гоняется в
      `test_scripting_validator.py` (TestCanonicalScript),
      `test_scripting_runner.py`, `test_repl_executor.py` и
      `test_scripting_startup.py` — все читают файл с диска, перегенерации не
      требуют.*
- [x] 6.6 `AGENTS.md`: вписать новый пакет `src/scripting/` в ASCII-диаграмму
      слоёв (раздел «Архитектура и слои») и уточнить направление зависимостей
      scripting → repl.ABC/core/harmony/session.model — согласно §2 этого плана.
      *Выполнено (2026-11-19): блок `src/scripting/` вставлен в диаграмму между
      `src/session/` и `src/harmony/` (слои: scripting ниже repl по зависимости,
      импортирует repl.ABC/core/harmony/session.model); счётчик тестов в шапке
      не менялся (pytest не прогонялся).*

---

## 6. Тестовая стратегия

- **Unit**: DTO (pure), валидатор (source → diagnostics, без файлов),
  ScriptSession (мок-ABC, `unittest.mock`/собственный стаб по паттернам тестов
  repl), форматтер отчёта.
- **Integration**: ScriptRunner + ScriptSession + мок-ABC — «скрипт поднимает
  сессию» e2e на стабах; REPL-парсер+executor с мок-раннером.
- **E2E (без железа)**: `--simulate` + startup-скрипт → App стартует /
  проваливается (существующие e2e-паттерны `spikes/spike_ui_simulate.py`,
  `tests/`).
- **Canonical-скрипт**: `proposal_script.py` — fixture для валидатора/раннера.

## 7. Риски и следствия решений

| Риск/следствие | Митигация |
|---|---|
| Динамика (переменные в аргументах) не проверяется статически | рантайм-проверка фасадом (движок отвечает текстом ошибки);`fatal=False` для управляемого продолжения |
| Fail-fast startup: кривой скрипт = RPi не стартует | решение Q22 осознанное; выводить ошибку на дисплей Push 2 при загрузке — отдельная задача (не в G2) |
| `add_track` — цепочка вызовов без транзакции | не откатываем (VersionHistory не про удаление); сообщить в README |
| Расширение сигнатуры `create_track/create_drum_track` (ABC-break) | все реализующие классы — в дереве (ABC/AppEngineControl + стабы тестов); обновить одним этапом (1.3) |
| REPL-блокировка на время `script run` | решение Q10 осознанное (синхронный батч); долгие скрипты → будущее: поток-раннер + `script stop` (вне G2) |
| Скоуп методов фасада может расползтись | §4 — список стражей; новые методы фасада = отдельная задача |
| `1-2-3-5-7` отсутствует в VOICINGS | не баг: инлайн-тест-кейс валидатора (2.4); proposal_script.py переписан на `1-3-5-7` + `degrees=[6, 5, 4]` (0..13, VII–VI–V — 6.5 выполнено) |
| Конвенция degrees (1..7 vs 0..13) | принято 0..13 (0-based, конвенция движка — «из ревизии»); без конверсии в DTO/валидаторе/фасаде; примеры и тесты пересчитаны (тоника `[0]`, VII–VI–V → `[6, 5, 4]`) |

## 8. Definition of Done

1. `proposal_script.py` (degrees согласованы с конвенцией 0..13 — `[6, 5, 4]`)
   проходит `script check` без замечаний.
2. E2e: startup-скрипт с полной сессией (2 melodic + 1 drum + гармония + роутинг)
   исполняется на моках в тестах; с `--simulate` — в spike.
3. Провал startup/`--script`: процесс завершается до входа в main loop
   (exit(1) с отчётом); созданные дорожки не откатываются (осознанно —
   транзакционность вне скоопа, §4).
4. `uv run pytest` — зелёный; ruff/black/mypy — без новых замечаний.
5. README + ROADMAP обновлены; `graphify update .` выполнен.