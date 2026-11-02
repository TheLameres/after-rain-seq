"""Logical CC parameter names → MIDI CC numbers per port.

This module provides:
- :class:`CCParamOverride` — Pydantic model for a per-port parameter override
- :class:`CCMapConfig` — Pydantic model for the ``cc_map:`` config section
- :class:`CCMapError` — raised when a parameter cannot be resolved
- :class:`CCMap` — runtime resolver: logical name → :class:`CCMapEntry`

Design (from plan v5.4 §2.4):
- Generators use **logical names** (``filter``, ``resonance`` …), never raw CC numbers.
- The mapping lives in **one place** — this module — not scattered across generators.
- A missing parameter is an **error at config load time**, never a silent skip.
- Ports can have ``_no_automation: true`` to opt out of CC automation entirely
  (e.g. controller ports like Launch Control XL 3).
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field, model_validator

from src.midi.abc import MidiCC
from src.sync.cc_map_entry import CCMapEntry

log = logging.getLogger(__name__)

# Special key in the ports dict that disables CC automation for a port.
_NO_AUTOMATION_KEY = "_no_automation"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CCMapError(Exception):
    """Raised when a logical parameter name cannot be resolved."""


# ---------------------------------------------------------------------------
# Config models
# ---------------------------------------------------------------------------


class CCParamOverride(BaseModel):
    """Per-port override for a single logical parameter.

    Can be specified as a plain int (CC number only) or a full override
    with invert and/or range in config.yaml.
    """

    cc: int = Field(ge=0, le=127)
    invert: bool = False
    range: tuple[int, int] = (0, 127)

    @model_validator(mode="after")
    def _validate_range(self) -> CCParamOverride:
        lo, hi = self.range
        if not (0 <= lo < hi <= 127):
            raise ValueError(
                f"range must satisfy 0 <= lo < hi <= 127, got {self.range}"
            )
        return self


class CCMapConfig(BaseModel):
    """The ``cc_map:`` section in config.yaml.

    Example
    -------
    .. code-block:: yaml

        cc_map:
          default:
            filter: 74
            resonance: 71
          ports:
            "Синт A":
              filter: 22
            "Старый ромплер":
              filter:
                cc: 74
                invert: true
                range: [20, 110]
            "Launch Control XL 3 DAW In":
              _no_automation: true
    """

    default: dict[str, int] = Field(default_factory=dict)
    """Logical name → CC number.  Used when the port has no override."""

    ports: dict[str, dict[str, CCParamOverride | int | bool]] = Field(
        default_factory=dict
    )
    """Port label → {logical name → CC number or full override}.

    The special key ``_no_automation`` (value ``True``) disables CC
    automation for the port entirely.
    """

    @model_validator(mode="after")
    def _validate_port_params(self) -> CCMapConfig:
        for port_label, params in self.ports.items():
            for param_name, override in params.items():
                if param_name == _NO_AUTOMATION_KEY:
                    if override is not True:
                        raise ValueError(
                            f"cc_map.ports[{port_label!r}].{_NO_AUTOMATION_KEY} "
                            "must be true"
                        )
                    continue
                if param_name not in self.default:
                    raise ValueError(
                        f"cc_map.ports[{port_label!r}]: parameter {param_name!r} "
                        f"is not defined in cc_map.default"
                    )
        return self


# ---------------------------------------------------------------------------
# Runtime resolver
# ---------------------------------------------------------------------------


class CCMap:
    """Resolves logical parameter names to CC entries per port.

    Parameters
    ----------
    config:
        Validated :class:`CCMapConfig` instance.
    """

    def __init__(self, config: CCMapConfig) -> None:
        self._default = config.default
        self._ports = config.ports

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, port_label: str, param_name: str) -> CCMapEntry | None:
        """Resolve *param_name* to a :class:`CCMapEntry` for *port_label*.

        Resolution order:

        1. Port override (int or :class:`CCParamOverride`) — highest priority.
        2. ``default`` — fallback.
        3. Neither → :class:`CCMapError`.

        Returns ``None`` (not an error) when the port has
        ``_no_automation: true`` — the caller should skip sending.

        Parameters
        ----------
        port_label:
            Human-readable port label from config.
        param_name:
            Logical parameter name (e.g. ``"filter"``).

        Returns
        -------
        CCMapEntry | None
            Resolved entry, or ``None`` if the port opts out of automation.

        Raises
        ------
        CCMapError
            If *param_name* is not defined in ``default`` and not overridden
            for *port_label*.
        """
        port_params = self._ports.get(port_label)

        # Port opts out of CC automation entirely
        if port_params is not None and port_params.get(_NO_AUTOMATION_KEY) is True:
            return None

        # Port-level override
        if port_params is not None and param_name in port_params:
            override = port_params[param_name]
            if isinstance(override, CCParamOverride):
                return CCMapEntry(
                    cc=MidiCC(override.cc),
                    invert=override.invert,
                    range=override.range,
                )
            return CCMapEntry(cc=MidiCC(override))

        # Default
        if param_name in self._default:
            return CCMapEntry(cc=MidiCC(self._default[param_name]))

        raise CCMapError(
            f"CC parameter {param_name!r} not found in cc_map.default "
            f"and no override for port {port_label!r}"
        )

    def is_automation_enabled(self, port_label: str) -> bool:
        """Return ``False`` if the port has ``_no_automation: true``."""
        port_params = self._ports.get(port_label)
        if port_params is None:
            return True
        return port_params.get(_NO_AUTOMATION_KEY) is not True

    def known_params(self) -> frozenset[str]:
        """Return all logical parameter names defined in ``default``."""
        return frozenset(self._default.keys())

    def automation_ports(self) -> frozenset[str]:
        """Return labels of all ports that have ``_no_automation: true``."""
        return frozenset(
            label
            for label, params in self._ports.items()
            if params.get(_NO_AUTOMATION_KEY) is True
        )

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"CCMap(params={len(self._default)}, "
            f"ports={len(self._ports)}, "
            f"no_automation={sorted(self.automation_ports())})"
        )


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------


def create_cc_map(config: CCMapConfig | None = None) -> CCMap:
    """Create a :class:`CCMap` from a config, or with empty defaults."""
    if config is None:
        config = CCMapConfig()
    return CCMap(config)


# ---------------------------------------------------------------------------
# Default parameter table (GM / MIDI CC Plus conventions)
# ---------------------------------------------------------------------------

DEFAULT_CC_PARAMS: dict[str, int] = {
    "filter": 74,
    "resonance": 71,
    "reverb": 91,
    "delay": 93,
    "delay_feedback": 94,
    "mod_wheel": 1,
    "volume": 7,
    "pan": 10,
}
"""Default logical-name → CC-number mapping.

These follow the GM / MIDI CC Plus conventions and work for most synths
out of the box.  Individual ports override in ``cc_map.ports``.
"""


def default_cc_map_config() -> CCMapConfig:
    """Return a :class:`CCMapConfig` pre-populated with :data:`DEFAULT_CC_PARAMS`."""
    return CCMapConfig(default=dict(DEFAULT_CC_PARAMS))
