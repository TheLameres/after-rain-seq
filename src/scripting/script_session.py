"""Объект ``session``, видимый скрипту: обёртки над EngineControl ABC.

Единственный фасад скрипта (план G2 §3.7). Все вызовы проходят через
:class:`src.repl.engine_control.EngineControl` — скрипт не знает о
внутренностях App. Каждый метод возвращает :class:`EngineResult`:

- ``fatal=True`` (по умолчанию): ``EngineResult.error`` ⇒ ``ScriptError``;
- ``fatal=False``: вернуть ``EngineResult`` как есть — скрипт сам решает,
  продолжать ли.

Деструктивные операции (``stop``, ``remove_track``) выполняются с
авто-подтверждением (эквивалент ``--yes``): в лог пишется
``script: auto-confirmed destructive <op>``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Final

from src.core.engine_result import EngineResult
from src.core.proposal import DrumProposal, TrackProposal
from src.repl.engine_control import EngineControl
from src.scripting.error import ScriptError

log = logging.getLogger(__name__)

# Деструктивные операции: подтверждение не спрашивается, но факт
# подтверждения пишется в лог (план G2 §3.7). Имена — методы EngineControl
# в терминах `_call`: фасадный `stop()` вызывает `stop_transport`.
DESTRUCTIVE_OPS: Final[frozenset[str]] = frozenset({"stop_transport", "remove_track"})


class ScriptSession:
    """Объект ``session``, видимый скрипту. Все вызовы — через EngineControl ABC.

    Аргументы:
        control: Контракт управления движком (в тестах — мок).
    """

    def __init__(self, control: EngineControl) -> None:
        self._control = control

    # ------------------------------------------------------------------
    # Сессия — раскладка proposal → примитивы ABC
    # ------------------------------------------------------------------

    def add_track(self, proposal: TrackProposal, *, fatal: bool = True) -> EngineResult:
        """Создать melodic-дорожку по proposal и применить voicing/degrees.

        Шаги цепочки (что задано в proposal):
            1. ``create_track(profile_name, channel, name)``;
            2. ``set_track_voicing(name, voicing)`` — если voicing задан;
            3. ``set_track_degrees(name, degrees)`` — если degrees заданы.

        Имя дорожки для шагов 2–3 берётся из ``result.data["track"]``
        (фасад кладёт имя после создания) — надёжнее, чем ``proposal.name``.
        Неудачный шаг: ``ScriptError`` (fatal) или возврат ``EngineResult``.

        Аргументы:
            proposal: Замысел melodic-дорожки.
            fatal: Бросать ли ``ScriptError`` при ошибке.

        Returns:
            ``EngineResult`` неудачного шага или итогового шага цепочки.

        Raises:
            ScriptError: Шаг цепочки вернул ошибку при ``fatal=True``.
        """
        created = self._call(
            "create_track",
            (proposal.profile_name, proposal.channel, proposal.name),
            fatal=fatal,
        )
        if created.error:
            return created
        track_name = created.data.get("track")
        if not isinstance(track_name, str):
            track_name = proposal.name
        if proposal.voicing is not None:
            voiced = self._call(
                "set_track_voicing", (track_name, proposal.voicing), fatal=fatal
            )
            if voiced.error:
                return voiced
        if proposal.degrees is not None:
            degreed = self._call(
                "set_track_degrees", (track_name, proposal.degrees), fatal=fatal
            )
            if degreed.error:
                return degreed
        return created

    def add_drum(self, proposal: DrumProposal, *, fatal: bool = True) -> EngineResult:
        """Создать drum-дорожку по proposal (``create_drum_track(name)``).

        Аргументы:
            proposal: Замысел drum-дорожки.
            fatal: Бросать ли ``ScriptError`` при ошибке.

        Returns:
            ``EngineResult`` движения ``create_drum_track``.

        Raises:
            ScriptError: Движок вернул ошибку при ``fatal=True``.
        """
        return self._call("create_drum_track", (proposal.name,), fatal=fatal)

    # ------------------------------------------------------------------
    # Транспорт и клок
    # ------------------------------------------------------------------

    def start(self, *, fatal: bool = True) -> EngineResult:
        """Запустить транспорт (``EngineControl.start_transport``)."""
        return self._call("start_transport", (), fatal=fatal)

    def stop(self, *, fatal: bool = True) -> EngineResult:
        """Остановить транспорт (all notes off). Деструктив: авто-confirm."""
        return self._call("stop_transport", (), fatal=fatal, op="stop")

    def set_bpm(self, bpm: float, *, fatal: bool = True) -> EngineResult:
        """Установить BPM (20..300; валидация — движок)."""
        return self._call("set_bpm", (bpm,), fatal=fatal)

    def set_swing(self, amount: float, *, fatal: bool = True) -> EngineResult:
        """Установить свинг 0.0–1.0 (валидация — движок)."""
        return self._call("set_swing", (amount,), fatal=fatal)

    def request_clock_source(self, source: str, *, fatal: bool = True) -> EngineResult:
        """Переключить источник клока (internal|midi|link) на ближайшей доле.

        Обёртка 1:1 над ``EngineControl.request_clock_source``: движок
        применяет переключение queued (на ближайшей доле), обёртка
        фактического переключения не ждёт.
        """
        return self._call("request_clock_source", (source,), fatal=fatal)

    # ------------------------------------------------------------------
    # Захват SMF (add-capture-smf)
    # ------------------------------------------------------------------

    def capture_start(
        self, path: str | None = None, *, fatal: bool = True
    ) -> EngineResult:
        """Начать запись вывода в SMF (``EngineControl.capture_start``).

        Обёртка 1:1: ``path=None`` — автогенерация имени в ``captures/``;
        существующий файл — ошибка движка (перезапись запрещена).
        """
        return self._call("capture_start", (path,), fatal=fatal)

    def capture_stop(self, *, fatal: bool = True) -> EngineResult:
        """Остановить запись и создать SMF-файл (``capture_stop``)."""
        return self._call("capture_stop", (), fatal=fatal)

    # ------------------------------------------------------------------
    # Гармония
    # ------------------------------------------------------------------

    def set_root(self, root: str, *, fatal: bool = True) -> EngineResult:
        """Сменить тонику (валидация — движок)."""
        return self._call("set_root", (root,), fatal=fatal)

    def set_scale(self, name: str, *, fatal: bool = True) -> EngineResult:
        """Сменить лад (8 ладов; валидация — движок)."""
        return self._call("set_scale", (name,), fatal=fatal)

    # ------------------------------------------------------------------
    # Дорожки
    # ------------------------------------------------------------------

    def remove_track(self, name: str, *, fatal: bool = True) -> EngineResult:
        """Удалить дорожку. Деструктив: авто-confirm."""
        return self._call("remove_track", (name,), fatal=fatal)

    def set_track_channel(
        self, name: str, channel: int, *, fatal: bool = True
    ) -> EngineResult:
        """Сменить MIDI-канал дорожки (0..15)."""
        return self._call("set_track_channel", (name, channel), fatal=fatal)

    def route_track(self, name: str, label: str, *, fatal: bool = True) -> EngineResult:
        """Привязать дорожку к MIDI-порту (старый порт глушится)."""
        return self._call("route_track", (name, label), fatal=fatal)

    def unroute_track(self, name: str, *, fatal: bool = True) -> EngineResult:
        """Отключить дорожку от порта (тишина, сессия живёт)."""
        return self._call("unroute_track", (name,), fatal=fatal)

    def set_track_sources(
        self, name: str, *sources: str, fatal: bool = True
    ) -> EngineResult:
        """Назначить источники гармонии (максимум 2; без аргументов — снять)."""
        return self._call("set_track_sources", (name, *sources), fatal=fatal)

    def set_track_degrees(
        self, name: str, degrees: Sequence[int], *, fatal: bool = True
    ) -> EngineResult:
        """Задать прогрессию ступеней дорожки."""
        return self._call("set_track_degrees", (name, degrees), fatal=fatal)

    def set_track_voicing(
        self, name: str, voicing: str, *, fatal: bool = True
    ) -> EngineResult:
        """Задать voicing дорожки (формат ``"1-3-5"``, реестр VOICINGS)."""
        return self._call("set_track_voicing", (name, voicing), fatal=fatal)

    def set_track_octave(
        self, name: str, octave: int, *, fatal: bool = True
    ) -> EngineResult:
        """Задать октаву melodic-дорожки (0..8)."""
        return self._call("set_track_octave", (name, octave), fatal=fatal)

    def set_track_inversion(
        self, name: str, k: int, *, fatal: bool = True
    ) -> EngineResult:
        """Задать обращение аккорда дорожки (0..len(voicing)-1)."""
        return self._call("set_track_inversion", (name, k), fatal=fatal)

    def set_track_profile(
        self, name: str, profile_name: str, *, fatal: bool = True
    ) -> EngineResult:
        """Сменить профиль дорожки (cc_only ↔ нота требует перезапуска)."""
        return self._call("set_track_profile", (name, profile_name), fatal=fatal)

    def set_track_gate(
        self, name: str, gate: float, *, fatal: bool = True
    ) -> EngineResult:
        """Задать гейт melodic-дорожки (0.0–1.0; валидация — движок)."""
        return self._call("set_track_gate", (name, gate), fatal=fatal)

    def set_track_density(
        self, name: str, density: float, *, fatal: bool = True
    ) -> EngineResult:
        """Задать плотность паттерна (0.0–1.0, макро-ось DEN; валидация — движок)."""
        return self._call("set_track_density", (name, density), fatal=fatal)

    def set_drum_pattern(
        self, name: str, lane: str, pattern: str, *, fatal: bool = True
    ) -> EngineResult:
        """Задать паттерн lane'а drum-дорожки строкой-нотацией.

        Обёртка 1:1 над ``EngineControl.set_drum_pattern``: нотация
        (``x``/``X``/``.``/``~``, евклид ``(p,s[,offset])``) компилируется
        движком; пустая строка — очистка lane'а. Правка записывается
        в историю версий (design §7).
        """
        return self._call("set_drum_pattern", (name, lane, pattern), fatal=fatal)

    # ------------------------------------------------------------------
    # Порты
    # ------------------------------------------------------------------

    def rescan_ports(self, *, fatal: bool = True) -> EngineResult:
        """Принудительный rescan портов."""
        return self._call("rescan_ports", (), fatal=fatal)

    def switch_port(
        self, label: str, match: str, *, fatal: bool = True
    ) -> EngineResult:
        """Перенаправить лейбл порта на другое устройство (рантайм-only)."""
        return self._call("switch_port", (label, match), fatal=fatal)

    # ------------------------------------------------------------------
    # Внутреннее
    # ------------------------------------------------------------------

    def _call(
        self,
        method_name: str,
        args: tuple[object, ...],
        *,
        fatal: bool,
        op: str | None = None,
    ) -> EngineResult:
        """Вызвать метод EngineControl; ошибка ⇒ ScriptError (fatal) / result.

        Деструктивные операции выполняются с авто-подтверждением: в лог
        пишется предупреждение (план G2 §3.7).

        Аргументы:
            method_name: Имя метода ``EngineControl``.
            args: Позиционные аргументы вызова.
            fatal: Бросать ли ``ScriptError`` при ошибке.
            op: Лейбл операции фасада для лога (если отличается от
                ``method_name``, например ``stop`` вместо ``stop_transport``).

        Returns:
            ``EngineResult`` движения (при ``fatal=True`` — всегда успешный).

        Raises:
            ScriptError: Движок вернул ошибку при ``fatal=True``.
        """
        if method_name in DESTRUCTIVE_OPS:
            log.warning("script: auto-confirmed destructive %s", op or method_name)
        method: Callable[..., EngineResult] = getattr(self._control, method_name)
        result = method(*args)
        if result.error and fatal:
            raise ScriptError(result.message)
        return result
