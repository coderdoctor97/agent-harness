"""Local web server for the agent harness UI (PRD G8).

Kept separate from :mod:`agent_harness.web.app` so the ASGI app can be imported
and tested without uvicorn, and so the launcher — the piece ``start.bat`` and
``python -m agent_harness.web`` both call — owns port selection, the browser-open
handshake and shutdown, in one place.

Spec: SPEC-006 § 1 (config is the source of truth for host/port) · PRD G8
"""

from __future__ import annotations

import contextlib
import importlib
import os
import socket
import threading
import time
import webbrowser
from collections.abc import Callable
from typing import Any

#: The UI's default port. Chosen above the usual 3000/5173 front-end defaults and
#: below 10000 so it does not collide with the OS ephemeral range.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

#: Environment overrides. SPEC-006 § 1 freezes the config *sections*, and a
#: ``web:`` block would be rejected by the loader as an unknown section
#: (``CONFIG_VALIDATION_FAILED``), so the UI takes its settings from the
#: environment until the spec gains a section (SCR-P6-1). Precedence is the same
#: as everywhere else in this project: flag > env > config > default.
ENV_HOST = "AGENT_HARNESS_WEB_HOST"
ENV_PORT = "AGENT_HARNESS_WEB_PORT"
ENV_NO_BROWSER = "AGENT_HARNESS_WEB_NO_BROWSER"

#: How long the launcher waits for the socket to accept before opening the
#: browser. The wait is on the *socket*, not on the app's first request, so a
#: slow first compile cannot produce a blank tab.
READY_TIMEOUT_SECONDS = 15.0


class WebDependencyError(RuntimeError):
    """Raised when the optional web dependencies are not installed.

    Carries user-facing remediation: the CLI turns this into one actionable line
    rather than a traceback (SPEC-005 § 4's spirit, applied to optional extras).
    """


def web_dependencies_available() -> bool:
    """Whether FastAPI and uvicorn can be imported.

    Returns:
        ``True`` when ``pip install 'agent-harness[web]'`` has been run.
    """
    for module in ("fastapi", "uvicorn", "pydantic"):
        try:
            importlib.import_module(module)
        except ImportError:
            return False
    return True


def require_web_dependencies() -> None:
    """Raise :class:`WebDependencyError` unless the optional extras are present."""
    missing: list[str] = []
    for module, package in (
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn"),
        ("pydantic", "pydantic"),
    ):
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(package)
    if missing:
        raise WebDependencyError(
            "web UI dependencies are not installed (missing: "
            + ", ".join(missing)
            + '). Install them with: pip install "agent-harness[web]"'
        )


def port_in_use(host: str, port: int) -> bool:
    """Whether ``host:port`` is already bound.

    Args:
        host: interface to probe.
        port: port to probe.

    Returns:
        ``True`` when the address is taken, so the caller can pick the next one.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return True
    return False


def pick_port(host: str, preferred: int, *, attempts: int = 20) -> int:
    """Return ``preferred`` if free, else the first free port above it.

    Args:
        host: interface to probe.
        preferred: the port the user (or config) asked for.
        attempts: how many consecutive ports to try before giving up.

    Returns:
        A free port number.

    Raises:
        WebDependencyError: when every candidate is taken.
    """
    for offset in range(attempts):
        candidate = preferred + offset
        if not port_in_use(host, candidate):
            return candidate
    raise WebDependencyError(
        f"no free port in {preferred}-{preferred + attempts - 1} on {host}"
    )


def wait_until_ready(
    host: str,
    port: int,
    *,
    timeout: float = READY_TIMEOUT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Block until ``host:port`` accepts a TCP connection.

    Args:
        host: interface the server binds.
        port: port the server binds.
        timeout: maximum seconds to wait.
        sleep: injectable sleep, so tests do not really wait.

    Returns:
        ``True`` when the socket answered, ``False`` on timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.25)
            if probe.connect_ex((host, port)) == 0:
                return True
        sleep(0.05)
    return False


def open_browser_when_ready(
    url: str,
    host: str,
    port: int,
    *,
    timeout: float = READY_TIMEOUT_SECONDS,
    opener: Callable[[str], Any] = webbrowser.open,
) -> threading.Thread:
    """Open the UI in the default browser as soon as the server accepts.

    Runs on a daemon thread so the server start path never blocks on browser
    startup, and so a machine with no browser (a container, a headless VM) is
    unaffected: a failed open is simply ignored.

    Args:
        url: the URL to open.
        host: interface the server binds.
        port: port the server binds.
        timeout: maximum seconds to wait for the socket.
        opener: injectable browser opener (defaults to :func:`webbrowser.open`).

    Returns:
        The started thread, so a caller (or a test) may join it.
    """

    def target() -> None:
        if not wait_until_ready(host, port, timeout=timeout):
            return
        with contextlib.suppress(Exception):
            opener(url)

    thread = threading.Thread(target=target, name="web-ui-browser", daemon=True)
    thread.start()
    return thread


def launch(
    *,
    config: Any = None,
    host: str | None = None,
    port: int | None = None,
    open_browser: bool = True,
    log_level: str = "info",
) -> int:
    """Run the web UI until interrupted, and return the process exit code.

    Args:
        config: a :class:`agent_harness.config.schema.Config`; loaded from the
            usual sources when omitted (flag > ``AGENT_HARNESS_CONFIG`` > file).
        host: interface to bind; config ``web.host`` when omitted, else
            :data:`DEFAULT_HOST`.
        port: port to bind; config ``web.port`` when omitted, else
            :data:`DEFAULT_PORT`.
        open_browser: whether to open the default browser once listening.
        log_level: uvicorn log level.

    Returns:
        ``0`` on a clean shutdown, ``130`` when the user interrupts it (the same
        convention the CLI uses, SPEC-005 § 2.1 row 5).

    Raises:
        WebDependencyError: when the optional web extras are not installed.
    """
    require_web_dependencies()
    uvicorn = importlib.import_module("uvicorn")
    app_module = importlib.import_module("agent_harness.web.app")

    resolved_host = (
        host
        or os.environ.get(ENV_HOST)
        or _config_value(config, "web.host", DEFAULT_HOST)
    )
    preferred_port = int(
        port
        or os.environ.get(ENV_PORT)
        or _config_value(config, "web.port", DEFAULT_PORT)
    )
    resolved_port = pick_port(str(resolved_host), preferred_port)
    open_browser = open_browser and not _env_flag(ENV_NO_BROWSER)

    application = app_module.create_app(config=config)
    url = f"http://{_display_host(str(resolved_host))}:{resolved_port}/"
    _announce(url, preferred_port, resolved_port, open_browser)

    if open_browser:
        open_browser_when_ready(url, str(resolved_host), resolved_port)

    try:
        uvicorn.run(
            application,
            host=str(resolved_host),
            port=resolved_port,
            log_level=log_level,
            access_log=False,
        )
    except KeyboardInterrupt:  # pragma: no cover - depends on a real TTY
        return 130
    return 0


def _announce(url: str, preferred: int, actual: int, open_browser: bool) -> None:
    """Print the startup banner to stdout (never the web log stream)."""
    lines = ["", "  Agent Harness — local web UI", f"  {url}"]
    if actual != preferred:
        lines.append(f"  (port {preferred} was busy; using {actual})")
    lines.append(
        "  Browser opening automatically." if open_browser else "  Open the URL above."
    )
    lines.append("  Press Ctrl+C to stop.")
    lines.append("")
    print("\n".join(lines), flush=True)  # noqa: T201 - this is the CLI surface


def _display_host(host: str) -> str:
    """Render a bind address as something a browser can be pointed at."""
    return "localhost" if host in {"0.0.0.0", "::", ""} else host


def _config_value(config: Any, dotted: str, default: Any) -> Any:
    """Read a dotted config path defensively, falling back to a default.

    ``web.*`` is an addition this package introduces (see the ADR in
    ``documentations/``): an older config file simply has no such section, and
    that must never be an error.
    """
    if config is None:
        config = _load_default_config()
    getter = getattr(config, "get", None)
    if callable(getter):
        try:
            value = getter(dotted)
        except Exception:  # noqa: BLE001 - an unknown path is not a failure here
            value = None
        if value is not None:
            return value
    section, _, key = dotted.partition(".")
    holder = getattr(config, section, None)
    return getattr(holder, key, default) if holder is not None else default


#: Values that mean "yes" for the boolean environment switches.
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _env_flag(name: str) -> bool:
    """Whether a boolean environment switch is set to a true value."""
    return os.environ.get(name, "").strip().lower() in _TRUE_VALUES


def _load_default_config() -> Any:
    """Load the config the same way the CLI does, without importing it eagerly."""
    try:
        config_module = importlib.import_module("agent_harness.config")
        return config_module.Config()
    except Exception:  # noqa: BLE001 - the caller falls back to defaults
        return None
