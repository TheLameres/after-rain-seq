"""Контракт управления движком для REPL — ABC.

Единственная точка соприкосновения REPL с движком. Методы, возвращающие
``str``, — пользовательский фидбек: текст результата или текст ошибки
(с префиксом ``"error:"``, код возврата 1). REPL не должен ронять цикл
по исключению команды — реализация ловит исключения движка и
превращает их в текст.

Направление зависимостей строго вниз: ``app/engine_control.py`` импортирует
этот модуль, ``repl/`` не импортирует ``app/`` ни под каким видом
(даже в ``TYPE_CHECKING``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.repl.status import StatusSnapshot, TrackSummary


class EngineControl(ABC):
    """Интерфейс управления движком для REPL.

    Реализуется ``AppEngineControl`` (единственный модуль с доступом
    к внутренностям App). В тестах — мок/стаб.
    """

    @abstractmethod
    def get_status(self) -> StatusSnapshot:
        """Текущий снапшот состояния (собран в main loop)."""

    @abstractmethod
    def get_logs(self, n: int) -> list[str]:
        """Последние ``n`` строк лога из кольцевого буфера."""

    # ------------------------------------------------------------------
    # Транспорт и клок
    # ------------------------------------------------------------------

    @abstractmethod
    def start_transport(self) -> str:
        """Запустить транспорт. Вернуть фидбек."""

    @abstractmethod
    def stop_transport(self) -> str:
        """Остановить транспорт (all notes off). Вернуть фидбек."""

    @abstractmethod
    def set_bpm(self, bpm: float) -> str:
        """Установить BPM (20..300). Вернуть фидбек или текст ошибки."""

    @abstractmethod
    def set_swing(self, amount: float) -> str:
        """Установить свинг (0.0–1.0, D2: экран GLOBAL E3). Вернуть фидбек."""

    @abstractmethod
    def request_clock_source(self, source: str) -> str:
        """Переключить источник клока на ближайшей доле.

        Returns:
            ``"switched to midi on next beat"`` или текст ошибки
            (валидация source, Link не установлен и т.п.).
        """

    # ------------------------------------------------------------------
    # Порты
    # ------------------------------------------------------------------

    @abstractmethod
    def rescan_ports(self) -> str:
        """Принудительный rescan портов. Вернуть фидбек."""

    @abstractmethod
    def switch_port(self, label: str, match: str) -> str:
        """Перенаправить лейбл порта на другое устройство (рантайм-only).

        Вернуть фидбек или текст ошибки (неизвестный лейбл и т.п.).
        Применяется на ближайшем poll (~2 с) — старый порт закрывается
        с all_notes_off, новый открывается.
        """

    # ------------------------------------------------------------------
    # Гармония
    # ------------------------------------------------------------------

    @abstractmethod
    def set_root(self, root: str) -> str:
        """Сменить тонику. Вернуть фидбек или текст ошибки."""

    @abstractmethod
    def set_scale(self, name: str) -> str:
        """Сменить лад (валидация 8 ладов). Вернуть фидбек или ошибку."""

    # ------------------------------------------------------------------
    # Сессия
    # ------------------------------------------------------------------

    @abstractmethod
    def list_tracks(self) -> list[TrackSummary]:
        """Сводки дорожек (из снапшота)."""

    @abstractmethod
    def create_track(self, profile: str, channel: int | None = None) -> str:
        """Создать melodic-дорожку профиля. Вернуть фидбек или ошибку.

        ``channel=None`` — автоназначение первого свободного канала.
        """

    @abstractmethod
    def set_track_channel(self, name: str, channel: int) -> str:
        """Сменить MIDI-канал дорожки в рантайме. Вернуть фидбек или ошибку."""

    @abstractmethod
    def remove_track(self, name: str) -> str:
        """Удалить дорожку. Вернуть фидбек или ошибку."""

    @abstractmethod
    def route_track(self, name: str, label: str) -> str:
        """Привязать дорожку к MIDI-порту. Вернуть фидбек или ошибку.

        Старый порт глушится all_notes_off. Рантайм-only.
        """

    @abstractmethod
    def unroute_track(self, name: str) -> str:
        """Отключить дорожку от порта (тишина). Вернуть фидбек или ошибку."""

    @abstractmethod
    def freeze(self, name: str | None = None) -> str:
        """Заморозить все дорожки (без имени) или одну. Вернуть фидбек."""

    @abstractmethod
    def evolve(self) -> str:
        """Разморозить и продолжить эволюцию. Вернуть фидбек."""

    # ------------------------------------------------------------------
    # Сессия — расширения D2 (экраны TRACK/TRACKS)
    # ------------------------------------------------------------------

    @abstractmethod
    def create_drum_track(self) -> str:
        """Создать drum-дорожку. Вернуть фидбек или текст ошибки (лимиты)."""

    @abstractmethod
    def set_track_sources(self, name: str, *sources: str) -> str:
        """Назначить источники дорожке (максимум 2).

        Вернуть фидбек или текст ошибки: цикл графа, несуществующая
        дорожка — человекочитаемо, во flash-строку экрана.
        """

    @abstractmethod
    def set_track_gate(self, name: str, gate: float) -> str:
        """Установить гейт melodic-дорожки (0.0–1.0). Вернуть фидбек/ошибку."""

    @abstractmethod
    def set_track_density(self, name: str, density: float) -> str:
        """Установить плотность паттерна (0.0–1.0, макро-ось DEN).

        Вернуть фидбек или текст ошибки.
        """

    @abstractmethod
    def set_track_mutate(self, name: str, mutate: float) -> str:
        """Установить вероятность мутации (0.0–1.0, макро-ось MUT).

        0 = заморожена (как freeze()). Вернуть фидбек или текст ошибки.
        """

    @abstractmethod
    def evolve_track(self, name: str) -> str:
        """Разморозить одну дорожку (симметрия freeze). Вернуть фидбек."""
