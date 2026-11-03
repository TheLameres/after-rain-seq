"""core — чистые типы без зависимостей от подсистем проекта.

Правило слоя: модули здесь импортируют только стандартную библиотеку
и ``pydantic``. Обратные импорты (``core`` → ``session``/``devices``/…)
запрещены и проверяются в CI.

Состав:

- :class:`Color` — цвет как r/g/b с валидацией и проверкой хроматичности.
"""

from src.core.color import ACHROMATIC_TOLERANCE, Color

__all__ = [
    "ACHROMATIC_TOLERANCE",
    "Color",
]
