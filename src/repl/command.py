"""DTO команды REPL — результат разбора строки."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    """Разобранная команда: строка → структура.

    Атрибуты:
        argv: Позиционные токены как введены (без флагов).
        name: Каноническое имя команды (``"track add"``).
        domain: Первый токен (lower-case).
        action: Второй токен-действие (lower-case) или ``None``.
        args: Аргументы после домена и действия.
        flags: Флаги вида ``--yes``/``-f`` (без дефисов).
        error: Текст ошибки разбора (неизвестная команда, неверные
            аргументы) или ``None``, если команда валидна.
        usage: Usage-строка для показа при ошибке синтаксиса.
    """

    argv: tuple[str, ...] = ()
    name: str = ""
    domain: str = ""
    action: str | None = None
    args: tuple[str, ...] = ()
    flags: frozenset[str] = frozenset()
    error: str | None = None
    usage: str | None = None

    @property
    def destructive_confirmed(self) -> bool:
        """Флаг ``--yes``/``-f`` — деструктивная команда подтверждена."""
        return bool(self.flags & {"yes", "f"})


@dataclass(frozen=True)
class CommandResult:
    """Результат выполнения команды.

    Атрибуты:
        output: Текст для вывода пользователю (может быть пустым).
        code: 0 — ок, 1 — ошибка.
        exit: True — команда запросила завершение (``exit``/``quit``).
    """

    output: str = ""
    code: int = 0
    exit: bool = False
