"""Статус-бар REPL — StatusSnapshot → строка toolbar'а.

Формат (ASCII-only — безопасно для любых SSH-терминалов)::

    > 120.0 bpm | clock: internal | A dorian | tracks 5 | mut 12 | ports 3 ok

Модификаторы:
    - Транспорт не запущен: ``||`` вместо ``>``, серый цвет.
    - Есть ``clock_pending``: ``clock: midi (pending)``, жёлтый.
    - ``clock_error`` или порт в ``error``/``ambiguous``: красный сегмент.
    - Link активен: справа ``link: 2 peers``.
    - Обрезание по ширине терминала: приоритет слева направо.

Цвета — ANSI; в не-TERM средах (``TERM=dumb``, pipe) вызывайте с
``color=False`` — вернётся чистый ASCII.
"""

from __future__ import annotations

from src.repl.status import StatusSnapshot

ANSI: dict[str, str] = {
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "red": "\x1b[31m",
    "gray": "\x1b[90m",
}
RESET: str = "\x1b[0m"

SEPARATOR: str = " | "

# Стили сегментов
_OK = "green"
_PAUSED = "gray"
_PENDING = "yellow"
_ERR = "red"


def render_toolbar(snapshot: StatusSnapshot, width: int, color: bool = True) -> str:
    """Отрисовать статус-бар заданной ширины.

    Аргументы:
        snapshot: Текущий снапшот состояния.
        width: Ширина терминала в колонках (хвост обрезается).
        color: Включать ANSI-цвета (False для dumb/pipe-терминалов).

    Returns:
        Строка для ``bottom_toolbar``.
    """
    segments = _segments(snapshot)
    width = max(width, 8)

    # Обрезание по приоритету слева направо (на plain-тексте, до покраски).
    chosen: list[tuple[str, str | None]] = []
    used = 0
    for text, style in segments:
        sep_len = len(SEPARATOR) if chosen else 0
        if used + sep_len + len(text) > width:
            break
        chosen.append((text, style))
        used += sep_len + len(text)

    if not chosen and segments:
        # Узкий терминал: хотя бы BPM, жёстко обрезаем с многоточием.
        head, style = segments[0]
        cut = max(width - 1, 1)
        chosen = [(head[:cut] + "…", style)]

    if color:
        parts = [
            f"{ANSI[style]}{text}{RESET}" if style else text for text, style in chosen
        ]
    else:
        parts = [text for text, _ in chosen]
    return SEPARATOR.join(parts)


def _segments(snapshot: StatusSnapshot) -> list[tuple[str, str | None]]:
    """Список (текст, стиль) в порядке приоритета слева направо."""
    if snapshot.running:
        segments: list[tuple[str, str | None]] = [(f"> {snapshot.bpm:.1f} bpm", _OK)]
    else:
        segments = [(f"|| {snapshot.bpm:.1f} bpm", _PAUSED)]

    if snapshot.clock_error:
        segments.append((f"clock err: {snapshot.clock_error}", _ERR))
    elif snapshot.clock_pending:
        segments.append((f"clock: {snapshot.clock_pending} (pending)", _PENDING))
    else:
        segments.append((f"clock: {snapshot.clock_source}", None))

    segments.append((f"{snapshot.root} {snapshot.scale}", None))
    segments.append((f"tracks {len(snapshot.tracks)}", None))
    segments.append((f"mut {snapshot.total_mutations}", None))

    bad_ports = [p for p in snapshot.ports if p.status in ("error", "ambiguous")]
    if bad_ports:
        first = bad_ports[0]
        segments.append((f"port {first.name}: {first.status}", _ERR))
    elif snapshot.ports:
        ok = sum(1 for p in snapshot.ports if p.status == "connected")
        segments.append((f"ports {ok}/{len(snapshot.ports)} ok", _OK))
    else:
        segments.append(("ports —", _PAUSED))

    if snapshot.link_active:
        segments.append((f"link: {snapshot.link_peers} peers", _OK))

    return segments
