"""Canonical-пример скрипта after-rain-seq: подъём полной сессии.

Прогоняется валидатором (``script check``) и раннером (``script run`` /
``--script`` / startup) как fixture тестов скриптового движка. Все имена
(``session``, ``TrackProposal``, ``DrumProposal``) инжектируются в globals —
импортов в скриптах нет.
"""

pad = TrackProposal(
    name="Track 1",
    profile_name="atmos",
    voicing="1-3-5-7",
    degrees=[6, 5, 4],
)

sub = TrackProposal(name="Track 2", profile_name="sub", channel=1)

session.add_track(pad)
session.add_track(sub)
session.set_track_sources("Track 2", "Track 1")

session.add_drum(DrumProposal(name="Kick"))

session.set_bpm(120)
session.set_root("A")
session.set_scale("dorian")

session.route_track("Track 1", "main")
session.route_track("Track 2", "main")
session.route_track("Kick", "main")

session.start()
