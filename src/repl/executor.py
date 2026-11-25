"""Исполнитель команд REPL: Command + EngineControl → CommandResult.

Деструктивные команды проходят через политику подтверждений
(``--yes``/``-f`` в флагах — пропускает вопрос). Исключения из движка
ловятся и превращаются в текст ошибки — цикл REPL не падает.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from src.core.engine_result import EngineResult
from src.harmony.degree_names import parse_degrees
from src.harmony.voicings import Voicing
from src.repl.command import Command, CommandResult
from src.repl.confirm import DEFAULT_PROMPT, ConfirmPolicy, ConfirmPrompt
from src.repl.engine_control import EngineControl
from src.repl.parser import CommandParser, CommandSpec
from src.repl.render import render_text
from src.repl.status import StatusSnapshot, TrackSummary
from src.scripting.runner import ScriptRunner, format_report
from src.sync.midi_trace import MidiTraceEntry, format_entry

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

    def _resolve_track_prefix(self, text: str) -> tuple[str, str] | None:
        """Разделить ``<имя дорожки> <значение>`` по реально существующим дорожкам.

        Имена с пробелами не отличить от значений по форме токенов («Pad 1» и
        «Pad»), поэтому берётся самое длинное имя из сессии, за которым идёт
        непустой остаток. Не найдено — ``None``.
        """
        names = set(self._control.track_names())
        tokens = text.split()
        for i in range(len(tokens) - 1, 0, -1):
            name = " ".join(tokens[:i])
            if name in names:
                return name, " ".join(tokens[i:])
        return None

    @staticmethod
    def _no_track(text: str) -> CommandResult:
        return CommandResult(
            output=f"error: no track matches {text!r} (quote names with spaces)",
            code=1,
        )

    def _cmd_track_degrees(self, command: Command) -> CommandResult:
        resolved = self._resolve_track_prefix(command.args[0])
        if resolved is None:
            return self._no_track(command.args[0])
        name, rest = resolved
        try:
            degrees = parse_degrees(rest)
        except ValueError as exc:
            return CommandResult(output=f"error: {exc}", code=1)
        return self._feedback(self._control.set_track_degrees(name, degrees))

    def _cmd_track_voicing(self, command: Command) -> CommandResult:
        resolved = self._resolve_track_prefix(command.args[0])
        if resolved is None:
            return self._no_track(command.args[0])
        name, rest = resolved
        return self._feedback(self._control.set_track_voicing(name, rest))

    def _cmd_track_octave(self, command: Command) -> CommandResult:
        resolved = self._resolve_track_prefix(command.args[0])
        if resolved is None:
            return self._no_track(command.args[0])
        name, rest = resolved
        try:
            octave = int(rest)
        except ValueError:
            return CommandResult(output=f"error: {rest!r} is not a number", code=1)
        return self._feedback(self._control.set_track_octave(name, octave))

    def _cmd_track_inversion(self, command: Command) -> CommandResult:
        resolved = self._resolve_track_prefix(command.args[0])
        if resolved is None:
            return self._no_track(command.args[0])
        name, rest = resolved
        try:
            k = int(rest)
        except ValueError:
            return CommandResult(output=f"error: {rest!r} is not a number", code=1)
        return self._feedback(self._control.set_track_inversion(name, k))

    def _cmd_track_profile(self, command: Command) -> CommandResult:
        resolved = self._resolve_track_prefix(command.args[0])
        if resolved is None:
            return self._no_track(command.args[0])
        name, rest = resolved
        return self._feedback(self._control.set_track_profile(name, rest))

    def _cmd_voicings(self, command: Command) -> CommandResult:
        return CommandResult(output="voicings: " + ", ".join(sorted(Voicing.VOICINGS)))

    def _cmd_track_delete(self, command: Command) -> CommandResult:
        return self._feedback(self._control.remove_track(command.args[0]))

    def _cmd_track_sources(self, command: Command) -> CommandResult:
        """``track sources <дорожка> [<источник> ...]`` — подписка на гармонию.

        Существование дорожки и источников проверяет фасад: одна точка правды,
        одинаковые сообщения для REPL и Push 2.
        """
        name = command.args[0]
        sources = command.args[1:]
        return self._feedback(self._control.set_track_sources(name, *sources))

    def _cmd_track_route(self, command: Command) -> CommandResult:
        return self._feedback(
            self._control.route_track(command.args[0], command.args[1])
        )

    def _cmd_track_unroute(self, command: Command) -> CommandResult:
        return self._feedback(self._control.unroute_track(command.args[0]))

    def _cmd_track_chain(self, command: Command) -> CommandResult:
        """``track chain <name> show | add <stage> [k=v ...] | remove <n>``.

        Существование дорожки и валидность этапа проверяет фасад: одна
        точка правды, одинаковые сообщения для REPL, Push 2 и скриптов.
        Ошибки разбора (действие, пары k=v, индекс) — здесь, код 1,
        цикл живёт.
        """
        name, action = command.args[0], command.args[1].lower()
        if action == "show":
            return self._feedback(self._control.track_chain(name))
        if action == "add":
            return self._track_chain_add(name, command.args[2:])
        if action == "remove":
            return self._track_chain_remove(name, command.args[2:])
        return CommandResult(
            output=(
                f"error: unknown action {action!r} "
                "(choose from: show, add, remove)\n"
                "usage: track chain <name> show | add <stage> [k=v ...] | remove <n>"
            ),
            code=1,
        )

    def _track_chain_add(self, name: str, tokens: tuple[str, ...]) -> CommandResult:
        """``add <stage> [k=v ...]``: этап и пары параметров строками."""
        if not tokens:
            return CommandResult(
                output=(
                    "error: track chain add: missing stage name\n"
                    "usage: track chain <name> add <stage> [k=v ...]"
                ),
                code=1,
            )
        params: dict[str, str] = {}
        for token in tokens[1:]:
            if "=" not in token:
                return CommandResult(
                    output=(
                        f"error: параметр {token!r} без значения "
                        "(ожидается «ключ=значение»)"
                    ),
                    code=1,
                )
            key, _, value = token.partition("=")
            if key in params:
                return CommandResult(
                    output=f"error: дубликат параметра {key!r}",
                    code=1,
                )
            params[key] = value
        return self._feedback(self._control.track_chain_add(name, tokens[0], params))

    def _track_chain_remove(self, name: str, tokens: tuple[str, ...]) -> CommandResult:
        """``remove <n>``: 1-based индекс этапа."""
        if not tokens:
            return CommandResult(
                output=(
                    "error: track chain remove: missing index\n"
                    "usage: track chain <name> remove <n>"
                ),
                code=1,
            )
        raw = tokens[0]
        try:
            index = int(raw)
        except ValueError:
            return CommandResult(output=f"error: {raw!r} is not a number", code=1)
        return self._feedback(self._control.track_chain_remove(name, index))

    def _cmd_drum_add(self, command: Command) -> CommandResult:
        """``drum add [name]`` — создать drum-дорожку (имя опционально)."""
        name = command.args[0] if command.args else None
        return self._feedback(self._control.create_drum_track(name))

    def _cmd_drum_pattern(self, command: Command) -> CommandResult:
        """``drum pattern <track> <lane> [<notation...>]``.

        Два аргумента (без нотации) — очистка lane'а (design §9).
        Нотация может содержать пробелы и ``|`` — остаточные токены
        джойнятся пробелом (грамматика их игнорирует).
        """
        name, lane = command.args[0], command.args[1]
        notation = " ".join(command.args[2:])
        return self._feedback(self._control.set_drum_pattern(name, lane, notation))

    def _cmd_root(self, command: Command) -> CommandResult:
        return self._feedback(self._control.set_root(command.args[0]))

    def _cmd_scale(self, command: Command) -> CommandResult:
        return self._feedback(self._control.set_scale(command.args[0]))

    def _cmd_mutations(self, command: Command) -> CommandResult:
        snap = self._control.get_status()
        return CommandResult(output=f"total mutations: {snap.total_mutations}")

    def _cmd_evolve(self, command: Command) -> CommandResult:
        """``evolve`` — все дорожки; ``evolve <name>`` — одна (spec §3)."""
        name = command.args[0] if command.args else None
        return self._feedback(self._control.request_mutation(name))

    def _cmd_undo(self, command: Command) -> CommandResult:
        return self._feedback(self._control.undo_mutation(command.args[0]))

    def _cmd_recall(self, command: Command) -> CommandResult:
        *name_words, version = command.args
        try:
            index = int(version)
        except ValueError:
            return CommandResult(
                output=f"error: {version!r} is not a version number", code=1
            )
        return self._feedback(self._control.recall_version(" ".join(name_words), index))

    def _cmd_history(self, command: Command) -> CommandResult:
        """``history`` — сводка по всем; ``history <name>`` — по одной."""
        if command.args:
            return self._feedback(self._control.mutation_history(command.args[0]))
        snap = self._control.get_status()
        return CommandResult(output=format_histories(snap))

    def _cmd_midi(self, command: Command) -> CommandResult:
        """``midi`` — поток на выход; ``midi on|off|clear`` — управление записью."""
        arg = command.args[0].strip().lower() if command.args else ""
        if arg in ("on", "off"):
            return self._feedback(self._control.set_midi_trace(arg == "on"))
        if arg == "clear":
            return self._feedback(self._control.clear_midi_trace())

        n = DEFAULT_LOG_LINES
        if arg:
            try:
                n = int(arg)
            except ValueError:
                return CommandResult(
                    output=f"error: {arg!r} is not a number (or on/off/clear)", code=1
                )

        entries: list[MidiTraceEntry] = []
        for entry in self._control.midi_trace(n):
            if isinstance(entry, MidiTraceEntry):
                entries.append(entry)
        if not entries:
            return CommandResult(output="no MIDI events recorded (midi on to enable)")

        owners = self._trace_owners()
        lines = [
            format_entry(entry, owners.get((entry.port, entry.channel)))
            for entry in entries
        ]
        return CommandResult(output="\n".join(lines))

    def _cmd_script_run(self, command: Command) -> CommandResult:
        """``script run <file>`` — исполнить скрипт (синхронный батч).

        Отчёт раннера: линии фидбека движка + diagnostics/ошибка.
        Код 1 при diagnostics или ошибке исполнения; REPL живёт.
        """
        report = ScriptRunner(self._control).run_file(Path(command.args[0]))
        code = 1 if report.error is not None or report.diagnostics else 0
        return CommandResult(output=format_report(report), code=code)

    def _cmd_script_check(self, command: Command) -> CommandResult:
        """``script check <file>`` — валидация скрипта без исполнения."""
        diagnostics = ScriptRunner(self._control).check_file(Path(command.args[0]))
        if not diagnostics:
            return CommandResult(output=f"script {command.args[0]}: ok")
        lines = [f"script {command.args[0]}: {len(diagnostics)} diagnostic(s)"]
        lines.extend(d.format() for d in diagnostics)
        return CommandResult(output="\n".join(lines), code=1)

    def _cmd_capture(self, command: Command) -> CommandResult:
        """``capture`` — статус захвата SMF."""
        return self._feedback(self._control.capture_status())

    def _cmd_capture_start(self, command: Command) -> CommandResult:
        """``capture start [path]`` — начать запись (путь опционален)."""
        path = command.args[0] if command.args else None
        return self._feedback(self._control.capture_start(path))

    def _cmd_capture_stop(self, command: Command) -> CommandResult:
        """``capture stop`` — остановить запись и создать SMF-файл."""
        return self._feedback(self._control.capture_stop())

    def _trace_owners(self) -> dict[tuple[str, int], str]:
        """Кто играет на паре (порт, канал) — чтобы подписать события дорожкой."""
        return self._control.track_routes()

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
    def _feedback(result: EngineResult) -> CommandResult:
        """Результат движка → вывод REPL; ошибка → код 1."""
        return CommandResult(output=render_text(result), code=1 if result.error else 0)


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
        state = " pending" if t.pending else ""
        lines.append(
            f"  {t.name:<{width}}  {t.kind:<7}  {t.profile:<10}  "
            f"port {port:<10}  src {src:<10}  mut {t.mutation_count}{state}"
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
    ]
    return "\n".join(lines)


def format_histories(snap: StatusSnapshot) -> str:
    """Сводка историй версий всех дорожек (команда ``history``)."""
    if not snap.tracks:
        return "no tracks"
    width = max(len(t.name) for t in snap.tracks)
    lines = []
    for t in snap.tracks:
        if t.history_len == 0:
            versions = "no history"
        else:
            versions = f"version {t.mutation_count} ({t.history_len} total)"
        state = " pending" if t.pending else ""
        lines.append(f"  {t.name:<{width}}  {versions}{state}")
    return "\n".join(lines)


EchoFn = Callable[[str], None]
