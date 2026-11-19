"""Ручная мутация в EngineControl: request/undo/recall/history (spec §3, §8).

White-box по образцу test_engine_control_d2.py: App не запускается,
``_session`` заполняется напрямую, MutationEngine инициализируется
``_init_mutation``.
"""

from __future__ import annotations

from src.app.application import App
from src.app.engine_control import AppEngineControl
from src.session.mutation.mutation_config import MutationConfig
from src.session.session import Session


def make_control() -> tuple[AppEngineControl, App]:
    """App с сессией (pad + drum) и инициализированным MutationEngine."""
    app = App(config_path="config.yaml", simulate=True)
    app._session = Session()
    app._session.create_melodic_track("pad")
    app._session.create_drum_track()
    app._init_mutation(MutationConfig())
    return AppEngineControl(app), app


class TestRequestMutation:
    def test_unknown_track_is_error(self) -> None:
        ctl, _app = make_control()
        result = ctl.request_mutation("Nope")
        assert result.error
        assert "not found" in result.message

    def test_cc_only_is_not_mutable(self) -> None:
        ctl, app = make_control()
        cc = app._session.create_melodic_track("cc_filter")
        result = ctl.request_mutation(cc.name)
        assert result.error
        assert "not mutable" in result.message

    def test_evolve_one_sets_pending(self) -> None:
        ctl, app = make_control()
        pad = app._session.get_track("Pad 1")
        result = ctl.request_mutation("Pad 1")
        assert not result.error
        assert "pending" in result.message
        assert pad.pending is True

    def test_evolve_all_sets_pending_on_mutable(self) -> None:
        ctl, app = make_control()
        result = ctl.request_mutation()
        assert not result.error
        assert "2 tracks" in result.message
        assert app._session.get_track("Pad 1").pending is True
        assert app._session.get_track("Drum 1").pending is True

    def test_engine_missing_is_error(self) -> None:
        app = App(config_path="config.yaml", simulate=True)
        app._session = Session()
        app._session.create_melodic_track("pad")
        ctl = AppEngineControl(app)
        result = ctl.request_mutation("Pad 1")
        assert result.error
        assert "mutation engine" in result.message


class TestUndo:
    def test_undo_at_root_is_error(self) -> None:
        ctl, _app = make_control()
        result = ctl.undo_mutation("Pad 1")
        assert result.error
        assert "root" in result.message

    def test_undo_restores_version(self) -> None:
        ctl, app = make_control()
        pad = app._session.get_track("Pad 1")
        ctl.request_mutation("Pad 1")
        engine = app.mutation_engine
        engine.tick(0.0)
        engine.tick(pad.pattern_length)  # граница цикла
        assert pad.mutation_count == 1
        result = ctl.undo_mutation("Pad 1")
        assert not result.error
        assert pad.mutation_count == 0

    def test_undo_unknown_track_is_error(self) -> None:
        ctl, _app = make_control()
        assert ctl.undo_mutation("Nope").error


class TestRecall:
    def test_bad_index_is_error(self) -> None:
        ctl, _app = make_control()
        result = ctl.recall_version("Pad 1", 5)
        assert result.error
        assert "no version 5" in result.message

    def test_recall_to_root(self) -> None:
        ctl, app = make_control()
        pad = app._session.get_track("Pad 1")
        ctl.request_mutation("Pad 1")
        engine = app.mutation_engine
        engine.tick(0.0)
        engine.tick(pad.pattern_length)
        result = ctl.recall_version("Pad 1", 0)
        assert not result.error
        assert pad.mutation_count == 0

    def test_undo_drum_track(self) -> None:
        ctl, app = make_control()
        drum = app._session.get_track("Drum 1")
        ctl.request_mutation("Drum 1")
        engine = app.mutation_engine
        engine.tick(0.0)
        engine.tick(4.0)  # steps=16 → цикл 4 бита
        assert drum.mutation_count == 1
        result = ctl.undo_mutation("Drum 1")
        assert not result.error
        assert drum.mutation_count == 0


class TestHistory:
    def test_history_message(self) -> None:
        ctl, app = make_control()
        pad = app._session.get_track("Pad 1")
        result = ctl.mutation_history("Pad 1")
        assert not result.error
        assert "1 versions" in result.message
        assert "current 0" in result.message
        ctl.request_mutation("Pad 1")
        app.mutation_engine.tick(0.0)
        app.mutation_engine.tick(pad.pattern_length)
        result = ctl.mutation_history("Pad 1")
        assert "2 versions" in result.message
        assert "current 1" in result.message

    def test_history_unknown_track_is_error(self) -> None:
        ctl, _app = make_control()
        assert ctl.mutation_history("Nope").error

    def test_history_cc_only_is_error(self) -> None:
        ctl, app = make_control()
        cc = app._session.create_melodic_track("cc_space")
        assert ctl.mutation_history(cc.name).error
