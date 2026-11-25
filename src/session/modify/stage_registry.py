"""Реестр этапов цепочки модификаций (track-modify-chain).

Строки-спецификации «имя [ключ=значение ...]» превращаются в экземпляры
этапов. Реестр — единое место для REPL и скриптового фасада: добавление
нового этапа — одна строка в ``STAGE_FACTORIES``. Параметры передаются
строками, конверсия — забота реестра.

Листовой модуль слоя modify: импортов вверх нет.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from src.session.events.note_event import NoteEvent
from src.session.modify.arpeggiate import ArpeggiateStage
from src.session.modify.chain import Stage
from src.session.modify.densify import DensifyStage

# Допустимые параметры этапов: имя этапа → {имя параметра: обязательный?}.
_STAGE_PARAMS: dict[str, dict[str, bool]] = {
    "arpeggiate": {"step": False, "direction": False},
    "densify": {"density": True},
}


def _parse_float(stage_name: str, key: str, raw: str) -> float:
    """Число из строки с русским сообщением об ошибке."""
    try:
        return float(raw)
    except ValueError:
        raise ValueError(
            f"{stage_name}: параметр {key!r} должен быть числом, получено {raw!r}"
        ) from None


def _build_arpeggiate(params: Mapping[str, str]) -> Stage[NoteEvent]:
    """Фабрика этапа Arpeggiate (step, direction — опциональные)."""
    step = 0.25
    if "step" in params:
        step = _parse_float("arpeggiate", "step", params["step"])
    direction = params.get("direction", "up")
    return ArpeggiateStage(step=step, direction=direction)


def _build_densify(params: Mapping[str, str]) -> Stage[NoteEvent]:
    """Фабрика этапа Densify (density — обязательный, скрытых дефолтов нет)."""
    if "density" not in params:
        raise ValueError("densify: отсутствует обязательный параметр density")
    density = _parse_float("densify", "density", params["density"])
    return DensifyStage(density=density)


STAGE_FACTORIES: dict[str, Callable[[Mapping[str, str]], Stage[NoteEvent]]] = {
    "arpeggiate": _build_arpeggiate,
    "densify": _build_densify,
}


def build_stage(name: str, params: Mapping[str, str]) -> Stage[NoteEvent]:
    """Собрать этап по имени и параметрам.

    Аргументы:
        name: Имя этапа из ``STAGE_FACTORIES``.
        params: Параметры строками.

    Raises:
        ValueError: Неизвестное имя (с перечнем доступных), неизвестный
            параметр, нечисловое значение, отсутствующий обязательный
            параметр.
    """
    if name not in STAGE_FACTORIES:
        available = ", ".join(sorted(STAGE_FACTORIES))
        raise ValueError(f"Неизвестный этап {name!r}; доступные этапы: {available}")
    allowed = _STAGE_PARAMS[name]
    for key in params:
        if key not in allowed:
            raise ValueError(
                f"{name}: неизвестный параметр {key!r}; "
                f"допустимые параметры: {', '.join(sorted(allowed))}"
            )
    return STAGE_FACTORIES[name](params)


def format_stage(stage: Stage[NoteEvent]) -> str:
    """Каноническая строка-спецификация этапа для показа и REPL.

    Формат: ``имя [ключ=значение ...]``. Круговая согласованность
    с :func:`parse_stage_spec` фиксируется тестом.
    """
    name = stage.name
    if isinstance(stage, ArpeggiateStage):
        return f"arpeggiate step={stage.step} direction={stage.direction}"
    if isinstance(stage, DensifyStage):
        return f"densify density={stage.density}"
    return name


def parse_stage_spec(spec: str) -> tuple[str, dict[str, str]]:
    """Разобрать строку-спецификацию «имя [ключ=значение ...]».

    Первая лексема — имя этапа, остальные — пары ``k=v``. Лексема без
    ``=`` или дубликат ключа — ``ValueError`` с русским сообщением.

    Returns:
        Кортеж (имя этапа, параметры строками).

    Raises:
        ValueError: Пустая строка, лексема без ``=``, дубликат ключа.
    """
    tokens = spec.split()
    if not tokens:
        raise ValueError("Спецификация этапа пуста")
    name = tokens[0]
    params: dict[str, str] = {}
    for token in tokens[1:]:
        if "=" not in token:
            raise ValueError(
                f"Спецификация этапа {name!r}: параметр {token!r} без значения "
                "(ожидается «ключ=значение»)"
            )
        key, _, value = token.partition("=")
        if key in params:
            raise ValueError(f"Спецификация этапа {name!r}: дубликат параметра {key!r}")
        params[key] = value
    return name, params
