"""Линейная история версий дорожки с курсором и лимитом.

Корень (индекс 0) никогда не вытесняется. Мутация из середины истории
отрезает будущие версии.
"""

from __future__ import annotations

from typing import Generic, TypeVar

T = TypeVar("T")

HISTORY_LIMIT: int = 256


class VersionHistory(Generic[T]):
    def __init__(self, root: T, limit: int = HISTORY_LIMIT) -> None:
        if limit < 2:
            raise ValueError(f"limit должен быть >= 2, got {limit}")
        self._limit = limit
        self._versions: list[T] = [root]
        self._cursor = 0

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def current(self) -> T:
        return self._versions[self._cursor]

    def __len__(self) -> int:
        return len(self._versions)

    def versions(self) -> list[T]:
        return list(self._versions)

    def push(self, version: T) -> int:
        del self._versions[self._cursor + 1 :]
        self._versions.append(version)
        self._cursor = len(self._versions) - 1
        if len(self._versions) > self._limit:
            del self._versions[1]
            self._cursor -= 1
        return self._cursor

    def undo(self) -> bool:
        if self._cursor == 0:
            return False
        self._cursor -= 1
        return True

    def recall(self, index: int) -> bool:
        if not 0 <= index < len(self._versions):
            return False
        self._cursor = index
        return True
