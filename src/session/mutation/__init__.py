"""Мутация и эволюция — дрейф параметров мелодических дорожек.

Три механизма мутации (план §6, Фаза 3):

- :class:`NoteDrift` — непрерывный дрейф нот в пределах лада
  (для ``lead``, ``texture``).
- :class:`FloatingEuclidean` — плавающий ``PEuclidean``, pulses дрейфует
  во времени (для ``seq``, ``arp``, ``stab``).
- :class:`ParamDrift` — дрейф диапазонов ``PWhite``-подобный
  (для ``pad``, ``atmos``, ``bass``, ``sub``).

Координатор — :class:`MutationEngine`. Один на сессию, выбирает механизм
по профилю дорожки, управляет интервалом мутации (8–16 секунд),
деградацией к базовому рисунку, freeze/evolve.

Мутация **clock-independent** (план §5.1): оперирует beats, пересчёт
секунды → beats через ``bpm``.
"""

from src.session.mutation.drift_tables import (
    MECH_EUCLIDEAN,
    MECH_NOTE,
    MECH_PARAM,
    MUTATE_MAX_SECONDS,
    MUTATE_MIN_SECONDS,
    PARAM_DRIFT_PARAMS,
    PROFILE_MECHANISM,
)
from src.session.mutation.floating_euclidean import FloatingEuclidean
from src.session.mutation.mutation_config import MutationConfig
from src.session.mutation.mutation_engine import MutationEngine
from src.session.mutation.mutation_state import MutationState
from src.session.mutation.note_drift import NoteDrift
from src.session.mutation.param_drift import ParamDrift

__all__ = [
    "MECH_EUCLIDEAN",
    "MECH_NOTE",
    "MECH_PARAM",
    "MUTATE_MAX_SECONDS",
    "MUTATE_MIN_SECONDS",
    "PARAM_DRIFT_PARAMS",
    "PROFILE_MECHANISM",
    "FloatingEuclidean",
    "MutationConfig",
    "MutationEngine",
    "MutationState",
    "NoteDrift",
    "ParamDrift",
]
