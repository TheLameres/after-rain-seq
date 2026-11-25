"""Этап Densify: прореживание событий по позиции шага (§3.3, B4).

Решение принимается по ``beat`` (позиции шага в паттерне), а не по индексу
в списке. Индекс в списке зависит от того, какие соседние этапы уже что-то
удалили, и тогда одно и то же событие получило бы разное решение (тот же
класс дефекта, что §4.2 со свингом). ``beat`` от соседей не зависит.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.session.events.note_event import NoteEvent
from src.session.model.density import density_keep
from src.session.modify.chain import StageContext


@dataclass(frozen=True)
class DensifyStage:
    """Оставляет долю событий, заданную плотностью 0..1.

    Контракт: **Densify — до этапов, дробящих время** (арпеджиатор, будущие
    транспозиции времени). Решение по ``int(e.beat)`` осмысленно только на
    сетке целых битов: после ``ArpeggiateStage`` ноты получают дробные биты
    внутри целого такта и схлопываются в один индекс — решение деградирует.
    Этап не запрещает такой порядок, но контракт требует ставить Densify
    раньше.

    Атрибуты:
        density: Плотность 0.0–1.0. 1.0 — без прореживания.
            Шаг с позицией ``beat == 0`` (акцент) не удаляется никогда.
        name: Имя этапа для ``Chain.names``.
    """

    density: float
    name: str = "densify"

    def __post_init__(self) -> None:
        if not (0.0 <= self.density <= 1.0):
            raise ValueError(
                f"Densify: density должна быть в диапазоне 0.0–1.0, "
                f"получено {self.density}"
            )

    def process(self, batch: list[NoteEvent], ctx: StageContext) -> list[NoteEvent]:
        """Проредить список событий по позиции шага.

        Args:
            batch: События дорожки; используется поле ``beat``.
            ctx: Контекст тика (этап его не использует).

        Returns:
            Новый список выживших событий.
        """
        if self.density >= 1.0:
            return list(batch)
        return [e for e in batch if density_keep(int(e.beat), self.density)]
