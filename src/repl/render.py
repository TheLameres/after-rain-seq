"""Текст результата команды движка для человека (терминал и flash UI)."""

from __future__ import annotations

from src.core.engine_result import EngineResult


def render_text(result: EngineResult) -> str:
    """Ошибка получает префикс ``error:``; успех — только текст."""
    return f"error: {result.message}" if result.error else result.message
