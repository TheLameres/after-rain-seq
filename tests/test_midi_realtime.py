"""Tests for MIDI real-time message support in MidiMessage."""

import pytest
from src.midi.abc import MidiMessage


def test_clock_constructor():
    msg = MidiMessage.clock()
    assert msg.type == "clock"
    assert msg.channel is None
    assert msg.is_realtime


def test_start_constructor():
    msg = MidiMessage.start()
    assert msg.type == "start"
    assert msg.is_realtime


def test_stop_constructor():
    msg = MidiMessage.stop()
    assert msg.type == "stop"
    assert msg.is_realtime


def test_continue_constructor():
    msg = MidiMessage.continue_()
    assert msg.type == "continue"
    assert msg.is_realtime


def test_is_realtime_false_for_non_realtime():
    assert not MidiMessage.note_on(0, 60, 127).is_realtime
    assert not MidiMessage.cc(0, 1, 64).is_realtime
    assert not MidiMessage.sysex((0x00,)).is_realtime


def test_to_mido_clock():
    import mido
    msg = MidiMessage.clock().to_mido()
    assert isinstance(msg, mido.Message)
    assert msg.type == "clock"


def test_to_mido_start():
    import mido
    msg = MidiMessage.start().to_mido()
    assert isinstance(msg, mido.Message)
    assert msg.type == "start"


def test_to_mido_stop():
    import mido
    msg = MidiMessage.stop().to_mido()
    assert isinstance(msg, mido.Message)
    assert msg.type == "stop"


def test_to_mido_continue():
    import mido
    msg = MidiMessage.continue_().to_mido()
    assert isinstance(msg, mido.Message)
    assert msg.type == "continue"


def test_from_mido_clock_roundtrip():
    import mido
    mido_msg = mido.Message("clock")
    msg = MidiMessage.from_mido(mido_msg)
    assert msg.type == "clock"
    assert msg.is_realtime


def test_from_mido_start_roundtrip():
    import mido
    mido_msg = mido.Message("start")
    msg = MidiMessage.from_mido(mido_msg)
    assert msg.type == "start"
    assert msg.is_realtime


def test_from_mido_stop_roundtrip():
    import mido
    mido_msg = mido.Message("stop")
    msg = MidiMessage.from_mido(mido_msg)
    assert msg.type == "stop"
    assert msg.is_realtime


def test_from_mido_continue_roundtrip():
    import mido
    mido_msg = mido.Message("continue")
    msg = MidiMessage.from_mido(mido_msg)
    assert msg.type == "continue"
    assert msg.is_realtime
