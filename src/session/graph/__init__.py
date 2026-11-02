"""Граф зависимостей дорожек «источник → наследник».

:class:`TrackGraph` — топологическая сортировка (Kahn), защита от циклов,
откат рёбер при цикле. Работает с именами дорожек, не импортирует модель.
"""

from src.session.graph.track_graph import TrackGraph

__all__ = [
    "TrackGraph",
]
