"""Этап Arpeggiate: разворачивает аккорд в последовательность (§5.3).

В модели данных аккорд — это несколько :class:`NoteEvent` с **одинаковым**
``beat``. Этап находит такие группы и раскладывает их во времени: одна нота
за шаг, в выбранном порядке по ступеням.

Ключевое ограничение — не залезть на следующий аккорд. Если шаг уводит
последнюю ноту за ближайший следующий onset, шаг сжимается так, чтобы все
ноты успели прозвучать до него. Аккорд не должен «съесть» следующий.

Длительность каждой ноты становится равной шагу: иначе ноты наложатся друг
на друга и на слух снова получится аккорд, а не арпеджио.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from src.session.modify.chain import StageContext

DIRECTIONS: tuple[str, ...] = ("up", "down", "updown")
"""Допустимые направления обхода аккорда."""

_BEAT_PRECISION: int = 9
"""Знаков после запятой при сравнении ``beat``.

Ноты одного аккорда приходят из арифметики генератора и могут различаться
на доли ulp. Округление до 9 знаков склеивает их в одну группу.
"""


@dataclass(frozen=True)
class ArpeggiateStage:
    """Раскладывает одновременные ноты в арпеджио.

    Атрибуты:
        step: Расстояние между соседними нотами арпеджио, в beats.
            Должен быть > 0.
        direction: Порядок обхода: ``"up"`` — по возрастанию ступени,
            ``"down"`` — по убыванию, ``"updown"`` — вверх и обратно
            (крайние ноты не повторяются).
        name: Имя этапа для ``Chain.names``.
    """

    step: float = 0.25
    direction: str = "up"
    name: str = "arpeggiate"

    def __post_init__(self) -> None:
        if self.step <= 0.0:
            raise ValueError(f"Arpeggiate: step должен быть > 0, получено {self.step}")
        if self.direction not in DIRECTIONS:
            raise ValueError(
                f"Arpeggiate: неизвестное направление {self.direction!r}, "
                f"ожидалось одно из {DIRECTIONS}"
            )

    def process(self, batch: list, ctx: StageContext) -> list:
        """Развернуть аккорды в арпеджио.

        Args:
            batch: События дорожки; ожидаются поля ``beat``, ``degree``,
                ``duration`` и ``velocity``.
            ctx: Контекст тика (этап его не использует).

        Returns:
            Новый список, отсортированный по ``(beat, degree)``.
            Группы из одной ноты остаются как есть.
        """
        if len(batch) < 2:
            return list(batch)

        groups = self._group(batch)
        out: list = []
        for index, (beat, notes) in enumerate(groups):
            if len(notes) < 2:
                out.extend(notes)
                continue

            sequence = self._order(notes)
            step = self._fit_step(beat, groups, index, len(sequence))
            for position, note in enumerate(sequence):
                out.append(
                    replace(
                        note,
                        beat=beat + position * step,
                        duration=step,
                    )
                )

        out.sort(key=lambda event: (event.beat, event.degree))
        return out

    # ------------------------------------------------------------------
    # Внутренние
    # ------------------------------------------------------------------

    @staticmethod
    def _group(batch: list) -> list[tuple[float, list]]:
        """Сгруппировать события по позиции, сохранив порядок по времени."""
        buckets: dict[float, list] = {}
        for event in sorted(batch, key=lambda e: (e.beat, e.degree)):
            key = round(event.beat, _BEAT_PRECISION)
            buckets.setdefault(key, []).append(event)
        return sorted(buckets.items())

    def _order(self, notes: list) -> list:
        """Упорядочить ноты аккорда по выбранному направлению."""
        ascending = sorted(notes, key=lambda n: n.degree)
        if self.direction == "up":
            return ascending
        if self.direction == "down":
            return list(reversed(ascending))
        # updown: вверх, затем обратно без повторения крайних нот
        return ascending + list(reversed(ascending[1:-1]))

    def _fit_step(
        self, beat: float, groups: list[tuple[float, list]], index: int, count: int
    ) -> float:
        """Шаг, при котором арпеджио не залезает на следующий аккорд."""
        if index + 1 >= len(groups):
            return self.step
        gap = groups[index + 1][0] - beat
        if gap <= 0.0:
            return self.step
        return min(self.step, gap / count)
