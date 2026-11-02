"""Repl — поток с циклом prompt_toolkit.

Жизненный цикл:
    - ``start()`` — создать daemon-поток и вернуть его (вызывает App).
    - Цикл: ``prompt()`` с ``bottom_toolbar`` (статус-бар ~2 Гц через
      встроенный ``refresh_interval=0.5``) → executor → вывод.
    - EOF (Ctrl+D, обрыв SSH) или ``exit``/``quit`` → ``on_eof`` (App.stop()).
    - ``stop()`` снаружи (SIGTERM от systemd): флаг + ``app.exit()`` у
      prompt-объекта — поток выходит на следующей итерации.

Если stdin не TTY (systemd), Repl выводит предупреждение и работает
в «тихом» режиме — EOF из закрытого stdin = стоп.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import FileHistory
from prompt_toolkit.shortcuts import print_formatted_text

from src.repl.completer import Provider, ReplCompleter
from src.repl.confirm import DEFAULT_PROMPT, ConfirmPolicy, ConfirmPrompt
from src.repl.engine_control import EngineControl
from src.repl.executor import CommandExecutor, EchoFn
from src.repl.history_store import prepare_history
from src.repl.status_bar import render_toolbar

if TYPE_CHECKING:
    from prompt_toolkit.input import Input
    from prompt_toolkit.output import Output

log = logging.getLogger(__name__)

PROMPT_TEXT: str = "ars> "
REFRESH_INTERVAL: float = 0.5  # перерисовка статус-бара ~2 раза/сек

OnEof = Callable[[], None]


class Repl:
    """Интерактивный REPL поверх :class:`EngineControl`.

    Параметры:
        control: Контракт управления движком.
        history_path: Путь к файлу истории (готовится обрезкой).
        policy: Политика подтверждений деструктивных команд.
        prompt_input: Колбак подтверждений (в тестах — стаб).
        on_eof: Вызывается по EOF / ``exit`` / ``quit`` (обычно app.stop()).
        input: prompt_toolkit Input (в тестах — pipe).
        output: prompt_toolkit Output (в тестах — DummyOutput).
        echo: Куда печатать вывод команд (по умолчанию stdout).
        dynamic_providers: Динамические дополнения комплитера
            (``"track"``/``"scale"``/``"profile"`` — из main.py).
        color: ANSI-цвета статус-бара. ``None`` — авто по TERM.
    """

    def __init__(
        self,
        control: EngineControl,
        *,
        history_path: str | Path,
        policy: ConfirmPolicy = ConfirmPolicy.INTERACTIVE,
        prompt_input: ConfirmPrompt = DEFAULT_PROMPT,
        on_eof: OnEof | None = None,
        input: Input | None = None,
        output: Output | None = None,
        echo: EchoFn | None = None,
        dynamic_providers: Mapping[str, Provider] | None = None,
        color: bool | None = None,
    ) -> None:
        self._control = control
        self._history_path = prepare_history(Path(history_path))
        self._on_eof = on_eof or (lambda: None)
        self._input = input
        self._output = output
        self._echo: EchoFn = echo or self._print
        self._stopped = False
        self._eof_called = False
        self._session: PromptSession[str] | None = None
        self._color = (
            color
            if color is not None
            else os.environ.get("TERM", "dumb") not in ("", "dumb")
        )
        self._executor = CommandExecutor(control, policy=policy, prompt=prompt_input)
        self._completer = ReplCompleter(control, providers=dynamic_providers)
        self._notified_no_tty = False

    # ------------------------------------------------------------------
    # Жизненный цикл
    # ------------------------------------------------------------------

    def start(self) -> threading.Thread:
        """Запустить REPL в daemon-потоке. Вернуть поток (для join)."""
        thread = threading.Thread(target=self.run, name="repl", daemon=True)
        thread.start()
        return thread

    def run(self) -> None:
        """Тело потока: цикл prompt → execute → echo."""
        self._warn_if_no_tty()
        self._echo(self._banner())
        self._session = PromptSession(
            history=FileHistory(str(self._history_path)),
            completer=self._completer,
            input=self._input,
            output=self._output,
        )
        while not self._stopped:
            try:
                line = self._session.prompt(
                    PROMPT_TEXT,
                    bottom_toolbar=self._toolbar,
                    refresh_interval=REFRESH_INTERVAL,
                )
            except EOFError:
                self._eof()
                break
            except KeyboardInterrupt:
                self._echo("")
                continue
            result = self._executor.execute(line)
            if result.output:
                self._echo(result.output)
            if result.exit:
                self._eof()
                break

    def stop(self) -> None:
        """Мягко остановить цикл (вызывается из App._cleanup)."""
        self._stopped = True
        session = self._session
        if session is not None:
            try:
                session.app.exit(result="")
            except Exception as exc:  # noqa: BLE001 — лучше флаг, чем падение
                log.debug("Repl.stop: prompt exit error: %s", exc)

    # ------------------------------------------------------------------
    # Статус-бар
    # ------------------------------------------------------------------

    def _toolbar(self) -> ANSI | str:
        """Форматированный текст для ``bottom_toolbar`` (~2 раза/сек).

        С ANSI-стилями возвращаем :class:`ANSI` — prompt_toolkit парсит
        escape-коды в фрагменты со стилями. Plain-строку с ``\\x1b`` ему
        передавать нельзя: control-символы вырезаются при рендере, и
        терминал показывает мусор вида ``[32m``.
        """
        snapshot = self._control.get_status()
        try:
            width = shutil.get_terminal_size().columns
        except OSError:
            width = 80
        text = render_toolbar(snapshot, width, color=self._color)
        return ANSI(text) if self._color else text

    # ------------------------------------------------------------------
    # Внутренние хелперы
    # ------------------------------------------------------------------

    def _eof(self) -> None:
        """Обработать EOF/exit однократно."""
        if self._eof_called:
            return
        self._eof_called = True
        self._on_eof()

    def _print(self, text: str) -> None:
        """Эхо по умолчанию: stdout с коллбеком вывода prompt_toolkit."""
        print_formatted_text(text, output=self._output)

    def _warn_if_no_tty(self) -> None:
        """Предупредить о запуске без TTY (systemd) один раз."""
        if self._input is None and not sys.stdin.isatty() and not self._notified_no_tty:
            self._notified_no_tty = True
            log.warning(
                "REPL: stdin is not a TTY — quiet mode, EOF stops the app. "
                "Do not use --repl under systemd."
            )

    @staticmethod
    def _banner() -> str:
        return "after-rain-seq REPL — type 'help' for commands, Ctrl+D to stop."


# Переэкспорт для удобства сборки из main.py.
__all__ = ["OnEof", "Repl"]
