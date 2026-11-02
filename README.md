# after-rain-seq

Генеративный MIDI-хост для Ambient Dub Techno: гармонический движок (лад, войсинги,
аккордовый граф), drum-машина (евклидовы ритмы, 16 lane GM), непрерывная мутация
паттернов — с управлением с Ableton Push 2 или из терминала. Работает на Raspberry Pi 5
(Raspberry Pi OS 64-bit, Ubuntu) и на macOS.

- **Клок:** три источника с переключением на лету — internal, MIDI Clock, Ableton Link
- **Порты:** обнаружение MIDI-устройств по имени, hot-plug, перенаправление в рантайме
- **CC-автоматизация:** логические имена параметров → номера CC, троттлинг 30 Гц
- **REPL:** мониторинг и контроль из терминала (удобно по SSH с RPi)

## Требования

- Python ≥ 3.13
- [uv](https://docs.astral.sh/uv/) — управление зависимостями
- MIDI-бэкенд: `python-rtmidi` (входит в зависимости)
- Опционально: Ableton Link — `uv sync --extra link`

## Быстрый старт

```bash
uv sync                      # установить зависимости
uv run python -m src.main --list-ports        # какие MIDI-порты видит система
uv run python -m src.main                     # headless-режим (config.yaml создастся сам)
uv run python -m src.main --simulate          # без железа (эмулятор Push 2)
uv run python -m src.main --repl              # + интерактивный терминал
```

Полный список флагов: `--config FILE`, `--log-level LEVEL`, `--log-layer NAME=LEVEL`
(повторяемый, Spring Boot-стиль), `--simulate`, `--list-ports`, `--repl`.

## Конфигурация

При первом запуске рядом с `--config` (по умолчанию `config.yaml` в корне проекта)
создаётся файл с дефолтами. Все секции валидируются pydantic: ошибка в конфиге —
понятное сообщение и выход, движок с невалидным конфигом не стартует.

### `logging`

```yaml
logging:
  level:
    root: INFO
    src.sync: DEBUG        # per-layer override, ключи — имена логгеров
```

Уровни: `TRACE`, `DEBUG`, `INFO`, `WARN`, `ERROR`, `OFF`.
CLI `--log-level` и `--log-layer` перекрывают эти значения на один запуск.

### `sync` — клок и транспорт

```yaml
sync:
  enabled: true
  clock_source: "internal"   # internal | midi | link (стартовый источник)
  midi_clock_device: null    # имя входного MIDI-порта для MIDI Clock;
                             # null — взять из env ISOBAR_DEFAULT_MIDI_IN
  bpm: 120.0                 # 20..300 — для internal и link
  swing_amount: 0.0          # 0.0..1.0, свинг длительностями (не wall-clock)
```

Переключение источника в рантайме (кнопкой или командой `clock source midi`)
квантуется на ближайшую долу и сопровождается `all_notes_off` — без разрыва фазы.

### `ports` — MIDI-порты ⭐

См. раздел «Настройка портов» ниже.

### `cc_map` — логические имена CC

```yaml
cc_map:
  default:                   # глобальный маппинг: имя → номер CC
    filter: 74
    resonance: 71
    reverb: 91
    delay: 93
    delay_feedback: 94
    mod_wheel: 1
    volume: 7
    pan: 10
  ports:                     # переопределения и опции per-port
    "Синт A":
      filter: 22             # тот же параметр — другой CC на этом порту
      cutoff:                # полный вариант: CC + инверсия + диапазон
        cc: 74
        invert: true
        range: [20, 110]
    "LCXL3":
      _no_automation: true   # не слать CC-автоматизацию на этот порт вообще
```

Генераторы шлют автоматизацию по именам (`filter`, `resonance`, …). Резолвинг:
переопределение порта → `default` → ошибка при загрузке конфига. Поверх маппинга
работает троттлинг 30 Гц по ключу `(порт, канал, CC)` — DIN-шина не забивается.

### `drum` — drum-машина

```yaml
drum:
  preview_on_select: true    # предпрослушка lane при выборе
  preview_velocity: 100      # 1..127
  mutate_min_seconds: 8.0    # интервал мутации паттерна, сек (1..120)
  mutate_max_seconds: 16.0   # (1..300)
```

### `mutation` — эволюция паттернов

```yaml
mutation:
  enabled: true
  mutate_min_seconds: 8.0    # 1..120
  mutate_max_seconds: 16.0   # 1..300
  default_mutate: 0.5      # стартовое значение mutate для новых дорожек (0..1)
  drift_step_gate: 0.05      # макс. смещение gate за одну мутацию (0..0.5)
  drift_step_density: 0.1    # макс. смещение density
  drift_step_register: 1.0   # макс. смещение register (полутона)
```

Мутация обратима: `freeze` замораживает текущее состояние одной кнопкой,
деградация возвращает паттерн к базовому рисунку.

### `devices` — Push 2 и Launch Control XL 3

```yaml
devices:
  push2:
    enabled: true
    simulate: false          # true — эмулятор без железа (--simulate не нужен)
    brightness: 100
    use_user_midi_port: false
    display_enabled: true
    display_fps: 15
    encoder_banks: []        # банки энкодеров (см. AGENTS.md, план D2)
    global_encoders:
      tempo: null            # номер энкодера → глобальный параметр
      swing: null
      master: null
  lcxl3:
    enabled: false
    midi_in_port_name: "LCXL3 1 DAW Out"
    midi_out_port_name: "LCXL3 1 DAW In"
    encoder_banks: []
    faders: []
```

## Настройка портов

Проект оперирует **логическими лейблами**, которые резолвятся в физические
MIDI-порты системы. Дорожки ссылаются на лейблы, а не на имена устройств —
замена железа не требует правки сессии.

### Как происходит обнаружение

1. По `match` (регистронезависимая подстрока) порту ищется в списке имён
   системных портов.
2. Совпадение одно → порт **connected**.
3. Совпадений несколько → если задан `serial`, среди них ищется подстрока
   серийника. Не помогло — статус **ambiguous** с явным сообщением
   (никогда не угадываем).
4. Ничего не найдено → **disconnected** — дорожки на этом порту молчат,
   сессия продолжает работать.

Hot-plug: порты опрашиваются каждые ~2 с — устройство подключилось, дорожки
оживли; отключилось — `all_notes_off` и тишина.

### Пример: выход на синтезатор

```yaml
ports:
  outputs:
    - label: "main"          # как дорожки ссылаются на порт
      match: "IAC Bus 1"     # подстрока имени системного порта
      role: melodic          # melodic | drum | clock
      serial: null           # нужен только при неоднозначном match
      no_automation: false   # true — не слать сюда CC-автоматизацию
  inputs:
    - label: "clock-in"
      match: "IAC Bus 2"     # источник MIDI Clock
      role: clock
```

Смотреть, какие имена видит система: `uv run python -m src.main --list-ports`.
На macOS для тестов включите IAC Driver (Audio MIDI Setup → MIDI Studio →
IAC Driver, создайте шину) — имена шин появятся в выводе.

### Пример: несколько синтезаторов с похожими именами

```yaml
ports:
  outputs:
    - label: "synth-a"
      match: "USB MIDI"      # оба устройства матчатся…
      serial: "A12"          # …serial выбирает нужное
    - label: "synth-b"
      match: "USB MIDI"
      serial: "B77"
```

Если `serial` не задан и match неоднозначен — порт получит статус `ambiguous`,
а в поле `error` будет список кандидатов: добавьте `serial`.

### Правила ролей и автоматизации

- `role` — метка для человека и будущих экранов Push 2; на маршрутизацию
  MIDI сейчас не влияет.
- `no_automation: true` — для контроллеров типа Launch Control XL 3,
  которым CC от генераторов не нужен.
- Drum-дорожки шлют на канал 10; мелодические — на свои каналы дорожек.

### Рантайм: переключение без рестарта

В REPL (`--repl`):

```
ars> ports                    # текущее состояние всех лейблов
ars> ports scan               # принудительный rescan
ars> ports switch main "USB MIDI"   # перенаправить лейбл на другое устройство
```

`ports switch` меняет только память процесса: `config.yaml` не трогается,
после рестарта восстановится конфиг. Заявка применяется на ближайшем
poll (~2 с): старый порт закрывается с `all_notes_off`, новый открывается.
`serial` при switch очищается — новое устройство, новый дизамбигуатор.

### Маршрутизация дорожек

Дорожки привязываются к портам-лейблам (не к физическим устройствам):

```
ars> track add pad
ars> track route "Pad 1" main      # подключить к порту (имена с пробелами — в кавычках)
ars> track route "Pad 1" aux       # переключить: старый порт глушится all_notes_off
ars> track unroute "Pad 1"         # отключить — тишина, сессия живёт
ars> track delete "Pad 1"          # удалить вместе с движком
```

- Лейбл валидируется по сконфигурированным портам — опечатка не пройдёт.
- Если у дорожки, добавленной после старта, ещё нет движка — `route`
  создаёт его автоматически (on demand).
- Маршрутизация — рантайм-only: в `config.yaml` не пишется.
- Drum-дорожки шлют на канал 10, мелодические — на канал дорожки.

### Диагностика

| Симптом | Причина | Действие |
|---------|---------|----------|
| Порт `disconnected` | Устройство выключено / имя не совпало | `--list-ports`, поправить `match` |
| Порт `ambiguous` | Несколько устройств подходят | Добавить `serial` |
| Дорожка молчит | Её порт не connected | `ports`, проверить статус лейбла |
| CC не доходят | `no_automation: true` или не тот CC | `cc_map:` для этого лейбла |

## REPL

`uv run python -m src.main --repl` — строчный терминал (prompt_toolkit):
живой статус-бар (~2 Гц), история команд, автодополнение. Основные команды:
`status`, `start`/`stop`, `bpm`, `clock [source …]`, `ports [scan|switch …]`,
`tracks`, `track add|show|route|unroute|delete`, `root`, `scale`, `freeze`,
`evolve`, `mutations`, `logs [N]`, `help`, `exit`. Ctrl+D завершает приложение.
Удобно по SSH с Raspberry Pi. Изменения — только рантайм, конфиг не пишется.

## Разработка

```bash
uv sync                     # deps + dev (pytest, ruff, mypy, black)
uv run pytest               # 821 тест
uv run ruff check src tests
uv run black --check src tests
uv run mypy src
```

Архитектура, планы и история задач — в [AGENTS.md](AGENTS.md) и `plan_*.md`.
