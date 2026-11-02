"""Мелодическая дорожка — профиль + параметры, один ``generate()``.

Различия между типами мелодических дорожек (pad, atmos, sub, stab, seq,
arp, …) — это **данные** (профиль + параметры), не код. Один метод
``generate()`` строит события по профилю; ветвление — на уровне
генератора паттерна, не класса (см. ``track-hierarchy.md``).
"""

from __future__ import annotations

import logging

from src.session.events.chord_event import ChordEvent
from src.session.model.chord_math import chord_degrees_for, pattern_length
from src.session.model.melodic_profile import PROFILES, MelodicProfile
from src.session.model.track import Track

log = logging.getLogger(__name__)


class MelodicTrack(Track):
    """Мелодическая дорожка с профилем.

    Атрибуты:
        profile: Профиль поведения (см. :class:`MelodicProfile`).
        voicing: Имя войсинга из ``Voicing.VOICINGS``.
        inversion: Номер обращения (0..2).
        octave: Октава (0..8).
        gate: Длительность ноты относительно шага (0.0–1.0).
        degrees: Собственная прогрессия в ступенях (у источников).
        mutate: Вероятность мутации 0.0–1.0 (0 = заморожено).
        bpm: Текущий темп (для пересчёта интервала мутации).

    Поведение по профилю:
        - ``emits_chords=True`` (pad, atmos): публикует ``ChordEvent``
          из ``degrees`` по ``voicing``.
        - ``reads_source=True`` + ``sources`` пуст: молчит (стратегия B),
          outbox пуст, не падает.
        - ``reads_source=True`` + ``sources`` заданы: копирует события
          источников (заглушка до C4, где появится нарезка паттерном).
        - ``cc_only=True``: outbox пуст, CC придут в C4.
    """

    def __init__(
        self,
        name: str,
        profile_name: str = "pad",
        channel: int = 0,
        port: str | None = None,
        voicing: str | None = None,
        inversion: int = 0,
        octave: int | None = None,
        gate: float | None = None,
        degrees: list[int] | None = None,
    ) -> None:
        super().__init__(name=name, channel=channel, port=port)
        if profile_name not in PROFILES:
            raise ValueError(f"Неизвестный профиль: {profile_name!r}")
        self.profile: MelodicProfile = PROFILES[profile_name]
        self.voicing: str = (
            voicing if voicing is not None else self.profile.default_voicing
        )
        self.inversion: int = inversion
        self.octave: int = octave if octave is not None else self.profile.default_octave
        self.gate: float = gate if gate is not None else self.profile.default_gate
        self.degrees: list[int] = degrees if degrees is not None else [0, 3, 2, 0]
        self.mutate: float = 0.5
        self.density: float = 1.0
        """Плотность паттерна 0.0–1.0 (D2): 1.0 — базовый рисунок,
        0.0 — ~25% плотности (не тишина). Читается генераторами live."""
        self.bpm: float = 120.0

    # ------------------------------------------------------------------
    # Свойства
    # ------------------------------------------------------------------

    @property
    def profile_name(self) -> str:
        """Имя профиля дорожки."""
        return self.profile.name

    @property
    def mutation_count(self) -> int:
        """Изменений с последней заморозки (0 — MutationEngine не подключён)."""
        return 0

    @property
    def pattern_length(self) -> float:
        """Длина паттерна в beats (период циклического повторения).

        Делегирует в :func:`model.chord_math.pattern_length` — период
        зависит от спецификации профиля (C6): у atmos/texture паттерн
        длиннее такта.
        """
        return pattern_length(self)

    def freeze(self) -> None:
        """Заморозить мутацию (no-op без MutationEngine).

        Устанавливает ``mutate = 0``. MutationEngine, если подключён,
        синхронизируется через ``get_state()``.
        """
        self.mutate = 0.0

    # ------------------------------------------------------------------
    # Смена профиля
    # ------------------------------------------------------------------

    def set_profile(self, profile_name: str) -> None:
        """Сменить профиль дорожки, обновив параметры к дефолтам профиля.

        Аргументы:
            profile_name: Имя профиля из ``PROFILES``.

        Raises:
            ValueError: Если профиль не существует.
        """
        if profile_name not in PROFILES:
            raise ValueError(f"Неизвестный профиль: {profile_name!r}")
        self.profile = PROFILES[profile_name]
        self.voicing = self.profile.default_voicing
        self.octave = self.profile.default_octave
        self.gate = self.profile.default_gate
        log.debug("MelodicTrack %s: profile -> %s", self.name, profile_name)

    # ------------------------------------------------------------------
    # Генерация
    # ------------------------------------------------------------------

    def generate(self) -> list[ChordEvent]:
        """Сгенерировать события в outbox по профилю.

        Полная генерация isobar-паттернов — в C4/C5. Здесь — логика
        публикации и чтения гармонии.

        Returns:
            Список ChordEvent из outbox.
        """
        self.outbox.clear()

        if self.profile.cc_only:
            return []

        if self.profile.emits_chords:
            self._generate_chords()
        elif self.profile.reads_source:
            self._read_sources()

        return list(self.outbox)

    # ------------------------------------------------------------------
    # Внутренние хелперы
    # ------------------------------------------------------------------

    def _generate_chords(self) -> None:
        """Публиковать ChordEvent из собственной прогрессии degrees.

        Ступени аккорда — общая математика с генераторами нот
        (:func:`model.chord_math.chord_degrees_for`): войсинг + обращение.
        """
        beat = 0.0
        for degree in self.degrees:
            chord_degs = chord_degrees_for(self, degree)
            self.outbox.append(
                ChordEvent(
                    beat=beat,
                    degrees=chord_degs,
                    duration=1.0,
                    voicing=self.voicing,
                )
            )
            beat += 1.0

    def _read_sources(self) -> None:
        """Копировать события из источников (заглушка до C4).

        Реальная нарезка паттерном появится в C4. Пока — прямая
        проброска, чтобы граф был функционален.
        """
        if not self.sources:
            return  # стратегия B: молчим, не падаем
        # Реальное чтение из источников требует доступа к сессии.
        # Здесь оставляем outbox пустым — Session вызовет inject_sources()
        # после generate() всех дорожек.

    def inject_sources(self, source_tracks: list[Track]) -> None:
        """Принять события от дорожек-источников.

        Вызывается :class:`Session` после ``generate()`` всех дорожек
        в топологическом порядке.

        Аргументы:
            source_tracks: Дорожки-источники в порядке ``self.sources``.
        """
        if not self.profile.reads_source or not source_tracks:
            return
        for src in source_tracks:
            self.outbox.extend(src.outbox)
