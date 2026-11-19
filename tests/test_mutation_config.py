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
        assert cfg.drift_step_gate == 0.05
        assert cfg.drift_step_density == 0.1
        assert cfg.drift_step_register == 1.0

    def test_enabled_false(self) -> None:
        """enabled=False — мутация выключена."""
        cfg = MutationConfig(enabled=False)
        assert cfg.enabled is False

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
            "drift_step_gate": 0.03,
            "drift_step_density": 0.07,
            "drift_step_register": 1.5,
        }
        cfg = MutationConfig.model_validate(data)
        assert cfg.enabled is True
        assert cfg.drift_step_gate == 0.03
        assert cfg.drift_step_density == 0.07
        assert cfg.drift_step_register == 1.5
