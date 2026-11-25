"""Скриптовый фасад цепочки: show_track_chain / track_chain_add / remove (5.1/5.2).

Контракт данных — только поля ``EngineResult.data`` (``data["chain"]``,
``data["stage"]``); тексты сообщений контрактом не являются. Контроль —
AppEngineControl с реальной сессией (белый ящик, App не запускается).
"""

from __future__ import annotations

import pytest

from src.app.application import App
from src.app.engine_control import AppEngineControl
from src.scripting.error import ScriptError
from src.scripting.script_session import ScriptSession
from src.session.session import Session


def _session() -> tuple[ScriptSession, App]:
    """ScriptSession над AppEngineControl с pad- и drum-дорожкой."""
    app = App(config_path="config.yaml", simulate=True)
    app._session = Session()
    app._session.create_melodic_track("pad")
    app._session.create_drum_track()
    return ScriptSession(AppEngineControl(app)), app


class TestShowTrackChain:
    def test_empty_chain_contract(self) -> None:
        session, _app = _session()
        result = session.show_track_chain("Pad 1")
        assert not result.error
        assert result.data["chain"] == []

    def test_after_add_lists_stage_specs(self) -> None:
        session, _app = _session()
        session.track_chain_add("Pad 1", "arpeggiate step=0.25 direction=up")
        result = session.show_track_chain("Pad 1")
        assert result.data["chain"] == ["arpeggiate step=0.25 direction=up"]


class TestTrackChainAdd:
    def test_add_contract(self) -> None:
        session, app = _session()
        result = session.track_chain_add("Pad 1", "arpeggiate step=0.25 direction=up")
        assert not result.error
        assert result.data["stage"] == "arpeggiate step=0.25 direction=up"
        assert result.data["chain"] == ["arpeggiate step=0.25 direction=up"]
        track = app._session.get_track("Pad 1")
        assert len(track.chain) == 1

    def test_unknown_stage_fatal_raises(self) -> None:
        session, _app = _session()
        with pytest.raises(ScriptError, match="Неизвестный этап"):
            session.track_chain_add("Pad 1", "transpose step=1")

    def test_unknown_stage_non_fatal_returns_result(self) -> None:
        session, app = _session()
        result = session.track_chain_add("Pad 1", "transpose step=1", fatal=False)
        assert result.error
        assert len(app._session.get_track("Pad 1").chain) == 0

    def test_bad_param_fatal_raises(self) -> None:
        session, _app = _session()
        with pytest.raises(ScriptError, match="неизвестный параметр"):
            session.track_chain_add("Pad 1", "arpeggiate foo=1")

    def test_malformed_spec_fatal_raises(self) -> None:
        """Лексема без ``=`` — ScriptError до вызова фасада."""
        session, app = _session()
        with pytest.raises(ScriptError, match="без значения"):
            session.track_chain_add("Pad 1", "arpeggiate step")
        assert len(app._session.get_track("Pad 1").chain) == 0

    def test_malformed_spec_non_fatal(self) -> None:
        session, _app = _session()
        result = session.track_chain_add("Pad 1", "arpeggiate step", fatal=False)
        assert result.error


class TestTrackChainRemove:
    def test_remove_contract(self) -> None:
        session, _app = _session()
        session.track_chain_add("Pad 1", "arpeggiate step=0.25")
        result = session.track_chain_remove("Pad 1", 1)
        assert not result.error
        assert result.data["chain"] == []

    def test_remove_out_of_range_fatal(self) -> None:
        session, _app = _session()
        with pytest.raises(ScriptError, match="out of range"):
            session.track_chain_remove("Pad 1", 1)


class TestDrumTrackNotice:
    def test_add_on_drum_fatal_does_not_raise(self) -> None:
        """Drum-дорожка: успех с предупреждением, скрипт продолжается."""
        session, app = _session()
        result = session.track_chain_add("Drum 1", "arpeggiate step=0.25")
        assert result.error is False  # не fail-fast
        assert "цепочка игнорируется" in result.message
        assert result.data["chain"] == []
        drum = app._session.get_track("Drum 1")
        assert len(drum.chain) == 0

    def test_show_on_drum_empty_chain(self) -> None:
        session, _app = _session()
        result = session.show_track_chain("Drum 1")
        assert result.error is False
        assert result.data["chain"] == []
