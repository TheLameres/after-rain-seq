"""harmony — диатонический гармонический слой.

Разделение ответственности:

- :class:`src.harmony.Harmony` — Root + Scale как единая точка правды
  (корень, лад, валидация, резолвинг ступени в MIDI-ноту). Про аккорды
  не знает.
- :class:`src.harmony.Voicing` — аккорды, войсинги, обращения, качество,
  диатонические таблицы. Класс-утилита без состояния, зависит от
  :class:`Harmony`, не наоборот.
"""

from src.harmony.harmony import Harmony, HarmonyError
from src.harmony.voicings import Voicing

__all__ = [
    "Harmony",
    "HarmonyError",
    "Voicing",
]
