"""DrumConfig — Pydantic schema для секции drum: в config.yaml."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


class DrumConfig(BaseModel):
    """Конфигурация drum-машины.

    Атрибуты:
        preview_on_select: Предпрослушка lane при выборе (план 4.4).
        preview_velocity: Velocity предпрослушки.
        mutate_min_seconds: Минимальный интервал между мутациями (сек).
        mutate_max_seconds: Максимальный интервал между мутациями (сек).
    """

    preview_on_select: bool = True
    preview_velocity: int = Field(default=100, ge=1, le=127)
    mutate_min_seconds: float = Field(default=8.0, ge=1.0, le=120.0)
    mutate_max_seconds: float = Field(default=16.0, ge=1.0, le=300.0)
