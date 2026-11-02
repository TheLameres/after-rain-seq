"""Tests for PEuclideanCached — евклидовы ритмы с кешем."""

import pytest

from src.session.model.euclidean import PEuclideanCached

# ---------------------------------------------------------------------------
# Паттерн: корректность
# ---------------------------------------------------------------------------


def test_all_rests():
    """pulses=0 → все нули."""
    eucl = PEuclideanCached(steps=16, pulses=0)
    assert eucl.pattern == [0] * 16


def test_all_active():
    """pulses=steps → все единицы."""
    eucl = PEuclideanCached(steps=16, pulses=16)
    assert eucl.pattern == [1] * 16


def test_single_pulse():
    """pulses=1 → только первый шаг активен."""
    eucl = PEuclideanCached(steps=8, pulses=1)
    assert eucl.pattern == [1, 0, 0, 0, 0, 0, 0, 0]


def test_four_on_floor():
    """4/16 = классический four-on-the-floor: каждый 4-й шаг."""
    eucl = PEuclideanCached(steps=16, pulses=4)
    pattern = eucl.pattern
    assert len(pattern) == 16
    assert sum(pattern) == 4
    # Шаги 0, 4, 8, 12 активны
    assert pattern[0] == 1
    assert pattern[4] == 1
    assert pattern[8] == 1
    assert pattern[12] == 1
    assert pattern[1] == 0


def test_three_on_eight():
    """3/8 — распределение [1,0,0,1,0,0,1,0]."""
    eucl = PEuclideanCached(steps=8, pulses=3)
    assert eucl.pattern == [1, 0, 0, 1, 0, 0, 1, 0]


def test_five_on_sixteen():
    """5/16 — равномерное распределение."""
    eucl = PEuclideanCached(steps=16, pulses=5)
    pattern = eucl.pattern
    assert sum(pattern) == 5
    assert pattern[0] == 1  # первый шаг всегда активен


def test_pattern_length():
    """Длина паттерна всегда равна steps."""
    for steps in (1, 4, 8, 16, 32, 64):
        for pulses in range(steps + 1):
            eucl = PEuclideanCached(steps=steps, pulses=pulses)
            assert len(eucl.pattern) == steps


def test_pattern_sum():
    """Сумма паттерна всегда равна pulses."""
    for steps in (8, 16, 32):
        for pulses in range(steps + 1):
            eucl = PEuclideanCached(steps=steps, pulses=pulses)
            assert sum(eucl.pattern) == pulses


# ---------------------------------------------------------------------------
# Кеш
# ---------------------------------------------------------------------------


def test_cache_returns_copy():
    """pattern возвращает копию — внешний код не портит кеш."""
    eucl = PEuclideanCached(steps=8, pulses=3)
    p1 = eucl.pattern
    p1[0] = 99  # портим копию
    assert eucl.pattern[0] == 1  # кеш не пострадал


def test_pulses_setter_invalidates_cache():
    """Смена pulses инвалидирует кеш."""
    eucl = PEuclideanCached(steps=8, pulses=3)
    p1 = eucl.pattern
    eucl.pulses = 5
    p2 = eucl.pattern
    assert sum(p1) == 3
    assert sum(p2) == 5


def test_pulses_setter_same_value_no_invalidation():
    """Присвоение того же pulses не инвалидирует (оптимизация)."""
    eucl = PEuclideanCached(steps=8, pulses=3)
    _ = eucl.pattern  # заполняем кеш
    eucl._cached_marker = eucl._cached  # сохраняем ссылку
    eucl.pulses = 3  # то же значение
    assert eucl._cached is eucl._cached_marker  # кеш не тронут


# ---------------------------------------------------------------------------
# Валидация
# ---------------------------------------------------------------------------


def test_steps_zero_raises():
    """steps=0 → ValueError."""
    with pytest.raises(ValueError, match="steps"):
        PEuclideanCached(steps=0, pulses=0)


def test_pulses_negative_raises():
    """Отрицательные pulses → ValueError."""
    with pytest.raises(ValueError, match="pulses"):
        PEuclideanCached(steps=8, pulses=-1)


def test_pulses_exceeds_steps_raises():
    """pulses > steps → ValueError."""
    with pytest.raises(ValueError, match=">"):
        PEuclideanCached(steps=8, pulses=9)


def test_pulses_setter_negative_raises():
    """Setter pulses с отрицательным значением → ValueError."""
    eucl = PEuclideanCached(steps=8, pulses=3)
    with pytest.raises(ValueError, match="pulses"):
        eucl.pulses = -1


def test_pulses_setter_exceeds_steps_raises():
    """Setter pulses > steps → ValueError."""
    eucl = PEuclideanCached(steps=8, pulses=3)
    with pytest.raises(ValueError, match=">"):
        eucl.pulses = 9


# ---------------------------------------------------------------------------
# Отладка
# ---------------------------------------------------------------------------


def test_repr():
    """repr показывает steps и pulses."""
    eucl = PEuclideanCached(steps=16, pulses=4)
    r = repr(eucl)
    assert "16" in r
    assert "4" in r
