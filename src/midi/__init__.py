"""MIDI abstraction layer.

Provides library-agnostic MIDI types (``MidiMessage``) and abstract
interfaces (``MidiInPort``, ``MidiOutPort``, ``MidiPortRegistry``).

The default implementation uses mido::

    from src.midi import create_in_port, create_out_port, create_registry

To swap the underlying MIDI library, replace the factory implementations
in ``src/midi/factory.py`` — all higher-level code remains unchanged.

Public API
----------
- ``MidiMessage`` — immutable, frozen dataclass representing any MIDI message
- ``MidiChannel``, ``MidiCC``, ``MidiValue``, ``MidiNote`` — semantic int wrappers
- ``MidiInPort`` — abstract callback-based input
- ``MidiOutPort`` — abstract send-only output
- ``MidiPortRegistry`` — port discovery (list names, find by substring)
- ``create_in_port()``, ``create_out_port()``, ``create_registry()`` — factory functions
"""

from src.midi.abc import (
    MidiCC,
    MidiChannel,
    MidiInPort,
    MidiMessage,
    MidiNote,
    MidiOutPort,
    MidiPortRegistry,
    MidiValue,
)
from src.midi.factory import create_in_port, create_out_port, create_registry

__all__ = [
    "MidiCC",
    "MidiChannel",
    "MidiInPort",
    "MidiMessage",
    "MidiNote",
    "MidiOutPort",
    "MidiPortRegistry",
    "MidiValue",
    "create_in_port",
    "create_out_port",
    "create_registry",
]
