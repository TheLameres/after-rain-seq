"""Идентификаторы экранов Push 2 (план D2 §2.1, переразметка 02.11.2026)."""

from __future__ import annotations

from enum import Enum


class ScreenId(Enum):
    """Экраны навигации.

    Таб-бар (верхний ряд дисплея) — только дорожные вкладки
    (порядок — :meth:`tab_order`): GEN, MACRO, PORTS. Каждая вкладка
    расположена под своей кнопкой: GEN — под Clip (CC 113),
    MACRO — под Device (CC 110), PORTS — под Upper Row 5 (CC 106).
    Upper Row 1–4 и 6–8 освобождены под будущее (D3+). Вне табов:

    - ``TRACKS`` — список дорожек, кнопка ``Session`` (CC 51);
    - ``SCALE`` — корень/лад, кнопка ``Scale`` (CC 58); не вкладка;
    - ``SETUP`` — настройки (суб-вкладки), кнопка ``Setup`` (CC 30); не вкладка;
    - ``WIZARD`` — модальный экран создания дорожки (Add Track, CC 53);
    - ``DEMO`` — демо-экран фреймворка (вкладки сверху/снизу, 8 энкодеров),
      кнопка ``Note`` (CC 50); не вкладка.

    Выделенные кнопки переключают экраны: ``Clip`` → GEN, ``Device`` → MACRO,
    ``Scale`` → SCALE, ``Setup`` → SETUP, ``Session`` → TRACKS, ``Note`` → DEMO.
    """

    TRACKS = "tracks"  # Session (CC 51) — не таб
    TRACK_GEN = "gen"  # генерация — CLIP (CC 113); таб под Clip
    TRACK_MACRO = "macro"  # макро-CC синтов — DEVICE (CC 110); таб под Device
    SCALE = "scale"  # корень/лад — SCALE (CC 58); не таб
    SETUP = "setup"  # настройки (суб-вкладки) — SETUP (CC 30); не таб
    PORTS = "ports"  # таб под Upper Row 5 (CC 106)
    WIZARD = "wizard"  # модальный — не таб
    DEMO = "demo"  # демо фреймворка — NOTE (CC 50); не таб

    @classmethod
    def tab_order(cls) -> tuple[ScreenId, ...]:
        """Порядок дорожных табов в верхнем ряду дисплея."""
        return (
            cls.TRACK_GEN,
            cls.TRACK_MACRO,
            cls.PORTS,
        )
