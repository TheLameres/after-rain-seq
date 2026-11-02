"""Кольцевой буфер логов в памяти — logging.Handler.

Форматирует записи в ``emit`` и держит последние ``maxlen`` строк
(по умолчанию 500). Отдельно запоминает последнюю запись уровня
ERROR+ — она попадает в :class:`StatusSnapshot` как ``log_error``.

deque-операции потокобезопасны под GIL: REPL-поток читает буфер
напрямую, запись идёт из любых потоков логирования.
"""

from __future__ import annotations

import logging
from collections import deque


class LogBuffer(logging.Handler):
    """Кольцевой буфер форматированных строк лога.

    Параметры:
        capacity: Максимальное число хранимых строк.

    Атрибуты:
        last_error: Последняя строка уровня ERROR+ или ``None``.
    """

    def __init__(self, capacity: int = 500) -> None:
        super().__init__(level=logging.INFO)
        self._lines: deque[str] = deque(maxlen=capacity)
        self._last_error: str | None = None

    def emit(self, record: logging.LogRecord) -> None:
        """Форматировать запись и положить в буфер."""
        try:
            line = self.format(record)
        except Exception:  # noqa: BLE001 — logging.Handler не должен падать
            line = f"{record.levelname} {record.name}: {record.getMessage()}"
        self._lines.append(line)
        if record.levelno >= logging.ERROR:
            self._last_error = line

    def get_last(self, n: int) -> list[str]:
        """Последние ``n`` строк (n <= 0 → пустой список)."""
        if n <= 0:
            return []
        return list(self._lines)[-n:]

    @property
    def last_error(self) -> str | None:
        """Последняя строка уровня ERROR+, или ``None``."""
        return self._last_error
