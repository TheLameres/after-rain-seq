"""Контракт цепочки модификаций (§3.3, этап B: B1, B2)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.session.modify import Chain, Stage, StageContext

CTX = StageContext(beat=0.0, bpm=120.0, track_name="Pad 1")


@dataclass
class Ev:
    beat: float
    tag: str = ""


class Append:
    """Тестовый этап: добавляет свою метку к каждому событию."""

    name = "append"

    def __init__(self, label: str) -> None:
        self.label = label

    def process(self, batch: list[Ev], ctx: StageContext) -> list[Ev]:
        return [Ev(e.beat, e.tag + self.label) for e in batch]


class DropAll:
    """Тестовый этап: отбрасывает все события."""

    name = "drop"

    def process(self, batch: list[Ev], ctx: StageContext) -> list[Ev]:
        return []


class Boom:
    """Тестовый этап: падает, если его вообще вызвали."""

    name = "boom"

    def process(self, batch: list[Ev], ctx: StageContext) -> list[Ev]:
        raise AssertionError("этап не должен вызываться на пустом списке")


def _events() -> list[Ev]:
    return [Ev(0.0), Ev(0.5), Ev(1.0)]


class TestEmptyChainIsIdentity:
    """B1: пустая цепочка даёт тот же поток событий."""

    def test_same_content(self) -> None:
        out = Chain([]).process(_events(), CTX)
        assert out == _events()

    def test_returns_new_list(self) -> None:
        src = _events()
        out = Chain([]).process(src, CTX)
        assert out is not src

    def test_empty_input_stays_empty(self) -> None:
        assert Chain([]).process([], CTX) == []

    def test_len_zero(self) -> None:
        assert len(Chain([])) == 0


class TestOrderAndComposition:
    def test_stages_run_in_order(self) -> None:
        out = Chain([Append("a"), Append("b")]).process(_events(), CTX)
        assert all(e.tag == "ab" for e in out)

    def test_order_matters(self) -> None:
        ab = Chain([Append("a"), Append("b")]).process(_events(), CTX)
        ba = Chain([Append("b"), Append("a")]).process(_events(), CTX)
        assert ab[0].tag == "ab"
        assert ba[0].tag == "ba"

    def test_names_reflect_order(self) -> None:
        chain = Chain([Append("x"), DropAll()])
        assert chain.names == ("append", "drop")


class TestTruncationToZero:
    """B2: цепочка умеет обрезать список до нуля и не вызывать дальше."""

    def test_drop_empties_output(self) -> None:
        assert Chain([DropAll()]).process(_events(), CTX) == []

    def test_later_stages_not_called_after_empty(self) -> None:
        # Boom упал бы, если бы его вызвали на пустом списке.
        out = Chain([DropAll(), Boom()]).process(_events(), CTX)
        assert out == []

    def test_input_not_mutated(self) -> None:
        src = _events()
        snapshot = [Ev(e.beat, e.tag) for e in src]
        Chain([Append("z"), DropAll()]).process(src, CTX)
        assert src == snapshot


class TestStageProtocolAcceptsReadOnlyName:
    """`Stage.name` объявлен как property, а не изменяемое поле.

    Иначе frozen-этапы (`ArpeggiateStage`, `DensifyStage`) не проходят
    проверку протокола: pyright пишет «"name" is not read-only in protocol»,
    mypy — «Protocol member Stage.name expected settable variable».
    """

    def test_frozen_stage_satisfies_protocol(self) -> None:
        from src.session.modify.arpeggiate import ArpeggiateStage
        from src.session.modify.densify import DensifyStage

        stages: list[Stage[Ev]] = [ArpeggiateStage(), DensifyStage(1.0)]
        assert [s.name for s in stages] == ["arpeggiate", "densify"]

    def test_protocol_name_is_read_only(self) -> None:
        from src.session.modify.arpeggiate import ArpeggiateStage

        stage = ArpeggiateStage()
        with pytest.raises(AttributeError):
            stage.name = "changed"  # type: ignore[misc]

    def test_mutable_stage_still_accepted(self) -> None:
        """Этап с обычным атрибутом тоже подходит — протокол только читает."""
        stages: list[Stage[Ev]] = [Append("a")]
        assert stages[0].name == "append"
