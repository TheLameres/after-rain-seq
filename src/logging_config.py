"""Spring Boot-style layered logging for after-rain-seq.

Usage (matches Spring Boot logging.level.* syntax):
    from src.logging_config import apply_logging_config, set_level

    apply_logging_config(
        root_level="INFO",
        level_overrides={"src.midi": "DEBUG", "src.devices": "WARN"},
    )

    # Runtime change
    set_level("src.midi", "TRACE")

Level names: TRACE, DEBUG, INFO, WARN, ERROR, OFF  (Spring Boot convention).
Hierarchical: setting ``src.midi`` applies to ``src.midi.*`` automatically
via Python's logger inheritance.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.repl.log_buffer import LogBuffer

# Spring Boot level names → Python logging levels
_LEVEL_MAP: dict[str, int] = {
    "TRACE": logging.DEBUG,  # Python stdlib has no TRACE; closest is DEBUG
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "OFF": logging.CRITICAL + 1,  # effectively silences everything
}

# Reverse map for get_current_levels()
_PY_TO_LEVEL = {v: k for k, v in _LEVEL_MAP.items()}

# Known logger namespaces — used by the GUI config dialog.
KNOWN_LOGGERS = [
    "root",
    "src.midi",
    "src.devices",
    "src.app",
    "src.config",
    "src.sync",
]

VALID_LEVELS = list(_LEVEL_MAP.keys())


def _parse_level(level: str) -> int:
    """Convert Spring Boot level name to Python logging level int."""
    upper = level.strip().upper()
    if upper not in _LEVEL_MAP:
        raise ValueError(
            f"Unknown log level '{level}'. Valid: {', '.join(VALID_LEVELS)}"
        )
    return _LEVEL_MAP[upper]


def attach_log_buffer(buffer: LogBuffer) -> None:
    """Зарегистрировать LogBuffer на корневом логгере (для команды logs).

    Пишет в буфер в дополнение к существующим обработчикам,
    уровень INFO (всё, что до INFO, попадает в ``logs``).
    """
    buffer.setLevel(logging.INFO)
    logging.getLogger().addHandler(buffer)


def apply_logging_config(
    root_level: str,
    level_overrides: dict[str, str] | None = None,
) -> None:
    """Configure root logger + per-namespace levels (Spring Boot style).

    Args:
        root_level: Level for the root logger (e.g. "INFO").
        level_overrides: Mapping of logger name → level,
            e.g. ``{"src.midi": "DEBUG", "src.devices": "WARN"}``.
            ``"root"`` key here is ignored — use *root_level* for that.
    """
    logging.basicConfig(
        level=_parse_level(root_level),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    # Ensure root logger is set explicitly (basicConfig may have set it too).
    logging.getLogger().setLevel(_parse_level(root_level))

    for name, level in (level_overrides or {}).items():
        if name == "root":
            continue
        logging.getLogger(name).setLevel(_parse_level(level))


def set_level(name: str, level: str) -> None:
    """Change the log level for a logger at runtime.

    Args:
        name: Logger name (e.g. "src.midi"). Use "root" for the root logger.
        level: Spring Boot level name (TRACE, DEBUG, INFO, WARN, ERROR, OFF).
    """
    if name == "root":
        logging.getLogger().setLevel(_parse_level(level))
    else:
        logging.getLogger(name).setLevel(_parse_level(level))


def get_current_levels() -> dict[str, str]:
    """Return current effective levels for all KNOWN_LOGGERS."""
    result: dict[str, str] = {}
    for name in KNOWN_LOGGERS:
        logger = logging.getLogger(name) if name != "root" else logging.getLogger()
        py_level = logger.level
        # If logger has NOTSET, it inherits from parent — show parent's level
        if py_level == logging.NOTSET:
            # Walk up to find the first ancestor with a level
            effective = _resolve_effective_level(
                logger if name != "root" else logging.getLogger()
            )
            result[name] = effective
        else:
            result[name] = _PY_TO_LEVEL.get(py_level, f"Level({py_level})")
    return result


def _resolve_effective_level(logger: logging.Logger) -> str:
    """Walk the logger hierarchy to find the first non-NOTSET level."""
    current: logging.Logger | None = logger
    while current is not None:
        if current.level != logging.NOTSET:
            return _PY_TO_LEVEL.get(current.level, f"Level({current.level})")
        current = current.parent
    # Root always has a level
    return _PY_TO_LEVEL.get(logging.getLogger().level, "INFO")
