"""Инварианты ``degrees`` / ``voicing`` / ``inversion`` / ``revision`` (этап A2).

Закрывает Д3, Д4, Д5 из плана degrees_voicing_plan §2.
"""

from __future__ import annotations

import pytest

from src.harmony.harmony import HarmonyError
from src.session.model.melodic_profile import PROFILES
from src.session.model.melodic_track import MAX_DEGREES_LEN, MelodicTrack


def _pad() -> MelodicTrack:
    return MelodicTrack(name="P", profile_name="pad")


# ---------------------------------------------------------------------------
# degrees
# ---------------------------------------------------------------------------


def test_degrees_is_tuple() -> None:
    t = _pad()
    assert isinstance(t.degrees, tuple)
    assert t.degrees == (0, 3, 2, 0)


def test_degrees_cannot_be_mutated_in_place() -> None:
    t = _pad()
    with pytest.raises(AttributeError):
        t.degrees.append(99)  # type: ignore[attr-defined]


def test_degrees_setter_accepts_list_and_stores_tuple() -> None:
    t = _pad()
    t.degrees = [0, 1, 2, 3]
    t.commit_pending_degrees()
    assert t.degrees == (0, 1, 2, 3)


def test_degrees_setter_copies_input() -> None:
    t = _pad()
    src = [0, 1, 2]
    t.degrees = src
    src.append(5)
    t.commit_pending_degrees()
    assert t.degrees == (0, 1, 2)


def test_degrees_ctor_accepts_list() -> None:
    t = MelodicTrack(name="L", profile_name="lead", degrees=[0, 2, 4, 2])
    assert t.degrees == (0, 2, 4, 2)


def test_degrees_empty_raises() -> None:
    with pytest.raises(ValueError, match="длина"):
        _pad().degrees = []


def test_degrees_empty_in_ctor_raises() -> None:
    with pytest.raises(ValueError):
        MelodicTrack(name="P", profile_name="pad", degrees=[])


@pytest.mark.parametrize("bad", [[-1], [99], [14], [0, 3, -2]])
def test_degrees_out_of_range_raises(bad: list[int]) -> None:
    t = _pad()
    with pytest.raises(ValueError, match="вне диапазона"):
        t.degrees = bad
    assert t.degrees == (0, 3, 2, 0)  # состояние не испорчено


def test_degrees_boundaries_accepted() -> None:
    t = _pad()
    t.degrees = [0, 13]
    t.commit_pending_degrees()
    assert t.degrees == (0, 13)


def test_degrees_length_boundaries() -> None:
    t = _pad()
    t.degrees = [0] * MAX_DEGREES_LEN
    t.commit_pending_degrees()
    assert len(t.degrees) == 16
    with pytest.raises(ValueError, match="длина"):
        t.degrees = [0] * (MAX_DEGREES_LEN + 1)
    assert len(t.degrees) == 16


@pytest.mark.parametrize("bad", ["0123", 5, None, [0, 1.5], [0, "1"], [True]])
def test_degrees_wrong_type_raises(bad: object) -> None:
    with pytest.raises(TypeError):
        _pad().degrees = bad  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# voicing
# ---------------------------------------------------------------------------


def test_voicing_unknown_raises_harmony_error() -> None:
    t = _pad()
    with pytest.raises(HarmonyError):
        t.voicing = "nonsense"
    assert t.voicing == "1-3-5"


def test_voicing_empty_rejected_for_chord_profile() -> None:
    with pytest.raises(HarmonyError):
        _pad().voicing = ""


def test_voicing_empty_allowed_for_cc_only() -> None:
    t = MelodicTrack(name="C", profile_name="cc_filter")
    assert t.voicing == ""
    t.voicing = ""  # идемпотентно, не падает


def test_voicing_ctor_unknown_raises() -> None:
    with pytest.raises(HarmonyError):
        MelodicTrack(name="P", profile_name="pad", voicing="nope")


def test_voicing_setter_valid() -> None:
    t = _pad()
    t.voicing = "1-3-5-7"
    assert t.voicing == "1-3-5-7"


@pytest.mark.parametrize("profile_name", sorted(PROFILES))
def test_every_profile_constructs(profile_name: str) -> None:
    t = MelodicTrack(name="X", profile_name=profile_name)
    assert t.inversion == 0


# ---------------------------------------------------------------------------
# inversion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [3, 5, -1])
def test_inversion_out_of_range_raises(bad: int) -> None:
    t = _pad()  # 1-3-5: допустимо 0..2
    with pytest.raises(ValueError, match="вне диапазона"):
        t.inversion = bad
    assert t.inversion == 0


def test_inversion_range_follows_voicing_length() -> None:
    t = _pad()
    t.voicing = "1-3-5-7"
    t.inversion = 3  # 4 ноты -> 0..3
    assert t.inversion == 3
    with pytest.raises(ValueError):
        t.inversion = 4


def test_inversion_single_note_voicing_only_zero() -> None:
    t = MelodicTrack(name="B", profile_name="bass")
    t.inversion = 0
    with pytest.raises(ValueError):
        t.inversion = 1


def test_inversion_wrong_type_raises() -> None:
    with pytest.raises(TypeError):
        _pad().inversion = 1.0  # type: ignore[assignment]


def test_inversion_ctor_validates() -> None:
    with pytest.raises(ValueError):
        MelodicTrack(name="P", profile_name="pad", inversion=5)


def test_voicing_change_resets_incompatible_inversion() -> None:
    t = MelodicTrack(name="P", profile_name="atmos")  # 1-3-5-7
    t.inversion = 3
    t.voicing = "1-5"  # 2 ноты -> инверсия 3 невалидна
    assert t.inversion == 0


def test_voicing_change_keeps_compatible_inversion() -> None:
    t = _pad()
    t.inversion = 1
    t.voicing = "1-3-5-7"
    assert t.inversion == 1


# ---------------------------------------------------------------------------
# revision
# ---------------------------------------------------------------------------


def test_revision_starts_at_zero() -> None:
    assert _pad().revision == 0
    assert MelodicTrack(name="L", profile_name="lead", degrees=[1, 2]).revision == 0


def test_revision_grows_on_each_edit() -> None:
    t = _pad()
    r = t.revision
    t.degrees = [0, 1]
    t.commit_pending_degrees()
    assert t.revision > r
    r = t.revision
    t.voicing = "1-3-5-7"
    assert t.revision > r
    r = t.revision
    t.inversion = 1
    assert t.revision > r


def test_revision_not_changed_by_reads() -> None:
    t = _pad()
    r = t.revision
    _ = (t.degrees, t.voicing, t.inversion, t.pattern_length, t.profile_name)
    assert t.revision == r


def test_revision_not_changed_by_noop_write() -> None:
    t = _pad()
    r = t.revision
    t.degrees = list(t.degrees)
    t.voicing = t.voicing
    t.inversion = t.inversion
    assert t.revision == r


def test_revision_not_changed_by_rejected_write() -> None:
    t = _pad()
    r = t.revision
    with pytest.raises(ValueError):
        t.degrees = []
    assert t.revision == r


def test_set_profile_bumps_revision_and_keeps_degrees() -> None:
    t = MelodicTrack(name="L", profile_name="lead", degrees=[5, 5, 5])
    r = t.revision
    t.set_profile("pad")
    assert t.revision > r
    assert t.degrees == (5, 5, 5)  # решение §8.5: degrees сохраняются
    assert t.voicing == "1-3-5"


def test_set_profile_same_profile_still_bumps_revision() -> None:
    t = _pad()
    r = t.revision
    t.set_profile("pad")
    assert t.revision > r


def test_set_profile_resets_octave_and_gate() -> None:
    t = _pad()
    t.octave = 2
    t.gate = 0.1
    t.set_profile("atmos")
    assert t.octave == PROFILES["atmos"].default_octave
    assert t.gate == PROFILES["atmos"].default_gate


def test_set_profile_to_single_note_voicing_resets_inversion() -> None:
    t = _pad()
    t.inversion = 2
    t.set_profile("bass")
    assert t.voicing == "1"
    assert t.inversion == 0
