"""Диагностики и ошибки скриптового движка."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScriptDiagnostic:
    """Одно замечание валидации: файл, строка, колонка, текст.

    Атрибуты:
        filename: Имя проверяемого файла.
        line: Номер строки 1-based (``0`` — «весь файл», для IO-ошибок).
        col: Колонка 0-based.
        message: Человекочитаемое описание замечания.
    """

    filename: str
    line: int
    col: int
    message: str

    def format(self) -> str:
        """Формат отчёта: ``file:line: message`` (line 0 — без номера)."""
        if self.line <= 0:
            return f"{self.filename}: {self.message}"
        return f"{self.filename}:{self.line}: {self.message}"


class ScriptError(Exception):
    """Ошибка исполнения вызова фасада (движок вернул ``error``).

    Аргументы:
        message: Текст ошибки из ``EngineResult.message`` (без префикса
            номера строки — раннер оформляет итог как ``file:line: message``).
        line: Номер строки скрипта 1-based или ``None``; хранится как
            атрибут, в текст сообщения не включается.
    """

    def __init__(self, message: str, line: int | None = None) -> None:
        self.line = line
        super().__init__(message)
