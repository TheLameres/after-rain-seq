"""Файл истории команд REPL.

Путь: ``<config_dir>/repl_history`` (рядом с config.yaml). При старте,
если файл больше ``max_lines`` строк — обрезаем, оставляя последние
``keep`` строк.
"""

from __future__ import annotations

from pathlib import Path

# Лимиты обрезки истории (план F1).
MAX_LINES: int = 2000
KEEP_LINES: int = 1000

# Имя файла истории рядом с config.yaml.
HISTORY_FILENAME: str = "repl_history"


def history_path_for(config_path: str) -> Path:
    """Путь к файлу истории для данного config.yaml."""
    config = Path(config_path)
    directory = config.parent if config.parent != Path("") else Path(".")
    return directory / HISTORY_FILENAME


def prepare_history(
    path: Path,
    max_lines: int = MAX_LINES,
    keep: int = KEEP_LINES,
) -> Path:
    """Создать родительскую директорию и обрезать разросшийся файл.

    Аргументы:
        path: Путь к файлу истории.
        max_lines: Если файла больше строк — обрезать.
        keep: Сколько последних строк оставить.

    Returns:
        Тот же путь (fluent-стиль для удобства сборки).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return path
        if len(lines) > max_lines:
            path.write_text(
                "\n".join(lines[-keep:]) + "\n",
                encoding="utf-8",
            )
    return path
