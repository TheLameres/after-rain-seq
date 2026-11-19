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
    """

    preview_on_select: bool = True
    preview_velocity: int = Field(default=100, ge=1, le=127)
