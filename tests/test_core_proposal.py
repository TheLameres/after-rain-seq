"""Tests for TrackProposal/DrumProposal — frozen DTO, структурные проверки."""

from __future__ import annotations

import dataclasses

import pytest

from src.core.proposal import DrumProposal, TrackProposal


class TestTrackProposal:
    """Структурные проверки melodic-proposal (семантика — не здесь)."""

    def test_valid_canonical_case(self) -> None:
        """Канонический пример proposal_script.py: поля как заданы."""
        proposal = TrackProposal(
            name="Track 1",
            profile_name="atmos",
            voicing="1-3-5-7",
            degrees=[6, 5, 4],
        )
        assert proposal.name == "Track 1"
        assert proposal.profile_name == "atmos"
        assert proposal.voicing == "1-3-5-7"
        assert proposal.degrees == (6, 5, 4)
        assert proposal.channel is None

    def test_degrees_list_normalized_to_tuple(self) -> None:
        """``degrees=[1, 2, 3]`` (список) хранится как кортеж."""
        proposal = TrackProposal(profile_name="pad", degrees=[1, 2, 3])
        assert proposal.degrees == (1, 2, 3)
        assert isinstance(proposal.degrees, tuple)

    def test_degrees_none_and_voicing_none_ok(self) -> None:
        """``degrees=None``/``voicing=None`` — дефолты профиля, валидно."""
        proposal = TrackProposal(profile_name="pad")
        assert proposal.degrees is None
        assert proposal.voicing is None
        assert proposal.name is None

    def test_empty_profile_name_rejected(self) -> None:
        """Пустое имя профиля — структурная ошибка."""
        with pytest.raises(ValueError, match="profile_name"):
            TrackProposal(profile_name="")

    def test_whitespace_profile_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="profile_name"):
            TrackProposal(profile_name="   ")

    def test_non_string_profile_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="profile_name"):
            TrackProposal(profile_name=123)  # type: ignore[arg-type]

    def test_empty_name_rejected(self) -> None:
        """Заданное имя пустое — ошибка; ``None`` — валидно."""
        with pytest.raises(ValueError, match="name"):
            TrackProposal(profile_name="pad", name="")
        with pytest.raises(ValueError, match="name"):
            TrackProposal(profile_name="pad", name="   ")
        assert TrackProposal(profile_name="pad", name=None).name is None

    def test_channel_out_of_range_rejected(self) -> None:
        """Канал вне 0..15 — ошибка."""
        with pytest.raises(ValueError, match="channel"):
            TrackProposal(profile_name="pad", channel=16)
        with pytest.raises(ValueError, match="channel"):
            TrackProposal(profile_name="pad", channel=-1)
        with pytest.raises(ValueError, match="channel"):
            TrackProposal(profile_name="pad", channel=3.5)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="channel"):
            TrackProposal(profile_name="pad", channel=True)  # type: ignore[arg-type]

    def test_channel_boundaries_ok(self) -> None:
        assert TrackProposal(profile_name="pad", channel=0).channel == 0
        assert TrackProposal(profile_name="pad", channel=15).channel == 15

    def test_degrees_out_of_range_rejected(self) -> None:
        """Ступени вне 0..13 — ошибка (конвенция движка, 0-based)."""
        with pytest.raises(ValueError, match="degrees"):
            TrackProposal(profile_name="pad", degrees=[14])
        with pytest.raises(ValueError, match="degrees"):
            TrackProposal(profile_name="pad", degrees=[-1])
        with pytest.raises(ValueError, match="degrees"):
            TrackProposal(profile_name="pad", degrees=[3, 20])

    def test_degrees_boundaries_ok(self) -> None:
        """Границы 0..13 валидны; ``[0]`` — тоника."""
        assert TrackProposal(profile_name="pad", degrees=(0,)).degrees == (0,)
        assert TrackProposal(profile_name="pad", degrees=(13,)).degrees == (13,)

    def test_empty_degrees_rejected(self) -> None:
        with pytest.raises(ValueError, match="degrees"):
            TrackProposal(profile_name="pad", degrees=[])

    def test_non_int_degrees_rejected(self) -> None:
        """``degrees`` из строк/bool — ошибка (структурная проверка)."""
        with pytest.raises(ValueError, match="degrees"):
            TrackProposal(profile_name="pad", degrees="753")  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="degrees"):
            TrackProposal(profile_name="pad", degrees=[True])  # type: ignore[list-item]

    def test_non_iterable_degrees_rejected(self) -> None:
        with pytest.raises(ValueError, match="degrees"):
            TrackProposal(profile_name="pad", degrees=5)  # type: ignore[arg-type]

    def test_non_string_voicing_rejected(self) -> None:
        with pytest.raises(ValueError, match="voicing"):
            TrackProposal(profile_name="pad", voicing=135)  # type: ignore[arg-type]

    def test_frozen_immutable(self) -> None:
        """Frozen dataclass запрещает присваивание полей."""
        proposal = TrackProposal(profile_name="pad", name="Pad 1")
        with pytest.raises(dataclasses.FrozenInstanceError):
            proposal.name = "Pad 2"  # type: ignore[misc]


class TestDrumProposal:
    """Drum-proposal: только имя, структурная проверка."""

    def test_named(self) -> None:
        proposal = DrumProposal(name="Kick")
        assert proposal.name == "Kick"

    def test_nameless_ok(self) -> None:
        assert DrumProposal().name is None

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="name"):
            DrumProposal(name="")
        with pytest.raises(ValueError, match="name"):
            DrumProposal(name="  ")

    def test_non_string_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="name"):
            DrumProposal(name=1)  # type: ignore[arg-type]

    def test_frozen_immutable(self) -> None:
        proposal = DrumProposal(name="Kick")
        with pytest.raises(dataclasses.FrozenInstanceError):
            proposal.name = "Snare"  # type: ignore[misc]
