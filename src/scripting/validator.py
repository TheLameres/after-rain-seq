"""Статическая валидация скрипта: compile → AST-линт против модели фасада.

Валидатор (план G2 §3.6) ловит до исполнения:

- синтаксические ошибки (``compile()`` → diagnostic с line/col);
- вызовы фасада ``session.<method>(...)`` — метод таблицы
  (рефлексия ``inspect.signature(ScriptSession)``), счёт и имена
  аргументов, неизвестные kwarg;
- конструкторы DTO ``TrackProposal(...)/DrumProposal(...)`` — поля из
  ``dataclasses.fields``, семантика литералов против реестров
  (``PROFILES``, ``Voicing.VOICINGS``), диапазоны channel/degrees;
- переопределение инжектированных имён (``session``, DTO) присваиванием.

Не-литеральные аргументы пропускаются — рантайм проверит фасад.
Отчёт сортируется по ``(line, col)``; пустой список — валидно.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import logging
from dataclasses import dataclass
from typing import Final

from src.core.proposal import DrumProposal, TrackProposal
from src.harmony.voicings import Voicing
from src.scripting.error import ScriptDiagnostic
from src.scripting.script_session import ScriptSession
from src.session.model.melodic_profile import PROFILES

log = logging.getLogger(__name__)

# Имена, инжектируемые в globals скрипта: их переопределение — diagnostic.
INJECTED_NAMES: Final[frozenset[str]] = frozenset(
    {"session", "TrackProposal", "DrumProposal"}
)


def _const_int(node: ast.expr) -> int | None:
    """Целочисленный литерал AST-узла: ``Constant`` или унарный минус над ним.

    ``-1`` в AST — ``UnaryOp(USub, Constant(1))``, не ``Constant``: без
    распознавания унарного минуса отрицательные литералы пропускались бы
    как «не-литералы» (план G2 §3.6: degrees ⊆ 0..13 — минус обязан
    отбраковываться валидатором).

    Аргументы:
        node: AST-узел элемента списка.

    Returns:
        Целое значение литерала или ``None`` (не-литерал / не целое).
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, int)
    ):
        return -node.operand.value
    return None


@dataclass(frozen=True)
class _MethodSpec:
    """Спецификация публичного метода фасада для AST-линта.

    Атрибуты:
        positional: Имена позиционных параметров (без ``self``).
        required: Минимальное число позиционных аргументов (без дефолта).
        keywords: Все имена параметров (позиционные + kw-only, kwarg-проверка).
        var_positional: Метод принимает ``*args`` — лимита позиционных нет.
    """

    positional: tuple[str, ...]
    required: int
    keywords: frozenset[str]
    var_positional: bool


def _facade_methods() -> dict[str, _MethodSpec]:
    """Таблица методов фасада — рефлексией из ``inspect.signature``.

    Таблица не дублируется вручную: новый метод ``ScriptSession``
    автоматически попадает в линт (и в фасад скрипта).

    Returns:
        Имя метода → спека для проверки вызова.
    """
    methods: dict[str, _MethodSpec] = {}
    for name, member in inspect.getmembers(ScriptSession, inspect.isfunction):
        if name.startswith("_"):
            continue
        params = list(inspect.signature(member).parameters.values())[1:]  # без self
        positional = tuple(
            p.name
            for p in params
            if p.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        )
        required = sum(
            1
            for p in params
            if p.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
            and p.default is inspect.Parameter.empty
        )
        keywords = frozenset(
            p.name
            for p in params
            if p.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
        )
        methods[name] = _MethodSpec(
            positional=positional,
            required=required,
            keywords=keywords,
            var_positional=any(
                p.kind == inspect.Parameter.VAR_POSITIONAL for p in params
            ),
        )
    return methods


class ScriptValidator:
    """Двухступенчатая проверка скрипта: compile → AST-линт.

    Реестры берутся из кода (``PROFILES``, ``Voicing.VOICINGS``) —
    валидатор не дублирует их копиями.
    """

    def __init__(self) -> None:
        self._facade: dict[str, _MethodSpec] = _facade_methods()
        self._dto_fields: dict[str, tuple[str, ...]] = {
            TrackProposal.__name__: tuple(
                field.name for field in dataclasses.fields(TrackProposal)
            ),
            DrumProposal.__name__: tuple(
                field.name for field in dataclasses.fields(DrumProposal)
            ),
        }

    def validate_source(self, source: str, filename: str) -> list[ScriptDiagnostic]:
        """Валидация: compile → AST-обход. Пустой список — валидно.

        Аргументы:
            source: Исходный текст скрипта.
            filename: Имя файла (для отчёта).

        Returns:
            Отсортированный по ``(line, col)`` список диагностик.
        """
        try:
            tree = ast.parse(source, filename=filename)
        except SyntaxError as exc:
            diagnostic = ScriptDiagnostic(
                filename=filename,
                line=exc.lineno or 1,
                col=(exc.offset or 1) - 1,
                message=f"syntax error: {exc.msg}",
            )
            return [diagnostic]
        diagnostics: list[ScriptDiagnostic] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                diagnostics.extend(self._check_call(node, filename))
            elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                diagnostics.extend(self._check_assignment(node, filename))
        return sorted(diagnostics, key=lambda d: (d.line, d.col))

    # ------------------------------------------------------------------
    # AST-линт: вызовы
    # ------------------------------------------------------------------

    def _check_call(self, node: ast.Call, filename: str) -> list[ScriptDiagnostic]:
        """Проверить один вызов: фасад (``session.*``) или DTO-конструктор."""
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "session"
        ):
            return self._check_facade_call(node, func.attr, filename)
        if isinstance(func, ast.Name) and func.id in self._dto_fields:
            return self._check_dto_call(node, func.id, filename)
        return []

    def _check_facade_call(
        self, node: ast.Call, method_name: str, filename: str
    ) -> list[ScriptDiagnostic]:
        """Вызов ``session.<method>``: метод, счёт и имена аргументов."""
        spec = self._facade.get(method_name)
        if spec is None:
            return [
                ScriptDiagnostic(
                    filename=filename,
                    line=node.lineno,
                    col=node.col_offset,
                    message=f"unknown session method {method_name!r}",
                )
            ]
        diagnostics: list[ScriptDiagnostic] = []
        kwarg_names = [kw.arg for kw in node.keywords if kw.arg is not None]
        n_positional = len(node.args)
        if spec.var_positional is False and n_positional > len(spec.positional):
            diagnostics.append(
                ScriptDiagnostic(
                    filename=filename,
                    line=node.lineno,
                    col=node.col_offset,
                    message=(
                        f"session.{method_name}: too many positional arguments "
                        f"(max {len(spec.positional)}, got {n_positional})"
                    ),
                )
            )
        for kwarg in kwarg_names:
            if kwarg not in spec.keywords:
                diagnostics.append(
                    ScriptDiagnostic(
                        filename=filename,
                        line=node.lineno,
                        col=node.col_offset,
                        message=f"session.{method_name}: unknown keyword {kwarg!r}",
                    )
                )
        if n_positional > 0 and any(
            kwarg in spec.positional[:n_positional] for kwarg in kwarg_names
        ):
            diagnostics.append(
                ScriptDiagnostic(
                    filename=filename,
                    line=node.lineno,
                    col=node.col_offset,
                    message=(
                        f"session.{method_name}: multiple values for argument "
                        "(keyword overrides a positional argument)"
                    ),
                )
            )
        covered = n_positional + sum(
            1 for kwarg in kwarg_names if kwarg in spec.positional
        )
        if covered < spec.required:
            diagnostics.append(
                ScriptDiagnostic(
                    filename=filename,
                    line=node.lineno,
                    col=node.col_offset,
                    message=(
                        f"session.{method_name}: missing required argument "
                        f"(needs {spec.required}, got {covered})"
                    ),
                )
            )
        return diagnostics

    def _check_dto_call(
        self, node: ast.Call, dto_name: str, filename: str
    ) -> list[ScriptDiagnostic]:
        """Конструктор DTO: поля из ``dataclasses.fields`` + семантика литералов."""
        fields = self._dto_fields[dto_name]
        diagnostics: list[ScriptDiagnostic] = []
        if len(node.args) > len(fields):
            diagnostics.append(
                ScriptDiagnostic(
                    filename=filename,
                    line=node.lineno,
                    col=node.col_offset,
                    message=(
                        f"{dto_name}: too many positional arguments "
                        f"(max {len(fields)}, got {len(node.args)})"
                    ),
                )
            )
        for keyword in node.keywords:
            if keyword.arg is None:  # **unpacking — рантайм проверит
                continue
            if keyword.arg not in fields:
                diagnostics.append(
                    ScriptDiagnostic(
                        filename=filename,
                        line=node.lineno,
                        col=node.col_offset,
                        message=f"{dto_name}: unknown field {keyword.arg!r}",
                    )
                )
                continue
            diagnostic = self._check_dto_field(
                dto_name,
                keyword.arg,
                keyword.value,
                filename,
                node.lineno,
                node.col_offset,
            )
            if diagnostic is not None:
                diagnostics.append(diagnostic)
        for index, arg in enumerate(node.args):
            if index >= len(fields):
                break
            diagnostic = self._check_dto_field(
                dto_name, fields[index], arg, filename, node.lineno, node.col_offset
            )
            if diagnostic is not None:
                diagnostics.append(diagnostic)
        return diagnostics

    def _check_dto_field(
        self,
        dto_name: str,
        field: str,
        value: ast.expr,
        filename: str,
        line: int,
        col: int,
    ) -> ScriptDiagnostic | None:
        """Семантика литерального аргумента DTO; не-литерал → ``None``.

        Литералы: ``ast.Constant`` (строка/число), унарный минус над целым
        ``Constant`` (``_const_int``) и ``ast.List/ast.Tuple`` из целых
        констант (degrees). Всё остальное — переменные/выражения:
        рантайм проверит фасад/DTO.
        """
        literal: object
        if isinstance(value, ast.Constant):
            literal = value.value
        elif isinstance(value, (ast.List, ast.Tuple)):
            ints: list[int] = []
            for elt in value.elts:
                number = _const_int(elt)
                if number is None:
                    return None
                ints.append(number)
            literal = tuple(ints)
        else:
            return None
        if field == "name" and isinstance(literal, str) and not literal.strip():
            return ScriptDiagnostic(
                filename=filename,
                line=line,
                col=col,
                message=f"{dto_name}: name must be a non-empty string",
            )
        if dto_name != "TrackProposal":
            return None
        if (
            field == "profile_name"
            and isinstance(literal, str)
            and literal not in PROFILES
        ):
            return ScriptDiagnostic(
                filename=filename,
                line=line,
                col=col,
                message=(
                    f"unknown profile {literal!r} "
                    f"(choose: {', '.join(sorted(PROFILES))})"
                ),
            )
        if (
            field == "voicing"
            and isinstance(literal, str)
            and literal not in Voicing.VOICINGS
        ):
            return ScriptDiagnostic(
                filename=filename,
                line=line,
                col=col,
                message=(
                    f"unknown voicing {literal!r} "
                    f"(choose: {', '.join(sorted(Voicing.VOICINGS))})"
                ),
            )
        if field == "degrees" and isinstance(literal, tuple):
            for degree in literal:
                if (
                    isinstance(degree, int)
                    and not isinstance(degree, bool)
                    and not 0 <= degree <= 13
                ):
                    return ScriptDiagnostic(
                        filename=filename,
                        line=line,
                        col=col,
                        message=f"degrees out of 0..13: {degree!r}",
                    )
        if (
            field == "channel"
            and isinstance(literal, int)
            and not isinstance(literal, bool)
            and not 0 <= literal <= 15
        ):
            return ScriptDiagnostic(
                filename=filename,
                line=line,
                col=col,
                message=f"channel out of 0..15: {literal!r}",
            )
        return None

    # ------------------------------------------------------------------
    # AST-линт: присваивания
    # ------------------------------------------------------------------

    def _check_assignment(
        self, node: ast.Assign | ast.AugAssign | ast.AnnAssign, filename: str
    ) -> list[ScriptDiagnostic]:
        """Переопределение инжектированного имени присваиванием — diagnostic."""
        diagnostics: list[ScriptDiagnostic] = []
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        else:
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id in INJECTED_NAMES:
                diagnostics.append(
                    ScriptDiagnostic(
                        filename=filename,
                        line=node.lineno,
                        col=node.col_offset,
                        message=(
                            f"script: injected name {target.id!r} reassigned "
                            "(session/DTO names come from the runner)"
                        ),
                    )
                )
        return diagnostics
