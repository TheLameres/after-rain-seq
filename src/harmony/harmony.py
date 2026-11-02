"""Гармонический слой: Root + Scale как единая точка правды.

Этот модуль знает только о **ладе**: корневая нота, набор ступеней
(семитоны) и резолвинг ступени в абсолютный MIDI-номер. Всё, что
касается аккордов (ступени аккорда, качество, диатонические таблицы,
войсинги, обращения) живёт в :mod:`src.harmony.voicings`.

Ступени — это индексы в ладу (не полутоны). isobar нативно резолвит
``degree`` в абсолютный MIDI-номер через ``Key.get()``, перенося октаву
сам (ступень 8 в семиступенном ладу = +14 полутонов, т.е. нона).

Валидация лада: гармонические дорожки разрешены только в восьми
семиступенных ладах, дающих терцовые аккорды (min/maj/dim). Пентатоника
не даёт терций, wholetone даёт только увеличенные, chromatic — всё
подряд. Для них ``set_scale`` бросает :class:`HarmonyError`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from isobar import Key, Scale  # type: ignore[import-untyped]

if TYPE_CHECKING:  # pragma: no cover
    from isobar.timeline import Timeline  # type: ignore[import-untyped]

log = logging.getLogger(__name__)

# Интервалы терцового аккорда в полутонах от корня (используются при
# валидации лада и в voicings.py для вывода качества).
THIRD_MINOR = 3
THIRD_MAJOR = 4
FIFTH_PERFECT = 7
FIFTH_DIMINISHED = 6


class HarmonyError(ValueError):
    """Ошибка гармонического слоя: непригодный лад, нота, ступень."""


class Harmony:
    """Root + Scale — единая точка правды для всех дорожек.

    Владеет isobar :class:`Key` и резолвит ступени в абсолютные MIDI-номера.
    Смена лада или корня пересоздаёт ``Key``; играющие ноты хранят
    абсолютные значения, поэтому смена на ходу безопасна.

    Про аккорды этот класс не знает — см. :mod:`src.harmony.voicings`.
    """

    def __init__(self, root: str = "A", scale: str = "dorian") -> None:
        self._root = root
        self._scale_name = scale
        self._key = self._build_key(root, scale)

    # ------------------------------------------------------------------
    # Публичные свойства
    # ------------------------------------------------------------------

    @property
    def root(self) -> str:
        """Название корневой ноты (например, ``"A"``)."""
        return self._root

    @property
    def scale_name(self) -> str:
        """Имя лада (например, ``"dorian"``)."""
        return self._scale_name

    @property
    def key(self) -> Key:
        """isobar Key — для привязки к таймлайну или прямого резолвинга."""
        return self._key

    @property
    def semitones(self) -> tuple[int, ...]:
        """Семитоны лада от тоники (например, дорийский ``(0,2,3,5,7,9,10)``)."""
        return tuple(self._key.scale.semitones)

    @property
    def scale_length(self) -> int:
        """Количество ступеней в ладу (7 для диатоники)."""
        return len(self._key.scale.semitones)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def set_root(self, root: str) -> None:
        """Сменить корневую ноту. Сохраняет текущий лад."""
        self._root = root
        self._key = self._build_key(root, self._scale_name)
        log.debug("Harmony: root -> %s (%s)", root, self._scale_name)

    def set_scale(self, name: str) -> None:
        """Сменить лад с валидацией.

        Годятся только лады, дающие min/maj/dim по терциям. Пентатоника
        не даёт терций, wholetone даёт только увеличенные — для гармонии
        непригодны, бросаем :class:`HarmonyError`.
        """
        scale = self._resolve_scale(name)
        self._validate_harmonic(scale, name)
        self._scale_name = name
        self._key = self._build_key(self._root, name)
        log.debug("Harmony: scale -> %s (%s)", name, self._root)

    def apply(self, timeline: Timeline) -> None:
        """Привязать Key к таймлайну isobar — влияет на все degree-дорожки."""
        timeline.defaults.key = self._key

    def degree_to_semitone(self, degree: int) -> int:
        """Полутоновое смещение ступени от тоники, с переносом октав.

        Ступень 8 в семиступенном ладу = нона = +14 полутонов. isobar
        делает перенос сам через ``Key.get()``.
        """
        return int(self._key.get(degree))

    def degree_to_note(self, degree: int, octave: int = 5) -> int:
        """Резолвить ступень в абсолютный MIDI-номер.

        Октава переносится isobar'ом сам (ступень 8 = нона = +14 полутонов).
        """
        return self.degree_to_semitone(degree) + (octave * 12)

    # ------------------------------------------------------------------
    # Внутренние хелперы
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_scale(name: str) -> Scale:
        try:
            return Scale.byname(name)
        except Exception as exc:
            raise HarmonyError(f"Неизвестный лад: {name!r}") from exc

    @staticmethod
    def _validate_harmonic(scale: Scale, name: str) -> None:
        """Проверить, что лад даёт только min/maj/dim по терциям."""
        semitones = scale.semitones
        n = len(semitones)
        qualities: set[str] = set()
        for d in range(n):
            notes = [_degree_to_semitone(semitones, d + 2 * k) for k in range(3)]
            third = notes[1] - notes[0]
            fifth = notes[2] - notes[0]
            if third == THIRD_MINOR and fifth == FIFTH_PERFECT:
                qualities.add("min")
            elif third == THIRD_MAJOR and fifth == FIFTH_PERFECT:
                qualities.add("maj")
            elif third == THIRD_MINOR and fifth == FIFTH_DIMINISHED:
                qualities.add("dim")
            else:
                qualities.add(f"other({third},{fifth})")
        if not qualities <= {"min", "maj", "dim"}:
            raise HarmonyError(
                f"{name}: не диатонический по терциям ({sorted(qualities)})"
            )

    @staticmethod
    def _build_key(root: str, scale_name: str) -> Key:
        scale = Harmony._resolve_scale(scale_name)
        try:
            return Key(root, scale)
        except Exception as exc:
            raise HarmonyError(
                f"Некорректный корень {root!r} для лада {scale_name!r}"
            ) from exc


def _degree_to_semitone(semitones: list[int], degree: int) -> int:
    """Полутоновое смещение ступени от тоники, с переносом октав."""
    n = len(semitones)
    octaves, idx = divmod(degree, n)
    return semitones[idx] + octaves * 12
