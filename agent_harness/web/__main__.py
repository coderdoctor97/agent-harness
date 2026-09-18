"""``python -m agent_harness.web`` — start the local UI.

Kept as a thin argparse front end over :func:`agent_harness.web.server.launch`
so the same entry point serves ``start.bat``, a developer's terminal and an IDE
run configuration, with identical flags.

Example:
    $ python -m agent_harness.web --port 8765
    $ python -m agent_harness.web --no-browser --host 0.0.0.0
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from typing import Any

from agent_harness.web.server import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    WebDependencyError,
    launch,
)

#: Same variable the CLI honours for the config path (SPEC-006 § 1).
ENV_CONFIG_PATH = "AGENT_HARNESS_CONFIG"

EXIT_OK = 0
EXIT_FAILED = 1


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns:
        A fresh parser (never shared, so tests cannot leak state between runs).
    """
    parser = argparse.ArgumentParser(
        prog="python -m agent_harness.web",
        description="Start the Agent Harness local web UI on localhost.",
    )
    parser.add_argument(
        "--host",
        default=None,
        help=f"interface to bind (default: {DEFAULT_HOST}, or web.host from config)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"port to bind (default: {DEFAULT_PORT}, or web.port from config)",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="path to config.yaml (default: ./config.yaml or AGENT_HARNESS_CONFIG)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open the default browser automatically",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="uvicorn log level (default: info)",
    )
    return parser


def load_config(path: str | None) -> Any:
    """Load the harness config the same way the CLI does.

    Args:
        path: an explicit ``--config`` path, or ``None``.

    Returns:
        A :class:`agent_harness.config.schema.Config`. A missing *default* path
        falls back to documented defaults; an explicit path that does not exist
        is an error the caller surfaces (matching ``agent_harness.__main__``).
    """
    config_module = importlib.import_module("agent_harness.config")
    explicit = path or os.environ.get(ENV_CONFIG_PATH) or None
    if explicit:
        return config_module.Config.from_file(explicit)
    if os.path.exists("./config.yaml"):
        return config_module.Config.from_file("./config.yaml")
    return config_module.Config()


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the server until interrupted.

    Args:
        argv: argument list; ``sys.argv[1:]`` by default.

    Returns:
        The process exit code: 0 on a clean stop, 130 on Ctrl+C, 1 on an error
        the user can act on (a missing extra, an unreadable config).
    """
    args = build_parser().parse_args(argv)

    try:
        config = load_config(args.config)
    except Exception as exc:  # noqa: BLE001 - surfaced as one actionable line
        code = getattr(exc, "code", type(exc).__name__)
        message = getattr(exc, "message", str(exc))
        print(f"[ERROR] {code}: {message}", file=sys.stderr)
        return EXIT_FAILED

    try:
        return launch(
            config=config,
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser,
            log_level=args.log_level,
        )
    except WebDependencyError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess
    raise SystemExit(main())
