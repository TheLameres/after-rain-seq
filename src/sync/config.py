"""SyncConfig — Pydantic schema for the sync: block in config.yaml."""

from pydantic import BaseModel, Field


class SyncConfig(BaseModel):
    """Clock and sync configuration.

    Parameters
    ----------
    enabled:
        Master switch for the clock subsystem.
    clock_source:
        Initial clock source: ``"internal"``, ``"midi"``, or ``"link"``.
    midi_clock_device:
        MIDI input port name for MIDI clock.  ``None`` means use
        ``ISOBAR_DEFAULT_MIDI_IN`` environment variable.
    bpm:
        Initial tempo in BPM (used for internal and link sources).
    swing_amount:
        Global swing amount, 0.0–1.0.  ``0.0`` = no swing (passthrough).
        Applied to all tracks via duration transformation.
    """

    enabled: bool = False
    clock_source: str = "internal"
    midi_clock_device: str | None = None
    bpm: float = Field(default=120.0, ge=20.0, le=300.0)
    swing_amount: float = Field(default=0.0, ge=0.0, le=1.0)
