"""Реестр этапов цепочки: build/format/parse, ошибки, круговая согласованность."""

from __future__ import annotations

import pytest

from src.session.events.note_event import NoteEvent
from src.session.modify.arpeggiate import ArpeggiateStage
from src.session.modify.chain import Stage
from src.session.modify.densify import DensifyStage
from src.session.modify.stage_registry import (
    build_stage,
    format_stage,
    parse_stage_spec,
)


class TestBuildStage:
    def test_arpeggiate_defaults(self) -> None:
        stage = build_stage("arpeggiate", {})
        assert isinstance(stage, ArpeggiateStage)
        assert stage.step == 0.25
        assert stage.direction == "up"

    def test_arpeggiate_explicit_params(self) -> None:
        stage = build_stage("arpeggiate", {"step": "0.5", "direction": "down"})
        assert stage.step == 0.5
        assert stage.direction == "down"

    def test_densify_explicit_density(self) -> None:
        stage = build_stage("densify", {"density": "0.5"})
        assert isinstance(stage, DensifyStage)
        assert stage.density == 0.5

    def test_unknown_name_lists_available(self) -> None:
        with pytest.raises(ValueError, match="доступные этапы") as excinfo:
            build_stage("transpose", {})
        assert "arpeggiate" in str(excinfo.value)
        assert "densify" in str(excinfo.value)

    def test_unknown_param_is_error(self) -> None:
        with pytest.raises(ValueError, match="неизвестный параметр"):
            build_stage("arpeggiate", {"foo": "1"})

    def test_non_numeric_value_is_error(self) -> None:
        with pytest.raises(ValueError, match="должен быть числом"):
            build_stage("arpeggiate", {"step": "abc"})

    def test_missing_required_density_is_error(self) -> None:
        with pytest.raises(ValueError, match="обязательный"):
            build_stage("densify", {})


class TestFormatStage:
    def test_arpeggiate(self) -> None:
        assert format_stage(ArpeggiateStage()) == "arpeggiate step=0.25 direction=up"

    def test_densify(self) -> None:
        assert format_stage(DensifyStage(0.5)) == "densify density=0.5"


class TestParseStageSpec:
    def test_arpeggiate_with_params(self) -> None:
        name, params = parse_stage_spec("arpeggiate step=0.25 direction=up")
        assert name == "arpeggiate"
        assert params == {"step": "0.25", "direction": "up"}

    def test_name_only(self) -> None:
        assert parse_stage_spec("densify density=0.5") == (
            "densify",
            {"density": "0.5"},
        )

    def test_empty_spec_is_error(self) -> None:
        with pytest.raises(ValueError, match="пуста"):
            parse_stage_spec("   ")

    def test_token_without_value_is_error(self) -> None:
        with pytest.raises(ValueError, match="без значения"):
            parse_stage_spec("arpeggiate step")

    def test_duplicate_key_is_error(self) -> None:
        with pytest.raises(ValueError, match="дубликат"):
            parse_stage_spec("arpeggiate step=0.5 step=0.25")


class TestRoundTrip:
    @pytest.mark.parametrize(
        "stage",
        [
            ArpeggiateStage(),
            ArpeggiateStage(step=0.5, direction="down"),
            DensifyStage(0.7),
        ],
    )
    def test_parse_format_circle(self, stage: Stage[NoteEvent]) -> None:
        """parse_stage_spec(format_stage(s)) восстанавливает этап."""
        name, params = parse_stage_spec(format_stage(stage))
        assert build_stage(name, params) == stage
