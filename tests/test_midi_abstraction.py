"""Tests for the MIDI abstraction layer.

All tests run without hardware — no MIDI ports are opened.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.midi.abc import MidiCC, MidiChannel, MidiMessage, MidiNote, MidiValue

# ---------------------------------------------------------------------------
# Semantic int wrappers
# ---------------------------------------------------------------------------


class TestMidiChannel:
    def test_valid_values(self) -> None:
        assert MidiChannel(0) == 0
        assert MidiChannel(15) == 15
        assert isinstance(MidiChannel(0), int)

    def test_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="0-15"):
            MidiChannel(-1)
        with pytest.raises(ValueError, match="0-15"):
            MidiChannel(16)


class TestMidiCC:
    def test_valid_values(self) -> None:
        assert MidiCC(0) == 0
        assert MidiCC(127) == 127

    def test_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="0-127"):
            MidiCC(-1)
        with pytest.raises(ValueError, match="0-127"):
            MidiCC(128)


class TestMidiValue:
    def test_valid_values(self) -> None:
        assert MidiValue(0) == 0
        assert MidiValue(127) == 127

    def test_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="0-127"):
            MidiValue(-1)
        with pytest.raises(ValueError, match="0-127"):
            MidiValue(128)


class TestMidiNote:
    def test_valid_values(self) -> None:
        assert MidiNote(0) == 0
        assert MidiNote(127) == 127

    def test_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="0-127"):
            MidiNote(-1)
        with pytest.raises(ValueError, match="0-127"):
            MidiNote(128)


# ---------------------------------------------------------------------------
# MidiMessage — construction
# ---------------------------------------------------------------------------


class TestMidiMessageConstruction:
    def test_note_on(self) -> None:
        msg = MidiMessage.note_on(channel=0, note=36, velocity=127)
        assert msg.type == "note_on"
        assert msg.channel == 0
        assert msg.note == 36
        assert msg.velocity == 127
        assert msg.control is None
        assert msg.value is None
        assert msg.data is None

    def test_note_off(self) -> None:
        msg = MidiMessage.note_off(channel=1, note=60)
        assert msg.type == "note_off"
        assert msg.channel == 1
        assert msg.note == 60
        assert msg.velocity == 0

    def test_cc(self) -> None:
        msg = MidiMessage.cc(channel=0, control=1, value=64)
        assert msg.type == "control_change"
        assert msg.channel == 0
        assert msg.control == 1
        assert msg.value == 64

    def test_sysex_tuple(self) -> None:
        msg = MidiMessage.sysex((0x00, 0x20, 0x29))
        assert msg.type == "sysex"
        assert msg.data == (0x00, 0x20, 0x29)

    def test_sysex_bytes(self) -> None:
        msg = MidiMessage.sysex(b"\x00\x20\x29")
        assert msg.data == (0x00, 0x20, 0x29)

    def test_sysex_list(self) -> None:
        msg = MidiMessage.sysex([0x00, 0x20, 0x29])
        assert msg.data == (0x00, 0x20, 0x29)

    def test_program_change(self) -> None:
        msg = MidiMessage.program_change(channel=0, program=42)
        assert msg.type == "program_change"
        assert msg.channel == 0
        assert msg.value == 42

    def test_invalid_channel_raises(self) -> None:
        with pytest.raises(ValueError, match="MidiChannel must be"):
            MidiMessage.note_on(channel=16, note=60, velocity=100)

    def test_invalid_cc_raises(self) -> None:
        with pytest.raises(ValueError, match="MidiCC must be"):
            MidiMessage.cc(channel=0, control=200, value=64)

    def test_invalid_value_raises(self) -> None:
        with pytest.raises(ValueError, match="MidiValue must be"):
            MidiMessage.cc(channel=0, control=1, value=200)


# ---------------------------------------------------------------------------
# MidiMessage — convenience properties
# ---------------------------------------------------------------------------


class TestMidiMessageProperties:
    def test_is_note(self) -> None:
        assert MidiMessage.note_on(0, 60, 100).is_note
        assert MidiMessage.note_off(0, 60).is_note
        assert not MidiMessage.cc(0, 1, 64).is_note

    def test_is_cc(self) -> None:
        assert MidiMessage.cc(0, 1, 64).is_cc
        assert not MidiMessage.note_on(0, 60, 100).is_cc

    def test_is_sysex(self) -> None:
        assert MidiMessage.sysex((0x00,)).is_sysex
        assert not MidiMessage.cc(0, 1, 64).is_sysex

    def test_is_note_on(self) -> None:
        assert MidiMessage.note_on(0, 60, 100).is_note_on
        assert not MidiMessage.note_off(0, 60).is_note_on
        assert not MidiMessage.note_on(0, 60, 0).is_note_on

    def test_sysex_with_framing(self) -> None:
        msg = MidiMessage.sysex((0x00, 0x20, 0x29))
        assert msg.sysex_with_framing == (0xF0, 0x00, 0x20, 0x29, 0xF7)

    def test_sysex_with_framing_empty(self) -> None:
        msg = MidiMessage.sysex(())
        assert msg.sysex_with_framing == (0xF0, 0xF7)


# ---------------------------------------------------------------------------
# MidiMessage — immutability
# ---------------------------------------------------------------------------


class TestMidiMessageImmutability:
    def test_frozen(self) -> None:
        msg = MidiMessage.cc(channel=0, control=1, value=64)
        with pytest.raises(AttributeError, match="cannot assign to field"):
            msg.control = 2  # type: ignore[misc]

    def test_hashable(self) -> None:
        msg1 = MidiMessage.cc(channel=0, control=1, value=64)
        msg2 = MidiMessage.cc(channel=0, control=1, value=64)
        assert hash(msg1) == hash(msg2)
        # Can be used as dict key
        d: dict[MidiMessage, str] = {msg1: "ok"}
        assert d[msg2] == "ok"


# ---------------------------------------------------------------------------
# MidiMessage — mido conversion
# ---------------------------------------------------------------------------


class TestMidiMessageMidoConversion:
    def test_note_on_roundtrip(self) -> None:
        original = MidiMessage.note_on(channel=0, note=36, velocity=127)
        mido_msg = original.to_mido()
        restored = MidiMessage.from_mido(mido_msg)
        assert restored.type == original.type
        assert restored.channel == original.channel
        assert restored.note == original.note
        assert restored.velocity == original.velocity

    def test_cc_roundtrip(self) -> None:
        original = MidiMessage.cc(channel=9, control=7, value=100)
        mido_msg = original.to_mido()
        restored = MidiMessage.from_mido(mido_msg)
        assert restored.type == original.type
        assert restored.channel == original.channel
        assert restored.control == original.control
        assert restored.value == original.value

    def test_sysex_roundtrip(self) -> None:
        # mido sysex data must be 0-127; F0/F7 framing is added by mido automatically
        data = (0x00, 0x7E, 0x7F, 0x06, 0x01)
        original = MidiMessage.sysex(data)
        mido_msg = original.to_mido()
        restored = MidiMessage.from_mido(mido_msg)
        assert restored.data == data

    def test_program_change_roundtrip(self) -> None:
        original = MidiMessage.program_change(channel=0, program=42)
        mido_msg = original.to_mido()
        restored = MidiMessage.from_mido(mido_msg)
        assert restored.type == original.type
        assert restored.channel == original.channel
        assert restored.value == original.value


# ---------------------------------------------------------------------------
# MidiMessage — repr
# ---------------------------------------------------------------------------


class TestMidiMessageRepr:
    def test_cc_repr(self) -> None:
        msg = MidiMessage.cc(channel=0, control=1, value=64)
        r = repr(msg)
        assert "cc" in r
        assert "ch=1" in r
        assert "cc=1" in r

    def test_note_on_repr(self) -> None:
        msg = MidiMessage.note_on(channel=0, note=36, velocity=127)
        r = repr(msg)
        assert "note_on" in r
        assert "note=36" in r

    def test_sysex_repr(self) -> None:
        msg = MidiMessage.sysex((0x00, 0x20, 0x29))
        r = repr(msg)
        assert "sysex" in r
        assert "00" in r


# ---------------------------------------------------------------------------
# MidoInPort / MidoOutPort — mock tests
# ---------------------------------------------------------------------------


class TestMidoInPort:
    @patch("src.midi.mido_impl.mido")
    def test_open_and_close(self, mock_mido: MagicMock) -> None:
        from src.midi.mido_impl import MidoInPort

        mock_port = MagicMock()
        mock_mido.open_input.return_value = mock_port

        port = MidoInPort()
        port.open("Test Port")
        mock_mido.open_input.assert_called_once_with("Test Port")

        port.close()
        # On macOS CoreMIDI, _port.close() blocks indefinitely, so we only
        # clear the callback and drop the reference — not call close().
        mock_port.close.assert_not_called()
        assert port._port is None

    @patch("src.midi.mido_impl.mido")
    def test_callback_receives_midi_message(self, mock_mido: MagicMock) -> None:
        from src.midi.mido_impl import MidoInPort

        mock_port = MagicMock()
        mock_mido.open_input.return_value = mock_port

        port = MidoInPort()
        port.open("Test Port")

        received: list[MidiMessage] = []
        port.set_callback(received.append)

        # Simulate mido calling the registered callback
        callback_fn = mock_port.callback
        assert callback_fn is not None

        mock_mido_msg = MagicMock()
        mock_mido_msg.type = "control_change"
        mock_mido_msg.channel = 0
        mock_mido_msg.control = 7
        mock_mido_msg.velocity = None
        mock_mido_msg.value = 64
        mock_mido_msg.note = None
        mock_mido_msg.data = ()

        callback_fn(mock_mido_msg)

        assert len(received) == 1
        msg = received[0]
        assert msg.type == "control_change"
        assert msg.control == 7
        assert msg.value == 64

    @patch("src.midi.mido_impl.mido")
    def test_clear_callback(self, mock_mido: MagicMock) -> None:
        from src.midi.mido_impl import MidoInPort

        mock_port = MagicMock()
        mock_mido.open_input.return_value = mock_port

        port = MidoInPort()
        port.open("Test Port")
        port.set_callback(lambda msg: None)
        port.clear_callback()

        mock_port.callback = None  # mido callback should be cleared

    @patch("src.midi.mido_impl.mido")
    def test_poll_returns_message(self, mock_mido: MagicMock) -> None:
        from src.midi.mido_impl import MidoInPort

        mock_port = MagicMock()
        mock_mido.open_input.return_value = mock_port

        port = MidoInPort()
        port.open("Test Port")

        # Simulate incoming message
        callback_fn = mock_port.callback
        assert callback_fn is not None

        mock_mido_msg = MagicMock()
        mock_mido_msg.type = "note_on"
        mock_mido_msg.channel = 0
        mock_mido_msg.note = 60
        mock_mido_msg.velocity = 100
        mock_mido_msg.control = None
        mock_mido_msg.value = None
        mock_mido_msg.data = ()

        callback_fn(mock_mido_msg)

        msg = port.poll(timeout=0)
        assert msg is not None
        assert msg.type == "note_on"
        assert msg.note == 60
        assert msg.velocity == 100

    @patch("src.midi.mido_impl.mido")
    def test_poll_returns_none_on_timeout(self, mock_mido: MagicMock) -> None:
        from src.midi.mido_impl import MidoInPort

        mock_port = MagicMock()
        mock_mido.open_input.return_value = mock_port

        port = MidoInPort()
        port.open("Test Port")

        msg = port.poll(timeout=0.01)
        assert msg is None

    @patch("src.midi.mido_impl.mido")
    def test_iteration_multiple_messages(self, mock_mido: MagicMock) -> None:
        from src.midi.mido_impl import MidoInPort

        mock_port = MagicMock()
        mock_mido.open_input.return_value = mock_port

        port = MidoInPort()
        port.open("Test Port")

        callback_fn = mock_port.callback
        assert callback_fn is not None

        # Simulate 3 incoming messages
        for note in [60, 62, 64]:
            mock_mido_msg = MagicMock()
            mock_mido_msg.type = "note_on"
            mock_mido_msg.channel = 0
            mock_mido_msg.note = note
            mock_mido_msg.velocity = 100
            mock_mido_msg.control = None
            mock_mido_msg.value = None
            mock_mido_msg.data = ()
            callback_fn(mock_mido_msg)

        # Collect via iteration
        collected = []
        for _ in range(3):
            msg = next(port)
            collected.append(msg)

        assert len(collected) == 3
        assert [int(m.note) for m in collected] == [60, 62, 64]

    @patch("src.midi.mido_impl.mido")
    def test_iteration_stops_when_closed(self, mock_mido: MagicMock) -> None:
        from src.midi.mido_impl import MidoInPort

        mock_port = MagicMock()
        mock_mido.open_input.return_value = mock_port

        port = MidoInPort()
        port.open("Test Port")
        port.close()

        # Should raise StopIteration immediately
        with pytest.raises(StopIteration):
            next(port)

    @patch("src.midi.mido_impl.mido")
    def test_poll_works_without_callback(self, mock_mido: MagicMock) -> None:
        """Messages should be queued even when no user callback is set."""
        from src.midi.mido_impl import MidoInPort

        mock_port = MagicMock()
        mock_mido.open_input.return_value = mock_port

        port = MidoInPort()
        port.open("Test Port")
        # No set_callback() called

        # Simulate mido callback
        callback_fn = mock_port.callback
        assert callback_fn is not None

        mock_mido_msg = MagicMock()
        mock_mido_msg.type = "control_change"
        mock_mido_msg.channel = 0
        mock_mido_msg.control = 1
        mock_mido_msg.value = 64
        mock_mido_msg.velocity = None
        mock_mido_msg.note = None
        mock_mido_msg.data = ()

        callback_fn(mock_mido_msg)

        msg = port.poll(timeout=0)
        assert msg is not None
        assert msg.type == "control_change"
        assert msg.control == 1

    @patch("src.midi.mido_impl.mido")
    def test_callback_and_poll_both_fire(self, mock_mido: MagicMock) -> None:
        """Both callback and polling should receive the same message."""
        from src.midi.mido_impl import MidoInPort

        mock_port = MagicMock()
        mock_mido.open_input.return_value = mock_port

        port = MidoInPort()
        port.open("Test Port")

        received: list[MidiMessage] = []
        port.set_callback(received.append)

        callback_fn = mock_port.callback
        assert callback_fn is not None

        mock_mido_msg = MagicMock()
        mock_mido_msg.type = "note_on"
        mock_mido_msg.channel = 0
        mock_mido_msg.note = 36
        mock_mido_msg.velocity = 127
        mock_mido_msg.control = None
        mock_mido_msg.value = None
        mock_mido_msg.data = ()

        callback_fn(mock_mido_msg)

        # Callback should have fired
        assert len(received) == 1
        assert received[0].note == 36

        # Poll should also return the message
        msg = port.poll(timeout=0)
        assert msg is not None
        assert msg.note == 36


class TestMidoOutPort:
    @patch("src.midi.mido_impl.mido")
    def test_open_and_close(self, mock_mido: MagicMock) -> None:
        from src.midi.mido_impl import MidoOutPort

        mock_port = MagicMock()
        mock_mido.open_output.return_value = mock_port

        port = MidoOutPort()
        port.open("Test Out")
        mock_mido.open_output.assert_called_once_with("Test Out")

        port.close()
        mock_port.close.assert_called_once()

    @patch("src.midi.mido_impl.mido")
    def test_send_cc(self, mock_mido: MagicMock) -> None:
        from src.midi.mido_impl import MidoOutPort

        mock_port = MagicMock()
        mock_mido.open_output.return_value = mock_port

        port = MidoOutPort()
        port.open("Test Out")
        port.send(MidiMessage.cc(channel=0, control=1, value=64))

        mock_port.send.assert_called_once()
        sent_msg = mock_port.send.call_args[0][0]
        assert sent_msg.type == "control_change"
        assert sent_msg.control == 1
        assert sent_msg.value == 64

    @patch("src.midi.mido_impl.mido")
    def test_send_sysex(self, mock_mido: MagicMock) -> None:
        from src.midi.mido_impl import MidoOutPort

        mock_port = MagicMock()
        mock_mido.open_output.return_value = mock_port

        port = MidoOutPort()
        port.open("Test Out")
        port.send(MidiMessage.sysex((0x00, 0x20, 0x29)))

        mock_port.send.assert_called_once()
        sent_msg = mock_port.send.call_args[0][0]
        assert sent_msg.type == "sysex"

    @patch("src.midi.mido_impl.mido")
    def test_send_when_not_open_drops_silently(self, mock_mido: MagicMock) -> None:
        from src.midi.mido_impl import MidoOutPort

        port = MidoOutPort()
        port.send(MidiMessage.cc(channel=0, control=1, value=64))
        # Should not raise — silently drops


class TestMidoRegistry:
    @patch("src.midi.mido_impl.mido")
    def test_list_input_names(self, mock_mido: MagicMock) -> None:
        from src.midi.mido_impl import MidoRegistry

        mock_mido.get_input_names.return_value = ["M8", "Push 2", "LCXL3"]
        registry = MidoRegistry()
        assert registry.list_input_names() == ["M8", "Push 2", "LCXL3"]

    @patch("src.midi.mido_impl.mido")
    def test_list_output_names(self, mock_mido: MagicMock) -> None:
        from src.midi.mido_impl import MidoRegistry

        mock_mido.get_output_names.return_value = ["M8 Out", "Push 2 Out"]
        registry = MidoRegistry()
        assert registry.list_output_names() == ["M8 Out", "Push 2 Out"]

    @patch("src.midi.mido_impl.mido")
    def test_find_input_case_insensitive(self, mock_mido: MagicMock) -> None:
        from src.midi.mido_impl import MidoRegistry

        mock_mido.get_input_names.return_value = ["M8 MIDI Port", "Other"]
        registry = MidoRegistry()
        assert registry.find_input("m8") == "M8 MIDI Port"
        assert registry.find_input("M8") == "M8 MIDI Port"

    @patch("src.midi.mido_impl.mido")
    def test_find_input_no_match(self, mock_mido: MagicMock) -> None:
        from src.midi.mido_impl import MidoRegistry

        mock_mido.get_input_names.return_value = ["Push 2", "LCXL3"]
        registry = MidoRegistry()
        assert registry.find_input("M8") is None

    @patch("src.midi.mido_impl.mido")
    def test_find_output(self, mock_mido: MagicMock) -> None:
        from src.midi.mido_impl import MidoRegistry

        mock_mido.get_output_names.return_value = ["M8 Out", "Push 2 Out"]
        registry = MidoRegistry()
        assert registry.find_output("push") == "Push 2 Out"
        assert registry.find_output("nonexistent") is None


# ---------------------------------------------------------------------------
# Factory — smoke test
# ---------------------------------------------------------------------------


class TestFactory:
    @patch("src.midi.mido_impl.mido")
    def test_create_in_port(self, mock_mido: MagicMock) -> None:
        from src.midi import create_in_port
        from src.midi.abc import MidiInPort

        port = create_in_port()
        assert isinstance(port, MidiInPort)

    @patch("src.midi.mido_impl.mido")
    def test_create_out_port(self, mock_mido: MagicMock) -> None:
        from src.midi import create_out_port
        from src.midi.abc import MidiOutPort

        port = create_out_port()
        assert isinstance(port, MidiOutPort)

    @patch("src.midi.mido_impl.mido")
    def test_create_registry(self, mock_mido: MagicMock) -> None:
        from src.midi import create_registry
        from src.midi.abc import MidiPortRegistry

        registry = create_registry()
        assert isinstance(registry, MidiPortRegistry)
