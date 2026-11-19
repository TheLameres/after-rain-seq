# План B4: Транспорт и свинг

> **Зависимости:** B1 (ClockManager + TickProxy) ✅
> **Источник:** `../push2_dubtechno_plan_v5_4.md` §4.1a (свинг), §5.1 (контракт движка), Фаза 2
> **Дата плана:** 2026-11-01

---

## 1. Цель

Создать слой доставки MIDI-событий от isobar Timeline к физическим портам, который:

1. **Работает в двух режимах** под одним интерфейсом: Mode A (IsobarClock — isobar ведёт тики) и Mode B (ExternalClock —
   собственный цикл с look-ahead)
2. **Применяет свинг через длительности** — работает при всех трёх источниках клока
3. **Гарантирует `int()`** на всех значениях из isobar (`numpy.int64` → `int`)
4. **all_notes_off** по панике и при потере порта
5. **Троттлит CC** — flush () на границах тактов

---

## 2. Текущее состояние (что уже есть)

| Компонент      | Файл                         | Статус                                                         |
|----------------|------------------------------|----------------------------------------------------------------|
| ClockManager   | `../src/sync/clock_manager.py`  | ✅ Три источника, квантизация на долю, all_notes_off при смене |
| TickProxy      | `../src/sync/tick_proxy.py`     | ✅ Очередь + worker thread, drop-oldest                        |
| MidiPortOutput | `../src/sync/routing.py`        | ✅ Адаптер isobar→mido, CC mapping + throttle, flush()         |
| PortRegistry   | `../src/sync/routing.py`        | ✅ Жизненный цикл портов, all_notes_off при disconnect         |
| CCThrottle     | `../src/sync/throttle.py`       | ✅ 30 Hz, flush(), reset()                                     |
| CCMap          | `../src/sync/cc_map.py`         | ✅ Логические имена → номера, invert, range                    |
| Timeline       | создаётся в `application.py` | ✅ Создаётся с `ticks_per_beat=480`, **output_devices пуст**   |

**Чего нет:**

- `CaptureOutput` — isobar OutputDevice, перехватывающий события в очередь
- `Transport` — движок доставки событий из очереди на порты
- `swing.py` — свинг через длительности
- Связка Timeline → CaptureOutput → Transport → PortRegistry
- Swing amount в конфиге

---

## 3. Архитектура

### 3.1. Поток данных

```
Clock Source (internal/midi/link)
    ↓  tick()
TickProxy (queue + worker thread)         [B1 ✅]
    ↓  dispatch
isobar Timeline                           [существует]
    ↓  Timeline.tick() вызывает device.tick() / note_on() / note_off() / control_change()
    ↓  на каждом output_device в timeline.output_devices
CaptureOutput (НОВЫЙ)                     [B4]
    ↓  перехватывает события, кладёт в очередь TransportEvent
    ↓  разрешает logical CC names через CCMap
Transport (НОВЫЙ)                         [B4]
    ↓  забирает события из очереди
    ↓  применяет свинг (duration transform)
    ↓  маршрутизирует по PortRegistry
PortRegistry → MidiPortOutput             [B2 ✅]
    ↓  note_on / note_off / control_change / flush
Physical MIDI ports
```

### 3.2. Режимы работы

**Mode A — IsobarClock (старт проекта, реализуем сейчас):**

- isobar Clock/MidiInputDevice/_LinkClockSource тикают TickProxy
- TickProxy worker вызывает `timeline.tick()`
- Timeline на каждом тике вызывает методы на всех `output_devices`
- CaptureOutput стоит в `timeline.output_devices`, перехватывает события
- Transport забирает из очереди CaptureOutput и доставляет на порты
- **Доставка происходит в том же потоке, что и генерация** (TickProxy worker)

**Mode B — ExternalClock (закладываем интерфейс, реализация позже):**

- Собственный поток с `perf_counter()`
- Look-ahead: генерируем события заранее, шлём по wall-clock deadline
- Нужен если Mode A не даст нужной точности
- **Интерфейс Transport не меняется** — только внутренний механизм

### 3.3. Почему свинг через длительности

Из плана (§4.1a):

|                               | Сдвиг wall-clock              | Сдвиг длительностей |
|-------------------------------|-------------------------------|---------------------|
| Работает при IsobarClock      | **нет** — нет точки перехвата | **да**              |
| Работает при ExternalClock    | да                            | да                  |
| Риск инверсии порядка событий | есть                          | **нет**             |
| Риск удлинения ноты           | есть                          | **нет**             |

Свинг = укоротить чётные шаги 1/8, удлинить нечётные. Сумма пары сохраняется — темп не уезжает. Работает для всех
дорожек (melodic + drum) осознанно.

---

## 4. Файлы для создания

### 4.1. `../src/sync/swing.py` — свинг через длительности

**Что:** Чистая функция + класс-обёртка для применения к событиям.

```python
@dataclass(frozen=True)
class SwingConfig:
    """Конфигурация свинга."""
    amount: float = 0.0  # 0.0..1.0, 0 = выключен
    grid: int = 2  # 2 = 1/8, 4 = 1/16 (пока только 2)


def swing_duration(base: float, step_index: int, amount: float) -> float:
    """Чётный шаг короче на amount*pair/2, нечётный длиннее на столько же.
    Сумма пары сохраняется — темп не уезжает."""


class SwingApplier:
    """Применяет свинг к последовательности событий."""

    def apply(self, events: list[TransportEvent]) -> list[TransportEvent]: ...
```

**Ключевые решения:**

- Grid = 1/8 (не 1/16 — слишком тонко слышно)
- `amount=0` → passthrough (нет свинга)
- Свинг действует на **все** дорожки глобально
- Применяется к `duration` события, не к wall-clock времени

**Тесты:** `../tests/test_swing.py`

- amount=0 → длительности не меняются
- amount=0.5 → чётный шаг = base *0.75, нечётный = base*1.25
- Сумма пары = 2*base (темп сохраняется)
- Отрицательный amount → ValueError
- amount > 1.0 → ValueError

---

### 4.2. `../src/sync/transport_event.py` — тип события для транспорта

**Что:** Frozen dataclass, представляющий одно MIDI-событие в очереди транспорта.

```python
@dataclass(frozen=True)
class TransportEvent:
    """Одно MIDI-событие, готовое к доставке."""
    kind: EventKind  # NOTE_ON / NOTE_OFF / CONTROL_CHANGE
    port_label: str  # куда отправить (label из PortConfig)
    channel: int  # 0-15
    note: int | None  # для NOTE_ON/OFF
    velocity: int | None  # для NOTE_ON
    control: int | None  # для CONTROL_CHANGE (уже разрешённый номер)
    value: int | None  # для CONTROL_CHANGE
    duration: float | None  # в долях (для свинга)
    beat: float  # позиция в таймлайне (для свинга: вычисление step_index)
```

**Почему отдельный файл:** Соответствует правилу «один класс — один файл». Используется и CaptureOutput, и Transport, и
SwingApplier — общий тип ниже обоих.

**Тесты:** `../tests/test_transport_event.py`

- Создание каждого вида события
- Frozen (immutable)
- repr

---

### 4.3. `../src/sync/capture_output.py` — перехватчик isobar-событий

**Что:** isobar OutputDevice, который не шлёт в MIDI, а кладёт события в очередь Transport.

```python
class CaptureOutput:
    """isobar OutputDevice, перехватывающий события в очередь.

    Ставится в timeline.output_devices. isobar Timeline вызывает
    note_on/note_off/control_change на каждом устройстве в этом списке.
    CaptureOutput перехватывает их и кладёт TransportEvent в очередь.
    """

    def __init__(self, event_queue: queue.Queue[TransportEvent]) -> None: ...

    # isobar OutputDevice interface:
    def tick(self, tick_count: int) -> None: ...

    def note_on(self, channel: int, note: int, velocity: int, ...) -> None: ...

    def note_off(self, channel: int, note: int, ...) -> None: ...

    def control_change(self, channel: int, control: int, value: int) -> None: ...

    def all_notes_off(self) -> None: ...
```

**Ключевые решения:**

- `tick()` — no-op (не перехватываем MIDI Clock, только события)
- `all_notes_off()` — пробрасывает событие ALL_NOTES_OFF в очередь (чтобы Transport мог его обработать)
- Все значения `int()` при создании TransportEvent
- `port_label` — CaptureOutput не знает о портах. Порт определяется **дорожкой**, которая генерирует событие. Но isobar
  не передаёт информацию о дорожке в output_device...

**⚠️ Проблема: маршрутизация по портам.**

isobar Timeline вызывает `output_devices` без контекста дорожки. Но нам нужно знать, **на какой порт** отправить
событие. Решения:

**Вариант A: Один CaptureOutput на порт.** Создаём N CaptureOutput (по одному на каждый порт), добавляем все в
`timeline.output_devices`. Каждый знает свой `port_label`. Но тогда каждое событие попадёт в **все** порты — isobar шлёт
на все устройства.

**Вариант B: CaptureOutput с фильтром.** Один CaptureOutput, но события помечаются дорожкой. isobar это не поддерживает
напрямую.

**Вариант C (выбран): Timeline per port.** Вместо одного Timeline с N output_devices — **несколько Timelines, каждый со
своим CaptureOutput**. Но ClockManager сейчас управляет одним Timeline...

**Вариант D (выбран, проще): Отложенная маршрутизация.** CaptureOutput кладёт события без `port_label` (или с
`port_label=None`). Transport при доставке смотрит на `track_id` → ищет порт дорожки через Session. Но Session ещё не
интегрирован в B4...

**Вариант E (прагматичный, для B4): CaptureOutput с port_label, один на порт.** Но не добавляем все в
timeline.output_devices. Вместо этого:

- Создаём **один** Timeline
- Добавляем **один** CaptureOutput в `timeline.output_devices`
- CaptureOutput кладёт события с `port_label="default"` (или пустым)
- Transport при доставке использует **текущий маршрут** — пока один порт по умолчанию
- Когда появится Session (C3) — маршрутизация станет умнее

**Для B4 это приемлемо**, потому что:

- B4 зависит только от B1, не от C3
- Полная маршрутизация по дорожкам — задача интеграции C3+B4
- Сейчас нужен **рабочий транспорт**, который доставляет события на хотя бы один порт

**Финальное решение для B4:** `CaptureOutput` принимает `port_label: str` в конструкторе. В Application создаётся один
CaptureOutput с label первого сконфигурированного порта. Полная маршрутизация — при интеграции с Session.

**Тесты:** `../tests/test_capture_output.py`

- note_on → TransportEvent в очереди с правильными полями
- note_off → TransportEvent NOTE_OFF
- control_change → TransportEvent CONTROL_CHANGE
- tick () → ничего не добавляет в очередь
- all_notes_off → событие ALL_NOTES_OFF в очереди
- int () на numpy.int64 значениях
- Очередь полна → drop-oldest (не блокировать Timeline)

---

### 4.4. `../src/sync/transport.py` — движок доставки

**Что:** Забирает события из очереди CaptureOutput, применяет свинг, доставляет на порты через PortRegistry.

```python
class Transport:
    """Движок доставки MIDI-событий от Timeline к портам.

    Mode A (IsobarClock): вызывается из TickProxy worker после каждого
    timeline.tick(). Забирает накопившиеся события из очереди CaptureOutput
    и доставляет немедленно.

    Mode B (ExternalClock): собственный поток с look-ahead.
    Закладываем интерфейс, реализация позже.
    """

    def __init__(
            self,
            event_queue: queue.Queue[TransportEvent],
            port_registry: PortRegistry,
            swing: SwingApplier,
            mode: TransportMode = TransportMode.ISOBAR,
    ) -> None: ...

    def process_events(self) -> None:
        """Забрать все события из очереди и доставить. Вызывается после каждого тика."""

    def all_notes_off(self) -> None:
        """Паника: all_notes_off на всех портах + очистка очереди."""

    def flush_cc(self) -> None:
        """Flush throttled CC на всех портах."""

    @property
    def mode(self) -> TransportMode: ...

    def set_mode(self, mode: TransportMode) -> None: ...
```

**TransportMode enum:**

```python
class TransportMode(Enum):
    ISOBAR = auto()  # Mode A: доставка в том же потоке, что генерация
    EXTERNAL = auto()  # Mode B: собственный поток с look-ahead (TODO)
```

**Ключевые решения:**

1. **process_events () вызывается из TickProxy dispatch hook** — после `timeline.tick()`:
   ```python
   def hooked_dispatch(event):
       if event.name == "TICK":
           cm.on_tick()
       original_dispatch(event)
       if event.name == "TICK":
           transport.process_events()  # ← после тика: доставка
   ```

2. **Свинг применяется в process_events ()** — к каждому событию с `duration`:
    - Вычисляем `step_index = int(event.beat * swing.grid) % swing.grid`
    - `event.duration = swing_duration(event.duration, step_index, swing.amount)`
    - Создаём новый TransportEvent с изменённой длительностью

3. **CC flush на границах тактов** — если `timeline.current_time % 4 == 0` (начало такта):
   ```python
   if beat_position % 4.0 == 0.0:
       self._port_registry.flush_all()
   ```

4. **all_notes_off ()**:
    - Очищает очередь событий (чтобы не отсылать накопившееся)
    - Вызывает `port_registry.all_outputs()` → `all_notes_off()` на каждом
    - Вызывает `port_registry` → `flush_all()` (чтобы сбросить throttle)

5. **int () на всех значениях** — при доставке в MidiPortOutput:
   ```python
   adapter.note_on(channel=int(event.channel), note=int(event.note), velocity=int(event.velocity))
   ```

**Тесты:** `../tests/test_transport.py`

- **TestProcessEvents:**
    - Событие NOTE_ON → вызван adapter.note_on с правильными args
    - Событие NOTE_OFF → вызван adapter.note_off
    - Событие CONTROL_CHANGE → вызван adapter.control_change
    - Порт не найден → событие пропущено (тихо, с warning)
    - Очередь пуста → ничего не происходит

- **TestSwing:**
    - swing.amount=0 → длительности не меняются
    - swing.amount>0 → чётные шаги короче, нечётные длиннее
    - События без duration → свинг не применяется

- **TestAllNotesOff:**
    - Очередь очищена
    - all_notes_off вызван на всех адаптерах
    - Throttle сброшен

- **TestCCFlush:**
    - На границе такта → flush_all () вызван
    - Не на границе → flush_all () не вызван

- **TestMode:**
    - Default mode = ISOBAR
    - set_mode (EXTERNAL) → пока не реализовано, raise NotImplementedError

- **TestIntConversion:**
    - numpy.int64 channel/note/velocity → int при доставке

---

### 4.5. Изменения в существующих файлах

#### 4.5.1. `../src/sync/config.py` — добавить swing_amount

```python
class SyncConfig(BaseModel):
    # ... existing fields ...
    swing_amount: float = Field(default=0.0, ge=0.0, le=1.0)
```

#### 4.5.2. `../src/app/application.py` — интеграция Transport

В `_init_clock_manager()`:

```python
# Создать очередь событий
event_queue: queue.Queue[TransportEvent] = queue.Queue(maxsize=4096)

# Создать CaptureOutput и добавить в Timeline
capture = CaptureOutput(event_queue, port_label="default")  # или первый порт
timeline.output_devices.append(capture)

# Создать SwingApplier
swing = SwingApplier(SwingConfig(amount=sync_config.swing_amount))

# Создать Transport
self._transport = Transport(
    event_queue=event_queue,
    port_registry=self._port_registry,
    swing=swing,
)

# Hook transport.process_events() в TickProxy dispatch
original_dispatch = self._tick_proxy._dispatch
cm = self._clock_manager


def hooked_dispatch(event):
    if event.name == "TICK":
        cm.on_tick()
    original_dispatch(event)
    if event.name == "TICK":
        self._transport.process_events()


self._tick_proxy._dispatch = hooked_dispatch
```

В `_cleanup()`:

```python
if self._transport:
    self._transport.all_notes_off()
```

#### 4.5.3. `../config.yaml` — добавить swing_amount

```yaml
sync:
  enabled: true
  clock_source: "internal"
  midi_clock_device: null
  bpm: 120.0
  swing_amount: 0.0    # 0.0..1.0, 0 = выключен
```

#### 4.5.4. `../src/config.py` — DEFAULT_CONFIG_YAML

Добавить `swing_amount: 0.0` в sync-секцию шаблона.

---

## 5. Порядок реализации

### Шаг 1: `../src/sync/swing.py` + тесты

- SwingConfig frozen dataclass
- swing_duration () чистая функция
- SwingApplier класс
- ~15 тестов

### Шаг 2: `../src/sync/transport_event.py` + тесты

- EventKind enum
- TransportEvent frozen dataclass
- ~8 тестов

### Шаг 3: `../src/sync/capture_output.py` + тесты

- CaptureOutput класс (isobar OutputDevice interface)
- ~12 тестов

### Шаг 4: `../src/sync/transport.py` + тесты

- TransportMode enum
- Transport класс
- ~25 тестов

### Шаг 5: Конфиг

- `../src/sync/config.py` — добавить swing_amount
- `../src/config.py` — DEFAULT_CONFIG_YAML
- `../config.yaml` — swing_amount: 0.0

### Шаг 6: Интеграция в Application

- `_init_clock_manager()` — создать CaptureOutput, Transport, hook в dispatch
- `_cleanup()` — transport.all_notes_off ()

### Шаг 7: Проверка

- Все тесты проходят
- ruff / mypy / black чисто
- Ручной smoke-тест: внутренний клок + один порт → ноты играют

---

## 6. Ожидаемый результат

| Метрика            | Цель                                                              |
|--------------------|-------------------------------------------------------------------|
| Новых файлов       | 4 (swing.py, transport_event.py, capture_output.py, transport.py) |
| Новых тестов       | ~60                                                               |
| Изменённых файлов  | 4 (config.py × 2, application.py, config.yaml)                    |
| Общее число тестов | ~567 (507 + 60)                                                   |
| ruff/mypy/black    | Чисто                                                             |

---

## 7. Риски и митигация

| Риск                                            | Вероятность | Митигация                                                                    |
|-------------------------------------------------|-------------|------------------------------------------------------------------------------|
| isobar OutputDevice interface не документирован | Средняя     | Прочитать исходник isobar `output_device.py`, убедиться в сигнатурах         |
| Очередь переполняется при burst                 | Низкая      | Drop-oldest, как в TickProxy                                                 |
| Свинг ломает note-on/off пары                   | Низкая      | Свинг меняет duration, не время — пары не разрываются                        |
| Маршрутизация по портам неполная                | Высокая     | Для B4 — один порт по умолчанию. Полная маршрутизация при интеграции с C3    |
| Mode B (ExternalClock) — недоопределён          | Высокая     | Заложить интерфейс, реализацию отложить. Mode A достаточно для старта        |
| numpy.int64 пропущен где-то                     | Средняя     | int() в CaptureOutput при создании TransportEvent + в Transport при доставке |

---

## 8. Открытые вопросы (не блокируют B4)

| Вопрос                                         | Когда решится                      |
|------------------------------------------------|------------------------------------|
| Как маршрутизировать события по разным портам? | При интеграции C3 (Session) + B4   |
| Нужен ли Mode B (ExternalClock) на практике?   | После тестирования Mode A на RPi 5 |
| Swing amount крутится с Push 2 — как?          | D2 (экраны и навигация)            |
| Нужен ли MIDI Clock output (24 PPQN) на порты? | Отдельная задача, не B4            |

---

## 9. Связь с другими задачами

```
B4 (транспорт и свинг)
├── ← B1 (ClockManager + TickProxy) — тики приходят через TickProxy
├── ← B2 (PortRegistry) — доставка через MidiPortOutput
├── ← B3 (CCThrottle) — flush() на границах тактов
├── → C3 (Session) — маршрутизация событий по дорожкам/портам
├── → C4 (Drum) — drum-события проходят через Transport
├── → D2 (UI) — swing amount на экране, отображение
└── → E2 (живучесть) — 8-часовой прогон Transport без утечек
```
