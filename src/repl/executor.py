"""Исполнитель команд REPL: Command + EngineControl → CommandResult.

Деструктивные команды проходят через политику подтверждений
(``--yes``/``-f`` в флагах — пропускает вопрос). Исключения из движка
ловятся и превращаются в текст ошибки — цикл REPL не падает.
"""

from __future__ import annotations

from collections.abc import Callable

from src.repl.command import Command, CommandResult
from src.repl.confirm import DEFAULT_PROMPT, ConfirmPolicy, ConfirmPrompt
from src.repl.engine_control import EngineControl
from src.repl.parser import CommandParser, CommandSpec
from src.repl.status import StatusSnapshot, TrackSummary

DEFAULT_LOG_LINES: int = 20


class CommandExecutor:
    """Выполняет разобранные команды против :class:`EngineControl`.

    Параметры:
        control: Контракт управления движком (в тестах — мок).
        policy: Политика подтверждений деструктивных команд.
        prompt: Колбэк ввода для подтверждений (в тестах — стаб).
    """

    def __init__(
        self,
        control: EngineControl,
        policy: ConfirmPolicy = ConfirmPolicy.INTERACTIVE,
        prompt: ConfirmPrompt = DEFAULT_PROMPT,
    ) -> None:
        self._control = control
        self._policy = policy
        self._prompt = prompt
        self._parser = CommandParser()

    def execute(self, line: str) -> CommandResult:
        """Разобрать и выполнить строку ввода."""
        command = self._parser.parse(line)
        if command.error is not None:
            out = command.error
            if command.usage:
                out += f"\n{command.usage}"
            return CommandResult(output=out, code=1)
        if not command.name:
            return CommandResult()  # пустой ввод — no-op
        spec = self._spec(command.name)
        try:
            return self._dispatch(command, spec)
        except Exception as exc:  # noqa: BLE001 — REPL не должен падать
            return CommandResult(output=f"error: {exc}", code=1)

    # ------------------------------------------------------------------
    # Диспетчеризация
    # ------------------------------------------------------------------

    def _dispatch(self, command: Command, spec: CommandSpec) -> CommandResult:
        handler = getattr(self, f"_cmd_{command.name.replace(' ', '_')}", None)
        if handler is None:
            return CommandResult(
                output=f"error: no handler for {command.name!r}", code=1
            )
        if (
            spec.destructive
            and not command.destructive_confirmed
            and not self._policy.confirmed(self._question(command), self._prompt)
        ):
            return CommandResult(output="cancelled")
        return handler(command)

    @staticmethod
    def _question(command: Command) -> str:
        if command.name == "stop":
            return "Stop transport?"
        if command.name == "track delete":
            return f'Delete track "{command.args[0]}"?'
        return f"Execute {command.name}?"

    # ------------------------------------------------------------------
    # Команды
    # ------------------------------------------------------------------

    def _cmd_status(self, command: Command) -> CommandResult:
        return CommandResult(output=format_status(self._control.get_status()))

    def _cmd_start(self, command: Command) -> CommandResult:
        return self._feedback(self._control.start_transport())

    def _cmd_stop(self, command: Command) -> CommandResult:
        return self._feedback(self._control.stop_transport())

    def _cmd_bpm(self, command: Command) -> CommandResult:
        try:
            bpm = float(command.args[0])
        except ValueError:
            return CommandResult(
                output=f"error: {command.args[0]!r} is not a number", code=1
            )
        return self._feedback(self._control.set_bpm(bpm))

    def _cmd_clock(self, command: Command) -> CommandResult:
        snap = self._control.get_status()
        lines = [
            f"clock: {snap.clock_source}",
            f"running: {'yes' if snap.running else 'no'}",
            f"bpm: {snap.bpm:.1f}",
            f"pending: {snap.clock_pending or '—'}",
        ]
        link = f"link: {'on' if snap.link_active else 'off'} ({snap.link_peers} peers)"
        lines.append(link)
        lines.append(f"error: {snap.clock_error or '—'}")
        return CommandResult(output="\n".join(lines))

    def _cmd_clock_source(self, command: Command) -> CommandResult:
        return self._feedback(
            self._control.request_clock_source(command.args[0].lower())
        )

    def _cmd_ports(self, command: Command) -> CommandResult:
        snap = self._control.get_status()
        if not snap.ports:
            return CommandResult(output="no ports configured")
        width = max(len(p.name) for p in snap.ports)
        lines = []
        for p in snap.ports:
            lines.append(f"  {p.name:<{width}}  {p.status:<12} {p.detail}")
        return CommandResult(output="\n".join(lines))

    def _cmd_ports_scan(self, command: Command) -> CommandResult:
        return self._feedback(self._control.rescan_ports())

    def _cmd_ports_switch(self, command: Command) -> CommandResult:
        return self._feedback(
            self._control.switch_port(command.args[0], command.args[1])
        )

    def _cmd_tracks(self, command: Command) -> CommandResult:
        return CommandResult(output=format_tracks(self._control.get_status()))

    def _cmd_track_show(self, command: Command) -> CommandResult:
        name = command.args[0]
        for track in self._control.get_status().tracks:
            if track.name == name:
                return CommandResult(output=format_track(track))
        return CommandResult(output=f"error: track {name!r} not found", code=1)

    def _cmd_track_add(self, command: Command) -> CommandResult:
        channel: int | None = None
        if len(command.args) > 1:
            try:
                channel = int(command.args[1])
            except ValueError:
                return CommandResult(
                    output=f"error: {command.args[1]!r} is not a number", code=1
                )
        return self._feedback(self._control.create_track(command.args[0], channel))

    def _cmd_track_channel(self, command: Command) -> CommandResult:
        try:
            channel = int(command.args[1])
        except ValueError:
            return CommandResult(
                output=f"error: {command.args[1]!r} is not a number", code=1
            )
        return self._feedback(self._control.set_track_channel(command.args[0], channel))

    def _cmd_track_delete(self, command: Command) -> CommandResult:
        return self._feedback(self._control.remove_track(command.args[0]))

    def _cmd_track_route(self, command: Command) -> CommandResult:
        return self._feedback(
            self._control.route_track(command.args[0], command.args[1])
        )

    def _cmd_track_unroute(self, command: Command) -> CommandResult:
        return self._feedback(self._control.unroute_track(command.args[0]))

    def _cmd_root(self, command: Command) -> CommandResult:
        return self._feedback(self._control.set_root(command.args[0]))

    def _cmd_scale(self, command: Command) -> CommandResult:
        return self._feedback(self._control.set_scale(command.args[0]))

    def _cmd_freeze(self, command: Command) -> CommandResult:
        name = command.args[0] if command.args else None
        return self._feedback(self._control.freeze(name))

    def _cmd_evolve(self, command: Command) -> CommandResult:
        return self._feedback(self._control.evolve())

    def _cmd_mutations(self, command: Command) -> CommandResult:
        snap = self._control.get_status()
        return CommandResult(output=f"total mutations: {snap.total_mutations}")

    def _cmd_logs(self, command: Command) -> CommandResult:
        n = DEFAULT_LOG_LINES
        if command.args:
            try:
                n = int(command.args[0])
            except ValueError:
                return CommandResult(
                    output=f"error: {command.args[0]!r} is not a number", code=1
                )
        lines = self._control.get_logs(n)
        return CommandResult(output="\n".join(lines) if lines else "(log is empty)")

    def _cmd_help(self, command: Command) -> CommandResult:
        name = command.args[0] if command.args else None
        text = self._parser.help_text(name)
        code = 1 if text.startswith("error:") else 0
        return CommandResult(output=text, code=code)

    def _cmd_exit(self, command: Command) -> CommandResult:
        return CommandResult(output="bye", exit=True)

    _cmd_quit = _cmd_exit

    # ------------------------------------------------------------------
    # Внутренние хелперы
    # ------------------------------------------------------------------

    @staticmethod
    def _spec(name: str) -> CommandSpec:
        for spec in CommandParser().specs():
            if spec.name == name:
                return spec
        raise KeyError(name)

    @staticmethod
    def _feedback(text: str) -> CommandResult:
        """Фидбек из движка: префикс ``error:`` → код 1."""
        code = 1 if text.startswith("error:") else 0
        return CommandResult(output=text, code=code)


# ---------------------------------------------------------------------------
# Форматтеры снапшота
# ---------------------------------------------------------------------------


def format_status(snap: StatusSnapshot) -> str:
    """Полный снапшот текстом (команда ``status``)."""
    lines = [
        f"running: {'yes' if snap.running else 'no'}",
        f"bpm: {snap.bpm:.1f}",
        f"swing: {snap.swing:.2f}",
        f"clock: {snap.clock_source}"
        + (f" (pending: {snap.clock_pending})" if snap.clock_pending else ""),
        f"root: {snap.root}",
        f"scale: {snap.scale}",
        f"tracks: {len(snap.tracks)}",
        f"total mutations: {snap.total_mutations}",
        (
            f"ports: {sum(1 for p in snap.ports if p.status == 'connected')}"
            f"/{len(snap.ports)} ok"
        ),
    ]
    if snap.clock_error:
        lines.append(f"clock error: {snap.clock_error}")
    if snap.log_error:
        lines.append(f"log error: {snap.log_error}")
    lines.append("")
    tracks = format_tracks(snap)
    if tracks:
        lines.append(tracks)
    if snap.ports:
        lines.append("")
        for p in snap.ports:
            lines.append(f"port {p.name}: {p.status} — {p.detail}")
    return "\n".join(lines)


def format_tracks(snap: StatusSnapshot) -> str:
    """Список дорожек одной таблицей (команда ``tracks``)."""
    if not snap.tracks:
        return "no tracks"
    width = max(len(t.name) for t in snap.tracks)
    lines = []
    for t in snap.tracks:
        src = ",".join(t.sources) if t.sources else "—"
        port = t.port or "—"
        flags = " frozen" if t.frozen else ""
        lines.append(
            f"  {t.name:<{width}}  {t.kind:<7}  {t.profile:<10}  "
            f"port {port:<10}  src {src:<10}  mut {t.mutation_count}{flags}"
        )
    return "\n".join(lines)


def format_track(track: TrackSummary) -> str:
    """Детали одной дорожки (команда ``track show``)."""
    lines = [
        f"name: {track.name}",
        f"kind: {track.kind}",
        f"profile: {track.profile}",
        f"port: {track.port or '—'}",
        f"sources: {', '.join(track.sources) if track.sources else '—'}",
        f"mutations: {track.mutation_count}",
        f"frozen: {'yes' if track.frozen else 'no'}",
    ]
    return "\n".join(lines)


EchoFn = Callable[[str], None]
