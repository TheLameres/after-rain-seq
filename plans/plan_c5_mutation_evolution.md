# План C5: Мутация и эволюция — расширенный план

> Источник: `../push2_dubtechno_plan_v5_4.md` §4.2, §4.3, §4.4, §4.5, §5, §6, §7, §8,
> `track-hierarchy.md` §3, §4, §7, `AGENTS.md`
> Дата: 2026-11-01
> Зависимости: C1 (Harmony, Voicing) — ✅, C3 (Track, MelodicTrack, Session) — ✅,
> C4 (DrumTrack с мутацией, DrumEngine, PEuclideanCached) — ✅
> Связи: D2 (экраны — счётчик мутаций), D3 (пады MORPH-режим), E2 (8-часовой прогон)

---

## 1. Что уже сделано (C4 оставил как фундамент)

| Компонент | Файл | Состояние |
|-----------|------|-----------|
| DrumTrack мутация | `src/session/drum_track.py` | ✅ Интервал 8–16 с, 1–2 изменения, деградация, freeze(), счётчик |
| PEuclideanCached | `src/session/euclidean.py` | ✅ Кеш, сеттер pulses с инвалидацией |
| DrumEngine | `src/session/drum_engine.py` | ✅ Мост DrumTrack → TransportEvent, свинг |
| TransportEvent | `../src/sync/transport_event.py` | ✅ NOTE_ON/OFF, CC, ALL_NOTES_OFF |
| Transport | `../src/sync/transport.py` | ✅ Доставка, свинг, CC flush, all_notes_off |
| SwingApplier | `../src/sync/swing.py` | ✅ Длительностный свинг, авто-ресет |
| Harmony | `../src/harmony/harmony.py` | ✅ degree_to_note, set_root/set_scale |
| Voicing | `../src/harmony/voicings.py` | ✅ VOICINGS, invert, chord_degrees/notes |
| MelodicTrack | `src/session/melodic_track.py` | ✅ Профили, ChordEvent, граф — **нет мутации** |
| MelodicProfile | `src/session/melodic_profile.py` | ✅ 11 профилей — **нет mutation-параметров** |
| Session | `../src/session/session.py` | ✅ CRUD дорожек, граф — **нет freeze/evolve** |
| App интеграция | `../src/app/application.py` | ✅ DrumEngine в dispatch hook — **нет melodic engine** |

**Чего нет (делает C5):**

1. **Мутация мелодических дорожек** — MelodicTrack не имеет `mutate`, `_rng`, дрейфа параметров
2. **`mutation.py`** — единый модуль мутации, перечисленный в плане §5 как часть Engine-слоя
3. **Freeze/Evolve (глобальный)** — Session не имеет методов заморозки/разморозки всех дорожек
4. **Счётчик мутаций на дисплее** — DrumTrack.mutation_count есть, но нет агрегированного API
5. **Плавающий PEuclidean** — евклидовы параметры (pulses) не дрейфуют во времени
6. **Дрейф диапазонов PWhite** — параметры дорожек (gate, density, register) не эволюционируют
7. **MelodicEngine** — нет моста MelodicTrack → Transport (аналог DrumEngine)
8. **MutationConfig** — нет конфигурации мутации в config.yaml

---

## 2. Архитектура: что строим

### 2.1. Принцип: мутация — независимый слой

План §5.1 явно указывает: `mutation.py (дрейф)` — **clock-independent**. Мутация не зависит
от источника клока, работает одинаково при internal/MIDI/Link. Это достигается тем, что
мутация оперирует **beats** (позиция в тактах), а не секундами напрямую. Пересчёт
секунды → beats выполняется через `bpm`, который обновляется из ClockManager.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Слой мутации (session/mutation.py)                                  │
│                                                                      │
│  ┌──────────────┐  ┌───────────────────┐  ┌──────────────────────┐   │
│  │ MutationDrift│  │ FloatingEuclidean │  │ ParamDrift (PWhite)  │   │
│  │              │  │                   │  │                      │   │
│  │ Дрейф нот    │  │ pulses дрейфует   │  │ gate, density,       │   │
│  │ lead-профиля │  │ во времени        │  │ register плавно      │   │
│  │ в пределах   │  │ (±1 за мутацию)   │  │ меняют диапазон      │   │
│  │ лада         │  │                   │  │                      │   │
│  └──────────────┘  └──────────────────┘  └──────────────────────┘    │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ MutationEngine                                                │   │
│  │  • Владеет всеми MutationTarget'ами                           │   │
│  │  • tick(current_beat) → проверяет интервал, применяет дрейф   │   │
│  │  • freeze() / evolve() — глобальная заморозка/разморозка      │   │
│  │  • mutation_count — агрегированный счётчик для дисплея        │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  MelodicTrack (session/melodic_track.py) — ДОПОЛНЕНИЕ               │
│                                                                     │
│  + mutate: float = 0.5          # 0 = заморожено                    │
│  + bpm: float = 120.0           # для пересчёта интервала           │
│  + _mutation_state: MutationState                                    │
│  + maybe_mutate(current_beat)   # делегирует в MutationEngine       │
│  + freeze() / mutation_count    # как DrumTrack                     │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  MelodicEngine (session/melodic_engine.py) — НОВЫЙ                  │
│                                                                     │
│  Аналог DrumEngine:                                                   │
│  • tick(current_beat) → maybe_mutate → generate → TransportEvent    │
│  • Конвертация ChordEvent → note_on/note_off через Harmony          │
│  • Свинг к длительностям                                            │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Session (session/session.py) — ДОПОЛНЕНИЕ                          │
│                                                                     │
│  + freeze_all()  → mutate = 0 на всех дорожках                      │
│  + evolve_all()  → mutate = profile_default на всех дорожках        │
│  + total_mutation_count → sum всех дорожек                          │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2. Три механизма мутации

План §6 (Фаза 3) определяет три механизма:

| Механизм | Для кого | Что делает | Класс |
|----------|----------|------------|-------|
| **Непрерывный дрейф** | lead, texture | Ноты плавно перемещаются в пределах лада | `NoteDrift` |
| **Плавающий PEuclidean** | seq, arp | Pulses евклидова паттерна дрейфуют ±1 | `FloatingEuclidean` |
| **Дрейф диапазонов PWhite** | pad, atmos, bass | Gate, density, register плавно меняются | `ParamDrift` |

Каждый механизм — отдельный класс. `MutationEngine` выбирает механизм по профилю дорожки.

### 2.3. Разделение ответственности с DrumTrack

DrumTrack уже имеет встроенную мутацию (C4). C5 **не переписывает** её.
Вместо этого:

- DrumTrack.mutation_count агрегируется в Session.total_mutation_count
- DrumTrack.freeze() вызывается из Session.freeze_all()
- Мутация мелодики — новый код, не переиспользует drum-логику напрямую
- Общий интерфейс: `maybe_mutate(beat) -> bool`, `freeze() -> None`, `mutation_count -> int`

---

## 3. Пошаговая реализация

### Шаг 1: `MutationState` — value object для состояния мутации

**Файл:** `src/session/mutation.py`

```python
@dataclass(frozen=True)
class MutationState:
    """Немутируемый снимок состояния мутации дорожки.

    Атрибуты:
        mutate: Вероятность мутации 0.0–1.0 (0 = заморожено).
        mutation_count: Изменений с последней заморозки.
        next_mutation_beat: Beat следующей мутации.
        last_mutation_beat: Beat последней мутации.
    """
    mutate: float
    mutation_count: int
    next_mutation_beat: float
    last_mutation_beat: float
```

**Зачем:** DrumTrack хранит мутационное состояние в разрозненных полях (`_mutation_count`,
`_last_mutation_beat`, `_next_mutation_beat`). Для мелодических дорожек и MutationEngine
нужен единый объект, который можно передавать, копировать, сравнивать.

**Тесты:** `../tests/test_mutation.py`
- frozen dataclass
- поля корректны
- сравнение двух состояний

---

### Шаг 2: `NoteDrift` — непрерывный дрейф нот

**Файл:** `src/session/mutation.py`

Механизм для `lead` и `texture` профилей. Ноты плавно перемещаются в пределах лада.

```python
class NoteDrift:
    """Дрейф нот в пределах лада — для lead/texture профилей.

    Алгоритм:
    1. Хранит текущую ступень (degree) для каждой позиции паттерна
    2. При мутации: смещает одну ступень на ±1 (в пределах лада)
    3. Деградация: возвращает ступень к базовому значению

    Дрейф ограничен: ступень не выходит за пределы [0, scale_length * 2)
    (две октавы лада). Это предотвращает уход в неслышимые регистры.
    """

    def __init__(self, base_degrees: list[int], scale_length: int = 7) -> None:
        ...

    def drift_one(self, rng: random.Random) -> bool:
        """Сместить одну случайную ступень на ±1. Returns: True если изменилось."""

    def revert_one(self, rng: random.Random) -> bool:
        """Вернуть одну ступень к базовому значению. Returns: True если изменилось."""

    @property
    def current_degrees(self) -> list[int]:
        """Текущие (возможно продугие) ступени."""

    @property
    def drift_count(self) -> int:
        """Сколько ступеней отличается от базы."""
```

**Ключевые решения:**

- Дрейф **в ступенях**, не в полутонах — Harmony резолвит в ноты
- Ограничение двумя октавами лада (14 ступеней для диатоники)
- Смещение ±1 ступень (не ±2) — плавность
- Деградация к базовому рисунку (как DrumTrack)

**Тесты:**
- Дрейф меняет ровно одну ступень
- Дрейф не выходит за границы [0, 2 * scale_length)
- Дрейф при mutate=0 — no-op
- revert_one возвращает к базовому
- drift_count корректно считает отличия

---

### Шаг 3: `FloatingEuclidean` — плавающий PEuclidean

**Файл:** `src/session/mutation.py`

Механизм для `seq` и `arp` профилей. Количество pulses в евклидовом паттерне
медленно дрейфует.

```python
class FloatingEuclidean:
    """Евклидов паттерн с дрейфующим количеством pulses.

    Оборачивает PEuclideanCached. При мутации pulses меняется на ±1
    (в пределах [1, steps-1]). PEuclideanCached автоматически
    инвалидирует кеш при смене pulses.

    Использование:
        fe = FloatingEuclidean(steps=16, base_pulses=4)
        pattern = fe.pattern  # из кеша
        fe.drift(rng)         # pulses может стать 3 или 5
        pattern = fe.pattern  # пересчёт
    """

    def __init__(self, steps: int, base_pulses: int) -> None:
        ...

    def drift(self, rng: random.Random) -> bool:
        """Изменить pulses на ±1. Returns: True если изменилось."""

    def revert(self, rng: random.Random) -> bool:
        """Вернуть pulses к базовому значению."""

    @property
    def pattern(self) -> list[int]:
        """Текущий евклидов паттерн (кешированный)."""

    @property
    def pulses(self) -> int:
        """Текущее количество pulses."""

    @property
    def base_pulses(self) -> int:
        """Базовое количество pulses."""
```

**Ключевые решения:**

- Не создаёт свой алгоритм — переиспользует `PEuclideanCached` (C4)
- Pulses не выходит за [1, steps-1] — всегда есть и активные, и пустые шаги
- Дрейф ±1 за мутацию — плавность
- Деградация возвращает к `base_pulses`

**Тесты:**
- Дрейф меняет pulses на ровно ±1
- Pulses ограничен [1, steps-1]
- revert возвращает к base_pulses
- pattern обновляется после drift
- Кеш работает (не пересчитывает при неизменных pulses)

---

### Шаг 4: `ParamDrift` — дрейф параметров (PWhite-подобный)

**Файл:** `src/session/mutation.py`

Механизм для `pad`, `atmos`, `bass` профилей. Параметры (gate, density, register)
плавно меняют свои значения.

```python
class ParamDrift:
    """Плавный дрейф числовых параметров дорожки.

    Моделирует поведение isobar PWhite: значение блуждает в диапазоне,
    не выходя за границы. Каждая мутация смещает значение на малую
    величину (step), с вероятностью возврата к базовому.

    Поддерживает параметры:
        gate: 0.1–1.0 (длительность ноты)
        density: 0.0–1.0 (плотность паттерна)
        register: -2..+2 (смещение октавы от базовой)
    """

    def __init__(self) -> None:
        self._params: dict[str, _DriftParam] = {}

    def add_param(self, name: str, base: float, lo: float, hi: float, step: float) -> None:
        """Зарегистрировать параметр для дрейфа.

        Аргументы:
            name: Имя параметра (``"gate"``, ``"density"``, ``"register"``).
            base: Базовое значение.
            lo: Нижняя граница.
            hi: Верхняя граница.
            step: Максимальное смещение за одну мутацию.
        """

    def drift_one(self, rng: random.Random) -> str | None:
        """Сместить один случайный параметр. Returns: имя изменённого параметра."""

    def revert_one(self, rng: random.Random) -> str | None:
        """Вернуть один параметр к базовому. Returns: имя параметра."""

    def get(self, name: str) -> float:
        """Текущее значение параметра."""

    @property
    def drift_count(self) -> int:
        """Сколько параметров отличается от базы."""
```

**Внутренний хелпер:**

```python
@dataclass
class _DriftParam:
    """Состояние одного дрейфующего параметра."""
    base: float
    current: float
    lo: float
    hi: float
    step: float
```

**Ключевые решения:**

- Каждый параметр имеет свой `step` (gate: 0.05, density: 0.1, register: 1.0)
- Смещение — равномерное в [-step, +step]
- Границы жёсткие (clamp к [lo, hi])
- Деградация возвращает к `base`

**Тесты:**
- Дрейф не выходит за [lo, hi]
- Дрейф меняет значение не более чем на step
- revert возвращает к base
- Несколько параметров дрейфуют независимо
- drift_count корректен

---

### Шаг 5: `MutationEngine` — координатор мутации

**Файл:** `src/session/mutation.py`

Центральный класс, который владеет всеми механизмами мутации и решает,
какой применить к какой дорожке.

```python
class MutationEngine:
    """Координатор мутации для всех дорожек сессии.

    На каждом тике:
    1. Для каждой дорожки с mutate > 0: проверить, пришло ли время мутации
    2. Выбрать механизм по профилю дорожки
    3. Применить мутацию или деградацию
    4. Обновить MutationState

    Механизм выбирается по профилю:
        lead, texture  → NoteDrift
        seq, arp       → FloatingEuclidean
        pad, atmos, bass → ParamDrift
        drum           → не управляет (DrumTrack сам)
        cc_*           → пропуск (нет нот)
    """

    # Интервал мутации (план §4.2) — в секундах, пересчитывается в beats.
    MUTATE_MIN_SECONDS: float = 8.0
    MUTATE_MAX_SECONDS: float = 16.0

    def __init__(self) -> None:
        self._rng = random.Random()
        self._note_drifts: dict[str, NoteDrift] = {}       # track_name → drift
        self._euclidean_drifts: dict[str, FloatingEuclidean] = {}
        self._param_drifts: dict[str, ParamDrift] = {}
        self._states: dict[str, MutationState] = {}

    def register_track(self, track: MelodicTrack) -> None:
        """Зарегистрировать мелодическую дорожку для мутации.

        Создаёт нужный механизм по профилю, инициализирует MutationState.
        """

    def tick(self, current_beat: float) -> list[str]:
        """Один тик мутации.

        Аргументы:
            current_beat: Текущая позиция в тактах.

        Returns:
            Имена дорожек, которые мутировали на этом тике.
        """

    def freeze_all(self) -> None:
        """Заморозить мутацию на всех зарегистрированных дорожках."""

    def evolve_all(self) -> None:
        """Возобновить мутацию на всех зарегистрированных дорожках."""

    @property
    def total_mutation_count(self) -> int:
        """Суммарное количество мутаций (для дисплея)."""

    def get_state(self, track_name: str) -> MutationState | None:
        """Состояние мутации конкретной дорожки."""
```

**Ключевые решения:**

- Один `MutationEngine` на сессию (не на дорожку)
- Регистрация дорожек — явная (`register_track()`), не автоматическая
- `tick()` возвращает список мутировавших дорожек — для логирования и дисплея
- `freeze_all()` не уничтожает механизмы — только ставит `mutate = 0`
- `evolve_all()` восстанавливает `mutate` к значению по умолчанию (0.5)
- Интервал мутации: `uniform(8, 16)` секунд → beats через `bpm`

**Формула интервала (та же, что DrumTrack):**

```python
def _compute_next_mutation_beat(self, from_beat: float, bpm: float) -> float:
    seconds = self._rng.uniform(self.MUTATE_MIN_SECONDS, self.MUTATE_MAX_SECONDS)
    beats = seconds * bpm / 60.0
    return from_beat + beats
```

**Тесты:**
- Регистрация дорожки создаёт правильный механизм по профилю
- tick() при mutate=0 — no-op
- tick() до интервала — no-op
- tick() после интервала — мутация применена
- freeze_all() → tick() — no-op
- evolve_all() → tick() — мутация возобновляется
- total_mutation_count суммирует все дорожки
- Разные профили получают разные механизмы

---

### Шаг 6: Дополнение `MelodicTrack` — поля мутации

**Файл:** `src/session/melodic_track.py`

Добавить в `MelodicTrack` минимальный интерфейс мутации, совместимый с DrumTrack:

```python
class MelodicTrack(Track):
    """... (существующий код) ..."""

    # Новые поля (в __init__):
    # self.mutate: float = 0.5        # 0 = заморожено
    # self.bpm: float = 120.0         # для пересчёта интервала мутации

    @property
    def mutation_count(self) -> int:
        """Изменений с последней заморозки (делегирует в MutationEngine)."""

    def freeze(self) -> None:
        """Заморозить мутацию (делегирует в MutationEngine)."""
```

**Важно:** MelodicTrack **не владеет** логикой мутации. Он только хранит
`mutate` и `bpm` как публичные поля, которые читает MutationEngine.
Это соответствует принципу: данные — в дорожке, поведение — в движке.

**Тесты:**
- Новые поля имеют дефолты
- mutation_count до регистрации в MutationEngine — 0
- freeze() до регистрации — no-op, не падает

---

### Шаг 7: `MelodicEngine` — мост MelodicTrack → Transport

**Файл:** `src/session/melodic_engine.py`

Аналог DrumEngine. Конвертирует ChordEvent из MelodicTrack.generate()
в TransportEvent (note_on/note_off), резолвя ступени через Harmony.

```python
class MelodicEngine:
    """Движок мелодической дорожки — мост между MelodicTrack и Transport.

    На каждом тике:
    1. Получить ChordEvent из MelodicTrack.generate()
    2. Резолвить degrees → MIDI-ноты через Harmony
    3. Применить gate к длительности
    4. Применить свинг
    5. Конвертировать в TransportEvent, положить в очередь
    """

    def __init__(
        self,
        track: MelodicTrack,
        harmony: Harmony,
        event_queue: queue.Queue[TransportEvent],
        port_label: str,
        swing: SwingApplier,
    ) -> None:
        ...

    def tick(self, current_beat: float) -> int:
        """Один тик: генерация → конвертация → доставка.

        Returns:
            Количество событий, положенных в очередь.
        """

    def all_notes_off(self) -> None:
        """Panic: остановить все ноты этой дорожки."""
```

**Конвертация ChordEvent → TransportEvent:**

```python
def _chord_to_events(self, ev: ChordEvent) -> list[TransportEvent]:
    """Конвертировать ChordEvent в список TransportEvent.

    1. Для каждой ступени в ev.degrees:
       - Harmony.degree_to_note(degree, octave) → MIDI-номер
       - TransportEvent.note_on(port, channel, note, velocity, duration)
    2. Duration = ev.duration * track.gate
    3. Свинг применяется к duration
    """
```

**Ключевые решения:**

- Harmony передаётся извне (инъекция зависимости) — MelodicEngine не создаёт Harmony
- Один MelodicEngine на дорожку (в отличие от одного MutationEngine на сессию)
- Gate применяется к длительности: `duration = ev.duration * self._track.gate`
- Velocity по умолчанию 100 (пока нет маппинга от пада)
- `int()` на всех значениях (numpy-защита)

**Тесты:**
- tick() с пустым outbox → 0 событий
- tick() с ChordEvent → TransportEvent в очереди
- degrees резолвятся в правильные MIDI-ноты
- gate применяется к длительности
- свинг применяется к длительности
- all_notes_off() шлёт CC 123

---

### Шаг 8: Дополнение `Session` — freeze/evolve API

**Файл:** `../src/session/session.py`

```python
class Session:
    """... (существующий код) ..."""

    def freeze_all(self) -> None:
        """Заморозить мутацию на всех дорожках.

        Устанавливает mutate=0 на всех DrumTrack и MelodicTrack.
        Вызывает freeze() на каждой DrumTrack (сохраняет базовый паттерн).
        """

    def evolve_all(self, default_mutate: float = 0.5) -> None:
        """Возобновить мутацию на всех дорожках.

        Аргументы:
            default_mutate: Значение mutate для мелодических дорожек.
                DrumTrack восстанавливает своё предыдущее значение.
        """

    @property
    def total_mutation_count(self) -> int:
        """Суммарное количество мутаций всех дорожек (для дисплея)."""
```

**Ключевые решения:**

- `freeze_all()` — итерация по всем дорожкам, вызов freeze() на drum и mutate=0 на melodic
- `evolve_all()` — mutate=default на melodic, mutate=0.5 на drum
- `total_mutation_count` — сумма mutation_count всех дорожек
- MutationEngine, если зарегистрирован, тоже получает freeze_all/evolve_all

**Тесты:**
- freeze_all() → все дорожки заморожены
- evolve_all() → мутация возобновлена
- total_mutation_count суммирует
- Работает при пустой сессии (no-op)

---

### Шаг 9: `MutationConfig` — конфигурация

**Файл:** `src/session/mutation_config.py`

```python
class MutationConfig(BaseModel):
    """Конфигурация мутации и эволюции.

    Атрибуты:
        enabled: Глобальный выключатель мутации.
        mutate_min_seconds: Минимальный интервал между мутациями (сек).
        mutate_max_seconds: Максимальный интервал между мутациями (сек).
        default_mutate: Значение mutate для новых дорожек (0.0–1.0).
        drift_step_gate: Максимальное смещение gate за мутацию.
        drift_step_density: Максимальное смещение density за мутацию.
        drift_step_register: Максимальное смещение register за мутацию.
    """

    enabled: bool = True
    mutate_min_seconds: float = Field(default=8.0, ge=1.0, le=120.0)
    mutate_max_seconds: float = Field(default=16.0, ge=1.0, le=300.0)
    default_mutate: float = Field(default=0.5, ge=0.0, le=1.0)
    drift_step_gate: float = Field(default=0.05, gt=0.0, le=0.5)
    drift_step_density: float = Field(default=0.1, gt=0.0, le=0.5)
    drift_step_register: float = Field(default=1.0, gt=0.0, le=4.0)
```

**Файл:** `../src/config.py` — добавить `mutation: MutationConfig` в AppConfig

**Файл:** `../config.yaml` — добавить секцию:

```yaml
mutation:
  enabled: true
  mutate_min_seconds: 8.0
  mutate_max_seconds: 16.0
  default_mutate: 0.5
  drift_step_gate: 0.05
  drift_step_density: 0.1
  drift_step_register: 1.0
```

**Тесты:**
- Дефолты корректны
- Валидация границ
- Загрузка из YAML

---

### Шаг 10: Интеграция в Application

**Файл:** `../src/app/application.py`

```python
def _init_mutation(self, mutation_config: MutationConfig) -> None:
    """Создать MutationEngine и зарегистрировать мелодические дорожки."""
    if not mutation_config.enabled or not self._session:
        return
    self._mutation_engine = MutationEngine(
        min_seconds=mutation_config.mutate_min_seconds,
        max_seconds=mutation_config.mutate_max_seconds,
        default_mutate=mutation_config.default_mutate,
    )
    for track in self._session.ordered_tracks():
        if isinstance(track, MelodicTrack) and not track.profile.cc_only:
            self._mutation_engine.register_track(track)

def _init_melodic_engines(self) -> None:
    """Создать MelodicEngine для каждой мелодической дорожки."""
    if not self._session or not self._event_queue or not self._swing_applier:
        return
    for track in self._session.ordered_tracks():
        if isinstance(track, MelodicTrack) and not track.profile.cc_only:
            engine = MelodicEngine(
                track=track,
                harmony=self._harmony,  # Harmony создаётся в C5 или позже
                event_queue=self._event_queue,
                port_label=track.port or "default",
                swing=self._swing_applier,
            )
            self._melodic_engines.append(engine)
```

**Обновление dispatch hook:**

```python
def hooked_dispatch(event):
    if event.name == "TICK":
        cm.on_tick()
        # Мутация (до генерации — чтобы generate() использовал новые параметры)
        if mutation_engine:
            mutation_engine.tick(timeline.current_time)
        for engine in self._drum_engines:
            engine.tick(timeline.current_time)
        for engine in self._melodic_engines:
            engine.tick(timeline.current_time)
    original_dispatch(event)
    if event.name == "TICK":
        capture.beat = timeline.current_time
        transport.process_events(current_beat=timeline.current_time)
```

**Порядок в dispatch hook (важно):**

1. `cm.on_tick()` — клок
2. `mutation_engine.tick()` — мутация **до** генерации
3. `drum_engines.tick()` — drum-генерация (внутри вызывает maybe_mutate)
4. `melodic_engines.tick()` — melodic-генерация (использует продугие параметры)
5. `original_dispatch(event)` — isobar timeline.tick()
6. `transport.process_events()` — доставка

---

## 4. Что НЕ делает C5 (явные границы)

| Не делает | Почему | Кто делает |
|-----------|--------|------------|
| Пады MORPH-режим (UI) | UI — план D | D3 |
| Экран мутации (счётчик) | UI — план D | D2 |
| Кнопка Freeze на Push 2 | UI — план D | D3 |
| Реальный isobar PWhite | Своя реализация проще и тестируемее | — |
| Мутация CC-параметров (filter, reverb) | CC — не ноты, мутация CC отдельная тема | После C5 |
| Мутация гармонии (смена лада/корня) | Слишком радикально для автоматики | Ручное управление |
| Сохранение/загрузка мутационного состояния | Не требуется — мутация эфемерна | — |
| A/B сравнение паттернов | Не в плане | — |
| Мутация swing_amount | Глобальный параметр, не пер-трек | Ручное управление |

---

## 5. Тесты: полный список

| Файл | Тестов | Что проверяет |
|------|--------|---------------|
| `test_mutation.py` | 35–40 | MutationState, NoteDrift, FloatingEuclidean, ParamDrift, MutationEngine |
| `test_mutation_config.py` | 5–7 | дефолты, валидация, YAML |
| `test_melodic_track.py` | +5 | новые поля mutate, bpm, freeze, mutation_count |
| `test_melodic_engine.py` | 15–20 | tick(), конвертация, gate, свинг, all_notes_off |
| `test_session.py` | +5 | freeze_all, evolve_all, total_mutation_count |
| **Итого новых** | **~65–75** | |

### Детальный список тестов `test_mutation.py`

**MutationState (3 теста):**
1. frozen dataclass — нельзя изменить поле
2. Поля корректны при создании
3. Два одинаковых состояния равны

**NoteDrift (7 тестов):**
4. drift_one меняет ровно одну ступень
5. drift_one не выходит за [0, 2 * scale_length)
6. drift_one при mutate=0 — no-op (не применяется)
7. revert_one возвращает к базовому
8. revert_one при отсутствии дрейфа — no-op
9. drift_count корректно считает
10. current_degrees возвращает копию (не ссылку)

**FloatingEuclidean (7 тестов):**
11. drift меняет pulses на ±1
12. drift не выходит за [1, steps-1]
13. revert возвращает к base_pulses
14. pattern обновляется после drift
15. Кеш не пересчитывает при неизменных pulses
16. drift при pulses=1 → только +1 (не -1)
17. drift при pulses=steps-1 → только -1 (не +1)

**ParamDrift (8 тестов):**
18. add_param регистрирует параметр с базовым значением
19. drift_one меняет один параметр
20. drift_one не выходит за [lo, hi]
21. Смещение не более чем на step
22. revert_one возвращает к base
23. Несколько параметров дрейфуют независимо
24. get возвращает текущее значение
25. drift_count корректен

**MutationEngine (15 тестов):**
26. register_track создаёт NoteDrift для lead
27. register_track создаёт FloatingEuclidean для seq
28. register_track создаёт ParamDrift для pad
29. register_track пропускает cc_only профили
30. tick при mutate=0 — no-op
31. tick до интервала — no-op
32. tick после интервала — мутация применена
33. freeze_all → tick — no-op
34. evolve_all → tick — мутация возобновляется
35. total_mutation_count суммирует все дорожки
36. get_state возвращает MutationState
37. Интервал мутации зависит от bpm
38. Деградация: с вероятностью mutate откатываем
39. tick возвращает имена мутировавших дорожек
40. Удалённая дорожка не мутирует

---

## 6. Файлы: создание и изменение

### Новые файлы

```
src/session/mutation.py           # MutationState, NoteDrift, FloatingEuclidean,
                                  # ParamDrift, MutationEngine
src/session/mutation_config.py    # MutationConfig — pydantic-схема
src/session/melodic_engine.py     # MelodicEngine — мост в транспорт
tests/test_mutation.py            # Все тесты мутации
tests/test_mutation_config.py     # Тесты конфига
tests/test_melodic_engine.py      # Тесты MelodicEngine
```

### Изменяемые файлы

```
src/session/melodic_track.py      # + mutate, bpm, mutation_count, freeze()
src/session/melodic_profile.py    # + default_mutate в профилях (опционально)
src/session/session.py            # + freeze_all(), evolve_all(), total_mutation_count
src/config.py                     # + MutationConfig в AppConfig + DEFAULT_CONFIG_YAML
config.yaml                       # + секция mutation:
src/app/application.py            # + _init_mutation(), _init_melodic_engines(),
                                  #   обновление dispatch hook
tests/test_melodic_track.py       # + тесты новых полей
tests/test_session.py             # + тесты freeze_all/evolve_all
```

---

## 7. Порядок реализации

```
Шаг 1:  MutationState           ← нет зависимостей
Шаг 2:  NoteDrift               ← зависит от 1
Шаг 3:  FloatingEuclidean       ← зависит от C4 (PEuclideanCached)
Шаг 4:  ParamDrift              ← зависит от 1
Шаг 5:  MutationEngine          ← зависит от 1–4
Шаг 6:  MelodicTrack + поля     ← зависит от 5 (интерфейс)
Шаг 7:  MelodicEngine           ← зависит от 6, C1 (Harmony), B4 (Transport)
Шаг 8:  Session + freeze/evolve ← зависит от 5, 6
Шаг 9:  MutationConfig          ← независим, можно параллельно с 1–8
Шаг 10: Application             ← зависит от всех
```

Шаги 2, 3, 4 — параллельно (после Шага 1).
Шаг 9 — параллельно с 1–8.

---

## 8. Критерии готовности

- [ ] `MutationState` — frozen dataclass с 4 полями
- [ ] `NoteDrift` дрейфует ступени в пределах лада, не выходя за 2 октавы
- [ ] `FloatingEuclidean` дрейфует pulses ±1, используя PEuclideanCached
- [ ] `ParamDrift` дрейфует gate/density/register в заданных границах
- [ ] `MutationEngine` выбирает механизм по профилю дорожки
- [ ] Интервал мутации: uniform(8, 16) секунд, пересчёт через bpm
- [ ] Деградация: с вероятностью mutate откат к базовому
- [ ] `MelodicTrack` имеет `mutate`, `bpm`, `mutation_count`, `freeze()`
- [ ] `MelodicEngine` конвертирует ChordEvent → TransportEvent через Harmony
- [ ] `Session.freeze_all()` замораживает все дорожки
- [ ] `Session.evolve_all()` возобновляет мутацию
- [ ] `Session.total_mutation_count` — агрегированный счётчик
- [ ] `MutationConfig` в config.yaml с валидацией
- [ ] Dispatch hook: мутация → генерация → доставка
- [ ] ~65–75 новых тестов passed
- [ ] ruff / mypy / black чисто

---

## 9. Риски и митигация

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| Мутация делает музыку мусором | Высокая | Потолок `mutate`, Freeze одной кнопкой, деградация |
| Дрейф уводит ноты в неслышимый регистр | Средняя | Ограничение 2 октавами лада, clamp к [lo, hi] |
| Мутация уводит грув необратимо | Средняя | 1–2 изменения за 8–16 с, деградация, счётчик |
| FloatingEuclidean ломает кеш | Низкая | PEuclideanCached инвалидирует только при смене pulses |
| MutationEngine — bottleneck при 16 дорожках | Низкая | Мутация раз в 8–16 с, не каждый тик; O(1) на дорожку |
| Несовместимость с DrumTrack-мутацией | Низкая | DrumTrack не трогаем, общий интерфейс через Session |
| Потеря детерминизма при тестах | Средняя | `random.Random(seed)` в тестах, инъекция rng |
| MutationEngine и DrumTrack дублируют интервал | Низкая | Общие константы MUTATE_MIN/MAX_SECONDS в mutation.py |

---

## 10. Интерфейс для UI (будущие D2/D3)

Хотя UI — это план D, C5 закладывает API, который UI будет вызывать:

```python
# Для D2 (экраны):
session.total_mutation_count          # int — для счётчика на дисплее
mutation_engine.get_state(name)       # MutationState — для индикатора
track.mutate                          # float — для ползунка MUT

# Для D3 (пады MORPH-режим):
# X = density, Y = mutate
# Пад (x, y) → track.density = x/7, track.mutate = y/7
track.density                         # float 0.0–1.0 (если ParamDrift)
mutation_engine.freeze_all()          # по кнопке Freeze
mutation_engine.evolve_all()          # по кнопке Evolve

# Для D2 (экран дорожки):
track.mutation_count                  # int — изменения с последнего freeze
track.freeze()                        # заморозить одну дорожку
```

---

## 11. Связь с планом v5_4

| Требование плана | Раздел плана | Реализация C5 |
|-----------------|-------------|---------------|
| `mutation.py (дрейф)` | §5, §6 | `src/session/mutation.py` |
| Непрерывный дрейф | §6 | `NoteDrift` |
| Плавающий PEuclidean | §6 | `FloatingEuclidean` |
| Дрейф диапазонов PWhite | §6 | `ParamDrift` |
| Freeze/Evolve | §4.5, §6 | `Session.freeze_all()` / `evolve_all()` |
| Мутация 1–2 за 8–16 с | §4.2, §8 | `MutationEngine.MUTATE_MIN/MAX_SECONDS` |
| Деградация к базовому | §4.2, §7, §8 | revert_one() во всех механизмах |
| Счётчик на дисплее | §4.2 | `Session.total_mutation_count` |
| MORPH: X=density, Y=mutate | §4.4 | API: `track.density`, `track.mutate` |
| Clock-independent | §5.1 | Операции в beats, пересчёт через bpm |
| Мутация делает музыку мусором | §7 | Потолок mutate, Freeze, деградация |
