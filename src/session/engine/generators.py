"""Генераторы нот по профилям — паттерны как данные, один вход (C6, шаг 2).

Чистые функции ``generate_notes(ctx) -> list[NoteEvent]`: по профилю дорожки
(``track.profile.pattern``) и текущему состоянию механизмов мутации
(из ``GenerationContext``) порождают ноты в **ступенях лада** на один
паттерн (относительные beats). Циклическое повторение на таймлайне и
резолв ступеней в MIDI — забота :class:`MelodicEngine`.

Семейства (см. :class:`PatternSpec`):

- ``chord_source`` — прогрессия ``degrees`` → аккорды; ``change_every`` > 1
  — один аккорд на весь паттерн (atmos). Гейт и регистр читаются из
  ``ParamDrift``, если он подключён (pad/atmos/bass → ParamDrift).
- ``free_mono`` — одна нота на ступень; при подключённом ``NoteDrift``
  ступени берутся из дрейфа (lead/texture), иначе из ``track.degrees``
  (bass); ``change_every`` > 1 — редкая одиночная нота (texture).
- ``chord_slicer`` — нарезка ``ChordEvent`` источников; реализовано в
  шаге 3 C6, здесь возвращает пустой список (нет окна аккордов — тишина).
- ``cc_only`` — нот нет.

Механизмы мутации (``ctx.note_drift`` / ``ctx.param_drift``) могут быть
``None`` — тогда генератор играет базовый материал дорожки.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.session.events.note_event import NoteEvent
from src.session.model.chord_math import (
    chord_cycle,
    chord_degrees_for,
    pattern_length,
)
from src.session.model.euclidean import PEuclideanCached
from src.session.model.pattern_spec import (
    FAMILY_CC_ONLY,
    FAMILY_CHORD_SLICER,
    FAMILY_CHORD_SOURCE,
    FAMILY_FREE_MONO,
)

if TYPE_CHECKING:
    from src.session.events.chord_event import ChordEvent
    from src.session.model.melodic_track import MelodicTrack
    from src.session.mutation import FloatingEuclidean, NoteDrift, ParamDrift

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Общие хелперы
# ---------------------------------------------------------------------------
# ``chord_degrees_for`` / ``pattern_length`` / ``chord_cycle`` живут в
# ``model/chord_math.py`` (общая математика графа и звука) и
# реэкспортируются здесь для обратной совместимости импортов.
# ---------------------------------------------------------------------------


def pattern_length_for(ctx: GenerationContext) -> float:
    """Период паттерна для контекста генерации.

    Slicer'ы живут циклом аккордов источника (период = chord_cycle окна);
    остальные — собственной длиной паттерна профиля.
    """
    if ctx.track.profile.pattern.family == FAMILY_CHORD_SLICER and ctx.chord_window:
        return chord_cycle(ctx.chord_window)
    return pattern_length(ctx.track)


# ---------------------------------------------------------------------------
# GenerationContext
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GenerationContext:
    """Вход генератора: дорожка + текущее состояние механизмов мутации.

    Атрибуты:
        track: Мелодическая дорожка (профиль, voicing, octave, gate, …).
        chord_window: ChordEvent источников на окно планирования
            (chord_slicer; шаг 3 C6). Пусто — не подключён/нет источников.
        note_drift: NoteDrift дорожки или None (нет дрейфа).
        euclidean: FloatingEuclidean дорожки или None (шаг 3–4 C6).
        param_drift: ParamDrift дорожки или None (нет дрейфа).
    """

    track: MelodicTrack
    chord_window: tuple[ChordEvent, ...] = ()
    note_drift: NoteDrift | None = None
    euclidean: FloatingEuclidean | None = None
    param_drift: ParamDrift | None = None


# ---------------------------------------------------------------------------
# Генераторы семейств
# ---------------------------------------------------------------------------


def _effective_gate(ctx: GenerationContext) -> float:
    """Гейт: из ParamDrift, если он ведёт «gate», иначе гейт дорожки."""
    drift = ctx.param_drift
    if drift is not None and "gate" in drift.param_names:
        return drift.get("gate")
    return ctx.track.gate


def _octave_offset(ctx: GenerationContext) -> int:
    """Сдвиг регистра: округлённый «register» из ParamDrift, иначе 0."""
    drift = ctx.param_drift
    if drift is not None and "register" in drift.param_names:
        return round(drift.get("register"))
    return 0


def _gen_chord_source(ctx: GenerationContext) -> list[NoteEvent]:
    """Прогрессия → аккорды целиком (pad, atmos).

    Аккорд i ступени прогрессии занимает слот ``change_every`` beats
    (pad: 1 такт на аккорд; atmos: change_every тактов на аккорд). Первая
    нота паттерна акцентирована.
    """
    track = ctx.track
    spec = track.profile.pattern
    if not track.degrees:
        return []
    gate = _effective_gate(ctx)
    offset = _octave_offset(ctx)
    slot = float(spec.change_every)

    notes: list[NoteEvent] = []
    for i, degree in enumerate(track.degrees):
        velocity = spec.velocity_accent if i == 0 else spec.velocity_base
        for deg in chord_degrees_for(track, degree):
            notes.append(
                NoteEvent(
                    beat=i * slot,
                    degree=deg,
                    velocity=velocity,
                    duration=slot * gate,
                    octave_offset=offset,
                )
            )
    return notes


def _gen_free_mono(ctx: GenerationContext) -> list[NoteEvent]:
    """Одна мелодическая линия из собственных ступеней (bass, lead, texture).

    Ступени — из NoteDrift, если подключён (lead/texture), иначе из
    ``track.degrees`` (bass). ``change_every`` > 1 — редкая одиночная нота
    на весь паттерн (texture).
    """
    track = ctx.track
    spec = track.profile.pattern
    drift = ctx.note_drift
    degrees = drift.current_degrees if drift is not None else list(track.degrees)
    if not degrees:
        return []
    gate = _effective_gate(ctx)
    offset = _octave_offset(ctx)

    if spec.change_every > 1:  # texture: одна нота на паттерн
        return [
            NoteEvent(
                beat=0.0,
                degree=degrees[0],
                velocity=spec.velocity_base,
                duration=pattern_length(track) * gate,
                octave_offset=offset,
            )
        ]

    notes: list[NoteEvent] = []
    for i, degree in enumerate(degrees):
        if not _density_keep(i, track.density):
            continue  # макро-ось DEN (D2): разрежение паттерна
        velocity = spec.velocity_accent if i == 0 else spec.velocity_base
        notes.append(
            NoteEvent(
                beat=float(i),
                degree=degree,
                velocity=velocity,
                duration=1.0 * gate,
                octave_offset=offset,
            )
        )
    return notes


def _gen_chord_slicer(ctx: GenerationContext) -> list[NoteEvent]:
    """Нарезка ChordEvent источников (sub, stab, seq, arp).

    Паттерн slicer'а живёт циклом аккордов окна: ``ctx.chord_window``
    (относительные beats одного цикла источника), период —
    :func:`chord_cycle`. Форма нарезки — по полю ``shape`` спецификации:
    корень со сдвигом (sub), евклидовы стабы (stab), ступени по сетке
    с паузами (seq), обход аккорда (arp).
    """
    window = sorted(ctx.chord_window, key=lambda ev: ev.beat)
    if not window:
        return []  # стратегия B: нет источников — тишина
    shape = ctx.track.profile.pattern.shape
    if shape == "sub":
        return _slice_sub(ctx, window)
    if shape == "stab":
        return _slice_stab(ctx, window)
    if shape == "seq":
        return _slice_seq(ctx, window)
    if shape == "arp":
        return _slice_arp(ctx, window)
    log.debug("MelodicTrack %s: неизвестный shape %r", ctx.track.name, shape)
    return []


def _slice_sub(ctx: GenerationContext, window: list[ChordEvent]) -> list[NoteEvent]:
    """Корень аккорда источника, сдвинутый на долю аккорда (sub).

    Одна нота на аккорд: первая ступень события, старт на
    ``beat + duration * sub_shift``, длительность = длительность аккорда.
    """
    track = ctx.track
    spec = track.profile.pattern
    gate = _effective_gate(ctx)
    offset = _octave_offset(ctx)
    notes: list[NoteEvent] = []
    for ev in window:
        degree = ev.degrees[0] if ev.degrees else 0
        notes.append(
            NoteEvent(
                beat=ev.beat + ev.duration * spec.sub_shift,
                degree=degree,
                velocity=spec.velocity_base,
                duration=ev.duration * gate,
                octave_offset=offset,
            )
        )
    return notes


def _euclid_steps(ctx: GenerationContext) -> list[int]:
    """Активные шаги евклидова паттерна (1 — играем, 0 — пауза).

    Паттерн — из ``ctx.euclidean`` (FloatingEuclidean мутации), иначе
    строится по спецификации; плотность из ``ParamDrift`` сдвигает число
    pulses относительно ``base_pulses``, иначе — макро-ось DEN
    (``track.density``, D2): 1.0 = базовый рисунок, 0.0 = 25% базовой
    плотности (не тишина).
    """
    spec = ctx.track.profile.pattern
    if ctx.euclidean is not None:
        return ctx.euclidean.pattern
    pulses = spec.base_pulses
    drift = ctx.param_drift
    if drift is not None and "density" in drift.param_names:
        density = drift.get("density")
        pulses = max(
            1,
            min(spec.steps - 1, round(spec.base_pulses * (0.5 + density))),
        )
    else:
        pulses = _density_pulses(spec.base_pulses, spec.steps, ctx.track.density)
    return PEuclideanCached(spec.steps, pulses).pattern


def _density_pulses(base_pulses: int, steps: int, density: float) -> int:
    """Число pulses евклида под макро-осью DEN (план D2 §3.6).

    Формула: ``round(base * (0.25 + 0.75 * density))`` — DEN=1 → базовый
    рисунок, DEN=0 → 25% базовой плотности, кламп ``1..steps``.
    """
    scaled = round(base_pulses * (0.25 + 0.75 * density))
    return max(1, min(steps, scaled))


def _density_keep(index: int, density: float) -> bool:
    """Детерминированный фильтр плотности для free_mono (план D2 §3.6).

    Шаг 0 (акцент) всегда играет. Остальные — псевдо-случайно по индексу
    (хэш константа), порог ``0.25 + 0.75 * density``: плотность 1.0 → все
    ноты, 0.0 → ~25%. Детерминизм важен: паттерн перегенерируется на
    каждом цикле и должен оставаться стабильным.
    """
    if index == 0:
        return True
    h = ((index * 2654435761) % 1000) / 1000.0
    return h < (0.25 + 0.75 * density)


def _slice_stab(ctx: GenerationContext, window: list[ChordEvent]) -> list[NoteEvent]:
    """Аккорд источника целиком, нарезанный евклидовым паттерном (stab).

    Длительность аккорда делится на ``steps`` слотов; на активных шагах
    бьёт весь аккорд короткой нотой (гейт слит с гейтом дорожки).
    """
    track = ctx.track
    spec = track.profile.pattern
    gate = _effective_gate(ctx)
    offset = _octave_offset(ctx)
    pattern = _euclid_steps(ctx)
    notes: list[NoteEvent] = []
    for ev in window:
        slot = ev.duration / spec.steps
        for step, active in enumerate(pattern):
            if not active:
                continue
            velocity = spec.velocity_accent if step == 0 else spec.velocity_base
            for deg in ev.degrees:
                notes.append(
                    NoteEvent(
                        beat=ev.beat + step * slot,
                        degree=deg,
                        velocity=velocity,
                        duration=slot * (1.0 + gate),
                        octave_offset=offset,
                    )
                )
    return notes


def _slice_seq(ctx: GenerationContext, window: list[ChordEvent]) -> list[NoteEvent]:
    """Ступени аккорда источника по сетке с паузами (seq).

    Как stab, но играет не весь аккорд, а одну ступень за активный шаг,
    обходя ступени по порядку. Акцент — на первом шаге аккорда.
    """
    track = ctx.track
    spec = track.profile.pattern
    gate = _effective_gate(ctx)
    offset = _octave_offset(ctx)
    pattern = _euclid_steps(ctx)
    notes: list[NoteEvent] = []
    for ev in window:
        slot = ev.duration / spec.steps
        degrees = ev.degrees or (0,)
        idx = 0
        for step, active in enumerate(pattern):
            if not active:
                continue
            velocity = spec.velocity_accent if step == 0 else spec.velocity_base
            notes.append(
                NoteEvent(
                    beat=ev.beat + step * slot,
                    degree=degrees[idx % len(degrees)],
                    velocity=velocity,
                    duration=slot * (1.0 + gate),
                    octave_offset=offset,
                )
            )
            idx += 1
    return notes


def _slice_arp(ctx: GenerationContext, window: list[ChordEvent]) -> list[NoteEvent]:
    """Обход ступеней аккорда по сетке (arp).

    Каждый слот играет одну ступень; направление — ``arp_direction``
    спецификации (``"up"`` по кругу, ``"down"`` в обратном порядке).
    Пауз нет — плотный обход.
    """
    track = ctx.track
    spec = track.profile.pattern
    gate = _effective_gate(ctx)
    offset = _octave_offset(ctx)
    notes: list[NoteEvent] = []
    for ev in window:
        slot = ev.duration / spec.steps
        degrees = sorted(ev.degrees) or (0,)
        n = len(degrees)
        for step in range(spec.steps):
            if spec.arp_direction == "down":
                degree = degrees[(n - 1) - (step % n)]
            else:
                degree = degrees[step % n]
            velocity = spec.velocity_accent if step == 0 else spec.velocity_base
            notes.append(
                NoteEvent(
                    beat=ev.beat + step * slot,
                    degree=degree,
                    velocity=velocity,
                    duration=slot * (1.0 + gate),
                    octave_offset=offset,
                )
            )
    return notes


def _gen_cc_only(ctx: GenerationContext) -> list[NoteEvent]:
    """cc_only-профили не порождают нот (CC — отдельная задача)."""
    return []


GENERATORS: dict[str, Callable[[GenerationContext], list[NoteEvent]]] = {
    FAMILY_CHORD_SOURCE: _gen_chord_source,
    FAMILY_CHORD_SLICER: _gen_chord_slicer,
    FAMILY_FREE_MONO: _gen_free_mono,
    FAMILY_CC_ONLY: _gen_cc_only,
}


def generate_notes(ctx: GenerationContext) -> list[NoteEvent]:
    """Сгенерировать ноты паттерна дорожки по профилю и состоянию мутации.

    Аргументы:
        ctx: Контекст генерации (дорожка + механизмы).

    Returns:
        Список NoteEvent на один паттерн (относительные beats).
    """
    generator = GENERATORS.get(ctx.track.profile.pattern.family)
    if generator is None:
        log.debug(
            "MelodicTrack %s: нет генератора для семейства %r",
            ctx.track.name,
            ctx.track.profile.pattern.family,
        )
        return []
    return generator(ctx)
