## Коротко: две независимые подсистемы

Экран Push 2 — это не MIDI, а отдельный USB bulk-интерфейс. Поэтому «инициализация экрана» состоит из двух вещей,
которые надо сделать **обе**:

1. **Поднять backlight** по MIDI-sysex — без этого кадры принимаются, но панель остаётся чёрной.
2. **Открыть USB bulk-endpoint и гнать в него кадры** в бинарном формате.

Если сделать только второе (как это часто и происходит при первом запуске кода на `push2-python`), экран будет выглядеть
«мёртвым».

---

## Шаг 1. USB: найти и захватить устройство

```c
#define ABLETON_VENDOR_ID 0x2982
#define PUSH2_PRODUCT_ID  0x1967
#define PUSH2_BULK_EP_OUT 0x01
```

Push 2 — композитное устройство: интерфейс 0 содержит и MIDI, и generic bulk-интерфейс для дисплея. Порядок:

```
libusb_init → найти по VID/PID → libusb_open → libusb_claim_interface(handle, 0)
```

Всё, дальше нужен только `EP 0x01` (OUT) на запись. Освобождение — `release_interface` + `close`.

На Linux: нужны udev-права (`sudo` не обязателен, если правило прописано), а если устройство уже занято ядром/другим
процессом — `libusb_detach_kernel_driver`.

## Шаг 2. Backlight: sysex `0x08`

Из мануала, раздел *Display Backlight*:

> To see something drawn on the display, the display backlight LEDs must be turned on.

Формат: `F0 00 21 1D 01 01 <ID> <args...> F7`, где `ID = 0x08`, аргументы — яркость 14-битным значением (LSB 7 бит + 1
старший бит):

```
F0 00 21 1D 01 01 08 7F 01 F7   → яркость 255 (максимум)
F0 00 21 1D 01 01 08 40 00 F7   → яркость 64
```

Диапазон 0–255, где 0 = выключено. Прочитать текущее значение — `0x09` (без аргументов, ответ `... 09 40 00 F7`).

Важный нюанс из мануала: **на шине питания USB (без внешнего БП) яркость автоматически ограничивается до 100**, и
реальная мощность подсветки получается ~7% от максимума. То есть «255» на USB — это не 255.

Это чисто MIDI-сообщение, отправляется через MIDI OUT порт Push (Live-порт или User-порт, смотря какой у вас открыт).

## Шаг 3. Формат кадра

Каждый кадр = **16-байтовый заголовок + 327 680 байт пикселей**.

**Заголовок** (фиксированный, 16 байт):

```
FF CC AA 88 00 00 00 00 00 00 00 00 00 00 00 00
```

**Пиксели:** 160 строк × 960 пикселей × 16 бит. Каждая строка передаётся как 2048 байт: 1920 байт данных + **128 байт
filler-мусора** (чтобы границы строк не попадали в середину 512-байтовых USB-буферов). Пиксели в строке — слева направо,
строки — сверху вниз. Итого 160 × 2048 = 327 680 = 640 буферов по 512 байт.

**Кодировка цвета** — 16-бит, little-endian:

```
бит:  15 14 13 12 11 | 10 09 08 07 06 05 | 04 03 02 01 00
       b4 b3 b2 b1 b0 | g5 g4 g3 g2 g1 g0 | r4 r3 r2 r1 r0
```

То есть **BGR565**, не RGB565.

**XOR-маскирование** — обязательный шаг, про который легко забыть: перед отправкой данные ксорятся 32-битным паттерном
`0xFFE7F3E7` (little-endian, т.е. первый байт ^= `0xE7`, второй ^= `0xF3`, третий ^= `0xE7`, четвёртый ^= `0xFF`, и так
по кругу). Это «signal shaping pattern»; без него картинка будет мусорной.

**Отправка:** заголовок одним bulk-трансфером, затем данные — можно одним большим трансфером (push2-python так и
делает), можно кусками по 512 байт или по 16 КБ. Мануал предупреждает: **другие размеры/форматы сообщений
зарезервированы** (диагностика, прошивка), и случайная отправка зарезервированного сообщения может превратить устройство
в кирпич с необходимостью вскрывать корпус и перепрошивать. Не экспериментируйте с header'ом.

## Шаг 4. Тайминги

- Дисплей работает на **60 fps**, кадры double-buffered.
- Кадр показывается целиком, когда приняты все пиксельные данные.
- Если следующий кадр не пришёл вовремя — повторяется последний.
- **Если кадр не приходит дольше 2 секунд — экран гаснет в чёрный.** Поэтому нужен непрерывный цикл отправки (или
  `display_last_frame()` в push2-python).

---

## Как это выглядит в `push2-python`

Библиотека намеренно делает **ленивую инициализацию**: `Push2Display.configure_usb_device()` не вызывается из
`Push2.__init__()` — только в момент первой реальной отправки кадра (`send_to_display`), и не чаще
`PUSH2_RECONNECT_INTERVAL = 0.05` сек.

Внутри `configure_usb_device()` происходит:

```python
usb_device = usb.core.find(idVendor=0x2982, idProduct=0x1967)
device_configuration = usb_device.get_active_configuration()
interface = device_configuration[(0, 0)]
out_endpoint = usb.util.find_descriptor(interface, custom_match=...
ENDPOINT_OUT)
# проверка живучести: шлём заголовок + чёрный кадр
out_endpoint.write(DISPLAY_FRAME_HEADER, 1000)
out_endpoint.write(prepared_black_frame, 1000)
```

Если проверочная запись не падает с `USBError` — endpoint считается живым, взводится `ACTION_DISPLAY_CONNECTED`, иначе
`usb_endpoint = None` и попытка повторится при следующем кадре. Публичная проверка состояния —
`push.display_is_configured()`.

Конвейер подготовки кадра в `prepare_frame()` — ровно по спеке: при необходимости конвертация в BGR565 → раскладка в
`(960 + 64) × 160` с нулевым filler'ом → transpose+flatten → `byteswap()` в little-endian → XOR с
`NP_DISPLAY_FRAME_XOR_PATTERN` (массив `[0xE7F3, 0xE7FF]` повторённый).

Два подводных камня в README, на которые стоит обратить внимание:

1. **README говорит, что BGR565-кадр имеет форму `910x160`** — это опечатка. В коде ассерт строгий: `shape[0] == 960`,
   `shape[1] == 160`. Верхняя граница полосы filler — не часть вашего массива.
2. **`push2-python` вообще не выставляет яркость подсветки** — ни в `__init__`, ни в `configure_usb_device`. Sysex
   `0x08` там не отправляется нигде. Поэтому если у вас экран не загорается, хотя `display_is_configured()` возвращает
   `True` и кадры уходят без ошибок — это именно оно, надо вручную отправить `F0 00 21 1D 01 01 08 7F 01 F7` через
   `push.midi_out_port` (или через любой MIDI-порт Push).

---

## Минимальный рабочий цикл

```python
import usb.core, usb.util, numpy as np

VID, PID, EP = 0x2982, 0x1967, 0x01
HEADER = bytes([0xFF, 0xCC, 0xAA, 0x88] + [0] * 12)
W, H, FILLER = 960, 160, 128


def open_display():
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None: raise RuntimeError("Push 2 not found")
    cfg = dev.get_active_configuration()
    ep = usb.util.find_descriptor(cfg[(0, 0)],
                                  custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
                                                         == usb.util.ENDPOINT_OUT)
    return ep


def send_frame(ep, bgr565):  # bgr565: (160, 960) uint16
    line = np.zeros((H, W + FILLER // 2), dtype=np.uint16)
    line[:, :W] = bgr565
    buf = line.flatten().byteswap()  # little-endian
    pattern = np.frombuffer(b"\xE7\xF3\xE7\xFF" * (len(buf) // 2), dtype="<u2")
    buf = (buf.view("<u2") ^ pattern).tobytes()
    ep.write(HEADER, 1000)
    ep.write(buf, 1000)  # 327680 bytes
```

И параллельно, один раз при старте, sysex на подсветку:

```python
midi_out.send_message([0xF0, 0x00, 0x21, 0x1D, 0x01, 0x01, 0x08, 0x7F, 0x01, 0xF7])
```

Дальше — цикл с отправкой не реже ~2 раз в секунду, иначе панель погаснет.