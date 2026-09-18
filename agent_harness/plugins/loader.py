"""Plugin discovery and loading (SPEC-005 § 3).

Trust boundary
--------------
Everything this module touches is **untrusted third-party code**. A plugin file is
executed in-process with the full privileges of the user running the harness, so the
loader's job is to make one bad plugin *loud but harmless*: it must never abort startup,
never silently swallow a failure, and never let a plugin take over a built-in name.
See ``plugins/README.md`` for the author-facing security notice.

Spec: SPEC-005 § 3 · SPEC-001 § 2.4 · SPEC-006 § 6.1 (``plugin_loaded`` /
``plugin_failed`` events)
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import sys
import types
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only; real modules arrive at I1
    from agent_harness.config import Config
    from agent_harness.config.schema import AgentError
    from agent_harness.llm.client import LLMClient
    from agent_harness.logging.logger import StructuredLogger
    from agent_harness.tools.base import BaseTool
    from agent_harness.tools.registry import ToolRegistry

#: Synthetic module-name prefix, per SPEC-005 § 3 step 2. Keeping plugin modules out of
#: the ``agent_harness`` namespace stops a plugin from shadowing a real submodule.
MODULE_PREFIX = "agent_harness_plugin_"

#: Error code for every plugin failure (SPEC-001 § 3): isolated, never fatal.
PLUGIN_LOAD_FAILED = "PLUGIN_LOAD_FAILED"


def _agent_error_type() -> Any:
    """Return Plan 1's ``AgentError`` type, resolved lazily."""
    schema_module = importlib.import_module("agent_harness.config.schema")
    return schema_module.AgentError


def _base_tool_type() -> Any:
    """Return Plan 2's ``BaseTool`` type, resolved lazily.

    The loader imports the base itself (SPEC-005 § 3 step 3) rather than taking
    it as an argument, so a plugin is judged against exactly the class the
    registry will accept.
    """
    return importlib.import_module("agent_harness.tools.base").BaseTool


def _make_error(message: str) -> AgentError:
    """Build a ``PLUGIN_LOAD_FAILED`` error.

    SPEC-005 § 3 step 6: recoverable is always ``False`` — a plugin that will not load
    will not load on retry, and the harness must carry on without it.
    """
    error_type = _agent_error_type()
    return error_type(
        code=PLUGIN_LOAD_FAILED,
        message=message,
        component="plugins",
        recoverable=False,
    )


def _resolve_logger(logger: StructuredLogger | None) -> Any:
    """Use the injected logger, or the no-config default (SPEC-006 § 6.2)."""
    if logger is not None:
        return logger
    logging_module = importlib.import_module("agent_harness.logging")
    return logging_module.StructuredLogger.default()


def _iter_plugin_files(
    plugin_dirs: Sequence[str], *, logger: StructuredLogger | None = None
) -> Iterator[Path]:
    """SPEC-005 § 3 steps 1-2 — enumerate candidate plugin files.

    Directories are visited in the order given; files *within* a directory are sorted,
    so discovery order does not depend on the filesystem. A directory that does not
    exist is skipped and logged at ``DEBUG`` — never an error, because the default
    config points at ``~/.agent_harness/plugins`` which most users never create.

    Files whose name starts with ``_`` (``__init__.py``, ``_helpers.py``) are not
    plugins and are skipped.

    Args:
        plugin_dirs: directories to scan.
        logger: optional structured logger.

    Yields:
        Plugin file paths, in deterministic order.
    """
    log = _resolve_logger(logger)
    for raw_dir in plugin_dirs:
        directory = Path(raw_dir).expanduser()
        if not directory.is_dir():
            log.debug("plugins", "plugin_dir_skipped", path=str(directory))
            continue
        for candidate in sorted(directory.glob("*.py")):
            if candidate.name.startswith("_"):
                continue
            yield candidate


#: Constructor parameters the loader knows how to inject (SPEC-005 § 3 step 4).
#: Anything else a plugin needs must come from its own ``PLUGIN_SETTINGS``.
INJECTABLE_PARAMS = ("config", "llm_client")

#: Parameter kinds the loader is able to fill by keyword. ``*args`` and
#: ``**kwargs`` constructors are simply called with whatever we can supply.
FILLABLE_KINDS = frozenset(
    {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
)


def _find_tool_classes(module: types.ModuleType, base_tool: type) -> list[type]:
    """SPEC-005 § 3 step 3 — the tool classes a plugin module provides.

    Keep every class that subclasses the tool base, drop the base class itself,
    and drop anything still abstract: a plugin may legitimately ship a shared
    abstract helper alongside its concrete tools. Results are sorted by class
    name so discovery order never depends on ``getmembers`` ordering.

    Args:
        module: an executed plugin module.
        base_tool: Plan 2's ``BaseTool``, resolved by the caller.

    Returns:
        Concrete tool classes, ordered by name.
    """
    found: list[type] = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if obj is base_tool:
            continue
        try:
            is_tool = issubclass(obj, base_tool)
        except TypeError:  # an exotic metaclass that rejects issubclass
            continue
        if not is_tool or inspect.isabstract(obj):
            continue
        found.append(obj)
    return sorted(found, key=lambda candidate: candidate.__name__)


def _build_kwargs(
    plugin_class: type, config: object, llm_client: object
) -> dict[str, object] | AgentError | None:
    """SPEC-005 § 3 step 4 — work out how to call ``plugin_class.__init__``.

    Injection is by parameter *name*, in this order: ``config`` and
    ``llm_client`` receive the harness collaborators, any other name is looked
    up in the class's ``PLUGIN_SETTINGS`` mapping, and a defaulted parameter is
    simply left alone.

    Args:
        plugin_class: the candidate tool class.
        config: injected for a parameter named ``config``.
        llm_client: injected for a parameter named ``llm_client``.

    Returns:
        The keyword mapping; an ``AgentError`` when a required parameter has no
        source; or ``None`` when the signature could not be inspected, in which
        case a zero-argument construction is attempted.
    """
    settings = dict(getattr(plugin_class, "PLUGIN_SETTINGS", None) or {})
    try:
        # Signature of the constructor, ``self`` already excluded.
        parameters = inspect.signature(plugin_class).parameters
    except (TypeError, ValueError):
        return None
    kwargs: dict[str, object] = {}
    for name, parameter in parameters.items():
        if name == "self" or parameter.kind not in FILLABLE_KINDS:
            continue
        if name in INJECTABLE_PARAMS:
            kwargs[name] = config if name == "config" else llm_client
        elif name in settings:
            kwargs[name] = settings[name]
        elif parameter.default is inspect.Parameter.empty:
            return _make_error(
                f"plugin class {plugin_class.__name__!r} requires parameter "
                f"{name!r}: add it to the class's PLUGIN_SETTINGS, or name it "
                "'config' or 'llm_client' to have the harness inject it"
            )
    return kwargs


def _instantiate(
    plugin_class: type, config: object, llm_client: object
) -> BaseTool | AgentError:
    """Build one plugin class, converting every failure into an error record.

    The caller keeps scanning, so a plugin whose ``__init__`` raises costs its
    own tool and nothing else.
    """
    kwargs = _build_kwargs(plugin_class, config, llm_client)
    if isinstance(kwargs, _agent_error_type()):
        return kwargs
    try:
        return plugin_class(**(kwargs or {}))
    except Exception as exc:  # third-party constructor; not a bare except
        return _make_error(
            f"plugin class {plugin_class.__name__!r} failed to instantiate: {exc}"
        )


def _load_plugin_module(path: Path) -> types.ModuleType | AgentError:
    """SPEC-005 § 3 step 2 — execute one plugin file under a synthetic module name.

    Never raises: any failure (syntax error, import error, error at module scope) is
    converted to a :class:`AgentError` so a single bad file cannot abort startup. The
    half-built module is removed from ``sys.modules`` on failure so a later, fixed
    version can load cleanly.

    Args:
        path: the plugin file.

    Returns:
        The executed module, or an ``AgentError`` describing the failure.
    """
    module_name = f"{MODULE_PREFIX}{path.stem}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return _make_error(f"cannot build an import spec for plugin '{path.name}'")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    except Exception as exc:  # not a bare except: interrupts still propagate
        sys.modules.pop(module_name, None)
        return _make_error(f"failed to load plugin '{path.name}': {exc}")


def discover_tools(
    plugin_dirs: list[str],
    *,
    config: Config | None = None,
    llm_client: LLMClient | None = None,
    logger: StructuredLogger | None = None,
) -> tuple[list[BaseTool], list[AgentError]]:
    """SPEC-005 § 3 — discover plugin tools from a list of directories.

    Scanning is skipped entirely when ``config.plugins.auto_load`` is false.

    Args:
        plugin_dirs: directories to scan; ``~`` is expanded.
        config: harness configuration, used for ``plugins.auto_load`` and for
            injecting ``config`` into plugins that ask for it.
        llm_client: injected into plugins whose constructor accepts ``llm_client``.
        logger: optional structured logger.

    Returns:
        A ``(tools, errors)`` tuple. Errors are returned rather than raised: a plugin
        that fails to load is reported in the ``--list-tools`` footer and the startup
        log, and never aborts the harness.
    """
    log = _resolve_logger(logger)
    if config is not None and not config.plugins.auto_load:
        return [], []

    error_type = _agent_error_type()
    base_tool = _base_tool_type()
    tools: list[BaseTool] = []
    errors: list[AgentError] = []

    for path in _iter_plugin_files(plugin_dirs, logger=log):
        module = _load_plugin_module(path)
        if isinstance(module, error_type):
            errors.append(module)
            log.warning(
                "plugins", "plugin_failed", plugin=str(path), error=module.message
            )
            continue
        for plugin_class in _find_tool_classes(module, base_tool):
            outcome = _instantiate(plugin_class, config, llm_client)
            if isinstance(outcome, error_type):
                errors.append(outcome)
                log.warning(
                    "plugins", "plugin_failed", plugin=str(path), error=outcome.message
                )
                continue
            name = _safe_tool_name(outcome)
            if isinstance(name, error_type):
                # The instance built, but reading its name raised. It cannot be
                # registered or reported, so it is treated as a failed plugin.
                errors.append(name)
                log.warning(
                    "plugins", "plugin_failed", plugin=str(path), error=name.message
                )
                continue
            tools.append(outcome)
            log.debug(
                "plugins",
                "plugin_loaded",
                plugin=str(path),
                tool=name,
                module=module.__name__,
            )

    return tools, errors


def _safe_tool_name(tool: BaseTool) -> str | AgentError:
    """Read ``tool.name`` without trusting it to return.

    ``name`` is a property the plugin author wrote, so it may raise. Registration
    needs the name and the log line needs it too, so one guarded read serves both.
    """
    try:
        return str(tool.name)
    except Exception as exc:  # third-party property; not a bare except
        return _make_error(
            f"plugin tool of type {type(tool).__name__!r} raised from its name "
            f"property: {exc}"
        )


def register_discovered(
    registry: ToolRegistry,
    tools: Sequence[BaseTool],
    *,
    logger: StructuredLogger | None = None,
) -> list[BaseTool]:
    """SPEC-005 § 3 step 5 — add plugin tools without displacing built-ins.

    Step 4 of the ``run()`` lifecycle builds the registry from ``default_tools()``
    *before* plugins are discovered, so any name already present is a built-in and
    the plugin loses. SPEC-002 G2 would otherwise let ``register()`` overwrite it,
    which is exactly what a hostile or careless plugin must not be able to do.

    Args:
        registry: the registry already holding the built-in tools.
        tools: instances returned by :func:`discover_tools`.
        logger: optional structured logger.

    Returns:
        The tools that were actually registered, in the order given.
    """
    log = _resolve_logger(logger)
    registered: list[BaseTool] = []
    for tool in tools:
        name = _safe_tool_name(tool)
        if isinstance(name, _agent_error_type()):
            log.warning(
                "plugins", "plugin_failed", tool=type(tool).__name__, error=name.message
            )
            continue
        if registry.get(name) is not None:
            log.warning(
                "plugins",
                "plugin_name_collision",
                tool=name,
                reason="a tool with this name is already registered; built-ins win",
            )
            continue
        registry.register(tool)
        registered.append(tool)
    return registered
