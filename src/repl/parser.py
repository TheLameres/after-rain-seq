"""Парсер команд REPL — строка → :class:`Command` (git-стиль).

Синтаксис: ``домен [действие] [аргументы] [--flags]``.

Правила:
    - Лишние пробелы и регистр доменов не важны (``CLOCK SOURCE MIDI`` ок).
    - Имена дорожек с пробелами: аргументы джойнятся (``track delete Pad 1``)
      или берутся в кавычках (``track delete "Pad 1"``) — shlex.
    - Неизвестная команда → список похожих команд (difflib) + ``help``.
    - Ошибка синтаксиса → usage-строка команды.
"""

from __future__ import annotations

import difflib
import shlex
from dataclasses import dataclass

from src.repl.command import Command

# Источники клока — для подсказок и валидации.
CLOCK_SOURCE_NAMES: tuple[str, ...] = ("internal", "midi", "link")


@dataclass(frozen=True)
class CommandSpec:
    """Спецификация одной команды из таблицы.

    Атрибуты:
        name: Каноническое имя (``"track add"``).
        domain: Первый токен.
        action: Второй токен-действие или ``None``.
        usage: Usage-строка для справки и ошибок синтаксиса.
        help: Однострочное описание для ``help``.
        destructive: Требует подтверждения y/N (без ``--yes``/``-f``).
        min_args: Минимальное число аргументов.
        max_args: Максимальное число аргументов.
        join_args: Склеить все аргументы в одну строку (имена дорожек).
        choices: Допустимые значения единственного аргумента или ``None``.
    """

    name: str
    domain: str
    action: str | None
    usage: str
    help: str
    destructive: bool = False
    min_args: int = 0
    max_args: int = 0
    join_args: bool = False
    choices: tuple[str, ...] | None = None


_SPECS: tuple[CommandSpec, ...] = (
    CommandSpec(
        name="status",
        domain="status",
        action=None,
        usage="status",
        help="Полный снапшот состояния движка",
    ),
    CommandSpec(
        name="start",
        domain="start",
        action=None,
        usage="start",
        help="Запустить транспорт",
    ),
    CommandSpec(
        name="stop",
        domain="stop",
        action=None,
        usage="stop [--yes]",
        help="Остановить транспорт (деструктивно: all notes off)",
        destructive=True,
    ),
    CommandSpec(
        name="bpm",
        domain="bpm",
        action=None,
        usage="bpm <20..300>",
        help="Установить BPM",
        min_args=1,
        max_args=1,
    ),
    CommandSpec(
        name="clock",
        domain="clock",
        action=None,
        usage="clock",
        help="Статус клока: source, pending, link peers, ошибка",
    ),
    CommandSpec(
        name="clock source",
        domain="clock",
        action="source",
        usage="clock source <internal|midi|link>",
        help="Переключить источник клока (на ближайшей доле)",
        min_args=1,
        max_args=1,
        choices=CLOCK_SOURCE_NAMES,
    ),
    CommandSpec(
        name="ports",
        domain="ports",
        action=None,
        usage="ports",
        help="Список портов: имя, статус, детали",
    ),
    CommandSpec(
        name="ports scan",
        domain="ports",
        action="scan",
        usage="ports scan",
        help="Принудительный rescan портов",
    ),
    CommandSpec(
        name="ports switch",
        domain="ports",
        action="switch",
        usage="ports switch <label> <match>",
        help="Перенаправить порт на другое устройство (рантайм-only, serial очищается)",
        min_args=2,
        max_args=2,
    ),
    CommandSpec(
        name="track degrees",
        domain="track",
        action="degrees",
        usage="track degrees <name> <степени...>  (римские I..XIV или числа 0..13)",
        help='Задать прогрессию ступеней дорожки (например: track degrees "Pad 1" I IV V I)',
        min_args=1,
        max_args=64,
        join_args=True,
    ),
    CommandSpec(
        name="track voicing",
        domain="track",
        action="voicing",
        usage="track voicing <name> <voicing>",
        help="Задать voicing дорожки (список: voicings)",
        min_args=1,
        max_args=64,
        join_args=True,
    ),
    CommandSpec(
        name="track inversion",
        domain="track",
        action="inversion",
        usage="track inversion <name> <k>",
        help="Задать обращение аккорда дорожки (0..len(voicing)-1)",
        min_args=1,
        max_args=64,
        join_args=True,
    ),
    CommandSpec(
        name="track profile",
        domain="track",
        action="profile",
        usage="track profile <name> <profile>",
        help="Сменить профиль дорожки (cc_only <-> нота требует перезапуска)",
        min_args=1,
        max_args=64,
        join_args=True,
    ),
    CommandSpec(
        name="voicings",
        domain="voicings",
        action=None,
        usage="voicings",
        help="Список доступных voicing",
    ),
    CommandSpec(
        name="tracks",
        domain="tracks",
        action=None,
        usage="tracks",
        help="Список дорожек: имя, профиль, источники, mut, frozen",
    ),
    CommandSpec(
        name="track show",
        domain="track",
        action="show",
        usage="track show <name>",
        help="Детали одной дорожки",
        min_args=1,
        max_args=16,
        join_args=True,
    ),
    CommandSpec(
        name="track add",
        domain="track",
        action="add",
        usage="track add <profile> [channel]",
        help="Создать melodic-дорожку профиля (канал — автоназначение)",
        min_args=1,
        max_args=2,
    ),
    CommandSpec(
        name="track channel",
        domain="track",
        action="channel",
        usage="track channel <name> <ch 0..15>",
        help="Сменить MIDI-канал дорожки (движки подхватывают live)",
        min_args=2,
        max_args=2,
    ),
    CommandSpec(
        name="track delete",
        domain="track",
        action="delete",
        usage="track delete <name> [--yes]",
        help="Удалить дорожку (зависимые получают sources = ())",
        destructive=True,
        min_args=1,
        max_args=16,
        join_args=True,
    ),
    CommandSpec(
        name="track route",
        domain="track",
        action="route",
        usage="track route <name> <label>  (имена с пробелами — в кавычках)",
        help="Привязать дорожку к MIDI-порту; старый порт глушится",
        min_args=2,
        max_args=2,
    ),
    CommandSpec(
        name="track unroute",
        domain="track",
        action="unroute",
        usage="track unroute <name>",
        help="Отключить дорожку от порта — тишина, сессия живёт",
        min_args=1,
        max_args=16,
        join_args=True,
    ),
    CommandSpec(
        name="root",
        domain="root",
        action=None,
        usage="root <note>",
        help="Сменить тонику (root A, root F#)",
        min_args=1,
        max_args=1,
    ),
    CommandSpec(
        name="scale",
        domain="scale",
        action=None,
        usage="scale <mode>",
        help="Сменить лад (scale dorian); валидация 8 ладов",
        min_args=1,
        max_args=1,
    ),
    CommandSpec(
        name="freeze",
        domain="freeze",
        action=None,
        usage="freeze [name]",
        help="Заморозить все дорожки или одну",
        max_args=16,
        join_args=True,
    ),
    CommandSpec(
        name="evolve",
        domain="evolve",
        action=None,
        usage="evolve",
        help="Разморозить и продолжить эволюцию",
    ),
    CommandSpec(
        name="mutations",
        domain="mutations",
        action=None,
        usage="mutations",
        help="Счётчик мутаций",
    ),
    CommandSpec(
        name="logs",
        domain="logs",
        action=None,
        usage="logs [N]",
        help="Последние N строк лога (default 20)",
        max_args=1,
    ),
    CommandSpec(
        name="help",
        domain="help",
        action=None,
        usage="help [команда]",
        help="Справка; без аргумента — список команд",
        max_args=1,
    ),
    CommandSpec(
        name="exit",
        domain="exit",
        action=None,
        usage="exit",
        help="Остановить приложение и выйти",
    ),
    CommandSpec(
        name="quit",
        domain="quit",
        action=None,
        usage="quit",
        help="Синоним exit",
    ),
)

_BY_NAME: dict[str, CommandSpec] = {s.name: s for s in _SPECS}
_BY_DOMAIN: dict[str, list[CommandSpec]] = {}
for _spec in _SPECS:
    _BY_DOMAIN.setdefault(_spec.domain, []).append(_spec)


class CommandParser:
    """Разбор строки ввода в :class:`Command`.

    Ошибки разбора не бросаются — кладутся в ``Command.error`` +
    ``Command.usage`` (executor печатает и идёт дальше).
    """

    def parse(self, line: str) -> Command:
        """Разобрать строку. Пустой ввод → пустая команда (no-op)."""
        try:
            tokens = shlex.split(line)
        except ValueError as exc:
            return Command(error=f"syntax error: {exc}", usage="help")

        flags = frozenset(t.lstrip("-") for t in tokens if t.startswith("-"))
        positional = tuple(t for t in tokens if not t.startswith("-"))

        if not positional:
            return Command(flags=flags)

        domain = positional[0].lower()
        specs = _BY_DOMAIN.get(domain)
        if specs is None:
            return self._unknown(positional[0], flags, positional)

        # Выбор действия (action) среди спецификаций домена.
        action: str | None = None
        rest: tuple[str, ...] = positional[1:]
        action_names = {s.action for s in specs if s.action is not None}
        bare = next((s for s in specs if s.action is None), None)
        if action_names:
            if not rest:
                if bare is None:
                    return self._no_action(domain, action_names, flags)
                # Bare-команда без аргументов (``clock``, ``ports``)
                return self._check_args(bare, positional, None, (), flags)
            candidate = rest[0].lower()
            if candidate in action_names:
                action = candidate
                rest = rest[1:]
            elif bare is None:
                return self._unknown_action(domain, rest[0], action_names, flags)
            # иначе: аргументы bare-команды (проверит _check_args по счёту)

        spec = next(s for s in specs if s.action == action)
        return self._check_args(spec, positional, action, rest, flags)

    # ------------------------------------------------------------------
    # Справка
    # ------------------------------------------------------------------

    def specs(self) -> tuple[CommandSpec, ...]:
        """Все спецификации (для help и автодополнения)."""
        return _SPECS

    def help_text(self, name: str | None = None) -> str:
        """Текст справки: список команд или одна команда."""
        if name is None:
            lines = ["Доступные команды:", ""]
            for spec in _SPECS:
                marker = " (!)" if spec.destructive else ""
                lines.append(f"  {spec.usage:<42} {spec.help}{marker}")
            lines += [
                "",
                "(!) — деструктивная команда, спросит подтверждение y/N",
                "Для любой команды флаги --yes / -f подтверждают действие.",
            ]
            return "\n".join(lines)
        command_spec = _BY_NAME.get(name.lower())
        if command_spec is None:
            return f"error: unknown command {name!r} (see 'help')"
        return f"{command_spec.usage}\n\n{command_spec.help}"

    # ------------------------------------------------------------------
    # Внутренние хелперы
    # ------------------------------------------------------------------

    @staticmethod
    def _check_args(
        spec: CommandSpec,
        argv: tuple[str, ...],
        action: str | None,
        args: tuple[str, ...],
        flags: frozenset[str],
    ) -> Command:
        if len(args) < spec.min_args or len(args) > spec.max_args:
            plural = "s" if spec.max_args != 1 else ""
            return Command(
                argv=argv,
                name=spec.name,
                domain=spec.domain,
                action=action,
                flags=flags,
                error=(
                    f"{spec.name}: expected {spec.min_args}"
                    + (f"..{spec.max_args}" if spec.max_args != spec.min_args else "")
                    + f" argument{plural}, got {len(args)}"
                ),
                usage=f"usage: {spec.usage}",
            )
        if spec.choices is not None and args and args[0].lower() not in spec.choices:
            return Command(
                argv=argv,
                name=spec.name,
                domain=spec.domain,
                action=action,
                flags=flags,
                error=(
                    f"{spec.name}: unknown {args[0]!r} "
                    f"(choose from: {', '.join(spec.choices)})"
                ),
                usage=f"usage: {spec.usage}",
            )
        joined = (" ".join(args),) if spec.join_args and args else args
        return Command(
            argv=argv,
            name=spec.name,
            domain=spec.domain,
            action=action,
            args=joined,
            flags=flags,
        )

    @staticmethod
    def _unknown(token: str, flags: frozenset[str], argv: tuple[str, ...]) -> Command:
        known = sorted(_BY_NAME)
        close = difflib.get_close_matches(token.lower(), known, n=3, cutoff=0.4)
        hint = f" Did you mean: {', '.join(close)}?" if close else ""
        return Command(
            argv=argv,
            domain=token.lower(),
            flags=flags,
            error=f"unknown command: {token!r}.{hint} Type 'help' for commands.",
        )

    @staticmethod
    def _no_action(
        domain: str, action_names: set[str], flags: frozenset[str]
    ) -> Command:
        actions = " | ".join(sorted(action_names))
        return Command(
            domain=domain,
            flags=flags,
            error=f"{domain}: missing action (choose from: {actions})",
        )

    @staticmethod
    def _unknown_action(
        domain: str, token: str, action_names: set[str], flags: frozenset[str]
    ) -> Command:
        actions = " | ".join(sorted(action_names))
        close = difflib.get_close_matches(token.lower(), sorted(action_names), n=1)
        hint = f" Did you mean: {close[0]}?" if close else ""
        return Command(
            domain=domain,
            action=token.lower(),
            flags=flags,
            error=f"{domain}: unknown action {token!r}.{hint} Choose from: {actions}.",
        )
