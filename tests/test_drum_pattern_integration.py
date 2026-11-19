"""Интеграция: скрипт/REPL → правка паттерна → undo/recall (блок 7 tasks).

7.1 — дорожка создаётся **в рантайме** (после ``_init_mutation``):
разрыв регистрации закрыт ``create_drum_track`` → ``register_drum_track``.
Не использовать фикстуры с треками до ``_init_mutation`` — это маскирует
разрыв (см. tasks.md 7.1).

7.2 — регресс: drum-дорожка, существовавшая на старте (до
``_init_mutation``), работает как раньше; повтор того же паттерна
не плодит версий.
"""

from __future__ import annotations

from src.app.application import App
from src.app.engine_control import AppEngineControl
from src.session.model.drum_track import DrumTrack
from src.session.mutation.mutation_config import MutationConfig
from src.session.session import Session


def _app() -> App:
    """App с сессией; MutationEngine инициализируется отдельно."""
    app = App(config_path="config.yaml", simulate=True)
    app._session = Session()
    return app


class TestRuntimeCreatedTrack:
    """7.1: create_drum_track в рантайме → set_drum_pattern → undo/recall."""

    def test_full_scenario(self) -> None:
        app = _app()
        app._init_mutation(MutationConfig())
        ctl = AppEngineControl(app)
        engine = app.mutation_engine
        assert engine is not None

        # mutation_history ДО правки отвечает без «not mutable»
        created = ctl.create_drum_track("Drums")
        assert not created.error
        assert "Drums" in engine.registered_tracks
        history_before = ctl.mutation_history("Drums")
        assert not history_before.error
        assert "not mutable" not in history_before.message

        # Правка: бит изменился
        applied = ctl.set_drum_pattern("Drums", "kick", "x..x|x..x|....|....")
        assert not applied.error
        drum = app._session.get_track("Drums")
        assert isinstance(drum, DrumTrack)
        assert drum.lanes[0].pattern == [1, 0, 0, 1, 1, 0, 0, 1] + [0] * 8
        assert drum.mutation_count == 1

        # undo вернул стартовый (пустой) бит
        undone = ctl.undo_mutation("Drums")
        assert not undone.error
        assert drum.lanes[0].pattern == [0] * 16
        assert drum.mutation_count == 0

        # recall вернул правку
        recalled = ctl.recall_version("Drums", 1)
        assert not recalled.error
        assert drum.lanes[0].pattern[0] == 1
        assert drum.mutation_count == 1

        # счётчик согласован с историей
        assert engine.current_version("Drums") == drum.mutation_count == 1

    def test_history_reports_two_versions_after_edit(self) -> None:
        app = _app()
        app._init_mutation(MutationConfig())
        ctl = AppEngineControl(app)
        ctl.create_drum_track("Drums")
        ctl.set_drum_pattern("Drums", "kick", "x..x")
        result = ctl.mutation_history("Drums")
        assert not result.error
        assert "2 versions" in result.message


class TestStartupTrackRegression:
    """7.2: дорожка, существовавшая на старте (до _init_mutation)."""

    def test_set_undo_recall_works(self) -> None:
        app = _app()
        app._session.create_drum_track()
        app._init_mutation(MutationConfig())
        ctl = AppEngineControl(app)
        drum = app._session.get_track("Drum 1")
        assert ctl.set_drum_pattern("Drum 1", "kick", "x..x").error is False
        assert drum.lanes[0].pattern[0] == 1
        assert ctl.undo_mutation("Drum 1").error is False
        assert drum.lanes[0].pattern == [0] * 16
        assert ctl.recall_version("Drum 1", 1).error is False
        assert drum.lanes[0].pattern[0] == 1

    def test_same_pattern_twice_no_duplicate_version(self) -> None:
        app = _app()
        app._session.create_drum_track()
        app._init_mutation(MutationConfig())
        ctl = AppEngineControl(app)
        engine = app.mutation_engine
        assert engine is not None
        first = ctl.set_drum_pattern("Drum 1", "kick", "x..x")
        assert not first.error
        assert engine.history_len("Drum 1") == 2
        again = ctl.set_drum_pattern("Drum 1", "kick", "x..x")
        assert not again.error
        assert "без изменений" in again.message
        assert engine.history_len("Drum 1") == 2

    def test_new_pattern_after_same_creates_version(self) -> None:
        app = _app()
        app._session.create_drum_track()
        app._init_mutation(MutationConfig())
        ctl = AppEngineControl(app)
        engine = app.mutation_engine
        assert engine is not None
        ctl.set_drum_pattern("Drum 1", "kick", "x..x")
        ctl.set_drum_pattern("Drum 1", "kick", "x..x")  # дедупликация
        ctl.set_drum_pattern("Drum 1", "snare", "....x...")
        assert engine.history_len("Drum 1") == 3
