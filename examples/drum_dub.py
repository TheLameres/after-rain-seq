"""Пример скрипта after-rain-seq: dub techno бит на drum-дорожке.

Прогоняется валидатором (``script check``) и раннером (``script run``)
как fixture тестов скриптового движка. Имена ``session``, ``DrumProposal``
инжектируются в globals — импортов в скриптах нет.

Нотация lane'а: ``x`` = удар, ``X`` = акцент, ``.``/``~`` = пауза,
``|`` и пробелы — визуальная группировка, ``(p,s[,offset])`` — евклидов
ритм на весь цикл паттерна (см. раздел «Drum-паттерны из REPL и скриптов» в
README.md). Литеральная нотация короче сетки дополняется нулями
(16 шагов), длиннее — ошибка; евклид с ``s`` больше сетки — ошибка.
"""

session.add_drum(DrumProposal(name="Drums"))

# Kick: четыре удара на шагах 0, 3, 4, 7 (эталон drum_dub).
session.set_drum_pattern("Drums", "kick", "x..x|x..x|....|....")

# Snare: бэкбит на 2 и 4 (GM 38 — индекс 2).
session.set_drum_pattern("Drums", "snare", "....|X...|....|X...")

# Closed hat: восьмые.
session.set_drum_pattern("Drums", "closedhat", "x.x.x.x.x.x.x.x.")

# Shaker: евклид (3,8) — три удара на весь цикл паттерна (шаги 0, 6, 12).
session.set_drum_pattern("Drums", "shaker", "(3,8)")

# Conga: евклид (2,8,3) — ролл на 3 сегмента (удары на шагах 6 и 14).
session.set_drum_pattern("Drums", "conga", "(2,8,3)")

session.set_bpm(120)
session.start()
