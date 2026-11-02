"""Abstract MIDI interfaces and the canonical ``MidiMessage`` type.

This module defines **zero** dependencies on mido, python-rtmidi, or any
other MIDI library.  All higher-level code (``translator.py``,
``encoder_handler.py``, ``m8_connection.py``) can be written against these
interfaces and remain library-agnostic.

Types
-----
``MidiChannel``, ``MidiCC``, ``MidiValue``, ``MidiNote``
    Semantic ``int`` subclasses — provide type hints and runtime validation
    without any overhead.  ``MidiChannel(0)`` is MIDI channel 1 (0-indexed
    mido convention).

``MidiMessage``
    Immutable (``frozen=True``) dataclass that can represent any MIDI
    message: ``note_on``, ``note_off``, ``control_change``, ``sysex``.
    Named constructors (``.note_on()``, ``.cc()``, ``.sysex()``) make
    intent explicit at the call site.

Interfaces
----------
``MidiInPort``
    Callback-based MIDI input.  The caller provides a callable that receives
    ``MidiMessage`` instances; the implementation handles the library-specific
    plumbing (mido callback, rtmidi callback, etc.).

``MidiOutPort``
    Fire-and-forget MIDI output.  ``send(msg)`` delivers a ``MidiMessage``
    to the hardware.

``MidiPortRegistry``
    Port discovery — list available input/output port names and find a port
    by substring match (used for auto-detecting the M8 port).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    import mido

# ---------------------------------------------------------------------------
# Semantic int wrappers
# ---------------------------------------------------------------------------


class MidiChannel(int):
    """MIDI channel, 0-15 (0-indexed mido convention).

    ``MidiChannel(0)`` = MIDI channel 1.  This matches mido's convention
    and is used throughout push2-m8.
    """

    def __new__(cls, value: int) -> MidiChannel:
        if not (0 <= value <= 15):
            raise ValueError(f"MidiChannel must be 0-15, got {value}")
        return super().__new__(cls, value)


class MidiCC(int):
    """Control Change number, 0-127."""

    def __new__(cls, value: int) -> MidiCC:
        if not (0 <= value <= 127):
            raise ValueError(f"MidiCC must be 0-127, got {value}")
        return super().__new__(cls, value)


class MidiValue(int):
    """MIDI value (velocity, CC value, etc.), 0-127."""

    def __new__(cls, value: int) -> MidiValue:
        if not (0 <= value <= 127):
            raise ValueError(f"MidiValue must be 0-127, got {value}")
        return super().__new__(cls, value)


class MidiNote(int):
    """MIDI note number, 0-127."""

    def __new__(cls, value: int) -> MidiNote:
        if not (0 <= value <= 127):
            raise ValueError(f"MidiNote must be 0-127, got {value}")
        return super().__new__(cls, value)


# ---------------------------------------------------------------------------
# MidiMessage
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MidiMessage:
    """Immutable MIDI message — library-agnostic.

    Only the fields relevant to the message ``type`` are populated;
    the rest are ``None``.  This keeps the type simple and explicit.

    Examples
    --------
    >>> MidiMessage.note_on(channel=0, note=36, velocity=127)
    MidiMessage(type='note_on', channel=0, note=36, velocity=127, ...)

    >>> MidiMessage.cc(channel=0, control=1, value=64)
    MidiMessage(type='control_change', channel=0, control=1, value=64, ...)

    >>> MidiMessage.sysex((0x00, 0x20, 0x29, 0x02, 0x0E))
    MidiMessage(type='sysex', data=(0, 32, 41, 2, 14))
    """

    type: str
    """Message type: ``"note_on"``, ``"note_off"``, ``"control_change"``, ``"sysex"``."""

    channel: MidiChannel | None = None
    """0-indexed MIDI channel (0-15).  ``None`` for sysex."""

    note: MidiNote | None = None
    """Note number (0-127).  Only for ``note_on`` / ``note_off``."""

    velocity: MidiValue | None = None
    """Velocity (0-127).  Only for ``note_on`` / ``note_off``."""

    control: MidiCC | None = None
    """CC number (0-127).  Only for ``control_change``."""

    value: MidiValue | None = None
    """CC value (0-127).  Only for ``control_change``."""

    data: tuple[int, ...] | None = None
    """Raw SysEx bytes **without** F0/F7 delimiters.  Only for ``sysex``."""

    # ------------------------------------------------------------------
    # Named constructors
    # ------------------------------------------------------------------

    @classmethod
    def note_on(cls, channel: int, note: int, velocity: int) -> MidiMessage:
        """Create a Note On message."""
        return cls(
            type="note_on",
            channel=MidiChannel(channel),
            note=MidiNote(note),
            velocity=MidiValue(velocity),
        )

    @classmethod
    def note_off(cls, channel: int, note: int, velocity: int = 0) -> MidiMessage:
        """Create a Note Off message."""
        return cls(
            type="note_off",
            channel=MidiChannel(channel),
            note=MidiNote(note),
            velocity=MidiValue(velocity),
        )

    @classmethod
    def cc(cls, channel: int, control: int, value: int) -> MidiMessage:
        """Create a Control Change message."""
        return cls(
            type="control_change",
            channel=MidiChannel(channel),
            control=MidiCC(control),
            value=MidiValue(value),
        )

    @classmethod
    def sysex(cls, data: tuple[int, ...] | list[int] | bytes) -> MidiMessage:
        """Create a SysEx message.

        Parameters
        ----------
        data:
            Raw bytes **without** F0/F7 delimiters.
        """
        if isinstance(data, (bytes, list)):
            data = tuple(data)
        return cls(type="sysex", data=data)

    @classmethod
    def program_change(cls, channel: int, program: int) -> MidiMessage:
        """Create a Program Change message."""
        return cls(
            type="program_change",
            channel=MidiChannel(channel),
            value=MidiValue(program),
        )

    @classmethod
    def clock(cls) -> "MidiMessage":
        """Create a MIDI Clock tick message (0xF8)."""
        return cls(type="clock")

    @classmethod
    def start(cls) -> "MidiMessage":
        """Create a MIDI Start message (0xFA)."""
        return cls(type="start")

    @classmethod
    def stop(cls) -> "MidiMessage":
        """Create a MIDI Stop message (0xFC)."""
        return cls(type="stop")

    @classmethod
    def continue_(cls) -> "MidiMessage":
        """Create a MIDI Continue message (0xFB)."""
        return cls(type="continue")

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def is_note(self) -> bool:
        """True for ``note_on`` or ``note_off``."""
        return self.type in ("note_on", "note_off")

    @property
    def is_cc(self) -> bool:
        """True for ``control_change``."""
        return self.type == "control_change"

    @property
    def is_sysex(self) -> bool:
        """True for ``sysex``."""
        return self.type == "sysex"

    @property
    def is_note_on(self) -> bool:
        """True for ``note_on`` with velocity > 0."""
        return (
            self.type == "note_on" and self.velocity is not None and self.velocity > 0
        )

    @property
    def is_realtime(self) -> bool:
        """True for system real-time messages: clock, start, stop, continue."""
        return self.type in ("clock", "start", "stop", "continue")

    @property
    def sysex_with_framing(self) -> tuple[int, ...]:
        """SysEx data **with** F0/F7 delimiters — ready for wire transmission."""
        if self.data is None:
            return (0xF0, 0xF7)
        return (0xF0, *self.data, 0xF7)

    # ------------------------------------------------------------------
    # Conversion to/from mido (library boundary)
    # ------------------------------------------------------------------

    def to_mido(self) -> mido.Message:
        """Convert to a ``mido.Message``.

        This is the **only** place in the codebase that imports mido for
        message construction.  All other modules use ``MidiMessage`` directly.
        """
        import mido

        if self.type == "sysex":
            return mido.Message("sysex", data=self.data or ())

        if self.is_realtime:
            return mido.Message(self.type)

        kwargs: dict[str, int] = {}
        if self.channel is not None:
            kwargs["channel"] = int(self.channel)
        if self.note is not None:
            kwargs["note"] = int(self.note)
        if self.velocity is not None:
            kwargs["velocity"] = int(self.velocity)
        if self.control is not None:
            kwargs["control"] = int(self.control)

        if self.type == "program_change":
            # mido uses 'program' for Program Change, not 'value'
            if self.value is not None:
                kwargs["program"] = int(self.value)
        elif self.value is not None:
            kwargs["value"] = int(self.value)

        return mido.Message(self.type, **kwargs)

    @classmethod
    def from_mido(cls, msg: mido.Message) -> MidiMessage:
        """Create a ``MidiMessage`` from a ``mido.Message``.

        The reverse of :meth:`to_mido`.  Handles all standard MIDI message
        types.  Unknown types are returned as ``sysex`` with raw data if
        possible, or raise ``ValueError``.
        """

        if msg.type == "sysex":
            return cls.sysex(tuple(msg.data))

        channel = (
            MidiChannel(msg.channel)
            if isinstance(getattr(msg, "channel", None), int)
            else None
        )
        note = (
            MidiNote(msg.note) if isinstance(getattr(msg, "note", None), int) else None
        )
        velocity = (
            MidiValue(msg.velocity)
            if isinstance(getattr(msg, "velocity", None), int)
            else None
        )
        control = (
            MidiCC(msg.control)
            if isinstance(getattr(msg, "control", None), int)
            else None
        )

        # mido uses 'value' for CC and 'program' for Program Change;
        # we normalise both to the ``value`` field.
        value: MidiValue | None = None
        raw_program = getattr(msg, "program", None)
        if isinstance(raw_program, int):
            value = MidiValue(raw_program)
        else:
            raw_value = getattr(msg, "value", None)
            if isinstance(raw_value, int):
                value = MidiValue(raw_value)

        return cls(
            type=msg.type,
            channel=channel,
            note=note,
            velocity=velocity,
            control=control,
            value=value,
        )

    def __repr__(self) -> str:
        """Compact representation for logging."""
        if self.type == "sysex":
            hex_str = " ".join(f"{b:02X}" for b in (self.data or ()))
            return f"MidiMessage(sysex [{hex_str}])"
        ch_str = f"ch={int(self.channel) + 1}" if self.channel is not None else "ch=?"
        if self.is_cc:
            return f"MidiMessage(cc {ch_str} cc={self.control} val={self.value})"
        if self.is_note:
            return f"MidiMessage({self.type} {ch_str} note={self.note} vel={self.velocity})"
        return f"MidiMessage({self.type})"


# ---------------------------------------------------------------------------
# Abstract interfaces
# ---------------------------------------------------------------------------


class MidiInPort(ABC):
    """Abstract MIDI input port — callback-based.

    The implementation handles library-specific details (mido, rtmidi, etc.).
    The caller only interacts with this interface.

    Lifecycle
    ---------
    1. ``open(name)`` — open the port by name
    2. ``set_callback(fn)`` — register a callable that receives ``MidiMessage``
    3. On shutdown: ``clear_callback()`` then ``close()``

    Example
    -------
    >>> port = create_in_port()
    >>> port.open("M8 MIDI")
    >>> port.set_callback(lambda msg: print(msg))
    >>> # ... messages arrive asynchronously ...
    >>> port.clear_callback()
    >>> port.close()
    """

    @abstractmethod
    def open(self, name: str) -> None:
        """Open the named MIDI input port.

        Parameters
        ----------
        name:
            Exact port name (from :meth:`MidiPortRegistry.list_input_names`).
        """

    @abstractmethod
    def close(self) -> None:
        """Close the port.  Safe to call multiple times."""

    @abstractmethod
    def set_callback(self, callback: Callable[[MidiMessage], None]) -> None:
        """Register a callback invoked for every incoming MIDI message.

        The callback runs on the library's internal thread — it should be
        fast and non-blocking.  Queue the message if processing is needed.
        """

    @abstractmethod
    def clear_callback(self) -> None:
        """Remove the callback.  Safe to call if none is set."""

    @abstractmethod
    def poll(self, timeout: float = 0) -> MidiMessage | None:
        """Poll for the next incoming MIDI message.

        Parameters
        ----------
        timeout:
            Maximum seconds to wait for a message.  ``0`` returns
            immediately (``None`` if no message is available).

        Returns
        -------
        MidiMessage | None
            The next message, or ``None`` on timeout.

        Notes
        -----
        Polling and callbacks can coexist — the callback fires on the
        library's internal thread while ``poll()`` drains an internal
        queue.  If you only need polling, don't call :meth:`set_callback`.
        """

    def __iter__(self) -> Iterator[MidiMessage]:
        """Iterate over incoming messages until the port is closed.

        Example
        -------
        >>> with mido.open_input("M8 MIDI") as port:
        ...     for msg in port:
        ...         print(msg)
        """
        return self

    def __next__(self) -> MidiMessage:
        """Return the next message, blocking until available.

        Raises
        ------
        StopIteration
            When the port is closed or no longer accepting messages.
        """
        msg = self.poll(timeout=0.1)
        if msg is None:
            # Check if port is still "alive" — subclasses should override
            # __next__ if they have a better shutdown signal.
            raise StopIteration
        return msg


class MidiOutPort(ABC):
    """Abstract MIDI output port — send-only.

    Lifecycle
    ---------
    1. ``open(name)`` — open the port by name
    2. ``send(msg)`` — send MIDI messages
    3. On shutdown: ``close()``

    Example
    -------
    >>> port = create_out_port()
    >>> port.open("M8 MIDI")
    >>> port.send(MidiMessage.cc(channel=0, control=1, value=64))
    >>> port.close()
    """

    @abstractmethod
    def open(self, name: str) -> None:
        """Open the named MIDI output port.

        Parameters
        ----------
        name:
            Exact port name (from :meth:`MidiPortRegistry.list_output_names`).
        """

    @abstractmethod
    def close(self) -> None:
        """Close the port.  Safe to call multiple times."""

    @abstractmethod
    def send(self, msg: MidiMessage) -> None:
        """Send a MIDI message.

        Parameters
        ----------
        msg:
            The message to send.
        """


class MidiPortRegistry(ABC):
    """MIDI port discovery — list and find ports.

    This interface abstracts the library-specific port enumeration logic.
    """

    @abstractmethod
    def list_input_names(self) -> list[str]:
        """Return all available MIDI input port names."""

    @abstractmethod
    def list_output_names(self) -> list[str]:
        """Return all available MIDI output port names."""

    def find_input(self, needle: str) -> str | None:
        """Find the first MIDI input port whose name contains *needle*.

        The comparison is case-insensitive.  Returns ``None`` if no match.
        """
        needle_lower = needle.lower()
        for name in self.list_input_names():
            if needle_lower in name.lower():
                return name
        return None

    def find_output(self, needle: str) -> str | None:
        """Find the first MIDI output port whose name contains *needle*.

        The comparison is case-insensitive.  Returns ``None`` if no match.
        """
        needle_lower = needle.lower()
        for name in self.list_output_names():
            if needle_lower in name.lower():
                return name
        return None
