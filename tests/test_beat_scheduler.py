"""Тесты для BeatScheduler — lookahead-планировщик по битам."""

from __future__ import annotations

import pytest

from src.session.engine.beat_scheduler import BeatScheduler
from src.sync.transport_event import TransportEvent


def _note_on(beat: float, note: int = 60) -> TransportEvent:
    """note_on на абсолютном beat."""
    return TransportEvent.note_on(
        port_label="default", channel=0, note=note, velocity=100, beat=beat
    )


class TestInit:
    """Инициализация и валидация."""

    def test_defaults(self) -> None:
        """Дефолты: horizon=4, не инициализирован, пусто."""
        s = BeatScheduler()
        assert s.horizon == 4.0
        assert not s.initialized
        assert s.watermark == 0.0
        assert s.pending_count == 0

    def test_custom_horizon(self) -> None:
        """Кастомный горизонт."""
        s = BeatScheduler(horizon=2.0)
        assert s.horizon == 2.0

    def test_invalid_horizon(self) -> None:
        """horizon <= 0 — ValueError."""
        with pytest.raises(ValueError, match="horizon"):
            BeatScheduler(horizon=0.0)
        with pytest.raises(ValueError, match="horizon"):
            BeatScheduler(horizon=-1.0)

    def test_invalid_epsilon(self) -> None:
        """epsilon < 0 — ValueError."""
        with pytest.raises(ValueError, match="epsilon"):
            BeatScheduler(epsilon=-0.1)


class TestEnsure:
    """Ленивая инициализация водяного знака."""

    def test_ensure_sets_watermark(self) -> None:
        """ensure() ставит watermark = now."""
        s = BeatScheduler()
        s.ensure(3.5)
        assert s.initialized
        assert s.watermark == 3.5

    def test_ensure_idempotent(self) -> None:
        """Повторный ensure() не двигает знак."""
        s = BeatScheduler()
        s.ensure(3.5)
        s.ensure(10.0)
        assert s.watermark == 3.5


class TestAdvance:
    """Подъём водяного знака."""

    def test_advance_forward(self) -> None:
        """advance() двигает знак вперёд."""
        s = BeatScheduler()
        s.ensure(0.0)
        s.advance(4.0)
        assert s.watermark == 4.0

    def test_advance_backward_ignored(self) -> None:
        """advance() назад игнорируется."""
        s = BeatScheduler()
        s.ensure(4.0)
        s.advance(2.0)
        assert s.watermark == 4.0


class TestSchedule:
    """Размещение событий."""

    def test_schedule_keeps_sorted(self) -> None:
        """События хранятся по возрастанию beat."""
        s = BeatScheduler()
        s.schedule(_note_on(2.0, note=62))
        s.schedule(_note_on(0.0, note=60))
        s.schedule(_note_on(1.0, note=61))
        assert s.pending_count == 3
        # due() вызывается на каждом тике — выборка по мере наступления beat
        got = s.due(0.0) + s.due(1.0) + s.due(2.0)
        assert [ev.note for ev in got] == [60, 61, 62]

    def test_schedule_same_beat_order_stable(self) -> None:
        """События с одинаковым beat выдаются в порядке вставки."""
        s = BeatScheduler()
        s.schedule(_note_on(1.0, note=60))
        s.schedule(_note_on(1.0, note=61))
        assert s.due(0.9) == []
        got = s.due(1.0)
        assert [ev.note for ev in got] == [60, 61]


class TestDue:
    """Выборка событий к доставке."""

    def test_due_empty(self) -> None:
        """Пустой планировщик — пустая выборка."""
        s = BeatScheduler()
        assert s.due(0.0) == []

    def test_due_exact_boundary(self) -> None:
        """Событие с beat == now выдаётся."""
        s = BeatScheduler()
        s.schedule(_note_on(1.0))
        assert len(s.due(1.0)) == 1
        assert s.pending_count == 0

    def test_due_epsilon_tolerance(self) -> None:
        """Допуск epsilon: beat чуть больше now выдаётся."""
        s = BeatScheduler(epsilon=1e-3)
        s.schedule(_note_on(1.0000005))
        assert len(s.due(1.0)) == 1

    def test_due_future_not_returned(self) -> None:
        """Будущие события не выдаются и остаются."""
        s = BeatScheduler()
        s.schedule(_note_on(2.0))
        assert s.due(1.0) == []
        assert s.pending_count == 1

    def test_due_in_order_across_calls(self) -> None:
        """События выдаются по мере наступления beat."""
        s = BeatScheduler()
        for b in (0.5, 1.5, 2.5):
            s.schedule(_note_on(b))
        assert [ev.beat for ev in s.due(0.5)] == [0.5]
        assert [ev.beat for ev in s.due(1.5)] == [1.5]
        assert [ev.beat for ev in s.due(2.5)] == [2.5]
        assert s.pending_count == 0

    def test_due_late_skipped(self) -> None:
        """Опоздавшие события пропускаются, не выдаются."""
        s = BeatScheduler(epsilon=1e-6)
        s.schedule(_note_on(0.0, note=60))
        s.schedule(_note_on(0.5, note=61))
        due = s.due(2.0)
        # Оба позади now - epsilon — пропущены
        assert due == []
        assert s.pending_count == 0

    def test_due_late_and_due_mixed(self) -> None:
        """Сильно опоздавший пропускается, близкое — выдаётся."""
        s = BeatScheduler(epsilon=1e-6)
        s.schedule(_note_on(0.0, note=60))  # опоздало больше чем на 1/16
        s.schedule(_note_on(1.95, note=61))  # в пределах допуска
        due = s.due(2.0)
        assert [ev.note for ev in due] == [61]
        assert s.pending_count == 0


class TestReset:
    """Сброс планировщика."""

    def test_reset_clears_everything(self) -> None:
        """reset() чистит pending, знак и флаг инициализации."""
        s = BeatScheduler()
        s.ensure(2.0)
        s.schedule(_note_on(3.0))
        s.reset()
        assert s.pending_count == 0
        assert s.watermark == 0.0
        assert not s.initialized

    def test_reset_allows_fresh_start(self) -> None:
        """После reset() ensure() ставит знак заново."""
        s = BeatScheduler()
        s.ensure(100.0)
        s.reset()
        s.ensure(5.0)
        assert s.watermark == 5.0


class TestRepr:
    """repr."""

    def test_repr(self) -> None:
        """repr содержит horizon, watermark, pending."""
        s = BeatScheduler(horizon=4.0)
        s.ensure(1.0)
        s.schedule(_note_on(2.0))
        r = repr(s)
        assert "horizon=4.0" in r
        assert "watermark=1.000" in r
        assert "pending=1" in r
