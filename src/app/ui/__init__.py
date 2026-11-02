"""Управление UI с Push 2 — навигация, экраны, макро-оси.

Весь UI живёт в main loop App: MIDI-поток только кладёт события в
:class:`UiEventQueue`, drain и обработка — в main loop (паттерн TickProxy).
Экраны рисуются из ``StatusSnapshot`` (read-only DTO) и пишут команды
через ``EngineControl`` — UI не импортирует session/sync напрямую.
"""
