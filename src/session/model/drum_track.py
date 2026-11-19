"""Drum-машина — 16 лейнов, GM 36–51, вне графа гармонии.

Drum не читает и не публикует гармонию: ``sources`` заблокирован.
Попытка назначить источник — отказ с сообщением. Правила из плана 4.2:
абсолютные ноты (не ``degree``), смена Root/Scale не влияет, gate
one-shot, три уровня velocity силой нажатия пада. Мутация — только
по явному действию (NEW/``evolve``), на границе цикла; автономного
таймера нет.
"""

from __future__ import annotations

import logging
import random

from src.session.events.drum_event import DrumEvent
from src.session.model.drum_lane import DrumLane
from src.session.model.track import Track

log = logging.getLogger(__name__)

# Три уровня velocity (план 4.2, TR-808).
VELOCITY_GHOST: tuple[int, int] = (40, 55)
VELOCITY_NORMAL: tuple[int, int] = (90, 100)
VELOCITY_ACCENT: tuple[int, int] = (120, 127)

# Длительность one-shot удара в долях (1/16 = 0.25).
DEFAULT_GATE: float = 0.25

# Стандартная GM-карта для 16 лейнов (note, имя).
GM_DRUM_MAP: tuple[tuple[int, str], ...] = (
    (36, "Kick"),
    (37, "Rimshot"),
    (38, "Snare"),
    (39, "HandClap"),
    (40, "Snare2"),
    (41, "LowTom"),
    (42, "ClosedHat"),
    (43, "MidTom"),
    (44, "OpenHat"),
    (45, "HighTom"),
    (46, "Crash"),
    (47, "Ride"),
    (48, "Cowbell"),
    (49, "Shaker"),
    (50, "Tambourine"),
    (51, "Conga"),
)


class DrumTrack(Track):
    """Drum-дорожка с 16 лейнами.

    Атрибуты:
        lanes: Ровно 16 лейнов, GM 36–51.
        steps: Общая сетка (16/32/48/64), одна на все лейны.
        accent_level: Velocity акцента (по умолчанию 127).
        square: Активный квадрат сетки (4 столбца пада).

    ``sources`` всегда пустой tuple, попытка назначить — ValueError.
    """

    def __init__(
        self,
        name: str,
        channel: int = 9,
        port: str | None = None,
        steps: int = 16,
        color_slot: int | None = None,
    ) -> None:
        super().__init__(name=name, channel=channel, port=port, color_slot=color_slot)
        self.lanes: list[DrumLane] = [
            DrumLane(note=note, name=lname) for note, lname in GM_DRUM_MAP
        ]
        self.steps: int = steps
        # Расширяем паттерны lane до steps (если steps > 16).
        for lane in self.lanes:
            lane.ensure_length(steps)
        self.accent_level: int = 127
        self.square: int = 1

        # Мутация: ГПСЧ шага (применение — только по явному запросу,
        # см. MutationEngine / ручная мутация).
        self._rng = random.Random()

    # ------------------------------------------------------------------
    # Блокировка sources
    # ------------------------------------------------------------------

    @property
    def accepts_sources(self) -> bool:
        """Drum не участвует в графе — источники запрещены (§4.7)."""
        return False

    # ------------------------------------------------------------------
    # Генерация
    # ------------------------------------------------------------------

    def generate(self) -> list[DrumEvent]:
        """Сгенерировать drum-события по сетке.

        Для каждого не-muted lane: паттерн 0/1/2 → velocity-уровень.
        0 = пауза (событие не создаётся), 1 = normal, 2 = accent.

        Returns:
            Список DrumEvent, отсортированных по beat.
        """
        self.outbox.clear()
        events: list[DrumEvent] = []

        for lane_idx, lane in enumerate(self.lanes):
            if lane.muted:
                continue
            lane_events = self._generate_lane(lane_idx, lane)
            events.extend(lane_events)

        events.sort(key=lambda e: e.beat)
        # §4.5: outbox типизирован как ChordEvent | DrumEvent — публикуем
        # свои события, иначе current()/history() у drum-дорожки всегда пусты.
        self.outbox.extend(events)
        return events

    def _generate_lane(self, lane_idx: int, lane: DrumLane) -> list[DrumEvent]:
        """Сгенерировать события для одного лейна.

        Аргументы:
            lane_idx: Индекс лейна 0–15.
            lane: Объект DrumLane.

        Returns:
            Список DrumEvent для этого лейна.
        """
        events: list[DrumEvent] = []
        pattern = lane.pattern
        pattern_len = len(pattern)
        # Фиксированная 16-я (design §9): 0.25 бита всегда, независимо от
        # steps; цикл паттерна — steps/4 битов (как в MutationEngine).
        step_duration = 0.25

        for step in range(self.steps):
            cell = pattern[step % pattern_len]
            if cell == 0:
                continue  # пауза — событие не создаётся

            velocity = self._velocity_for_cell(cell)
            beat = step * step_duration
            events.append(
                DrumEvent(
                    beat=beat,
                    note=lane.note,
                    velocity=velocity,
                    lane_index=lane_idx,
                    duration=DEFAULT_GATE,
                )
            )
        return events

    def _velocity_for_cell(self, cell: int) -> int:
        """Преобразовать значение ячейки (1/2) в конкретную velocity.

        Аргументы:
            cell: 1 = normal, 2 = accent.

        Returns:
            Velocity из соответствующего диапазона.
        """
        if cell == 2:
            lo, hi = VELOCITY_ACCENT
        else:
            lo, hi = VELOCITY_NORMAL
        return self._rng.randint(lo, hi)

    # ------------------------------------------------------------------
    # Мутация
    # ------------------------------------------------------------------

    def snapshot(self) -> tuple[tuple[int, ...], ...]:
        """Снимок паттернов всех лейнов (для истории версий, spec §6).

        Returns:
            Кортеж паттернов лейнов в порядке индексов.
        """
        return tuple(tuple(lane.pattern) for lane in self.lanes)

    def restore(self, state: tuple[tuple[int, ...], ...]) -> None:
        """Восстановить паттерны лейнов из снимка.

        Аргументы:
            state: Снимок из :meth:`snapshot` (длина — числу лейнов).

        Raises:
            ValueError: Если длина снимка не совпадает с числом лейнов.
        """
        if len(state) != len(self.lanes):
            raise ValueError(f"snapshot lanes {len(state)} != {len(self.lanes)}")
        for lane, pattern in zip(self.lanes, state, strict=True):
            lane.pattern = list(pattern)

    def _apply_mutation(self) -> None:
        """Применить 1–2 случайных изменения к случайным lane."""
        num_changes = self._rng.randint(1, 2)
        for _ in range(num_changes):
            # Выбираем lane, который можно изменить (не все ячейки = 2).
            mutable = [
                idx
                for idx, lane in enumerate(self.lanes)
                if any(c < 2 for c in lane.pattern)
            ]
            if not mutable:
                break
            lane_idx = self._rng.choice(mutable)
            lane = self.lanes[lane_idx]
            # Выбираем шаг, который можно изменить (не 2).
            mutable_steps = [i for i, c in enumerate(lane.pattern) if c < 2]
            step_idx = self._rng.choice(mutable_steps)
            old_value = lane.pattern[step_idx]
            # Переключить: 0→1, 1→2
            new_value = old_value + 1
            lane.pattern[step_idx] = new_value
            # Счётчик ведёт MutationEngine (история версий, spec §7) —
            # здесь его не трогаем.
            log.debug(
                "DrumTrack %s: lane %d step %d %d→%d",
                self.name,
                lane_idx,
                step_idx,
                old_value,
                new_value,
            )

    # ------------------------------------------------------------------
    # Утилиты
    # ------------------------------------------------------------------

    @staticmethod
    def step_to_note(step: int) -> int:
        """Преобразовать шаг сетки в GM-номер ноты.

        Одна функция на весь проект (план 4.2).

        Аргументы:
            step: Индекс лейна 0..15.

        Returns:
            GM-номер ноты 36..51.

        Raises:
            ValueError: Если step вне диапазона 0..15.
        """
        if not 0 <= step < 16:
            raise ValueError(f"Шаг {step} вне диапазона 0..15")
        return GM_DRUM_MAP[step][0]

    def resolve_lane(self, spec: str) -> int:
        """Разрешить адресацию lane'а: индекс / GM-номер / имя (design §6).

        Целое 0–15 — индекс lane'а; целое 36–51 — GM-номер ноты; иначе —
        имя lane'а (``"Kick"``, ``"Snare"``, …) без учёта регистра.
        Индексы и GM-номера различимы диапазонами — двусмысленности нет.

        Аргументы:
            spec: Строка адресации (``"0"``, ``"36"``, ``"kick"``).

        Returns:
            Индекс lane'а 0..15.

        Raises:
            ValueError: Число вне обоих диапазонов или неизвестное имя.
        """
        try:
            number = int(spec)
        except ValueError:
            lowered = spec.strip().lower()
            for index, (_, lane_name) in enumerate(GM_DRUM_MAP):
                if lane_name.lower() == lowered:
                    return index
            raise ValueError(
                f"lane {spec!r}: не индекс 0..15, не GM-номер 36..51 "
                f"и не имя lane'а"
            ) from None
        if 0 <= number <= 15:
            return number
        if 36 <= number <= 51:
            return number - 36
        raise ValueError(f"lane {spec!r}: число вне диапазонов 0..15 и 36..51")
