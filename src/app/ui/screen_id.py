"""Идентификаторы экранов Push 2 (план D2 §2.1, переразметка 02.11.2026)."""

from __future__ import annotations

from enum import Enum


class ScreenId(Enum):
    """Экраны навигации.

    Таб-бара нет (удалён в Ф0): экраны переключаются только выделенными
    кнопками; Left/Right двигают курсор по дорожкам, а не экраны.

    - ``TRACKS`` — список дорожек, кнопка ``Session`` (CC 51);
    - ``TRACK_GEN`` — генерация выбранной дорожки, ``Clip`` (CC 113);
    - ``TRACK_MACRO`` — макро-CC синтов, ``Device`` (CC 110);
    - ``PORTS`` — порты и назначение дорожек, ``Mix`` (CC 112);
    - ``SCALE`` — корень/лад, ``Scale`` (CC 58);
    - ``SETUP`` — настройки (суб-вкладки), ``Setup`` (CC 30);
    - ``WIZARD`` — модальный экран создания дорожки (Add Track, CC 53);
    - ``DEMO`` — демо-экран фреймворка (вкладки сверху/снизу, 8 энкодеров),
      ``Note`` (CC 50).
    """

    TRACKS = "tracks"  # Session (CC 51)
    TRACK_GEN = "gen"  # генерация — Clip (CC 113)
    TRACK_MACRO = "macro"  # макро-CC синтов — Device (CC 110)
    SCALE = "scale"  # корень/лад — Scale (CC 58)
    SETUP = "setup"  # настройки (суб-вкладки) — Setup (CC 30)
    PORTS = "ports"  # порты — Mix (CC 112)
    WIZARD = "wizard"  # модальный — Add Track (CC 53)
    DEMO = "demo"  # демо фреймворка — Note (CC 50)
