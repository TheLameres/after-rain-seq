"""mido-based implementation of the MIDI abstraction interfaces.

This is the **only** module in ``src/midi/`` that imports mido directly.
To switch to a different MIDI library (e.g. rtmidi-python), create a new
``rtmidi_impl.py`` with equivalent classes and update ``factory.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import mido  # Direct mido import — this is the library boundary
import queue

from src.midi.abc import MidiInPort, MidiMessage, MidiOutPort, MidiPortRegistry

if TYPE_CHECKING:
    from collections.abc import Callable


class MidoInPort(MidiInPort):
    """mido-backed MIDI input port.

    Under the hood, mido uses ``python-rtmidi`` which runs its own callback
    thread.  The user's callback (set via :meth:`set_callback`) is invoked
    on that thread — it should be fast and non-blocking.

    This class also supports **polling** via :meth:`poll` and iteration
    (``for msg in port:``) — messages are buffered in an internal queue.
    """

    def __init__(self) -> None:
        self._port: mido.ports.BaseInput | None = None
        self._callback: Callable[[MidiMessage], None] | None = None
        self._queue: queue.Queue = queue.Queue()

    def open(self, name: str) -> None:
        """Open the named MIDI input port."""
        if self._port is not None:
            self.close()
        self._port = mido.open_input(name)
        # Always set up message reception — either with callback + queue,
        # or queue-only for polling/iteration mode
        self._apply_callback()

    def close(self) -> None:
        """Close the port and clear the callback."""
        if self._port is not None:
            self.clear_callback()
            # On macOS CoreMIDI, _port.close() blocks indefinitely when the
            # rtmidi callback thread is still active.  Just drop the reference;
            # the OS cleans up MIDI ports on process exit.
            self._port = None
        # Drain the queue on close
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def set_callback(self, callback: Callable[[MidiMessage], None]) -> None:
        """Register a callback that receives :class:`MidiMessage` instances."""
        self._callback = callback
        if self._port is not None:
            self._apply_callback()

    def clear_callback(self) -> None:
        """Remove the callback."""
        self._callback = None
        if self._port is not None:
            self._port.callback = None

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
        """
        try:
            result = self._queue.get(timeout=timeout or None)
            if isinstance(result, MidiMessage):
                return result
            return None
        except queue.Empty:
            return None

    def __next__(self) -> MidiMessage:
        """Return the next message, blocking until available.

        Raises
        ------
        StopIteration
            When the port is closed.
        """
        if self._port is None:
            raise StopIteration
        msg = self.poll(timeout=0.1)
        if msg is None:
            raise StopIteration
        return msg

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _apply_callback(self) -> None:
        """Wire the user callback through MidiMessage.from_mido."""
        cb = self._callback

        def _wrap(msg: mido.Message) -> None:
            midi_msg = MidiMessage.from_mido(msg)
            # Always push to the queue for polling support
            self._queue.put(midi_msg)
            # Also call the user callback if one is set
            if cb is not None:
                cb(midi_msg)

        if self._port is not None:
            self._port.callback = _wrap


class MidoOutPort(MidiOutPort):
    """mido-backed MIDI output port.

    ``send()`` is synchronous and blocking — it calls ``mido.Port.send()``
    which writes to the OS MIDI subsystem.  For rate-limited sending, use
    a queue + worker thread (as ``M8Connection._send_worker`` does).
    """

    def __init__(self) -> None:
        self._port: mido.ports.BaseOutput | None = None

    def open(self, name: str) -> None:
        """Open the named MIDI output port."""
        if self._port is not None:
            self.close()
        self._port = mido.open_output(name)

    def close(self) -> None:
        """Close the port."""
        if self._port is not None:
            self._port.close()
            self._port = None

    def send(self, msg: MidiMessage) -> None:
        """Send a MIDI message to the port.

        Parameters
        ----------
        msg:
            The message to send.  Converted to ``mido.Message`` internally.
        """
        if self._port is None:
            return  # silently drop if not connected
        self._port.send(msg.to_mido())


class MidoRegistry(MidiPortRegistry):
    """Port discovery via mido."""

    def list_input_names(self) -> list[str]:
        return list(mido.get_input_names())

    def list_output_names(self) -> list[str]:
        return list(mido.get_output_names())
