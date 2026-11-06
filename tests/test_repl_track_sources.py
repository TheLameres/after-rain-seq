"""REPL: track sources — подписка дорожки на источники гармонии."""

from __future__ import annotations

import pytest

from src.app.application import App
from src.app.engine_control import AppEngineControl
from src.repl.executor import CommandExecutor
from src.session.session import Session


def _repl() -> tuple[CommandExecutor, Session]:
    app = App(config_path="config.yaml", simulate=True)
    app._session = Session()
    return CommandExecutor(AppEngineControl(app)), app._session


def _tracks(session: Session, *profiles: str) -> list[str]:
    return [session.create_melodic_track(p).name for p in profiles]


class TestParsing:
    @pytest.mark.parametrize(
        ("line", "args"),
        [
            ('track sources "Sub 1" "Pad 1"', ("Sub 1", "Pad 1")),
            ('track sources "Sub 1"', ("Sub 1",)),
            ('track sources "Sub 1" "Pad 1" "Stab 1"', ("Sub 1", "Pad 1", "Stab 1")),
        ],
    )
    def test_split_of_quoted_names(self, line: str, args: tuple[str, ...]) -> None:
        from src.repl.parser import CommandParser

        command = CommandParser().parse(line)
        assert command.name == "track sources"
        assert command.args == args
        assert command.error is None

    def test_no_arguments_is_usage_error(self) -> None:
        from src.repl.parser import CommandParser

        command = CommandParser().parse("track sources")
        assert command.error is not None
        assert "1..3" in command.error

    def test_too_many_arguments_is_usage_error(self) -> None:
        from src.repl.parser import CommandParser

        command = CommandParser().parse("track sources A B C D")
        assert command.error is not None

    def test_help_works_inside_quotes(self) -> None:
        from src.repl.parser import CommandParser

        text = CommandParser().help_text("track sources")
        assert "track sources" in text and "источники" in text.lower()


class TestAssign:
    def test_reads_are_like_sources_sets_subscription(self) -> None:
        ex, session = _repl()
        sub, pad = _tracks(session, "sub", "pad")
        res = ex.execute(f'track sources "{sub}" "{pad}"')
        assert res.code == 0, res.output
        assert session.get_track(sub).sources == (pad,)

    def test_clearing_without_sources(self) -> None:
        ex, session = _repl()
        sub, pad = _tracks(session, "sub", "pad")
        ex.execute(f'track sources "{sub}" "{pad}"')
        res = ex.execute(f'track sources "{sub}"')
        assert res.code == 0
        assert session.get_track(sub).sources == ()

    def test_two_sources_accepted(self) -> None:
        ex, session = _repl()
        sub, pad, atmos = _tracks(session, "sub", "pad", "atmos")
        res = ex.execute(f'track sources "{sub}" "{pad}" "{atmos}"')
        assert res.code == 0, res.output
        assert session.get_track(sub).sources == (pad, atmos)

    def test_replacing_sources(self) -> None:
        ex, session = _repl()
        sub, pad, atmos = _tracks(session, "sub", "pad", "atmos")
        ex.execute(f'track sources "{sub}" "{pad}"')
        ex.execute(f'track sources "{sub}" "{atmos}"')
        assert session.get_track(sub).sources == (atmos,)


class TestErrors:
    def test_unknown_track(self) -> None:
        ex, _ = _repl()
        res = ex.execute('track sources "Nope"')
        assert res.code == 1
        assert "not found" in res.output

    def test_unknown_source(self) -> None:
        ex, session = _repl()
        (sub,) = _tracks(session, "sub")
        res = ex.execute(f'track sources "{sub}" "Nope"')
        assert res.code == 1
        assert "not found" in res.output

    def test_self_subscription_is_cycle(self) -> None:
        ex, session = _repl()
        (sub,) = _tracks(session, "sub")
        res = ex.execute(f'track sources "{sub}" "{sub}"')
        assert res.code == 1
        assert "Цикл" in res.output

    def test_indirect_cycle(self) -> None:
        ex, session = _repl()
        sub, pad = _tracks(session, "sub", "pad")
        ex.execute(f'track sources "{sub}" "{pad}"')
        res = ex.execute(f'track sources "{pad}" "{sub}"')
        assert res.code == 1
        assert "Цикл" in res.output

    def test_rejected_cycle_leaves_graph_unchanged(self) -> None:
        """Отклонённый цикл не должен оставить половинчатой подписки."""
        ex, session = _repl()
        sub, pad = _tracks(session, "sub", "pad")
        assert ex.execute(f'track sources "{sub}" "{pad}"').code == 0

        before_pad = session.get_track(pad).sources
        res = ex.execute(f'track sources "{pad}" "{sub}"')
        assert res.code == 1
        assert "Цикл" in res.output
        assert session.get_track(pad).sources == before_pad
        assert session.get_track(sub).sources == (pad,)

    def test_drum_as_dependent_is_error(self) -> None:
        ex, session = _repl()
        _tracks(session, "pad")
        drum = session.create_drum_track().name
        res = ex.execute(f'track sources "{drum}" "Pad 1"')
        assert res.code == 1
        assert "Drum" in res.output


class TestWarnings:
    def test_profile_without_reads_source_warns(self) -> None:
        """lead не читает источники: подписка проходит, но на звук не влияет."""
        ex, session = _repl()
        lead, pad = _tracks(session, "lead", "pad")
        res = ex.execute(f'track sources "{lead}" "{pad}"')
        assert res.code == 0
        assert session.get_track(lead).sources == (pad,)
        assert "не читает источники" in res.output

    def test_source_without_chords_warns(self) -> None:
        ex, session = _repl()
        sub, lead = _tracks(session, "sub", "lead")
        res = ex.execute(f'track sources "{sub}" "{lead}"')
        assert res.code == 0
        assert "не публикует аккорды" in res.output

    def test_clean_subscription_has_no_notes(self) -> None:
        ex, session = _repl()
        sub, pad = _tracks(session, "sub", "pad")
        res = ex.execute(f'track sources "{sub}" "{pad}"')
        assert "note:" not in res.output


class TestPropagation:
    def test_subscribed_track_receives_chords(self) -> None:
        """После подписки наследник получает аккорды источника в outbox."""
        ex, session = _repl()
        sub, pad = _tracks(session, "sub", "pad")
        ex.execute(f'track sources "{sub}" "{pad}"')
        session.propagate_chords()
        assert len(session.get_track(pad).outbox) > 0
        assert len(session.get_track(sub).outbox) == len(session.get_track(pad).outbox)

    def test_without_subscription_outbox_stays_empty(self) -> None:
        _ex, session = _repl()
        (sub,) = _tracks(session, "sub")
        session.propagate_chords()
        assert session.get_track(sub).outbox == []


class TestFacadeReadback:
    def test_track_sources_map(self) -> None:
        _ex, session = _repl()
        sub, pad = _tracks(session, "sub", "pad")
        session.set_sources(sub, pad)
        ctl = AppEngineControl(_app_of(session))
        assert ctl.track_sources()[sub] == (pad,)

    def test_map_from_session_not_snapshot(self) -> None:
        """Снапшот вне запуска пуст: карта должна приходить из сессии."""
        _ex, session = _repl()
        _tracks(session, "pad")
        app = _app_of(session)
        assert app.status_snapshot.tracks == ()
        assert "Pad 1" in AppEngineControl(app).track_sources()


def _app_of(session: Session) -> App:
    app = App(config_path="config.yaml", simulate=True)
    app._session = session
    return app
