"""``Color`` — цвет как значение, не как упакованное число (план §3.2а, §8).

Мотивация: дисплей Push 2 работает в BGR565, а палитра LED адресуется
индексом 0..127. Хранить в модели упакованное число нельзя — у него нет
ответа на вопрос «цветной или серый», и его нельзя сравнить без распаковки
битов. Поэтому цвет — отдельный неизменяемый тип, а упаковка — производная
операция на границе с устройством.

Модуль импортирует только stdlib (``dataclasses``), чтобы `core` оставался
нижним слоем без зависимостей.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ACHROMATIC_TOLERANCE", "Color"]

# Порог хроматичности, снятый с палитры устройства (план §3.2а).
# Настоящие серые в палитре Push 2 имеют насыщенность ровно 0.000,
# ближайший цветной оттенок — 0.085. 0.05 лежит в зазоре; любое значение
# в диапазоне 0.02..0.08 даёт тот же результат на всех 128 записях.
ACHROMATIC_TOLERANCE: float = 0.05

_WHITE = 255


@dataclass(frozen=True, slots=True)
class Color:
    """Цвет RGB с компонентами 0..255.

    Неизменяемость важна: цвет — это значение, его кладут в DTO и в
    снимки состояния, и никто не должен править его на месте.

    Атрибуты:
        r: Красный, 0..255.
        g: Зелёный, 0..255.
        b: Синий, 0..255.

    Raises:
        TypeError: Если компонента — ``bool`` (``True`` прошёл бы как ``1``
            и молча дал бы почти чёрный цвет вместо яркого).
        ValueError: Если компонента вне 0..255.
    """

    r: int
    g: int
    b: int

    def __post_init__(self) -> None:
        for name in ("r", "g", "b"):
            value = getattr(self, name)
            if isinstance(value, bool):
                raise TypeError(
                    f"Color.{name}: bool недопустим (isinstance(True, int) истинно, "
                    "и True молча стало бы компонентой 1)"
                )
            if not isinstance(value, int):
                raise TypeError(f"Color.{name}: ожидался int, получено {type(value).__name__}")
            if not 0 <= value <= 255:
                raise ValueError(f"Color.{name}: {value} вне диапазона 0..255")

    # ------------------------------------------------------------------
    # Производные свойства
    # ------------------------------------------------------------------

    @property
    def chroma(self) -> int:
        """Разница между максимальной и минимальной компонентой, 0..255."""
        return max(self.r, self.g, self.b) - min(self.r, self.g, self.b)

    @property
    def saturation(self) -> float:
        """HSV-насыщенность 0.0..1.0; у чёрного — 0.0.

        Чёрный вынесен отдельно: в HSV деление было бы на ноль, а численно
        «чёрный ненасыщен» — верное утверждение.
        """
        high = max(self.r, self.g, self.b)
        if high == 0:
            return 0.0
        return self.chroma / high

    def is_achromatic(self, tolerance: float = ACHROMATIC_TOLERANCE) -> bool:
        """Цвет без оттенка — серый, чёрный или белый.

        Аргументы:
            tolerance: Максимальная насыщенность, ещё считающаяся серой.
        """
        return self.saturation <= tolerance

    def is_chromatic(self, tolerance: float = ACHROMATIC_TOLERANCE) -> bool:
        """Цвет имеет оттенок (не серый)."""
        return not self.is_achromatic(tolerance)

    @property
    def relative_luminance(self) -> float:
        """Относительная яркость по WCAG 2.x, 0.0..1.0.

        Нужна, чтобы выбрать цвет текста поверх плашки, а не угадывать.
        """

        def channel(value: int) -> float:
            srgb = value / _WHITE
            return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4

        return (
            0.2126 * channel(self.r)
            + 0.7152 * channel(self.g)
            + 0.0722 * channel(self.b)
        )

    # ------------------------------------------------------------------
    # Упаковка
    # ------------------------------------------------------------------

    def to_rgb565(self) -> int:
        """Упаковать в RGB565 (5 бит красного, 6 зелёного, 5 синего)."""
        return ((self.r >> 3) << 11) | ((self.g >> 2) << 5) | (self.b >> 3)

    @classmethod
    def from_rgb565(cls, value: int) -> Color:
        """Распаковать RGB565. Младшие биты теряются — старшие дублируются."""
        if not 0 <= value <= 0xFFFF:
            raise ValueError(f"RGB565 {value} вне диапазона 0..65535")
        r5 = (value >> 11) & 0x1F
        g6 = (value >> 5) & 0x3F
        b5 = value & 0x1F
        return cls(r5 << 3 | r5 >> 2, g6 << 2 | g6 >> 4, b5 << 3 | b5 >> 2)

    def to_bgr565(self) -> int:
        """Упаковать в BGR565 — формат кадров дисплея Push 2.

        В спецификации Push 2 слово пишется как BGR565: синий в старших
        5 битах, зелёный в середине, красный в младших.
        """
        return ((self.b >> 3) << 11) | ((self.g >> 2) << 5) | (self.r >> 3)

    @classmethod
    def from_bgr565(cls, value: int) -> Color:
        """Распаковать BGR565.

        Младшие биты честно теряются: 5 бит синего не восстановить до 8.
        Расхождение с исходным цветом — до 7 на канал, и это ожидаемо.
        """
        if not 0 <= value <= 0xFFFF:
            raise ValueError(f"BGR565 {value} вне диапазона 0..65535")
        b5 = (value >> 11) & 0x1F
        g6 = (value >> 5) & 0x3F
        r5 = value & 0x1F
        return cls(r5 << 3 | r5 >> 2, g6 << 2 | g6 >> 4, b5 << 3 | b5 >> 2)

    # ------------------------------------------------------------------
    # Текст
    # ------------------------------------------------------------------

    def to_hex(self) -> str:
        """Строка ``#rrggbb`` в нижнем регистре."""
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}"

    @classmethod
    def from_hex(cls, value: str) -> Color:
        """Разобрать ``#rrggbb`` или ``rrggbb``.

        Raises:
            ValueError: Если строка не шестизначная hex.
        """
        text = value.lstrip("#")
        if len(text) != 6:
            raise ValueError(f"Ожидался #rrggbb, получено {value!r}")
        try:
            packed = int(text, 16)
        except ValueError as exc:
            raise ValueError(f"Ожидался #rrggbb, получено {value!r}") from exc
        return cls((packed >> 16) & 0xFF, (packed >> 8) & 0xFF, packed & 0xFF)

    def __str__(self) -> str:
        return self.to_hex()
