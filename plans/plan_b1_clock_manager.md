# Расширенный план B1: ClockManager + TickProxy

## 1. Анализ: что есть и что нужно построить

### 1.1. Что уже есть в isobar (не пишем с нуля)

| Компонент | Класс isobar | Статус |
|-----------|-------------|--------|
| Internal clock | `isobar.Clock` | ✅ Готов, 480 PPQN, свой поток |
| MIDI clock in | `isobar.MidiInputDevice` | ✅ Готов, 24 PPQN, колбэк из rtmidi-потока |
| Link clock | `isobar.AbletonLinkClock` | ✅ Готов, но `run()` — `while True:` без проверки `running` |
| Timeline | `isobar.Timeline` | ✅ Готов, `set_clock_source()` — мгновенный, без квантизации |

### 1.2. Что isobar НЕ даёт (пишем сами)

| Проблема | Почему isobar не решает |
|----------|------------------------|
| Квантизация переключения на долю | `set_clock_source()` — мгновенный |
| `all_notes_off()` перед сменой | `Timeline.stop()` гасит ноты, но и останавливает клок |
| Единый поток для тиков | `MidiInputDevice` тикает из rtmidi-потока, `Clock` — из своего |
| Проверка `link` пакета | `AbletonLinkClock` падает с `NameError`, не `ImportError` |
| Отслеживание MIDI transport state | `is_midi_transport_started` не существует в isobar 0.2.1 |
| Остановка `AbletonLinkClock` | `run()` — `while True:`, `stop()` не работает |

### 1.3. Ключевые находки при чтении isobar

1. **`Timeline.set_clock_source()`** — просто `clock_source.clock_target = self; self._clock_source = clock_source`. Ни валидации, ни квантизации, ни thread-safety.
2. **`Timeline.all_notes_off()` не существует** — нужно итерировать `timeline.output_devices` и звать `device.all_notes_off()`.
3. **`AbletonLinkClock.run()`** — `while True:` без проверки `self.running`. Поток нельзя остановить штатно. Нужен обход.
4. **`MidiInputDevice`** при `device_name=None` берёт `ISOBAR_DEFAULT_MIDI_IN` из env. Если и тот пуст — `mido.open_input(name=None)` откроет первый попавшийся порт (или упадёт).
5. **`MidiInputDevice.ticks_per_beat`** — всегда 24 (read-only). **`Clock.ticks_per_beat`** — 480 по умолчанию, settable.
6. **`Timeline.current_time`** — plain attribute, можно читать и писать напрямую.
7. **Нет формального Protocol/ABC для clock sources** — duck-typing: `.clock_target`, `.tick()`, `.ticks_per_beat`, `.tempo`, `.run()`, `.stop()`.

---

## 2. Архитектура

### 2.1. Новые файлы

```
src/sync/
├── clock_manager.py      # ClockManager — оркестратор переключения
├── tick_proxy.py         # TickProxy — очередь + рабочий поток
├── clock_source.py       # ClockSource enum + фабрика + _LinkClockSource
└── clock_state.py        # ClockState — frozen dataclass для дисплея
```

### 2.2. Диаграмма потоков данных

```
┌─────────────────────────────────────────────────────────┐
│                    ClockManager                          │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐                  │
│  │ internal │  │  midi   │  │  link   │  (источники)     │
│  │  Clock   │  │MidiInput│  │_Link    │                  │
│  │          │  │ Device  │  │ClockSrc │                  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                  │
│       │              │              │                      │
│       │  tick()      │  tick()     │  tick()              │
│       │  reset()     │  start()    │  ...                 │
│       │  start()     │  stop()     │                      │
│       │  stop()      │             │                      │
│       ▼              ▼              ▼                      │
│  ┌─────────────────────────────────────┐                  │
│  │           TickProxy                  │                  │
│  │  ┌───────────────────────────────┐  │                  │
│  │  │      queue.Queue(maxsize)     │  │                  │
│  │  │  [TICK, TICK, RESET,          │  │                  │
│  │  │   START, STOP, ...]           │  │                  │
│  │  └───────────────────────────────┘  │                  │
│  │              │                      │                  │
│  │  ┌───────────▼──────────┐          │                  │
│  │  │    worker thread      │          │                  │
│  │  │  while running:       │          │                  │
│  │  │    item = q.get()     │          │                  │
│  │  │    dispatch(item)     │          │                  │
│  │  └───────────┬───────────┘          │                  │
│  └──────────────┼──────────────────────┘                  │
│                 │                                         │
│                 ▼                                         │
│  ┌──────────────────────────────┐                         │
│  │      isobar.Timeline          │                         │
│  │  tick() / reset() /           │                         │
│  │  start() / stop()             │                         │
│  └──────────────────────────────┘                         │
└─────────────────────────────────────────────────────────┘
```

### 2.3. Слои и зависимости

```
app/application.py
  └── sync/clock_manager.py     ← новый, зависит от tick_proxy, clock_source
        └── sync/tick_proxy.py   ← новый, зависит только от stdlib + isobar Timeline
        └── sync/clock_source.py ← новый, зависит от isobar + optional link
        └── sync/clock_state.py  ← новый, zero deps
```

**Никаких циклов.** `sync/` остаётся автономным — зависит только от `mido`, `isobar` и опционального `link`.

---

## 3. Детальный дизайн классов

### 3.1. `ClockSource` (enum) — `clock_source.py`

```python
from enum import Enum, auto

class ClockSource(Enum):
    INTERNAL = auto()
    MIDI = auto()
    LINK = auto()
```

**Почему enum, не строки:** типобезопасность, exhaustiveness checking в `match`, нет опечаток. В `SyncConfig` для сериализации храним строку, конвертируем при загрузке.

### 3.2. `TickProxy` — `tick_proxy.py`

**Назначение:** Все источники клока кладут события в одну очередь. Один рабочий поток забирает и диспетчеризует. Генерация всегда в одном потоке.

```python
class TickProxy:
    """Проксирует тики от любого источника клока через очередь в один поток."""
    
    def __init__(self, timeline: Timeline, max_queue: int = 4096) -> None:
        self._timeline = timeline
        self._queue: queue.Queue[TickEvent] = queue.Queue(maxsize=max_queue)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
    
    def tick(self) -> None: ...      # put_nowait(TICK)
    def reset(self) -> None: ...     # put_nowait(RESET)
    def start(self) -> None: ...     # put_nowait(START)
    def stop(self) -> None: ...      # put_nowait(STOP)
    
    def run(self) -> None: ...       # рабочий поток: q.get() → dispatch
    def start_worker(self) -> None: ...  # запуск daemon thread
    def stop_worker(self) -> None: ...   # остановка потока
```

**Ключевые решения:**

| Аспект | Решение | Почему |
|--------|---------|--------|
| Тип элементов очереди | `TickEvent` (enum): `TICK`, `RESET`, `START`, `STOP` | Явно, расширяемо, не путаем `1` с `"1"` |
| `put_nowait` vs `put` | `put_nowait` с `try/except queue.Full` | Из rtmidi-колбэка нельзя блокироваться |
| При переполнении | Drop oldest (не новый!) | Лучше пропустить старый тик, чем замереть |
| Worker thread | `daemon=True`, имя `"tick-proxy"` | Не блокирует выход, отладка |
| Диспетчеризация | `match event: case TickEvent.TICK: timeline.tick()` | Exhaustive, читаемо |

### 3.3. `ClockManager` — `clock_manager.py`

**Назначение:** Управляет текущим источником клока, квантизует переключение на долю, гасит ноты перед сменой.

```python
class ClockManager:
    """Управляет источником клока для isobar Timeline.
    
    Поддерживает три источника: internal, midi, link.
    Переключение квантизовано на ближайшую долю.
    """
    
    def __init__(
        self,
        timeline: Timeline,
        tick_proxy: TickProxy,
        config: ClockManagerConfig,
    ) -> None:
        self._timeline = timeline
        self._proxy = tick_proxy
        self._config = config
        self._current: ClockSource = ClockSource.INTERNAL
        self._pending: tuple[ClockSource, str | None] | None = None
        self._midi_transport_started: bool = False
        self._error: str | None = None
    
    def request_source(self, source: ClockSource, device: str | None = None) -> None:
        """Запросить переключение источника. Применится на ближайшей доле."""
    
    def on_tick(self) -> None:
        """Вызывается из TickProxy при каждом тике.
        Проверяет _pending и применяет если current_time % 1 == 0."""
    
    def _apply_pending(self) -> None:
        """Применить отложенное переключение:
        1. all_notes_off()
        2. Остановить старый источник
        3. Создать и запустить новый
        4. Сохранить фазу (current_time)"""
    
    @property
    def state(self) -> ClockState: ...
```

**Алгоритм `_apply_pending`:**

```
1. mode, device = self._pending; self._pending = None
2. all_notes_off() — для каждого device in timeline.output_devices
3. Остановить старый источник:
   - internal: clock_source.stop() (остановит поток)
   - midi: clock_source.stop() (no-op в isobar, но вызвать для symmetry)
   - link: _LinkClockSource.stop() (корректно останавливается)
4. beats = timeline.current_time (сохранить фазу)
5. Создать новый источник:
   - internal: Clock(timeline, tempo, ticks_per_beat)
   - midi: MidiInputDevice(device_name=device) — с проверкой
   - link: _LinkClockSource(timeline, tempo) — с проверкой link модуля
6. source.clock_target = self._proxy (НЕ timeline напрямую!)
7. timeline.set_clock_source(source)
8. timeline.current_time = beats (восстановить фазу)
9. Запустить новый источник:
   - internal: source.background() (daemon thread)
   - midi: ничего (колбэк mido сам тикает)
   - link: threading.Thread(target=source.run, daemon=True).start()
10. self._current = mode
```

### 3.4. `_LinkClockSource` — внутри `clock_source.py`

```python
class _LinkClockSource:
    """Собственная обёртка над link.Link с корректной остановкой.
    
    Интерфейс совместим с isobar clock sources (duck-typed):
    - clock_target: объект с tick()/reset()/start()/stop()
    - ticks_per_beat: int
    - tempo: float (read/write через Link session)
    - run(): blocking loop
    - stop(): корректная остановка
    """
    
    def __init__(self, clock_target, tempo: float = 120.0, ticks_per_beat: int = 480) -> None:
        self.clock_target = clock_target
        self._tempo = tempo
        self._ticks_per_beat = ticks_per_beat
        self._stop_event = threading.Event()
        self._link_client = None
        self._thread: threading.Thread | None = None
    
    def run(self) -> None:
        """Poll Link session, emit ticks. Stoppable via stop()."""
    
    def stop(self) -> None:
        self._stop_event.set()
    
    def background(self) -> None:
        """Запустить run() в daemon thread."""
    
    @property
    def tempo(self) -> float: ...
    
    @tempo.setter
    def tempo(self, value: float) -> None: ...
    
    @property
    def ticks_per_beat(self) -> int:
        return self._ticks_per_beat
```

### 3.5. `ClockState` — `clock_state.py`

```python
@dataclass(frozen=True)
class ClockState:
    """Снимок состояния клока для дисплея."""
    source: ClockSource
    pending: ClockSource | None
    bpm: float | None
    midi_transport_started: bool
    link_peers: int
    error: str | None
    running: bool
```

### 3.6. `ClockManagerConfig` — в `clock_source.py`

```python
@dataclass(frozen=True)
class ClockManagerConfig:
    """Конфигурация ClockManager."""
    initial_source: ClockSource = ClockSource.INTERNAL
    initial_bpm: float = 120.0
    ticks_per_beat: int = 480
    midi_device_name: str | None = None
```

---

## 4. Конфигурация

### 4.1. Расширение `SyncConfig`

```python
# src/sync/config.py — добавить поля
class SyncConfig(BaseModel):
    # ... существующие поля ...
    
    # Новые поля для B1
    clock_source: str = "internal"
    midi_clock_device: str | None = None
```

### 4.2. Обновление `../config.yaml`

```yaml
sync:
  enabled: true
  clock_source: "internal"
  midi_clock_device: null
  link_enabled: false
  link_bpm: 120.0
```

---

## 5. Интеграция с App

### 5.1. Порядок инициализации

```
1. Load config
2. Create Timeline(tempo=config.link_bpm, ticks_per_beat=480)
3. Create TickProxy(timeline)
4. Create ClockManager(timeline, tick_proxy, config)
5. tick_proxy.start_worker()
6. clock_manager.start()
7. ... остальная инициализация ...
8. На выходе: clock_manager.stop() → tick_proxy.stop_worker()
```

---

## 6. Краевые случаи

| Случай | Обработка |
|--------|-----------|
| `link` пакет не установлен | `request_source(LINK)` → error, не переключаем |
| `midi` без устройства | explicit error |
| MIDI transport не запущен | Трекаем `midi_transport_started` |
| Быстрое переключение туда-обратно | `_pending` перезаписывается |
| Переключение во время нецелого такта | Квантизация: `current_time % 1 == 0` |
| Очередь TickProxy переполнена | Drop oldest, keep newest |
| `all_notes_off()` бросает исключение | try/except, продолжаем |
| Остановка App при активном link | `_LinkClockSource.stop()` |
| Смена BPM при midi-режиме | Только читать `estimated_tempo` |

---

## 7. Тестирование

### Матрица тестов

| Тест | Что проверяет |
|------|--------------|
| `test_tick_proxy_dispatches_tick` | tick() → timeline.tick() |
| `test_tick_proxy_dispatches_reset` | reset() → timeline.reset() |
| `test_tick_proxy_queue_overflow` | Drop oldest при переполнении |
| `test_tick_proxy_thread_safe` | 1000 tick() из 4 потоков |
| `test_clock_manager_initial_source` | По умолчанию INTERNAL |
| `test_clock_manager_request_valid` | request_source(INTERNAL) → OK |
| `test_clock_manager_request_invalid` | request_source("bad") → ValueError |
| `test_clock_manager_quantized_switch` | Применяется только на доле |
| `test_clock_manager_all_notes_off_before_switch` | all_notes_off до set_clock_source |
| `test_clock_manager_phase_preserved` | current_time сохранён |
| `test_clock_manager_pending_overwritten` | Два request → последний |
| `test_clock_manager_link_not_available` | LINK без пакета → error |
| `test_clock_manager_midi_no_device` | MIDI без устройства → error |
| `test_clock_manager_midi_transport_tracking` | start/stop от MidiInputDevice |
| `test_link_clock_source_stoppable` | stop() останавливает поток |
| `test_link_clock_source_tempo` | tempo read/write |

---

## 8. Порядок реализации

1. `clock_state.py` + `clock_source.py` — enum, config, _LinkClockSource, фабрика
2. `tick_proxy.py` — TickEvent, TickProxy
3. `clock_manager.py` — ClockManager
4. Конфигурация — SyncConfig, config.yaml
5. Интеграция — application.py
6. Тесты — все файлы тестов
7. Проверка — pytest, ruff, mypy, black

---

## 9. Риски

| Риск | Митигация |
|------|-----------|
| `AbletonLinkClock` нельзя остановить | Пишем `_LinkClockSource` |
| Гонка при переключении | Квантизация + all_notes_off |
| `MidiInputDevice` из rtmidi-потока | TickProxy: очередь в один поток |
| Пропуск тиков | maxsize=4096, drop oldest |
| `current_time` не восстанавливается | Явное сохранение/восстановление |

---

## 10. Определение «готово»

- [ ] ClockManager переключает между internal/midi/link
- [ ] Переключение квантизовано на долю
- [ ] all_notes_off() до смены источника
- [ ] TickProxy гарантирует один поток
- [ ] Проверка link пакета, явная ошибка
- [ ] Краевые случаи обработаны
- [ ] Все тесты passed
- [ ] ruff, mypy, black чисто
- [ ] AGENTS.md обновлён
