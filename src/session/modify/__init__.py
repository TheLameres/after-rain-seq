"""Модификации событий: цепочка этапов поверх списка событий (§3.3)."""

from src.session.modify.arpeggiate import ArpeggiateStage
from src.session.modify.chain import Chain, Stage, StageContext
from src.session.modify.densify import DensifyStage

__all__ = ["ArpeggiateStage", "Chain", "DensifyStage", "Stage", "StageContext"]
