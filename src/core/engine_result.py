"""Результат команды движка: тип вместо строки с префиксом (§4.9)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class EngineResult:
    """Итог команды управления движком.

    Атрибуты:
        message: Текст для человека. Префикс ошибки сюда не входит:
            терминал и UI сами решают, как показать ошибку.
        error: True, если команда не выполнена.
        data: Структурированные данные для вызывающего кода,
            например ``{"track": "Pad 9"}`` после создания дорожки.
    """

    message: str
    error: bool = False
    data: dict[str, object] = field(default_factory=dict)

    @classmethod
    def ok(cls, message: str, **data: object) -> EngineResult:
        return cls(message=message, error=False, data=dict(data))

    @classmethod
    def fail(cls, message: str) -> EngineResult:
        return cls(message=message, error=True)
