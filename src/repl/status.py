"""Снапшоты состояния движка — чистые данные для REPL.

Единственный тип данных, который REPL-поток читает из движка. Всё —
строки/числа/кортежи, frozen dataclass'ы, никаких ссылок на объекты
движка. Собирается в main loop App и публикуется атомарной заменой
ссылки (под GIL замена ссылки атомарна, замок не нужен).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PortSummary:
    """Сводка по одному сконфигурированному MIDI-порту."""

    name: str
    """Человекочитаемая метка из конфига (``label``)."""

    status: str
    """``"connected"`` | ``"disconnected"`` | ``"ambiguous"`` | ``"error"``."""

    detail: str
    """Человекочитаемая строка: resolved name или текст ошибки."""


@dataclass(frozen=True)
class TrackSummary:
    """Сводка по одной дорожке сессии."""

    name: str
    """Автогенерированное имя (``"Pad 1"``, ``"Drum 1"``)."""

    kind: str
    """``"melodic"`` или ``"drum"``."""

    profile: str
    """Имя профиля для melodic; для drum — ``"drum"``."""

    sources: tuple[str, ...]
    """Имена источников (пусто = молчит по стратегии B)."""

    mutation_count: int
    """Изменений с последней заморозки."""

    frozen: bool
    """True, когда ``mutate == 0`` (заморожена)."""

    port: str | None = None
    """Метка MIDI-порта; None — дорожка не привязана (молчит)."""

    gate: float = 0.0
    """Гейт дорожки 0.0–1.0 (melodic; drum всегда 0.0)."""

    voicing: str = ""
    """Имя войсинга (melodic; drum/cc_only — пусто)."""

    octave: int = 0
    """Октава регистра (melodic)."""

    mutate: float = 0.0
    """Вероятность мутации 0.0–1.0 (0 = заморожена)."""

    density: float = 1.0
    """Плотность паттерна 0.0–1.0 (D2; 1.0 = базовый рисунок)."""

    density_applicable: bool = False
    """True, когда профиль применяет density (chord_slicer/free_mono)."""

    channel: int = 0
    """MIDI-канал дорожки (0–15)."""


@dataclass(frozen=True)
class StatusSnapshot:
    """Полный снимок состояния движка для статус-бара и команд.

    Собирается в main loop App; REPL-поток никогда не читает объекты
    движка напрямую — только этот снапшот.
    """

    running: bool
    """Транспорт запущен (клок активен)."""

    bpm: float
    """Текущий BPM."""

    swing: float
    """Величина свинга 0.0–1.0."""

    clock_source: str
    """``"internal"`` | ``"midi"`` | ``"link"``."""

    clock_pending: str | None
    """Ожидающее переключение источника клока (lower-case) или ``None``."""

    clock_error: str | None
    """Ошибка клока или ``None``."""

    link_active: bool
    """Ableton Link активен."""

    link_peers: int
    """Количество Link-пиров."""

    root: str
    """Корневая нота (``"A"``)."""

    scale: str
    """Имя лада (``"dorian"``)."""

    tracks: tuple[TrackSummary, ...]
    """Дорожки в топологическом порядке."""

    total_mutations: int
    """Суммарный счётчик мутаций."""

    ports: tuple[PortSummary, ...]
    """Сконфигурированные порты."""

    log_error: str | None
    """Последняя ошибка из логов (если есть)."""

    midi_clock_device: str = ""
    """Имя устройства MIDI-клока (экран SYNC; "" → «—»)."""

    @classmethod
    def empty(cls) -> StatusSnapshot:
        """Дефолтный пустой снапшот (до первого прохода main loop)."""
        return cls(
            running=False,
            bpm=120.0,
            swing=0.0,
            clock_source="internal",
            clock_pending=None,
            clock_error=None,
            link_active=False,
            link_peers=0,
            root="A",
            scale="dorian",
            tracks=(),
            total_mutations=0,
            ports=(),
            log_error=None,
        )
