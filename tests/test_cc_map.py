"""Tests for CCMap — logical parameter names to CC numbers per port."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.sync.cc_map import (
    DEFAULT_CC_PARAMS,
    CCMap,
    CCMapConfig,
    CCMapError,
    CCParamOverride,
    default_cc_map_config,
)


def make_config(**kwargs) -> CCMapConfig:
    """Shortcut for building CCMapConfig."""
    return CCMapConfig(**kwargs)


def make_map(**kwargs) -> CCMap:
    """Shortcut for building CCMap from config."""
    return CCMap(make_config(**kwargs))


class TestCCParamOverride:
    """Tests for the Pydantic override model."""

    def test_defaults(self):
        """Default override: no invert, full range."""
        o = CCParamOverride(cc=22)
        assert o.cc == 22
        assert o.invert is False
        assert o.range == (0, 127)

    def test_cc_out_of_range(self):
        """CC number must be 0-127."""
        with pytest.raises(ValidationError):
            CCParamOverride(cc=128)

    def test_invalid_range(self):
        """Range must satisfy 0 <= lo < hi <= 127."""
        with pytest.raises(ValidationError):
            CCParamOverride(cc=74, range=(100, 50))


class TestCCMapConfig:
    """Tests for config validation."""

    def test_empty_config_valid(self):
        """Empty default and ports is valid."""
        cfg = make_config()
        assert cfg.default == {}
        assert cfg.ports == {}

    def test_default_params(self):
        """Default params dict is accepted."""
        cfg = make_config(default=DEFAULT_CC_PARAMS)
        assert cfg.default["filter"] == 74
        assert cfg.default["volume"] == 7

    def test_port_override_int(self):
        """Port override as plain int is valid."""
        cfg = make_config(
            default={"filter": 74},
            ports={"Synth A": {"filter": 22}},
        )
        assert cfg.ports["Synth A"]["filter"] == 22

    def test_port_override_full(self):
        """Port override as CCParamOverride dict is valid."""
        cfg = make_config(
            default={"filter": 74},
            ports={
                "Old Synth": {"filter": {"cc": 74, "invert": True, "range": [20, 110]}}
            },
        )
        override = cfg.ports["Old Synth"]["filter"]
        assert isinstance(override, CCParamOverride)
        assert override.invert is True

    def test_port_param_not_in_default_raises(self):
        """Port override for param not in default raises ValidationError."""
        with pytest.raises(ValidationError, match="not defined in cc_map.default"):
            make_config(
                default={"filter": 74},
                ports={"Synth A": {"unknown_param": 22}},
            )

    def test_no_automation_true_valid(self):
        """_no_automation: true is valid."""
        cfg = make_config(
            default={"filter": 74},
            ports={"LCXL3": {"_no_automation": True}},
        )
        assert cfg.ports["LCXL3"]["_no_automation"] is True

    def test_no_automation_non_true_raises(self):
        """_no_automation with non-true value raises."""
        with pytest.raises(ValidationError, match="must be true"):
            make_config(
                default={"filter": 74},
                ports={"LCXL3": {"_no_automation": False}},
            )


class TestCCMapResolve:
    """Tests for CCMap.resolve() — the core resolution logic."""

    def test_resolve_from_default(self):
        """Param not overridden by port resolves from default."""
        cc_map = make_map(default={"filter": 74, "volume": 7})
        entry = cc_map.resolve("Any Port", "filter")
        assert entry is not None
        assert entry.cc == 74
        assert entry.invert is False
        assert entry.range == (0, 127)

    def test_resolve_port_override_int(self):
        """Port override as int replaces default CC number."""
        cc_map = make_map(
            default={"filter": 74},
            ports={"Synth A": {"filter": 22}},
        )
        entry = cc_map.resolve("Synth A", "filter")
        assert entry is not None
        assert entry.cc == 22

    def test_resolve_port_override_full(self):
        """Port override as CCParamOverride applies invert and range."""
        cc_map = make_map(
            default={"filter": 74},
            ports={
                "Old Synth": {
                    "filter": CCParamOverride(cc=74, invert=True, range=(20, 110))
                }
            },
        )
        entry = cc_map.resolve("Old Synth", "filter")
        assert entry is not None
        assert entry.cc == 74
        assert entry.invert is True
        assert entry.range == (20, 110)

    def test_resolve_other_port_uses_default(self):
        """Port without override falls back to default."""
        cc_map = make_map(
            default={"filter": 74},
            ports={"Synth A": {"filter": 22}},
        )
        entry = cc_map.resolve("Synth B", "filter")
        assert entry is not None
        assert entry.cc == 74

    def test_resolve_unknown_param_raises(self):
        """Unknown param (not in default, no override) raises CCMapError."""
        cc_map = make_map(default={"filter": 74})
        with pytest.raises(CCMapError, match="not found"):
            cc_map.resolve("Any Port", "reverb")

    def test_resolve_no_automation_returns_none(self):
        """_no_automation port returns None instead of entry."""
        cc_map = make_map(
            default={"filter": 74},
            ports={"LCXL3": {"_no_automation": True}},
        )
        entry = cc_map.resolve("LCXL3", "filter")
        assert entry is None

    def test_resolve_no_automation_does_not_raise_for_unknown(self):
        """_no_automation port returns None even for unknown params."""
        cc_map = make_map(
            default={"filter": 74},
            ports={"LCXL3": {"_no_automation": True}},
        )
        # Should not raise CCMapError — port opts out entirely
        entry = cc_map.resolve("LCXL3", "unknown_param")
        assert entry is None


class TestCCMapQueries:
    """Tests for is_automation_enabled, known_params, automation_ports."""

    def test_is_automation_enabled_default(self):
        """Port not in config has automation enabled."""
        cc_map = make_map(default={"filter": 74})
        assert cc_map.is_automation_enabled("Any Port") is True

    def test_is_automation_enabled_no_automation(self):
        """Port with _no_automation has automation disabled."""
        cc_map = make_map(
            default={"filter": 74},
            ports={"LCXL3": {"_no_automation": True}},
        )
        assert cc_map.is_automation_enabled("LCXL3") is False

    def test_known_params(self):
        """known_params returns all default param names."""
        cc_map = make_map(default={"filter": 74, "volume": 7})
        params = cc_map.known_params()
        assert params == frozenset({"filter", "volume"})

    def test_automation_ports(self):
        """automation_ports returns labels with _no_automation."""
        cc_map = make_map(
            default={"filter": 74},
            ports={
                "LCXL3": {"_no_automation": True},
                "Synth A": {"filter": 22},
            },
        )
        ports = cc_map.automation_ports()
        assert ports == frozenset({"LCXL3"})


class TestDefaultCCMapConfig:
    """Tests for the pre-populated default config."""

    def test_has_all_default_params(self):
        """Default config includes all DEFAULT_CC_PARAMS."""
        cfg = default_cc_map_config()
        for name, cc in DEFAULT_CC_PARAMS.items():
            assert cfg.default[name] == cc

    def test_create_cc_map_from_default(self):
        """CCMap created from default config resolves all params."""
        cc_map = CCMap(default_cc_map_config())
        for name, cc in DEFAULT_CC_PARAMS.items():
            entry = cc_map.resolve("Any Port", name)
            assert entry is not None
            assert entry.cc == cc


class TestRepr:
    """Tests for __repr__."""

    def test_repr(self):
        """Repr includes counts and no_automation ports."""
        cc_map = make_map(
            default={"filter": 74},
            ports={"LCXL3": {"_no_automation": True}},
        )
        r = repr(cc_map)
        assert "params=1" in r
        assert "ports=1" in r
        assert "LCXL3" in r
