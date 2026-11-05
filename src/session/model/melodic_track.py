"""Мелодическая дорожка — профиль + параметры, один ``generate()``.

Различия между типами мелодических дорожек (pad, atmos, sub, stab, seq,
arp, …) — это **данные** (профиль + параметры), не код. Один метод
``generate()`` строит события по профилю; ветвление — на уровне
генератора паттерна, не класса (см. ``track-hierarchy.md``).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from src.harmony.voicings import Voicing
from src.session.events.chord_event import ChordEvent
from src.session.model.chord_math import chord_degrees_for, pattern_length
from src.session.model.melodic_profile import PROFILES, MelodicProfile
from src.session.model.track import Track

log = logging.getLogger(__name__)

MAX_DEGREES_LEN = 16
"""Максимальная длина прогрессии ``degrees``."""

MAX_DEGREE = 14
"""Верхняя граница (исключая) ступени: две октавы семиступенного лада.
Совпадает с ``NoteDrift._max_degree`` при ``scale_length=7``."""


class MelodicTrack(Track):
    """Мелодическая дорожка с профилем.

    Атрибуты:
        profile: Профиль поведения (см. :class:`MelodicProfile`).
        voicing: Имя войсинга из ``Voicing.VOICINGS`` (property, валидируется).
            ``""`` допустим только для ``cc_only``-профилей.
        inversion: Номер обращения ``0 <= k < len(VOICINGS[voicing])``
            (property, валидируется).
        octave: Октава (0..8).
        gate: Длительность ноты относительно шага (0.0–1.0).
        degrees: Собственная прогрессия в ступенях (property, ``tuple``,
            длина 1..16, каждая ступень ``0 <= d < 14``). Неизменяема на месте.
        revision: Счётчик правок degrees/voicing/inversion/profile. Производные
            (NoteDrift, кэши) сравнивают свою копию с текущей и ресинхронизируются.
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
        degrees: Iterable[int] | None = None,
        color_slot: int | None = None,
    ) -> None:
        super().__init__(name=name, channel=channel, port=port, color_slot=color_slot)
        if profile_name not in PROFILES:
            raise ValueError(f"Неизвестный профиль: {profile_name!r}")
        self.profile: MelodicProfile = PROFILES[profile_name]
        self._revision: int = 0
        self._voicing: str = ""
        self._inversion: int = 0
        self._degrees: tuple[int, ...] = (0, 3, 2, 0)
        # B2: правка degrees ждёт границы ступени; играет _degrees.
        self._pending_degrees: tuple[int, ...] | None = None
        # Порядок важен: inversion проверяется относительно voicing.
        self.voicing = voicing if voicing is not None else self.profile.default_voicing
        self.inversion = inversion
        self.octave: int = octave if octave is not None else self.profile.default_octave
        self.gate: float = gate if gate is not None else self.profile.default_gate
        if degrees is not None:
            self._degrees = self._validate_degrees(degrees)
        self._revision = 0  # конструирование — не правка
        self.mutate: float = 0.5
        self.density: float = 1.0
        """Плотность паттерна 0.0–1.0 (D2): 1.0 — базовый рисунок,
        0.0 — ~25% плотности (не тишина). Читается генераторами live."""

    # ------------------------------------------------------------------
    # Свойства
    # ------------------------------------------------------------------

    @property
    def revision(self) -> int:
        """Растёт при любом изменении играющих degrees (на границе ступени), voicing, inversion, profile."""
        return self._revision

    @property
    def degrees(self) -> tuple[int, ...]:
        """Играющая прогрессия в ступенях (неизменяемый ``tuple``).

        Правка через сеттер попадает в :attr:`pending_degrees` и становится
        играющей только после :meth:`commit_pending_degrees` (B2: на границе
        текущей ступени, её вызывает :class:`MelodicEngine`).
        """
        return self._degrees

    @degrees.setter
    def degrees(self, value: Iterable[int]) -> None:
        """Запросить новую прогрессию (применится на границе ступени).

        Значение, совпадающее с играющим, отменяет ожидающую правку.

        Raises:
            ValueError: Пусто, длина > 16 или ступень вне ``0..13``.
            TypeError: Не последовательность или элемент не ``int``.
        """
        new = self._validate_degrees(value)
        self._pending_degrees = None if new == self._degrees else new

    @property
    def pending_degrees(self) -> tuple[int, ...] | None:
        """Прогрессия, которая применится на следующей границе ступени, или ``None``."""
        return self._pending_degrees

    def commit_pending_degrees(self) -> bool:
        """Сделать ожидающую прогрессию играющей (B2).

        Вызывается движком на границе текущей ступени. Увеличивает ``revision``:
        производные (NoteDrift) пересинхронизируются по нему.

        Returns:
            True, если была ожидающая правка и она применена.
        """
        if self._pending_degrees is None:
            return False
        self._degrees = self._pending_degrees
        self._pending_degrees = None
        self._revision += 1
        return True

    def _validate_degrees(self, value: Iterable[int]) -> tuple[int, ...]:
        """Проверить прогрессию и вернуть её как ``tuple``."""
        if isinstance(value, (str, bytes)):
            raise TypeError(
                f"degrees: ожидается последовательность int, получено {value!r}"
            )
        try:
            new = tuple(value)
        except TypeError:
            raise TypeError(
                f"degrees: ожидается последовательность int, получено {value!r}"
            ) from None
        if not 1 <= len(new) <= MAX_DEGREES_LEN:
            raise ValueError(
                f"degrees: длина должна быть 1..{MAX_DEGREES_LEN}, получено {len(new)} "
                f"(текущее значение {self._degrees})"
            )
        for d in new:
            if isinstance(d, bool) or not isinstance(d, int):
                raise TypeError(f"degrees: ступень должна быть int, получено {d!r}")
            if not 0 <= d < MAX_DEGREE:
                raise ValueError(
                    f"degrees: ступень {d} вне диапазона 0..{MAX_DEGREE - 1} "
                    f"(текущее значение {self._degrees})"
                )
        return new

    @property
    def voicing(self) -> str:
        """Имя войсинга."""
        return self._voicing

    @voicing.setter
    def voicing(self, value: str) -> None:
        """Задать войсинг.

        Если текущее обращение не помещается в новый войсинг (``inversion >=
        len``), оно сбрасывается в 0 с записью в лог.

        Raises:
            HarmonyError: Имени нет в ``Voicing.VOICINGS`` (``""`` допустим
                только для ``cc_only``-профилей).
        """
        if not (value == "" and self.profile.cc_only):
            Voicing.offsets(value)  # HarmonyError для неизвестного имени
        if value != self._voicing:
            self._voicing = value
            self._revision += 1
        size = len(Voicing.VOICINGS.get(value, ()))
        if self._inversion >= max(size, 1):
            log.info(
                "MelodicTrack %s: inversion %d не подходит voicing %r -> 0",
                self.name,
                self._inversion,
                value,
            )
            self._inversion = 0
            self._revision += 1

    @property
    def inversion(self) -> int:
        """Номер обращения."""
        return self._inversion

    @inversion.setter
    def inversion(self, value: int) -> None:
        """Задать обращение.

        Raises:
            ValueError: Вне ``0 <= k < len(VOICINGS[voicing])``
                (для ``cc_only`` с ``voicing=""`` допустим только 0).
            TypeError: Не ``int``.
        """
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"inversion: ожидается int, получено {value!r}")
        size = len(Voicing.VOICINGS.get(self._voicing, ()))
        if not 0 <= value < max(size, 1):
            raise ValueError(
                f"inversion: {value} вне диапазона 0..{max(size, 1) - 1} "
                f"для voicing {self._voicing!r}"
            )
        if value != self._inversion:
            self._inversion = value
            self._revision += 1

    @property
    def profile_name(self) -> str:
        """Имя профиля дорожки."""
        return self.profile.name

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
        self.reset_mutation_count()

    # ------------------------------------------------------------------
    # Смена профиля
    # ------------------------------------------------------------------

    def set_profile(self, profile_name: str) -> None:
        """Сменить профиль дорожки, обновив параметры к дефолтам профиля.

        Сбрасываются к дефолтам нового профиля: ``voicing``, ``octave``, ``gate``
        (``inversion`` обнуляется, если не помещается в новый voicing).
        **Не** сбрасываются: ``degrees`` (пользовательская прогрессия, а не
        свойство профиля), ``mutate``, ``density``, ``sources``.
        Всегда увеличивает ``revision``.

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
        self._revision += 1
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
