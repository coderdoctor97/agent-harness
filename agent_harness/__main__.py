"""Command line entry point: ``python -m agent_harness``.

This module owns the *interface* only — parsing, precedence, rendering and exit
codes. All behaviour lives in :class:`agent_harness.AgentHarness`; the CLI is a
thin shell around it, so everything here is testable without an LLM.

Spec: SPEC-005 § 2 (FROZEN CLI contract, flag table, exit codes, rendering) ·
SPEC-006 § 1.2 (precedence CLI > env > file > defaults)
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only; real modules arrive at I1
    from agent_harness.config import Config

#: Exit codes, FROZEN by SPEC-005 § 2.1.
EXIT_OK = 0  # completed, or --dry-run / --list-tools succeeded
EXIT_FAILED = 1  # failed result, or an unhandled AgentError
EXIT_USAGE = 2  # CLI usage error (argparse's own code)
EXIT_PARTIAL = 3  # partial result
EXIT_INTERRUPTED = 130  # SIGINT

#: SPEC-005 § 2 — the four levels the contract allows.
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

#: Environment variables the CLI consults. Both sit *below* a command line flag
#: and *above* the config file (SPEC-006 § 1.2).
ENV_CONFIG_PATH = "AGENT_HARNESS_CONFIG"
ENV_LOG_LEVEL = "AGENT_HARNESS_LOG_LEVEL"

#: Default config path, per SPEC-005 § 2.
DEFAULT_CONFIG_PATH = "./config.yaml"

#: The usage line SPEC-005 § 2 freezes. Compared whitespace-normalised, because
#: argparse re-wraps it to the terminal width.
USAGE = """\
usage: python -m agent_harness [-h] [--config PATH] [--output-dir DIR]
                               [--log-level LEVEL] [--dry-run] [--list-tools]
                               [--max-steps N] [--no-fallback]
                               [prompt]"""

#: Dotted config paths each flag writes to. Kept as data so the mapping the plan
#: asks for is inspectable and testable in one place.
OVERRIDE_PATHS = {
    "output_dir": "execution.output_dir",
    "max_steps": "execution.max_steps",
    "log_level": "logging.level",
}


def _positive_int(value: str) -> int:
    """Argparse ``type`` enforcing SPEC-005 § 2's "positive int".

    Args:
        value: the raw command line token.

    Returns:
        The parsed integer.

    Raises:
        argparse.ArgumentTypeError: when the token is not a positive integer.
            Argparse turns that into a usage error with exit code 2.
    """
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a positive integer, got {value!r}"
        ) from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {number}")
    return number


def _log_level(value: str) -> str:
    """Argparse ``type`` for ``--log-level``.

    Accepts any case and returns the upper-case name the config uses. A custom
    type rather than ``choices`` so that ``--log-level debug`` works while the
    stored value stays canonical.

    Args:
        value: the raw command line token.

    Returns:
        One of :data:`LOG_LEVELS`.

    Raises:
        argparse.ArgumentTypeError: for anything else.
    """
    level = value.strip().upper()
    if level not in LOG_LEVELS:
        raise argparse.ArgumentTypeError(
            f"expected one of {', '.join(LOG_LEVELS)}, got {value!r}"
        )
    return level


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser exactly as SPEC-005 § 2 specifies.

    A fresh parser per call, so no state leaks between invocations in the same
    process (the test suite calls this many times).

    Returns:
        The configured :class:`argparse.ArgumentParser`.
    """
    parser = argparse.ArgumentParser(
        prog="python -m agent_harness",
        description="Run a task through the agent harness.",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help=(
            f"config file (default {DEFAULT_CONFIG_PATH}, then the "
            f"{ENV_CONFIG_PATH} environment variable)"
        ),
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        default=None,
        help="overrides execution.output_dir",
    )
    parser.add_argument(
        "--log-level",
        metavar="LEVEL",
        type=_log_level,
        default=None,
        help=f"one of {', '.join(LOG_LEVELS)}; overrides config and {ENV_LOG_LEVEL}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan and exit without executing",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="print the tool registry and exit; no prompt needed",
    )
    parser.add_argument(
        "--max-steps",
        metavar="N",
        type=_positive_int,
        default=None,
        help="overrides execution.max_steps (positive integer)",
    )
    parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="set execution.enable_replan=false and strip fallback tools",
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        default=None,
        help="the task to run; '-' reads it from stdin",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse a command line, applying the one cross-flag rule the spec states.

    ``prompt`` is required unless ``--list-tools`` is given; everything else is
    argparse's own validation. Any failure exits with code 2.

    Args:
        argv: arguments to parse; ``None`` means ``sys.argv[1:]``.

    Returns:
        The parsed namespace.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.prompt is None and not args.list_tools:
        parser.error("a prompt is required unless --list-tools is given")
    return args


def read_prompt(args: argparse.Namespace) -> str | None:
    """Resolve the task text, honouring ``-`` as "read stdin".

    Args:
        args: a namespace from :func:`parse_args`.

    Returns:
        The stripped prompt, or ``None`` when there is no prompt to read
        (``--list-tools``).

    Raises:
        SystemExit: code 2 when ``-`` is given but stdin is empty, because an
            empty task is a usage mistake rather than something to run.
    """
    if args.prompt is None:
        return None
    if args.prompt != "-":
        prompt: str = args.prompt  # typed local: Namespace attributes are Any
        return prompt
    text = sys.stdin.read().strip()
    if not text:
        build_parser().error("'-' was given but stdin was empty")
    return text


def resolve_config_path(args: argparse.Namespace) -> str:
    """Pick the config file: flag, then environment, then the default.

    Args:
        args: a namespace from :func:`parse_args`.

    Returns:
        The path to load. The file need not exist — SPEC-006 K5 requires the
        harness to work with defaults alone so ``--list-tools`` never needs
        configuration.
    """
    if args.config:
        config_path: str = args.config  # typed local: Namespace attributes are Any
        return config_path
    from_env = os.environ.get(ENV_CONFIG_PATH, "").strip()
    if from_env:
        return from_env
    return DEFAULT_CONFIG_PATH


def collect_overrides(args: argparse.Namespace) -> dict[str, Any]:
    """Turn the parsed flags into dotted config paths and values.

    Only flags the user actually passed appear, so an omitted flag can never
    overwrite what the config file said (SPEC-006 § 1.2 precedence).

    Args:
        args: a namespace from :func:`parse_args`.

    Returns:
        A mapping of dotted config path to value.
    """
    overrides: dict[str, Any] = {}
    for flag, dotted in OVERRIDE_PATHS.items():
        value = getattr(args, flag, None)
        if value is not None:
            overrides[dotted] = value
    if args.no_fallback:
        overrides["execution.enable_replan"] = False
    return overrides


def _env_log_level() -> str | None:
    """The ``AGENT_HARNESS_LOG_LEVEL`` value, if it is a valid level."""
    raw = os.environ.get(ENV_LOG_LEVEL, "").strip()
    return _log_level(raw) if raw.upper() in LOG_LEVELS else None


def _assign_dotted(config: Any, dotted: str, value: Any) -> None:
    """Set ``a.b.c`` on a typed config that has no ``apply_overrides``.

    Args:
        config: the config object.
        dotted: a path such as ``execution.max_steps``.
        value: the value to store.
    """
    section_name, _, attribute = dotted.rpartition(".")
    section = getattr(config, section_name)
    setattr(section, attribute, value)


def apply_cli_overrides(config: Config, args: argparse.Namespace) -> Config:
    """Apply command line flags (and the log-level env var) to a config.

    Uses ``config.apply_overrides`` when Plan 1 provides it — the seam plan 4.1
    names — and falls back to direct typed-attribute assignment otherwise,
    because the FROZEN ``Config`` surface in SPEC-006 § 1.1 does not declare
    ``apply_overrides`` (SCR-P4-9). Either way the same dotted paths are written.

    ``AGENT_HARNESS_LOG_LEVEL`` is applied here too, and only when no
    ``--log-level`` flag was given, so the precedence stays CLI > env > file.

    Args:
        config: the config to modify, in place.
        args: a namespace from :func:`parse_args`.

    Returns:
        The same config object, for chaining.
    """
    overrides = collect_overrides(args)
    env_level = _env_log_level()
    if env_level is not None:
        overrides.setdefault("logging.level", env_level)
    if not overrides:
        return config

    apply = getattr(config, "apply_overrides", None)
    if callable(apply):
        apply(overrides)
        return config
    for dotted, value in overrides.items():
        _assign_dotted(config, dotted, value)
    return config


# ---------------------------------------------------------------------------
# Sub-phase 4.2 — dispatch and exit codes
# ---------------------------------------------------------------------------

#: Maps a terminal :class:`HarnessResult` status onto SPEC-005 § 2.1's exit code.
STATUS_EXIT_CODES = {
    "completed": EXIT_OK,
    "partial": EXIT_PARTIAL,
    "failed": EXIT_FAILED,
}


def _agent_error_type() -> Any:
    """Plan 1's ``AgentError``, resolved lazily so this module imports cheaply."""
    return importlib.import_module("agent_harness.config.schema").AgentError


def _error_code(exc: BaseException) -> str:
    """The ``code`` on an ``AgentError``, or the exception class name."""
    code = getattr(exc, "code", None)
    return str(code) if code else type(exc).__name__


def _load_config(args: argparse.Namespace) -> Config:
    """Load and override the configuration.

    Args:
        args: a namespace from :func:`parse_args`.

    Returns:
        A config with CLI and environment overrides applied.

    Raises:
        AgentError: when the file cannot be loaded. The caller turns that into
            exit code 1, per SPEC-005 § 2.1.
    """
    config_module = importlib.import_module("agent_harness.config")
    config = config_module.Config.from_file(resolve_config_path(args))
    return apply_cli_overrides(config, args)


def _default_harness_factory(config: Config) -> Any:
    """Build the real harness. Swapped out by tests via ``harness_factory``."""
    from agent_harness import AgentHarness

    return AgentHarness(config)


def use_rich(stream: Any = None) -> bool:
    """Decide whether console output should be styled (SPEC-005 § 2.2).

    Rich is used only when all four hold: the ``rich`` package is importable,
    the stream is a terminal, ``NO_COLOR`` is not set to a non-empty value, and
    ``TERM`` is not ``dumb``. Anything else degrades to plain text, so piped
    output stays greppable and a missing optional dependency never crashes.

    Args:
        stream: the destination to inspect; ``sys.stdout`` by default.

    Returns:
        ``True`` when styled output is appropriate.
    """
    target = sys.stdout if stream is None else stream
    if os.environ.get("NO_COLOR", ""):
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    try:
        isatty = target.isatty
    except AttributeError:
        return False
    if not isatty():
        return False
    try:
        importlib.import_module("rich")
    except ImportError:
        return False
    return True


def _rich_string(renderable: Any, width: int = 100) -> str:
    """Render a rich object to a styled string.

    ``force_terminal`` is deliberate: the caller has already decided that the
    destination is a terminal, and this console writes to a buffer rather than
    to the real stream, so it would otherwise strip the styling.

    Args:
        renderable: any rich renderable.
        width: fixed column width, so output does not depend on the terminal.

    Returns:
        The rendered text, including ANSI escape codes.
    """
    import io

    from rich.console import Console

    buffer = io.StringIO()
    console = Console(file=buffer, force_terminal=True, width=width, record=True)
    console.print(renderable)
    return console.export_text(styles=True)


def _rich_tools_table(tools: Sequence[dict[str, Any]]) -> str:
    """The registry as a rich table."""
    from rich.table import Table

    table = Table(title=f"Tools ({len(tools)})", title_style="bold")
    table.add_column("NAME", style="cyan", no_wrap=True)
    table.add_column("CAPABILITIES", style="magenta")
    table.add_column("DESCRIPTION")
    for row in tools:
        table.add_row(
            str(row.get("name", "")),
            ", ".join(row.get("capabilities", [])),
            str(row.get("description", "")),
        )
    return _rich_string(table)


def _rich_plan_table(plan: Any) -> str:
    """The plan as a rich table: id, description, tool, priority, dependencies."""
    from rich.table import Table

    steps = list(getattr(plan, "steps", []))
    table = Table(title=f"Plan ({len(steps)} steps)", title_style="bold")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("TOOL", style="green")
    table.add_column("PRIORITY", style="yellow")
    table.add_column("DEPENDS ON")
    table.add_column("DESCRIPTION")
    for step in steps:
        table.add_row(
            str(step.id),
            str(step.tool_name),
            _priority_name(step.priority),
            ", ".join(getattr(step, "depends_on", []) or []) or "-",
            str(step.description),
        )
    return _rich_string(table)


def _rich_result_panel(result: Any) -> str:
    """The final output inside a panel titled with the run status."""
    from rich.panel import Panel
    from rich.text import Text

    output = getattr(result, "final_output", None)
    if output is None:
        body = ""
    elif isinstance(output, str):
        body = output
    else:
        body = str(output)
    style = {
        "completed": "green",
        "partial": "yellow",
        "failed": "red",
    }.get(str(result.status), "white")
    return _rich_string(
        Panel(
            Text(body or "(no output)"),
            title=f"Status: {result.status}",
            border_style=style,
        )
    )


def _render_tools(tools: Sequence[dict[str, Any]], *, rich: bool = False) -> str:
    """Registry table: name, capabilities, description.

    Args:
        tools: rows from :meth:`AgentHarness.list_tools`.
        rich: render as a styled rich table rather than plain text.

    Returns:
        The rendered table.
    """
    if rich and tools:
        return _rich_tools_table(tools)
    if not tools:
        return "No tools registered.\n"
    name_width = max(len(str(row.get("name", ""))) for row in tools)
    name_width = max(name_width, len("NAME"))
    cap_width = max(
        [len(", ".join(row.get("capabilities", []))) for row in tools]
        + [len("CAPABILITIES")]
    )
    lines = [f"Tools ({len(tools)})", ""]
    lines.append(
        f"  {'NAME'.ljust(name_width)}  {'CAPABILITIES'.ljust(cap_width)}  DESCRIPTION"
    )
    for row in tools:
        lines.append(
            f"  {str(row.get('name', '')).ljust(name_width)}  "
            f"{', '.join(row.get('capabilities', [])).ljust(cap_width)}  "
            f"{row.get('description', '')}"
        )
    return "\n".join(lines) + "\n"


def _render_plugin_errors(errors: Sequence[Any]) -> str:
    """SPEC-005 § 3 step 6 — the ``--list-tools`` footer for failed plugins."""
    if not errors:
        return ""
    lines = ["", f"{len(errors)} plugin(s) failed to load:"]
    lines.extend(f"  - [{_error_code(e)}] {e.message}" for e in errors)
    return "\n".join(lines) + "\n"


def _priority_name(priority: Any) -> str:
    """Render an enum priority as its name, or fall back to ``str``."""
    name = getattr(priority, "name", None)
    return str(name) if name else str(priority)


def _render_plan(plan: Any, *, rich: bool = False) -> str:
    """Plan table: id, description, tool, priority, dependencies.

    Args:
        plan: the plan to render.
        rich: render as a styled rich table rather than plain text.

    Returns:
        The rendered table.
    """
    steps = list(getattr(plan, "steps", []))
    if rich and steps:
        return _rich_plan_table(plan)
    if not steps:
        return "Plan has no steps.\n"
    lines = [f"Plan ({len(steps)} steps)", ""]
    lines.append("  ID        TOOL          PRIORITY  DEPENDS ON   DESCRIPTION")
    for step in steps:
        depends = ", ".join(getattr(step, "depends_on", []) or []) or "-"
        lines.append(
            f"  {str(step.id).ljust(8)}  {str(step.tool_name).ljust(12)}  "
            f"{_priority_name(step.priority).ljust(8)}  {depends.ljust(11)}  "
            f"{step.description}"
        )
    return "\n".join(lines) + "\n"


def _render_result(result: Any, *, rich: bool = False) -> str:
    """The final output, plus a status line when there is no output to show.

    Args:
        result: the :class:`HarnessResult` to render.
        rich: render as a styled panel rather than plain text.

    Returns:
        The rendered result.
    """
    if rich:
        return _rich_result_panel(result)
    parts: list[str] = []
    output = getattr(result, "final_output", None)
    if isinstance(output, str) and output:
        parts.append(output)
    elif output is not None:
        parts.append(str(output))
    errors = list(getattr(result, "errors", []) or [])
    if errors:
        parts.append("")
        parts.append(f"{len(errors)} error(s):")
        parts.extend(f"  - [{_error_code(e)}] {e.message}" for e in errors)
    parts.append("")
    parts.append(f"Status: {result.status}")
    return "\n".join(parts) + "\n"


#: Maps an orchestrator event name onto the line the console prints for it.
#: ``{}`` placeholders are filled from the event dict; unknown events print
#: nothing, so a future event cannot crash an older CLI.
PROGRESS_LINES = {
    "plan_start": "plan started",
    "step_start": "[{step_id}] starting",
    "step_complete": "[{step_id}] complete",
    "step_failed": "[{step_id}] failed: {error}",
    "recovery": "[{step_id}] recovery: {strategy}",
    "plan_complete": "plan complete: {status}",
}


def _progress_line(event: dict[str, Any]) -> str | None:
    """Format one progress event, or ``None`` when there is nothing to show."""
    template = PROGRESS_LINES.get(str(event.get("event", "")))
    if template is None:
        return None
    fields = {key: str(value) for key, value in event.items()}
    try:
        return template.format(**fields)
    except KeyError:
        return template


def _live_progress(stream: Any = None) -> Any:
    """Build the ``progress`` callback the harness calls on every step event.

    Progress output goes to **stderr**, so a piped ``stdout`` still carries only
    the deliverable. Writing is best effort: if the console has gone away the
    run must still finish, because losing a progress line is not a reason to
    discard completed work.

    Args:
        stream: destination; ``sys.stderr`` by default.

    Returns:
        A callback accepting one event dict.
    """

    def callback(event: dict[str, Any]) -> None:
        """Print one event, tolerating a vanished console."""
        line = _progress_line(event)
        if line is None:
            return
        target = sys.stderr if stream is None else stream
        try:
            target.write(f"{line}\n")
            target.flush()
        except OSError:
            pass  # best effort: a dead console must not abort the run

    return callback


def _execution_report(result: Any) -> str:
    """SPEC-006 § 7 — the execution report, rendered through ``render_report``.

    Args:
        result: the completed :class:`HarnessResult`.

    Returns:
        The report, or an empty string when there is nothing to report or the
        report module cannot render it. Never raises: a reporting failure must
        not turn a successful run into a failed exit code.
    """
    plan = getattr(result, "plan", None)
    metrics = getattr(result, "metrics", None)
    if plan is None or metrics is None:
        return ""
    try:
        report_module = importlib.import_module("agent_harness.logging.report")
        return str(report_module.render_report(plan, metrics, style="text"))
    except Exception:  # reporting is advisory; the result still stands
        return ""


def _cmd_list_tools(harness: Any, *, rich: bool = False) -> int:
    """Print the registry and any plugin failures. Needs no credentials."""
    sys.stdout.write(_render_tools(harness.list_tools(), rich=rich))
    footer = _render_plugin_errors(getattr(harness, "plugin_errors", []))
    if footer:
        sys.stdout.write(footer)
    return EXIT_OK


def _cmd_dry_run(harness: Any, prompt: str, *, rich: bool = False) -> int:
    """Print the plan without executing it."""
    sys.stdout.write(_render_plan(harness.plan(prompt), rich=rich))
    return EXIT_OK


def _cmd_run(harness: Any, prompt: str, *, rich: bool = False) -> int:
    """Run the task and map the terminal status onto an exit code."""
    result = harness.run(prompt)
    sys.stdout.write(_render_result(result, rich=rich))
    report = _execution_report(result)
    if report:
        sys.stdout.write("\n" + report.rstrip("\n") + "\n")
    return STATUS_EXIT_CODES.get(str(result.status), EXIT_FAILED)


def main(
    argv: Sequence[str] | None = None,
    *,
    harness_factory: Any = None,
) -> int:
    """CLI entry point.

    Args:
        argv: arguments to parse; ``None`` means ``sys.argv[1:]``.
        harness_factory: builds the harness from a config. Tests inject a double;
            the default builds a real :class:`agent_harness.AgentHarness`.

    Returns:
        The process exit code, per SPEC-005 § 2.1: 0 completed, 1 failed,
        2 usage error, 3 partial, 130 interrupted.
    """
    try:
        args = parse_args(argv)
        prompt = read_prompt(args)
    except SystemExit as exc:  # argparse already printed the message
        code = exc.code
        return code if isinstance(code, int) else EXIT_USAGE

    try:
        config = _load_config(args)
    except _agent_error_type() as exc:
        print(f"Error [{exc.code}]: {exc.message}", file=sys.stderr)
        return EXIT_FAILED

    factory = _default_harness_factory if harness_factory is None else harness_factory
    styled = use_rich(sys.stdout)
    harness: Any = None
    try:
        harness = factory(config)
        if args.list_tools:
            return _cmd_list_tools(harness, rich=styled)
        if args.dry_run:
            assert prompt is not None  # parse_args guarantees this
            return _cmd_dry_run(harness, prompt, rich=styled)
        assert prompt is not None  # parse_args guarantees this
        set_progress = getattr(harness, "set_progress", None)
        if callable(set_progress):
            set_progress(_live_progress())
        return _cmd_run(harness, prompt, rich=styled)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return EXIT_INTERRUPTED
    except _agent_error_type() as exc:
        print(f"Error [{exc.code}]: {exc.message}", file=sys.stderr)
        return EXIT_FAILED
    finally:
        if harness is not None:
            harness.close()


if __name__ == "__main__":  # pragma: no cover - exercised by the subprocess tests
    raise SystemExit(main())
