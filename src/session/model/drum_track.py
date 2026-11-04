"""Drum-машина — 16 лейнов, GM 36–51, вне графа гармонии.

Drum не читает и не публикует гармонию: ``sources`` заблокирован.
Попытка назначить источник — отказ с сообщением. Правила из плана 4.2:
абсолютные ноты (не ``degree``), смена Root/Scale не влияет, gate
one-shot, три уровня velocity силой нажатия пада, мутация 1–2 изменения
за 8–16 секунд с деградацией к базовому рисунку.
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

# Мутация: интервал в секундах, не в тактах (план 4.2).
MUTATE_MIN_SECONDS: float = 8.0
MUTATE_MAX_SECONDS: float = 16.0

# Длительность one-shot удара в долях (1/16 = 0.25).
DEFAULT_GATE: float = 0.25

# Стандартная GM-карта для 16 лейнов (note, имя).
_GM_DRUM_MAP: tuple[tuple[int, str], ...] = (
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
        mutate: Вероятность мутации 0.0–1.0 (0 = заморожено).
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
            DrumLane(note=note, name=lname) for note, lname in _GM_DRUM_MAP
        ]
        self.steps: int = steps
        # Расширяем паттерны lane до steps (если steps > 16).
        for lane in self.lanes:
            lane.ensure_length(steps)
        self.accent_level: int = 127
        self.mutate: float = 0.5
        self.square: int = 1

        # Мутация: состояние.
        self._rng = random.Random()
        self._base_patterns: list[list[int]] = [
            list(lane.pattern) for lane in self.lanes
        ]
        self._last_mutation_beat: float = 0.0
        self._next_mutation_beat: float | None = None

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
        step_duration = 1.0 / (self.steps / 4)  # доля = 1/4 такта

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

    def _compute_next_mutation_beat(self, from_beat: float, bpm: float) -> float:
        """Вычислить beat следующей мутации.

        Интервал от времени (секунды), не от тактов — при смене BPM
        частота мутации сохраняется (план 4.2).

        Аргументы:
            from_beat: Beat, от которого отсчитывать.

        Returns:
            Beat следующей мутации.
        """
        seconds = self._rng.uniform(MUTATE_MIN_SECONDS, MUTATE_MAX_SECONDS)
        beats = seconds * bpm / 60.0
        return from_beat + beats

    def maybe_mutate(self, current_beat: float, bpm: float) -> bool:
        """Применить мутацию, если пришло время.

        Правила из плана 4.2:
        - Интервал uniform(8, 16) секунд
        - 1–2 изменения за интервал
        - Деградация: с вероятностью ``mutate`` откатываем к базовому

        Аргументы:
            current_beat: Текущая позиция в тактах.

        Returns:
            True, если мутация была применена.
        """
        if self.mutate <= 0.0:
            return False
        if self._next_mutation_beat is None:
            self._next_mutation_beat = self._compute_next_mutation_beat(
                current_beat, bpm
            )
            return False
        if current_beat < self._next_mutation_beat:
            return False

        # Деградация: с вероятностью mutate откатываем одно изменение.
        if self._mutation_count > 0 and self._rng.random() < self.mutate:
            self._revert_one_mutation()
        else:
            self._apply_mutation()

        self._last_mutation_beat = current_beat
        self._next_mutation_beat = self._compute_next_mutation_beat(current_beat, bpm)
        return True

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
            self.record_mutation(1)
            log.debug(
                "DrumTrack %s: lane %d step %d %d→%d",
                self.name,
                lane_idx,
                step_idx,
                old_value,
                new_value,
            )

    def _revert_one_mutation(self) -> None:
        """Откатить одно изменение к базовому паттерну."""
        # Находим lane, который отличается от базового.
        candidates: list[tuple[int, int, int]] = []  # (lane, step, base_val)
        for lane_idx, lane in enumerate(self.lanes):
            base = self._base_patterns[lane_idx]
            for step_idx in range(min(len(lane.pattern), len(base))):
                if lane.pattern[step_idx] != base[step_idx]:
                    candidates.append((lane_idx, step_idx, base[step_idx]))

        if not candidates:
            return

        lane_idx, step_idx, base_val = self._rng.choice(candidates)
        self.lanes[lane_idx].pattern[step_idx] = base_val
        if self._mutation_count > 0:
            self.record_mutation(-1)
        log.debug(
            "DrumTrack %s: revert lane %d step %d → %d",
            self.name,
            lane_idx,
            step_idx,
            base_val,
        )

    def freeze(self) -> None:
        """Заморозить мутацию — запомнить текущий паттерн как базовый."""
        self._base_patterns = [list(lane.pattern) for lane in self.lanes]
        self.reset_mutation_count()
        # §4.3: без mutate=0 maybe_mutate продолжал мутировать после freeze.
        self.mutate = 0.0
        log.info("DrumTrack %s: frozen", self.name)

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
        return _GM_DRUM_MAP[step][0]
