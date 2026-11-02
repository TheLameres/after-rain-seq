"""Тесты для MutationConfig — pydantic-схема конфигурации мутации."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.session.mutation.mutation_config import MutationConfig


class TestMutationConfig:
    """Тесты для MutationConfig."""

    def test_defaults(self) -> None:
        """Дефолтные значения корректны."""
        cfg = MutationConfig()
        assert cfg.enabled is True
        assert cfg.mutate_min_seconds == 8.0
        assert cfg.mutate_max_seconds == 16.0
        assert cfg.default_mutate == 0.5
        assert cfg.drift_step_gate == 0.05
        assert cfg.drift_step_density == 0.1
        assert cfg.drift_step_register == 1.0

    def test_enabled_false(self) -> None:
        """enabled=False — мутация выключена."""
        cfg = MutationConfig(enabled=False)
        assert cfg.enabled is False

    def test_mutate_min_seconds_bounds(self) -> None:
        """mutate_min_seconds валидирует границы."""
        with pytest.raises(ValidationError):
            MutationConfig(mutate_min_seconds=0.5)
        with pytest.raises(ValidationError):
            MutationConfig(mutate_min_seconds=200.0)

    def test_mutate_max_seconds_bounds(self) -> None:
        """mutate_max_seconds валидирует границы."""
        with pytest.raises(ValidationError):
            MutationConfig(mutate_max_seconds=0.5)
        with pytest.raises(ValidationError):
            MutationConfig(mutate_max_seconds=500.0)

    def test_default_mutate_bounds(self) -> None:
        """default_mutate валидирует границы."""
        with pytest.raises(ValidationError):
            MutationConfig(default_mutate=-0.1)
        with pytest.raises(ValidationError):
            MutationConfig(default_mutate=1.1)

    def test_drift_step_gate_bounds(self) -> None:
        """drift_step_gate валидирует границы."""
        with pytest.raises(ValidationError):
            MutationConfig(drift_step_gate=0.0)
        with pytest.raises(ValidationError):
            MutationConfig(drift_step_gate=0.6)

    def test_drift_step_density_bounds(self) -> None:
        """drift_step_density валидирует границы."""
        with pytest.raises(ValidationError):
            MutationConfig(drift_step_density=0.0)
        with pytest.raises(ValidationError):
            MutationConfig(drift_step_density=0.6)

    def test_drift_step_register_bounds(self) -> None:
        """drift_step_register валидирует границы."""
        with pytest.raises(ValidationError):
            MutationConfig(drift_step_register=0.0)
        with pytest.raises(ValidationError):
            MutationConfig(drift_step_register=5.0)

    def test_yaml_roundtrip(self) -> None:
        """Загрузка из YAML-совместимого dict."""
        data = {
            "enabled": True,
            "mutate_min_seconds": 10.0,
            "mutate_max_seconds": 20.0,
            "default_mutate": 0.3,
            "drift_step_gate": 0.03,
            "drift_step_density": 0.07,
            "drift_step_register": 1.5,
        }
        cfg = MutationConfig.model_validate(data)
        assert cfg.enabled is True
        assert cfg.mutate_min_seconds == 10.0
        assert cfg.mutate_max_seconds == 20.0
        assert cfg.default_mutate == 0.3
        assert cfg.drift_step_gate == 0.03
        assert cfg.drift_step_density == 0.07
        assert cfg.drift_step_register == 1.5
