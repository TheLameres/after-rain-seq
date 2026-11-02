"""Tests for Session API — дорожки, граф, лимиты, стратегия B."""

import pytest

from src.session import (
    PROFILES,
    ChordEvent,
    DrumTrack,
    MelodicTrack,
    Session,
    TrackGraph,
)

# ---------------------------------------------------------------------------
# ChordEvent
# ---------------------------------------------------------------------------


def test_chord_event_frozen():
    """ChordEvent — frozen dataclass с полями beat/degrees/duration/voicing."""
    ev = ChordEvent(beat=0.0, degrees=(0, 2, 4), duration=1.0, voicing="1-3-5")
    assert ev.beat == 0.0
    assert ev.degrees == (0, 2, 4)
    assert ev.duration == 1.0
    assert ev.voicing == "1-3-5"


def test_chord_event_immutable():
    """Frozen dataclass не позволяет менять поля."""
    ev = ChordEvent(beat=0.0, degrees=(0, 2, 4), duration=1.0, voicing="1-3-5")
    with pytest.raises(AttributeError):
        ev.beat = 1.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# MelodicTrack — создание и дефолты
# ---------------------------------------------------------------------------


def test_melodic_track_default_pad():
    """Дефолтная дорожка — pad с параметрами профиля."""
    t = MelodicTrack(name="Pad 1", profile_name="pad")
    assert t.profile_name == "pad"
    assert t.voicing == "1-3-5"
    assert t.octave == 5
    assert t.gate == 0.9
    assert t.inversion == 0
    assert t.degrees == [0, 3, 2, 0]
    assert t.sources == ()
    assert t.port is None
    assert t.muted is False


def test_melodic_track_custom_overrides():
    """Пользовательские параметры перекрывают дефолты профиля."""
    t = MelodicTrack(
        name="Pad 1",
        profile_name="pad",
        voicing="1-3-5-7",
        octave=4,
        gate=0.7,
        degrees=[0, 4, 3, 0],
    )
    assert t.voicing == "1-3-5-7"
    assert t.octave == 4
    assert t.gate == 0.7
    assert t.degrees == [0, 4, 3, 0]


def test_melodic_track_unknown_profile():
    """Неизвестный профиль — ValueError."""
    with pytest.raises(ValueError, match="Неизвестный профиль"):
        MelodicTrack(name="X 1", profile_name="nonexistent")


def test_melodic_track_set_profile():
    """set_profile меняет профиль и обновляет параметры к дефолтам."""
    t = MelodicTrack(name="Pad 1", profile_name="pad")
    t.set_profile("stab")
    assert t.profile_name == "stab"
    assert t.voicing == "1-4-7"
    assert t.octave == 5
    assert t.gate == 0.2


def test_melodic_track_set_profile_invalid():
    """set_profile с несуществующим профилем — ValueError."""
    t = MelodicTrack(name="Pad 1", profile_name="pad")
    with pytest.raises(ValueError, match="Неизвестный профиль"):
        t.set_profile("nonexistent")


# ---------------------------------------------------------------------------
# MelodicTrack — generate()
# ---------------------------------------------------------------------------


def test_pad_generates_chord_events():
    """pad (emits_chords) публикует ChordEvent из degrees."""
    t = MelodicTrack(name="Pad 1", profile_name="pad", degrees=[0, 3])
    t.generate()
    assert len(t.outbox) == 2
    assert t.outbox[0].degrees == (0, 2, 4)
    assert t.outbox[0].beat == 0.0
    assert t.outbox[1].degrees == (3, 5, 7)
    assert t.outbox[1].beat == 1.0


def test_pad_with_inversion():
    """Обращение применяется к ступеням аккорда."""
    t = MelodicTrack(name="Pad 1", profile_name="pad", degrees=[0], inversion=1)
    t.generate()
    # (0,2,4) инвертируется на 1 → (2,4,7): C E A
    assert t.outbox[0].degrees == (2, 4, 7)


def test_sub_without_sources_silent():
    """sub без источников молчит (стратегия B), не падает."""
    t = MelodicTrack(name="Sub 1", profile_name="sub")
    t.generate()
    assert t.outbox == []


def test_cc_only_silent():
    """cc_filter не генерирует нот, outbox пуст."""
    t = MelodicTrack(name="CC 1", profile_name="cc_filter")
    t.generate()
    assert t.outbox == []


def test_current_and_history():
    """current() — последнее событие, history() — с фильтром по beat."""
    t = MelodicTrack(name="Pad 1", profile_name="pad", degrees=[0, 3, 2])
    t.generate()
    assert t.current() is not None
    assert t.current().beat == 2.0
    assert len(t.history(1.0)) == 2
    assert len(t.history(0.0)) == 3


# ---------------------------------------------------------------------------
# MelodicTrack — inject_sources
# ---------------------------------------------------------------------------


def test_inject_sources():
    """Дорожка-наследник получает события от источника."""
    pad = MelodicTrack(name="Pad 1", profile_name="pad", degrees=[0, 3])
    pad.generate()
    sub = MelodicTrack(name="Sub 1", profile_name="sub")
    sub.inject_sources([pad])
    assert len(sub.outbox) == 2


# ---------------------------------------------------------------------------
# Session — propagate_chords (C6, шаг 3)
# ---------------------------------------------------------------------------


def test_propagate_chords_fills_descendants():
    """propagate_chords: источник публикует, наследник получает окно."""
    s = Session()
    s.create_melodic_track(profile="pad", degrees=[0, 3])
    s.create_melodic_track(profile="seq", channel=1)
    s.set_sources("Seq 1", "Pad 1")
    s.propagate_chords()
    seq = s.get_track("Seq 1")
    assert seq is not None
    assert len(seq.outbox) == 2  # два ChordEvent от Pad 1


def test_propagate_chords_idempotent():
    """Повторный propagate не дублирует события в outbox."""
    s = Session()
    s.create_melodic_track(profile="pad", degrees=[0, 3])
    s.create_melodic_track(profile="sub", channel=1)
    s.set_sources("Sub 1", "Pad 1")
    s.propagate_chords()
    s.propagate_chords()
    sub = s.get_track("Sub 1")
    assert sub is not None
    assert len(sub.outbox) == 2


def test_propagate_chords_no_sources_empty():
    """Наследник без источников (стратегия B) — пустой outbox, не падение."""
    s = Session()
    s.create_melodic_track(profile="seq", channel=0)
    s.propagate_chords()
    seq = s.get_track("Seq 1")
    assert seq is not None
    assert seq.outbox == []


def test_propagate_chords_multiple_sources():
    """Два источника: окно получает события обоих."""
    s = Session()
    s.create_melodic_track(profile="pad", degrees=[0])
    s.create_melodic_track(profile="atmos", degrees=[3])
    s.create_melodic_track(profile="stab", channel=2)
    s.set_sources("Stab 1", "Pad 1", "Atmos 1")
    s.propagate_chords()
    stab = s.get_track("Stab 1")
    assert stab is not None
    assert len(stab.outbox) == 2  # по одному событию от каждого источника


# ---------------------------------------------------------------------------
# PROFILES
# ---------------------------------------------------------------------------


def test_all_profiles_exist():
    """Все профили из track-hierarchy.md присутствуют в реестре."""
    expected = {
        "pad",
        "atmos",
        "sub",
        "stab",
        "seq",
        "arp",
        "bass",
        "lead",
        "texture",
        "cc_filter",
        "cc_space",
    }
    assert set(PROFILES.keys()) == expected


def test_cc_profiles_flag():
    """cc_filter и cc_space помечены cc_only=True."""
    assert PROFILES["cc_filter"].cc_only is True
    assert PROFILES["cc_space"].cc_only is True
    assert PROFILES["pad"].cc_only is False


# ---------------------------------------------------------------------------
# DrumTrack
# ---------------------------------------------------------------------------


def test_drum_track_creation():
    """DrumTrack создаётся с 16 лейнами GM 36–51."""
    dt = DrumTrack(name="Drum 1")
    assert len(dt.lanes) == 16
    assert dt.lanes[0].note == 36
    assert dt.lanes[0].name == "Kick"
    assert dt.lanes[15].note == 51
    assert dt.lanes[15].name == "Conga"
    assert dt.steps == 16
    assert dt.mutate == 0.5
    assert dt.square == 1
    assert dt.accent_level == 127


def test_drum_track_sources_blocked():
    """DrumTrack отклоняет попытку назначить источники."""
    dt = DrumTrack(name="Drum 1")
    assert dt.sources == ()
    with pytest.raises(ValueError, match="не участвует в графе"):
        dt.sources = ("Pad 1",)


def test_drum_track_generate_clears_outbox():
    """generate() очищает outbox (drum не публикует ChordEvent)."""
    dt = DrumTrack(name="Drum 1")
    dt.outbox.append(ChordEvent(0.0, (0, 2, 4), 1.0, "1-3-5"))
    dt.generate()
    assert dt.outbox == []


def test_step_to_note():
    """step_to_note мапит 0..15 на GM 36..51."""
    assert DrumTrack.step_to_note(0) == 36
    assert DrumTrack.step_to_note(6) == 42
    assert DrumTrack.step_to_note(15) == 51


def test_step_to_note_out_of_range():
    """step_to_note вне 0..15 — ValueError."""
    with pytest.raises(ValueError, match="вне диапазона"):
        DrumTrack.step_to_note(16)
    with pytest.raises(ValueError, match="вне диапазона"):
        DrumTrack.step_to_note(-1)


# ---------------------------------------------------------------------------
# TrackGraph
# ---------------------------------------------------------------------------


def _build_dub_techno_graph() -> TrackGraph:
    """Граф из примера «Dub Techno» (track-hierarchy.md §6)."""
    g = TrackGraph()
    for name in ("Pad 1", "Sub 1", "Stab 1", "Seq 1", "Atmos 1", "Drum 1"):
        g.add_track(name)
    g.set_sources("Sub 1", ("Pad 1",))
    g.set_sources("Stab 1", ("Pad 1",))
    g.set_sources("Seq 1", ("Pad 1",))
    return g


def test_graph_topological_order():
    """Топосорт: источники перед наследниками."""
    g = _build_dub_techno_graph()
    order = g.topological_order()
    pad_idx = order.index("Pad 1")
    assert order.index("Sub 1") > pad_idx
    assert order.index("Stab 1") > pad_idx
    assert order.index("Seq 1") > pad_idx


def test_graph_cycle_detection():
    """Цикл Pad 1 → Stab 1 → Pad 1 ловится на set_sources."""
    g = _build_dub_techno_graph()
    with pytest.raises(ValueError, match="Цикл"):
        g.set_sources("Pad 1", ("Stab 1",))


def test_graph_dependents():
    """dependents_of возвращает наследников."""
    g = _build_dub_techno_graph()
    assert g.dependents_of("Pad 1") == ["Seq 1", "Stab 1", "Sub 1"]
    assert g.dependents_of("Drum 1") == []


def test_graph_remove_track():
    """remove_track удаляет рёбра."""
    g = _build_dub_techno_graph()
    g.remove_track("Pad 1")
    assert g.dependents_of("Pad 1") == []


def test_graph_add_duplicate():
    """Добавление дубликата — ValueError."""
    g = TrackGraph()
    g.add_track("A")
    with pytest.raises(ValueError, match="уже в графе"):
        g.add_track("A")


# ---------------------------------------------------------------------------
# Session — создание и лимиты
# ---------------------------------------------------------------------------


def test_session_create_melodic():
    """Session создаёт мелодическую дорожку с автогенерацией имени."""
    s = Session()
    t1 = s.create_melodic_track(profile="pad")
    t2 = s.create_melodic_track(profile="pad")
    t3 = s.create_melodic_track(profile="sub")
    assert t1.name == "Pad 1"
    assert t2.name == "Pad 2"
    assert t3.name == "Sub 1"
    assert s.track_count == 3


def test_session_create_drum():
    """Session создаёт drum-дорожку."""
    s = Session()
    dt = s.create_drum_track()
    assert dt.name == "Drum 1"
    assert isinstance(dt, DrumTrack)


def test_session_max_tracks():
    """Лимит 16 дорожек; каналы кончаются раньше (15 свободных)."""
    s = Session()
    for _ in range(15):
        s.create_melodic_track()
    # 16-я melodic без явного канала: свободных каналов нет
    with pytest.raises(ValueError, match="свободных MIDI-каналов"):
        s.create_melodic_track()
    # с явным каналом — влезает, лимит дорожек всё ещё 16
    s.create_melodic_track(channel=9)
    assert s.track_count == 16
    with pytest.raises(ValueError, match="Лимит дорожек"):
        s.create_melodic_track(channel=10)


# ---------------------------------------------------------------------------
# Автоназначение MIDI-каналов (фикс слипания дорожек в один канал)
# ---------------------------------------------------------------------------


def test_session_auto_assigns_distinct_channels():
    """Дорожки без явного канала получают разные свободные каналы."""
    s = Session()
    t1 = s.create_melodic_track(profile="pad")
    t2 = s.create_melodic_track(profile="bass")
    t3 = s.create_melodic_track(profile="lead")
    assert (t1.channel, t2.channel, t3.channel) == (0, 1, 2)


def test_session_auto_assign_skips_drum_channel():
    """Канал 9 (ch10) резервируется под drum и не выдаётся мелодике."""
    s = Session()
    s.create_drum_track()  # ch9 занят
    used = set()
    for _ in range(15):
        used.add(s.create_melodic_track().channel)
    assert 9 not in used
    assert used == {0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 15}


def test_session_explicit_channel_respected():
    """Явный канал не переназначается."""
    s = Session()
    t = s.create_melodic_track(profile="pad", channel=7)
    assert t.channel == 7


def test_session_explicit_channel_out_of_range():
    """Канал вне 0..15 — ValueError."""
    s = Session()
    with pytest.raises(ValueError, match="0..15"):
        s.create_melodic_track(channel=16)
    with pytest.raises(ValueError, match="0..15"):
        s.create_melodic_track(channel=-1)


def test_session_freed_channel_reused():
    """Удалённая дорожка освобождает канал."""
    s = Session()
    t1 = s.create_melodic_track(profile="pad")
    s.remove_track(t1.name)
    t2 = s.create_melodic_track(profile="bass")
    assert t2.channel == t1.channel


def test_session_max_drum_tracks():
    """Лимит 2 drum-машин."""
    s = Session()
    s.create_drum_track()
    s.create_drum_track()
    with pytest.raises(ValueError, match="Лимит drum"):
        s.create_drum_track()


def test_session_unknown_profile():
    """Создание с неизвестным профилем — ValueError."""
    s = Session()
    with pytest.raises(ValueError, match="Неизвестный профиль"):
        s.create_melodic_track(profile="nonexistent")


# ---------------------------------------------------------------------------
# Session — удаление и стратегия B
# ---------------------------------------------------------------------------


def test_session_remove_track():
    """Удаление дорожки убирает её из сессии."""
    s = Session()
    t = s.create_melodic_track()
    s.remove_track(t.name)
    assert s.get_track(t.name) is None
    assert s.track_count == 0


def test_session_remove_nonexistent():
    """Удаление несуществующей дорожки — ValueError."""
    s = Session()
    with pytest.raises(ValueError, match="не найдена"):
        s.remove_track("Ghost 1")


def test_session_remove_source_strategy_b():
    """Стратегия B: удаление источника сбрасывает sources у зависимых."""
    s = Session()
    pad = s.create_melodic_track(profile="pad")
    sub = s.create_melodic_track(profile="sub")
    s.set_sources(sub.name, pad.name)
    assert sub.sources == (pad.name,)

    s.remove_track(pad.name)
    assert sub.sources == ()
    # Дорожка не падает, generate() работает
    sub.generate()
    assert sub.outbox == []


# ---------------------------------------------------------------------------
# Session — set_sources
# ---------------------------------------------------------------------------


def test_session_set_sources():
    """Назначение источников обновляет дорожку и граф."""
    s = Session()
    pad = s.create_melodic_track(profile="pad")
    sub = s.create_melodic_track(profile="sub")
    s.set_sources(sub.name, pad.name)
    assert sub.sources == (pad.name,)


def test_session_set_two_sources():
    """Два источника — допустимо."""
    s = Session()
    pad1 = s.create_melodic_track(profile="pad")
    pad2 = s.create_melodic_track(profile="pad")
    sub = s.create_melodic_track(profile="sub")
    s.set_sources(sub.name, pad1.name, pad2.name)
    assert sub.sources == (pad1.name, pad2.name)


def test_session_max_sources():
    """Три источника — ValueError."""
    s = Session()
    s.create_melodic_track(profile="pad")
    s.create_melodic_track(profile="pad")
    s.create_melodic_track(profile="pad")
    sub = s.create_melodic_track(profile="sub")
    with pytest.raises(ValueError, match="Максимум источников"):
        s.set_sources(sub.name, "Pad 1", "Pad 2", "Pad 3")


def test_session_set_sources_nonexistent():
    """Назначение несуществующего источника — ValueError."""
    s = Session()
    sub = s.create_melodic_track(profile="sub")
    with pytest.raises(ValueError, match="не найден"):
        s.set_sources(sub.name, "Ghost 1")


def test_session_set_sources_cycle():
    """Цикл в графе — ValueError, состояние откатывается."""
    s = Session()
    pad = s.create_melodic_track(profile="pad")
    stab = s.create_melodic_track(profile="stab")
    s.set_sources(stab.name, pad.name)
    with pytest.raises(ValueError, match="Цикл"):
        s.set_sources(pad.name, stab.name)
    # Pad 1 не получил источник
    assert pad.sources == ()


def test_session_set_sources_drum():
    """Назначение источников drum-дорожке — ValueError."""
    s = Session()
    pad = s.create_melodic_track(profile="pad")
    drum = s.create_drum_track()
    with pytest.raises(ValueError, match="не участвует в графе"):
        s.set_sources(drum.name, pad.name)


# ---------------------------------------------------------------------------
# Session — топологический порядок
# ---------------------------------------------------------------------------


def test_session_ordered_tracks():
    """ordered_tracks возвращает дорожки в топопорядке."""
    s = Session()
    pad = s.create_melodic_track(profile="pad")
    sub = s.create_melodic_track(profile="sub")
    stab = s.create_melodic_track(profile="stab")
    s.set_sources(sub.name, pad.name)
    s.set_sources(stab.name, pad.name)

    order = s.ordered_tracks()
    names = [t.name for t in order]
    pad_idx = names.index(pad.name)
    assert names.index(sub.name) > pad_idx
    assert names.index(stab.name) > pad_idx


# ---------------------------------------------------------------------------
# Session — полный цикл: пресет «Dub Techno»
# ---------------------------------------------------------------------------


def test_dub_techno_preset():
    """Полный пресет из track-hierarchy.md §6 создаётся и генерируется."""
    s = Session()
    pad = s.create_melodic_track(profile="pad", channel=2, port="Синт B")
    sub = s.create_melodic_track(profile="sub", channel=1, port="Синт A")
    stab = s.create_melodic_track(
        profile="stab", channel=2, port="Синт B", voicing="1-4-7"
    )
    seq = s.create_melodic_track(profile="seq", channel=3, port="Синт B")
    s.create_melodic_track(profile="atmos", channel=4, port="Синт B")
    cc_f = s.create_melodic_track(profile="cc_filter", channel=2, port="Синт B")
    cc_s = s.create_melodic_track(profile="cc_space", channel=2, port="Синт B")
    drum = s.create_drum_track(channel=9, port="Синт A")

    s.set_sources(sub.name, pad.name)
    s.set_sources(stab.name, pad.name)
    s.set_sources(seq.name, pad.name)

    assert s.track_count == 8
    assert drum.sources == ()

    # Генерация в топопорядке
    for track in s.ordered_tracks():
        track.generate()
        if isinstance(track, MelodicTrack) and track.profile.reads_source:
            src_tracks = [s.get_track(src) for src in track.sources]
            track.inject_sources([t for t in src_tracks if t is not None])

    # Pad опубликовал аккорды, sub получил их
    assert len(pad.outbox) == 4  # I–IV–III–I
    assert len(sub.outbox) == 4
    # CC-профили молчат
    assert cc_f.outbox == []
    assert cc_s.outbox == []
    # Drum молчит в графе гармонии
    assert drum.outbox == []


# ---------------------------------------------------------------------------
# MelodicTrack — мутация (C5)
# ---------------------------------------------------------------------------


def test_melodic_track_mutate_default():
    """MelodicTrack имеет mutate=0.5 по умолчанию."""
    t = MelodicTrack(name="Pad 1", profile_name="pad")
    assert t.mutate == 0.5


def test_melodic_track_bpm_default():
    """MelodicTrack имеет bpm=120.0 по умолчанию."""
    t = MelodicTrack(name="Pad 1", profile_name="pad")
    assert t.bpm == 120.0


def test_melodic_track_mutation_count_default():
    """mutation_count = 0 без MutationEngine."""
    t = MelodicTrack(name="Pad 1", profile_name="pad")
    assert t.mutation_count == 0


def test_melodic_track_freeze():
    """freeze() устанавливает mutate=0."""
    t = MelodicTrack(name="Pad 1", profile_name="pad")
    t.freeze()
    assert t.mutate == 0.0


def test_melodic_track_freeze_idempotent():
    """freeze() можно вызывать многократно."""
    t = MelodicTrack(name="Pad 1", profile_name="pad")
    t.freeze()
    t.freeze()
    assert t.mutate == 0.0


# ---------------------------------------------------------------------------
# Session — freeze/evolve (C5)
# ---------------------------------------------------------------------------


def test_session_freeze_all():
    """freeze_all() замораживает все дорожки."""
    s = Session()
    pad = s.create_melodic_track(profile="pad")
    drum = s.create_drum_track()
    s.freeze_all()
    assert pad.mutate == 0.0
    assert drum.mutate == 0.0


def test_session_evolve_all():
    """evolve_all() возобновляет мутацию."""
    s = Session()
    pad = s.create_melodic_track(profile="pad")
    drum = s.create_drum_track()
    s.freeze_all()
    s.evolve_all(default_mutate=0.7)
    assert pad.mutate == 0.7
    assert drum.mutate == 0.5


def test_session_total_mutation_count_empty():
    """total_mutation_count = 0 для пустой сессии."""
    s = Session()
    assert s.total_mutation_count == 0


def test_session_total_mutation_count_with_tracks():
    """total_mutation_count суммирует mutation_count всех дорожек."""
    s = Session()
    s.create_melodic_track(profile="pad")
    s.create_drum_track()
    # Без мутаций — 0
    assert s.total_mutation_count == 0


def test_session_freeze_all_empty():
    """freeze_all() на пустой сессии — no-op, не падает."""
    s = Session()
    s.freeze_all()
    s.evolve_all()
    assert s.total_mutation_count == 0
