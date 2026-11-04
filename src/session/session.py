"""Сессия — контейнер дорожек, граф, API создания/удаления/связывания.

Единая точка входа для движка и UI. Владеет дорожками и графом,
обеспечивает лимиты, автогенерацию имён, стратегию B при удалении
источника (зависимые получают ``sources = ()`` и молчат).
"""

from __future__ import annotations

import logging

from src.devices.push2.palette import TRACK_PAD_INDICES
from src.session.graph.track_graph import TrackGraph
from src.session.model.drum_track import DrumTrack
from src.session.model.melodic_profile import PROFILES
from src.session.model.melodic_track import MelodicTrack
from src.session.model.track import Track

log = logging.getLogger(__name__)


class Session:
    """Сессия — набор дорожек и граф их зависимостей.

    Лимиты:
        - Всего дорожек: 16.
        - Drum-машин: ≤ 2.
        - Источников на дорожку: ≤ 2.

    Имена автогенерируются по профилю: ``"Pad 1"``, ``"Sub 2"``,
    ``"Drum 1"``. Пользовательское переименование не требуется.
    """

    MAX_TRACKS: int = 16
    MAX_DRUM_TRACKS: int = 2
    MAX_SOURCES: int = 2

    def __init__(self) -> None:
        self._tracks: dict[str, Track] = {}
        self._graph = TrackGraph()
        self._counters: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Создание дорожек
    # ------------------------------------------------------------------

    def create_melodic_track(
        self,
        profile: str = "pad",
        channel: int | None = None,
        port: str | None = None,
        **kwargs: object,
    ) -> MelodicTrack:
        """Создать мелодическую дорожку.

        Аргументы:
            profile: Имя профиля из ``PROFILES``.
            channel: MIDI-канал 0..15; ``None`` — взять первый свободный
                (канал 9/ch10 резервируется под drum, чтобы мелодика не
                слипалась с ударными на одном порту).
            port: Имя MIDI-порта или ``None``.
            **kwargs: Дополнительные параметры для ``MelodicTrack``.

        Returns:
            Созданная дорожка.

        Raises:
            ValueError: При неизвестном профиле, превышении лимита,
                занятости всех каналов или канале вне 0..15.
        """
        self._check_limit()
        if profile not in PROFILES:
            raise ValueError(f"Неизвестный профиль: {profile!r}")
        if channel is None:
            channel = self._alloc_channel()
        elif not 0 <= channel <= 15:
            raise ValueError(f"MIDI-канал вне диапазона 0..15: {channel}")
        name = self._next_name(profile)
        track = MelodicTrack(
            name=name,
            profile_name=profile,
            channel=channel,
            port=port,
            color_slot=self._alloc_color_slot(),
            **kwargs,  # type: ignore[arg-type]
        )
        self._tracks[name] = track
        self._graph.add_track(name)
        log.debug("Session: создан %s", track)
        return track

    def _alloc_color_slot(self) -> int | None:
        """Первый свободный слот цвета (§4.8).

        Слот — свойство дорожки, а не её позиция в списке: занятые слоты
        соседей не переезжают при удалении. Освободившийся слот достаётся
        следующей созданной дорожке, поэтому цвета не «уползают».

        Returns:
            Индекс 0..15 (позиция в ``TRACK_PAD_INDICES``) либо ``None``,
            когда все слоты заняты (дорожек больше, чем цветов).
        """
        used = {t.color_slot for t in self._tracks.values() if t.color_slot is not None}
        for slot in range(len(TRACK_PAD_INDICES)):
            if slot not in used:
                return slot
        return None

    def _alloc_channel(self) -> int:
        """Первый свободный MIDI-канал, не занятый ни одной дорожкой.

        Канал 9 (ch10) пропускается — под него живут drum-дорожки; без
        этого мелодика и ударные на одном порту слипались бы в один канал.

        Returns:
            Номер канала 0..15.

        Raises:
            ValueError: Все каналы заняты.
        """
        used = {t.channel for t in self._tracks.values()}
        for ch in range(16):
            if ch == 9:
                continue
            if ch not in used:
                return ch
        raise ValueError("нет свободных MIDI-каналов (0..15)")

    def create_drum_track(
        self,
        channel: int = 9,
        port: str | None = None,
        steps: int = 16,
    ) -> DrumTrack:
        """Создать drum-дорожку.

        Аргументы:
            channel: MIDI-канал 0..15 (по умолчанию 9 = ch10).
            port: Имя MIDI-порта или ``None``.
            steps: Размер сетки (16/32/48/64).

        Returns:
            Созданная drum-дорожка.

        Raises:
            ValueError: При превышении лимита дорожек или drum-машин.
        """
        self._check_limit()
        drum_count = sum(1 for t in self._tracks.values() if isinstance(t, DrumTrack))
        if drum_count >= self.MAX_DRUM_TRACKS:
            raise ValueError(f"Лимит drum-машин: {self.MAX_DRUM_TRACKS}")
        name = self._next_name("drum")
        track = DrumTrack(
            name=name,
            channel=channel,
            port=port,
            steps=steps,
            color_slot=self._alloc_color_slot(),
        )
        self._tracks[name] = track
        self._graph.add_track(name)
        log.debug("Session: создан %s", track)
        return track

    # ------------------------------------------------------------------
    # Удаление дорожек
    # ------------------------------------------------------------------

    def remove_track(self, name: str) -> None:
        """Удалить дорожку. Стратегия B для зависимых.

        Дорожки, которые читают удаляемую, получают ``sources = ()``
        и молчат (не падают, не теряют настройки).

        Аргументы:
            name: Имя дорожки.

        Raises:
            ValueError: Если дорожки нет.
        """
        if name not in self._tracks:
            raise ValueError(f"Дорожка {name!r} не найдена")

        dependents = self._graph.dependents_of(name)
        for dep_name in dependents:
            dep = self._tracks[dep_name]
            dep.sources = ()
            self._graph.set_sources(dep_name, ())

        del self._tracks[name]
        self._graph.remove_track(name)
        log.debug("Session: удалена %r, зависимых сброшено: %d", name, len(dependents))

    # ------------------------------------------------------------------
    # Связывание
    # ------------------------------------------------------------------

    def set_sources(self, track_name: str, *sources: str) -> None:
        """Назначить источники дорожке.

        Аргументы:
            track_name: Имя дорожки-наследника.
            *sources: Имена источников (максимум 2).

        Raises:
            ValueError: При превышении лимита, несуществующей дорожке
                или цикле в графе.
        """
        if len(sources) > self.MAX_SOURCES:
            raise ValueError(f"Максимум источников: {self.MAX_SOURCES}")
        track = self.get_track(track_name)
        if track is None:
            raise ValueError(f"Дорожка {track_name!r} не найдена")
        for src in sources:
            if self.get_track(src) is None:
                raise ValueError(f"Источник {src!r} не найден")

        # DrumTrack отклоняет в своём сеттере; проверяем явно для ясности.
        if isinstance(track, DrumTrack) and sources:
            raise ValueError("Drum-трек не участвует в графе гармонии")

        self._graph.set_sources(track_name, tuple(sources))
        track.sources = tuple(sources)
        log.debug("Session: %s.sources = %s", track_name, sources)

    # ------------------------------------------------------------------
    # Доступ
    # ------------------------------------------------------------------

    def get_track(self, name: str) -> Track | None:
        """Получить дорожку по имени или ``None``."""
        return self._tracks.get(name)

    def track_names(self) -> list[str]:
        """Имена всех дорожек в порядке добавления."""
        return list(self._tracks.keys())

    def ordered_tracks(self) -> list[Track]:
        """Дорожки в топологическом порядке (источники перед наследниками).

        Returns:
            Список дорожек для последовательной генерации.

        Raises:
            ValueError: При цикле в графе.
        """
        order = self._graph.topological_order()
        return [self._tracks[name] for name in order]

    @property
    def track_count(self) -> int:
        """Количество дорожек в сессии."""
        return len(self._tracks)

    # ------------------------------------------------------------------
    # Распространение гармонии (C6, шаг 3)
    # ------------------------------------------------------------------

    def propagate_chords(self) -> None:
        """Фаза графа: источники публикуют ChordEvent, наследники получают.

        Один проход в два шага (топологический порядок — источники раньше
        наследников):

        1. ``generate()`` всех мелодических дорожек — источники
           (``emits_chords``) наполняют свой outbox, outbox наследников
           очищается.
        2. ``inject_sources()`` — наследники (``reads_source``) получают
           ChordEvent своих источников в outbox.

        Движки (MelodicEngine) читают outbox дорожки как окно аккордов
        (``ctx.chord_window``). DrumTrack в графе не участвуют.

        Идемпотентна: каждый вызов пересобирает outbox с нуля — повторный
        вызов на том же тике не дублирует события.
        """
        melodic = [t for t in self.ordered_tracks() if isinstance(t, MelodicTrack)]
        for track in melodic:
            track.generate()
        for track in melodic:
            if not track.profile.reads_source or not track.sources:
                continue
            sources: list[Track] = []
            for name in track.sources:
                src = self._tracks.get(name)
                if src is not None and isinstance(src, MelodicTrack):
                    sources.append(src)
            track.inject_sources(sources)
        log.debug("Session: propagate_chords (%d melodic)", len(melodic))

    # ------------------------------------------------------------------
    # Freeze / Evolve
    # ------------------------------------------------------------------

    def freeze_all(self) -> None:
        """Заморозить мутацию на всех дорожках.

        Устанавливает ``mutate = 0`` на всех DrumTrack и MelodicTrack.
        Вызывает ``freeze()`` на каждой DrumTrack (сохраняет базовый паттерн).
        """
        for track in self._tracks.values():
            if isinstance(track, DrumTrack):
                track.freeze()
                track.mutate = 0.0
            elif isinstance(track, MelodicTrack):
                track.freeze()
        log.info("Session: all tracks frozen")

    def evolve_all(self, default_mutate: float = 0.5) -> None:
        """Возобновить мутацию на всех дорожках.

        Аргументы:
            default_mutate: Значение mutate для мелодических дорожек.
        """
        for track in self._tracks.values():
            if isinstance(track, DrumTrack):
                track.mutate = 0.5
            elif isinstance(track, MelodicTrack):
                track.mutate = default_mutate
        log.info("Session: all tracks evolved")

    @property
    def total_mutation_count(self) -> int:
        """Суммарное количество мутаций всех дорожек (для дисплея)."""
        total = 0
        for track in self._tracks.values():
            if isinstance(track, (DrumTrack, MelodicTrack)):
                total += track.mutation_count
        return total

    # ------------------------------------------------------------------
    # Внутренние хелперы
    # ------------------------------------------------------------------

    def _check_limit(self) -> None:
        """Проверить общий лимит дорожек."""
        if len(self._tracks) >= self.MAX_TRACKS:
            raise ValueError(f"Лимит дорожек: {self.MAX_TRACKS}")

    def _next_name(self, profile: str) -> str:
        """Автогенерация имени: ``"Pad 1"``, ``"Sub 2"``, ``"Drum 1"``."""
        self._counters[profile] = self._counters.get(profile, 0) + 1
        prefix = profile.capitalize()
        return f"{prefix} {self._counters[profile]}"
