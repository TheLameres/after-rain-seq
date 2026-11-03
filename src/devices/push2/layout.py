"""Типы Grid-макета экранов Push 2 (Ф1 плана «перевод всех экранов на Grid»).

Модель экрана — три полосы::

    HEADER  y   0–13   h  14   заголовок + flash (рисует screens.py)
    BODY    y  14–159  h 146   энкодеры E1–E8 (8 слотов × 120)
      UPPER y  14–31   h  18   верхний ряд кнопок (Upper Row 1–8)
      KNOBS y  32–123  h  92   энкодеры E1–E8
      LOWER y 124–141  h  18   нижний ряд кнопок (Lower Row 1–8)
      FOOT  y 142–159  h  18   под-полоса (второй ряд корней / имена дорожек)

Слот — вертикальная колонка шириной :data:`SLOT_W` под энкодером E(i+1);
индекс элемента в кортеже ``ScreenLayout.upper``/``lower``/``foot``/``encoders``
совпадает с номером слота. Короткий кортеж оставляет хвостовые слоты пустыми,
``Empty()`` — явная пустота в середине.

Типы immutable (frozen dataclass'ы): экран собирает их на каждый кадр.

Никакой логики и никаких импортов выше ``devices/`` — только примитивы
``renderer.py`` и геометрия ``widgets.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.devices.push2.renderer import Colors, FrameBuffer
from src.devices.push2.widgets import (
    BODY_Y0,
    BODY_Y1,
    SLOT_COUNT,
    SLOT_W,
    Bar,
    Label,
    Marker,
    Rect,
    SegmentTabs,
)


def _ellipsize(fb: FrameBuffer, text: str, font: str, max_w: int) -> str:
    """Обрезать *text* до ширины max_w с многоточием «…»."""
    if fb.text_width(text, font) <= max_w:
        return text
    out = text
    while out and fb.text_width(out + "…", font) > max_w:
        out = out[:-1]
    return out + "…" if out else ""

# ── Полосы тела ────────────────────────────────────────────────────────

UPPER_H = 18  # верхний ряд кнопок
LOWER_H = 18  # нижний ряд кнопок
FOOT_H = 18  # под-полоса под Lower Row

UPPER_Y0 = BODY_Y0  # 14
UPPER_Y1 = UPPER_Y0 + UPPER_H  # 32
LOWER_Y1 = BODY_Y1 - FOOT_H  # 142
LOWER_Y0 = LOWER_Y1 - LOWER_H  # 124
FOOT_Y0 = LOWER_Y1  # 142
FOOT_Y1 = BODY_Y1  # 160
KNOBS_Y0 = UPPER_Y1  # 32
KNOBS_Y1 = LOWER_Y0  # 124


@dataclass(frozen=True)
class Band:
    """Горизонтальная полоса экрана: имя + вертикальные границы (half-open)."""

    name: str
    y0: int
    y1: int

    @property
    def h(self) -> int:
        """Высота полосы в пикселях."""
        return self.y1 - self.y0


HEADER_BAND = Band("header", 0, BODY_Y0)
UPPER_BAND = Band("upper", UPPER_Y0, UPPER_Y1)
KNOBS_BAND = Band("knobs", KNOBS_Y0, KNOBS_Y1)
LOWER_BAND = Band("lower", LOWER_Y0, LOWER_Y1)
FOOT_BAND = Band("foot", FOOT_Y0, FOOT_Y1)
BODY_BAND = Band("body", BODY_Y0, BODY_Y1)


def slot_rect(slot: int, y0: int, y1: int, inset: int = 4) -> Rect:
    """Прямоугольник слота *slot* в полосе y0..y1 (с боковым отступом *inset*)."""
    return Rect(slot * SLOT_W + inset, y0, SLOT_W - 2 * inset, y1 - y0)


# ── Элементы слота ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Empty:
    """Пустой слот: ничего не рисуется (плейсхолдер позиции)."""

    def render(self, fb: FrameBuffer, rect: Rect) -> None:
        """Ничего не делать."""
        return


@dataclass(frozen=True)
class Button:
    """Кнопка ряда (Upper/Lower Row) внутри одного слота.

    active=True — белая заливка с чёрным текстом (как TabStrip).
    led — цвет точки-индикатора справа; None — точки нет.
    fit — "slot" (на всю ширину слота) или "half" (половина слота).
    """

    text: str
    active: bool = False
    color: int = Colors.GRAY
    led: int | None = None
    fit: str = "slot"

    def render(self, fb: FrameBuffer, rect: Rect) -> None:
        """Отрисовать кнопку в rect (высота полосы сохраняется)."""
        w = rect.w if self.fit == "slot" else rect.w // 2
        x, y, h = rect.x, rect.y + 1, rect.h - 2
        if self.active:
            fb.fill_rect(x, y, w, h, Colors.WHITE)
            text_color = Colors.BLACK
        else:
            fb.fill_rect(x, y, w, h, Colors.ENCODER_BG)
            fb.rect(x, y, w, h, Colors.DARK_GRAY)
            text_color = self.color
        led_w = 8 if self.led is not None else 0
        Label(self.text, "sm", text_color, "c").render(
            fb, Rect(x, y + (h - 13) // 2, w - led_w, 13)
        )
        if self.led is not None:
            Marker(self.led, size=6).render(fb, Rect(x + w - 10, y, 6, h))


@dataclass(frozen=True)
class Text:
    """Однострочная подпись в слоте (без крупного значения и бара).

    Для полосы FOOT и строки параметров: высота строки меньше метки Panel.
    ``label`` — приглушённая подпись слева, ``value`` — значение.
    """

    label: str
    value: str = ""
    color: int = Colors.GRAY
    label_color: int = Colors.DIM
    font: str = "sm"
    vcenter: bool = True  # False — прижать к верхнему краю слота
    active: bool = False  # белая заливка слота с чёрным текстом (SCALE: выбранный корень)

    def render(self, fb: FrameBuffer, rect: Rect) -> None:
        """Отрисовать «label  value» в одну строку с обрезкой по ширине."""
        line_h = 15 if self.font == "md" else 13
        if self.vcenter:
            y = rect.y + (rect.h - line_h) // 2
        else:
            y = rect.y + 2
        color = self.color
        label_color = self.label_color
        if self.active:
            # Заливка — только под строкой текста, а не весь слот (высота слота — 92 px).
            fb.fill_rect(rect.x, y - 1, rect.w, line_h + 2, Colors.WHITE)
            color, label_color = Colors.BLACK, Colors.DARK_GRAY
        x = rect.x
        if self.label:
            Label(self.label, "sm", label_color).render(fb, Rect(x, y, rect.w, 13))
            x += fb.text_width(self.label, "sm") + 6
        if self.value:
            Label(
                _ellipsize(fb, self.value, self.font, rect.x + rect.w - x),
                self.font,
                color,
            ).render(fb, Rect(x, y, max(1, rect.x + rect.w - x), line_h))


@dataclass(frozen=True)
class Tabs:
    """Полоса сегментных вкладок на всю ширину фрейма (SETUP).

    Живёт в полосе FOOT, но не по слотам: рисуется один раз на всю ширину.
    """

    labels: tuple[str, ...]
    active: str

    def render(self, fb: FrameBuffer, rect: Rect) -> None:
        """Отрисовать вкладки в rect (активная — белой заливкой)."""
        SegmentTabs(self.labels, active=self.active).render(fb, rect)


@dataclass(frozen=True)
class Panel:
    """Панель с крупным значением: метка сверху, значение ``lg``, подпись снизу."""

    label: str
    value: str
    footer: str | None = None

    def render(self, fb: FrameBuffer, rect: Rect) -> None:
        """Отрисовать панель: label / value / footer."""
        Label(self.label, "sm", Colors.GRAY, "c").render(
            fb, Rect(rect.x, rect.y + 4, rect.w, 12)
        )
        Label(self.value, "lg", Colors.WHITE, "c").render(
            fb, Rect(rect.x, rect.y + 22, rect.w, 18)
        )
        if self.footer:
            Label(self.footer, "sm", Colors.DIM, "c").render(
                fb, Rect(rect.x, rect.y + 46, rect.w, 12)
            )


@dataclass(frozen=True)
class Range:
    """Энкодер-значение с баром: метка, значение (с единицей), полоса 0..1."""

    label: str
    value: float | None  # None — значение «не применимо» («—», без бара)
    lo: float
    hi: float
    unit: str = ""

    @property
    def frac(self) -> float | None:
        """Доля заполнения бара 0..1; None — нет значения или вырожденный диапазон."""
        if self.value is None:
            return None
        span = self.hi - self.lo
        if span == 0:
            return None
        return max(0.0, min(1.0, (self.value - self.lo) / span))

    def render(self, fb: FrameBuffer, rect: Rect) -> None:
        """Отрисовать метку, значение и бар."""
        Label(self.label, "sm", Colors.GRAY, "c").render(
            fb, Rect(rect.x, rect.y + 4, rect.w, 12)
        )
        shown = "—" if self.value is None else f"{self.value:g}{self.unit}"
        Label(shown, "lg", Colors.WHITE if self.value is not None else Colors.DIM, "c").render(
            fb, Rect(rect.x, rect.y + 22, rect.w, 18)
        )
        Bar(self.frac).render(fb, Rect(rect.x + 10, rect.y + 46, max(1, rect.w - 20), 8))


@dataclass(frozen=True)
class List:
    """Список вариантов в слоте: метка сверху, до ``rows`` строк с курсором."""

    label: str
    options: tuple[str, ...]
    index: int = 0
    rows: int = 3

    def render(self, fb: FrameBuffer, rect: Rect) -> None:
        """Отрисовать окно списка вокруг index; курсор — цветом BPM_LINK."""
        Label(self.label, "sm", Colors.GRAY, "c").render(
            fb, Rect(rect.x, rect.y + 4, rect.w, 12)
        )
        if not self.options:
            Label("—", "md", Colors.DIM, "c").render(
                fb, Rect(rect.x, rect.y + 20, rect.w, 15)
            )
            return
        index = max(0, min(len(self.options) - 1, self.index))
        # Окно: держим курсор в середине, но не выходим за границы списка.
        start = max(0, min(index - self.rows // 2, len(self.options) - self.rows))
        window = self.options[start : start + self.rows]
        for row, option in enumerate(window):
            y = rect.y + 20 + row * 15
            active = start + row == index
            if active:
                Marker(Colors.BPM_LINK, size=6).render(fb, Rect(rect.x + 2, y, 6, 13))
            Label(option, "md", Colors.WHITE if active else Colors.GRAY, "c").render(
                fb, Rect(rect.x, y, rect.w, 15)
            )


@dataclass(frozen=True)
class FlowList:
    """Список, растянутый на несколько слотов: по ``rows_per_slot`` строк в каждом.

    ``slots`` — индексы слотов (могут быть не соседними: SCALE кладёт лады
    в слоты 0 и 7, оставляя 1–6 под корни). Элементы раскладываются подряд:
    первый слот забирает первые ``rows_per_slot``, второй — следующие и т.д.
    """

    items: tuple[str, ...]
    index: int = 0
    slots: tuple[int, ...] = (0, 1)
    rows_per_slot: int = 4

    def render(self, fb: FrameBuffer, rect: Rect) -> None:
        """Отрисовать свою часть элементов в rect (слот задан снаружи)."""
        self.render_slot(fb, rect, slot_pos=0)

    def render_slot(self, fb: FrameBuffer, rect: Rect, slot_pos: int) -> None:
        """Отрисовать порцию элементов для slot_pos-го слота из ``slots``.

        Сколько строк реально влезает — зависит от высоты полосы: в KNOBS
        (92 px) помещаются все ``rows_per_slot``, в FOOT (18 px) — одна.
        """
        row_h = 15
        visible = max(1, rect.h // row_h)
        chunk = self.items[
            slot_pos * self.rows_per_slot : (slot_pos + 1) * self.rows_per_slot
        ]
        for row, item in enumerate(chunk[:visible]):
            y = rect.y + row * row_h
            active = slot_pos * self.rows_per_slot + row == self.index
            if active:
                Marker(Colors.BPM_LINK, size=6).render(fb, Rect(rect.x + 2, y, 6, 13))
            Label(item, "md", Colors.WHITE if active else Colors.GRAY).render(
                fb, Rect(rect.x + 12, y, max(1, rect.w - 12), row_h)
            )


SlotItem = Button | Panel | Range | List | FlowList | Text | Empty


@dataclass(frozen=True)
class ScreenLayout:
    """Макет экрана: четыре ряда элементов, индекс = номер слота E1–E8."""

    upper: tuple[SlotItem, ...] = ()
    encoders: tuple[SlotItem, ...] = ()
    lower: tuple[SlotItem, ...] = ()
    foot: tuple[SlotItem, ...] = ()
    tabs: Tabs | None = None  # полоса вкладок на всю ширину FOOT (SETUP)
    stripe: int | None = None  # BGR565 — цветная полоса 4 px слева во всю высоту body

    def all_buttons(self) -> tuple[Button, ...]:
        """Все кнопки верхнего и нижнего ряда (для LED-карты, Ф6)."""
        return tuple(
            item
            for row in (self.upper, self.lower)
            for item in row
            if isinstance(item, Button)
        )


def _render_row(
    fb: FrameBuffer,
    items: tuple[SlotItem, ...],
    band: Band,
) -> None:
    """Нарисовать ряд элементов по слотам (индекс = слот)."""
    for slot, item in enumerate(items[:SLOT_COUNT]):
        rect = slot_rect(slot, band.y0, band.y1)
        if isinstance(item, FlowList):
            # Порция зависит от того, сколько его слотов уже пройдено.
            slot_pos = next(
                (pos for pos, s_idx in enumerate(item.slots) if s_idx == slot), 0
            )
            item.render_slot(fb, rect, slot_pos)
        else:
            item.render(fb, rect)


def render_layout(fb: FrameBuffer, layout: ScreenLayout) -> None:
    """Отрисовать макет: тело очищается, затем upper → knobs → lower → foot."""
    fb.fill_rect(0, BODY_Y0, 8 * SLOT_W, BODY_Y1 - BODY_Y0, Colors.BG)
    if layout.stripe is not None:
        # Цвет дорожки — узкая полоса слева; слоты начинаются с inset=4 и не перекрывают её.
        fb.fill_rect(0, BODY_Y0, 4, BODY_Y1 - BODY_Y0, layout.stripe)
    _render_row(fb, layout.upper, UPPER_BAND)
    _render_row(fb, layout.encoders, KNOBS_BAND)
    _render_row(fb, layout.lower, LOWER_BAND)
    if layout.tabs is not None:
        layout.tabs.render(fb, Rect(0, FOOT_BAND.y0, 8 * SLOT_W, FOOT_BAND.h))
    else:
        _render_row(fb, layout.foot, FOOT_BAND)
