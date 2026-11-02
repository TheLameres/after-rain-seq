"""MutationConfig — Pydantic schema для секции mutation: в config.yaml."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


class MutationConfig(BaseModel):
    """Конфигурация мутации и эволюции.

    Атрибуты:
        enabled: Глобальный выключатель мутации.
        mutate_min_seconds: Минимальный интервал между мутациями (сек).
        mutate_max_seconds: Максимальный интервал между мутациями (сек).
        default_mutate: Значение mutate для новых дорожек (0.0–1.0).
        drift_step_gate: Максимальное смещение gate за мутацию.
        drift_step_density: Максимальное смещение density за мутацию.
        drift_step_register: Максимальное смещение register за мутацию.
    """

    enabled: bool = True
    mutate_min_seconds: float = Field(default=8.0, ge=1.0, le=120.0)
    mutate_max_seconds: float = Field(default=16.0, ge=1.0, le=300.0)
    default_mutate: float = Field(default=0.5, ge=0.0, le=1.0)
    drift_step_gate: float = Field(default=0.05, gt=0.0, le=0.5)
    drift_step_density: float = Field(default=0.1, gt=0.0, le=0.5)
    drift_step_register: float = Field(default=1.0, gt=0.0, le=4.0)
