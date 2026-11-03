"""Цвет как значение — r/g/b, валидация, проверка хроматичности.

Зачем отдельный тип
-------------------
Сейчас цвет дорожки в проекте — это ``int`` в BGR565, посчитанный из
кортежа ``(r, g, b)``. Из-за этого нельзя ответить на вопрос «этот цвет
цветной или серый?», не заглядывая в формат устройства, и нельзя
сравнить два цвета, не распаковывая биты.

:class:`Color` хранит компоненты как есть и отвечает на вопросы о себе.
Упаковка в BGR565 — производная операция, а не способ хранения.

Чёрно-белый или цветной
-----------------------
Хроматичность определяется насыщенностью в модели HSV:

    saturation = (max - min) / max        (0.0 для чёрного)

Цвет считается ахроматичным, если насыщенность не выше
:data:`ACHROMATIC_TOLERANCE`. Порог 0.05 выбран по фактическим данным
палитры LED Push 2 (128 записей, снято спайком): настоящие серые имеют
насыщенность **ровно 0.000**, ближайший цветной — 0.085. Между ними
чистый зазор, поэтому любое значение в 0.02–0.08 даёт одинаковый
результат; 0.05 — середина зазора.

        (89, 89, 89)    S=0.000   ахроматичный
        (204, 204, 204) S=0.000   ахроматичный
        (107, 117, 110) S=0.085   цветной (слабо, но цветной)
        (0, 0, 255)     S=1.000   цветной

Использование::

    >>> c = Color(0, 0, 255)
    >>> c.is_chromatic()
    True
    >>> c.saturation
    1.0
    >>> Color(89, 89, 89).is_achromatic()
    True
    >>> Color.from_hex("#0000ff") == c
    True
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ACHROMATIC_TOLERANCE", "Color"]

#: Порог насыщенности, ниже которого цвет считается ахроматичным.
#: Обоснование — в докстринге модуля (зазор 0.000 … 0.085 в палитре Push 2).
ACHROMATIC_TOLERANCE: float = 0.05

_CHANNEL_MAX = 255


def _validate_channel(value: object, name: str) -> int:
    """Проверить и вернуть компоненту цвета.

    ``bool`` отклоняется явно: в Python ``isinstance(True, int)`` истинно,
    и ``Color(True, 0, 0)`` молча создал бы красный полутон.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{name} должен быть int 0..{_CHANNEL_MAX}, получено "
            f"{type(value).__name__}: {value!r}"
        )
    if not 0 <= value <= _CHANNEL_MAX:
        raise ValueError(
            f"{name} вне диапазона 0..{_CHANNEL_MAX}: {value}"
        )
    return value


@dataclass(frozen=True, slots=True)
class Color:
    """Цвет в sRGB: три компоненты 0..255.

    Неизменяемый: ``Color`` — значение, а не накопитель состояния.
    Создание дорого не стоит, зато исключены случайные мутации
    одного цвета из нескольких мест.

    Параметры:
        r: Красная компонента, 0..255.
        g: Зелёная компонента, 0..255.
        b: Синяя компонента, 0..255.

    Raises:
        TypeError: Компонента не ``int`` (в том числе ``bool``).
        ValueError: Компонента вне 0..255.
    """

    r: int
    g: int
    b: int

    def __post_init__(self) -> None:
        _validate_channel(self.r, "r")
        _validate_channel(self.g, "g")
        _validate_channel(self.b, "b")

    # ------------------------------------------------------------------
    # Конструкторы
    # ------------------------------------------------------------------

    @classmethod
    def from_hex(cls, value: str) -> Color:
        """Создать цвет из ``"#rrggbb"`` или ``"rrggbb"``.

        Raises:
            ValueError: Строка не шестизначная или не hex.
        """
        text = value.strip().lstrip("#")
        if len(text) != 6:
            raise ValueError(
                f"ожидалось 6 hex-цифр (#rrggbb), получено {value!r}"
            )
        try:
            r = int(text[0:2], 16)
            g = int(text[2:4], 16)
            b = int(text[4:6], 16)
        except ValueError as exc:
            raise ValueError(f"не hex-цвет: {value!r}") from exc
        return cls(r, g, b)

    @classmethod
    def from_rgb(cls, rgb: tuple[int, int, int]) -> Color:
        """Создать цвет из кортежа ``(r, g, b)``."""
        r, g, b = rgb
        return cls(r, g, b)

    # ------------------------------------------------------------------
    # Хроматичность
    # ------------------------------------------------------------------

    @property
    def chroma(self) -> int:
        """Размах каналов: ``max - min``, 0..255.

        0 — каналы равны, то есть серый тон (включая чёрный и белый).
        """
        return max(self.r, self.g, self.b) - min(self.r, self.g, self.b)

    @property
    def saturation(self) -> float:
        """Насыщенность HSV, 0.0..1.0.

        Относительная — делится на максимальный канал, поэтому тёмный
        насыщенный цвет и яркий насыщенный дают одинаковую единицу.
        Для чёрного ``(0, 0, 0)`` возвращает 0.0.
        """
        high = max(self.r, self.g, self.b)
        if high == 0:
            return 0.0
        return self.chroma / high

    def is_achromatic(self, tolerance: float = ACHROMATIC_TOLERANCE) -> bool:
        """True, если цвет чёрно-белый (серый тон, без оттенка).

        Сюда попадают чёрный, белый и все серые. Слабо тонированные
        цвета вроде ``(107, 117, 110)`` при допуске по умолчанию
        считаются цветными.

        Параметры:
            tolerance: Порог насыщенности; значение ИЛИ ниже него —
                ахроматично. ``0.0`` — только точные серые.
        """
        if tolerance < 0.0:
            raise ValueError(f"tolerance не может быть < 0: {tolerance}")
        return self.saturation <= tolerance

    def is_chromatic(self, tolerance: float = ACHROMATIC_TOLERANCE) -> bool:
        """True, если у цвета есть оттенок (не чёрно-белый).

        Дополнение :meth:`is_achromatic` при том же допуске.
        """
        return not self.is_achromatic(tolerance)

    # ------------------------------------------------------------------
    # Светимость
    # ------------------------------------------------------------------

    @property
    def relative_luminance(self) -> float:
        """Относительная светимость по WCAG, 0.0..1.0.

        Нужна, чтобы решать «чёрный или белый текст на этом цвете»:
        контраст считается по ней, а не по среднему каналов.
        """
        def linear(channel: int) -> float:
            s = channel / _CHANNEL_MAX
            if s <= 0.04045:
                return s / 12.92
            return ((s + 0.055) / 1.055) ** 2.4

        return (
            0.2126 * linear(self.r)
            + 0.7152 * linear(self.g)
            + 0.0722 * linear(self.b)
        )

    def is_dark(self, threshold: float = 0.5) -> bool:
        """True, если цвет тёмный (нужен светлый текст поверх)."""
        return self.relative_luminance < threshold

    # ------------------------------------------------------------------
    # Упаковка
    # ------------------------------------------------------------------

    def to_rgb565(self) -> int:
        """Упаковать в RGB565: ``rrrrrggg gggbbbbb`` (старшие 5/6/5 бит)."""
        return ((self.r >> 3) << 11) | ((self.g >> 2) << 5) | (self.b >> 3)

    def to_bgr565(self) -> int:
        """Упаковать в BGR565: раскладка дисплея Push 2 (синий в старших).

        Отличие от :meth:`to_rgb565` — только порядок каналов.
        """
        return ((self.b >> 3) << 11) | ((self.g >> 2) << 5) | (self.r >> 3)

    @classmethod
    def from_bgr565(cls, value: int) -> Color:
        """Распаковать BGR565 обратно в цвет.

        Младшие биты каналов теряются — это неизбежно, 5 и 6 бит уже
        не восстановить до 8.
        """
        if not 0 <= value <= 0xFFFF:
            raise ValueError(f"BGR565 вне 0..0xFFFF: {value:#x}")
        r = (value & 0x1F) << 3
        g = ((value >> 5) & 0x3F) << 2
        b = ((value >> 11) & 0x1F) << 3
        return cls(r, g, b)

    def to_hex(self) -> str:
        """Строка ``"#rrggbb"`` в нижнем регистре."""
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}"

    # ------------------------------------------------------------------
    # Представление
    # ------------------------------------------------------------------

    def __str__(self) -> str:
        return self.to_hex()
