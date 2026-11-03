"""Тесты ScreenController: навигация, команды, энкодеры, CC-оси.

Мок EngineControl записывает вызовы; снапшот собирается вручную —
UI читает только StatusSnapshot (план D2 §2.2).
"""

from __future__ import annotations

from src.app.ui.macro_axes import MacroAxes
from src.app.ui.screen_controller import (
    LED_GREEN,
    MELODIC_PROFILES,
    ScreenController,
)
from src.app.ui.screen_id import ScreenId
from src.app.ui.ui_event import UiEvent
from src.repl.engine_control import EngineControl
from src.repl.status import PortSummary, StatusSnapshot, TrackSummary

NOW = 1000.0


def make_track(
    name: str,
    profile: str = "pad",
    channel: int = 0,
    port: str | None = "Синт A",
    sources: tuple[str, ...] = (),
    mutate: float = 0.5,
    gate: float = 0.9,
    density: float = 1.0,
    density_applicable: bool = False,
    kind: str = "melodic",
) -> TrackSummary:
    return TrackSummary(
        name=name,
        kind=kind,
        profile=profile,
        sources=sources,
        mutation_count=0,
        frozen=mutate == 0.0,
        port=port,
        gate=gate,
        voicing="1-3-5" if kind == "melodic" else "",
        octave=5,
        mutate=mutate,
        density=density,
        density_applicable=density_applicable,
        channel=channel,
    )


PORTS = (
    PortSummary("Синт A", "connected", "Bus One"),
    PortSummary("Синт B", "disconnected", "no match"),
)


class MockEngine(EngineControl):
    """Полный стаб EngineControl с записью вызовов."""

    def __init__(self, tracks: tuple[TrackSummary, ...] = ()) -> None:
        self.tracks = tracks
        self.calls: list[tuple[str, tuple]] = []
        self.feedback: dict[str, str] = {}  # метод → фиксированный ответ

    def get_status(self) -> StatusSnapshot:
        return StatusSnapshot(
            running=True,
            bpm=118.0,
            swing=0.0,
            clock_source="internal",
            clock_pending=None,
            clock_error=None,
            link_active=False,
            link_peers=0,
            root="A",
            scale="dorian",
            tracks=self.tracks,
            total_mutations=0,
            ports=PORTS,
            log_error=None,
        )

    def get_logs(self, n: int) -> list[str]:
        return []

    def _rec(self, method: str, *args) -> str:
        self.calls.append((method, args))
        return self.feedback.get(method, f"{method} ok")

    def start_transport(self) -> str:
        return self._rec("start_transport")

    def stop_transport(self) -> str:
        return self._rec("stop_transport")

    def set_bpm(self, bpm: float) -> str:
        return self._rec("set_bpm", bpm)

    def set_swing(self, amount: float) -> str:
        return self._rec("set_swing", amount)

    def request_clock_source(self, source: str) -> str:
        return self._rec("request_clock_source", source)

    def rescan_ports(self) -> str:
        return self._rec("rescan_ports")

    def switch_port(self, label: str, match: str) -> str:
        return self._rec("switch_port", label, match)

    def set_root(self, root: str) -> str:
        return self._rec("set_root", root)

    def set_scale(self, name: str) -> str:
        return self._rec("set_scale", name)

    def list_tracks(self) -> list[TrackSummary]:
        return list(self.tracks)

    def create_track(self, profile: str, channel: int | None = None) -> str:
        return self._rec("create_track", profile)

    def set_track_channel(self, name: str, channel: int) -> str:
        return self._rec("set_track_channel", name, channel)

    def remove_track(self, name: str) -> str:
        return self._rec("remove_track", name)

    def route_track(self, name: str, label: str) -> str:
        return self._rec("route_track", name, label)

    def unroute_track(self, name: str) -> str:
        return self._rec("unroute_track", name)

    def freeze(self, name: str | None = None) -> str:
        return self._rec("freeze", name)

    def evolve(self) -> str:
        return self._rec("evolve")

    def create_drum_track(self) -> str:
        return self._rec("create_drum_track")

    def set_track_sources(self, name: str, *sources: str) -> str:
        return self._rec("set_track_sources", name, *sources)

    def set_track_gate(self, name: str, gate: float) -> str:
        return self._rec("set_track_gate", name, gate)

    def set_track_density(self, name: str, density: float) -> str:
        return self._rec("set_track_density", name, density)

    def set_track_mutate(self, name: str, mutate: float) -> str:
        return self._rec("set_track_mutate", name, mutate)

    def evolve_track(self, name: str) -> str:
        return self._rec("evolve_track", name)

    # helpers для тестов
    def called(self, method: str) -> list[tuple]:
        return [args for m, args in self.calls if m == method]


def make_controller(
    tracks: tuple[TrackSummary, ...] = (),
) -> tuple[ScreenController, MockEngine, list[tuple[str, str, int, int]]]:
    engine = MockEngine(tracks)
    sent: list[tuple[str, str, int, int]] = []
    ctl = ScreenController(engine, MacroAxes(), cc_sender=lambda *a: sent.append(a))
    return ctl, engine, sent


def btn(ctl: ScreenController, name: str, now: float = NOW) -> None:
    ctl.handle(UiEvent.button(name, True), now)


def enc(ctl: ScreenController, idx: int, inc: int = 1, now: float = NOW) -> None:
    ctl.handle(UiEvent.encoder(f"Track{idx} Encoder", inc), now)


# ── Навигация ─────────────────────────────────────────────────────────────────


class TestNavigation:
    def test_tabs(self) -> None:
        """Табы дорожки на выделенных кнопках: Clip → GEN, Device → MACRO,
        Upper Row 5 → PORTS."""
        ctl, _, _ = make_controller()
        btn(ctl, "Clip")
        assert ctl.state.screen is ScreenId.TRACK_GEN
        btn(ctl, "Device")
        assert ctl.state.screen is ScreenId.TRACK_MACRO
        btn(ctl, "Upper Row 5")
        assert ctl.state.screen is ScreenId.PORTS

    def test_page_left_right_and_clamp(self) -> None:
        tracks = tuple(make_track(f"T{i}") for i in range(10))
        ctl, _, _ = make_controller(tracks)
        assert ctl.state.page == 0
        btn(ctl, "Right")
        assert ctl.state.page == 1
        # Вторая Right на последней странице → вход в GEN выбранной.
        btn(ctl, "Right")
        assert ctl.state.screen is ScreenId.TRACK_GEN
        btn(ctl, "Left")  # назад на TRACKS (страница сохранилась)
        assert ctl.state.screen is ScreenId.TRACKS
        assert ctl.state.page == 1
        btn(ctl, "Left")
        assert ctl.state.page == 0
        btn(ctl, "Left")  # TRACKS не таб: за левым краем — стоим
        assert ctl.state.page == 0
        assert ctl.state.screen is ScreenId.TRACKS

    def test_cursor_up_down_clamp(self) -> None:
        tracks = (make_track("A"), make_track("B"))
        ctl, _, _ = make_controller(tracks)
        assert ctl.state.selected == 0
        btn(ctl, "Down")
        assert ctl.state.selected == 1
        btn(ctl, "Down")  # кламп
        assert ctl.state.selected == 1
        btn(ctl, "Up")
        assert ctl.state.selected == 0
        btn(ctl, "Up")  # кламп
        assert ctl.state.selected == 0

    def test_right_enters_track_screen(self) -> None:
        tracks = (make_track("A"),)
        ctl, _, _ = make_controller(tracks)
        btn(ctl, "Right")
        assert ctl.state.screen is ScreenId.TRACK_GEN
        btn(ctl, "Left")
        assert ctl.state.screen is ScreenId.TRACKS

    def test_session_opens_tracks(self) -> None:
        """Session (CC 51) — экран TRACKS (не таб Upper Row)."""
        ctl, _, _ = make_controller((make_track("A"),))
        btn(ctl, "Upper Row 1")  # GEN
        btn(ctl, "Session")
        assert ctl.state.screen is ScreenId.TRACKS

    def test_clip_and_device_open_gen_macro(self) -> None:
        """Clip (CC 113) → GEN, Device (CC 110) → MACRO выбранной дорожки."""
        tracks = (make_track("A"), make_track("B"))
        ctl, _, _ = make_controller(tracks)
        btn(ctl, "Down")  # выбрана B
        btn(ctl, "Clip")
        assert ctl.state.screen is ScreenId.TRACK_GEN
        btn(ctl, "Device")
        assert ctl.state.screen is ScreenId.TRACK_MACRO
        btn(ctl, "Left")  # MACRO → GEN
        assert ctl.state.screen is ScreenId.TRACK_GEN
        btn(ctl, "Left")  # GEN → TRACKS
        assert ctl.state.screen is ScreenId.TRACKS

    def test_lower_row_selects_track_and_opens_gen(self) -> None:
        """Lower Row 1–8: курсор на слот + вход в GEN (позиционно по странице)."""
        tracks = tuple(make_track(n) for n in ("A", "B", "C"))
        ctl, _, _ = make_controller(tracks)
        btn(ctl, "Lower Row 3")  # C
        assert ctl.state.selected == 2
        assert ctl.state.screen is ScreenId.TRACK_GEN
        view = ctl.build_view(ctl._engine.get_status(), NOW)
        assert view.track is not None and view.track.name == "C"

    def test_lower_row_empty_slot_moves_cursor_only(self) -> None:
        """Пустой слот Lower Row: курсор переносится, экран не открывается."""
        ctl, _, _ = make_controller((make_track("A"),))
        btn(ctl, "Lower Row 5")  # пусто
        assert ctl.state.selected == 4
        assert ctl.state.screen is ScreenId.TRACKS

    def test_tabs_step_gen_macro(self) -> None:
        """Right/Left между табами: GEN → MACRO → PORTS → GEN (кольцо).
        SCALE/SETUP — глобальные экраны вне табов: стрелки на них не ходят."""
        ctl, engine, _ = make_controller()
        btn(ctl, "Clip")  # GEN
        assert ctl.state.screen is ScreenId.TRACK_GEN
        btn(ctl, "Right")
        assert ctl.state.screen is ScreenId.TRACK_MACRO
        btn(ctl, "Right")
        assert ctl.state.screen is ScreenId.PORTS
        btn(ctl, "Right")  # PORTS: Right ходит по списку портов, не по табам
        assert ctl.state.screen is ScreenId.PORTS
        assert ctl.state.selected == 1  # курсор сдвинулся
        btn(ctl, "Setup")
        btn(ctl, "Left")  # SETUP вне табов — стоим
        assert ctl.state.screen is ScreenId.SETUP
        btn(ctl, "Scale")
        btn(ctl, "Right")  # SCALE Right крутит корень, не таб
        assert engine.called("set_root") == [("A#",)]
        assert ctl.state.screen is ScreenId.SCALE

    def test_scale_and_setup_buttons(self) -> None:
        """Scale (CC 58) → SCALE, Setup (CC 30) → SETUP."""
        ctl, _, _ = make_controller()
        btn(ctl, "Scale")
        assert ctl.state.screen is ScreenId.SCALE
        btn(ctl, "Setup")
        assert ctl.state.screen is ScreenId.SETUP

    def test_scale_arrows_rotate_root_and_scale(self) -> None:
        """SCALE: Left/Right — корень, Up/Down — лад."""
        ctl, engine, _ = make_controller()
        btn(ctl, "Scale")
        btn(ctl, "Right")  # A → A#
        assert engine.called("set_root") == [("A#",)]
        btn(ctl, "Down")  # dorian → phrygian
        assert engine.called("set_scale") == [("phrygian",)]

    def test_setup_tabs_cycle_with_up_down(self) -> None:
        """SETUP: Up/Down переключают суб-вкладки (clock → midi → link)."""
        ctl, _, _ = make_controller()
        btn(ctl, "Setup")
        assert ctl.state.setup_tab == 0
        btn(ctl, "Down")
        assert ctl.state.setup_tab == 1
        btn(ctl, "Down")
        assert ctl.state.setup_tab == 2
        btn(ctl, "Down")  # кольцо
        assert ctl.state.setup_tab == 0
        view = ctl.build_view(ctl._engine.get_status(), NOW)
        assert view.sync is not None and view.sync.tab == "clock"


# ── Кнопки-команды ────────────────────────────────────────────────────────────


class TestButtons:
    def test_duplicate_is_unassigned(self) -> None:
        """Duplicate (CC 88) — резерв: создание перенесено на Add Track (wizard)."""
        ctl, engine, _ = make_controller()
        btn(ctl, "Duplicate")
        assert engine.called("create_track") == []

    def test_add_track_opens_wizard(self) -> None:
        """Add Track (CC 53) открывает wizard на шаге выбора вида."""
        ctl, engine, _ = make_controller()
        btn(ctl, "Add Track")
        assert ctl.state.screen is ScreenId.WIZARD
        assert ctl.state.wizard_kind == "kind"
        assert engine.calls == []

    def test_wizard_melodic_flow_creates_track(self) -> None:
        """kind → profile → route (по умолчанию «—») → create без порта."""
        ctl, engine, _ = make_controller()
        btn(ctl, "Add Track")
        # kind: melodic выбран по умолчанию (индекс 0)
        btn(ctl, "Right")
        assert ctl.state.wizard_kind == "profile"
        # профили: pad — индекс 0; выберем stab
        idx = MELODIC_PROFILES.index("stab")
        for _ in range(idx):
            btn(ctl, "Down")
        btn(ctl, "Right")
        assert ctl.state.wizard_kind == "route"
        assert ctl.state.wizard_profile == "stab"
        btn(ctl, "Right")  # route: «—» по умолчанию — порт не назначаем
        assert engine.called("create_track") == [("stab",)]
        assert engine.called("create_drum_track") == []
        assert engine.called("route_track") == []
        assert ctl.state.screen is ScreenId.TRACKS
        assert ctl.state.wizard_profile is None  # профиль сброшен
        assert ctl.state.flash_text is not None

    def test_wizard_drum_flow_creates_drum_track(self) -> None:
        """kind=drum → сразу шаг route → create_drum_track и выход."""
        ctl, engine, _ = make_controller()
        btn(ctl, "Add Track")
        btn(ctl, "Down")  # melodic → drum
        btn(ctl, "Right")
        assert ctl.state.wizard_kind == "route"
        assert ctl.state.wizard_profile is None
        btn(ctl, "Right")  # route: «—»
        assert engine.called("create_drum_track") == [()]
        assert engine.called("create_track") == []
        assert engine.called("route_track") == []
        assert ctl.state.screen is ScreenId.TRACKS

    def test_wizard_route_assigns_port(self) -> None:
        """На шаге route выбор порта → create + route_track(имя, порт)."""
        ctl, engine, _ = make_controller()
        engine.feedback["create_track"] = 'created track "Pad 1" (profile pad, ch 0)'
        btn(ctl, "Add Track")
        btn(ctl, "Right")  # kind → profile
        btn(ctl, "Right")  # profile (pad) → route
        btn(ctl, "Down")  # «—» → «Синт A» (первый порт снапшота)
        assert ctl.state.wizard_index == 1
        btn(ctl, "Right")  # создать и привязать порт
        assert engine.called("create_track") == [(MELODIC_PROFILES[0],)]
        assert engine.called("route_track") == [("Pad 1", "Синт A")]
        assert ctl.state.screen is ScreenId.TRACKS

    def test_wizard_route_port_cycle_via_encoder(self) -> None:
        """E1 листает варианты и на шаге route."""
        ctl, engine, _ = make_controller()
        engine.feedback["create_drum_track"] = 'created track "Drum 1" (drum, ch 9)'
        btn(ctl, "Add Track")
        btn(ctl, "Down")  # drum
        btn(ctl, "Right")  # → route
        enc(ctl, 1)  # «—» → «Синт A»
        enc(ctl, 1)  # «Синт A» → «Синт B»
        assert ctl.state.wizard_index == 2
        btn(ctl, "Right")
        assert engine.called("create_drum_track") == [()]
        assert engine.called("route_track") == [("Drum 1", "Синт B")]

    def test_wizard_route_error_flashes(self) -> None:
        """Ошибка роута (error:) перекрывает фидбек создания."""
        ctl, engine, _ = make_controller()
        engine.feedback["create_track"] = 'created track "Pad 1" (profile pad, ch 0)'
        engine.feedback["route_track"] = "error: port not connected"
        btn(ctl, "Add Track")
        btn(ctl, "Right")  # kind → profile
        btn(ctl, "Right")  # profile → route
        btn(ctl, "Down")  # «Синт A»
        btn(ctl, "Right")
        assert engine.called("route_track") == [("Pad 1", "Синт A")]
        assert ctl.state.flash_text == "error: port not connected"

    def test_wizard_cancel_resets_profile(self) -> None:
        """Отмена с шага route сбрасывает и шаг, и выбранный профиль."""
        ctl, engine, _ = make_controller()
        btn(ctl, "Add Track")
        btn(ctl, "Right")  # kind → profile
        btn(ctl, "Right")  # profile → route
        assert ctl.state.wizard_profile == MELODIC_PROFILES[0]
        btn(ctl, "Left")
        assert ctl.state.screen is ScreenId.TRACKS
        assert ctl.state.wizard_profile is None
        assert engine.calls == []

    def test_wizard_cancel_left_and_delete(self) -> None:
        """Left/Delete отменяют wizard без создания дорожки."""
        for cancel in ("Left", "Delete"):
            ctl, engine, _ = make_controller()
            btn(ctl, "Add Track")
            btn(ctl, "Down")
            btn(ctl, cancel)
            assert ctl.state.screen is ScreenId.TRACKS
            assert engine.calls == []

    def test_wizard_encoder_e1_rotates(self) -> None:
        """E1 крутит выбор в wizard'е (kind, profile и route)."""
        ctl, engine, _ = make_controller()
        btn(ctl, "Add Track")
        enc(ctl, 1, -1)  # melodic → drum (обёртка)
        assert ctl.state.wizard_index == 1
        btn(ctl, "Right")  # drum → route
        assert ctl.state.wizard_kind == "route"
        assert (
            engine.called("create_drum_track") == []
        )  # создание — на подтверждении route
        enc(ctl, 1)  # «—» → «Синт A»
        assert ctl.state.wizard_index == 1

    def test_wizard_select_confirms(self) -> None:
        """Select (CC 48) подтверждает шаг wizard'а."""
        ctl, _, _ = make_controller()
        btn(ctl, "Add Track")
        btn(ctl, "Select")
        assert ctl.state.wizard_kind == "profile"

    def test_wizard_create_error_flashes(self) -> None:
        """Ошибка создания (лимит дорожек) — во flash, wizard закрывается."""
        ctl, engine, _ = make_controller()
        engine.feedback["create_track"] = "error: max tracks reached"
        btn(ctl, "Add Track")
        btn(ctl, "Right")  # kind → profile
        btn(ctl, "Right")  # profile → route
        btn(ctl, "Right")  # create
        assert engine.called("create_track") == [(MELODIC_PROFILES[0],)]
        assert ctl.state.flash_text == "error: max tracks reached"
        assert ctl.state.screen is ScreenId.TRACKS

    def test_delete_requires_shift(self) -> None:
        tracks = (make_track("A"), make_track("B"))
        ctl, engine, _ = make_controller(tracks)
        btn(ctl, "Delete")
        assert engine.called("remove_track") == []
        btn(ctl, "Shift")
        btn(ctl, "Delete")
        assert engine.called("remove_track") == [("A",)]

    def test_play_toggles_transport(self) -> None:
        ctl, engine, _ = make_controller()
        btn(ctl, "Play")
        assert engine.called("stop_transport")  # running=True → stop
        assert engine.called("start_transport") == []

    def test_record_freezes_all_on_tracks(self) -> None:
        ctl, engine, _ = make_controller((make_track("A"),))
        btn(ctl, "Record")
        assert engine.called("freeze") == [(None,)]

    def test_record_freezes_selected_on_track(self) -> None:
        tracks = (make_track("A"), make_track("B"))
        ctl, engine, _ = make_controller(tracks)
        btn(ctl, "Down")
        btn(ctl, "Right")  # TRACK выбранной (B)
        btn(ctl, "Record")
        assert engine.called("freeze") == [("B",)]

    def test_browse_rescans_only_on_ports(self) -> None:
        ctl, engine, _ = make_controller()
        btn(ctl, "Browse")
        assert engine.called("rescan_ports") == []
        btn(ctl, "Upper Row 5")  # PORTS
        btn(ctl, "Browse")
        assert engine.called("rescan_ports") == [()]


# ── Энкодеры ──────────────────────────────────────────────────────────────────


class TestEncoders:
    def test_tracks_screen_ignores_track_encoders(self) -> None:
        tracks = (make_track("A"),)
        ctl, engine, _ = make_controller(tracks)
        enc(ctl, 1)
        assert engine.calls == []

    def test_track_gate_encoder(self) -> None:
        tracks = (make_track("A", gate=0.9),)
        ctl, engine, _ = make_controller(tracks)
        btn(ctl, "Right")  # TRACK
        enc(ctl, 3, inc=-2)
        assert engine.called("set_track_gate") == [("A", 0.9 - 2 * 0.05)]

    def test_track_den_encoder(self) -> None:
        tracks = (
            make_track("A", profile="stab", density=1.0, density_applicable=True),
        )
        ctl, engine, _ = make_controller(tracks)
        btn(ctl, "Right")
        enc(ctl, 4, inc=-127)  # кламп в 0.0 произойдёт в фасаде
        name, value = engine.called("set_track_density")[0]
        assert name == "A"
        assert value == 1.0 - 127 / 127.0

    def test_den_not_applicable_ignored(self) -> None:
        tracks = (make_track("A", profile="pad", density_applicable=False),)
        ctl, engine, _ = make_controller(tracks)
        btn(ctl, "Right")
        enc(ctl, 4)
        assert engine.called("set_track_density") == []

    def test_track_mut_encoder(self) -> None:
        tracks = (make_track("A", mutate=0.5),)
        ctl, engine, _ = make_controller(tracks)
        btn(ctl, "Right")
        enc(ctl, 5, inc=10)
        assert engine.called("set_track_mutate")[0][0] == "A"

    def test_tempo_encoder_sets_bpm(self) -> None:
        ctl, engine, _ = make_controller()
        ctl.handle(UiEvent.encoder("Tempo Encoder", 2), NOW)
        assert engine.called("set_bpm") == [(118.0 + 2 * 0.5,)]

    def test_global_encoders(self) -> None:
        ctl, engine, _ = make_controller()
        btn(ctl, "Scale")  # SCALE
        enc(ctl, 1)  # ROOT: A -> A#
        assert engine.called("set_root") == [("A#",)]
        enc(ctl, 2)  # SCALE: dorian -> phrygian
        assert engine.called("set_scale") == [("phrygian",)]
        enc(ctl, 3)  # E3 на SCALE не назначен (свинг — Swing Encoder, D2-6)
        assert engine.called("set_swing") == []

    def test_swing_encoder_always_sets_swing(self) -> None:
        """Swing Encoder крутит свинг на любом экране."""
        ctl, engine, _ = make_controller()
        ctl.handle(UiEvent.encoder("Swing Encoder", 1), NOW)
        assert engine.called("set_swing") == [(0.0 + 0.05,)]

    def test_setup_encoder_only_on_clock_tab(self) -> None:
        """E1 меняет источник клока только на вкладке CLOCK."""
        ctl, engine, _ = make_controller()
        btn(ctl, "Setup")
        enc(ctl, 1)  # clock-вкладка: internal -> midi
        assert engine.called("request_clock_source") == [("midi",)]
        btn(ctl, "Down")  # вкладка midi
        enc(ctl, 1)
        assert engine.called("request_clock_source") == [("midi",)]  # не больше

    def test_sync_encoder_cycles_source(self) -> None:
        ctl, engine, _ = make_controller()
        btn(ctl, "Setup")  # SETUP
        enc(ctl, 1)  # internal -> midi
        assert engine.called("request_clock_source") == [("midi",)]

    def test_ports_encoders_route(self) -> None:
        tracks = (make_track("A"), make_track("B"))
        ctl, engine, _ = make_controller(tracks)
        btn(ctl, "Upper Row 5")  # PORTS
        enc(ctl, 1)  # route track A -> B
        assert ctl.state.ports_route_track == "B"
        # У B порт «Синт A» (pos=1): +1 → «Синт B», -1 → None (unroute).
        enc(ctl, 2)
        assert engine.called("route_track") == [("B", "Синт B")]
        enc(ctl, 2, inc=-1)
        assert engine.called("unroute_track") == [("B",)]


# ── Касания энкодеров (D2-5: статус-бара нет, значение — во flash) ────────────


class TestEncoderTouch:
    def test_tempo_touch_shows_bpm_flash(self) -> None:
        """Касание Tempo Encoder → flash 'BPM <bpm> <SOURCE>' на пару секунд."""
        ctl, engine, _ = make_controller()
        btn(ctl, "Tempo Encoder")
        assert ctl.state.visible_flash(NOW) == "BPM 118.0 INTERNAL"
        view = ctl.build_view(engine.get_status(), NOW)
        assert view.flash == "BPM 118.0 INTERNAL"

    def test_tempo_touch_flash_expires(self) -> None:
        ctl, _, _ = make_controller()
        btn(ctl, "Tempo Encoder")
        assert ctl.state.visible_flash(NOW + 2.5) is None

    def test_swing_touch_shows_swing_flash(self) -> None:
        ctl, _, _ = make_controller()
        btn(ctl, "Swing Encoder")
        assert ctl.state.visible_flash(NOW) == "SWING 0 %"

    def test_touch_release_ignored(self) -> None:
        """Отпускание энкодера (button pressed=False) не трогает flash."""
        ctl, _, _ = make_controller()
        ctl.handle(UiEvent.button("Tempo Encoder", False), NOW)
        assert ctl.state.flash_text is None

    def test_tempo_turn_still_sets_bpm(self) -> None:
        """Поворот Tempo Encoder работает независимо от касания."""
        ctl, engine, _ = make_controller()
        ctl.handle(UiEvent.encoder("Tempo Encoder", 2), NOW)
        assert engine.called("set_bpm") == [(118.0 + 2 * 0.5,)]


# ── SRC-цикл ──────────────────────────────────────────────────────────────────


class TestSourceCycle:
    def test_e1_cycles_none_then_candidates(self) -> None:
        tracks = (make_track("A"), make_track("B"))
        ctl, engine, _ = make_controller(tracks)
        btn(ctl, "Down")  # выбрана B
        btn(ctl, "Right")  # TRACK
        enc(ctl, 1)  # SRC: none -> A
        assert engine.called("set_track_sources") == [("B", "A")]
        # Повторный поворот при текущих sources=("A",) → none (цикл замкнулся).
        ctl2, engine2, _ = make_controller(
            (make_track("A"), make_track("B", sources=("A",)))
        )
        btn(ctl2, "Down")
        btn(ctl2, "Right")
        enc(ctl2, 1)
        assert engine2.called("set_track_sources") == [("B",)]

    def test_e2_second_source(self) -> None:
        tracks = (
            make_track("A"),
            make_track("B"),
            make_track("C", sources=("A",)),
        )
        ctl, engine, _ = make_controller(tracks)
        btn(ctl, "Down")
        btn(ctl, "Down")  # C
        btn(ctl, "Right")
        enc(ctl, 2)  # SRC2: none -> B (A уже занят в SRC)
        assert engine.called("set_track_sources") == [("C", "A", "B")]


# ── CC-оси ────────────────────────────────────────────────────────────────────


class TestCcAxes:
    def test_tone_sends_filter_cc(self) -> None:
        tracks = (make_track("A", channel=0, port="Синт A"),)
        ctl, _, sent = make_controller(tracks)
        btn(ctl, "Device")  # MACRO
        enc(ctl, 1, inc=10)
        assert sent == [("Синт A", "filter", 0, 10)]

    def test_space_sends_reverb_and_delay(self) -> None:
        tracks = (make_track("A", channel=2, port="Синт A"),)
        ctl, _, sent = make_controller(tracks)
        btn(ctl, "Device")  # MACRO
        enc(ctl, 2, inc=5)
        assert ("Синт A", "reverb", 2, 5) in sent
        assert ("Синт A", "delay", 2, 5) in sent

    def test_depth_sends_param_cc(self) -> None:
        tracks = (make_track("A", channel=1, port="Синт A"),)
        ctl, _, sent = make_controller(tracks)
        btn(ctl, "Device")  # MACRO
        enc(ctl, 3, inc=3)
        assert sent  # DEPTH шлёт хотя бы один параметр из оси

    def test_no_port_no_send_but_value_kept(self) -> None:
        tracks = (make_track("A", port=None),)
        ctl, _, sent = make_controller(tracks)
        btn(ctl, "Device")  # MACRO
        enc(ctl, 1, inc=7)
        assert sent == []
        assert ctl.state.macro_value("A", "TONE") == 7

    def test_value_clamps_at_127(self) -> None:
        tracks = (make_track("A", channel=0, port="Синт A"),)
        ctl, _, sent = make_controller(tracks)
        btn(ctl, "Device")  # MACRO
        enc(ctl, 1, inc=200)
        assert sent == [("Синт A", "filter", 0, 127)]

    def test_gen_screen_has_no_cc_axes(self) -> None:
        """CC-оси с GEN убраны: E6 на GEN ничего не шлёт (переезд на MACRO)."""
        tracks = (make_track("A", channel=0, port="Синт A"),)
        ctl, _, sent = make_controller(tracks)
        btn(ctl, "Clip")  # GEN
        enc(ctl, 6, inc=10)
        assert sent == []


# ── LED-подсветка кнопок ──────────────────────────────────────────────────────


class TestButtonLeds:
    def test_working_buttons_are_lit(self) -> None:
        """Рабочие кнопки есть в карте со значениями > 0."""
        ctl, engine, _ = make_controller((make_track("A"),))
        states = ctl.button_led_states(engine.get_status())
        for name in ("Session", "Clip", "Device", "Scale", "Setup", "Add Track"):
            assert states[name] > 0, name
        for name in ("Left", "Right", "Up", "Down", "Select", "Browse"):
            assert states[name] > 0, name

    def test_play_led_reflects_transport(self) -> None:
        """Play зелёный при работающем транспорте, белый — на стопе."""
        from dataclasses import replace as _replace

        from src.app.ui.screen_controller import LED_GREEN, LED_WHITE

        class StoppedEngine(MockEngine):
            def get_status(self) -> StatusSnapshot:
                return _replace(super().get_status(), running=False)

        tracks = (make_track("A"),)
        ctl, engine, _ = make_controller(tracks)
        assert ctl.button_led_states(engine.get_status())["Play"] == LED_GREEN
        stopped = StoppedEngine(tracks)
        ctl2, _, _ = make_controller(tracks)
        ctl2._engine = stopped
        assert ctl2.button_led_states(stopped.get_status())["Play"] == LED_WHITE

    def test_delete_led_armed_red(self) -> None:
        from src.app.ui.screen_controller import LED_RED

        ctl, engine, _ = make_controller((make_track("A"),))
        assert ctl.button_led_states(engine.get_status())["Delete"] != LED_RED
        btn(ctl, "Delete")
        assert ctl.button_led_states(engine.get_status())["Delete"] == LED_RED

    def test_lower_row_leds_follow_tracks_and_selection(self) -> None:
        from src.app.ui.screen_controller import LED_GREEN, LED_WHITE

        tracks = (make_track("A"), make_track("B"))
        ctl, engine, _ = make_controller(tracks)
        states = ctl.button_led_states(engine.get_status())
        assert states["Lower Row 1"] == LED_GREEN  # selected = 0
        assert states["Lower Row 2"] == LED_WHITE
        assert "Lower Row 3" not in states  # пустой слот — не подсвечивается
        btn(ctl, "Down")
        states = ctl.button_led_states(engine.get_status())
        assert states["Lower Row 2"] == LED_GREEN

    def test_upper_row_leds_follow_active_tab(self) -> None:
        from src.app.ui.screen_controller import LED_GRAY, LED_WHITE

        ctl, engine, _ = make_controller((make_track("A"),))
        states = ctl.button_led_states(engine.get_status())
        # TRACKS — не таб: PORTS (Upper Row 5) тусклая; прочие Upper Row
        # не подсвечиваются (освобождены под будущее, D2-4).
        assert states["Upper Row 5"] == LED_GRAY
        assert "Upper Row 1" not in states
        btn(ctl, "Upper Row 5")  # PORTS активный таб
        states = ctl.button_led_states(engine.get_status())
        assert states["Upper Row 5"] == LED_WHITE
        btn(ctl, "Clip")  # GEN — PORTS снова тусклая
        states = ctl.button_led_states(engine.get_status())
        assert states["Upper Row 5"] == LED_GRAY


# ── Flash и view ──────────────────────────────────────────────────────────────


class TestFlashAndView:
    def test_error_flashes_and_survives_screen_switch(self) -> None:
        ctl, engine, _ = make_controller()
        engine.feedback["set_bpm"] = "error: bpm out of range"
        ctl.handle(UiEvent.encoder("Tempo Encoder", 1), NOW)
        assert ctl.state.flash_text == "error: bpm out of range"
        btn(ctl, "Upper Row 4")
        view = ctl.build_view(engine.get_status(), NOW + 1.0)
        assert view.flash == "error: bpm out of range"

    def test_flash_expires(self) -> None:
        ctl, engine, _ = make_controller()
        engine.feedback["set_bpm"] = "error: bpm out of range"
        ctl.handle(UiEvent.encoder("Tempo Encoder", 1), NOW)
        view = ctl.build_view(engine.get_status(), NOW + 5.0)
        assert view.flash is None

    def test_build_view_tracks_page_title(self) -> None:
        tracks = tuple(make_track(f"T{i}") for i in range(10))
        ctl, engine, _ = make_controller(tracks)
        btn(ctl, "Right")  # page 1
        view = ctl.build_view(engine.get_status(), NOW)
        assert view.screen == "tracks"
        assert view.title == "TRACKS 9-16/2"  # метка страницы по размеру банка
        assert view.tracks is not None
        assert len(view.tracks) == 2  # заполненные строки (слоты не добавляем)
        assert view.flash is None  # статус-бара нет (D2-5) — только flash

    def test_build_view_track_detail(self) -> None:
        tracks = (make_track("A", profile="stab", density_applicable=True),)
        ctl, engine, _ = make_controller(tracks)
        btn(ctl, "Right")
        view = ctl.build_view(engine.get_status(), NOW)
        assert view.track is not None
        assert view.track.density == 1.0
        assert view.track.color != 0  # свой цвет дорожки (палитра)

    def test_build_view_track_macro(self) -> None:
        tracks = (make_track("A", port="Синт A"),)
        ctl, engine, _ = make_controller(tracks)
        btn(ctl, "Device")
        view = ctl.build_view(engine.get_status(), NOW)
        assert view.track_macro is not None
        assert view.track_macro.macros == (0, 0, 0)  # порт есть → 0..127
        assert view.track_macro.color != 0

    def test_build_view_track_macro_no_port_dashes(self) -> None:
        tracks = (make_track("A", port=None),)
        ctl, engine, _ = make_controller(tracks)
        btn(ctl, "Device")
        view = ctl.build_view(engine.get_status(), NOW)
        assert view.track_macro is not None
        assert view.track_macro.macros == (-1, -1, -1)

    def test_track_rows_carry_distinct_colors(self) -> None:
        """У соседних дорожек разные цвета (маркеры в списке TRACKS)."""
        tracks = tuple(make_track(f"T{i}") for i in range(4))
        ctl, engine, _ = make_controller(tracks)
        view = ctl.build_view(engine.get_status(), NOW)
        colors = [r.color for r in view.tracks or ()]
        assert len(set(colors)) == 4

    def test_build_view_ports(self) -> None:
        ctl, engine, _ = make_controller((make_track("A"),))
        btn(ctl, "Upper Row 5")
        view = ctl.build_view(engine.get_status(), NOW)
        assert view.ports is not None
        assert len(view.ports.rows) == 2
        assert view.ports.route_track == "A"
        assert view.ports.route_port == "Синт A"


# ── Регрессии spike_ui_simulate ───────────────────────────────────────────────


class TestSpikeRegressions:
    """Дефекты, найденные E2E-spike (план D2 §5, сценарии 2 и 6)."""

    def test_right_opens_selected_track_not_first(self) -> None:
        """Курсор переживает вход в TRACK: Right открывает ВЫБРАННУЮ дорожку.

        Баг: _clamp_cursor обнулял курсор на экранах без курсора
        (_cursor_limit → 0), и TRACK всегда открывал дорожку 0.
        """
        tracks = (make_track("Pad 1"), make_track("Pad 2"), make_track("Stab 1"))
        ctl, engine, _ = make_controller(tracks)
        btn(ctl, "Down")
        btn(ctl, "Down")
        assert ctl.state.selected == 2
        btn(ctl, "Right")
        assert ctl.state.screen is ScreenId.TRACK_GEN
        view = ctl.build_view(engine.get_status(), NOW)
        assert view.track is not None
        assert view.track.name == "Stab 1"
        assert view.title == "GEN: Stab 1"

    def test_shift_delete_flashes_result(self) -> None:
        """Shift+Delete показывает результат во flash (в т.ч. сброс зависимых)."""
        tracks = (make_track("Pad 1"), make_track("Pad 2", sources=("Pad 1",)))
        ctl, engine, _ = make_controller(tracks)
        engine.feedback["remove_track"] = 'deleted track "Pad 1"'
        btn(ctl, "Shift")
        btn(ctl, "Delete")
        assert engine.called("remove_track") == [("Pad 1",)]
        assert ctl.state.flash_text == 'deleted track "Pad 1"'
        assert ctl.state.flash_deadline == NOW + 3.0  # дефолт flash TTL

    def test_delete_arms_and_disarms(self) -> None:
        """Delete без Shift вооружает удаление (без engine-вызовов)."""
        ctl, engine, _ = make_controller((make_track("A"),))
        btn(ctl, "Delete")
        assert ctl.state.delete_armed is True
        assert engine.calls == []
        assert ctl.state.flash_text is not None
        btn(ctl, "Delete")  # повторный — разоружает
        assert ctl.state.delete_armed is False

    def test_armed_delete_lower_row_removes_track(self) -> None:
        """DELETE + LOWER ROW N удаляет дорожку на позиции N (со сбросом armed)."""
        tracks = (make_track("A"), make_track("B"), make_track("C"))
        ctl, engine, _ = make_controller(tracks)
        engine.feedback["remove_track"] = 'deleted track "B"'
        btn(ctl, "Delete")  # armed
        btn(ctl, "Lower Row 2")  # B
        assert engine.called("remove_track") == [("B",)]
        assert ctl.state.delete_armed is False
        assert ctl.state.flash_text == 'deleted track "B"'

    def test_armed_delete_lower_row_empty_slot_noop(self) -> None:
        """DELETE + LOWER ROW на пустом слоте — разоружает, ничего не удаляет."""
        ctl, engine, _ = make_controller((make_track("A"),))
        btn(ctl, "Delete")
        btn(ctl, "Lower Row 5")  # пусто
        assert engine.calls == []
        assert ctl.state.delete_armed is False

    def test_delete_without_shift_no_engine_call(self) -> None:
        """Вооружение Delete не зовёт движок (защита от случайного удаления)."""
        tracks = (make_track("Pad 1"),)
        ctl, engine, _ = make_controller(tracks)
        btn(ctl, "Delete")
        assert engine.calls == []


class TestDemoScreen:
    """DEMO (Note, CC 50) — демо-экран фреймворка.

    Экран обязан быть достижим кнопкой, отдавать DTO, крутить вкладки
    энкодерами E1/E2 и значения E3–E8, и не ломать навигацию по табам
    (стрелки на нём заняты, _step_screen не должен получить ScreenId.DEMO).
    """

    def test_note_button_opens_demo(self) -> None:
        ctl, _, _ = make_controller()
        btn(ctl, "Note")
        assert ctl.state.screen is ScreenId.DEMO

    def test_view_has_demo_body(self) -> None:
        ctl, _, _ = make_controller()
        btn(ctl, "Note")
        view = ctl.build_view(ctl._engine.get_status(), NOW)
        assert view.screen == "demo"
        assert view.tab is None  # DEMO вне табов
        assert view.demo is not None
        assert len(view.demo.values) == 6

    def test_title_is_not_ports(self) -> None:
        ctl, engine, _ = make_controller()
        btn(ctl, "Note")
        view = ctl.build_view(engine.get_status(), NOW)
        assert view.title == "DEMO: FRAMEWORK"

    def test_arrows_change_tabs_not_screens(self) -> None:
        ctl, engine, _ = make_controller()
        btn(ctl, "Note")
        top0 = ctl.state.demo_top
        bottom0 = ctl.state.demo_bottom
        btn(ctl, "Right")
        btn(ctl, "Down")
        assert ctl.state.screen is ScreenId.DEMO  # остались на экране
        assert ctl.state.demo_top != top0
        assert ctl.state.demo_bottom != bottom0
        # Left на DEMO не должен уходить в _step_screen (иначе ValueError)
        btn(ctl, "Left")
        assert ctl.state.screen is ScreenId.DEMO

    def test_e1_e2_cycle_tabs(self) -> None:
        ctl, engine, _ = make_controller()
        btn(ctl, "Note")
        top0 = ctl.state.demo_top
        enc(ctl, 1, 1)
        assert ctl.state.demo_top != top0
        bottom0 = ctl.state.demo_bottom
        enc(ctl, 2, 1)
        assert ctl.state.demo_bottom != bottom0

    def test_e3_e8_set_values_with_clamp(self) -> None:
        ctl, engine, _ = make_controller()
        btn(ctl, "Note")
        start = ctl.state.demo_values[0]
        enc(ctl, 3, 10)
        assert ctl.state.demo_values[0] == min(127, start + 10)
        enc(ctl, 8, 127)  # кламп в 127
        assert ctl.state.demo_values[5] == 127
        enc(ctl, 8, -127)  # кламп в 0
        assert ctl.state.demo_values[5] == 0
        # Демо-экран не командует движком.
        assert engine.calls == []

    def test_values_length_is_always_six(self) -> None:
        ctl, engine, _ = make_controller()
        ctl.state.demo_values = (1, 2)  # искусственно битая длина
        btn(ctl, "Note")
        view = ctl.build_view(engine.get_status(), NOW)
        assert len(view.demo.values) == 6
        assert view.demo.values[2] == 64  # DEMO_VALUE_DEFAULT

    def test_note_led_lit_on_demo(self) -> None:
        ctl, engine, _ = make_controller()
        btn(ctl, "Note")
        states = ctl.button_led_states(engine.get_status())
        assert states["Note"] == LED_GREEN

    def test_other_screen_untouched(self) -> None:
        """Возврат на TRACKS: состояние DEMO сохраняется, экран переключился."""
        ctl, engine, _ = make_controller()
        btn(ctl, "Note")
        btn(ctl, "Left")
        enc(ctl, 3, 5)
        btn(ctl, "Session")
        assert ctl.state.screen is ScreenId.TRACKS
        view = ctl.build_view(engine.get_status(), NOW)
        assert view.demo is None
        assert view.tracks is not None
