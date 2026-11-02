"""REPL — терминальный фронтенд для мониторинга и контроля движка.

Третий «фронтенд» к движку (рядом с Push 2 UI и headless). Зависит только
от :class:`src.repl.engine_control.EngineControl` (ABC) и
:class:`src.repl.status.StatusSnapshot` — тестируется моком, ``app/``
реализует контракт в :mod:`src.app.engine_control`.
"""

from __future__ import annotations
