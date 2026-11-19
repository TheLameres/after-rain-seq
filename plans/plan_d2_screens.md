# Расширенный план D2: Экраны и навигация (screens.py)

> Задача D2 из AGENTS.md (Фаза 4). Выход: `screens.py` — банк дорожек с
> прокруткой, 5 макро-осей (DEN/MUT/SPACE/DEPTH/TONE), статус-бар
> (Root/Scale/BPM/порт), создание дорожки одним нажатием, SOURCE/SOURCE2,
> экраны SYNC и PORTS. Зависимости: D1 (рендерер), B1 (клок), B2 (порты).

---

## 1. Анализ: что есть и что нужно построить

### 1.1. Что уже есть (используем как фундамент)

| Компонент | Файл | Что даёт D2 |
|-----------|------|-------------|
| Рендерер + dirty rects | `../src/devices/push2/renderer.py` (D1) | FrameBuffer, примитивы, GlyphCache, Colors — рисуем экраны только ими |
| Композитор | `../src/devices/push2/display.py` (`PushDisplay`) | Scene-composer с per-widget инвалидацией; публичный API `update_state`/`render_usb`/`render_frame_only` |
| Снапшот состояния | `../src/repl/status.py` (`StatusSnapshot`) | running/bpm/swing/clock(+pending/error)/link/root/scale/tracks(`TrackSummary`)/mutations/ports(`PortSummary`) — собирается в main loop, атомарная замена ссылки |
| Фасад команд | `../src/repl/engine_control.py` (`EngineControl` ABC + `AppEngineControl`) | start/stop, set_bpm, request_clock_source, rescan_ports, switch_port, set_root/set_scale, create/track/route/unroute/freeze/evolve — всё, что нужно экранам, уже с валидацией и текстом ошибок |
| Кнопки/энкодеры/пады | `../src/devices/push2/push2_device.py` + `mapping.py` | Колбэки `on_button(name, pressed)`/`on_encoder(name, inc)`/`on_pad(note, vel)`; карта имён кнопок; relative→increment конвертация |
| Session API | `../src/session/session.py` | `create_melodic_track`, `create_drum_track`, `set_sources` (с проверкой цикла), `remove_track` (стратегия B), `freeze_all`/`evolve_all`, лимиты с текстом `ValueError` |
| CC-маппинг | `../src/sync/cc_map.py` | `DEFAULT_CC_PARAMS`: filter 74, resonance 71, reverb 91, delay 93, … — логические имена для осей TONE/SPACE/DEPTH |
| Track-параметры | `src/session/melodic_track.py` | `channel`, `sources`, `gate`, `voicing`, `octave`, `mutate`, `mutation_count`, `freeze()` — читаются движками live |

### 1.2. Чего нет (пишем в D2)

| Проблема | Последствие |
|----------|-------------|
| Push 2 показывает банки энкодеров M8-эпохи (`EncoderHandler`), не дорожки сессии | Экран не отражает ни сессию, ни граф, ни клок/порты — «полное управление с Push 2» невозможно |
| Нет понятия «экран» и навигации | Требование: 6 экранов (TRACKS/TRACK/GLOBAL/SYNC/PORTS + статус-бар), переключение кнопками |
| MIDI-колбэки зовутся из потока mido напрямую в `App._on_device_*` | Правило проекта «никаких колбэков из чужих потоков» (B1, TickProxy) нарушено для UI: мутация состояния экрана с MIDI-потока гонится с render loop |
| Нет макро-осей DEN/MUT/SPACE/DEPTH/TONE | Требование D2; у движка нет `density`, нет live-CC «performance»-слоя через CCMap |
| `EngineControl` не покрывает drum-дорожки, источники, gate, per-track evolve | Экран TRACK нечем наполнить — расширяем фасад (аддитивно) |
| `TrackSummary` не несёт gate/voicing/octave/mutate | Экрану TRACK не хватает деталей — расширяем frozen DTO (аддитивно, REPL не ломается) |

### 1.3. Ключевые находки при чтении кода

1. **Слои запрещают импорт session/sync из devices/.** Экраны рисуют данные сессии → view-модель строится в app-слое и спускается вниз как чистые DTO (прецедент: `../src/devices/display_state.py` — там уже живут `DisplayState`/`EncoderDisplayInfo`, которые заполняет `DisplayRenderer.build_display_state`). D2 расширяет этот прецедент, а не ломает иерархию.
2. **`StatusSnapshot` — готовый read-only источник правды для экранов.** Собирается в main loop (`App._update_status_snapshot`), атомарная замена ссылки, REPL его уже ест. Экраны строятся из него + малого мутабельного `UiState` (выбор/страница/текущий экран). Движок из render-потока не читается.
3. **`EngineControl` — готовый write-фасад.** Все команды экранов идут через него (как REPL); исключения уже превращены в текст. Расширяем аддитивно: `create_drum_track`, `set_track_sources`, `set_track_gate`, `set_track_density`, `evolve_track`.
4. **`Session.set_sources()` уже ловит цикл** и сбрасывает зависимых по стратегии B; ошибка придёт текстом во flash-строку экрана (требование мастер-плана: «STAB → CHORDS → STAB: цикл», а не трейсбек).
5. **Push 2 не имеет кнопок «Page Left/Right»**. Кнопочный состав: Upper Row 1–8 (софт-клавиши над дисплеем), Left/Right/Up/Down/Session/Note/Shift/Play/Record/Delete/Duplicate/Mute/Solo/Layout/Browse/Setup, правый столбец 1/4…1/32t, Lower Row 1–8. Навигацию проектируем на этом составе (§3.3).
6. **Upper Row сейчас = выбор банка энкодеров** (`update_bank_leds`, `EncoderHandler.on_bank_select`, перехват в App). В модели D2 банки M8-эпохи для Push 2 мертвы: экран TRACKS сам определяет, что крутят 8 энкодеров. Решение: Upper Row перепрофилируется в табы экранов; `EncoderHandler` остаётся для LCXL3 (его путь не трогаем), Push 2-путь `on_encoder` идёт в UI-контроллер. Код `EncoderHandler`/банков для Push 2 не удаляем в D2 (LCXL3), но `DisplayRenderer` больше не строит для Push 2 encoder_info из банков.
7. **Энкодеры Push 2 — только relative-поворот + touch, без нажатия.** Значит «подтверждение падом» из мастер-плана не нужно, а «создание дорожки одним нажатием» — кнопкой (§3.3).
8. **Все события UI обрабатываются в main loop.** Render loop, снапшот и UI-диспетчер живут в одном потоке (main loop App) → `UiState` пишется и читается только там, замок не нужен; MIDI-поток только кладёт события в очередь (паттерн TickProxy: очередь + drain в main loop).
9. **CC-оси (TONE/SPACE/DEPTH) идут через `CCMap` + троттлер порта** — тот же путь, что B3: логическое имя → номер CC по порту дорожки → `MidiPortOutput.control()` (30 Hz троттлинг уже внутри). Дорожка без порта → ось показывает `—` и шлёт некуда.
10. **`display.py` D1** шлёт кадр по факту dirty + keepalive 1 с — экраны D2 наследуют это бесплатно; статичные экраны (SYNC без активности) не гоняют USB.

---

## 2. Архитектура

### 2.1. Файлы

```
src/devices/
├── display_state.py           # ИЗМЕНЁННЫЙ: + view-модели экранов (frozen DTO, только данные)
└── push2/
    ├── screens.py             # НОВЫЙ: 5 рендереров экранов (pure draw на FrameBuffer)
    └── display.py             # ИЗМЕНЁННЫЙ: PushDisplay.update_screen(view) вместо bank-виджетов

src/app/ui/                    # НОВЫЙ пакет (всё управление — в main loop)
├── __init__.py
├── screen_id.py               # ScreenId enum: TRACKS/TRACK/GLOBAL/SYNC/PORTS
├── ui_state.py                # UiState: screen, page, selected, flash(text+deadline), macro values
├── ui_event.py                # UiEvent frozen: BUTTON(name,pressed) | ENCODER(name,inc)
├── ui_queue.py                # UiEventQueue: thread-safe, drain() из main loop
├── macro_axes.py              # MacroAxis enum, mapping axis→CC params (config), DEN/MUT semantics
└── screen_controller.py       # навигация, команды через EngineControl, сборка ScreenView

src/repl/
├── status.py                  # ИЗМЕНЁННЫЙ: TrackSummary + gate/voicing/octave/mutate (аддитивно)
└── engine_control.py          # ИЗМЕНЁННЫЙ: + create_drum_track/set_track_sources/set_track_gate/
                               #   set_track_density/evolve_track (аддитивно)

src/session/
├── melodic_track.py           # ИЗМЕНЁННЫЙ: + density (0..1, default 1.0)
└── generators.py              # ИЗМЕНЁННЫЙ: density влияет на chord_slicer/free_mono

src/app/application.py         # ИЗМЕНЁННЫЙ: wiring — drain ui_queue в main loop, render через controller
src/app/display.py             # ИЗМЕНЁННЫЙ: build_display_state → build ScreenView через контроллер
src/config.py + config.yaml    # ИЗМЕНЁННЫЙ: секция ui: (macro_axes, defaults)

tests/
├── test_ui_state.py           # НОВЫЙ
├── test_ui_queue.py           # НОВЫЙ
├── test_macro_axes.py         # НОВЫЙ
├── test_screen_controller.py  # НОВЫЙ: навигация, команды, краевые случаи (мок EngineControl)
├── test_screens_render.py     # НОВЫЙ: каждый экран рисует ключевые элементы (пиксельные проверки)
└── test_display_state.py      # СУЩЕСТВУЕТ?: view-модели + сравнение-снапшоты для dirty

spikes/
└── spike_ui_simulate.py       # НОВЫЙ: --simulate эмулятор: on_frame превью + скрипт «нажатий»
```

### 2.2. Слои и зависимости (циклов нет)

```
main.py
  └── app/
        ├── ui/  (screen_controller, ui_state, macro_axes, ui_queue)
        │     ├── читает:  repl/status (StatusSnapshot — DTO)
        │     └── пишет:  repl/engine_control (EngineControl ABC)
        ├── display.py (DisplayRenderer: snapshot → ScreenView → device.render_display)
        └── application.py (wiring: midi-колбэки → UiEventQueue → drain в main loop)

devices/push2/screens.py   ← devices/display_state.py (view DTO) + renderer.py (примитивы)
devices/push2/display.py   ← screens.py; НЕ знает про session/sync/app
```

- `screens.py` — чистая отрисовка: функции `(FrameBuffer, <ViewDTO>) -> None`. Никакой логики, никаких импортов выше devices/.
- `app/ui/` не импортирует session/sync напрямую — только `StatusSnapshot` (данные) и `EngineControl` (команды). Это держает UI заменяемым и тестируемым на моках.
- `EngineControl` физически лежит в `../src/repl` — это историческое имя, ABC генеричен (фасад движка). Переименование/перенос файла вне скоупа D2; импортируем как есть (задокументировано в коде).

### 2.3. Потоки данных

```
MIDI-поток (mido callback)
   │  on_button/on_encoder (Push2Device)
   ▼
App._on_device_button/_on_device_encoder ──put──▶ UiEventQueue (lock, capacity 64)
                                                        │
main loop App                                           ▼
   │  1. drain ui_queue → ScreenController.handle_*    │
   │     (навигация: UiState; команды: EngineControl;  │
   │      ошибки → UiState.flash)                      │
   │  2. _update_status_snapshot() (как сейчас)        │
   │  3. render: DisplayRenderer.build_display_state → │
   │     controller.build_view(snapshot) → ScreenView  │
   ▼                                                   │
PushDisplay.update_screen(view) → compare per-region → │
   invalidate dirty regions → screens.py рисует        │
   через FrameBuffer-примитивы → render_usb (D1)       │
```

Инварианты:
- `UiState` пишется только в main loop (дrain) → render читает без замка.
- Снапшот — frozen, атомарная замена ссылки (как сейчас).
- MIDI-поток не трогает ни движок, ни UiState — только `UiEventQueue.put` (O(1), не блокирует; при переполнении — drop + warning в лог, не молча).

---

## 3. Детальный дизайн

### 3.1. View-модели — `../src/devices/display_state.py`

Все frozen, только строки/числа/кортежи (контракт слоёв):

```python
@dataclass(frozen=True)
class TrackRowView:
    """Строка дорожки на экране TRACKS."""
    name: str
    kind: str            # "melodic" | "drum"
    profile: str
    channel: int
    port: str | None     # None — не привязана (молчит)
    frozen: bool
    mutation_count: int
    selected: bool

@dataclass(frozen=True)
class TrackDetailView:
    """Экран TRACK: параметры выбранной дорожки."""
    name: str; kind: str; profile: str
    channel: int; port: str | None
    sources: tuple[str, ...]        # ("Pad 1",) | () — «—»
    gate: float                     # 0..1; для drum — 0.0 («—»)
    voicing: str                    # "1-4-7"; drum/cc_only — ""
    density: float                  # 0..1; chord_slicer/free_mono, иначе None → «—»
    mutate: float                   # 0..1 (0 = frozen)
    macros: tuple[int, int, int]    # TONE/SPACE/DEPTH 0..127; порт None → (-1,-1,-1) = «—»

@dataclass(frozen=True)
class SyncView:
    source: str            # internal|midi|link
    pending: str | None
    error: str | None
    bpm: float             # локальный (при midi/link — «внешний»)
    running: bool
    link_active: bool; link_peers: int
    midi_device: str       # устройство MIDI-клока или «—»

@dataclass(frozen=True)
class PortRowView:
    label: str; status: str; detail: str   # status: connected|disconnected|ambiguous|error

@dataclass(frozen=True)
class PortsView:
    rows: tuple[PortRowView, ...]
    route_track: str          # дорожка для назначения (ENC1)
    route_port: str | None    # её текущий порт (None = «—»)
    selected: int             # курсор

@dataclass(frozen=True)
class GlobalView:
    root: str; scale: str; swing: float
    total_mutations: int
    frozen_count: int         # «3/7 frozen»
    bpm: float

@dataclass(frozen=True)
class ScreenView:
    """Единый контейнер, который получает PushDisplay."""
    screen: str               # ScreenId value (str — чтобы не тянуть enum в devices)
    title: str                # «TRACKS 1-8/2», «TRACK: Stab 1», …
    flash: str | None         # transient сообщение (ошибка/подтверждение)
    tracks: tuple[TrackRowView, ...] | None = None
    track: TrackDetailView | None = None
    sync: SyncView | None = None
    ports: PortsView | None = None
    global_: GlobalView | None = None
    status: StatusBarView     # всегда
    # Метки действий для нижней строки экрана (подсказки кнопок):
    hints: tuple[str, ...] = ()
```

`StatusBarView` (требование «Статус: Root/Scale/BPM/порт»):
`root: str; scale: str; bpm: float; clock: str; pending: str|None; sel_port: str|None; error: bool` — левая часть `A dorian`, центр `118.0 INT` (или `LINK·2`/`MIDI`), правая `▸Синт A` (порт выбранной дорожки; `—` если нет). При `error=True` — красный цвет flash-части.

### 3.2. `UiState` — `../src/app/ui/ui_state.py`

```python
@dataclass
class UiState:
    """Мутабельное состояние навигации. Пишется только из main loop."""
    screen: ScreenId = ScreenId.TRACKS
    page: int = 0                    # банк дорожек: 0 = дорожки 1-8
    selected: int = 0                # курсор (индекс в рамках страницы / строки списка)
    flash_text: str | None = None
    flash_deadline: float = 0.0      # monotonic; TTL 3.0 с
    macro_cc: dict[str, int] = field(default_factory=dict)
        # (track_name, axis) → value 0..127 — performance-CC (TONE/SPACE/DEPTH)
    shift: bool = False              # Shift held
```

- `flash(text)`: пишет текст + deadline; render показывает, пока `now < deadline`; не блокирует UI.
- `macro_cc` живёт в рантайме (не config): переживает смену экранов, не переживает restart — осознанно (performance-слой).
- Смена экрана → `PushDisplay` получает view с другим `screen` → full invalidate (D1-API `reset()`).

### 3.3. Навигация и кнопки

Кнопочная карта (вся — в `screen_controller.py`, константы рядом; не в mapping.py — там физический слой):

| Кнопка | Действие |
|--------|----------|
| **Upper Row 1–5** | Прямой переход на TRACKS / TRACK / GLOBAL / SYNC / PORTS. LED активной вкладки — белый, остальные — dim (заменяет `update_bank_leds` для Push 2; LCXL3-путь не трогаем) |
| **Left / Right** | На TRACKS: Page Left/Right (банк 8 дорожек). На PORTS: скролл курсора по списку. Иначе: предыдущий/следующий экран |
| **Up / Down** | Курсор выбора: дорожка (TRACKS), строка (PORTS) |
| **Play** | Транспорт start/stop (через `EngineControl.start/stop_transport`) |
| **Record** | На TRACKS: freeze all (`freeze()`). На TRACK: freeze выбранной дорожки. LED = «все заморожены» |
| **Duplicate** | «+ NEW TRACK»: создать melodic-дорожку `pad` с дефолтами одним нажатием (мастер-план §4.1: «новое нажатие = новая дорожка с дефолтами»); профиль/порт правятся потом на TRACK/PORTS. При лимите 16 — flash с текстом ошибки |
| **Shift+Delete** | Удалить выбранную дорожку (`remove_track`, стратегия B: зависимые получают `sources=()` — flash «Stab 1: источник сброшен» берём из текста ошибки/результата). Без Shift — Delete не действует (защита от случайного) |
| **Browse** | На PORTS: `rescan_ports()` (кнопка SCAN). Иначе — ничего |
| **Shift** | Модификатор (удержание); состояние в `UiState.shift` |
| Прочие | Не назначены в D2 (Layout/Session/Note/Setup — резерв; пады — D3) |

Переход на экран TRACK: короткое нажатие **Right** при выбранной дорожке на TRACKS (и Left — назад на TRACKS). Дублируется табом Upper Row 2.

LED-табов: контроллер публикует `active_screen`; `Push2Device.update_bank_leds` для Push 2 вызывается с маппингом «экран → Upper Row» (реализация в controller, не трогая LCXL3-вызовы).

### 3.4. Экраны — `../src/devices/push2/screens.py`

Каждый рендерер: `def draw_<screen>(fb: FrameBuffer, view: <DTO>) -> None`. Раскладка (960×160):

- **y 0–21** — header: заголовок слева, flash-строка справа (красная/жёлтая).
- **y 24–135** — body экрана.
- **y 138–160** — status bar (глобальный, рисуется всегда из `StatusBarView`) + hints-строка (мелкий текст: `◀▶PAGE ▲▼SEL DUP+ NEW`).

Макеты body:

```
TRACKS (8 строк × 14px, шрифт sm/md):
  ▶ Pad 1    pad   ch0  ▸Синт A  ❄FROZEN
    Bass 1   bass  ch1  ▸Синт A  mut:12
    Drum 1   drum  ch9  —        mut:3
    …(пустые строки = слоты; курсор ▶)
  Заголовок обязан показывать «TRACKS 1-8 / 2» (мастер-план §4.3).

TRACK (две колонки параметров + макро-блок):
  SRC  Pad 1     SRC2 —        PORT ▸Синт B   CH 3(RO)
  GATE ▮▮▯▯ 0.25 DEN ▮▮▮▯▯  MUT ▮▯▯▯▯  VOICING 1-4-7
  TONE ▮▮▮▯  SPACE ▮▯▯▯  DEPTH ▮▯▯▯
  Энкодеры: E1=SRC E2=SRC2 E3=GATE E4=DEN E5=MUT E6=TONE E7=SPACE E8=DEPTH
  (PORT назначается на экране PORTS; CH — read-only, меняется в REPL)
  drum-дорожка: вместо SRC/GATE/DEN — «—»; MUT = мутация машины.

GLOBAL:
  ROOT ▶A        SCALE ▶dorian     SWING ▮▯▯▯ 12%
  MUTATIONS: 47   FROZEN: 2/7       BPM 118.0
  Энкодеры: E1=ROOT (листает 12 нот) E2=SCALE (листает HARMONIC_SCALES) E3=SWING

SYNC:
  SOURCE ●internal  ○midi  ○link      ← E1 листает, применение на ближайшей доле
  DEVICE LCXL3 1 DAW Out                ← midi-clock устройство (RO)
  TEMPO  118.0 (local)                  ← глобальный Tempo-энкодер крутит BPM
  STATUS running · LINK peers 2         ← pending показывается как «→ link…»

PORTS:
  ▶ Синт A   connected    LCXL3 1 DAW In
    Синт B   disconnected  (no match)
    …
  ROUTE: Pad 1 → ▸Синт A                ← E1 листает дорожку, E2 листает порт
  Browse = SCAN
```

Энкодерные назначения — по имени («Track1 Encoder»…«Track8 Encoder»): контроллер мапит `E1..E8` позиционно. Глобальные (Tempo/Swing/Master): Tempo — BPM всегда; Swing — swing_amount; Master — не назначен в D2 (резерв, показывать dim).

### 3.5. Макро-оси — `../src/app/ui/macro_axes.py`

```python
class MacroAxis(Enum):
    DENSITY = "DEN"; MUTATE = "MUT"; SPACE = "SPACE"; DEPTH = "DEPTH"; TONE = "TONE"
```

| Ось | Семантика | Путь |
|-----|-----------|------|
| **DEN** | Плотность паттерна дорожки, 0..1 → `track.density`. Влияет на `chord_slicer` (плотность евклида: effective pulses из `base_pulses`×density, кламп 1..steps) и `free_mono` (вероятность ноты). Для `chord_source`/`cc_only` — «—» (не применимо) | `EngineControl.set_track_density` |
| **MUT** | `track.mutate` 0..1 напрямую (0 = заморожена, как `freeze()`). Счётчик мутаций — на экране | `EngineControl.set_track_gate`-стиль: прямое поле + валидация 0..1 |
| **TONE** | Performance-CC: `filter` (74) на порт дорожки | CCMap → MidiPortOutput.control, троттлинг 30 Hz (B3) |
| **SPACE** | `reverb` (91) + `delay` (93) одним значением | то же |
| **DEPTH** | `resonance` (71) | то же |

- Маппинг осей → логические CC-параметры — в конфиге (§3.7), валидация при загрузке: неизвестный параметр → `ConfigError` (стиль B3). Значение оси хранится в `UiState.macro_cc[(track, axis)]`; отправка — в момент поворота энкодера (increment → новое значение 0..127).
- CC-оси шлются только если у дорожки есть порт (`TrackSummary.port`); иначе поворот энкодера меняет сохранённое значение (без звука) и показывает «—». При назначении порта значения не «догоняются» осознанно (performance-слой, не состояние синта).
- DEN применяется live: движки читают `track.density` при генерации (как `channel` — C6-фикс).

### 3.6. Расширения движка (аддитивные, маленькие)

`EngineControl` + `AppEngineControl`:
- `create_drum_track() -> str` — обёртка над `session.create_drum_track()` (тексты лимитов — из `ValueError`).
- `set_track_sources(name, *sources) -> str` — обёртка над `session.set_sources()`; `ValueError` → текст «цикл: …» во flash.
- `set_track_gate(name, gate: float) -> str` — валидация 0..1; поле `MelodicTrack.gate` (существует).
- `set_track_density(name, density: float) -> str` — валидация 0..1; новое поле `MelodicTrack.density = 1.0`.
- `evolve_track(name) -> str` — `track.mutate = default` для одной дорожки (симметрия freeze).

`src/session/generators.py`: чтение `track.density` в `generate_notes(ctx)`:
- `chord_slicer`: `pulses = clamp(1, spec.steps, round(spec.base_pulses * (0.25 + 0.75 * density)))` — DEN=1 → базовый рисунок, DEN=0 → 25% базовой плотности (не тишина: «почти пусто», требование §3.5).
- `free_mono`: вероятность включения шага масштабируется на density.
- `chord_source`/`cc_only`: density игнорируется (DTO отдаёт `None` → «—»).

`../src/repl/status.py` (`TrackSummary`, аддитивно): `gate: float = 0.0`, `voicing: str = ""`, `octave: int = 0`, `mutate: float = 0.0`, `density: float = 1.0` — заполняется в `App._track_summaries()`. REPL не ломается (новые поля не выводятся).

### 3.7. Конфигурация

```yaml
ui:
  macro_axes:
    tone: [filter]
    space: [reverb, delay]
    depth: [resonance]
  flash_seconds: 3.0
```

- `../src/config.py`: `UiConfig` (pydantic), в `AppConfig` как `ui: UiConfig`. Валидация имён параметров — против `DEFAULT_CC_PARAMS` ∪ `cc_map.ports`-оверрайдов (если CCMap уже построен; иначе против дефолтов, что покрывает старт).
- Порядок осей на экране TRACK фиксирован (TONE/SPACE/DEPTH), состав — конфиг.

### 3.8. Интеграция — `application.py` / `display.py` / `push2_device.py`

- `App.__init__`: `_ui_queue = UiEventQueue()`, `_ui = ScreenController(engine_control, ui_state, macro_axes)`.
- `App._on_device_button/_on_device_encoder` (сейчас — заглушки/энкодер-хендлер): для Push 2-слота → `self._ui_queue.put(UiEvent(...))`. LCXL3-слот — без изменений (`EncoderHandler`). Push 2 больше не регистрируется в `EncoderHandler` (экраны сами определяют назначение энкодеров).
- main loop (рядом с `_poll_ports`): `for ev in self._ui_queue.drain(): self._ui.handle(ev)` → контроллер дёргает `EngineControl` и мутирует `UiState`.
- `DisplayRenderer.build_display_state`: вместо `encoder_info` из банков — `controller.build_view(app.status_snapshot, clock_state)` → `DisplayState(screen_view=...)` (новое поле; старое `encoder_info` остаётся для LCXL3).
- `Push2Device.render_display`: если `state.screen_view is not None` → `PushDisplay.update_screen(view)` (новый метод); иначе — legacy `update_state` (LCXL3 нет дисплея такого, путь остаётся для совместимости/тестов).
- `PushDisplay.update_screen(view)`: сравнение view с предыдущим по регионам (header/body/status) → инвалидация изменённых → вызов соответствующего `draw_*` из `screens.py`. Смена `screen` → `fill(BG)` + invalidate full (D1 `reset()`).

---

## 4. Краевые случаи

| Случай | Обработка |
|--------|-----------|
| Дорожек 0 | TRACKS: пустые строки + hint «DUP = +NEW»; TRACK — «no tracks» |
| Дорожек > 8 | Page Left/Right, заголовок «TRACKS 9-16 / 2»; курсор в рамках страницы |
| Лимиты (16 дорожек / 2 drum) | Текст `ValueError` → flash 3 с; состояние не меняется |
| Цикл графа при выборе SRC | `set_sources` → текст «цикл: Stab 1 → Pad 1 → Stab 1» → flash; значение не применено |
| Удаление дорожки-источника (Shift+Delete) | Стратегия B: зависимые `sources=()`; flash «Bass 1: источник сброшен» |
| Удаление выбранной/последней дорожки | Курсор: clamp к существующему индексу; экран TRACK → TRACKS если дорожки кончились |
| SRC указывает на себя | Не предлагаем: список SRC = все дорожки кроме самой (фильтр в контроллере) |
| Поворот энкодера на пустом слоте TRACKS | Игнор (debug-лог); flash не нужен |
| CC-ось у дорожки без порта | Значение сохраняется, отправки нет, на экране «—» |
| Порт отвалился (hot-plug) | Статус-бар и TRACKS показывают «—»/disconnected из снапшота; CC-оси молчат (PortRegistry сам сделал all_notes_off, B2) |
| Переключение клока pending | SYNC: «→ link…» до применения; статус-бар тоже показывает pending |
| Ошибка клока (link не установлен и т.п.) | `clock_error` → flash + красный индикатор в статус-баре; экран SYNC показывает STATUS с ошибкой |
| MIDI-шторм кнопок | Очередь capacity 64; overflow → drop oldest + `log.warning` (не молча) |
| Simulate-режим (без железа) | Весь UI работает; `render_frame_only` + on_frame превью (D1); spike драйверит сценарии |
| Flash во время смены экрана | Flash живёт в UiState, переживает смену экрана до deadline (ошибка видна) |
| Трек создан из REPL во время сета | Снапшот подхватывает на следующем тике; курсор/страница — clamp |

---

## 5. Тестирование

### Матрица тестов

| Тест | Что проверяет |
|------|---------------|
| `test_ui_queue_put_drain` | put → drain возвращает в порядке FIFO; drain пустит очередь |
| `test_ui_queue_threaded` | put из потока ×1000 — ни одной потери, порядок сохранён |
| `test_ui_queue_overflow` | > capacity → drop oldest + warning (мок лога) |
| `test_ui_state_flash_ttl` | flash ставит deadline; `expired(now)` корректен |
| `test_screen_id_values` | 5 экранов, стабильные строковые значения |
| `test_nav_tabs` | Upper Row N → ScreenId N; LED-маппинг активного таба |
| `test_nav_page_wrap` | Left/Right на TRACKS листает страницы, кламп за краями |
| `test_nav_cursor_clamp` | Up/Down клампится; удаление последней дорожки сбрасывает курсор |
| `test_enter_exit_track_screen` | Right на TRACKS → TRACK выбранной; Left → назад |
| `test_new_track_duplicate` | Duplicate → `create_track("pad")` через мок EngineControl; flash при лимите |
| `test_delete_requires_shift` | Delete без Shift — no-op; Shift+Delete → remove_track |
| `test_encoder_routes_per_screen` | E1..E8 на TRACK/SYNC/PORTS/GLOBAL идут в нужные команды (мок) |
| `test_macro_den_mut` | поворот DEN → set_track_density с клампом 0..1; MUT → mutate |
| `test_macro_cc_send` | TONE поворот → CC 74 на порт дорожки (мок MidiPortOutput); throttle задействован |
| `test_macro_cc_no_port` | дорожка без порта → значение сохраняется, отправки нет, «—» в view |
| `test_macro_axis_config_validation` | неизвестный параметр в `ui.macro_axes` → ошибка загрузки конфига |
| `test_density_generators_slicer` | DEN=1 → base_pulses; DEN=0 → 25%; кламп ≥1 (generators) |
| `test_density_generators_free_mono` | вероятность масштабируется на density |
| `test_track_summary_extended` | gate/voicing/octave/mutate/density в TrackSummary из App |
| `test_view_models_frozen` | ScreenView/детали — frozen, собираются из снапшота без движка (мок снапшота) |
| `test_screens_tracks_render` | draw_tracks: 8 строк, курсор «▶», заголовок «1-8/2» — пиксели в bbox не фоновые |
| `test_screens_track_render` | draw_track: SRC/SRC2/GATE/DEN/MUT/TONE/SPACE/DEPTH подписи присутствуют (через GlyphCache: ширина текста > 0 и не BG-пиксели в строках) |
| `test_screens_sync_render` | ● у активного source; pending показан; error красным |
| `test_screens_ports_render` | строки портов + ROUTE-строка; статусы цветом |
| `test_screens_statusbar` | Root/Scale/BPM/порт выбранной дорожки на местах |
| `test_pushdisplay_screen_invalidate` | смена screen → full invalidate; повторный тот же view → пусто (dirty пуст) |
| `test_flash_survives_screen_switch` | flash в view после смены экрана до deadline |

Порядок: ui_queue → ui_state/macro_axes → view models → screens render (на мок-View) → controller (мок EngineControl) → engine additions (density в generators, TrackSummary) → интеграция App/PushDisplay → spike.

### E2E-проверка (spike_ui_simulate.py)

Сценарий в одном процессе (`App(--simulate)` + on_frame превью):
1. Duplicate ×2 → на TRACKS 2 дорожки; заголовок «TRACKS 1-8 / 1».
2. Right → TRACK; крутануть E4 (DEN) → `track.density` изменился; E6 (TONE) с непривязанной дорожкой → «—».
3. На PORTS: выбрать порт, назначить дорожке (E1/E2) → `TrackSummary.port` появился.
4. GLOBAL: E1 крутит root A→B#…; статус-бар обновился.
5. SYNC: E1 → link (pending виден), вернуть internal.
6. Shift+Delete → дорожка удалена, зависимая сброшена (flash).
Проверка — ассерты по view/снапшоту + PNG-дампы кадров для глаз.

---

## 6. Порядок реализации

1. **`ui/` каркас**: `screen_id.py`, `ui_event.py`, `ui_queue.py`, `ui_state.py` + тесты.
2. **View-модели** в `display_state.py` + `StatusBarView`; `TrackSummary` расширить.
3. **Engine additions**: `MelodicTrack.density`, generators, `EngineControl`/`AppEngineControl` (+5 методов) + тесты.
4. **`macro_axes.py`** + `UiConfig` в конфиге + валидация + тесты.
5. **`screens.py`**: статус-бар → TRACKS → TRACK → GLOBAL → SYNC → PORTS; тесты отрисовки.
6. **`screen_controller.py`**: навигация, кнопочная карта, энкодерные назначения, сборка view + тесты на моках.
7. **Интеграция**: `App` (drain в main loop, wiring колбэков), `DisplayRenderer.build_display_state`, `PushDisplay.update_screen`, `Push2Device.render_display`.
8. Полный прогон: `pytest`, `ruff`, `mypy`, `black`.
9. `../spikes/spike_ui_simulate.py` + PNG-дампы; ручной прогон `--simulate --repl` (UI и REPL согласованы через один снапшот).
10. Обновить AGENTS.md (D2 → завершено, скриншоты/метрики из spike).

---

## 7. Риски

| Риск | Вероятн. | Митигация |
|------|----------|-----------|
| Конфликт Upper Row: табы экранов vs банки энкодеров | Высокая (решается в плане) | План §1.3.6: Push 2-путь уходит в UI, LCXL3-путь сохранён; `update_bank_leds` для Push 2 заменён на табы |
| DEN меняет звук непредсказуемо для chord_source | Средняя | density не применяется к chord_source/cc_only (DTO «—»); формула с клампом и тестами |
| CC-оси дёргают синт при случайном повороте | Средняя | Троттлинг 30 Hz (B3) уже в порту; ось шлёт только по факту поворота, значение не «догоняет» при route |
| Энкодерная карта неудобна вживую | Средняя | Все назначения — константы в одном модуле; правка одной строкой; spike-прогон с эмулятором до железа |
| View-модели разрастутся и продублируют StatusSnapshot | Средняя | Единый источник — StatusSnapshot; view собирается контроллером, DTO только строки/числа |
| Render-thread читает UiState без замка | Низкая | Писатель один (main loop drain); документировано в ui_state.py |
| Регрессия REPL при расширении TrackSummary/EngineControl | Низкая | Аддитивные поля/методы; существующие тесты REPL должны пройти без изменений |

---

## 8. Определение «готово»

- [ ] 6 навигационных поверхностей: TRACKS (банк 8 + Page Left/Right + заголовок страницы), TRACK (SRC/SRC2/GATE/DEN/MUT/макро-CC), GLOBAL (Root/Scale/Swing), SYNC (source/device/tempo/status, pending и error видны), PORTS (список/назначение/SCAN) + глобальный статус-бар Root/Scale/BPM/порт
- [ ] Создание дорожки одним нажатием (Duplicate) с дефолтами; удаление — Shift+Delete со стратегией B
- [ ] 5 макро-осей: DEN (density в generators, с тестами), MUT (mutate), TONE/SPACE/DEPTH (CC через CCMap+троттлер, конфигурируемый маппинг)
- [ ] Все команды — через EngineControl (мок в тестах); MIDI-поток не трогает движок (очередь → main loop)
- [ ] Dirty-инвалидация по регионам сохранена (D1): типичный тик экрана ≤ 2 мс compose
- [ ] simulate-прогон spike_ui_simulate.py: сценарии 1–6 PASS, PNG-кадры осмысленны
- [ ] Расширения аддитивны: все существующие тесты (1012) passed без правок ожиданий
- [ ] ruff, mypy, black чисто на новых/изменённых файлах
- [ ] AGENTS.md обновлён (D2 → завершено)
- [ ] (При доступе к железу) ручной прогон на Push 2: табы, LED, энкодеры, 25 fps без артефактов

---

## 9. Не-цели D2 (явно)

- **Пады и их LED** — D3 (CHORDS/NOTES/MORPH/DRUM-режимы); в D2 пад-ивенты принимаются и игнорируются (debug-лог)
- **DRUM-экран 256 ячеек и плейхед** — D3
- **Сохранение выбора клока/портов в config.yaml** — E1 (экраны в D2 работают в рантайме, как `ports switch` в REPL)
- **LCXL3 UI/банки** — без изменений; `EncoderHandler` не трогаем для LCXL3
- **Полноэкранный TUI / удалённый UI** — F1 покрывает терминал
- **Перенос/переименование `EngineControl` из `../src/repl`** — косметика, отдельной задачей
