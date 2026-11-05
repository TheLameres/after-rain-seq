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
from collections.abc import Sequence

from src.core.engine_result import EngineResult
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
    def start_transport(self) -> EngineResult:
        """Запустить транспорт. Вернуть фидбек."""

    @abstractmethod
    def stop_transport(self) -> EngineResult:
        """Остановить транспорт (all notes off). Вернуть фидбек."""

    @abstractmethod
    def set_bpm(self, bpm: float) -> EngineResult:
        """Установить BPM (20..300). Вернуть фидбек или текст ошибки."""

    @abstractmethod
    def set_swing(self, amount: float) -> EngineResult:
        """Установить свинг (0.0–1.0, D2: экран GLOBAL E3). Вернуть фидбек."""

    @abstractmethod
    def request_clock_source(self, source: str) -> EngineResult:
        """Переключить источник клока на ближайшей доле.

        Returns:
            ``"switched to midi on next beat"`` или текст ошибки
            (валидация source, Link не установлен и т.п.).
        """

    # ------------------------------------------------------------------
    # Порты
    # ------------------------------------------------------------------

    @abstractmethod
    def rescan_ports(self) -> EngineResult:
        """Принудительный rescan портов. Вернуть фидбек."""

    @abstractmethod
    def switch_port(self, label: str, match: str) -> EngineResult:
        """Перенаправить лейбл порта на другое устройство (рантайм-only).

        Вернуть фидбек или текст ошибки (неизвестный лейбл и т.п.).
        Применяется на ближайшем poll (~2 с) — старый порт закрывается
        с all_notes_off, новый открывается.
        """

    # ------------------------------------------------------------------
    # Гармония
    # ------------------------------------------------------------------

    @abstractmethod
    def set_root(self, root: str) -> EngineResult:
        """Сменить тонику. Вернуть фидбек или текст ошибки."""

    @abstractmethod
    def set_scale(self, name: str) -> EngineResult:
        """Сменить лад (валидация 8 ладов). Вернуть фидбек или ошибку."""

    # ------------------------------------------------------------------
    # Сессия
    # ------------------------------------------------------------------

    @abstractmethod
    def list_tracks(self) -> list[TrackSummary]:
        """Сводки дорожек (из снапшота)."""

    @abstractmethod
    def create_track(self, profile: str, channel: int | None = None) -> EngineResult:
        """Создать melodic-дорожку профиля. Вернуть фидбек или ошибку.

        ``channel=None`` — автоназначение первого свободного канала.
        """

    @abstractmethod
    def set_track_channel(self, name: str, channel: int) -> EngineResult:
        """Сменить MIDI-канал дорожки в рантайме. Вернуть фидбек или ошибку."""

    @abstractmethod
    def remove_track(self, name: str) -> EngineResult:
        """Удалить дорожку. Вернуть фидбек или ошибку."""

    @abstractmethod
    def route_track(self, name: str, label: str) -> EngineResult:
        """Привязать дорожку к MIDI-порту. Вернуть фидбек или ошибку.

        Старый порт глушится all_notes_off. Рантайм-only.
        """

    @abstractmethod
    def unroute_track(self, name: str) -> EngineResult:
        """Отключить дорожку от порта (тишина). Вернуть фидбек или ошибку."""

    @abstractmethod
    def freeze(self, name: str | None = None) -> EngineResult:
        """Заморозить все дорожки (без имени) или одну. Вернуть фидбек."""

    @abstractmethod
    def evolve(self) -> EngineResult:
        """Разморозить и продолжить эволюцию. Вернуть фидбек."""

    # ------------------------------------------------------------------
    # Сессия — расширения D2 (экраны TRACK/TRACKS)
    # ------------------------------------------------------------------

    @abstractmethod
    def create_drum_track(self) -> EngineResult:
        """Создать drum-дорожку. Вернуть фидбек или текст ошибки (лимиты)."""

    @abstractmethod
    def set_track_sources(self, name: str, *sources: str) -> EngineResult:
        """Назначить источники дорожке (максимум 2).

        Вернуть фидбек или текст ошибки: цикл графа, несуществующая
        дорожка — человекочитаемо, во flash-строку экрана.
        """

    def track_names(self) -> list[str]:
        """Имена дорожек. По умолчанию — из ``list_tracks()``."""
        return [t.name for t in self.list_tracks()]

    # C1–C4: не абстрактные, чтобы существующие заглушки продолжали работать.
    def set_track_degrees(self, name: str, degrees: Sequence[int]) -> EngineResult:
        """Задать прогрессию ступеней. По умолчанию не поддерживается."""
        return EngineResult.fail("degrees are not supported by this control")

    def set_track_voicing(self, name: str, voicing: str) -> EngineResult:
        """Задать voicing. По умолчанию не поддерживается."""
        return EngineResult.fail("voicing is not supported by this control")

    def set_track_inversion(self, name: str, k: int) -> EngineResult:
        """Задать обращение. По умолчанию не поддерживается."""
        return EngineResult.fail("inversion is not supported by this control")

    def set_track_profile(self, name: str, profile_name: str) -> EngineResult:
        """Сменить профиль дорожки. По умолчанию не поддерживается."""
        return EngineResult.fail("profile change is not supported by this control")

    @abstractmethod
    def set_track_gate(self, name: str, gate: float) -> EngineResult:
        """Установить гейт melodic-дорожки (0.0–1.0). Вернуть фидбек/ошибку."""

    @abstractmethod
    def set_track_density(self, name: str, density: float) -> EngineResult:
        """Установить плотность паттерна (0.0–1.0, макро-ось DEN).

        Вернуть фидбек или текст ошибки.
        """

    @abstractmethod
    def set_track_mutate(self, name: str, mutate: float) -> EngineResult:
        """Установить вероятность мутации (0.0–1.0, макро-ось MUT).

        0 = заморожена (как freeze()). Вернуть фидбек или текст ошибки.
        """

    @abstractmethod
    def evolve_track(self, name: str) -> EngineResult:
        """Разморозить одну дорожку (симметрия freeze). Вернуть фидбек."""
