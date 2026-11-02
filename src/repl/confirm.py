"""Политика подтверждений для деструктивных команд.

``INTERACTIVE`` — спросить ``y/N`` (по умолчанию «нет»: пустой ответ
или что угодно кроме ``y``/``yes`` отменяет команду).
``ALWAYS`` — не спрашивать, всегда подтверждать (тесты, ``--yes``).
"""

from __future__ import annotations

import builtins
from collections.abc import Callable
from enum import Enum, auto

# Функция запроса ввода: получает вопрос, возвращает сырую строку ответа.
ConfirmPrompt = Callable[[str], str]

DEFAULT_PROMPT: ConfirmPrompt = builtins.input


class ConfirmPolicy(Enum):
    """Как исполнять деструктивные команды."""

    INTERACTIVE = auto()
    """Спросить y/N через prompt-колбэк."""

    ALWAYS = auto()
    """Подтверждать всегда, не спрашивая (тесты)."""

    def confirmed(self, question: str, prompt: ConfirmPrompt = DEFAULT_PROMPT) -> bool:
        """Задать вопрос и вернуть решение.

        Аргументы:
            question: Текст вопроса (например, ``Delete track "Pad 3"? [y/N]``).
            prompt: Колбэк ввода (в тестах — стаб).

        Returns:
            True — выполнять деструктивное действие.
        """
        if self is ConfirmPolicy.ALWAYS:
            return True
        answer = prompt(f"{question} [y/N] ").strip().lower()
        return answer in ("y", "yes")
