# План B3: CC-троттлинг и маппинг

> Источник: `../push2_dubtechno_plan_v5_4.md` (разделы 2.4, 3.4, риски)
> Зависимости: B2 (порты, `MidiPortOutput`, `PortRegistry`)
> Дата планирования: 2026-11-01

---

## Цель

Два модуля в `../src/sync`:

1. **`throttle.py`** — троттлинг CC до 30 Hz с сохранением финального значения (`flush()`)
2. **`cc_map.py`** — логические имена параметров → номера CC по портам, с инверсией и диапазоном

Плюс интеграция в конфиг и `MidiPortOutput`.

---

## Контекст из плана v5.4

### Проблема: CC забивает DIN-шину (раздел 3.4)

| | CC | msg/s | Полоса DIN |
|---|---|---|---|
| Сырой поток | 3 840 | 377.6 | **53.9%** |
| После троттлинга 30 Hz | **93** | 9.1 | **1.3%** |

> DIN MIDI 31 250 бит/с, CC = 30 бит, практический потолок ≈ 700 сообщений/сек.
> Троттлинг обязателен, не опция.

### Проблема: номера CC различаются у синтов (раздел 2.4)

Генератор оперирует **именами** (`filter`, `resonance`, `reverb`), номер подставляется при отправке — по порту. Пример из плана:

```
генератор:  {"control": "filter", "value": 30..110, "duration": 16}
                              ↓
routing:    filter + Синт B → CC 74
            filter + Синт A → CC 22
                              ↓
mido:       control_change(control=74, value=..., channel=...)
```

---

## Архитектура

```
src/sync/
├── throttle.py          # CCTrottle — троттлинг 30 Hz
├── cc_map.py            # CCMap, CCMapConfig — логические имена → CC
├── cc_map_entry.py      # CCMapEntry — одна запись (cc, invert, range)
├── routing.py           # MidiPortOutput — добавить control() с маппингом
└── ports.py             # PortConfig — добавить _no_automation флаг
```

### Слои

```
cc_map.py          ← не зависит от midi/ (чистая логика маппинга)
throttle.py        ← зависит от midi/abc.py (MidiCC, MidiValue)
routing.py         ← зависит от cc_map.py + throttle.py + midi/
config.py          ← зависит от cc_map.py (CCMapConfig)
```

Никаких циклов. `cc_map.py` — нижний слой, `routing.py` — верхний.

---

## Шаг 1: `../src/sync/cc_map_entry.py` — запись маппинга

Одна запись: логическое имя → номер CC + опции.

```python
@dataclass(frozen=True)
class CCMapEntry:
    """Resolved CC mapping entry for one logical parameter on one port."""
    cc: MidiCC                    # номер CC (0–127)
    invert: bool = False          # 0 = ярко, 127 = глухо
    range: tuple[int, int] = (0, 127)  # кламп диапазона
```

**Валидация в `__post_init__`**:
- `range[0] < range[1]` (строго)
- `range[0] >= 0`, `range[1] <= 127`
- `cc` — валидный `MidiCC` (0–127)

**Метод**:
- `transform(value: int) -> int` — применить инверсию и диапазон к нормализованному 0–127

```python
def transform(self, value: int) -> int:
    """Map a normalized 0–127 value through invert + range."""
    if self.invert:
        value = 127 - value
    lo, hi = self.range
    return lo + round(value * (hi - lo) / 127)
```

**Тесты**: прямое отображение, инверсия, диапазон, инверсия+диапазон, граничные значения (0→lo, 127→hi), ошибки валидации.

---

## Шаг 2: `../src/sync/cc_map.py` — маппинг имён → CC

### Конфиг-схема (Pydantic)

```python
class CCParamOverride(BaseModel):
    """Per-port override for one logical parameter."""
    cc: int = Field(ge=0, le=127)
    invert: bool = False
    range: tuple[int, int] = (0, 127)  # валидация: lo < hi

class CCMapConfig(BaseModel):
    """CC mapping configuration."""
    default: dict[str, int] = Field(default_factory=dict)       # имя → CC
    ports: dict[str, dict[str, CCParamOverride | int]] = Field(default_factory=dict)
    # ports["Имя порта"]["filter"] = 74  или  CCParamOverride(cc=74, invert=True)
```

**Валидация при загрузке**:
- Все имена в `default` — str, не пустые, уникальные (dict гарантирует)
- Все значения в `default` — int 0–127
- Все порты в `ports` — str, не пустые
- Все имена внутри порта — существуют в `default` (иначе ошибка: «параметр X не определён в default»)
- `_no_automation: true` — специальный ключ порта, пропускается при валидации имён

### CCMap (runtime)

```python
class CCMap:
    """Resolves logical parameter names to CC numbers per port."""

    def __init__(self, config: CCMapConfig) -> None: ...

    def resolve(self, port_label: str, param_name: str) -> CCMapEntry | None:
        """Resolve logical name to CC entry for a specific port.

        Returns None if the port has _no_automation or param not found.
        Raises CCMapError if param not in default and not in port.
        """

    def is_automation_enabled(self, port_label: str) -> bool:
        """Check if port accepts CC automation (not _no_automation)."""

    def known_params(self) -> frozenset[str]:
        """All known logical parameter names."""
```

### Правила разрешения

| Ситуация | Поведение |
|---|---|
| Порт имеет `CCParamOverride` для параметра | берётся override (cc, invert, range) |
| Порт имеет `int` для параметра | берётся номер, invert=False, range=(0,127) |
| Порт не переопределил, `default` имеет | берётся default |
| Параметра нет нигде | **CCMapError** — не тихий пропуск |
| Порт имеет `_no_automation: true` | `resolve()` → `None`, `is_automation_enabled()` → `False` |

### Конфиг по умолчанию (DEFAULT_CONFIG_YAML)

```yaml
cc_map:
  default:
    filter:         74
    resonance:      71
    reverb:         91
    delay:          93
    delay_feedback: 94
    mod_wheel:       1
    volume:          7
    pan:            10
  ports: {}
```

**Тесты**:
- Разрешение по умолчанию (default → CCMapEntry)
- Переопределение по порту (int и CCParamOverride)
- Инверсия и диапазон через CCParamOverride
- `_no_automation` → `resolve()` = None
- Неизвестный параметр → CCMapError
- Параметр в `ports` но не в `default` → ошибка валидации
- `known_params()` возвращает все имена из default

---

## Шаг 3: `../src/sync/throttle.py` — троттлинг CC

### Принцип

Все CC, приходящие чаще 30 Hz, схлопываются: берётся последнее значение. При `flush()` — принудительная отправка накопленного.

### API

```python
@dataclass(frozen=True)
class CCKey:
    """Throttle key: (port_label, channel, cc)."""
    port: str
    channel: MidiChannel
    cc: MidiCC

@dataclass(frozen=True)
class CCEvent:
    """A throttled CC event ready for delivery."""
    key: CCKey
    value: MidiValue

class CCThrottle:
    """Rate-limits CC messages to max_rate Hz per (port, channel, cc) key.

    Non-thread-safe. Designed for single-threaded event loop (transport).
    """

    def __init__(self, max_rate_hz: float = 30.0) -> None:
        ...

    def submit(
        self,
        port: str,
        channel: int,
        cc: int,
        value: int,
    ) -> list[CCEvent]:
        """Submit a CC value. Returns events to send NOW (may be empty).

        If the key was sent less than 1/max_rate ago, the value is stored
        as pending and empty list is returned. Otherwise returns the event.
        """

    def flush(self) -> list[CCEvent]:
        """Force-send all pending values. Call at end of tick/bar."""

    def pending_count(self) -> int:
        """Number of keys with unsent pending values."""

    def reset(self) -> None:
        """Clear all pending values (e.g., on panic/all_notes_off)."""
```

### Логика `submit()`

```
key = (port, channel, cc)
now = time.monotonic()

if key not in _last_sent:
    _last_sent[key] = now
    return [CCEvent(key, value)]

elapsed = now - _last_sent[key]
if elapsed >= 1/max_rate:
    _last_sent[key] = now
    return [CCEvent(key, value)]

# Слишком часто — сохранить как pending
_pending[key] = value
return []
```

### Логика `flush()`

```
events = [CCEvent(k, v) for k, v in _pending.items()]
_pending.clear()
for k in events: _last_sent[k.key] = now
return events
```

### Ключевые свойства

- **Не потокобезопасен** — работает в одном потоке транспорта (как указано в плане v5.4: "throttle.py — не зависит от клока")
- **Ключ = (порт, канал, разрешённый_CC)** — две дорожки, пришедшие к одному CC через разные имена, делят один троттлер
- **`flush()` гарантирует доставку финала** — свип не обрывается на предпоследнем значении
- **`reset()`** — при `all_notes_off()` / панике сбрасывает pending

**Тесты**:
- Первый `submit()` → сразу отправляет
- Быстрые `submit()` → пустой список, значение в pending
- `submit()` после интервала → отправляет
- `flush()` → отправляет все pending, очищает
- `flush()` при пустом pending → пустой список
- Разные ключи независимы
- `reset()` → pending_count() == 0
- Проверка что финальное значение совпадает с последним submit

---

## Шаг 4: Интеграция в `MidiPortOutput` (routing.py)

### Добавить зависимости в конструктор

```python
class MidiPortOutput:
    def __init__(
        self,
        label: str,
        port: MidiOutPort,
        cc_map: CCMap | None = None,
        throttle: CCThrottle | None = None,
    ) -> None:
        self.label = label
        self._port = port
        self._cc_map = cc_map
        self._throttle = throttle
```

### Новый метод `control()`

```python
def control(self, param_name: str, channel: int, value: int) -> None:
    """Send CC by logical parameter name with mapping + throttling.

    Resolves param_name → CC number via CCMap, transforms value
    (invert + range), submits to throttle. If throttle defers,
    the value will be sent on next flush().

    Silently ignores if:
    - cc_map is None (no mapping configured)
    - port has _no_automation
    - param not found (logged as warning)
    """
```

### Модифицировать `control_change()`

Существующий `control_change(channel, control, value)` остаётся для прямой отправки (без маппинга, без троттлинга). Используется для служебных CC (all_notes_off = CC 123).

### Добавить `flush()`

```python
def flush(self) -> None:
    """Send all pending throttled CC values."""
    if self._throttle is None:
        return
    for event in self._throttle.flush():
        self._port.send(MidiMessage.cc(
            channel=int(event.key.channel),
            control=int(event.key.cc),
            value=int(event.value),
        ))
```

### Добавить `all_notes_off()` сброс троттлера

```python
def all_notes_off(self) -> None:
    for ch in range(16):
        self._port.send(MidiMessage.cc(channel=ch, control=123, value=0))
    if self._throttle is not None:
        self._throttle.reset()
```

**Тесты**:
- `control()` с маппингом → правильный CC номер отправлен
- `control()` с инверсией → значение перевернуто
- `control()` с диапазоном → значение в диапазоне
- `control()` на `_no_automation` порту → ничего не отправлено
- `control()` с несуществующим именем → warning, ничего не отправлено
- Быстрые `control()` → троттлинг, `flush()` → финальное значение
- `control_change()` напрямую → работает без маппинга/троттлинга
- `all_notes_off()` → сбрасывает троттлер

---

## Шаг 5: Интеграция в `PortRegistry`

### Обновить `_open_port()`

При создании `MidiPortOutput` передавать `cc_map` и `throttle`:

```python
def _open_port(self, label: str, config: PortConfig) -> MidiPortOutput:
    port = self._factory()
    port.open(config.match)
    return MidiPortOutput(
        label=label,
        port=port,
        cc_map=self._cc_map,
        throttle=self._throttle,
    )
```

### Добавить `flush_all()`

```python
def flush_all(self) -> None:
    """Flush pending CC on all active ports."""
    for output in self._outputs.values():
        output.flush()
```

### Добавить `flush_port(label)`

```python
def flush_port(self, label: str) -> None:
    """Flush pending CC on a specific port."""
```

**Тесты**:
- Открытый порт получает cc_map и throttle
- `flush_all()` вызывает flush на всех портах
- `flush_port()` вызывает flush на конкретном порту

---

## Шаг 6: Конфигурация

### `../src/config.py`

```python
from src.sync.cc_map import CCMapConfig

class AppConfig(BaseModel):
    ...
    cc_map: CCMapConfig = Field(default_factory=CCMapConfig)
```

### `../config.yaml` — добавить секцию

```yaml
cc_map:
  default:
    filter:         74
    resonance:      71
    reverb:         91
    delay:          93
    delay_feedback: 94
    mod_wheel:       1
    volume:          7
    pan:            10
  ports: {}
```

### `../src/app/config.py` — `LoadedConfig`

```python
@dataclass(frozen=True)
class LoadedConfig:
    ...
    cc_map_config: CCMapConfig = field(default_factory=CCMapConfig)
```

### `../src/app/application.py`

При инициализации `PortRegistry` передать `CCMap` и `CCThrottle`:

```python
def _init_port_registry(self) -> None:
    cc_map = CCMap(self._config.cc_map_config)
    throttle = CCThrottle(max_rate_hz=30.0)
    self._port_registry = PortRegistry(
        factory=create_out_port,
        cc_map=cc_map,
        throttle=throttle,
    )
```

---

## Шаг 7: `PortConfig` — флаг `_no_automation`

### В `../src/sync/ports.py`

```python
class PortConfig(BaseModel):
    """Configuration for a single MIDI port."""
    match: str
    serial: str | None = None
    _no_automation: bool = False  # не отправлять CC-автоматизацию
```

Или через `model_config = ConfigDict(extra="allow")` если нужно сохранить неизвестные ключи.

**Тесты**:
- Порт с `_no_automation: true` → `CCMap.resolve()` → None
- Порт без флага → обычное поведение

---

## Файлы для создания/изменения

| Файл | Действие | Описание |
|------|----------|----------|
| `../src/sync/cc_map_entry.py` | **Создать** | `CCMapEntry` — одна запись маппинга |
| `../src/sync/cc_map.py` | **Создать** | `CCMap`, `CCMapConfig`, `CCParamOverride`, `CCMapError` |
| `../src/sync/throttle.py` | **Создать** | `CCThrottle`, `CCKey`, `CCEvent` |
| `../src/sync/routing.py` | **Изменить** | Добавить `control()`, `flush()`, интегрировать throttle |
| `../src/sync/ports.py` | **Изменить** | Добавить `_no_automation` в `PortConfig` |
| `../src/config.py` | **Изменить** | Добавить `cc_map: CCMapConfig` в `AppConfig` |
| `../src/app/config.py` | **Изменить** | Добавить `cc_map_config` в `LoadedConfig` |
| `../src/app/application.py` | **Изменить** | Создать CCMap + CCThrottle, передать в PortRegistry |
| `../config.yaml` | **Изменить** | Добавить секцию `cc_map:` |
| `../tests/test_cc_map.py` | **Создать** | Тесты маппинга |
| `../tests/test_cc_map_entry.py` | **Создать** | Тесты CCMapEntry |
| `../tests/test_throttle.py` | **Создать** | Тесты троттлинга |
| `../tests/test_routing.py` | **Изменить** | Дополнить тестами control()/flush() |
| `../tests/test_ports.py` | **Изменить** | Дополнить тестами _no_automation |

---

## Порядок реализации

```
Шаг 1: cc_map_entry.py      (нет зависимостей)
Шаг 2: cc_map.py            (зависит от Шаг 1)
Шаг 3: throttle.py          (зависит от midi/abc.py — уже есть)
Шаг 4: routing.py           (зависит от Шаги 2, 3)
Шаг 5: PortRegistry         (зависит от Шаг 4)
Шаг 6: Конфигурация         (зависит от Шаги 2, 3)
Шаг 7: PortConfig           (можно параллельно с Шагами 4–6)
```

Шаги 1–3 независимы, можно делать параллельно.
Шаги 4–6 зависят от 1–3.

---

## Критерии приёмки

- [ ] `CCMapEntry.transform()` корректно применяет invert + range
- [ ] `CCMap.resolve()` разрешает имена по default и per-port
- [ ] Неизвестный параметр → `CCMapError`, не молчание
- [ ] `_no_automation` порты игнорируют CC
- [ ] `CCThrottle.submit()` схлопывает частые значения до 30 Hz
- [ ] `CCThrottle.flush()` отправляет финальное значение серии
- [ ] `MidiPortOutput.control()` работает с маппингом + троттлингом
- [ ] `MidiPortOutput.control_change()` работает напрямую (без маппинга)
- [ ] `all_notes_off()` сбрасывает троттлер
- [ ] Конфиг загружается и валидируется через pydantic
- [ ] Все тесты passed
- [ ] ruff / mypy / black чисто

---

## Риски и митигация

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| `flush()` не вызывается → последнее значение не доходит | Средняя | `flush()` вызывать в конце каждого тика транспорта (B4) |
| Два имени → один CC → двойная отправка | Средняя | Ключ троттлера = `(порт, канал, CC)`, не имя |
| Инверсия забыта → свип в обратную сторону | Низкая | Тест на `transform()` с invert=True |
| Параметр не в default → тихий пропуск | Закрыто | `CCMapError` при загрузке |
| `spike_cc_throttle.py` потерян | — | Писать с нуля по спецификации из плана v5.4 |

---

## Заметки

- `spike_cc_throttle.py` **отсутствует** в репозитории — код спайка не перенесён из оригинального проекта. Реализация пишется с нуля по числам из плана (3840 → 93 CC).
- `MidiPortOutput.control_change()` уже существует — он нужен для служебных CC (all_notes_off). Новый метод `control()` — для логических имён.
- `CCThrottle` не потокобезопасен by design — он работает в однопоточном цикле транспорта (B4).
- Интеграция с `transport.py` / `capture.py` (вызов `flush()` каждый тик) — задача B4, не B3.
