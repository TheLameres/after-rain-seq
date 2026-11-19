"""Скриптовый движок: Python DSL для подъёма сессии (план G2).

Модель «скрипт = синхронный батч типизированных вызовов»:

- скрипт исполняется в globals с инжектированными ``session``,
  ``TrackProposal``, ``DrumProposal`` — импортов в скриптах нет;
- все вызовы проходят через ABC :class:`src.repl.engine_control.EngineControl`
  — единственный фасад движка;
- валидация (``compile`` + AST-линт) прогоняется до исполнения:
  diagnostics ⇒ побочных эффектов не будет.

Направление зависимостей (правила слоёв): пакет импортирует repl (только
ABC-модуль ``engine_control``), core, harmony, session.model — строго вниз,
циклов нет. ``app/`` пакет не импортирует. REPL (executor) импортирует
этот пакет: scripting — sibling ниже repl по зависимости (scripting
зависит только от ABC и core/harmony/session.model, а app-слой импортирует
ABC из repl).
"""

from __future__ import annotations

from src.scripting.error import ScriptDiagnostic, ScriptError
from src.scripting.runner import ScriptRunner, format_report
from src.scripting.script_session import ScriptSession

__all__ = [
    "ScriptDiagnostic",
    "ScriptError",
    "ScriptRunner",
    "ScriptSession",
    "format_report",
]
