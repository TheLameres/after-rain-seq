# Расширенный план D1: Рендерер дисплея (renderer.py)

> Задача D1 из AGENTS.md (Фаза 4). Выход: `renderer.py` — примитивы на numpy,
> dirty rects, 25 fps с запасом. Зависимости: A2 (дисплей и USB-слой из push2-m8).

---

## 1. Анализ: что есть и что нужно построить

### 1.1. Что уже есть (наследие push2-m8, пережившее вырезание A2)

| Компонент | Файл | Статус |
|-----------|------|--------|
| USB-драйвер дисплея | `../src/devices/push2/push2_display.py` (`Push2UsbDisplay`) | ✅ Работает: open/send_frame/clear, XOR-scramble, BGR565 |
| Композитор кадра | `../src/devices/push2/display.py` (`PushDisplay`) | ⚠️ Работает, но whole-frame PIL-перерисовка |
| Драйвер render-loop | `../src/app/display.py` (`DisplayRenderer`) | ✅ Тикает по `frame_interval`, строит `DisplayState` |
| Замеры железа | `../spikes/spike_display.py` | ✅ 102 fps реальный, 9.82 мс/кадр (сырая отправка), 51.8 °C |

### 1.2. Что НЕ даёт текущее решение (пишем сами)

| Проблема | Почему это важно |
|----------|------------------|
| Перерисовка всего кадра при любом изменении | Любой тик (BPM, плейхед, значение энкодера) тянет полный PIL-проход + полную конвертацию RGB→BGR565 |
| Нет регионной инвалидации | D2 (экраны) и D3 (drum-сетка 256 ячеек + плейхед) будут дёргать кадр каждый тик — whole-frame модель не масштабируется |
| `numpy.zeros` 327 КБ + transpose + tobytes на каждый кадр | До 8 МБ/с аллокаций на 25 fps; лишняя работа GC и кеша |
| Текст растеризуется PIL на каждый кадр заново | `draw.text` в горячем цикле; одинаковые глифы считаются тысячи раз за сет |
| Нет библиотеки примитивов | Экраны D2 придётся рисовать напрямую PIL/numpy — дублирование и рассинхрон |
| fps в конфиге 15 | Цель по плану — 25 fps (читаемость анимации плейхеда, прокрутки) |

### 1.3. Ключевые находки при чтении кода

1. **Проводной протокол — только полный кадр, diff-кадров нет** (проверено по официальному мануалу Ableton `push-interface`, раздел *Display Interface Protocol*). Заголовок — фиксированные 16 байт `{FF CC AA 88, 0×12}` без полей региона/смещения; все прочие форматы заголовков — «reserved» и опасны: *«may compromise the device function, up to making the device unusable, requiring to open the case and reflash the firmware»*. Кадр отображается **только при получении полных пиксельных данных** (640 буферов × 512 байт, построчно, 1920 B пиксели + 128 B filler на строку). Дисплей работает на 60 fps, double-buffered: повторяет последний полный кадр, при тишине **2 секунды** гаснет в чёрный. **Следствия для D1:**
   - dirty rects — CPU-side оптимизация compose/encode; USB-трафик они не сокращают (архитектура плана это и закладывает);
   - **постоянная отправка 25 fps не нужна**: дисплей сам держит картинку. Режим отправки — по факту dirty + keepalive-кадр раз в ~1 с (запас до 2-секундного таймаута гашения). Экономия USB и CPU на статичных экранах;
   - 60 fps — потолок самого дисплея; таргет 25 fps на обновления (плейхед, анимация) в пределах спецификации.
2. **`_encode_frame()` аллоцирует на каждый вызов:** `numpy.zeros((1024, 160))` → transpose → flatten → два byteswap → XOR → `tobytes()`. Всё это можно делать в два предвыделенных буфера без единой аллокации в горячем цикле.
3. **`PushDisplay` уже имеет `_dirty`-флаг** и пропускает пересборку кадра при неизменном состоянии — модель «инвалидируй, а не рисуй вслепую» уже заложена, расширяем её до регионов.
4. **Конвертация RGB→BGR565** (`display.py:226-231`) — векторизованный numpy-проход по всему кадру (~153 600 px), при dirty rects делаем его только по грязным прямоугольникам.
5. **`on_frame`-колбэк (эмулятор экрана в simulate-режиме)** сейчас получает PIL-Image. После переезда на BGR565-буфер превью делаем обратной конвертацией 565→888 (потеря точности для эмулятора некритична) — только в simulate-режиме.
6. **Шрифты:** в репозитории нет ассетов шрифтов; `_try_load_font()` (унаследован из push2-m8) грузит системные TTF (Menlo/DejaVu/Liberation) с fallback на `ImageFont.load_default()`. Формулировка «шрифты из push2-m8» в D1 относится к этому механизму — он сохраняется, но растеризация уходит в глиф-кеш (см. 3.4).

---

## 2. Архитектура

### 2.1. Файлы

```
src/devices/push2/
├── renderer.py        # НОВЫЙ: FrameBuffer, DirtyTracker, primitives, GlyphCache
├── push2_display.py   # ИЗМЕНЁННЫЙ: предвыделенный encoder, без аллокаций в цикле
├── display.py         # ИЗМЕНЁННЫЙ: PushDisplay становится scene composer поверх renderer
└── ...
tests/
├── test_renderer_dirty.py    # НОВЫЙ: DirtyTracker
├── test_renderer_primitives.py  # НОВЫЙ: примитивы, clipping, цвета
├── test_renderer_glyph_cache.py # НОВЫЙ: кеш глифов
└── test_push2_display.py   # СУЩЕСТВУЕТ?: encoder roundtrip (перенос/дополнение)
spikes/
└── spike_renderer_bench.py # НОВЫЙ: стоимость кадра нового пайплайна
```

### 2.2. Слои и зависимости

```
app/display.py (DisplayRenderer, render loop)
  └── devices/push2/display.py (PushDisplay — scene composer: раскладка + виджеты)
        └── devices/push2/renderer.py (FrameBuffer + примитивы + DirtyTracker + GlyphCache)
              └── PIL (только внутри GlyphCache, растеризация по одному разу на глиф)
  └── devices/push2/push2_display.py (Push2UsbDisplay — wire format, USB)
```

**Никаких циклов.** `renderer.py` не знает про USB, сцены и устройства — только numpy + PIL.

### 2.3. Пайплайн кадра

```
update_state(...)                     # снапшот состояния, compare → invalidate(rect)
       │
       ▼
PushDisplay.compose()                 # только грязные виджеты → renderer primitives
       │                                (fill_rect / text / bar / grid_cell …)
       ▼
FrameBuffer.pixels (960×160, uint16 BGR565) + DirtyTracker (список rect)
       │
       ▼
Encoder.encode(dirty_rects)           # BGR565 → wire bytes в предвыделенный буфер
       │                                (только если dirty; transpose+XOR+fill разом)
       ▼
usb.write(header); usb.write(payload) # 2 USB-write, как сейчас
```

По USB всегда уходит полный кадр (протокол не даёт иного), но **шлём его не на каждом тике, а по факту изменений**: дисплей double-buffered и повторяет последний кадр, гашение только после 2 с тишины. Режим: `dirty → encode+send`, плюс keepalive-кадр раз в ~1 с. Тик 25 fps остаётся верхней границей частоты обновлений (плейхед, анимация), а не обязательным потоком. Dirty rects работают на этапах compose и encode.

---

## 3. Детальный дизайн

### 3.1. `DirtyTracker` — `renderer.py`

**Назначение:** учёт грязных прямоугольников кадра: слияние пересекающихся, отсечение по границам кадра, защита от взрыва числа rect.

```python
Rect = tuple[int, int, int, int]  # (x0, y0, x1, y1) — half-open [x0,x1) × [y0,y1)

class DirtyTracker:
    """Реестр грязных регионов кадра."""

    def __init__(self, width: int, height: int, max_rects: int = 64) -> None:
        self._width, self._height = width, height
        self._rects: list[Rect] = []
        self._max_rects = max_rects
        self._full = False  # «грязен весь кадр» — стоп-слиянию

    def invalidate(self, x: int, y: int, w: int, h: int) -> None:
        """Отметить регион грязным. Отсекает по границам кадра, сливается
        с существующими; при переполнении max_rects — деградирует к full-frame."""

    def rects(self) -> tuple[Rect, ...]:
        """Текущий набор (защищённая копия)."""

    def take(self) -> tuple[Rect, ...]:
        """Забрать и очистить (вызывается после encode)."""

    def clear(self) -> None: ...
    @property
    def is_full(self) -> bool: ...
```

**Ключевые решения:**

| Аспект | Решение | Почему |
|--------|---------|--------|
| Формат rect | half-open `(x0, y0, x1, y1)` | Один согласованный контракт, нет ±1 багов |
| Слияние | объединять пересекающиеся/смежные (порог по площади) | 200 грязных ячеек drum-сетки → 1 rect строки |
| Переполнение | `max_rects` → `_full = True` | Дешёвая деградация, а не O(n²) слияния |
| Отсечение | clamp в границы кадра при invalidate | Примитивы не обязаны проверять границы сами |

### 3.2. `FrameBuffer` + примитивы — `renderer.py`

**Назначение:** единственное владение пикселями и единственный API рисования для всех экранов D2.

```python
class FrameBuffer:
    """Буфер кадра 960×160 uint16 BGR565 + примитивы рисования."""

    def __init__(self, width: int = 960, height: int = 160) -> None:
        # Храним в (W, H) — тот же порядок, что ожидает wire-format encoder.
        self.pixels = numpy.zeros((width, height), dtype=numpy.uint16)
        self.dirty = DirtyTracker(width, height)

    # ── примитивы (каждый помечает dirty) ──
    def fill(self, color: int) -> None: ...                    # весь кадр
    def fill_rect(self, x, y, w, h, color: int) -> None: ...
    def rect(self, x, y, w, h, color: int, width_px: int = 1) -> None: ...  # контур
    def hline(self, x, y, w, color: int) -> None: ...
    def vline(self, x, y, h, color: int) -> None: ...
    def blit(self, patch: numpy.ndarray, x: int, y: int) -> None: ...  # uint16 (w,h) → (x,y)

    # ── текст ──
    def text(self, x, y, s, font_key: str, color: int) -> int:
        """Нарисовать строку глифами из кеша. Возвращает ширину в px."""

    def text_width(self, s: str, font_key: str) -> int: ...
    def text_centered(self, cx, y, s, font_key, color) -> None: ...

    # ── высокоуровневые (используются виджетами D2) ──
    def bar(self, x, y, w, h, value: int, maximum: int = 127, color, bg) -> None: ...
    def grid_cell(self, x, y, w, h, color, lit: bool, head: bool = False) -> None: ...
```

**Правила примитивов:**

1. Каждый примитив сам инвалидирует свой bounding box — вызывающий код не думает о dirty.
2. Все координаты int, отсечение — в `DirtyTracker` и на уровне slice (numpy сам отсекает при корректных границах; выход за кадр не падает, а clamp'ится в invalidate).
3. Цвет — уже сконвертированный BGR565 `uint16` (конвертер `_rgb_to_bgr565` переезжает в renderer, остаётся module-level helper).
4. `blit` — основа текста и будущих иконок; patch готовится кем-то ещё (GlyphCache) в правильном dtype/shape.

### 3.3. Палитра и цвет — `renderer.py`

```python
def rgb_to_bgr565(r: int, g: int, b: int) -> int: ...
def lpp3_to_bgr565(color_idx: int) -> int: ...   # переезд из display.py

class Colors:  # именованные константы проекта, BGR565
    BG, WHITE, GRAY, DIM, ...  # значения из display.py переносятся как-is
```

Существующие RGB-кортежи из `display.py` (строки 37–52) переносятся сюда один-в-один, чтобы визуал не изменился; новые цвета добавляются по мере D2.

### 3.4. `GlyphCache` — `renderer.py`

**Назначение:** PIL растеризует каждый глиф ровно один раз; горячий цикл — чистый numpy-blit.

```python
class GlyphCache:
    """Кеш растеризованных глифов: (char, font_key, color) → (patch, advance)."""

    def __init__(self, fonts: dict[str, ImageFont.FreeTypeFont], max_entries: int = 512) -> None:
        self._fonts = fonts
        self._cache: OrderedDict[tuple[str, str, int], tuple[numpy.ndarray, int]] = OrderedDict()
        self._max = max_entries

    def glyph(self, ch: str, font_key: str, color: int) -> tuple[numpy.ndarray, int]:
        """uint16 patch (w, h) в BGR565 + ширина advance. Miss → растеризуем PIL,
        кладём в LRU. Patch дополнен до целого числа px по ширине."""
```

**Ключевые решения:**

| Аспект | Решение | Почему |
|--------|---------|--------|
| Ключ кеша | `(char, font_key, color)` | Цвет в ключе — кадр 565, перекраска = перерастеризация; набор цветов текста мал |
| Растеризация | `ImageFont.getmask` → numpy → сдвиг в BGR565 + маска | Один PIL-вызов на глиф, не на кадр |
| LRU | `OrderedDict`, `max_entries=512` | Верхняя граница памяти; типичный набор < 200 глифов |
| Fallback шрифта | цепочка системных TTF как сейчас + `load_default()` | Код из push2-m8 сохраняется без изменений |

### 3.5. Encoder — `push2_display.py`

**Назначение:** убрать аллокации из горячего пути; API совместим с текущим.

```python
class FrameEncoder:
    """BGR565 (960,160) → wire bytes. Два предвыделенных буфера, ноль аллокаций."""

    def __init__(self) -> None:
        self._prepared = numpy.zeros(_FRAME_WIDTH * LINES, dtype=numpy.uint16)

    def encode(self, frame: numpy.ndarray) -> memoryview:
        """frame (960,160) uint16 → memoryview готового payload.
        Записывает во внутренний буфер; валиден до следующего encode()."""
```

Изменения в `Push2UsbDisplay.send_frame()`: внутри держит `FrameEncoder`, шлёт `memoryview` (usb.core принимает buffer-like). Функция `_encode_frame` остаётся как thin-обёртка для совместимости тестов либо удаляется вместе с обновлением тестов.

Оптимизация transpose: раньше `prepared.transpose().flatten()` аллоцировал; теперь `numpy.copyto(self._prepared_view_2d[...], frame.T)` в предвыделенный 2D-view, затем in-place byteswap + XOR (уже in-place сейчас). Итог: 0 аллокаций размером с кадр.

### 3.6. `PushDisplay` — рефакторинг `display.py`

**Назначение:** scene composer. Владеет `FrameBuffer`, `GlyphCache`, раскладкой; `_draw_*`-методы переписываются с PIL на примитивы renderer. Публичный API (`update_state`, `render_usb`, `render_frame_only`, `set_on_frame`) **не меняется** — интеграция в `push2_device.py` и `app/display.py` нулевая.

Внутреннее:

```python
class PushDisplay:
    def __init__(self, fps=15, on_frame=None) -> None:
        self._fb = FrameBuffer()
        self._glyphs = GlyphCache(FONTS)          # FONTS — dict из _FONT_SM/MD/LG
        ...

    def _build_frame(self) -> None:
        # была: Image.new + ImageDraw + 4 метода на PIL
        # стала: по dirty-виджетам зовём примитивы; виджет = (rect, draw_fn)
```

**Виджетная декомпозиция** (закладывает D2): каждый `_draw_*` получает свой rect-инвалидатор:

| Виджет | Rect | D2-заметка |
|--------|------|-----------|
| bank_tabs | (0, 0, 960, 23) | заменится на header экрана |
| track_encoders | (0, 26, 960, 52) | 8 колонок, Page Left/Right |
| global_encoders | (0, 54, 960, 80) | 5 макро-осей |
| status_bar | (0, 138, 960, 160) | Root/Scale/BPM/порт |

Полная перерисовка (первый кадр, смена экрана в D2) — `fill(BG)` + invalidate full.

**Сравнение состояния:** `update_state` сравнивает новый снапшот с предыдущим и инвалидирует только виджеты, чьи входы изменились (сейчас: грубый `_dirty = True` на всё). Сравнение — по полям; дёшево, кадр мал.

**`on_frame` в simulate:** конвертация `pixels` (565) → RGB uint8 (H, W, 3) → `Image.fromarray`, только если колбэк установлен и кадр грязный. Для эмулятора точности 565 достаточно.

### 3.7. Конфигурация

```yaml
# config.yaml + src/config.py (AppConfig)
display_fps: 25   # было 15
```

Бюджет кадра на 25 fps = 40 мс. Ожидаемая фактическая стоимость: compose 1–3 мс + encode ~1–2 мс + USB ~10 мс (спайк: 9.82 мс) ≈ 15 мс → запас > 2.5×, на RPi 5 проверяется бенч-спайком (3.8).

### 3.8. Бенч-спайк `../spikes/spike_renderer_bench.py`

Замеряет на целевом железе (и macOS для сравнения):

1. Стоимость compose полного кадра (все виджеты) — цель ≤ 5 мс.
2. Стоимость compose «типичного тика» (плавает BPM + один энкодер) — цель ≤ 2 мс.
3. Стоимость encode (0 аллокаций) — цель ≤ 2 мс.
4. Сквозной fps при непрерывной отправке 60 с — цель ≥ 25 fps с p99-временем кадра < 40 мс.
5. CPU% процесса при 25 fps (сравнить с 15 fps baseline) — ориентир: рост CPU рендера не более чем в 1.5×.

Критерий: пункты 1–4 на RPi 5 (A1-подобный прогон 10 минут, температура в лог).

---

## 4. Краевые случаи

| Случай | Обработка |
|--------|-----------|
| Виджет выходит за границу кадра | clamp в `DirtyTracker.invalidate`; slice numpy отсекает |
| > max_rects инвалидаций за кадр | деградация к full-frame (один rect) |
| USB-ошибка в середине отправки | как сейчас: лог + пропуск; следующий тик шлёт заново |
| Дисплей отключили во время работы | `Push2UsbDisplay.send_frame` no-op при `_device is None`; reconnect — зона ответственности device-слоя, не renderer |
| Символа нет в шрифте (нестандартный юникод) | PIL отдаёт `.notdef` — визуально пустой глиф, не исключение |
| Шрифт не найден ни в одной цепочке | `load_default()` — как сейчас |
| GlyphCache переполнен | LRU-вытеснение, рост задержки только на miss |
| `update_state` зовут из чужого потока | сохраняем `threading.Lock` вокруг снапшота (как сейчас) |
| Первый кадр / смена экрана (D2) | `fill(BG)` + invalidate full — явный API `reset()` |
| Мутация цвета 565↔888 в превью | округление при обратной конвертации; только simulate, на железе не используется |

---

## 5. Тестирование

### Матрица тестов

| Тест | Что проверяет |
|------|--------------|
| `test_dirty_single_rect` | invalidate → rects() возвращает его |
| `test_dirty_merge_overlap` | два пересекающихся → один объединённый |
| `test_dirty_merge_adjacent` | смежные по горизонтали сливаются |
| `test_dirty_clamp` | rect за границей кадра обрезается |
| `test_dirty_overflow_degrades_full` | > max_rects → is_full |
| `test_dirty_take_clears` | take() → пусто |
| `test_fill_rect_pixels` | пиксели по углам и центру rect верные |
| `test_rect_outline` | контур 1px: 4 стороны залиты, внутри пусто |
| `test_primitives_mark_dirty` | каждый примитив инвалидирует свой bbox |
| `test_bar_fill_ratio` | value 0/64/127 → ширина 0/половина/максимум |
| `test_grid_cell_lit_unlit_head` | три состояния ячейки — три разных паттерна пикселей |
| `test_glyph_cache_hit` | дважды same key → одинаковый объект patch (identity) |
| `test_glyph_cache_lru` | overflow вытесняет самый старый |
| `test_glyph_cache_color_in_key` | другой color → другой patch |
| `test_text_width_monospace` | ширина строки = Σ advance (SM-шрифт) |
| `test_encoder_matches_legacy` | `FrameEncoder.encode(frame)` байт-в-байт == старый `_encode_frame(frame)` (roundtrip-регрессия) |
| `test_encoder_no_alloc` | повторный encode не меняет id внутреннего буфера |
| `test_pushdisplay_api_stable` | update_state/render_frame_only работают без USB (smoke, simulate) |
| `test_pushdisplay_partial_invalidate` | изменение только BPM трогает только status_rect |
| `test_bgr565_values` | rgb(255,0,0) → 0xF800 и т.п. |

Порядок: dirty → primitives → glyph cache → encoder → PushDisplay-рефактор + его тесты → bench-спайк.

---

## 6. Порядок реализации

1. **`renderer.py`**: `DirtyTracker`, `rgb_to_bgr565`, `Colors`, `FrameBuffer` + примитивы, `GlyphCache` — чистый numpy/PIL, без связей с остальным проектом.
2. Тесты renderer (dirty, primitives, glyph cache).
3. **`push2_display.py`**: `FrameEncoder` с предвыделенными буферами + roundtrip-тест против legacy `_encode_frame`.
4. **`display.py`**: `PushDisplay` на примитивах; сравнение снапшотов; widget-rects; превью 565→888 для `on_frame`.
5. Конфиг: `display_fps: 25`.
6. Полный прогон тестов (`pytest`), `ruff`, `mypy`, `black`.
7. `../spikes/spike_renderer_bench.py` — бенч на macOS; на RPi 5 — при следующем доступе к железу (не блокер, критерии зафиксированы в 3.8).
8. Обновить AGENTS.md (D1 → завершено, метрики из бенча).

---

## 7. Риски

| Риск | Вероятн. | Митигация |
|------|----------|-----------|
| PIL-растеризация глифов медленнее ожидания на RPi | Средняя | Глиф-кеш: растеризация разово; miss-стоимость амортизируется |
| Обратная конвертация 565→888 для эмулятора «грязнит» код | Низкая | Изолирована в `render_frame_only`, на железе не вызывается |
| Регрессия визуала при переносе цветов | Средняя | Цвета переносятся константами; тест пикселей углов rect |
| Encoder roundtrip не совпадёт с legacy | Низкая | Roundtrip-тест до рефактора compose; расхождение = баг переноса |
| 25 fps съедает CPU вместе с движком (24.9% baseline) | Низкая | Бюджет 15 мс/кадр vs 40 мс; бенч-спайк с CPU%-замером; при нехватке — dirty-only отправка (код региона уже есть) |
| Dirty-логика даёт артефакты (не стёртый след) | Средняя | Правило: виджет перерисовывает весь свой rect; тест partial_invalidate |

---

## 8. Определение «готово»

- [ ] `renderer.py`: примитивы numpy, DirtyTracker, GlyphCache — с тестами
- [ ] Encoder без аллокаций в горячем цикле, roundtrip-равенство с legacy
- [ ] `PushDisplay` на примитивах, публичный API не изменился
- [ ] Частичная инвалидация: изменение одного виджета не перерисовывает остальные
- [ ] `display_fps: 25`, стоимость типичного тика ≤ 2 мс (compose) + ≤ 2 мс (encode)
- [ ] Сквозной fps ≥ 25 с запасом; визуал идентичен текущему
- [ ] Отправка по факту dirty + keepalive раз в ~1 с (спека: гашение через 2 с тишины); статичный экран не гоняет USB
- [ ] ruff, mypy, black чисто; все тесты passed
- [ ] AGENTS.md обновлён (D1 → завершено)
- [ ] (При доступе к RPi) бенч-спайк подтверждает цифры на целевом железе
