# План F1: REPL/TUI для мониторинга и контроля

> Статус: план утверждён, готов к реализации
> Дата плана: 2026-11-02
> Зависимости: A2, B1, B2, B3, B4, C1, C3, C4, C5 — все завершены

---

## Принятые решения (из обсуждения)

| Вопрос | Решение |
|--------|---------|
| Назначение | Мониторинг + лёгкий контроль: живой дашборд состояния + команды управления |
| Среда запуска | И Mac (dev, IAC Driver), и RPi по SSH |
| Технология | Простой строчный REPL на **prompt_toolkit** (автодополнение, история, bottom_toolbar). Не полноэкранный TUI |
| Архитектура | REPL-поток **внутри процесса App**, доступ через интерфейс `EngineControl` |
| Домены | Транспорт/клок, порты/маршрутизация, дорожки/сессия, гармония/мутация |
| Мониторинг | Живой статус-бар (prompt_toolkit `bottom_toolbar`), обновление ~2 раза/сек |
| MIDI на Mac | IAC + реальные порты; REPL ничего не знает про железо |
| Персистентность | Изменения только в рантайме. В config.yaml ничего не пишем. История команд — отдельный файл |
| Запуск | Явный флаг `--repl`. Без флага — поведение не меняется (важно для systemd) |
| EOF stdin (Ctrl+D, обрыв SSH) | Режим по флагу: при `--repl` EOF = `app.stop()` (REPL = жизнь процесса) |
| Опасные команды | Подтверждение `y/N` по умолчанию; `--yes`/`-f` для подтверждённого вызова |
| Тесты | Минимум: дымовые — parser, executor с моком, smoke потока REPL |
| Скрипты из файла | Не сейчас (возможное расширение) |
| Логи | Команда `logs [N]` — кольцевой буфер в памяти через logging.Handler |
| Частота бара | ~2 Гц |
| История | Файл рядом с config.yaml |

---

## Цель

Дать возможность наблюдать за состоянием движка и управлять им из терминала
без Push 2: локально на Mac (разработка, IAC Driver) и на RPi по SSH
(выступления, отладка в полевых условиях).

## Не-цели (v1)

- Полноэкранный TUI (textual, панели, окна) — сознательно не делаем
- Запись изменений в `../config.yaml`
- Выполнение команд из файла (`run script.txt`)
- Автозапуск REPL по детекту TTY (только флаг `--repl`)
- Управление drum-lane паттернами пошагово (это зона D3-падов)
- Mute дорожек (в Session API v1 нет mute; добавление — отдельная задача)
- Переключение swing в рантайме, если нет публичного сеттера (только отображение)

---

## Архитектура

### Слои и зависимости

REPL — это третий «фронтенд» к движку (рядом с Push 2 UI и headless).
Направление зависимостей строго вниз, циклов нет:

```
main.py
  └── app/
        ├── application.py        ← App (main loop, сбор снапшота)
        ├── engine_control.py     ← AppEngineControl (реализация EngineControl)
        └── ...
  └── repl/                       ← НЕ импортирует app/ вообще
        ├── engine_control.py     ← EngineControl (ABC) — контракт
        ├── status.py             ← StatusSnapshot (frozen, чистые данные)
        ├── command.py            ← Command (DTO)
        ├── parser.py             ← строка → Command
        ├── executor.py           ← Command + EngineControl → CommandResult
        ├── confirm.py            ← политика подтверждений
        ├── log_buffer.py         ← кольцевой буфер логов
        ├── history_store.py      ← путь к файлу истории
        ├── completer.py          ← NestedCompleter из таблицы parser'а
        ├── status_bar.py         ← StatusSnapshot → строка toolbar'а
        └── repl.py               ← Repl: поток, цикл prompt_toolkit
```

Ключевое: `repl/` зависит только от `EngineControl` (ABC) и `StatusSnapshot`.
Поэтому весь слой тестируется моком, а `app/` может реализовать контракт.
`app/engine_control.py` импортирует `repl.engine_control` — цикла нет
(repl не импортирует app ни под каким видом, даже в `TYPE_CHECKING`).

### Потоки и безопасность

Существующая схема: main loop App обрабатывает тики, порты, мутацию
(всё движок — в одном потоке). REPL добавляет второй поток. Правила:

1. **REPL-поток никогда не читает объекты движка напрямую** (ClockManager,
   Session, Harmony, PortManager). Только `StatusSnapshot` — frozen
   dataclass из чистых данных.
2. **Снапшот собирается в main loop** (там же, где `_poll_ports()`, раз в
   ~0.5 с или каждую итерацию loop'а) и публикуется атомарной заменой
   ссылки: `self._status_snapshot = snap`. Под GIL замена ссылки —
   атомарна, замок не нужен.
3. Команды управления вызывают только те методы движка, что спроектированы
   для внешних вызовов (как кнопки Push 2): `ClockManager.request_source()`,
   `Harmony.set_root()/set_scale()`, `Session.freeze_all()/evolve_all()`,
   `Session.remove_track()` и т.д. Все они валидируют вход и не падают.
4. Деструктивные команды идут через подтверждение в потоке REPL до вызова
   в движок.

### Сбор StatusSnapshot

`../src/repl/status.py`:

```python
@dataclass(frozen=True)
class PortSummary:
    name: str
    status: str          # "connected" | "disconnected" | "ambiguous" | "error"
    detail: str          # человекочитаемая строка: match/serial или ошибка

@dataclass(frozen=True)
class TrackSummary:
    name: str
    kind: str            # "melodic" | "drum"
    profile: str         # для melodic; для drum — "drum"
    sources: tuple[str, ...]
    mutation_count: int
    frozen: bool

@dataclass(frozen=True)
class StatusSnapshot:
    running: bool
    bpm: float
    swing: float
    clock_source: str    # "internal" | "midi" | "link"
    clock_pending: str | None
    clock_error: str | None
    link_active: bool
    link_peers: int
    root: str
    scale: str
    tracks: tuple[TrackSummary, ...]
    total_mutations: int
    ports: tuple[PortSummary, ...]
    log_error: str | None  # последняя ошибка из логов (если есть)
```

Всё — строки/числа/кортежи. Никаких ссылок на объекты движка.

Сбор в App: `App._update_status_snapshot()` читает `ClockState`
(`ClockManager.state`), `PortManager` (список `PortState`), `Session`
(`ordered_tracks()`, `total_mutation_count()`), `Harmony` (`root`,
`scale_name`). Реализация — в `AppEngineControl`, App предоставляет
read-only свойства (см. ниже).

---

## Интерфейс EngineControl

`../src/repl/engine_control.py` — ABC:

```python
class EngineControl(ABC):
    @abstractmethod
    def get_status(self) -> StatusSnapshot: ...

    @abstractmethod
    def get_logs(self, n: int) -> list[str]: ...

    # --- транспорт и клок ---
    @abstractmethod
    def start_transport(self) -> None: ...
    @abstractmethod
    def stop_transport(self) -> None: ...
    @abstractmethod
    def set_bpm(self, bpm: float) -> None: ...
    @abstractmethod
    def request_clock_source(self, source: str) -> str:
        """Вернуть человекочитаемый результат: "switched to midi on next beat"
        или текст ошибки (валидация source, Link не установлен и т.п.)."""

    # --- порты ---
    @abstractmethod
    def rescan_ports(self) -> str: ...

    # --- гармония ---
    @abstractmethod
    def set_root(self, root: str) -> str: ...
    @abstractmethod
    def set_scale(self, name: str) -> str: ...

    # --- сессия ---
    @abstractmethod
    def list_tracks(self) -> list[TrackSummary]: ...
    @abstractmethod
    def create_track(self, profile: str) -> str: ...
    @abstractmethod
    def remove_track(self, name: str) -> str: ...
    @abstractmethod
    def freeze(self, name: str | None = None) -> str: ...
    @abstractmethod
    def evolve(self) -> str: ...
```

Методы, возвращающие `str`, — пользовательский фидбек (ок/ошибка).
Исключения из движка ловятся в реализации и превращаются в текст ошибки:
REPL не должен ронять цикл по исключению команды.

### Реализация: `../src/app/engine_control.py`

`AppEngineControl(EngineControl)` — единственный модуль, имеющий доступ
к внутренностям App. Для этого в `App` добавляются публичные read-only
свойства (без сеттеров): `clock_manager`, `port_manager`, `session`,
`harmony`, `transport`, `swing_amount`, `status_snapshot`, `log_buffer`,
плюс `set_sync_bpm(value)`. Ничего другого в App не меняем.

Сбор снапшота: `AppEngineControl.get_status()` возвращает
`app.status_snapshot` (уже собранный в main loop). Если снапшот ещё не
собран (loop не стартовал) — вернуть дефолтный пустой.

`set_bpm`: валидировать диапазон (20..300), писать в `app._sync_bpm`
через новый метод `App.set_sync_bpm()` — тот же механизм, что использует
энкодер на Push 2.

`request_clock_source`: маппинг строки в `ClockSource` enum, делегировать
`ClockManager.request_source()`. Ошибки (неверное имя, Link не
установлен, MIDI-порт не найден) — текстом.

`set_root`/`set_scale`: `Harmony.set_root()`/`set_scale()`, `HarmonyError`
→ текст ошибки (например, пентатоника отклоняется).

`create_track`: `Session.create_melodic_track(profile)` с `PROFILES`,
ошибки лимитов (16 дорожек) — текстом.

`freeze(name)`: без имени → `Session.freeze_all()`; с именем → найти
трек, `MelodicTrack.freeze()` (у DrumTrack freeze игнорируем/ошибка текстом).

---

## Команды

Синтаксис — git-стиль: `домен [действие] [аргументы]`. Таблица команд v1:

| Команда | Действие | Деструктивная? |
|---------|----------|----------------|
| `status` | Полный снапшот текстом | нет |
| `start` | Запустить транспорт | нет |
| `stop` | Остановить транспорт | **да** (y/N) |
| `bpm <20..300>` | Установить BPM | нет |
| `clock` | Статус клока: source, pending, link peers, ошибка | нет |
| `clock source <internal\|midi\|link>` | Переключить источник (на ближайшей доле) | нет |
| `ports` | Список портов: имя, статус, детали | нет |
| `ports scan` | Принудительный rescan | нет |
| `tracks` | Список дорожек: имя, профиль, источники, mut, frozen | нет |
| `track show <name>` | Детали одной дорожки | нет |
| `track add <profile>` | Создать melodic-дорожку профиля | нет |
| `track delete <name>` | Удалить дорожку (зависимые получают `sources = ()`) | **да** (y/N) |
| `root <note>` | Сменить тонику (`root A`, `root F#`) | нет |
| `scale <mode>` | Сменить лад (`scale dorian`); валидация 8 ладов | нет |
| `freeze` | Заморозить все дорожки | нет |
| `freeze <name>` | Заморозить одну дорожку | нет |
| `evolve` | Разморозить и продолжить эволюцию | нет |
| `mutations` | Счётчик мутаций | нет |
| `logs [N]` | Последние N строк лога (default 20) | нет |
| `help [команда]` | Справка; без аргумента — список | нет |
| `exit` / `quit` / Ctrl+D | `app.stop()` | — |

Правила парсера:

- Лишние пробелы и регистр доменов не важны (`CLOCK SOURCE MIDI` ок).
- Неизвестная команда → список похожих команд (difflib) + `help`.
- Ошибка синтаксиса → usage-строка команды.
- Флаги `--yes`/`-f` на деструктивных командах — сразу выполнять.

### Автодополнение

`NestedCompleter` строится из таблицы команд parser'а
(`домен → {действие → {аргументы}}`), плюс динамические дополнения:
- `track show/delete/freeze <TAB>` → имена из `list_tracks()`
- `scale <TAB>` → 8 ладов из `HARMONIC_SCALES`
- `root <TAB>` → 12 нот
- `track add <TAB>` → профили из `PROFILES`
- `clock source <TAB>` → internal/midi/link

Динамические части — отдельный `DynamicCompleter`, который дергает
`EngineControl` при TAB-нажатии (дешёво: снапшот уже в памяти).

---

## Статус-бар (мониторинг)

`prompt_toolkit` `bottom_toolbar` — функция `() -> str`, вызывается при
перерисовке. Живость — через `prompt(..., refresh_interval=0.5)`
(перерисовка 2 раза/сек; `refresh_interval` встроен в prompt_toolkit).

Формат (ASCII-only — безопасно для любых SSH-терминалов):

```
> 120.0 bpm | clock: internal | A dorian | tracks 5 | mut 12 | ports 3 ok
```

Модификаторы:

- Транспорт не запущен: `||` вместо `>`, серый цвет.
- Есть `clock_pending`: `clock: midi (pending)`, жёлтый.
- `clock_error` или порт в `error`/`ambiguous`: красный сегмент с текстом ошибки.
- Link активен: справа `| link: 2 peers`.
- Обрезание по ширине терминала (`shutil.get_terminal_size().columns`):
  приоритет слева направо, хвост обрезается.

Цвета — ANSI через prompt_toolkit `Style`: зелёный (ok/бег), жёлтый
(pending), красный (error), серый (paused). В не-TERM средах
(`TERM=dumb`, pipe) — без цветов.

---

## Запуск и жизненный цикл

### main.py

```
python -m src.main --repl [--config config.yaml] [--simulate]
```

Флаг `--repl`: после создания `App` создаётся `AppEngineControl(app)`,
`Repl(...)`, и `app.run(repl=repl)` стартует REPL-поток вместе с main loop.

### Поток Repl

`Repl` — класс с методом `run()` для потока (threading.Thread, daemon).

Цикл:

```python
def run(self) -> None:
    while not self._stopped:
        try:
            line = self._prompt()   # prompt_toolkit с toolbar + историей
        except EOFError:
            self._on_eof()          # app.stop()
            break
        except KeyboardInterrupt:
            continue                # очистить строку, не выходить
        result = self._executor.execute(line)
        if result.output:
            print(result.output)
    self._history.flush()
```

- EOF (Ctrl+D, обрыв SSH → закрытый stdin) → `on_eof` → `app.stop()` —
  процесс завершается по выбранной политике «режим по флагу».
- `exit`/`quit` → то же самое.
- `app.stop()` снаружи (SIGTERM от systemd) → main loop завершается →
  App джойнит REPL-поток и мягко закрывает prompt (внутри Repl —
  флаг `_stopped`, поток выходит на следующей итерации).

### Совместимость с systemd

Без `--repl` ничего не меняется — headless-режим как раньше.
С `--repl` под systemd REPL не запускают (нет TTY); если stdin не TTY,
Repl выводит предупреждение и работает в «тихом» режиме (принимает EOF
как стоп) — но рекомендация: не использовать `--repl` в юните.

---

## Логи: LogBuffer

`../src/repl/log_buffer.py` — `LogBuffer(logging.Handler)`:

- `deque(maxlen=500)` — кольцевой буфер форматированных строк
  (`self.format(record)` при emit).
- `get_last(n: int) -> list[str]`.
- Регистрация в `apply_logging_config` (или отдельным вызовом из main):
  handler уровня INFO, пишет в буфер в дополнение к существующим
  обработчикам. Со снапшотом не связан — `logs` команда читает буфер
  напрямую из потока REPL (deque-операции потокобезопасны).

---

## История команд

- Путь: рядом с config.yaml — `<config_dir>/repl_history`.
- `FileHistory(path)` из prompt_toolkit; родительская директория
  создаётся при необходимости.
- Обрезка: при старте, если файл > 2000 строк — оставить последние 1000.
- Файл в `../.gitignore` проекта (строка `repl_history`).

---

## Подтверждения

`../src/repl/confirm.py`:

```python
class ConfirmPolicy(Enum):
    INTERACTIVE = auto()   # спрашивать y/N
    ALWAYS = auto()        # для тестов и --yes
```

- Деструктивные команды объявлены в таблице parser'а (`destructive=True`).
- В INTERACTIVE-режиме: печатается `Delete track "Pad 3"? [y/N]`,
  ответ `y`/`yes` — выполнять, иначе — «cancelled».
- `--yes`/`-f` — пропускает вопрос.
- В тестах политика ALWAYS.

---

## Файлы (итоговый список)

Новые:

| Файл | Содержимое |
|------|-----------|
| `../src/repl/__init__.py` | пакет |
| `../src/repl/engine_control.py` | `EngineControl` ABC |
| `../src/repl/status.py` | `StatusSnapshot`, `PortSummary`, `TrackSummary` |
| `../src/repl/command.py` | `Command` DTO: `argv`, `domain`, `action`, `args`, `flags` |
| `../src/repl/parser.py` | `CommandParser`: строка → Command; таблица команд; usage |
| `../src/repl/executor.py` | `CommandExecutor`: Command → CommandResult(output, code) |
| `../src/repl/confirm.py` | `ConfirmPolicy`, callback-протокол |
| `../src/repl/log_buffer.py` | `LogBuffer(logging.Handler)` |
| `../src/repl/history_store.py` | путь истории, обрезка |
| `../src/repl/completer.py` | NestedCompleter + динамические дополнения |
| `../src/repl/status_bar.py` | `render_toolbar(snapshot, width) -> str` |
| `../src/repl/repl.py` | `Repl`: поток, цикл prompt_toolkit |
| `../src/app/engine_control.py` | `AppEngineControl(EngineControl)` |

Изменённые:

| Файл | Изменение |
|------|-----------|
| `../src/app/application.py` | read-only свойства; `set_sync_bpm()`; `_update_status_snapshot()` в main loop; `run(repl=...)`; cleanup REPL-потока в `stop()` |
| `../src/main.py` | флаг `--repl`; сборка Repl и передача в App |
| `../src/logging_config.py` | регистрация LogBuffer (или отдельная функция) |
| `../pyproject.toml` | зависимость `prompt_toolkit>=3.0` |
| `../.gitignore` | `repl_history` |

Тесты (минимум — дымовые):

| Файл | Что проверяет |
|------|--------------|
| `../tests/test_repl_parser.py` | разбор всех команд, ошибки синтаксиса, usage, похожие команды |
| `../tests/test_repl_executor.py` | мок EngineControl: каждая команда, коды возврата, confirm y/N, `--yes` |
| `../tests/test_repl_status_bar.py` | рендер бара: цвета, pending, error, обрезание по ширине |
| `../tests/test_repl_smoke.py` | весь Repl через `create_pipe_input()` + `DummyOutput`: команды в pipe → вывод в pipe, EOF → stop вызван |

---

## Риски и митигация

| Риск | Митигация |
|------|-----------|
| Гонка REPL-потока и main loop при чтении состояния | Снапшот только из main loop, атомарная замена ссылки; REPL не трогает движок |
| bottom_toolbar не обновляется сам по себе | `refresh_interval=0.5` в `prompt()` |
| SSH-обрыв останавливает музыку (EOF → stop) | Принято сознательно (политика «по флагу»); systemd-юнит не использует `--repl` |
| Не-UTF8/TERM=dumb терминалы | ASCII-only бар, отключение цветов по TERM |
| Узкий терминал (< 80 колонок) | Обрезание бара по приоритету слева направо |
| prompt_toolkit в RPi-окружении | Pure Python, без C-расширений; проверить в спайке-окружении задачи A1 |
| История разрастается | Обрезка до 1000 строк на старте |
| REPL-поток завис на вводе при stop() из другого потока | `stop()` ставит флаг и вызывает `app.invalidate()` у prompt-объекта; поток выходит по EOFError/на следующей итерации |

---

## Критерии готовности

1. `python -m src.main --repl` поднимается и на Mac (IAC), и на RPi по SSH.
2. Статус-бар обновляется ~2 раза/сек и отражает: bpm, источник клока
   (с pending), root/scale, число дорожек, mutation count, состояние портов.
3. Все команды из таблицы работают; деструктивные спрашивают y/N.
4. `clock source midi` применяется на ближайшей доле, `all_notes_off`
   перед переключением — штатное поведение B1, регрессии нет.
5. Ctrl+D и `exit` останавливают App чисто (без хвостов в MIDI, порты
   закрыты).
6. Без `--repl` поведение main.py не изменилось (регрессионный прогон
   существующих 726 тестов зелёный).
7. Дымовые тесты REPL проходят; ruff/black чисто на новых файлах;
   mypy — только пре-существующие ошибки (mido/isobar без stubs).
8. История сохраняется между запусками в файле рядом с config.yaml.

---

## Шаги реализации (для coder-агента)

1. **Зависимости**: `prompt_toolkit>=3.0` в pyproject, обновить uv.lock.
2. **`../src/repl` скелет**: status.py, command.py, engine_control.py (ABC),
   confirm.py — без логики, компилируется.
3. **parser.py + executor.py**: таблица команд, разбор, мок-фикстура
   EngineControl для тестов. Тесты parser/executor.
4. **App-сторона**: read-only свойства, `set_sync_bpm()`,
   `_update_status_snapshot()` в main loop, `run(repl=...)`, cleanup.
5. **`../src/app/engine_control.py`**: AppEngineControl со всеми методами.
6. **repl.py + completer.py + status_bar.py + history_store.py**:
   поток, цикл prompt_toolkit, динамическое автодополнение, бар.
7. **LogBuffer**: logging.Handler, регистрация, команда `logs`.
8. **main.py**: флаг `--repl`, сборка, политика EOF → stop.
9. **Дымовые тесты**: smoke через pipe input; ручной чек-лист из
   «Критериев готовности» пункт 1–5 на Mac.
10. **AGENTS.md**: раздел «Задача F1» со статусом ✅, файлами,
    результатами; обновить «Рекомендации по запуску агентов».
