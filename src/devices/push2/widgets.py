"""Мини-фреймворк виджетов для экранов Push 2 (D2-7).

Каждый виджет — объект с единственным методом ``render(fb, rect)``:
рисует себя в заданном прямоугольнике :class:`Rect` на FrameBuffer.
Экраны собираются из виджетов (см. ``screens.py``); новый виджет —
тот же контракт, сложная геометрия — только внутри ``render``.

Геометрия экрана (960×160): таб-бар y 0–21, заголовок y 22–35,
body y 36–160 — восемь колонок по 120 px ровно под энкодерами
E1–E8 и кнопками Lower Row 1–8 (:class:`ColumnGrid`).

Виджеты immutable (frozen dataclass'ы): экран может собирать их
на каждый кадр без аллокационных последствий — это дёшево.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from src.devices.push2.renderer import FRAME_W, Colors, FrameBuffer

# Body-геометрия (дублирует screens.py, чтобы виджеты не импортировали
# слой экранов; это каноническое место определения колонок).
BODY_Y0 = 14
BODY_Y1 = 160
COL_W = 120  # шаг колонок = шаг энкодеров E1–E8 / Lower Row

# Физическая сетка: 8 слотов одинакового размера. Энкодеры E1–E8 и кнопки
# Upper/Lower Row стоят на одном шаге COL_W, поэтому и кнопки, и колонки
# экрана выравниваются по этой же сетке (см. ColumnGrid).
SLOT_COUNT = 8
SLOT_W = COL_W


@dataclass(frozen=True)
class Rect:
    """Прямоугольник в пикселях фрейма: левый верхний угол + размер."""

    x: int
    y: int
    w: int
    h: int

    @property
    def cx(self) -> int:
        """Горизонтальный центр."""
        return self.x + self.w // 2

    @property
    def bottom(self) -> int:
        """y нижнего края (half-open: первая строка за пределами)."""
        return self.y + self.h

    def inset(self, dx: int, dy: int) -> Rect:
        """Уменьшить со всех сторон (минимум 1×1)."""
        return Rect(
            self.x + dx,
            self.y + dy,
            max(1, self.w - 2 * dx),
            max(1, self.h - 2 * dy),
        )


@runtime_checkable
class Widget(Protocol):
    """Контракт виджета: отрисовать себя внутри rect на FrameBuffer."""

    def render(self, fb: FrameBuffer, rect: Rect) -> None:
        """Отрисовать виджет; rect — выделенная область (можно не заполнять)."""
        ...


# ── Примитивы ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Label:
    """Текстовая метка с горизонтальным выравниванием внутри rect.

    align: ``"l"`` (по левому краю), ``"c"`` (по центру), ``"r"`` (по правому).
    Вертикально — по верхнему краю rect (y-компенсация — на вызывающей
    стороне: виджеты не знают метрик шрифтов).
    """

    text: str
    font: str = "sm"
    color: int = Colors.WHITE
    align: str = "l"

    def render(self, fb: FrameBuffer, rect: Rect) -> None:
        if not self.text:
            return
        if self.align == "c":
            fb.text_centered(rect.cx, rect.y, self.text, self.font, self.color)
        elif self.align == "r":
            width = fb.text_width(self.text, self.font)
            fb.text(rect.x + rect.w - width, rect.y, self.text, self.font, self.color)
        else:
            fb.text(rect.x, rect.y, self.text, self.font, self.color)


@dataclass(frozen=True)
class Marker:
    """Цветной квадратный маркер (дорожка/порт), по левому краю по центру."""

    color: int
    size: int = 7

    def render(self, fb: FrameBuffer, rect: Rect) -> None:
        size = min(self.size, rect.h)
        y = rect.y + (rect.h - size) // 2
        fb.fill_rect(rect.x, y, min(self.size, rect.w), size, self.color)


@dataclass(frozen=True)
class Bar:
    """Горизонтальный бар 0..1 по нижнему краю rect.

    frac=None — не рисовать ничего (значение «не применимо»).
    """

    frac: float | None
    color: int = Colors.TRACK_FILL
    height: int = 8

    def render(self, fb: FrameBuffer, rect: Rect) -> None:
        if self.frac is None:
            return
        clamped = max(0.0, min(1.0, self.frac))
        fb.bar(
            rect.x,
            rect.bottom - self.height,
            rect.w,
            self.height,
            round(clamped * 127),
            color=self.color,
        )


# ── Композитные виджеты ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class Column:
    """Колонка под энкодером: метка сверху мелко, крупное значение,
    бар снизу (если frac не None). Ровно одна ячейка ColumnGrid."""

    label: str
    value: str
    frac: float | None = None

    def render(self, fb: FrameBuffer, rect: Rect) -> None:
        Label(self.label, "sm", Colors.GRAY, "c").render(
            fb, Rect(rect.x, rect.y + 4, rect.w, 12)
        )
        Label(self.value, "lg", Colors.WHITE, "c").render(
            fb, Rect(rect.x, rect.y + 22, rect.w, 18)
        )
        # Бар закреплён под значением (как на экранах Ableton), не по низу.
        Bar(self.frac).render(fb, Rect(rect.x + 10, rect.y + 46, rect.w - 20, 8))


class ColumnGrid:
    """Сетка из count колонок шириной COL_W, начиная с x=0.

    Колонка i — ровно под энкодером E(i+1) и кнопкой Lower Row i+1.
    Не виджет сам по себе: даёт rect'ы для размещения виджетов.
    """

    def __init__(
        self, count: int = FRAME_W // COL_W, y0: int = BODY_Y0, y1: int = BODY_Y1
    ) -> None:
        self.count = count
        self.y0 = y0
        self.y1 = y1

    def rect(self, i: int) -> Rect:
        """Прямоугольник i-й колонки (i по модулю count)."""
        i %= self.count
        return Rect(i * COL_W, self.y0, COL_W, self.y1 - self.y0)

    def center_x(self, i: int) -> int:
        """Горизонтальный центр i-й колонки."""
        return self.rect(i).cx


@dataclass(frozen=True)
class TabStrip:
    """Таб-бар: ячейки (метка, x-центр) под своими физическими кнопками;
    активная вкладка — белой заливкой с чёрным текстом.

    Ячейки размещаются по абсолютным x-центрам, потому что кнопки Clip/Device/
    Upper Row 5 стоят в своих местах корпуса, а не на равном шаге. Для ряда
    из восьми равных кнопок используйте :func:`slot_cells`.
    Работает на любой высоте: отсчёт y-координат — от rect.y.
    """

    cells: tuple[tuple[str, int], ...]
    active: str | None
    cell_w: int = 110

    def render(self, fb: FrameBuffer, rect: Rect) -> None:
        fb.fill_rect(rect.x, rect.y, rect.w, rect.h, Colors.BG)
        for label_text, cx in self.cells:
            x = cx - self.cell_w // 2
            is_active = label_text.lower() == self.active
            if is_active:
                fb.fill_rect(x, rect.y + 2, self.cell_w, rect.h - 4, Colors.WHITE)
            fb.text_centered(
                cx,
                rect.y + 6,
                label_text,
                "md",
                Colors.BLACK if is_active else Colors.GRAY,
            )


def slot_cells(labels: tuple[str, ...]) -> tuple[tuple[str, int], ...]:
    """Разложить метки по физической сетке: метка i — центр слота i (шаг SLOT_W).

    Слот i совпадает с колонкой ColumnGrid.rect(i) по x, поэтому кнопка и
    энкодер над/под ним стоят на одной вертикали.
    """
    return tuple(
        (label, i * SLOT_W + SLOT_W // 2) for i, label in enumerate(labels[:SLOT_COUNT])
    )



@dataclass(frozen=True)
class SegmentTabs:
    """Нижний ряд вкладок: равные сегменты на всю ширину rect (образец —
    низ экрана Setup Push standalone). Сегмент i активен — белой заливкой
    с чёрным текстом.

    Слотовая модель (SLOT_W) здесь не применяется: нижний ряд — это полоса
    на всю ширину, а не ряд физических кнопок. Физическую привязку к
    энкодерам и кнопкам даёт верхний TabStrip и ColumnGrid.
    """

    labels: tuple[str, ...]
    active: str
    height: int = 14

    def render(self, fb: FrameBuffer, rect: Rect) -> None:
        fb.fill_rect(rect.x, rect.y, rect.w, rect.h, Colors.BG)
        count = max(1, len(self.labels))
        seg_w = rect.w // count
        y = rect.y + rect.h - self.height
        for i, label_text in enumerate(self.labels):
            x = rect.x + i * seg_w
            is_active = label_text.lower() == self.active
            if is_active:
                fb.fill_rect(x, y - 2, seg_w - 8, self.height, Colors.WHITE)
            Label(
                label_text.upper(),
                "sm",
                Colors.BLACK if is_active else Colors.GRAY,
            ).render(fb, Rect(x + 4, y, seg_w - 12, self.height))
