"""Инварианты voicing на уровне модели: профили, неизвестные имена, cc_only.

Закрывает Д1 (``KeyError`` вместо ``HarmonyError``) и Д2 (падение на cc_only-профиле)
из плана ``degrees_voicing_plan`` §2.
"""

from __future__ import annotations

import pytest

from src.harmony.harmony import HarmonyError
from src.harmony.voicings import Voicing
from src.session.model.chord_math import chord_degrees_for
from src.session.model.melodic_profile import PROFILES
from src.session.model.melodic_track import MelodicTrack


@pytest.mark.parametrize("profile_name", sorted(PROFILES))
def test_every_profile_default_voicing_is_known(profile_name: str) -> None:
    """У каждого профиля дефолтный voicing есть в словаре.

    ``cc_only`` — исключение по устройству: аккордов нет, значение ``""``.
    """
    profile = PROFILES[profile_name]
    if profile.cc_only:
        assert profile.default_voicing == ""
        with pytest.raises(HarmonyError):
            Voicing.offsets(profile.default_voicing)
    else:
        assert profile.default_voicing in Voicing.VOICINGS, profile.default_voicing


@pytest.mark.parametrize("profile_name", sorted(PROFILES))
def test_track_constructed_from_profile_has_valid_voicing(profile_name: str) -> None:
    """Дорожка, созданная по дефолтам профиля, не падает на chord_degrees_for.

    Для cc_only падение ожидаемо — но ``HarmonyError``, не ``KeyError``.
    """
    track = MelodicTrack(name="T", profile_name=profile_name)
    if PROFILES[profile_name].cc_only:
        with pytest.raises(HarmonyError):
            chord_degrees_for(track, 0)
    else:
        assert chord_degrees_for(track, 0)


def test_unknown_voicing_raises_harmony_error_not_key_error() -> None:
    """Д1: неизвестный voicing — ``HarmonyError``, как и в ``voicing_degrees``."""
    track = MelodicTrack(name="X", profile_name="pad")
    track.voicing = "nonsense"
    with pytest.raises(HarmonyError):
        chord_degrees_for(track, 0)


def test_cc_only_profile_raises_harmony_error() -> None:
    """Д2: cc_only-профиль падает предсказуемо, а не ``KeyError: ''``."""
    track = MelodicTrack(name="C", profile_name="cc_filter")
    with pytest.raises(HarmonyError):
        chord_degrees_for(track, 0)


def test_single_note_voicing_gives_one_degree() -> None:
    """``"1"`` — одна ступень: аккорд из одной ноты."""
    track = MelodicTrack(name="B", profile_name="bass")
    assert chord_degrees_for(track, 3) == (3,)


def test_chord_math_matches_voicing_degrees() -> None:
    """Оба пути дают одинаковые ступени — одна точка правды."""
    track = MelodicTrack(name="P", profile_name="pad")
    from src.harmony.harmony import Harmony

    h = Harmony()
    for voicing in Voicing.VOICINGS:
        track.voicing = voicing
        assert chord_degrees_for(track, 2) == Voicing.voicing_degrees(h, 2, voicing)
