"""Контракт этапа Densify (§3.3, B4): решение по позиции, а не по порядку."""

from __future__ import annotations

from dataclasses import dataclass

from src.session.modify.densify import DensifyStage

from src.session.engine.generators import _density_keep
from src.session.modify import Chain, StageContext

CTX = StageContext(beat=0.0, bpm=120.0, track_name="Pad 1")


@dataclass
class N:
    beat: float


def _notes(n: int = 8) -> list[N]:
    return [N(float(i)) for i in range(n)]


class Drop:
    """Тестовый сосед: удаляет события с заданной чётностью beat."""

    name = "drop"

    def __init__(self, keep_even: bool) -> None:
        self.keep_even = keep_even

    def process(self, batch: list[N], ctx: StageContext) -> list[N]:
        return [n for n in batch if (int(n.beat) % 2 == 0) == self.keep_even]


class TestDensifyMatchesGenerator:
    """Одиночный Densify даёт тот же набор, что генератор."""

    def test_full_density_keeps_all(self) -> None:
        out = Chain([DensifyStage(1.0)]).process(_notes(), CTX)
        assert [int(n.beat) for n in out] == list(range(8))

    def test_partial_density_matches_generator(self) -> None:
        for d in (0.0, 0.25, 0.5, 0.75):
            expected = [i for i in range(8) if _density_keep(i, d)]
            got = [int(n.beat) for n in Chain([DensifyStage(d)]).process(_notes(), CTX)]
            assert got == expected, f"density={d}"

    def test_accent_step_always_kept(self) -> None:
        for d in (0.0, 0.1, 0.5):
            out = Chain([DensifyStage(d)]).process(_notes(), CTX)
            assert any(n.beat == 0.0 for n in out), f"density={d}"


class TestDensifyIgnoresNeighbours:
    """B4 ключевое: решение не зависит от того, что удалил сосед."""

    def test_after_neighbour_drop_same_decision(self) -> None:
        d = 0.5
        alone = [int(n.beat) for n in Chain([DensifyStage(d)]).process(_notes(), CTX)]
        after_drop = Chain([Drop(keep_even=True), DensifyStage(d)]).process(
            _notes(), CTX
        )
        # Для чётных шагов решение то же, что генератор принял бы на тех же позициях
        expected = [i for i in range(0, 8, 2) if _density_keep(i, d)]
        assert [int(n.beat) for n in after_drop] == expected
        assert set(expected) <= set(alone)

    def test_order_with_drop_does_not_change_survivors(self) -> None:
        d = 0.5
        a = Chain([DensifyStage(d), Drop(keep_even=True)]).process(_notes(), CTX)
        b = Chain([Drop(keep_even=True), DensifyStage(d)]).process(_notes(), CTX)
        assert {int(n.beat) for n in a} == {int(n.beat) for n in b}


class TestDensifyDeterminism:
    def test_same_input_same_output(self) -> None:
        first = [int(n.beat) for n in Chain([DensifyStage(0.5)]).process(_notes(), CTX)]
        for _ in range(5):
            again = [
                int(n.beat) for n in Chain([DensifyStage(0.5)]).process(_notes(), CTX)
            ]
            assert again == first

    def test_input_not_mutated(self) -> None:
        src = _notes()
        Chain([DensifyStage(0.0)]).process(src, CTX)
        assert [n.beat for n in src] == [float(i) for i in range(8)]


class TestNotYetWired:
    """Densify НЕ подключён к движку: генератор уже прореживает по density.

    Подключение без переноса прореживания из генератора дало бы двойное
    прореживание (pad d=0.5: 12 -> 9 вместо 12 -> 6). Этот тест фиксирует
    текущее состояние, чтобы подключение не произошло молча.
    """

    def test_generator_already_thins_by_density(self) -> None:
        import inspect

        from src.session.engine import generators

        source = inspect.getsource(generators)
        assert "_density_keep(i, track.density)" in source
