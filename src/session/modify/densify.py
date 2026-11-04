"""Этап Densify: прореживание событий по позиции шага (§3.3, B4).

Решение принимается по ``beat`` (позиции шага в паттерне), а не по индексу
в списке. Индекс в списке зависит от того, какие соседние этапы уже что-то
удалили, и тогда одно и то же событие получило бы разное решение (тот же
класс дефекта, что §4.2 со свингом). ``beat`` от соседей не зависит.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.session.engine.generators import _density_keep
from src.session.modify.chain import StageContext


@dataclass(frozen=True)
class DensifyStage:
    """Оставляет долю событий, заданную плотностью 0..1.

    Атрибуты:
        density: Плотность 0.0–1.0. 1.0 — без прореживания.
            Шаг с позицией ``beat == 0`` (акцент) не удаляется никогда.
    """

    density: float
    name: str = "densify"

    def process(self, batch: list, ctx: StageContext) -> list:
        if self.density >= 1.0:
            return list(batch)
        return [e for e in batch if _density_keep(int(e.beat), self.density)]
