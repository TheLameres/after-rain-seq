"""Цепочка модификаций — последовательность этапов над списком событий (§3.3).

Этап получает **весь** список событий, а не одно событие: иначе нельзя
транспонировать аккорд, поставить арпеджиатор или отфильтровать плотность.
Цепочка выполняет этапы по порядку и останавливается, как только список
опустел, — дальнейшие этапы на пустом списке не имеют смысла.

Этапы не знают друг о друге и не хранят состояние между тиками: всё, что
нужно им для решения, передаётся в :class:`StageContext`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class StageContext:
    """Всё, что этап может знать о текущем тике, кроме самих событий.

    Атрибуты:
        beat: Абсолютная позиция на таймлайне, в beats.
        bpm: Текущий темп.
        track_name: Имя дорожки, для которой идёт обработка.
    """

    beat: float
    bpm: float
    track_name: str


class Stage[T](Protocol):
    """Этап цепочки: преобразует список событий.

    Этап обязан вернуть новый список и не должен менять входной — цепочка
    полагается на то, что промежуточные списки можно безопасно сравнивать.
    """

    name: str

    def process(self, batch: list[T], ctx: StageContext) -> list[T]: ...


@dataclass
class Chain[T]:
    """Упорядоченный набор этапов. Пустая цепочка — тождество.

    Атрибуты:
        stages: Этапы в порядке выполнения.
    """

    stages: Sequence[Stage[T]] = field(default_factory=tuple)

    def process(self, batch: list[T], ctx: StageContext) -> list[T]:
        """Прогнать список через все этапы.

        Returns:
            Новый список. Для пустой цепочки — копия входа.
        """
        current = list(batch)
        for stage in self.stages:
            if not current:
                break  # усечение до нуля: дальше нечего обрабатывать
            current = stage.process(current, ctx)
        return current

    def __len__(self) -> int:
        return len(self.stages)

    @property
    def names(self) -> tuple[str, ...]:
        """Имена этапов в порядке выполнения (для отладки и REPL)."""
        return tuple(stage.name for stage in self.stages)
