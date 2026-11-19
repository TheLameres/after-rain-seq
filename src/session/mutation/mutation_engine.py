"""Координатор мутации для мелодических и drum-дорожек сессии.

Мутация **только ручная** (spec «ручная мутация и линейная история»):
автономного таймера нет, паттерн меняется по явному действию — кнопка
``NEW`` на Push 2 или команда ``evolve`` в REPL.

На каждом тике:
1. Разобрать очередь запросов (``request_mutation``) в ``pending``
2. Для каждой дорожки с ожидающей мутацией: дождаться границы цикла
   (``_cycle_index``) и применить шаг механизма по профилю
   (таблица ``PROFILE_MECHANISM``; у drum — шаг по лейнам)
3. Запушить новую версию в линейную историю (:class:`VersionHistory`),
   синхронизировать счётчик с курсором и снять ``pending`` дорожки

История линейная: ``undo``/``recall`` восстанавливают снимок в объекты
дрейфа, мутация из середины отрезает будущее. Механизмы оперируют beats;
границы циклов дорожки не зависят от BPM.
"""

from __future__ import annotations

import logging
import math
import random
from collections import deque
from collections.abc import Sequence

from src.session.model.drum_track import DrumTrack
from src.session.model.track import Track
from src.session.model.version_history import VersionHistory
from src.session.mutation.drift_tables import (
    MECH_EUCLIDEAN,
    MECH_NOTE,
    MECH_PARAM,
    PARAM_DRIFT_PARAMS,
    PROFILE_MECHANISM,
)
from src.session.mutation.floating_euclidean import FloatingEuclidean
from src.session.mutation.mutation_state import MutationState
from src.session.mutation.note_drift import NoteDrift
from src.session.mutation.param_drift import ParamDrift
from src.session.mutation.track_version import DrumVersion, MelodicVersion

log = logging.getLogger(__name__)


def _cycle_index(beat: float, cycle_beats: float) -> int:
    return math.floor(beat / cycle_beats + 1e-9)


class MutationEngine:
    """Координатор мутации для дорожек сессии + линейная история версий.

    Механизм выбирается по профилю:
        lead, texture    → NoteDrift
        seq, arp, stab   → FloatingEuclidean
        pad, atmos, bass → ParamDrift
        cc_*             → пропуск (нет нот)
    Drum-дорожки регистрируются отдельно (:meth:`register_drum_track`):
    шаг мутации — 1–2 изменения по лейнам, граница цикла — ``steps / 4``.
    """

    def __init__(
        self,
        rng: random.Random | None = None,
    ) -> None:
        self._rng: random.Random = rng if rng is not None else random.Random()

        self._note_drifts: dict[str, NoteDrift] = {}
        self._euclidean_drifts: dict[str, FloatingEuclidean] = {}
        self._param_drifts: dict[str, ParamDrift] = {}
        self._states: dict[str, MutationState] = {}
        self._track_profiles: dict[str, str] = {}
        # §4.4: дорожки-владельцы счётчика (пишем в них, читаем из них).
        self._track_refs: dict[str, object] = {}
        # B1: ревизия трека, с которой механизм синхронизирован, и параметры
        # регистрации (для пересоздания механизма при смене профиля).
        self._track_revision: dict[str, int] = {}
        self._reg_params: dict[str, dict[str, float | int]] = {}
        # Линейная история версий (spec §6): корень — снимок при регистрации.
        self._histories: dict[str, VersionHistory[MelodicVersion | DrumVersion]] = {}
        # Drum-дорожки: шаг мутации делегируется самой дорожке.
        self._drum_tracks: dict[str, DrumTrack] = {}
        self._requests: deque[tuple[str, float]] = deque()
        self._pending: dict[str, float] = {}
        self._prev_beat: float | None = None

    # ------------------------------------------------------------------
    # Регистрация
    # ------------------------------------------------------------------

    def register_track(
        self,
        track_name: str,
        profile_name: str,
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
            degrees: Базовые ступени (для NoteDrift).
            scale_length: Длина лада (для NoteDrift).
            euclidean_steps: Шаги сетки (для FloatingEuclidean).
            euclidean_pulses: Базовые pulses (для FloatingEuclidean).
            gate: Базовый gate (для ParamDrift).
            density: Базовая density (для ParamDrift).
            register: Базовый register (для ParamDrift).
            track: Дорожка-владелец счётчика (§4.4); движок пишет в неё.
        """
        if track is not None:
            self._track_refs[track_name] = track
        self._track_profiles[track_name] = profile_name

        self._reg_params[track_name] = {
            "scale_length": scale_length,
            "euclidean_steps": euclidean_steps,
            "euclidean_pulses": euclidean_pulses,
            "gate": gate,
        }
        self._track_revision[track_name] = int(getattr(track, "revision", 0))
        self._build_mechanism(track_name, profile_name, degrees, gate)

        # Инициализируем состояние (мутация ручная, расписания нет)
        self._states[track_name] = MutationState(
            mutation_count=0,
            last_mutation_beat=0.0,
        )
        # Корень истории — снимок состояния при регистрации (spec §6).
        self._histories[track_name] = VersionHistory(self._snapshot_melodic(track_name))
        log.debug("MutationEngine: зарегистрирован %s (%s)", track_name, profile_name)

    def register_drum_track(
        self,
        track_name: str,
        track: DrumTrack | None = None,
    ) -> None:
        """Зарегистрировать drum-дорожку для ручной мутации.

        Шаг мутации — ``DrumTrack._apply_mutation`` (1–2 изменения по лейнам);
        граница цикла вычисляется фасадом как ``steps / 4`` битов.

        Аргументы:
            track_name: Имя дорожки.
            track: Дорожка-владелец счётчика и паттернов.
        """
        if track is not None:
            self._track_refs[track_name] = track
            self._drum_tracks[track_name] = track
        self._track_profiles[track_name] = "drum"
        self._states[track_name] = MutationState(
            mutation_count=0,
            last_mutation_beat=0.0,
        )
        root = DrumVersion(lanes=track.snapshot() if track is not None else ())
        self._histories[track_name] = VersionHistory(root)
        log.debug("MutationEngine: зарегистрирован drum %s", track_name)

    def _build_mechanism(
        self,
        track_name: str,
        profile_name: str,
        degrees: Sequence[int] | None,
        gate: float,
    ) -> None:
        """Создать механизм мутации по профилю (таблица PROFILE_MECHANISM, C6)."""
        params = self._reg_params[track_name]
        mechanism = PROFILE_MECHANISM.get(profile_name)
        if mechanism == MECH_NOTE:
            base = list(degrees) if degrees is not None else [0, 2, 4, 2]
            self._note_drifts[track_name] = NoteDrift(base, int(params["scale_length"]))
        elif mechanism == MECH_EUCLIDEAN:
            self._euclidean_drifts[track_name] = FloatingEuclidean(
                int(params["euclidean_steps"]), int(params["euclidean_pulses"])
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

    def _drop_mechanisms(self, track_name: str) -> None:
        """Удалить все механизмы дорожки (состояние ``MutationState`` не трогаем)."""
        self._note_drifts.pop(track_name, None)
        self._euclidean_drifts.pop(track_name, None)
        self._param_drifts.pop(track_name, None)

    def refresh_track(
        self,
        track_name: str,
        degrees: Sequence[int] | None = None,
        profile_name: str | None = None,
    ) -> None:
        """Подтянуть механизм дорожки к текущему состоянию трека (B1).

        Трек — источник истины: движок читает ``track.revision`` и при
        расхождении вызывает этот метод.

        - Профиль изменился → механизм пересоздаётся по **новому** профилю
          (закрывает Д7: после ``set_profile("pad")`` NoteDrift заменяется
          на ParamDrift). Накопленный дрейф при этом теряется осознанно,
          счётчики мутаций (трек и ``MutationState``) обнуляются, в лог — ``info``.
        - Профиль тот же, механизм NoteDrift и ``degrees`` отличаются от базы →
          ``NoteDrift.set_base`` (закрывает Д6); счётчик мутаций сохраняется.

        Аргументы:
            track_name: Имя дорожки (должна быть зарегистрирована).
            degrees: Текущая прогрессия; None — взять из ``track.degrees``.
            profile_name: Текущий профиль; None — взять из ``track.profile_name``.
        """
        if track_name not in self._states:
            return
        track = self._track_refs.get(track_name)
        if degrees is None and track is not None:
            degrees = getattr(track, "degrees", None)
        if profile_name is None:
            profile_name = getattr(
                track, "profile_name", None
            ) or self._track_profiles.get(track_name, "")
        if track is not None:
            self._track_revision[track_name] = int(getattr(track, "revision", 0))

        old_profile = self._track_profiles.get(track_name)
        if profile_name != old_profile:
            log.info(
                "MutationEngine: %s профиль %s -> %s, механизм пересоздан",
                track_name,
                old_profile,
                profile_name,
            )
            self._track_profiles[track_name] = profile_name
            self._drop_mechanisms(track_name)
            gate = float(getattr(track, "gate", self._reg_params[track_name]["gate"]))
            self._build_mechanism(track_name, profile_name, degrees, gate)
            # Сброс счётчиков при смене профиля — осознанный (§9): накопленный
            # дрейф относился к другому механизму.
            reset = getattr(track, "reset_mutation_count", None)
            if callable(reset):
                reset()
            state = self._states[track_name]
            self._states[track_name] = MutationState(
                mutation_count=0,
                last_mutation_beat=state.last_mutation_beat,
            )
            # История начинается заново: накопленный дрейф относился к другому
            # механизму; корень — снимок нового механизма (spec §6).
            self._histories[track_name] = VersionHistory(
                self._snapshot_melodic(track_name)
            )
            return

        # Правка degrees: пользовательская прогрессия — новая истина.
        drift = self._note_drifts.get(track_name)
        if (
            drift is not None
            and degrees is not None
            and list(degrees) != drift.base_degrees
        ):
            drift.set_base(degrees)
            # История и счётчик начинаются заново от новой базы (spec §7:
            # mutation_count = номер версии от корня; старые версии относятся
            # к другой базе и невосстановимы).
            self._reset_history(track_name)

    def _sync_revisions(self) -> None:
        """Ресинк механизмов с треками по ``revision`` (int-сравнение на дорожку)."""
        for name, track in self._track_refs.items():
            rev = getattr(track, "revision", None)
            if rev is not None and rev != self._track_revision.get(name):
                self.refresh_track(name)

    def unregister_track(self, track_name: str) -> None:
        """Удалить дорожку из мутации (при удалении из сессии).

        Аргументы:
            track_name: Имя дорожки.
        """
        self._track_refs.pop(track_name, None)
        self._track_revision.pop(track_name, None)
        self._reg_params.pop(track_name, None)
        self._drop_mechanisms(track_name)
        self._states.pop(track_name, None)
        self._track_profiles.pop(track_name, None)
        self._histories.pop(track_name, None)
        self._drum_tracks.pop(track_name, None)

    # ------------------------------------------------------------------
    # Тик
    # ------------------------------------------------------------------

    def tick(self, current_beat: float) -> list[str]:
        """Один тик мутации: применить ожидающие запросы на границах циклов.

        Аргументы:
            current_beat: Текущая позиция в тактах.

        Returns:
            Имена дорожек, которые мутировали на этом тике.
        """
        self._sync_revisions()
        return self._apply_requested(current_beat)

    def _apply_mutation(self, track_name: str) -> bool:
        """Применить мутацию к дорожке через её механизм.

        Returns:
            True, если состояние дорожки действительно изменилось (§4.4).
        """
        if track_name in self._drum_tracks:
            track = self._drum_tracks[track_name]
            before = track.snapshot()
            track._apply_mutation()
            return track.snapshot() != before
        if track_name in self._note_drifts:
            return bool(self._note_drifts[track_name].drift_one(self._rng))
        if track_name in self._euclidean_drifts:
            return bool(self._euclidean_drifts[track_name].drift(self._rng))
        if track_name in self._param_drifts:
            return self._param_drifts[track_name].drift_one(self._rng) is not None
        return False

    def restart(self) -> None:
        """Перезапуск транспорта с нуля (внешний Start).

        Счётчики, механизмы и ожидающие запросы сохраняются (spec §4c:
        pending переживает stop/start и применяется на первой границе
        цикла после запуска). Водяной знак границы сбрасывается.
        """
        self._prev_beat = None
        for name, state in self._states.items():
            self._states[name] = MutationState(
                mutation_count=state.mutation_count,
                last_mutation_beat=0.0,
            )

    # ------------------------------------------------------------------
    # Доступ
    # ------------------------------------------------------------------

    def request_mutation(self, track_name: str, cycle_beats: float) -> None:
        self._requests.append((track_name, cycle_beats))

    def _apply_requested(self, current_beat: float) -> list[str]:
        prev = self._prev_beat
        self._prev_beat = current_beat
        while self._requests:
            name, cycle_beats = self._requests.popleft()
            if name in self._states:
                self._pending[name] = cycle_beats
        applied: list[str] = []
        for name, cycle_beats in list(self._pending.items()):
            if name not in self._states:
                del self._pending[name]
                continue
            if prev is None or _cycle_index(current_beat, cycle_beats) <= _cycle_index(
                prev, cycle_beats
            ):
                continue
            del self._pending[name]
            self._commit_manual(name, current_beat)
            applied.append(name)
        return applied

    def _commit_manual(self, track_name: str, beat: float) -> None:
        changed = self._apply_mutation(track_name)
        if changed:
            # Снимок головы → мутация → новая версия (spec §5.2a): состояние
            # до шага уже лежит в истории предыдущей версией.
            history = self._histories.get(track_name)
            if history is not None:
                if track_name in self._drum_tracks:
                    version: MelodicVersion | DrumVersion = DrumVersion(
                        lanes=self._drum_tracks[track_name].snapshot()
                    )
                else:
                    version = self._snapshot_melodic(track_name)
                history.push(version)
                self._sync_counter(track_name, history.cursor)
        state = self._states[track_name]
        self._states[track_name] = MutationState(
            mutation_count=state.mutation_count,
            last_mutation_beat=beat,
        )
        # Мигание снимается в момент применения (spec §4a/§5.2b).
        track = self._track_refs.get(track_name)
        if isinstance(track, Track) and track.pending:
            track.pending = False
        log.debug("MutationEngine: %s ручная мутация на beat %.3f", track_name, beat)

    # ------------------------------------------------------------------
    # История версий (spec §6–§8)
    # ------------------------------------------------------------------

    def _snapshot_melodic(self, track_name: str) -> MelodicVersion:
        """Полный снимок механизмов мелодической дорожки."""
        return MelodicVersion(
            degrees=(
                self._note_drifts[track_name].snapshot()
                if track_name in self._note_drifts
                else None
            ),
            pulses=(
                self._euclidean_drifts[track_name].snapshot()
                if track_name in self._euclidean_drifts
                else None
            ),
            params=(
                self._param_drifts[track_name].snapshot()
                if track_name in self._param_drifts
                else None
            ),
        )

    def _restore_version(
        self, track_name: str, version: MelodicVersion | DrumVersion
    ) -> None:
        """Восстановить снимок в объекты дрейфа / паттерны лейнов (spec §6)."""
        if isinstance(version, DrumVersion):
            track = self._drum_tracks.get(track_name)
            if track is None:
                raise ValueError(f"drum track {track_name!r} is not registered")
            track.restore(version.lanes)
            return
        if version.degrees is not None:
            drift = self._note_drifts.get(track_name)
            if drift is None:
                raise ValueError(f"NoteDrift missing for {track_name!r}")
            drift.restore(version.degrees)
        if version.pulses is not None:
            euclid = self._euclidean_drifts.get(track_name)
            if euclid is None:
                raise ValueError(f"FloatingEuclidean missing for {track_name!r}")
            euclid.restore(version.pulses)
        if version.params is not None:
            params = self._param_drifts.get(track_name)
            if params is None:
                raise ValueError(f"ParamDrift missing for {track_name!r}")
            params.restore(version.params)

    def _sync_counter(self, track_name: str, cursor: int) -> None:
        """Счётчик мутаций = номер версии от корня (spec §7): движок + дорожка."""
        state = self._states.get(track_name)
        if state is None:
            return
        old = state.mutation_count
        self._states[track_name] = MutationState(
            mutation_count=cursor,
            last_mutation_beat=state.last_mutation_beat,
        )
        track = self._track_refs.get(track_name)
        recorder = getattr(track, "record_mutation", None)
        if cursor != old and callable(recorder):
            recorder(cursor - old)

    def _reset_history(self, track_name: str) -> None:
        """Начать историю заново: корень — текущий снимок, счётчик в 0."""
        state = self._states.get(track_name)
        if state is None:
            return
        if track_name in self._drum_tracks:
            root: MelodicVersion | DrumVersion = DrumVersion(
                lanes=self._drum_tracks[track_name].snapshot()
            )
        else:
            root = self._snapshot_melodic(track_name)
        self._histories[track_name] = VersionHistory(root)
        self._states[track_name] = MutationState(
            mutation_count=0,
            last_mutation_beat=state.last_mutation_beat,
        )
        track = self._track_refs.get(track_name)
        reset = getattr(track, "reset_mutation_count", None)
        if callable(reset):
            reset()

    def record_manual_version(self, track_name: str) -> bool:
        """Записать ручную правку дорожки как новую версию (design §7).

        Снимок состояния **после** правки (состояние до правки уже лежит
        в истории предыдущей версией) → ``history.push()`` →
        ``_sync_counter()`` — без шага дрейфа, в отличие от
        ``_commit_manual``. Дедупликация: перед push снимок сравнивается
        с головой истории (``history.current``); совпадение — версия не
        создаётся («без изменений»). Возврат к старому паттерну после
        промежуточных правок честно создаёт новую версию: сравнение
        только с головой, не со всей историей.

        Аргументы:
            track_name: Имя дорожки.

        Returns:
            ``True`` — новая версия записана в историю.
            ``False`` — версия не записана: дорожка не зарегистрирована
            или снимок совпал с головой истории (дедупликация).
        """
        history = self._histories.get(track_name)
        if history is None:
            return False
        if track_name in self._drum_tracks:
            version: MelodicVersion | DrumVersion = DrumVersion(
                lanes=self._drum_tracks[track_name].snapshot()
            )
        else:
            version = self._snapshot_melodic(track_name)
        if version == history.current:
            log.debug(
                "MutationEngine: %s ручная правка без изменений (дубль головы)",
                track_name,
            )
            return False
        history.push(version)
        self._sync_counter(track_name, history.cursor)
        log.debug("MutationEngine: %s записана ручная версия", track_name)
        return True

    def undo(self, track_name: str) -> bool:
        """Откатить дорожку на одну версию (spec §4c, §8).

        Восстанавливает снимок предыдущей версии в объекты дрейфа.
        На корне или для незарегистрированной дорожки — отказ (``False``),
        состояние не меняется.
        """
        history = self._histories.get(track_name)
        if history is None or not history.undo():
            return False
        self._restore_version(track_name, history.current)
        self._sync_counter(track_name, history.cursor)
        return True

    def recall(self, track_name: str, index: int) -> bool:
        """Перейти на версию ``index`` (spec §4: нажатие пада сетки).

        Несуществующий номер — отказ (``False``). Будущее не отрезается:
        его отрежет следующая мутация (spec §6).
        """
        history = self._histories.get(track_name)
        if history is None or not history.recall(index):
            return False
        self._restore_version(track_name, history.current)
        self._sync_counter(track_name, history.cursor)
        return True

    def history_len(self, track_name: str) -> int:
        """Число версий в истории дорожки (0 — не зарегистрирована)."""
        history = self._histories.get(track_name)
        return len(history) if history is not None else 0

    def current_version(self, track_name: str) -> int:
        """Индекс текущей версии (курсор истории); -1 — не зарегистрирована."""
        history = self._histories.get(track_name)
        return history.cursor if history is not None else -1

    def get_state(self, track_name: str) -> MutationState | None:
        """Состояние мутации конкретной дорожки."""
        return self._states.get(track_name)

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
