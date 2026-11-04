"""Тесты MacroAxis/MacroAxes: состав осей, валидация, конверсии CC↔unit."""

from __future__ import annotations

import pytest

from src.app.ui.macro_axes import MacroAxes, MacroAxis, cc_to_unit, unit_to_cc
from src.config import UiConfig


class TestAxisEnum:
    def test_values_stable(self) -> None:
        assert MacroAxis.DENSITY.value == "DEN"
        assert MacroAxis.MUTATE.value == "MUT"
        assert MacroAxis.SPACE.value == "SPACE"
        assert MacroAxis.DEPTH.value == "DEPTH"
        assert MacroAxis.TONE.value == "TONE"

    def test_five_axes(self) -> None:
        assert len(MacroAxis) == 5

    def test_cc_axis_flags(self) -> None:
        assert MacroAxis.TONE.is_cc_axis
        assert MacroAxis.SPACE.is_cc_axis
        assert MacroAxis.DEPTH.is_cc_axis
        assert not MacroAxis.DENSITY.is_cc_axis
        assert not MacroAxis.MUTATE.is_cc_axis


class TestConversions:
    def test_cc_to_unit(self) -> None:
        assert cc_to_unit(0) == 0.0
        assert cc_to_unit(127) == 1.0
        assert cc_to_unit(64) == pytest.approx(64 / 127)

    def test_cc_to_unit_clamps(self) -> None:
        assert cc_to_unit(200) == 1.0
        assert cc_to_unit(-5) == 0.0

    def test_unit_to_cc_roundtrip(self) -> None:
        assert unit_to_cc(0.0) == 0
        assert unit_to_cc(1.0) == 127

    def test_unit_to_cc_clamps(self) -> None:
        assert unit_to_cc(2.0) == 127
        assert unit_to_cc(-1.0) == 0


class TestMacroAxesDefaults:
    def test_default_mapping(self) -> None:
        axes = MacroAxes()
        assert axes.cc_params(MacroAxis.TONE) == ("filter",)
        assert axes.cc_params(MacroAxis.SPACE) == ("reverb", "delay")
        assert axes.cc_params(MacroAxis.DEPTH) == ("resonance",)

    def test_from_none_config(self) -> None:
        assert MacroAxes.from_ui_config(None).cc_params(MacroAxis.TONE) == ("filter",)

    def test_from_ui_config(self) -> None:
        ui = UiConfig(
            macro_axes={"tone": ["mod_wheel"], "space": ["reverb"], "depth": ["filter"]}
        )
        axes = MacroAxes.from_ui_config(ui.macro_axes)
        assert axes.cc_params(MacroAxis.TONE) == ("mod_wheel",)

    def test_non_cc_axis_raises(self) -> None:
        axes = MacroAxes()
        with pytest.raises(ValueError, match="CC"):
            axes.cc_params(MacroAxis.DENSITY)


class TestValidation:
    def test_unknown_param_rejected(self) -> None:
        with pytest.raises(ValueError, match="неизвестный параметр"):
            MacroAxes({"tone": ["not_a_param"]})

    def test_unknown_axis_rejected(self) -> None:
        with pytest.raises(ValueError, match="неизвестная ось"):
            MacroAxes({"warp": ["filter"]})

    def test_empty_axis_rejected(self) -> None:
        with pytest.raises(ValueError, match="без параметров"):
            MacroAxes({"tone": []})

    def test_ui_config_validation_rejects_unknown_param(self) -> None:
        with pytest.raises(ValueError):
            UiConfig(macro_axes={"tone": ["bogus"]})
