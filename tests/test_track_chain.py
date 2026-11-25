"""Поле ``chain`` у дорожки: хранение, fail-fast валидация, источник — профиль.

Блок 2 tasks (track-modify-chain): дефолт — пустая (тождественная) цепочка;
сеттер валидирует структуру; профиль даёт цепочку по умолчанию и не меняется
после правок дорожки; ``set_profile`` цепочку не сбрасывает.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.session.model.drum_track import DrumTrack
from src.session.model.melodic_profile import PROFILES, MelodicProfile
from src.session.model.melodic_track import MelodicTrack
from src.session.modify.arpeggiate import ArpeggiateStage
from src.session.modify.chain import Chain, StageContext


class NameOnly:
    """Этап-заглушка: имя есть, ``process`` нет (для проверки сеттера)."""

    name = "name_only"


class ProcessOnly:
    """Этап-заглушка: ``process`` есть, имени (str) нет."""

    def process(self, batch: list[object], ctx: StageContext) -> list[object]:
        return list(batch)


def _pad() -> MelodicTrack:
    return MelodicTrack(name="Pad 1", profile_name="pad")


class TestDefaultChain:
    def test_melodic_track_default_is_empty(self) -> None:
        chain = _pad().chain
        assert isinstance(chain, Chain)
        assert len(chain) == 0

    def test_drum_track_default_is_empty(self) -> None:
        chain = DrumTrack(name="Drum 1").chain
        assert isinstance(chain, Chain)
        assert len(chain) == 0

    def test_every_profile_registry_has_empty_chain(self) -> None:
        """Проверка по реестру (не перечислению имён): новые профили тоже."""
        for name, profile in PROFILES.items():
            assert len(profile.chain) == 0, f"profile {name!r}"


class TestSetterValidation:
    def test_non_chain_is_type_error(self) -> None:
        track = _pad()
        with pytest.raises(TypeError, match="Chain"):
            track.chain = "arpeggiate"  # type: ignore[assignment]

    def test_stage_without_process_is_value_error(self) -> None:
        track = _pad()
        with pytest.raises(ValueError, match="process"):
            track.chain = Chain((NameOnly(),))  # type: ignore[list-item]

    def test_stage_without_name_is_value_error(self) -> None:
        track = _pad()
        with pytest.raises(ValueError, match="имени"):
            track.chain = Chain((ProcessOnly(),))  # type: ignore[list-item]

    def test_rejected_chain_keeps_previous(self) -> None:
        """Невалидное присвоение не оставляет дорожку без цепочки."""
        track = _pad()
        track.chain = Chain((ArpeggiateStage(),))
        with pytest.raises(TypeError):
            track.chain = None  # type: ignore[assignment]
        assert len(track.chain) == 1

    def test_valid_chain_accepted(self) -> None:
        track = _pad()
        chain = Chain((ArpeggiateStage(step=0.5),))
        track.chain = chain
        assert track.chain is chain
        assert len(track.chain) == 1


class TestProfileSource:
    def test_track_copies_profile_chain(self) -> None:
        """Дорожка стартует с цепочкой профиля (ссылка на тот же объект)."""
        track = _pad()
        assert track.chain is track.profile.chain

    def test_track_edit_does_not_change_profile(self) -> None:
        track = _pad()
        track.chain = Chain((ArpeggiateStage(),))
        assert len(track.profile.chain) == 0

    def test_profile_remains_frozen(self) -> None:
        profile = PROFILES["pad"]
        with pytest.raises(FrozenInstanceError):
            profile.chain = Chain((ArpeggiateStage(),))  # type: ignore[misc]

    def test_set_profile_keeps_chain(self) -> None:
        track = _pad()
        track.chain = Chain((ArpeggiateStage(),))
        track.set_profile("stab")
        assert len(track.chain) == 1


class TestDrumStoresChain:
    def test_drum_track_keeps_non_empty_chain(self) -> None:
        """Модель хранит непустую цепочку у drum-дорожки без ошибок."""
        drum = DrumTrack(name="Drum 1")
        drum.chain = Chain((ArpeggiateStage(),))
        assert len(drum.chain) == 1


class TestMelodicProfileField:
    def test_default_factory_is_empty_chain(self) -> None:
        profile = MelodicProfile(
            name="x",
            reads_source=False,
            emits_chords=False,
            default_voicing="1-3-5",
            default_octave=5,
            default_gate=0.5,
        )
        assert isinstance(profile.chain, Chain)
        assert len(profile.chain) == 0
