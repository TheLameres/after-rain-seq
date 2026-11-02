"""Граф зависимостей между дорожками.

Дорожка-источник публикует ``ChordEvent``, дорожка-наследник читает.
Граф хранит рёбра ``source → dependent`` и обеспечивает:
топологический порядок генерации, защиту от циклов, поиск зависимых.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class TrackGraph:
    """Ориентированный граф зависимостей дорожек.

    Ребро ``A → B`` означает: ``B`` читает аккорды из ``A``
    (``B.sources`` содержит имя ``A``). Топологический порядок —
    источники перед наследниками.
    """

    def __init__(self) -> None:
        # Имя дорожки → множество имён её наследников.
        self._edges: dict[str, set[str]] = {}

    # ------------------------------------------------------------------
    # Управление вершинами
    # ------------------------------------------------------------------

    def add_track(self, name: str) -> None:
        """Добавить вершину (без рёбер).

        Аргументы:
            name: Имя дорожки.

        Raises:
            ValueError: Если вершина уже существует.
        """
        if name in self._edges:
            raise ValueError(f"Дорожка {name!r} уже в графе")
        self._edges[name] = set()

    def remove_track(self, name: str) -> None:
        """Удалить вершину и все связанные рёбра.

        Аргументы:
            name: Имя дорожки.
        """
        self._edges.pop(name, None)
        for deps in self._edges.values():
            deps.discard(name)

    # ------------------------------------------------------------------
    # Управление рёбрами
    # ------------------------------------------------------------------

    def set_sources(self, track_name: str, sources: tuple[str, ...]) -> None:
        """Перестроить входящие рёбра дорожки.

        Удаляет старые рёбра ``X → track_name``, добавляет новые
        ``src → track_name`` для каждого ``src`` в ``sources``.
        Проверяет на циклы.

        Аргументы:
            track_name: Имя дорожки-наследника.
            sources: Имена источников.

        Raises:
            ValueError: Если вершина не существует или образуется цикл.
        """
        if track_name not in self._edges:
            raise ValueError(f"Дорожка {track_name!r} нет в графе")
        for src in sources:
            if src not in self._edges:
                raise ValueError(f"Источник {src!r} нет в графе")

        # Удалить старые входящие рёбра.
        for deps in self._edges.values():
            deps.discard(track_name)

        # Добавить новые.
        for src in sources:
            self._edges[src].add(track_name)

        # Проверить на циклы.
        try:
            self.validate_no_cycles()
        except ValueError:
            # Откат: удалить добавленные рёбра.
            for src in sources:
                self._edges[src].discard(track_name)
            raise

    def dependents_of(self, name: str) -> list[str]:
        """Имена дорожек, которые читают данную.

        Аргументы:
            name: Имя дорожки-источника.

        Returns:
            Список имён наследников.
        """
        return sorted(self._edges.get(name, set()))

    # ------------------------------------------------------------------
    # Топологическая сортировка
    # ------------------------------------------------------------------

    def topological_order(self) -> list[str]:
        """Топологическая сортировка имён дорожек.

        Источники идут перед наследниками. Дорожки без связей —
        в порядке добавления.

        Returns:
            Список имён в порядке генерации.

        Raises:
            ValueError: При цикле в графе.
        """
        # Kahn's algorithm.
        in_degree: dict[str, int] = {name: 0 for name in self._edges}
        for deps in self._edges.values():
            for dep in deps:
                in_degree[dep] += 1

        # Очередь вершин без входящих рёбер, в порядке добавления.
        queue = [n for n in self._edges if in_degree[n] == 0]
        order: list[str] = []

        while queue:
            node = queue.pop(0)
            order.append(node)
            for dep in sorted(self._edges[node]):
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)

        if len(order) != len(self._edges):
            # Найти вершины в цикле.
            remaining = [n for n in self._edges if in_degree[n] > 0]
            raise ValueError(f"Цикл в графе дорожек: {sorted(remaining)}")
        return order

    def validate_no_cycles(self) -> None:
        """Проверить весь граф на циклы.

        Raises:
            ValueError: При цикле, с именами участвующих дорожек.
        """
        self.topological_order()

    # ------------------------------------------------------------------
    # Отладка
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        edges_str = ", ".join(
            f"{src}→{dep}" for src, deps in self._edges.items() for dep in sorted(deps)
        )
        return f"TrackGraph({edges_str})"
