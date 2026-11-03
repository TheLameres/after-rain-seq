#!/usr/bin/env python3
"""
Spike D2: UI-сценарии 1–9 в simulate-режиме (план D2 §5 + переразметка
02.11.2026, E2E-проверка).

Сценарий в одном процессе (`App(--simulate)` + on_frame превью PushDisplay):
1. Wizard Add Track ×2 → на TRACKS 2 дорожки; заголовок «TRACKS 1-8/1».
2. Right → GEN; E4 (DEN) меняет track.density у stab; Device → MACRO,
   E1 (TONE) без порта → значение сохраняется, в view «—».
3. PORTS: E2 назначает порт дорожке → TrackSummary.port появился.
4. SCALE (кнопка Scale): E1 крутит root; стрелки Left/Right — root,
   Up/Down — лад; касание Tempo Encoder → flash с BPM (статус-бара нет, D2-5).
5. SETUP (кнопка Setup): вкладки clock/midi/link (Up/Down), E1 меняет
   источник клока (только на вкладке clock); вернуть internal.
6. Shift+Delete → дорожка удалена, зависимая сброшена, flash показан.
   (Shift после сценария отпускается btn_up — иначе Delete идёт по Shift-ветке.)
7. Wizard: kind → Drum → route (порт main) — Drum 1 создан и привязан;
   melodic → profile (stab) → route «—» — Stab 2 создан без порта.
8. Session → TRACKS; Lower Row 2 → GEN дорожки по позиции; Lower Row 8
   (пусто) — курсор перенесён.
9. DELETE + LOWER ROW: Delete вооружается (LED красный), Lower Row 4
   удаляет Stab 2; Delete разоружён, flash показан; карта LED проверена.

Проверка — ассерты по view/снапшоту + PNG-дампы кадров в spikes/out/.

Запуск:
    PYTHONPATH=. .venv/bin/python spikes/spike_ui_simulate.py
"""

import tempfile
import threading
import time
from pathlib import Path

OUT_DIR = Path(__file__).parent / "out"
PUMP_SECONDS = 0.25  # main loop (5 мс sleep) успевает drain + render

CONFIG_TEMPLATE = """\
logging:
  level:
    root: INFO

sync:
  enabled: true
  clock_source: "internal"
  midi_clock_device: null
  bpm: 120.0
  swing_amount: 0.0

ports:
  outputs:
    - label: "main"
      match: "No Such Synth"
      role: melodic
      serial: null
      no_automation: false
  inputs: []

cc_map:
  default:
    filter: 74
    resonance: 71
  ports: {}

mutation:
  enabled: true
  mutate_min_seconds: 8.0
  mutate_max_seconds: 16.0
  default_mutate: 0.5
  drift_step_gate: 0.05
  drift_step_density: 0.1
  drift_step_register: 1.0

devices:
  push2:
    enabled: true
    brightness: 100
    use_user_midi_port: false
    simulate: false
    display_enabled: true
    display_fps: 25
    encoder_banks: []
    global_encoders:
      tempo: null
      swing: null
      master: null
  lcxl3:
    enabled: false
    midi_in_port_name: "LCXL3 1 DAW Out"
    midi_out_port_name: "LCXL3 1 DAW In"
    encoder_banks: []
    faders: []
"""


class Checker:
    """Ассерты с накоплением: все сценарии прогоняются, FAIL не обрывает."""

    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, cond: bool, label: str, detail: str = "") -> None:
        status = "ok " if cond else "FAIL"
        print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
        if not cond:
            self.failures.append(label)


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", prefix="ars_ui_", delete=False
    ) as tmp:
        tmp.write(CONFIG_TEMPLATE)
    config_path = Path(tmp.name)

    from src.app.application import App
    from src.app.engine_control import AppEngineControl
    from src.app.ui.macro_axes import MacroAxis
    from src.app.ui.ui_event import UiEvent
    from src.app.ui.ui_state import PAGE_SIZE
    from src.devices.push2.push2_device import Push2Device

    app = App(config_path=str(config_path), simulate=True)
    control = AppEngineControl(app)

    run_thread = threading.Thread(target=app.run, kwargs={"repl": None}, daemon=True)
    run_thread.start()

    # Дождаться поднятия UI внутри run().
    deadline = time.monotonic() + 10
    while app._ui is None and time.monotonic() < deadline:
        time.sleep(0.05)
    if app._ui is None:
        print("[ui] FAIL: ScreenController не создан")
        return 1

    # Превью-кадры с PushDisplay (emulator callback).
    frames: list = []
    push2 = next(
        s.device for s in app._device_manager.slots if isinstance(s.device, Push2Device)
    )
    push2.set_display_frame_callback(frames.append)

    chk = Checker()

    def pump(seconds: float = PUMP_SECONDS) -> None:
        time.sleep(seconds)

    def btn(name: str) -> None:
        app._ui_queue.put(UiEvent.button(name, True))
        pump(0.05)

    def btn_up(name: str) -> None:
        # Отпускание кнопки (нужно для модификаторов вроде Shift).
        app._ui_queue.put(UiEvent.button(name, False))
        pump(0.05)

    def enc(idx: int, increment: int = 1) -> None:
        app._ui_queue.put(UiEvent.encoder(f"Track{idx} Encoder", increment))
        pump(0.05)

    def view():
        return app._ui.build_view(app._status_snapshot, time.monotonic())

    def snap():
        return app._status_snapshot

    def save_png(name: str) -> None:
        if frames:
            frames[-1].save(OUT_DIR / f"{name}.png")
            print(f"  [png] {OUT_DIR / f'{name}.png'} ({len(frames)} кадров)")
        else:
            print(f"  [png] нет кадров для {name}!")

    try:
        # ── Сценарий 1: Add Track wizard ×2 (pad, route «—») ────────────
        print("\n[ui] Сценарий 1: Add Track wizard ×2 (pad)")
        for _ in range(2):
            btn("Add Track")  # wizard: kind
            btn("Right")  # melodic → profile
            btn("Right")  # pad (профиль 0) → route
            btn("Right")  # route «—» → создать без порта
        pump()
        v = view()
        chk.check(v.screen == "tracks", "экран TRACKS")
        chk.check(
            len(v.tracks or ()) == 2,
            "2 дорожки на TRACKS",
            f"rows={len(v.tracks or ())}",
        )
        chk.check("1-8/1" in v.title, "заголовок «1-8/1»", f"title={v.title!r}")
        save_png("ui_1_tracks")

        # Stab-дорожка для DEN (pad — chord_source, density не применяется).
        print(f"[ui] create stab: {control.create_track('stab')}")
        pump()

        # ── Сценарий 2: Right → GEN, E4 DEN; Device → MACRO, E1 TONE ────
        print("\n[ui] Сценарий 2: GEN (E4 DEN), MACRO (E1 TONE)")
        for _ in range(PAGE_SIZE):  # курсор вниз → кламп к Stab 1
            btn("Down")
        btn("Clip")  # → GEN выбранной (Stab 1)
        pump()
        v = view()
        chk.check(v.screen == "gen", "экран GEN")
        chk.check(
            v.track is not None and v.track.name == "Stab 1",
            "открыт Stab 1",
            f"track={getattr(v.track, 'name', None)!r}",
        )
        chk.check(
            v.track is not None and v.track.color != 0,
            "у дорожки есть цвет (полоса GEN)",
            f"color={getattr(v.track, 'color', None)!r}",
        )
        density_before = app._session.get_track("Stab 1").density
        enc(4, -10)  # E4 DEN: −10/127 (вниз — вверх кламп 1.0)
        pump()
        density_after = app._session.get_track("Stab 1").density
        chk.check(
            density_after < density_before,
            "E4 меняет track.density",
            f"{density_before:.3f} → {density_after:.3f}",
        )
        v = view()
        chk.check(
            v.track is not None and v.track.density is not None,
            "DEN применим и виден в view (не «—»)",
            f"density={getattr(v.track, 'density', None)!r}",
        )
        save_png("ui_2_track_gen")
        btn("Device")  # → MACRO выбранной (Stab 1)
        pump()
        v = view()
        chk.check(v.screen == "macro", "экран MACRO (Device)")
        chk.check(
            v.track_macro is not None and v.track_macro.name == "Stab 1",
            "MACRO открыт для Stab 1",
            f"track_macro={getattr(v.track_macro, 'name', None)!r}",
        )
        enc(1, 5)  # E1 TONE: порт не назначен
        pump()
        tone_value = app._ui.state.macro_value("Stab 1", MacroAxis.TONE.value)
        chk.check(
            0 <= tone_value <= 127, "TONE сохранён в UiState", f"value={tone_value}"
        )
        v = view()
        chk.check(
            v.track_macro is not None and v.track_macro.macros[0] == -1,
            "TONE в view «—» (порт не назначен)",
            f"macros={getattr(v.track_macro, 'macros', None)!r}",
        )
        save_png("ui_2b_track_macro")

        # ── Сценарий 3: PORTS — назначить порт ──────────────────────────
        print("\n[ui] Сценарий 3: PORTS, назначение main")
        btn("Mix")
        pump()
        v = view()
        chk.check(v.screen == "ports", "экран PORTS")
        chk.check(
            v.ports is not None and len(v.ports.rows) == 1,
            "1 сконфигурированный порт в списке",
            f"rows={len(v.ports.rows) if v.ports else 0}",
        )
        # E1: крутим, пока не выберем Pad 1 (курсор PORTS живёт своей жизнью).
        for _ in range(3):
            v = view()
            if v.ports is not None and v.ports.route_track == "Pad 1":
                break
            enc(1, 1)
            pump()
        v = view()
        chk.check(
            v.ports is not None and v.ports.route_track == "Pad 1",
            "дорожка для назначения — Pad 1",
            f"route_track={v.ports.route_track if v.ports else None!r}",
        )
        enc(2, 1)  # E2: None → main (применение сразу)
        pump()
        pad1 = next(t for t in snap().tracks if t.name == "Pad 1")
        chk.check(pad1.port == "main", "Pad 1 получил порт main", f"port={pad1.port!r}")
        v = view()
        chk.check(
            v.ports is not None and v.ports.route_port == "main",
            "route_port в view = main",
            f"route_port={v.ports.route_port if v.ports else None!r}",
        )
        save_png("ui_3_ports")

        # ── Сценарий 4: SCALE — крутим root (кнопка Scale) ──────────────
        print("\n[ui] Сценарий 4: SCALE (Scale button), E1 (root)")
        btn("Scale")  # CC 58
        pump()
        v = view()
        chk.check(v.screen == "scale", "экран SCALE (кнопка Scale)")
        chk.check(
            v.scale is not None and v.scale.root_index >= 0,
            "вид SCALE: корни и лады",
            f"roots={len(v.scale.roots) if v.scale else 0}",
        )
        root_before = snap().root
        enc(1, 1)  # E1 root +1
        pump()
        v = view()
        chk.check(
            snap().root != root_before,
            "root изменился",
            f"{root_before} → {snap().root}",
        )
        btn("Right")  # стрелки на SCALE: корень +1
        pump()
        v = view()
        chk.check(
            v.scale is not None and v.scale.roots[v.scale.root_index] == snap().root,
            "выбранный корень совпадает со статусом",
            f"root={snap().root}",
        )
        harmony_root = app._harmony.root if app._harmony else None
        chk.check(
            str(harmony_root) == snap().root,
            "статус совпадает с Harmony",
            f"harmony={harmony_root} status={snap().root}",
        )
        # Касание Tempo Encoder (D2-5): BPM показывается во flash-строке.
        btn("Tempo Encoder")
        pump()
        chk.check(
            view().flash is not None and "BPM" in (view().flash or ""),
            "касание Tempo → flash с BPM",
            f"flash={view().flash!r}",
        )
        save_png("ui_4_scale")

        # ── Сценарий 5: SETUP — суб-вкладки + переключение источника ────
        print("\n[ui] Сценарий 5: SETUP (Setup button), вкладки, E1 (clock)")
        btn("Setup")  # CC 30
        pump()
        v = view()
        chk.check(v.screen == "setup", "экран SETUP (кнопка Setup)")
        chk.check(
            v.sync is not None and v.sync.tab == "clock",
            "вкладка CLOCK активна",
            f"tab={v.sync.tab if v.sync else None!r}",
        )
        btn("Down")  # clock → midi
        pump()
        v = view()
        chk.check(
            v.sync is not None and v.sync.tab == "midi",
            "вкладка MIDI",
            f"tab={v.sync.tab if v.sync else None!r}",
        )
        save_png("ui_5a_setup_midi")
        btn("Up")  # назад на clock
        pump()
        source_before = v.sync.source if v.sync else None
        print(f"[ui] start transport: {control.start_transport()}")
        enc(1, 1)  # internal → midi
        pump()
        v = view()
        pending = v.sync.pending if v.sync else None
        source_now = v.sync.source if v.sync else None
        chk.check(
            pending is not None or source_now != source_before,
            "pending или смена источника видна",
            f"source={source_before}→{source_now} pending={pending!r}",
        )
        pump(1.0)  # квантизация на долю: 120 bpm → 0.5 с
        v = view()
        chk.check(
            v.sync is not None and v.sync.source == "midi",
            "источник стал midi после квантизации",
            f"source={v.sync.source if v.sync else None!r}",
        )
        enc(1, -1)  # midi → internal
        pump(1.0)
        v = view()
        chk.check(
            v.sync is not None and v.sync.source == "internal",
            "вернули internal",
            f"source={v.sync.source if v.sync else None!r}",
        )
        print(f"[ui] stop transport: {control.stop_transport()}")
        save_png("ui_5_setup")

        # ── Сценарий 6: Shift+Delete ────────────────────────────────────
        print("\n[ui] Сценарий 6: Shift+Delete")
        # Pad 2 зависит от Pad 1 (стратегия B: сброс после удаления).
        print(f"[ui] set sources: {control.set_track_sources('Pad 2', 'Pad 1')}")
        pump()
        btn("Session")  # TRACKS (кнопка Session, CC 51)
        for _ in range(PAGE_SIZE):
            btn("Up")  # курсор → 0 (Pad 1)
        pump()
        v = view()
        chk.check(
            v.tracks is not None and v.tracks[0].name == "Pad 1",
            "курсор на Pad 1",
            f"row0={v.tracks[0].name if v.tracks else None!r}",
        )
        btn("Shift")
        btn("Delete")
        btn_up("Shift")  # отпускаем, иначе Delete в след. сценариях идёт по Shift-ветке
        pump()
        names = [t.name for t in snap().tracks]
        chk.check("Pad 1" not in names, "Pad 1 удалён", f"tracks={names}")
        pad2 = app._session.get_track("Pad 2")
        chk.check(
            pad2 is not None and tuple(pad2.sources) == (),
            "Pad 2 sources сброшены (стратегия B)",
            f"sources={tuple(pad2.sources) if pad2 else None!r}",
        )
        flash = app._ui.state.flash_text
        chk.check(flash is not None, "flash показан", f"flash={flash!r}")
        save_png("ui_6_after_delete")

        # ── Сценарий 7: wizard — kind → profile → route (порт) ──────────
        print("\n[ui] Сценарий 7: wizard (drum → route main; melodic stab → route —)")
        btn("Add Track")  # wizard: kind
        v = view()
        chk.check(v.screen == "wizard", "wizard открыт", f"screen={v.screen!r}")
        chk.check(
            v.wizard is not None and v.wizard.step == "kind",
            "шаг kind",
            f"step={v.wizard.step if v.wizard else None!r}",
        )
        save_png("ui_7_wizard_kind")
        btn("Down")  # melodic → drum
        btn("Right")  # kind → route
        v = view()
        chk.check(
            v.wizard is not None and v.wizard.step == "route",
            "шаг route (drum)",
            f"step={v.wizard.step if v.wizard else None!r}",
        )
        save_png("ui_7a_wizard_route")
        btn("Down")  # «—» → «main»
        btn("Right")  # создать Drum 1 и сразу привязать к main
        pump()
        drum1 = next((t for t in snap().tracks if t.name == "Drum 1"), None)
        chk.check(
            drum1 is not None and drum1.port == "main",
            "Drum 1 создан и привязан к main",
            f"port={drum1.port if drum1 else None!r}",
        )
        btn("Add Track")  # wizard: kind
        btn("Right")  # melodic → profile
        v = view()
        chk.check(
            v.wizard is not None and v.wizard.step == "profile",
            "шаг profile",
            f"step={v.wizard.step if v.wizard else None!r}",
        )
        for _ in range(3):
            btn("Down")  # профиль 0 (pad) → 3 (stab)
        btn("Right")  # profile → route
        btn("Right")  # route «—»: создать Stab 2 без порта
        pump()
        stab2 = next((t for t in snap().tracks if t.name == "Stab 2"), None)
        chk.check(
            stab2 is not None and stab2.port is None,
            "Stab 2 создан без порта",
            f"port={stab2.port if stab2 else None!r} tracks={[t.name for t in snap().tracks]}",
        )
        flash = app._ui.state.flash_text
        chk.check(flash is not None, "flash показан", f"flash={flash!r}")
        save_png("ui_7b_wizard_profile")

        # ── Сценарий 8: Session → TRACKS, Lower Row → GEN по позиции ────
        print("\n[ui] Сценарий 8: Session + Lower Row")
        btn("Session")  # TRACKS
        pump()
        v = view()
        chk.check(v.screen == "tracks", "Session открывает TRACKS")
        save_png("ui_8_session_tracks")
        # После удаления Pad 1: ['Pad 2', 'Stab 1', 'Drum 1', 'Stab 2'].
        btn("Lower Row 2")  # Stab 1
        pump()
        v = view()
        chk.check(v.screen == "gen", "Lower Row открывает GEN")
        chk.check(
            v.track is not None and v.track.name == "Stab 1",
            "Lower Row 2 → Stab 1",
            f"track={getattr(v.track, 'name', None)!r}",
        )
        btn("Lower Row 8")  # пустой слот — курсор переносится, экран не меняется
        pump()
        v = view()
        chk.check(
            v.screen == "gen",
            "Lower Row 8 (пусто) — курсор перенесён, экран GEN",
            f"screen={v.screen!r}",
        )

        # ── Сценарий 9: DELETE + LOWER ROW удаляет трек ─────────────────
        print("\n[ui] Сценарий 9: DELETE + LOWER ROW")
        from src.app.ui.screen_controller import LED_RED

        btn("Session")  # TRACKS
        pump()
        led_states = app._ui.button_led_states(snap())
        chk.check(
            led_states.get("Play", 0) > 0 and led_states.get("Session", 0) > 0,
            "рабочие кнопки подсвечены (карта LED)",
            f"play={led_states.get('Play')} session={led_states.get('Session')}",
        )
        btn("Delete")  # armed
        pump()
        chk.check(app._ui.state.delete_armed, "Delete вооружён")
        led_states = app._ui.button_led_states(snap())
        chk.check(
            led_states.get("Delete") == LED_RED,
            "LED Delete красный при armed",
            f"delete={led_states.get('Delete')}",
        )
        btn("Lower Row 4")  # Stab 2 (индекс 3)
        pump()
        names = [t.name for t in snap().tracks]
        chk.check("Stab 2" not in names, "Stab 2 удалён (DEL+ROW)", f"tracks={names}")
        chk.check(not app._ui.state.delete_armed, "Delete разоружён после удаления")
        flash = app._ui.state.flash_text
        chk.check(
            flash is not None and "Stab 2" in flash,
            "flash показан",
            f"flash={flash!r}",
        )
        save_png("ui_9_delete_row")

        # ── Итог ────────────────────────────────────────────────────────
        print("\n[ui] === сводка ===")
        print(f"[ui] кадров превью получено: {len(frames)}")
        if frames:
            print(f"[ui] размер кадра: {frames[-1].size} {frames[-1].mode}")
        if chk.failures:
            print(f"[ui] FAIL ({len(chk.failures)}):")
            for f in chk.failures:
                print(f"  - {f}")
            return 1
        print("[ui] PASS: сценарии 1–8 выполнены")
        return 0
    finally:
        app.stop()
        run_thread.join(timeout=5)
        config_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
