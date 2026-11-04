"""Координатор мутации для всех мелодических дорожек сессии.

На каждом тике:
1. Для каждой дорожки с mutate > 0: проверить, пришло ли время мутации
2. Выбрать механизм по профилю дорожки (таблица ``PROFILE_MECHANISM``)
3. Применить мутацию или деградацию
4. Обновить :class:`MutationState`

Мутация **clock-independent** (план §5.1): оперирует beats, пересчёт
секунды → beats через ``bpm``.
"""

from __future__ import annotations

import logging
import random

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
from src.session.mutation.mutation_state import MutationState
from src.session.mutation.note_drift import NoteDrift
from src.session.mutation.param_drift import ParamDrift

log = logging.getLogger(__name__)


class MutationEngine:
    """Координатор мутации для всех мелодических дорожек сессии.

    Механизм выбирается по профилю:
        lead, texture    → NoteDrift
        seq, arp, stab   → FloatingEuclidean
        pad, atmos, bass → ParamDrift
        cc_*             → пропуск (нет нот)
    """

    def __init__(
        self,
        min_seconds: float = MUTATE_MIN_SECONDS,
        max_seconds: float = MUTATE_MAX_SECONDS,
        default_mutate: float = 0.5,
        rng: random.Random | None = None,
    ) -> None:
        if min_seconds >= max_seconds:
            raise ValueError(
                f"min_seconds ({min_seconds}) должен быть < max_seconds ({max_seconds})"
            )
        self._min_seconds: float = min_seconds
        self._max_seconds: float = max_seconds
        self._default_mutate: float = default_mutate
        self._rng: random.Random = rng if rng is not None else random.Random()

        self._note_drifts: dict[str, NoteDrift] = {}
        self._euclidean_drifts: dict[str, FloatingEuclidean] = {}
        self._param_drifts: dict[str, ParamDrift] = {}
        self._states: dict[str, MutationState] = {}
        self._track_profiles: dict[str, str] = {}
        self._track_mutate: dict[str, float] = {}
        # §4.4: дорожки-владельцы счётчика (пишем в них, читаем из них).
        self._track_refs: dict[str, object] = {}

    # ------------------------------------------------------------------
    # Регистрация
    # ------------------------------------------------------------------

    def register_track(
        self,
        track_name: str,
        profile_name: str,
        mutate: float | None = None,
        bpm: float = 120.0,
        degrees: list[int] | None = None,
        scale_length: int = 7,
        euclidean_steps: int = 16,
        euclidean_pulses: int = 4,
        gate: float = 0.5,
        density: float = 0.5,
        register: int = 0,
        track: object | None = None,
    ) -> None:
        """Зарегистрировать мелодическую дорожку для мутации.

        Создаёт нужный механизм по профилю, инициализирует MutationState.

        Аргументы:
            track_name: Имя дорожки.
            profile_name: Имя профиля (``"lead"``, ``"seq"``, ``"pad"``, …).
            mutate: Начальное значение mutate (None = default_mutate).
            bpm: Текущий темп.
            degrees: Базовые ступени (для NoteDrift).
            scale_length: Длина лада (для NoteDrift).
            euclidean_steps: Шаги сетки (для FloatingEuclidean).
            euclidean_pulses: Базовые pulses (для FloatingEuclidean).
            gate: Базовый gate (для ParamDrift).
            density: Базовая density (для ParamDrift).
            register: Базовый register (для ParamDrift).
            track: Дорожка-владелец счётчика (§4.4); движок пишет в неё.
        """
        effective_mutate = mutate if mutate is not None else self._default_mutate
        if track is not None:
            self._track_refs[track_name] = track
        self._track_profiles[track_name] = profile_name
        self._track_mutate[track_name] = effective_mutate

        # Создаём механизм по профилю (таблица PROFILE_MECHANISM, C6)
        mechanism = PROFILE_MECHANISM.get(profile_name)
        if mechanism == MECH_NOTE:
            base = degrees if degrees is not None else [0, 2, 4, 2]
            self._note_drifts[track_name] = NoteDrift(base, scale_length)
        elif mechanism == MECH_EUCLIDEAN:
            self._euclidean_drifts[track_name] = FloatingEuclidean(
                euclidean_steps, euclidean_pulses
            )
        elif mechanism == MECH_PARAM:
            pd = ParamDrift()
            for pname, pbase, lo, hi, step in PARAM_DRIFT_PARAMS.get(
                profile_name,
                (("gate", gate, 0.1, 1.0, 0.05),),
            ):
                # База «gate» — актуальный гейт дорожки (может отличаться
                # от дефолта профиля), остальные — из таблицы.
                eff_base = gate if pname == "gate" else pbase
                pd.add_param(pname, eff_base, lo, hi, step)
            self._param_drifts[track_name] = pd
        # cc_* и неизвестные профили — пропускаем

        # Инициализируем состояние
        next_beat = self._compute_next_mutation_beat(0.0, bpm)
        self._states[track_name] = MutationState(
            mutate=effective_mutate,
            mutation_count=0,
            next_mutation_beat=next_beat,
            last_mutation_beat=0.0,
        )
        log.debug("MutationEngine: зарегистрирован %s (%s)", track_name, profile_name)

    def unregister_track(self, track_name: str) -> None:
        """Удалить дорожку из мутации (при удалении из сессии).

        Аргументы:
            track_name: Имя дорожки.
        """
        self._track_refs.pop(track_name, None)
        self._note_drifts.pop(track_name, None)
        self._euclidean_drifts.pop(track_name, None)
        self._param_drifts.pop(track_name, None)
        self._states.pop(track_name, None)
        self._track_profiles.pop(track_name, None)
        self._track_mutate.pop(track_name, None)

    # ------------------------------------------------------------------
    # Тик
    # ------------------------------------------------------------------

    def tick(self, current_beat: float, bpm: float) -> list[str]:
        """Один тик мутации.

        Аргументы:
            current_beat: Текущая позиция в тактах.
            bpm: Текущий темп. Передаётся снаружи (от часов) и не хранится:
                интервал мутации считается в секундах, поэтому темп нужен
                в момент тика.

        Returns:
            Имена дорожек, которые мутировали на этом тике.
        """
        mutated: list[str] = []
        for name, state in self._states.items():
            if state.mutate <= 0.0:
                continue
            if current_beat < state.next_mutation_beat:
                continue

            # Деградация: с вероятностью mutate откатываем
            if state.mutation_count > 0 and self._rng.random() < state.mutate:
                changed = self._apply_revert(name)
                delta = -1
            else:
                changed = self._apply_mutation(name)
                delta = 1
            # §4.4: счётчик — на дорожке (источник истины, §3.4).
            if changed:
                track = self._track_refs.get(name)
                recorder = getattr(track, "record_mutation", None)
                if callable(recorder):
                    recorder(delta)

            new_state = MutationState(
                mutate=state.mutate,
                mutation_count=state.mutation_count + 1,
                next_mutation_beat=self._compute_next_mutation_beat(current_beat, bpm),
                last_mutation_beat=current_beat,
            )
            self._states[name] = new_state
            mutated.append(name)
        return mutated

    def _apply_mutation(self, track_name: str) -> bool:
        """Применить мутацию к дорожке через её механизм.

        Returns:
            True, если механизм действительно что-то изменил (§4.4).
        """
        if track_name in self._note_drifts:
            return bool(self._note_drifts[track_name].drift_one(self._rng))
        if track_name in self._euclidean_drifts:
            return bool(self._euclidean_drifts[track_name].drift(self._rng))
        if track_name in self._param_drifts:
            return self._param_drifts[track_name].drift_one(self._rng) is not None
        return False

    def _apply_revert(self, track_name: str) -> bool:
        """Откатить одно изменение к базовому.

        Returns:
            True, если механизм действительно что-то откатил.
        """
        if track_name in self._note_drifts:
            return bool(self._note_drifts[track_name].revert_one(self._rng))
        if track_name in self._euclidean_drifts:
            return bool(self._euclidean_drifts[track_name].revert(self._rng))
        if track_name in self._param_drifts:
            return self._param_drifts[track_name].revert_one(self._rng) is not None
        return False

    def _compute_next_mutation_beat(self, from_beat: float, bpm: float) -> float:
        """Вычислить beat следующей мутации.

        Интервал от времени (секунды), не от тактов — при смене BPM
        частота мутации сохраняется (план §4.2).

        Аргументы:
            from_beat: Beat, от которого отсчитывать.
            bpm: Текущий темп.

        Returns:
            Beat следующей мутации.
        """
        seconds = self._rng.uniform(self._min_seconds, self._max_seconds)
        beats = seconds * bpm / 60.0
        return from_beat + beats

    # ------------------------------------------------------------------
    # Freeze / Evolve
    # ------------------------------------------------------------------

    def freeze_all(self) -> None:
        """Заморозить мутацию на всех зарегистрированных дорожках."""
        for name, state in self._states.items():
            self._states[name] = MutationState(
                mutate=0.0,
                mutation_count=state.mutation_count,
                next_mutation_beat=state.next_mutation_beat,
                last_mutation_beat=state.last_mutation_beat,
            )
        log.info("MutationEngine: all frozen")

    def evolve_all(self) -> None:
        """Возобновить мутацию на всех зарегистрированных дорожках."""
        for name, state in self._states.items():
            self._states[name] = MutationState(
                mutate=self._default_mutate,
                mutation_count=state.mutation_count,
                next_mutation_beat=state.next_mutation_beat,
                last_mutation_beat=state.last_mutation_beat,
            )
        log.info("MutationEngine: all evolved")

    # ------------------------------------------------------------------
    # Доступ
    # ------------------------------------------------------------------

    def get_state(self, track_name: str) -> MutationState | None:
        """Состояние мутации конкретной дорожки."""
        return self._states.get(track_name)

    def sync_mutate(self, track_name: str, value: float) -> None:
        """Подтянуть mutate из источника истины (``track.mutate``).

        Вызывается перед каждым tick: ``MelodicTrack.freeze()`` и
        ``AppEngineControl.set_track_mutate`` меняют только трек, а
        ``MutationEngine`` хранит собственную копию в ``MutationState``.
        Без синхронизации заморозка не доходит до движка (§4.1).
        No-op, если значение уже совпадает.
        """
        state = self._states.get(track_name)
        if state is None or state.mutate == value:
            return
        self._states[track_name] = MutationState(
            mutate=value,
            mutation_count=state.mutation_count,
            next_mutation_beat=state.next_mutation_beat,
            last_mutation_beat=state.last_mutation_beat,
        )

    def set_mutate(self, track_name: str, value: float) -> None:
        """Установить mutate для конкретной дорожки.

        Аргументы:
            track_name: Имя дорожки.
            value: Новое значение 0.0–1.0.
        """
        if track_name not in self._states:
            return
        state = self._states[track_name]
        self._states[track_name] = MutationState(
            mutate=value,
            mutation_count=state.mutation_count,
            next_mutation_beat=state.next_mutation_beat,
            last_mutation_beat=state.last_mutation_beat,
        )

    @property
    def total_mutation_count(self) -> int:
        """Суммарное количество мутаций (для дисплея)."""
        return sum(s.mutation_count for s in self._states.values())

    @property
    def registered_tracks(self) -> list[str]:
        """Имена всех зарегистрированных дорожек."""
        return list(self._states.keys())

    # ------------------------------------------------------------------
    # Доступ к механизмам (для MelodicEngine)
    # ------------------------------------------------------------------

    def get_note_drift(self, track_name: str) -> NoteDrift | None:
        """NoteDrift для дорожки или None."""
        return self._note_drifts.get(track_name)

    def get_euclidean_drift(self, track_name: str) -> FloatingEuclidean | None:
        """FloatingEuclidean для дорожки или None."""
        return self._euclidean_drifts.get(track_name)

    def get_param_drift(self, track_name: str) -> ParamDrift | None:
        """ParamDrift для дорожки или None."""
        return self._param_drifts.get(track_name)

    def __repr__(self) -> str:
        return (
            f"MutationEngine(tracks={len(self._states)}, "
            f"total_mutations={self.total_mutation_count})"
        )
