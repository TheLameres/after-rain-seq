"""Application — thin orchestrator for after-rain-seq.

Owns the device connections and display renderer, wires up input callbacks,
and coordinates startup / shutdown of all subsystems.
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import queue
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from src.app.config import load_app_config
from src.app.device_manager import DeviceManager
from src.app.display import DisplayRenderer
from src.app.engine_control import AppEngineControl
from src.app.slot import DeviceSlot
from src.app.ui.macro_axes import MacroAxes
from src.app.ui.screen_controller import ScreenController
from src.app.ui.ui_event import UiEvent
from src.app.ui.ui_queue import UiEventQueue
from src.devices.push2.push2_device import Push2Device
from src.harmony.harmony import Harmony
from src.midi.factory import create_registry
from src.repl.status import PortSummary, StatusSnapshot, TrackSummary
from src.session.drum.drum_engine import DrumEngine
from src.session.engine.melodic_engine import MelodicEngine
from src.session.model.drum_track import DrumTrack
from src.session.model.melodic_track import MelodicTrack
from src.session.model.pattern_spec import FAMILY_CHORD_SLICER, FAMILY_FREE_MONO
from src.session.model.track import Track
from src.session.mutation.mutation_config import MutationConfig
from src.session.mutation.mutation_engine import MutationEngine
from src.session.session import Session
from src.sync import ClockManager, ClockManagerConfig, ClockSource, TickProxy
from src.sync.capture_output import CaptureOutput
from src.sync.cc_map import CCMap
from src.sync.ports import PortManager
from src.sync.routing import PortRegistry
from src.sync.swing import SwingApplier, SwingConfig
from src.sync.throttle import CCThrottle
from src.sync.transport import Transport
from src.sync.transport_event import TransportEvent

if TYPE_CHECKING:
    import threading

    from src.repl.repl import Repl

log = logging.getLogger(__name__)


class App:
    """Core application: connects devices, runs display loop.

    Parameters
    ----------
    config_path:
        Path to config.yaml.
    simulate:
        If True, use hardware simulator instead of real USB.
    on_device_connected:
        Optional callback invoked with True/False when device connection changes.
    """

    def __init__(
        self,
        config_path: str = "config.yaml",
        simulate: bool = False,
        on_device_connected: Callable[[bool], None] | None = None,
        on_devices_changed: Callable[[list[str]], None] | None = None,
    ) -> None:
        self._config_path = config_path
        self._simulate = simulate
        self._running = False

        self._cb_device_connected = on_device_connected or (lambda _v: None)
        self._cb_devices_changed = on_devices_changed or (lambda _n: None)

        # Subsystems
        self._device_manager: DeviceManager | None = None
        self._display_renderer: DisplayRenderer | None = None
        self._clock_manager: ClockManager | None = None
        self._tick_proxy: TickProxy | None = None
        self._port_manager: PortManager | None = None
        self._port_registry: PortRegistry | None = None
        self._capture: CaptureOutput | None = None
        self._transport: Transport | None = None
        self._session: Session | None = None
        self._drum_engines: list[DrumEngine] = []
        self._melodic_engines: list[MelodicEngine] = []
        self._mutation_engine: MutationEngine | None = None
        self._harmony: Harmony | None = None
        self._event_queue: queue.Queue[TransportEvent] | None = None
        self._swing_applier: SwingApplier | None = None
        self._sync_bpm: float = 120.0
        self._midi_clock_device: str = ""

        # REPL (F1): снапшот состояния для терминального фронтенда.
        # Собирается в main loop, публикуется атомарной заменой ссылки.
        self._status_snapshot: StatusSnapshot = StatusSnapshot.empty()
        self._repl: Repl | None = None
        self._repl_thread: threading.Thread | None = None

        # D2: UI Push 2 — очередь событий (MIDI-поток → main loop),
        # контроллер экранов, фасад команд (общий с REPL-стилем).
        self._engine_control: AppEngineControl | None = None
        self._ui_queue: UiEventQueue | None = None
        self._ui: ScreenController | None = None
        self._last_led_states: dict[str, int] = {}

        atexit.register(self._atexit_cleanup)

    def run(self, repl: Repl | None = None) -> None:
        """Start all subsystems and block until stop() is called.

        Parameters
        ----------
        repl:
            Optional REPL instance (flag ``--repl``). Started in a daemon
            thread alongside the main loop; stopped and joined on cleanup.
        """
        self._running = True
        self._repl = repl

        # 1. Load config
        loaded = load_app_config(self._config_path, self._simulate)

        # 2. Create device manager
        self._device_manager = DeviceManager(
            config=loaded,
            simulate=self._simulate,
            on_device_connected=self._cb_device_connected,
            on_devices_changed=self._cb_devices_changed,
        )

        # 3. Wire device input callbacks
        self._device_manager.on_pad = self._on_device_pad
        self._device_manager.on_button = self._on_device_button
        self._device_manager.on_encoder = self._on_device_encoder
        self._device_manager.on_fader = self._on_device_fader

        # 4. Create display renderer
        self._display_renderer = DisplayRenderer(fps=loaded.display_fps)

        # 5. Create port manager + registry (with CC mapping and throttling)
        self._init_port_manager(loaded.ports_config, loaded.cc_map_config)

        # 6. Create session
        self._session = Session()

        # 6b. D2: UI controller (Push 2 screens) — независимо от REPL.
        # Команды идут через AppEngineControl (тот же фасад, что у REPL);
        # MIDI-поток только кладёт события в очередь (паттерн TickProxy).
        self._engine_control = AppEngineControl(self)
        self._ui_queue = UiEventQueue()
        self._ui = ScreenController(
            self._engine_control,
            MacroAxes.from_ui_config(loaded.ui_config),
            cc_sender=self._send_cc,
            ui_config=loaded.ui_config,
        )

        # 7. Create clock manager + tick proxy (creates event_queue + swing)
        if loaded.sync_config.enabled:
            self._init_clock_manager(loaded.sync_config)

        # 8. Create drum engines (needs event_queue + swing from clock manager)
        self._init_drum_engines(loaded.drum_config)

        # 8b. Create mutation engine + melodic engines
        self._init_mutation(loaded.mutation_config)
        self._init_melodic_engines()

        # 9. Connect all devices
        self._device_manager.connect_all()

        if self._clock_manager is not None:
            self._clock_manager.start()

        # 9b. Start REPL thread (F1) alongside the main loop
        if repl is not None:
            self._repl_thread = repl.start()

        # 10. Initial display render
        if self._device_manager and self._device_manager.slots:
            for slot in self._device_manager.slots:
                if slot.device.supports_display:
                    try:
                        state = self._display_renderer.build_display_state(
                            slot,
                            self._device_manager.slots,
                        )
                        slot.device.render_display(state)
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "Display render error (%s): %s", slot.device.name, exc
                        )

        # 11. Main loop — render at configured fps, poll ports for hot-plug
        log.info("after-rain-seq running (fps=%d)", loaded.display_fps)
        _last_render = 0.0
        _last_port_poll = 0.0
        _port_poll_interval = 2.0  # seconds
        while self._running:
            now = time.monotonic()

            # Status snapshot for REPL (F1) — атомарная замена ссылки
            self._update_status_snapshot()

            # D2: UI-события Push 2 — drain и обработка в main loop.
            if self._ui is not None and self._ui_queue is not None:
                for ev in self._ui_queue.drain():
                    try:
                        self._ui.handle(ev, now)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("UI event handling error: %s", exc)
                self._update_button_leds()

            # Hot-plug polling
            if self._port_manager and now - _last_port_poll >= _port_poll_interval:
                self._poll_ports()
                _last_port_poll = now

            # Display rendering
            if (
                self._device_manager
                and self._display_renderer
                and now - _last_render >= self._display_renderer.frame_interval
            ):
                sync_state = self._clock_manager.state if self._clock_manager else None
                screen_view = (
                    self._ui.build_view(self._status_snapshot, now)
                    if self._ui is not None
                    else None
                )
                self._display_renderer.render_frame(
                    self._device_manager.slots,
                    sync_state=sync_state,
                    screen_view=screen_view,
                )
                _last_render = now
            time.sleep(0.005)

        # 10. Cleanup
        self._cleanup()

    # ------------------------------------------------------------------
    # Input callbacks (from DeviceManager)
    # ------------------------------------------------------------------

    def _on_device_pad(self, slot: DeviceSlot, pad_n: int, velocity: int) -> None:
        """Called by device driver on pad press/release."""
        log.debug("Pad %d vel=%d on %s", pad_n, velocity, slot.device.name)
        # TODO(Phase 4/D3): route to pads.py for CHORDS/NOTES/MORPH/DRUM modes

    def _on_device_button(
        self, slot: DeviceSlot, button_name: str, pressed: bool
    ) -> None:
        """Called by device driver on button press/release."""
        if isinstance(slot.device, Push2Device) and self._ui_queue is not None:
            # D2: в очередь; обработка — в main loop (drain), не здесь.
            self._ui_queue.put(UiEvent.button(button_name, pressed))
            return
        log.debug("Button %s %s on %s", button_name, pressed, slot.device.name)

    def _on_device_encoder(
        self, slot: DeviceSlot, encoder_name: str, increment: int
    ) -> None:
        """Called by device driver on encoder rotation."""
        if isinstance(slot.device, Push2Device) and self._ui_queue is not None:
            self._ui_queue.put(UiEvent.encoder(encoder_name, increment))
            return
        log.debug("Encoder %s inc=%d on %s", encoder_name, increment, slot.device.name)

    def _on_device_fader(self, slot: DeviceSlot, fader_name: str, value: int) -> None:
        """Called by device driver on fader movement."""
        log.debug("Fader %s val=%d on %s", fader_name, value, slot.device.name)
        # TODO(Phase 2/B3): route to CC mapping

    # ------------------------------------------------------------------
    # UI helpers (D2)
    # ------------------------------------------------------------------

    def _update_button_leds(self) -> None:
        """Подсветить рабочие кнопки Push 2 (дифф-отправка, однократно).

        Карту состояний строит ScreenController (знает назначения и
        контекст: armed Delete, выбранная дорожка, running, табы).
        """
        if self._ui is None:
            return
        snap = self._status_snapshot
        if snap is None:
            return
        states = self._ui.button_led_states(snap)
        if states == self._last_led_states:
            return
        self._last_led_states = dict(states)
        if not self._device_manager:
            return
        for slot in self._device_manager.slots:
            if isinstance(slot.device, Push2Device) and slot.device.is_connected:
                slot.device.set_button_leds(states)

    def _send_cc(self, port_label: str, param: str, channel: int, value: int) -> None:
        """Отправить CC по логическому имени параметра через PortRegistry."""
        registry = self._port_registry
        if registry is None:
            return
        out = registry.get_output(port_label)
        if out is None:
            return
        out.control(param, channel, value)

    # ------------------------------------------------------------------
    # Port manager helpers
    # ------------------------------------------------------------------

    def _init_port_manager(self, ports_config, cc_map_config) -> None:
        """Create PortManager and PortRegistry from ports config."""
        registry = create_registry()
        self._port_manager = PortManager(ports_config, registry)
        # start() возвращает события начального скана — иначе порт,
        # подключённый до старта, не откроется в PortRegistry (hot-plug
        # эмитит событие только при смене статуса на следующем poll).
        start_events = self._port_manager.start()

        cc_map = CCMap(cc_map_config)
        throttle = CCThrottle(max_rate_hz=30.0)
        self._port_registry = PortRegistry(
            self._port_manager,
            cc_map=cc_map,
            throttle=throttle,
        )
        for event in start_events:
            self._port_registry.handle_port_event(event)

    def _poll_ports(self) -> None:
        """Check for port changes and handle hot-plug events."""
        if not self._port_manager or not self._port_registry:
            return
        events = self._port_manager.poll()
        for event in events:
            self._port_registry.handle_port_event(event)
            # TODO(Phase 5/E1): notify ClockManager when clock port changes

    # ------------------------------------------------------------------
    # Clock manager helpers
    # ------------------------------------------------------------------

    def _init_clock_manager(self, sync_config) -> None:
        """Create TickProxy, ClockManager, CaptureOutput and Transport."""
        import queue as _queue

        source_map = {
            "internal": ClockSource.INTERNAL,
            "midi": ClockSource.MIDI,
            "link": ClockSource.LINK,
        }
        initial_source = source_map.get(sync_config.clock_source, ClockSource.INTERNAL)

        # --- B4: Transport + CaptureOutput ---
        # Determine default port label from config
        default_label = self._get_default_port_label()

        # Event queue between CaptureOutput and Transport
        self._event_queue = _queue.Queue(maxsize=4096)

        # CaptureOutput intercepts isobar events into the queue.
        # Passed as output_device to Timeline so isobar does not try to
        # open a default MIDI port (which fails when no ports exist).
        self._capture = CaptureOutput(self._event_queue, port_label=default_label)

        from isobar import Timeline

        timeline = Timeline(
            tempo=sync_config.bpm,
            output_device=self._capture,
            ticks_per_beat=480,
        )

        self._tick_proxy = TickProxy(timeline)

        cm_config = ClockManagerConfig(
            initial_source=initial_source,
            initial_bpm=sync_config.bpm,
            ticks_per_beat=480,
            midi_device_name=sync_config.midi_clock_device,
        )
        self._clock_manager = ClockManager(timeline, self._tick_proxy, cm_config)
        self._midi_clock_device = sync_config.midi_clock_device or ""

        # Swing from config
        self._swing_applier = SwingApplier(SwingConfig(amount=sync_config.swing_amount))
        self._sync_bpm = sync_config.bpm

        # Transport delivers events to ports
        if self._port_registry is None:
            raise RuntimeError("PortRegistry must be initialized before Transport")
        self._transport = Transport(
            event_queue=self._event_queue,
            port_registry=self._port_registry,
            swing=self._swing_applier,
        )

        # Hook ClockManager.on_tick + MutationEngine.tick +
        # DrumEngine.tick + MelodicEngine.tick + Transport.process_events
        original_dispatch = self._tick_proxy._dispatch
        cm = self._clock_manager
        transport = self._transport
        capture = self._capture
        drum_engines = self._drum_engines
        melodic_engines = self._melodic_engines
        mutation_engine = self._mutation_engine
        session = self._session

        def hooked_dispatch(event):
            if event.name == "TICK":
                cm.on_tick()
                bpm_now = cm.state.bpm or self._sync_bpm
                # Мутация до генерации — generate() использует новые параметры.
                # §4.1: подтянуть mutate из треков (freeze / set_track_mutate
                # меняют track.mutate, а не копию в MutationEngine).
                if mutation_engine:
                    if session:
                        for track in session.ordered_tracks():
                            if isinstance(track, MelodicTrack):
                                mutation_engine.sync_mutate(track.name, track.mutate)
                    mutation_engine.tick(timeline.current_time, bpm_now)
                # C6 шаг 3: фаза графа — источники публикуют ChordEvent,
                # наследники получают их в outbox (движки читают как окно)
                if session:
                    session.propagate_chords()
                for engine in drum_engines:
                    engine.tick(timeline.current_time, bpm_now)
                for engine in melodic_engines:
                    engine.tick(timeline.current_time)
            elif event.name == "STOP":
                # C6: сброс планировщиков — после остановки не доставлять
                # запланированное «прошлое»
                for engine in melodic_engines:
                    engine.reset()
            original_dispatch(event)
            if event.name == "TICK":
                capture.beat = timeline.current_time
                transport.process_events(current_beat=timeline.current_time)

        self._tick_proxy._dispatch = hooked_dispatch  # type: ignore[method-assign]

        self._tick_proxy.start_worker()

    def _init_drum_engines(self, drum_config) -> None:
        """Создать DrumEngine для каждой DrumTrack в сессии.

        Аргументы:
            drum_config: DrumConfig из загруженного конфига.
        """
        if not self._session or not self._event_queue or not self._swing_applier:
            return
        for track in self._session.ordered_tracks():
            if isinstance(track, DrumTrack):
                engine = DrumEngine(
                    drum_track=track,
                    event_queue=self._event_queue,
                    port_label=track.port or "default",
                )
                self._drum_engines.append(engine)
                log.info("DrumEngine создан для %s", track.name)

    def _init_mutation(self, mutation_config: MutationConfig) -> None:
        """Создать MutationEngine и зарегистрировать мелодические дорожки.

        Аргументы:
            mutation_config: MutationConfig из загруженного конфига.
        """
        if not mutation_config.enabled or not self._session:
            return
        self._mutation_engine = MutationEngine(
            min_seconds=mutation_config.mutate_min_seconds,
            max_seconds=mutation_config.mutate_max_seconds,
            default_mutate=mutation_config.default_mutate,
        )
        for track in self._session.ordered_tracks():
            if isinstance(track, MelodicTrack) and not track.profile.cc_only:
                self._mutation_engine.register_track(
                    track_name=track.name,
                    profile_name=track.profile_name,
                    mutate=track.mutate,
                    bpm=self._sync_bpm,
                    degrees=list(track.degrees),
                    gate=track.gate,
                    track=track,  # §4.4: счётчик живёт на дорожке
                )
        log.info(
            "MutationEngine создан, дорожек: %d",
            len(self._mutation_engine.registered_tracks),
        )

    def _init_melodic_engines(self) -> None:
        """Создать MelodicEngine для каждой мелодической дорожки."""
        if not self._session or not self._event_queue or not self._swing_applier:
            return
        if not self._harmony:
            from src.harmony.harmony import Harmony

            self._harmony = Harmony()
        for track in self._session.ordered_tracks():
            if isinstance(track, MelodicTrack) and not track.profile.cc_only:
                engine = MelodicEngine(
                    track=track,
                    harmony=self._harmony,
                    event_queue=self._event_queue,
                    port_label=track.port or "default",
                    mutation_engine=self._mutation_engine,
                )
                self._melodic_engines.append(engine)
                log.info("MelodicEngine создан для %s", track.name)

    def _get_default_port_label(self) -> str:
        """Return the first configured output port label, or a fallback."""
        if self._port_registry and self._port_manager:
            # Try to get the first configured output label
            outputs = (
                self._port_manager._config.outputs
                if hasattr(self._port_manager, "_config")
                else []
            )
            if outputs:
                return outputs[0].label
        return "default"

    # ------------------------------------------------------------------
    # Маршрутизация дорожек (REPL: track route / track unroute)
    # ------------------------------------------------------------------

    def route_track(self, name: str, label: str) -> str:
        """Привязать дорожку к MIDI-порту (рантайм, без рестарта).

        Старый порт глушится all_notes_off, новый подхватывается на
        следующем событии (Transport резолвит адаптер по метке каждый раз).
        """
        if self._session is None:
            return "error: session not available"
        track = self._session.get_track(name)
        if track is None:
            return f"error: track {name!r} not found"
        if self._port_manager is None:
            return "error: port manager not available"
        if self._port_manager.get_state(label) is None:
            known = ", ".join(s.label for s in self._port_manager.all_states())
            return f"error: unknown port label {label!r} (configured: {known})"
        engine = self._find_engine(track)
        if engine is None:
            engine = self._create_engine_for(track)
        if engine is None:
            return f"error: cannot route track {name!r} (engine prerequisites missing)"
        old = engine.set_port_label(label)
        track.port = label
        self._silence_old_port(old, label)
        log.info("Track %s routed → port %r (was %r)", name, label, old)
        was = f' (was "{old}")' if old else ""
        return f'track "{name}" → port "{label}"{was}'

    def unroute_track(self, name: str) -> str:
        """Отключить дорожку от порта — тишина, сессия живёт."""
        if self._session is None:
            return "error: session not available"
        track = self._session.get_track(name)
        if track is None:
            return f"error: track {name!r} not found"
        engine = self._find_engine(track)
        if engine is None:
            # Движка нет — просто снимаем привязку, глушить нечего.
            track.port = None
            return f'track "{name}" disconnected'
        old = engine.set_port_label(None)
        track.port = None
        self._silence_old_port(old, None)
        log.info("Track %s disconnected (was port %r)", name, old)
        was = f' (was "{old}")' if old else ""
        return f'track "{name}" disconnected{was}'

    def drop_track(self, name: str) -> str:
        """Удалить дорожку вместе с её движком (глушит порт перед удалением)."""
        if self._session is None:
            return "error: session not available"
        try:
            self._session.remove_track(name)
        except ValueError as exc:
            return f"error: {exc}"
        removed = False
        for melodic_engine in list(self._melodic_engines):
            if melodic_engine.track.name == name:
                self._silence_engine(melodic_engine)
                self._melodic_engines.remove(melodic_engine)
                removed = True
        for drum_engine in list(self._drum_engines):
            if drum_engine.track.name == name:
                self._silence_engine(drum_engine)
                self._drum_engines.remove(drum_engine)
                removed = True
        log.info("Track %s deleted (engine removed: %s)", name, removed)
        return f'deleted track "{name}"'

    def _silence_engine(self, engine: MelodicEngine | DrumEngine) -> None:
        """All notes off на текущем порту движка и перевод в тишину."""
        old = engine.set_port_label(None)
        self._silence_old_port(old, None)

    def _create_engine_for(self, track: Track) -> MelodicEngine | DrumEngine | None:
        """Создать движок для дорожки, добавленной после старта (on demand).

        Melodic-дорожки с профилем cc_only движка не получают (CC-only).
        Returns:
            Созданный движок или None, если prerequisites недоступны.
        """
        if self._event_queue is None or self._swing_applier is None:
            return None
        if isinstance(track, DrumTrack):
            drum_engine = DrumEngine(
                drum_track=track,
                event_queue=self._event_queue,
                port_label=None,  # порт назначит route_track
            )
            self._drum_engines.append(drum_engine)
            log.info("DrumEngine создан для %s (on demand)", track.name)
            return drum_engine
        if isinstance(track, MelodicTrack) and not track.profile.cc_only:
            if self._harmony is None:
                self._harmony = Harmony()
            melodic_engine = MelodicEngine(
                track=track,
                harmony=self._harmony,
                event_queue=self._event_queue,
                port_label=None,
                mutation_engine=self._mutation_engine,
            )
            self._melodic_engines.append(melodic_engine)
            log.info("MelodicEngine создан для %s (on demand)", track.name)
            return melodic_engine
        return None

    def _find_engine(self, track: Track) -> MelodicEngine | DrumEngine | None:
        """Найти движок, обслуживающий дорожку."""
        for melodic_engine in self._melodic_engines:
            if melodic_engine.track is track:
                return melodic_engine
        for drum_engine in self._drum_engines:
            if drum_engine.track is track:
                return drum_engine
        return None

    def _silence_old_port(self, old: str | None, new: str | None) -> None:
        """All notes off на старом порту при смене/отключении."""
        if old is None or old == new or self._event_queue is None:
            return
        try:
            self._event_queue.put_nowait(TransportEvent.all_notes_off(port_label=old))
        except queue.Full:
            log.warning("route: event queue full, all_notes_off lost")

    # ------------------------------------------------------------------
    # Status snapshot for REPL (F1)
    # ------------------------------------------------------------------

    def _update_status_snapshot(self) -> None:
        """Собрать StatusSnapshot из объектов движка (main loop only).

        Читает только публичные снапшотные API (ClockState, PortState)
        и простые атрибуты; публикует атомарной заменой ссылки
        (под GIL замена ссылки атомарна, замок не нужен).
        """
        cm = self._clock_manager
        if cm is not None:
            clock_state = cm.state
            bpm = clock_state.bpm if clock_state.bpm is not None else self._sync_bpm
            snap = StatusSnapshot(
                running=clock_state.running,
                bpm=bpm,
                swing=self._swing_applier.amount if self._swing_applier else 0.0,
                clock_source=clock_state.source.name.lower(),
                clock_pending=(
                    clock_state.pending.name.lower() if clock_state.pending else None
                ),
                clock_error=clock_state.error,
                link_active=clock_state.link_active,
                link_peers=clock_state.link_peers,
                root=self._harmony.root if self._harmony else "A",
                scale=self._harmony.scale_name if self._harmony else "dorian",
                tracks=self._track_summaries(),
                total_mutations=(
                    self._session.total_mutation_count if self._session else 0
                ),
                ports=self._port_summaries(),
                log_error=self._status_snapshot.log_error,
                midi_clock_device=self._midi_clock_device,
            )
        else:
            snap = StatusSnapshot.empty()
        self._status_snapshot = snap

    def _track_summaries(self) -> tuple[TrackSummary, ...]:
        """Сводки дорожек сессии в топологическом порядке."""
        if not self._session:
            return ()
        tracks: list[Track] = []
        try:
            tracks = self._session.ordered_tracks()
        except ValueError:  # цикл в графе — не роняем main loop
            for name in self._session.track_names():
                track = self._session.get_track(name)
                if track is not None:
                    tracks.append(track)
        summaries = []
        for track in tracks:
            if isinstance(track, DrumTrack):
                kind, profile = "drum", "drum"
                gate, voicing, octave, density = 0.0, "", 0, 1.0
                density_applicable = False
            elif isinstance(track, MelodicTrack):
                kind, profile = "melodic", track.profile_name
                gate = track.gate
                voicing = track.voicing
                octave = track.octave
                density = track.density
                density_applicable = track.profile.pattern.family in (
                    FAMILY_CHORD_SLICER,
                    FAMILY_FREE_MONO,
                )
            else:
                continue  # неизвестный наследник Track — пропускаем
            summaries.append(
                TrackSummary(
                    name=track.name,
                    kind=kind,
                    profile=profile,
                    sources=tuple(track.sources),
                    mutation_count=int(track.mutation_count),
                    frozen=bool(track.mutate == 0.0),
                    port=track.port,
                    gate=float(gate),
                    voicing=voicing,
                    octave=int(octave),
                    mutate=float(track.mutate),
                    density=float(density),
                    density_applicable=density_applicable,
                    channel=int(track.channel),
                    color_slot=track.color_slot,
                )
            )
        return tuple(summaries)

    def _port_summaries(self) -> tuple[PortSummary, ...]:
        """Сводки сконфигурированных портов."""
        if not self._port_manager:
            return ()
        summaries = []
        for state in self._port_manager.all_states():
            detail = state.error or state.resolved_name or f"match: {state.match}"
            summaries.append(
                PortSummary(
                    name=state.label,
                    status=state.status.name.lower(),
                    detail=detail,
                )
            )
        return tuple(summaries)

    # ------------------------------------------------------------------
    # Read-only properties for AppEngineControl (F1)
    # ------------------------------------------------------------------

    @property
    def clock_manager(self) -> ClockManager | None:
        """ClockManager (read-only)."""
        return self._clock_manager

    @property
    def tick_proxy(self) -> TickProxy | None:
        """TickProxy (read-only)."""
        return self._tick_proxy

    @property
    def port_manager(self) -> PortManager | None:
        """PortManager (read-only)."""
        return self._port_manager

    @property
    def port_registry(self) -> PortRegistry | None:
        """PortRegistry (read-only)."""
        return self._port_registry

    @property
    def session(self) -> Session | None:
        """Session (read-only)."""
        return self._session

    @property
    def harmony(self) -> Harmony | None:
        """Harmony (read-only)."""
        return self._harmony

    @property
    def transport(self) -> Transport | None:
        """Transport (read-only)."""
        return self._transport

    @property
    def swing_amount(self) -> float:
        """Текущая величина свинга (0.0 без SwingApplier)."""
        return self._swing_applier.amount if self._swing_applier else 0.0

    @property
    def swing_applier(self) -> SwingApplier | None:
        """SwingApplier (read-only) — рантайм-сеттер свинга."""
        return self._swing_applier

    @property
    def status_snapshot(self) -> StatusSnapshot:
        """Последний снапшот состояния (собран в main loop)."""
        return self._status_snapshot

    def set_sync_bpm(self, value: float) -> None:
        """Установить BPM рантайма (тот же механизм, что у энкодера).

        Валидирует диапазон 20..300, обновляет ``_sync_bpm`` и делает
        best-effort обновление темпа активного internal-клока.
        """
        if not 20.0 <= value <= 300.0:
            raise ValueError(f"BPM out of range 20..300: {value}")
        self._sync_bpm = value
        cm = self._clock_manager
        if (
            cm is not None
            and cm.state.running
            and cm.current_source is ClockSource.INTERNAL
        ):
            timeline = getattr(cm, "_timeline", None)
            clock_src = getattr(cm, "_clock_source", None)
            with contextlib.suppress(Exception):
                if timeline is not None:
                    timeline.tempo = value
                if clock_src is not None and hasattr(clock_src, "tempo"):
                    clock_src.tempo = value
        log.info("App: sync bpm -> %.1f", value)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _atexit_cleanup(self) -> None:
        """Cleanup handler called by atexit on abnormal termination."""
        if self._running:
            log.warning("atexit: application still running, forcing cleanup")
            self._running = False
            self._cleanup()

    def stop(self) -> None:
        """Signal a clean shutdown."""
        log.info("App.stop() called")
        self._running = False

    def _cleanup(self) -> None:
        """Tear down all subsystems."""
        # F1: остановить REPL-поток первым — чтобы он не дёргал движок
        # во время разборки остальных подсистем.
        if self._repl is not None:
            self._repl.stop()
            self._repl = None
        if self._repl_thread is not None:
            self._repl_thread.join(timeout=1.0)
            self._repl_thread = None
        if self._transport:
            self._transport.all_notes_off()
        if self._clock_manager:
            self._clock_manager.stop()
        if self._tick_proxy:
            self._tick_proxy.stop_worker()
        if self._port_registry:
            self._port_registry.stop()
        if self._port_manager:
            self._port_manager.stop()
        if self._device_manager:
            self._device_manager.disconnect_all()
        with contextlib.suppress(Exception):
            atexit.unregister(self._atexit_cleanup)
