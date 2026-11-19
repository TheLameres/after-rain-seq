"""Мутация — дрейф параметров, только по явному действию пользователя.

Три механизма мутации (план §6, Фаза 3):

- :class:`NoteDrift` — непрерывный дрейф нот в пределах лада
  (для ``lead``, ``texture``).
- :class:`FloatingEuclidean` — плавающий ``PEuclidean``, pulses дрейфует
  во времени (для ``seq``, ``arp``, ``stab``).
- :class:`ParamDrift` — дрейф диапазонов ``PWhite``-подобный
  (для ``pad``, ``atmos``, ``bass``, ``sub``).

Координатор — :class:`MutationEngine`. Один на сессию, выбирает механизм
по профилю дорожки. Автономного таймера нет: мутация применяется по
явному запросу (``request_mutation``) на ближайшей границе цикла дорожки.
"""

from src.session.mutation.drift_tables import (
    MECH_EUCLIDEAN,
    MECH_NOTE,
    MECH_PARAM,
    PARAM_DRIFT_PARAMS,
    PROFILE_MECHANISM,
)
from src.session.mutation.floating_euclidean import FloatingEuclidean
from src.session.mutation.mutation_config import MutationConfig
from src.session.mutation.mutation_engine import MutationEngine
from src.session.mutation.mutation_state import MutationState
from src.session.mutation.note_drift import NoteDrift
from src.session.mutation.param_drift import ParamDrift
from src.session.mutation.track_version import DrumVersion, MelodicVersion

__all__ = [
    "MECH_EUCLIDEAN",
    "MECH_NOTE",
    "MECH_PARAM",
    "PARAM_DRIFT_PARAMS",
    "PROFILE_MECHANISM",
    "DrumVersion",
    "FloatingEuclidean",
    "MelodicVersion",
    "MutationConfig",
    "MutationEngine",
    "MutationState",
    "NoteDrift",
    "ParamDrift",
]
