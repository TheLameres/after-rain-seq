"""Entry point for after-rain-seq.

Parses CLI arguments, sets up logging, runs headless.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.app.application import App

from src.config import ensure_default_config, load_config
from src.logging_config import VALID_LEVELS, apply_logging_config, attach_log_buffer


def main() -> None:
    parser = argparse.ArgumentParser(
        description="after-rain-seq: Generative MIDI host for Ambient Dub Techno"
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Run with hardware simulator (no hardware required)",
    )
    parser.add_argument(
        "--list-ports",
        action="store_true",
        help="List available MIDI ports and exit",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        metavar="FILE",
        help="Path to config file (default: config.yaml)",
    )
    parser.add_argument(
        "--repl",
        action="store_true",
        help="Start interactive REPL for monitoring and control (needs a TTY)",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=VALID_LEVELS,
        help="Root logging level (default: from config.yaml, or INFO)",
    )
    parser.add_argument(
        "--log-layer",
        action="append",
        default=[],
        metavar="NAME=LEVEL",
        help="Spring Boot-style: --log-layer src.midi=DEBUG (repeatable)",
    )
    args = parser.parse_args()

    # Create default config if absent, then load it
    ensure_default_config(args.config)
    cfg = load_config(args.config)

    # Merge config levels with CLI overrides
    levels = dict(cfg.logging.level)
    if args.log_level is not None:
        levels["root"] = args.log_level
    for override in args.log_layer:
        if "=" not in override:
            print(
                f"Invalid --log-layer: '{override}' (expected NAME=LEVEL)",
                file=sys.stderr,
            )
            sys.exit(1)
        name, level = override.split("=", 1)
        levels[name.strip()] = level.strip()

    root_level = levels.pop("root", "INFO")
    apply_logging_config(root_level, levels)

    if args.list_ports:
        import mido

        print("MIDI input ports:")
        for name in mido.get_input_names():
            print(f"  {name}")
        print("MIDI output ports:")
        for name in mido.get_output_names():
            print(f"  {name}")
        sys.exit(0)

    _run_headless(args.config, args.simulate, repl=args.repl)


def _run_headless(config_path: str, simulate: bool, repl: bool = False) -> None:
    import signal

    from src.app.application import App

    log = logging.getLogger(__name__)
    app = App(config_path=config_path, simulate=simulate)

    def _shutdown(signum, frame):
        log.info("Signal %d received, shutting down", signum)
        app.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    log.info(
        "after-rain-seq headless mode (config=%s, simulate=%s)", config_path, simulate
    )
    app.run(repl=_build_repl(app, config_path) if repl else None)  # blocks until stop()


def _build_repl(app: App, config_path: str):
    """Собрать Repl с AppEngineControl и LogBuffer (флаг --repl)."""
    from src.app.engine_control import AppEngineControl
    from src.harmony.voicings import Voicing
    from src.repl.history_store import history_path_for
    from src.repl.log_buffer import LogBuffer
    from src.repl.repl import Repl
    from src.session.model.melodic_profile import PROFILES

    log_buffer = LogBuffer()
    attach_log_buffer(log_buffer)
    control = AppEngineControl(app, log_buffer=log_buffer)

    return Repl(
        control,
        history_path=history_path_for(config_path),
        on_eof=app.stop,
        dynamic_providers={
            "profile": lambda: sorted(PROFILES),
            "scale": lambda: sorted(Voicing.HARMONIC_SCALES),
        },
    )


if __name__ == "__main__":
    main()
