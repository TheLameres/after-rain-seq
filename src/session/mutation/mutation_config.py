"""MutationConfig — Pydantic schema для секции mutation: в config.yaml."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


class MutationConfig(BaseModel):
    """Конфигурация мутации.

    Атрибуты:
        enabled: Глобальный выключатель мутации.
        drift_step_gate: Максимальное смещение gate за мутацию.
        drift_step_density: Максимальное смещение density за мутацию.
        drift_step_register: Максимальное смещение register за мутацию.
    """

    enabled: bool = True
    drift_step_gate: float = Field(default=0.05, gt=0.0, le=0.5)
    drift_step_density: float = Field(default=0.1, gt=0.0, le=0.5)
    drift_step_register: float = Field(default=1.0, gt=0.0, le=4.0)
