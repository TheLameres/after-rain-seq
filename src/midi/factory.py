"""Factory functions — the single point where the MIDI library is chosen.

To switch from mido to another library (e.g. rtmidi-python):
1. Create ``src/midi/rtmidi_impl.py`` with ``RtmidiInPort``, ``RtmidiOutPort``, ``RtmidiRegistry``
2. Update the imports and return values below
3. All higher-level code (``translator.py``, ``encoder_handler.py``, etc.) remains unchanged
"""

from src.midi.abc import MidiInPort, MidiOutPort, MidiPortRegistry
from src.midi.mido_impl import MidoInPort, MidoOutPort, MidoRegistry


def create_in_port() -> MidiInPort:
    """Create a MIDI input port."""
    return MidoInPort()


def create_out_port() -> MidiOutPort:
    """Create a MIDI output port."""
    return MidoOutPort()


def create_registry() -> MidiPortRegistry:
    """Create a port registry for discovery."""
    return MidoRegistry()
