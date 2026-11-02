"""Автодополнение REPL — NestedCompleter + динамические дополнения.

Статическая часть строится из таблицы команд parser'а
(``домен → {действие}``). Динамические части дергают
:class:`EngineControl` при TAB-нажатии (дешёво: снапшот уже в памяти):

    - ``track show/delete/freeze <TAB>`` → имена из ``list_tracks()``
    - ``freeze <TAB>`` → имена дорожек (опциональный аргумент)
    - ``scale <TAB>`` → 8 ладов (провайдер, см. main.py)
    - ``root <TAB>`` → 12 нот
    - ``track add <TAB>`` → профили (провайдер, см. main.py)
    - ``clock source <TAB>`` → internal/midi/link

Провайдеры передаются снаружи (из main.py), чтобы ``repl/`` не импортировал
``src.session``/``src.harmony`` и оставался зависимым только от контракта.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

from prompt_toolkit.completion import (
    CompleteEvent,
    Completer,
    Completion,
    NestedCompleter,
)
from prompt_toolkit.document import Document

from src.repl.engine_control import EngineControl
from src.repl.parser import CLOCK_SOURCE_NAMES, CommandParser

# 12 нот — музыкальная константа, не состояние движка.
NOTES: tuple[str, ...] = (
    "C",
    "C#",
    "D",
    "D#",
    "E",
    "F",
    "F#",
    "G",
    "G#",
    "A",
    "A#",
    "B",
)

# Провайдер динамических дополнений: возвращает варианты по ключу.
Provider = Callable[[], Iterable[str]]


class ReplCompleter(Completer):
    """Комбинированный комплитер: динамические контексты + статическое дерево.

    Параметры:
        control: Контракт движка (имена дорожек берутся из снапшота).
        providers: Ключ → callable. Поддерживаемые ключи:
            ``"track"`` (имена дорожек), ``"scale"`` (лады),
            ``"profile"`` (профили). Необязательны — отсутствующие
            ключи дают пустое дополнение.
    """

    def __init__(
        self,
        control: EngineControl,
        providers: Mapping[str, Provider] | None = None,
    ) -> None:
        self._control = control
        self._providers = dict(providers or {})
        self._static = self._build_static()

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        """Точка входа prompt_toolkit."""
        text = document.text_before_cursor
        words = text.split()
        if text and not text[-1].isspace():
            prefix = words[-1] if words else ""
            path = [w.lower() for w in words[:-1]]
        else:
            prefix = ""
            path = [w.lower() for w in words]

        candidates = self._dynamic_candidates(path)
        if candidates is not None:
            yield from self._word_completions(candidates, prefix)
            return
        yield from self._static.get_completions(document, complete_event)

    # ------------------------------------------------------------------
    # Динамические контексты
    # ------------------------------------------------------------------

    def _dynamic_candidates(self, path: list[str]) -> Iterable[str] | None:
        """Варианты для контекста или ``None`` — делегировать статике."""
        if (
            len(path) >= 2
            and path[0] == "track"
            and path[1]
            in (
                "show",
                "delete",
            )
        ):
            return self._track_names()
        if path == ["freeze"]:
            return self._track_names()  # freeze [name] — необязательный аргумент
        if path == ["track", "add"]:
            return self._provider("profile")
        if path == ["scale"]:
            return self._provider("scale")
        if path == ["root"]:
            return NOTES
        if path == ["clock", "source"]:
            return CLOCK_SOURCE_NAMES
        if path == ["help"]:
            return [spec.name for spec in CommandParser().specs()]
        return None

    def _track_names(self) -> list[str]:
        """Имена дорожек из текущего снапшота."""
        return [t.name for t in self._control.list_tracks()]

    def _provider(self, key: str) -> Iterable[str]:
        """Вызвать провайдера по ключу (отсутствует → пусто)."""
        provider = self._providers.get(key)
        return provider() if provider is not None else ()

    # ------------------------------------------------------------------
    # Статическое дерево
    # ------------------------------------------------------------------

    @staticmethod
    def _build_static() -> NestedCompleter:
        """NestedCompleter из таблицы команд parser'а."""
        tree: dict[str, object] = {}
        for spec in CommandParser().specs():
            if spec.action is None:
                tree.setdefault(spec.domain, None)
            else:
                node = tree.get(spec.domain)
                if not isinstance(node, dict):
                    node = {}
                    tree[spec.domain] = node
                node[spec.action] = None
        return NestedCompleter.from_nested_dict(tree)

    @staticmethod
    def _word_completions(
        candidates: Iterable[str], prefix: str
    ) -> Iterable[Completion]:
        """Completion-объекты для кандидатов, начинающихся с prefix."""
        lowered = prefix.lower()
        for candidate in candidates:
            if candidate.lower().startswith(lowered):
                yield Completion(candidate, start_position=-len(prefix))
