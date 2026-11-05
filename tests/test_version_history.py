import pytest

from src.session.model.version_history import HISTORY_LIMIT, VersionHistory


def test_starts_at_root():
    h = VersionHistory("root")
    assert len(h) == 1
    assert h.cursor == 0
    assert h.current == "root"


def test_push_appends_and_moves_cursor_to_head():
    h = VersionHistory("v0")
    assert h.push("v1") == 1
    assert h.push("v2") == 2
    assert h.versions() == ["v0", "v1", "v2"]
    assert h.current == "v2"


def test_undo_moves_back_and_refuses_at_root():
    h = VersionHistory("v0")
    h.push("v1")
    assert h.undo() is True
    assert h.current == "v0"
    assert h.undo() is False
    assert h.cursor == 0
    assert h.current == "v0"


def test_undo_does_not_drop_future_versions():
    h = VersionHistory("v0")
    h.push("v1")
    h.push("v2")
    h.undo()
    assert len(h) == 3
    assert h.current == "v1"


def test_push_after_undo_truncates_future():
    h = VersionHistory("v0")
    h.push("v1")
    h.push("v2")
    h.undo()
    h.push("v1b")
    assert h.versions() == ["v0", "v1", "v1b"]
    assert h.cursor == 2
    assert h.current == "v1b"


def test_recall_moves_cursor_without_dropping_versions():
    h = VersionHistory("v0")
    h.push("v1")
    h.push("v2")
    assert h.recall(1) is True
    assert h.current == "v1"
    assert len(h) == 3


def test_recall_out_of_range_fails_and_keeps_cursor():
    h = VersionHistory("v0")
    h.push("v1")
    assert h.recall(5) is False
    assert h.recall(-1) is False
    assert h.cursor == 1


def test_limit_evicts_first_non_root_and_keeps_root():
    h = VersionHistory("root", limit=4)
    for i in range(1, 6):
        h.push(f"v{i}")
    assert len(h) == 4
    assert h.versions() == ["root", "v3", "v4", "v5"]
    assert h.current == "v5"
    assert h.cursor == 3


def test_default_limit_is_256():
    h = VersionHistory("root")
    for i in range(HISTORY_LIMIT + 1):
        h.push(i)
    assert len(h) == HISTORY_LIMIT
    assert h.versions()[0] == "root"
    assert h.versions()[1] == 2


def test_eviction_keeps_cursor_on_current_version():
    h = VersionHistory("root", limit=3)
    h.push("a")
    h.push("b")
    h.undo()
    h.push("c")
    assert h.current == "c"
    assert h.versions() == ["root", "a", "c"]


def test_limit_below_two_rejected():
    with pytest.raises(ValueError):
        VersionHistory("root", limit=1)
