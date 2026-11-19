"""Раннер скриптов: compile → validate → exec (синхронный батч).

Скрипт исполняется в globals с инжектированными ``session``,
``TrackProposal``, ``DrumProposal`` (импортов в скриптах нет, решение
Q8 — песочницы нет, ``__builtins__`` стандартные). Порядок гарантий:

1. файл читается (иначе отчёт с ``error``);
2. валидация проходит (иначе отчёт целиком из diagnostics —
   побочных эффектов не будет);
3. ``exec`` на потоке вызывающего (REPL-поток / поток main при загрузке);
   ``ScriptError`` и прочие исключения ловятся в отчёт.

Фидбек движка собирается в отчёт: каждая линия ``output_lines`` —
``EngineResult.message`` одного вызова фасада (плюс ``log.info``).
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.core.proposal import DrumProposal, TrackProposal
from src.repl.engine_control import EngineControl
from src.scripting.error import ScriptDiagnostic, ScriptError
from src.scripting.script_session import ScriptSession
from src.scripting.validator import ScriptValidator

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScriptRunReport:
    """Итог исполнения скрипта.

    Атрибуты:
        filename: Имя файла скрипта.
        diagnostics: Диагностики preflight-валидации (для ``script check``);
            исполнение не начиналось, если список непустой.
        lines_executed: Сколько вызовов фасада прошло (без исключений).
        output_lines: Фидбек движка по порядку вызовов.
        error: Текст первой ошибки (``file:line: <message>``) или ``None``.
    """

    filename: str
    diagnostics: tuple[ScriptDiagnostic, ...]
    lines_executed: int
    output_lines: tuple[str, ...]
    error: str | None


class _TracedSession:
    """Runtime-обёртка ScriptSession: считает вызовы и собирает фидбек.

    Скрипт видит её как ``session``: атрибут-метод — тот же метод фасада,
    обёрнутый в подсчёт ``EngineResult.message``. ``ScriptError`` из фасада
    прокидывается как есть — раннер ловит и оформляет отчёт.
    """

    def __init__(self, inner: ScriptSession, on_result: Callable[[str], None]) -> None:
        self._inner = inner
        self._on_result = on_result
        self.calls: int = 0

    def __getattr__(self, name: str) -> Callable[..., object]:
        method: Callable[..., object] = getattr(self._inner, name)

        def wrapper(*args: object, **kwargs: object) -> object:
            result = method(*args, **kwargs)
            self.calls += 1
            self._on_result(result.message)  # type: ignore[attr-defined]
            return result

        return wrapper


def _script_line(exc: BaseException, filename: str) -> int | None:
    """Номер строки скрипта в traceback исключения.

    Ищет последний кадр с ``co_filename == filename`` — строка скрипта,
    где произошёл вызов/исключение. Нет кадра скрипта (исключение в
    раннере) — ``None``.
    """
    line: int | None = None
    for frame in traceback.extract_tb(exc.__traceback__):
        if frame.filename == filename:
            line = frame.lineno
    return line


def format_report(report: ScriptRunReport) -> str:
    """Текстовый отчёт: заголовок, фидбек движка, diagnostics/ошибка.

    Формат (статус-стиль): строки ``NNN| <message движка>``, замечания
    валидации — ``file:line: message``.
    """
    lines = [f"script {report.filename}:"]
    if report.diagnostics:
        lines.append(f"  validation: {len(report.diagnostics)} diagnostic(s)")
        for diagnostic in report.diagnostics:
            lines.append(f"  {diagnostic.format()}")
        return "\n".join(lines)
    for index, message in enumerate(report.output_lines, 1):
        lines.append(f"  {index:>3}| {message}")
    if report.error is not None:
        lines.append(f"  error: {report.error}")
    else:
        lines.append(f"  ok: {report.lines_executed} call(s)")
    return "\n".join(lines)


class ScriptRunner:
    """Исполнение скрипта: compile → validate → exec (синхронно).

    Параметры:
        control: Контракт движка (мок в тестах, ``AppEngineControl`` в App).
    """

    def __init__(self, control: EngineControl) -> None:
        self._control = control

    def check_file(self, path: Path) -> list[ScriptDiagnostic]:
        """Только валидация (``script check``), без исполнения.

        Аргументы:
            path: Файл скрипта.

        Returns:
            Список диагностик (пустой — валидно). Файл не читается —
            одна диагностик с ``line=0``.
        """
        source, error = self._read(path)
        if error is not None:
            return [ScriptDiagnostic(filename=str(path), line=0, col=0, message=error)]
        return ScriptValidator().validate_source(source, str(path))

    def run_file(self, path: Path) -> ScriptRunReport:
        """Валидация → exec → отчёт (синхронный батч, решение Q3/Q10).

        Диагностики валидатора ⇒ исполнение не начинается: отчёт целиком
        из diagnostics, ``lines_executed=0``. Файл не читается — отчёт с
        ``error`` (без diagnostics). Прочие исключения скрипта ловятся в
        отчёт с traceback-текстом.

        Аргументы:
            path: Файл скрипта.

        Returns:
            Отчёт об исполнении.
        """
        source, error = self._read(path)
        if error is not None:
            return ScriptRunReport(
                filename=str(path),
                diagnostics=(),
                lines_executed=0,
                output_lines=(),
                error=error,
            )
        diagnostics = ScriptValidator().validate_source(source, str(path))
        if diagnostics:
            return ScriptRunReport(
                filename=str(path),
                diagnostics=tuple(diagnostics),
                lines_executed=0,
                output_lines=(),
                error=None,
            )
        return self._execute(source, str(path))

    # ------------------------------------------------------------------
    # Внутренние хелперы
    # ------------------------------------------------------------------

    @staticmethod
    def _read(path: Path) -> tuple[str, str | None]:
        """Прочитать файл скрипта; при ошибке — ``(source, error-текст)``.

        Аргументы:
            path: Файл скрипта.

        Returns:
            Кортеж ``(source, error)``: ровно одно значение не пусто.
        """
        try:
            return path.read_text(encoding="utf-8"), None
        except FileNotFoundError:
            return "", f"file not found: {path}"
        except OSError as exc:
            return "", f"cannot read {path}: {exc}"

    def _execute(self, source: str, filename: str) -> ScriptRunReport:
        """``exec`` валидированного скрипта в globals с инжекцией.

        Аргументы:
            source: Текст скрипта (уже прошёл валидацию).
            filename: Имя файла (для compile и отчёта).

        Returns:
            Отчёт: фидбек движка, счётчик вызовов, первая ошибка.
        """
        output_lines: list[str] = []

        def on_result(message: str) -> None:
            output_lines.append(message)
            log.info("script %s: %s", filename, message)

        traced = _TracedSession(ScriptSession(self._control), on_result)
        code = compile(source, filename, "exec")
        script_globals: dict[str, object] = {
            "__name__": "afterrain.script",
            "__file__": filename,
            "session": traced,
            "TrackProposal": TrackProposal,
            "DrumProposal": DrumProposal,
        }
        try:
            exec(code, script_globals)  # noqa: S102 — песочницы нет (решение Q8)
        except ScriptError as exc:
            line = _script_line(exc, filename)
            error = (
                f"{filename}:{line}: {exc.args[0]}" if line is not None else str(exc)
            )
            return ScriptRunReport(
                filename=filename,
                diagnostics=(),
                lines_executed=traced.calls,
                output_lines=tuple(output_lines),
                error=error,
            )
        except Exception as exc:  # noqa: BLE001 — прочие исключения скрипта в отчёт
            line = _script_line(exc, filename)
            text = f"{type(exc).__name__}: {exc}"
            error = f"{filename}:{line}: {text}" if line is not None else text
            return ScriptRunReport(
                filename=filename,
                diagnostics=(),
                lines_executed=traced.calls,
                output_lines=tuple(output_lines),
                error=error,
            )
        return ScriptRunReport(
            filename=filename,
            diagnostics=(),
            lines_executed=traced.calls,
            output_lines=tuple(output_lines),
            error=None,
        )
