"""Чистые типы без внутренних зависимостей (plan §3.1, нижний слой).

Модули здесь импортируют только stdlib. Ничего из ``src.session``,
``src.sync``, ``src.devices``, ``src.app``, ``src.repl`` сюда тянуться не должно.
"""

from __future__ import annotations

from src.core.color import ACHROMATIC_TOLERANCE, Color

__all__ = ["ACHROMATIC_TOLERANCE", "Color"]
