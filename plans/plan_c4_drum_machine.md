# План C4: Drum-машина — расширенный план

> Источник: `../push2_dubtechno_plan_v5_4.md` §4.2, `track-hierarchy.md` §4, `AGENTS.md`
> Дата: 2026-11-01
> Зависимости: C3 (Track, DrumTrack, DrumLane, Session) — ✅ завершено
> Связи: C5 (мутация), B4 (транспорт), D3 (пады DRUM-режим)

---

## 1. Что уже сделано (C3 оставил заглушки)

| Компонент                     | Файл                        | Состояние                                                                                 |
|-------------------------------|-----------------------------|-------------------------------------------------------------------------------------------|
| `DrumTrack`                   | `src/session/drum_track.py` | ✅ Класс, 16 лейнов, `sources` заблокирован, `step_to_note()` — **заглушка `generate()`** |
| `DrumLane`                    | `src/session/drum_lane.py`  | ✅ Dataclass: `note`, `name`, `pattern[16]` (0/1/2), `muted`                              |
| `Session.create_drum_track()` | `../src/session/session.py`    | ✅ Создание, лимит ≤ 2, автонейминг "Drum 1"                                              |
| GM-карта 36–51                | `src/session/drum_track.py` | ✅ `_GM_DRUM_MAP` — 16 записей                                                            |
| Транспорт (B4)                | `../src/sync/transport.py`     | ✅ `TransportEvent`, `CaptureOutput`, `Transport.process_events()`                        |
| Свинг (B4)                    | `../src/sync/swing.py`         | ✅ `SwingApplier` — работает через длительности, применяется ко всем дорожкам             |
| CC-троттлинг (B3)             | `../src/sync/throttle.py`      | ✅ `CCThrottle` 30 Hz + `flush()`                                                         |

**Чего нет (делает C4):**

1. Генерация drum-паттерна — `DrumTrack.generate()` сейчас очищает outbox
2. isobar-интеграция — нет связи между `DrumTrack` и `Timeline`
3. Евклидовы ритмы — `PEuclidean` не используется
4. Мутация drum-машины — нет дрейфа, нет деградации
5. Velocity-уровни — три уровня (ghost/normal/accent) не реализованы
6. Drum-события в транспорте — нет маршрутизации drum-нот через `CaptureOutput`
7. Конфигурация drum — `preview_on_select`, `preview_velocity` не в конфиге

---

## 2. Архитектура: что строим

### 2.1. Принцип: drum — это генератор, не получатель

```
┌──────────────────────────────────────────────────────────┐
│  DrumTrack (session/)                                    │
│  ├── lanes: list[DrumLane]        ← данные (уже есть)   │
│  ├── generate()                   ← СТРОИТ isobar-паттерн│
│  │   └── возвращает list[DrumEvent]                      │
│  └── mutate / accent_level / square  ← параметры (уже)  │
├──────────────────────────────────────────────────────────┤
│  DrumEvent (session/drum_event.py)   ← НОВЫЙ             │
│  ├── beat: float                                         │
│  ├── note: int              (GM 36–51)                   │
│  ├── velocity: int          (40–127)                     │
│  ├── lane_index: int        (0–15)                       │
│  └── duration: float        (в долях)                    │
├──────────────────────────────────────────────────────────┤
│  DrumEngine (session/drum_engine.py)  ← НОВЫЙ            │
│  ├── Владеет isobar Timeline                             │
│  ├── Конвертирует DrumEvent → TransportEvent             │
│  └── Применяет свинг к drum-паттерну                     │
├──────────────────────────────────────────────────────────┤
│  PEuclideanCached (session/euclidean.py)  ← НОВЫЙ        │
│  └── Обёртка с кешем до смены mod/length                 │
└──────────────────────────────────────────────────────────┘
```

### 2.2. Почему DrumEvent отдельно от ChordEvent

`ChordEvent` — гармоническая единица (ступени, войсинг, лад). `DrumEvent` — ритмическая единица (абсолютная нота,
velocity, lane). Они не взаимозаменяемы:

- `DrumTrack` не публикует `ChordEvent` (уже гарантировано C3)
- `MelodicTrack` не публикует `DrumEvent`
- Транспорт обрабатывает оба типа по-разному (drum → note_on/note_off, melodic → degree → note)

---

## 3. Пошаговая реализация

### Шаг 1: `DrumEvent` — value object

**Файл:** `src/session/drum_event.py`

```python
@dataclass(frozen=True)
class DrumEvent:
    """Одно drum-событие — удар на конкретном шаге сетки."""
    beat: float  # позиция в тактах
    note: int  # GM-номер 36–51
    velocity: int  # 0–127
    lane_index: int  # 0–15
    duration: float  # длительность в долях (для свинга)
```

**Тесты:** `../tests/test_drum_event.py`

- frozen dataclass
- поля корректны

---

### Шаг 2: `PEuclideanCached` — обёртка с кешем

**Файл:** `src/session/euclidean.py`

**Проблема:** `PEuclidean` в isobar пересчитывает алгоритм Бьорклунда **каждый тик** (поле `self.sequence` объявлено, но
не используется). При 16 lane × 480 PPQN это 7680 пересчётов в секунду.

**Решение:** кешировать результат до смены `mod` или `length`.

```python
class PEuclideanCached:
    """PEuclidean с кешем — пересчёт только при смене mod/length.

    Использование:
        eucl = PEuclideanCached(steps=16, pulses=4)
        pattern = eucl.pattern  # вычисляется один раз
        # ... 1000 тиков ...
        eucl.pulses = 5         # инвалидирует кеш
        pattern = eucl.pattern  # пересчёт
    """

    def __init__(self, steps: int, pulses: int) -> None:
        self._steps = steps
        self._pulses = pulses
        self._cached: list[int] | None = None

    @property
    def pattern(self) -> list[int]:
        """Кешированный паттерн (0/1 на каждый шаг)."""
        if self._cached is None:
            self._cached = self._compute()
        return self._cached

    @property
    def pulses(self) -> int:
        return self._pulses

    @pulses.setter
    def pulses(self, value: int) -> None:
        if value != self._pulses:
            self._pulses = value
            self._cached = None  # инвалидация

    def _compute(self) -> list[int]:
        """Алгоритм Бьорклунда."""
        ...
```

**Важно:** не вызывать `repr()` на isobar `PEuclidean` — баг в isobar (`self.phase` vs `self.pos` → `AttributeError`).

**Тесты:** `../tests/test_euclidean.py`

- паттерн корректен для известных пар (steps/pulses)
- кеш работает: повторный доступ не пересчитывает
- смена `pulses` инвалидирует кеш
- граничные случаи: pulses=0, pulses=steps

---

### Шаг 3: `DrumTrack.generate()` — реальная генерация

**Файл:** `src/session/drum_track.py` (заменить заглушку)

**Что делает:**

```python
def generate(self) -> list[DrumEvent]:
    """Сгенерировать drum-события по сетке.

    Алгоритм:
    1. Для каждого lane (0..15):
       a. Если muted → skip
       b. Получить паттерн из lane.pattern (0/1/2 на каждый шаг)
       c. Для каждого шага сетки (0..steps-1):
          - pattern[step % len(pattern)] == 0 → skip (пауза)
          - == 1 → velocity = normal (90–100)
          - == 2 → velocity = accent (120–127)
    2. Собрать все события, отсортировать по beat
    3. Применить mutate (если > 0) — мутирует паттерн, не события
    """
```

**Ключевые правила из плана §4.2:**

| Правило             | Реализация                                  |
|---------------------|---------------------------------------------|
| Абсолютные ноты     | `note` из `_GM_DRUM_MAP`, не через `Key`    |
| Лад не применяется  | не обращаемся к `Harmony`                   |
| Gate one-shot       | фиксированная короткая длительность         |
| Пауза = amplitude 0 | шаг 0 в паттерне → событие не создаётся     |
| Три уровня velocity | 0=skip, 1=normal(90–100), 2=accent(120–127) |
| Полиметр отключён   | одна сетка `self.steps` на все lane         |
| Свой канал          | `self.channel` (по умолчанию 9 = ch10)      |

**Velocity-уровни:**

```python
VELOCITY_GHOST: tuple[int, int] = (40, 55)
VELOCITY_NORMAL: tuple[int, int] = (90, 100)
VELOCITY_ACCENT: tuple[int, int] = (120, 127)
```

Уровень из паттерна (0/1/2) → диапазон → конкретное значение через `rng.randint()`.

**Мутация (в `generate()` или отдельный метод):**

```python
def _apply_mutation(self) -> None:
    """Мутировать паттерн — 1–2 изменения за 8–16 секунд.

    Правила из плана §4.2:
    - Интервал от времени (секунды), не от тактов
    - uniform(8, 16) — нерегулярность окна
    - Деградация: с вероятностью `mutate` откатываем к базовому
    - Счётчик изменений на дисплее
    """
```

**Формула интервала мутации:**

```python
MUTATE_MIN_SECONDS: float = 8.0
MUTATE_MAX_SECONDS: float = 16.0


def _next_mutation_beat(self, bpm: float) -> float:
    seconds = self.rng.uniform(MUTATE_MIN_SECONDS, MUTATE_MAX_SECONDS)
    beats = seconds * bpm / 60.0
    return self._last_mutation_beat + beats
```

**Тесты:** `../tests/test_drum_track.py`

- `generate()` возвращает `list[DrumEvent]`
- muted lane не генерирует событий
- паттерн 0/1/2 → правильные velocity-диапазоны
- `steps=32` → события на шагах 0..31
- смена Root/Scale не влияет (drum не использует Harmony)
- мутация: `mutate=0` → паттерн не меняется
- мутация: `mutate=1` → паттерн меняется через 8–16 секунд
- деградация: после N мутаций паттерн возвращается к базовому

---

### Шаг 4: `DrumEngine` — мост между DrumTrack и транспортом

**Файл:** `src/session/drum_engine.py`

**Задача:** взять `list[DrumEvent]` от `DrumTrack.generate()`, сконвертировать в `TransportEvent`, положить в очередь.

```python
class DrumEngine:
    """Движок drum-машины — мост между DrumTrack и Transport.

    Владеет isobar Timeline (один на всю сессию).
    На каждом тике:
    1. Проверить, пора ли регенерировать (начало нового цикла сетки)
    2. Вызвать drum_track.generate()
    3. Конвертировать DrumEvent → TransportEvent
    4. Положить в event_queue
    """

    def __init__(
            self,
            drum_track: DrumTrack,
            event_queue: queue.Queue[TransportEvent],
            port_label: str,
            swing: SwingApplier,
    ) -> None:
        ...

    def tick(self, current_beat: float) -> None:
        """Вызывается из TickProxy dispatch hook."""
        ...
```

**Почему не напрямую в `Transport`:** `Transport` — универсальный доставщик. Он не знает про drum-сетки, евклидовы
ритмы, мутацию. `DrumEngine` — специализированный генератор, который кормит `Transport`.

**Свинг:** применяется к `DrumEvent.duration` через `SwingApplier.apply_duration()`, как у мелодических дорожек.

**Тесты:** `../tests/test_drum_engine.py`

- `tick()` при пустом паттерне → нет событий в очереди
- `tick()` с паттерном → TransportEvent в очереди
- свинг применяется к длительностям
- `all_notes_off()` очищает очередь и шлёт CC 123

---

### Шаг 5: Интеграция в Application

**Файл:** `../src/app/application.py`

```python
def _init_drum_engine(self, session: Session) -> None:
    """Создать DrumEngine для каждой DrumTrack в сессии."""
    for track in session.ordered_tracks():
        if isinstance(track, DrumTrack):
            engine = DrumEngine(
                drum_track=track,
                event_queue=self._event_queue,
                port_label=track.port or "default",
                swing=self._swing,
            )
            self._drum_engines.append(engine)
```

**Hook в TickProxy dispatch:**

```python
def hooked_dispatch(event):
    if event.name == "TICK":
        cm.on_tick()
        for engine in self._drum_engines:
            engine.tick(timeline.current_time)
    original_dispatch(event)
    if event.name == "TICK":
        capture.beat = timeline.current_time
        transport.process_events(current_beat=timeline.current_time)
```

---

### Шаг 6: Конфигурация drum

**Файл:** `../src/config.py` — добавить секцию `drum:`

```python
class DrumConfig(BaseModel):
    """Конфигурация drum-машины."""
    preview_on_select: bool = True  # предпрослушка lane при выборе
    preview_velocity: int = 100  # velocity предпрослушки
    mutate_min_seconds: float = 8.0  # минимум между мутациями
    mutate_max_seconds: float = 16.0  # максимум между мутациями
```

**Файл:** `../config.yaml` — добавить:

```yaml
drum:
  preview_on_select: true
  preview_velocity: 100
  mutate_min_seconds: 8.0
  mutate_max_seconds: 16.0
```

---

## 4. Что НЕ делает C4 (явные границы)

| Не делает                            | Почему                        | Кто делает |
|--------------------------------------|-------------------------------|------------|
| Пады DRUM-режим (UI)                 | UI — план D                   | D3         |
| Экран drum-сетки                     | UI — план D                   | D2         |
| Предпрослушка lane (звук)            | Нужен UI для выбора lane      | D3         |
| Мутация мелодических дорожек         | Отдельная задача              | C5         |
| Freeze/Evolve (глобальная заморозка) | Касается всех дорожек         | C5         |
| Полиметр (разные сетки на lane)      | Запрещён планом §4.2          | —          |
| Звуки drum (сэмплы, синтез)          | MIDI-хост, не звуковой движок | —          |
| Drum из audio (сайдчейн)             | Не MIDI                       | —          |

---

## 5. Тесты: полный список

| Файл                  | Тестов  | Что проверяет                                    |
|-----------------------|---------|--------------------------------------------------|
| `test_drum_event.py`  | 3       | frozen, поля, конвертация в TransportEvent       |
| `test_euclidean.py`   | 8       | паттерн, кеш, инвалидация, границы               |
| `test_drum_track.py`  | 15      | generate(), velocity, мутация, деградация, steps |
| `test_drum_engine.py` | 10      | tick(), очередь, свинг, all_notes_off            |
| `test_drum_config.py` | 4       | дефолты, валидация, YAML                         |
| **Итого**             | **~40** |                                                  |

---

## 6. Файлы: создание и изменение

### Новые файлы

```
src/session/drum_event.py       # DrumEvent — value object
src/session/euclidean.py         # PEuclideanCached — обёртка с кешем
src/session/drum_engine.py       # DrumEngine — мост в транспорт
tests/test_drum_event.py
tests/test_euclidean.py
tests/test_drum_track.py         # заменит/дополнит существующие drum-тесты
tests/test_drum_engine.py
tests/test_drum_config.py
```

### Изменяемые файлы

```
src/session/drum_track.py        # generate() — реальная генерация
src/session/drum_lane.py         # + методы для мутации паттерна
src/config.py                    # + DrumConfig
config.yaml                      # + секция drum:
src/app/application.py           # + _init_drum_engine()
```

---

## 7. Порядок реализации

```
Шаг 1: DrumEvent          ← нет зависимостей
Шаг 2: PEuclideanCached   ← нет зависимостей
Шаг 3: DrumTrack.generate() ← зависит от 1, 2
Шаг 4: DrumEngine         ← зависит от 3, B4 (Transport)
Шаг 5: Application        ← зависит от 4
Шаг 6: Config             ← независим, можно параллельно с 1–5
```

Шаги 1 и 2 — параллельно.
Шаг 6 — параллельно с 1–5.

---

## 8. Критерии готовности

- [ ] `DrumTrack.generate()` возвращает `list[DrumEvent]` по сетке
- [ ] Три уровня velocity: ghost (40–55), normal (90–100), accent (120–127)
- [ ] `PEuclideanCached` не пересчитывает при неизменных mod/length
- [ ] Мутация: 1–2 изменения за 8–16 секунд, деградация к базовому
- [ ] `DrumEngine` кормит `TransportEvent` в очередь транспорта
- [ ] Свинг применяется к drum-длительностям
- [ ] `mutate = 0` — полная заморозка паттерна
- [ ] Смена Root/Scale не влияет на drum
- [ ] Muted lane не генерирует событий
- [ ] `all_notes_off()` останавливает все drum-ноты
- [ ] ~40 тестов passed
- [ ] ruff / mypy / black чисто

---

## 9. Риски и митигация

| Риск                                  | Вероятность | Митигация                                         |
|---------------------------------------|-------------|---------------------------------------------------|
| `PEuclidean` без кеша — CPU взлетает  | Высокая     | `PEuclideanCached` — обязательный, не опция       |
| `repr(PEuclidean)` → `AttributeError` | Средняя     | Не вызывать `repr()`, своя обёртка                |
| Мутация уводит грув необратимо        | Средняя     | Деградация к базовому, `mutate=0`                 |
| `numpy.int64` ломает mido             | Высокая     | `int()` в `DrumEngine` при конвертации            |
| Drum-ноты лезут в граф гармонии       | Низкая      | `sources` заблокирован (C3), тест есть            |
| 16 lane × 32 steps = 512 событий/тик  | Низкая      | События только на активных шагах, паузы бесплатны |
