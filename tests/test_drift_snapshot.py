import random

import pytest

from src.session.mutation.floating_euclidean import FloatingEuclidean
from src.session.mutation.note_drift import NoteDrift
from src.session.mutation.param_drift import ParamDrift


def _param_drift() -> ParamDrift:
    pd = ParamDrift()
    pd.add_param("gate", base=0.5, lo=0.1, hi=1.0, step=0.1)
    pd.add_param("density", base=0.5, lo=0.0, hi=1.0, step=0.1)
    return pd


def test_note_drift_restore_returns_state():
    nd = NoteDrift([0, 2, 4], scale_length=7)
    rng = random.Random(1)
    for _ in range(5):
        nd.drift_one(rng)
    state = nd.snapshot()
    expected = nd.current_degrees
    for _ in range(5):
        nd.drift_one(rng)
    nd.restore(state)
    assert nd.current_degrees == expected


def test_note_drift_continues_from_restored_state():
    source = NoteDrift([0, 2, 4], scale_length=7)
    rng = random.Random(7)
    for _ in range(4):
        source.drift_one(rng)
    target = NoteDrift([0, 2, 4], scale_length=7)
    target.restore(source.snapshot())

    rng_a = random.Random(42)
    rng_b = random.Random(42)
    for _ in range(10):
        source.drift_one(rng_a)
        target.drift_one(rng_b)
    assert target.current_degrees == source.current_degrees


def test_note_drift_restore_rejects_wrong_length():
    nd = NoteDrift([0, 2, 4], scale_length=7)
    with pytest.raises(ValueError):
        nd.restore((0, 2))


def test_floating_euclidean_restore_returns_pulses_and_pattern():
    fe = FloatingEuclidean(steps=16, base_pulses=4)
    rng = random.Random(3)
    fe.drift(rng)
    fe.drift(rng)
    state = fe.snapshot()
    pattern = fe.pattern
    fe.drift(rng)
    fe.drift(rng)
    fe.restore(state)
    assert fe.pulses == state
    assert fe.pattern == pattern


def test_floating_euclidean_continues_from_restored_state():
    source = FloatingEuclidean(steps=16, base_pulses=4)
    rng = random.Random(5)
    source.drift(rng)
    target = FloatingEuclidean(steps=16, base_pulses=4)
    target.restore(source.snapshot())

    rng_a = random.Random(11)
    rng_b = random.Random(11)
    for _ in range(10):
        source.drift(rng_a)
        target.drift(rng_b)
    assert target.pulses == source.pulses


def test_param_drift_restore_returns_values():
    pd = _param_drift()
    rng = random.Random(2)
    for _ in range(4):
        pd.drift_one(rng)
    state = pd.snapshot()
    expected = {n: pd.get(n) for n in pd.param_names}
    for _ in range(4):
        pd.drift_one(rng)
    pd.restore(state)
    assert {n: pd.get(n) for n in pd.param_names} == expected


def test_param_drift_continues_from_restored_state():
    source = _param_drift()
    rng = random.Random(9)
    for _ in range(4):
        source.drift_one(rng)
    target = _param_drift()
    target.restore(source.snapshot())

    rng_a = random.Random(13)
    rng_b = random.Random(13)
    for _ in range(10):
        source.drift_one(rng_a)
        target.drift_one(rng_b)
    assert {n: target.get(n) for n in target.param_names} == {
        n: source.get(n) for n in source.param_names
    }


def test_param_drift_restore_rejects_unknown_params():
    pd = _param_drift()
    with pytest.raises(ValueError):
        pd.restore((("gate", 0.5),))
