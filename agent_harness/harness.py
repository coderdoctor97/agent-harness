"""``AgentHarness`` — the composition root and public facade.

This module is the L3 surface: it wires the L0 foundation (config, context, logging,
LLM), the L1 capability layer (tools) and the L2 cognition layer (planner,
orchestrator, assembler) into a single runnable product. Dependency direction is
strictly downward
(SPEC-000 § 2); nothing here is imported by a lower layer.

Sub-phase 1.1 provides the :class:`HarnessResult` value type; sub-phase 1.2 adds the
:class:`AgentHarness` facade.

Composition strategy
--------------------
Every collaborator is resolved **lazily, by dotted name, at call time** — never imported
at module scope. Two consequences matter:

* ``import agent_harness`` never fails because a lower layer or an optional
  dependency is missing.
* The integration-window swap (planning/README § 4, step I1) needs no edit here:
  while Plans 1-3 are absent the test suite installs spec-shaped stubs under these
  same dotted names, and once they land the identical code path resolves the real
  modules.

Spec: SPEC-005 § 1 · SPEC-001 § 2.5
"""

from __future__ import annotations

import importlib
import os
import shutil
import time
import types
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only; real modules arrive at I1
    from agent_harness.config import Config
    from agent_harness.config.schema import (
        AgentError,
        ExecutionMetrics,
        ExecutionPlan,
    )
    from agent_harness.llm.client import LLMClient
    from agent_harness.logging.logger import StructuredLogger
    from agent_harness.orchestration.assembler import Assembler
    from agent_harness.orchestration.orchestrator import ExecutionHooks, Orchestrator
    from agent_harness.planning.planner import Planner
    from agent_harness.tools.base import BaseTool, ToolRegistry


#: SPEC-005 § 1.1 step 1 — the prompt length bound.
MAX_PROMPT_CHARS = 20_000

#: SPEC-005 § 1.1 — lifecycle steps whose failure **raises** to the caller
#: (3 create client, 4 build registry, 5 plan).
RAISING_LIFECYCLE_STEPS = frozenset({3, 4, 5})

#: SPEC-005 § 1.1 — lifecycle steps whose failure is **contained** and surfaced on
#: ``HarnessResult.status`` / ``errors`` (6 execute, 7 assemble, 8 metrics/report).
#: Once a plan exists the harness always returns a result.
CONTAINED_LIFECYCLE_STEPS = frozenset({6, 7, 8})


@dataclass
class HarnessResult:
    """The value returned by :meth:`AgentHarness.run`.

    Field names, order and types are FROZEN by SPEC-005 § 1.

    Attributes:
        status: ``"completed"``, ``"partial"`` or ``"failed"`` (SPEC-003 § 6).
        final_output: the assembled deliverable — a string for text/markdown, a mapping
            for structured output.
        plan: the executed plan, with every step carrying a terminal status.
        metrics: post-run accounting (SPEC-001 § 2.5).
        files_created: mirrors ``context["files_created"]`` — deduplicated, ordered
            (SPEC-005 § 1.2).
        errors: mirrors ``context["errors"]`` — JSON-safe dicts (SPEC-001 § 2.4).
    """

    status: str
    final_output: Any
    plan: ExecutionPlan
    metrics: ExecutionMetrics
    files_created: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)


class AgentHarness:
    """The public facade and composition root.

    Example:
        >>> from agent_harness import AgentHarness, Config
        >>> config = Config.from_file("./config.yaml")   # doctest: +SKIP (needs I1)
        >>> harness = AgentHarness(config)               # doctest: +SKIP (needs I1)
        >>> result = harness.run("Research X")   # doctest: +SKIP (needs I1)

    Args:
        config: typed configuration (SPEC-006 § 1).
        llm_client: injected LLM client; when ``None`` one is built from
            ``agent_harness.llm.create_llm_client`` on first use.
        planner: injected planner (SPEC-004 § 2).
        orchestrator: injected orchestrator (SPEC-003 § 2).
        assembler: injected assembler (SPEC-003 § 6).
        registry: injected tool registry (SPEC-002 § 2).
        logger: injected structured logger (SPEC-006 § 6.2).
        clock: monotonic time source used for ``total_duration_ms``. Injectable so
            tests are deterministic (SPEC-000 § 5.5).
        progress: called with one structured event dict per orchestrator event
            (SPEC-003 § 2.1). The CLI supplies a Rich renderer here (SPEC-005
            § 2.2); the default is no output at all.

    The five injectable collaborators are the documented test seams: injecting one
    guarantees the real constructor is never called for it.
    """

    def __init__(
        self,
        config: Config,
        *,
        llm_client: LLMClient | None = None,
        planner: Planner | None = None,
        orchestrator: Orchestrator | None = None,
        assembler: Assembler | None = None,
        registry: ToolRegistry | None = None,
        logger: StructuredLogger | None = None,
        clock: Callable[[], float] = time.monotonic,
        progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """Store the config and seams, and create the working directories.

        Every argument after ``config`` is a test seam. Production code passes
        only the config and lets the harness resolve its collaborators.

        Example:
            >>> harness = AgentHarness(Config())          # doctest: +SKIP (needs I1)
            >>> harness.list_tools()                      # doctest: +SKIP (needs I1)
        """
        self.config = config
        self._llm_client = llm_client
        self._planner = planner
        self._orchestrator = orchestrator
        self._assembler = assembler
        self._registry = registry
        self._logger = logger
        self._clock = clock
        self._progress = progress
        self._closed = False
        self._emitted_warnings: set[str] = set()
        #: The result of the most recent :meth:`run`, including an interrupted one.
        self.last_result: HarnessResult | None = None
        #: The report rendered by the most recent :meth:`run`, or ``None``.
        self.last_report: str | None = None
        #: Plugins that failed to load, kept for the ``--list-tools`` footer
        #: (SPEC-005 § 3 step 6). Populated when the registry is built.
        self.plugin_errors: list[AgentError] = []
        self._ensure_directories()
        self._emit_startup_warnings()

    @classmethod
    def from_config(cls, path: str = "./config.yaml") -> AgentHarness:
        """Build a harness from a configuration file.

        Args:
            path: path to a ``config.yaml``.

        Returns:
            A configured :class:`AgentHarness`.

        Example:
            >>> harness = AgentHarness.from_config()  # doctest: +SKIP (needs I1)
        """
        config_module = importlib.import_module("agent_harness.config")
        return cls(config_module.Config.from_file(path))

    # -- internal collaborators ------------------------------------------------

    def _ensure_directories(self) -> None:
        """SPEC-005 § 1.2 — create ``output_dir`` and ``temp_dir`` when missing.

        SPEC-006 K4 assigns lazy directory creation to consumers, so the harness owns
        this rather than the config loader.
        """
        for directory in (
            self.config.execution.output_dir,
            self.config.execution.temp_dir,
        ):
            os.makedirs(directory, exist_ok=True)

    def _resolve_llm_client(self) -> LLMClient:
        """Return the injected client, building and caching one if absent.

        Returns:
            The LLM client for this harness.

        Raises:
            AgentError: ``CONFIG_VALIDATION_FAILED`` when the configured
                ``api_key_env`` variable is unset. The message names the variable and
                the remediation, per SPEC-005 § 4. Construction itself does not raise
                (SPEC-006 K5) so that ``--list-tools`` works without credentials.
        """
        if self._llm_client is not None:
            return self._llm_client
        llm_module = importlib.import_module("agent_harness.llm")
        self._llm_client = llm_module.create_llm_client(self.config)
        return self._llm_client

    def _resolve_logger(self) -> StructuredLogger:
        """Return the injected logger, building and caching one if absent."""
        if self._logger is not None:
            return self._logger
        logging_module = importlib.import_module("agent_harness.logging")
        self._logger = logging_module.StructuredLogger(self.config)
        return self._logger

    # -- startup warnings (SPEC-005 § 4) ---------------------------------------

    def _emit_startup_warnings(self) -> None:
        """SPEC-005 § 4 — one-time startup warnings.

        Every message names variables and binaries only; **no credential value is
        ever placed in a log record**. Each condition is emitted at most once per
        instance, so a harness reused across runs does not repeat itself.
        """
        logger = self._resolve_logger()

        transmitted = self._transmitted_env_names()
        if transmitted:
            self._emit_once(
                "credentials_transmitted",
                lambda: logger.warning(
                    "harness",
                    "credentials_transmitted",
                    env_vars=transmitted,
                    note=(
                        "these variables are sent to external providers; "
                        "names only - values are never logged"
                    ),
                ),
            )

        if shutil.which("wkhtmltopdf") is None:
            self._emit_once(
                "pdf_export_degraded",
                lambda: logger.info(
                    "harness",
                    "pdf_export_degraded",
                    note=(
                        "wkhtmltopdf not found; pdf_export runs in degraded "
                        "markdown mode"
                    ),
                ),
            )

        if self.config.security.allow_shell:
            self._emit_once(
                "shell_execution_enabled",
                lambda: logger.warning(
                    "harness",
                    "shell_execution_enabled",
                    note=(
                        "security.allow_shell is true; whitelisted shell "
                        "commands can run on this machine"
                    ),
                ),
            )

        api_key_env = self.config.llm.api_key_env
        if api_key_env and not os.environ.get(api_key_env):
            self._emit_once(
                "api_key_missing",
                lambda: logger.warning(
                    "harness",
                    "api_key_missing",
                    env_var=api_key_env,
                    remediation="cp .env.example .env and add your key",
                ),
            )

    def _emit_once(self, event: str, emit: Callable[[], None]) -> None:
        """Emit a warning at most once per harness instance."""
        if event in self._emitted_warnings:
            return
        self._emitted_warnings.add(event)
        emit()

    def _transmitted_env_names(self) -> list[str]:
        """Names of configured credentials that will leave this machine.

        Returns:
            Sorted, de-duplicated environment variable *names* (never values).
        """
        candidates = {
            self.config.llm.api_key_env: self.config.llm.provider,
            self.config.search.api_key_env: self.config.search.provider,
        }
        present = set(os.environ) | set(self._read_dotenv_names())
        return sorted(name for name in candidates if name and name in present)

    def _read_dotenv_names(self) -> list[str]:
        """Read only the *names* defined by a local ``.env``.

        Values are deliberately never parsed into memory beyond the line being
        scanned, so a malformed or unreadable file cannot leak or crash startup.
        """
        path = os.path.join(os.getcwd(), ".env")
        if not os.path.isfile(path):
            return []
        names: list[str] = []
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#") or "=" not in stripped:
                        continue
                    name = stripped.split("=", 1)[0].strip()
                    if name.startswith("export "):
                        name = name[len("export ") :].strip()
                    if name and name.replace("_", "").isalnum():
                        names.append(name)
        except OSError as exc:
            self._resolve_logger().warning(
                "harness", "dotenv_unreadable", error=str(exc)
            )
        return names

    # -- run lifecycle: steps 1-4 ----------------------------------------------

    def _prepare_run(
        self, prompt: str, context: dict[str, Any] | None
    ) -> dict[str, Any]:
        """SPEC-005 § 1.1 steps 1-4 — validate, fresh context, client, registry.

        Steps 3 and 4 belong to :data:`RAISING_LIFECYCLE_STEPS`: a failure here
        propagates to the caller rather than being contained.

        Args:
            prompt: the task description.
            context: caller-supplied context; seeds ``variables`` and, for
                path-shaped values, ``allowed_read_paths``.

        Returns:
            The fresh per-run context mapping (SPEC-003 § 4.1 layout).
        """
        self._validate_prompt(prompt)  # step 1
        run_context = self._new_context(context)  # step 2
        self._resolve_llm_client()  # step 3
        self._resolve_registry()  # step 4
        run_context["llm_client"] = self._llm_client
        return run_context

    def _new_context(self, supplied: dict[str, Any] | None) -> dict[str, Any]:
        """SPEC-005 § 1.1 step 2 — a fresh ContextStore, seeded from the caller.

        Returns:
            The store's mapping, with ``variables`` and ``allowed_read_paths``
            seeded. The mapping is never shared between runs.
        """
        context_module = importlib.import_module("agent_harness.context")
        store = context_module.ContextStore(self.config)
        data: dict[str, Any] = store.as_dict()
        values = dict(supplied or {})
        data["variables"] = values
        data["allowed_read_paths"] = self._collect_read_paths(values)
        return data

    @classmethod
    def _collect_read_paths(cls, node: Any) -> list[str]:
        """Collect path-shaped strings from the caller's context, in traversal order.

        Args:
            node: a string, mapping or sequence to walk recursively.

        Returns:
            Unique path-shaped strings, in first-seen order.
        """
        found: list[str] = []

        def walk(current: Any) -> None:
            if isinstance(current, str):
                if cls._looks_like_path(current) and current not in found:
                    found.append(current)
            elif isinstance(current, dict):
                for value in current.values():
                    walk(value)
            elif isinstance(current, (list, tuple)):
                for value in current:
                    walk(value)

        walk(node)
        return found

    @staticmethod
    def _looks_like_path(value: str) -> bool:
        """Decide whether a string is plausibly a filesystem path.

        Conservative on purpose: anything containing whitespace or control
        characters is rejected, so prose in the caller's context never widens
        ``allowed_read_paths`` (SPEC-002 § 3.4).
        """
        if not value or len(value) > 4096:
            return False
        if any(char in value for char in "\n\r\x00"):
            return False
        if value != value.strip() or " " in value:
            return False
        root, extension = os.path.splitext(os.path.basename(value))
        if extension and root:
            return True
        return os.sep in value or "/" in value or value.startswith((".", "~"))

    def _resolve_registry(self) -> ToolRegistry:
        """Return the tool registry, building and caching it if absent.

        SPEC-005 § 1.1 step 4. The registry is cached so that ``register_tool()``
        after a run affects subsequent runs only (SPEC-005 § 5).

        The LLM client is resolved *tolerantly* here: a missing API key must not stop
        the registry from being listed, because ``--list-tools`` is required to work
        without credentials (SPEC-006 K5). Planning and execution still demand a real
        client, and those paths raise.
        """
        if self._registry is not None:
            return self._registry
        tools_module = importlib.import_module("agent_harness.tools")
        registry = tools_module.ToolRegistry()
        for tool in tools_module.default_tools(self.config, self._llm_client_or_none()):
            registry.register(tool)
        self._load_plugins(registry)
        self._registry = registry
        return self._registry

    def _load_plugins(self, registry: ToolRegistry) -> None:
        """SPEC-005 § 1.1 step 4 — add discovered plugins after the built-ins.

        Order matters: registering the built-ins first is what makes the
        collision rule in SPEC-005 § 3 step 5 work, since
        :func:`agent_harness.plugins.loader.register_discovered` refuses any name
        already present. Failures are collected rather than raised, so one bad
        plugin costs its own tool and shows up in the ``--list-tools`` footer.

        Args:
            registry: the registry already holding the built-in tools.
        """
        loader = importlib.import_module("agent_harness.plugins.loader")
        plugin_dirs = list(self.config.plugins.dirs)
        tools, errors = loader.discover_tools(
            plugin_dirs,
            config=self.config,
            llm_client=self._llm_client_or_none(),
            logger=self._resolve_logger(),
        )
        loader.register_discovered(registry, tools, logger=self._resolve_logger())
        self.plugin_errors = list(errors)

    def _resolve_planner(self) -> Planner:
        """Return the injected planner, building and caching one if absent."""
        if self._planner is not None:
            return self._planner
        planning_module = importlib.import_module("agent_harness.planning")
        self._planner = planning_module.Planner(
            self._resolve_llm_client(), self.config, logger=self._resolve_logger()
        )
        return self._planner

    def _resolve_orchestrator(self) -> Orchestrator:
        """Return the injected orchestrator, building and caching one if absent.

        ``context_store`` is left unset on purpose: the harness threads the single
        per-run context through ``plan.context`` (see :meth:`run`), so the
        orchestrator and the assembler cannot end up looking at different objects.
        """
        if self._orchestrator is not None:
            return self._orchestrator
        orchestration_module = importlib.import_module("agent_harness.orchestration")
        self._orchestrator = orchestration_module.Orchestrator(
            self._resolve_registry(),
            self.config,
            llm_client=self._llm_client,
            planner=self._resolve_planner(),
            context_store=None,
            logger=self._resolve_logger(),
        )
        return self._orchestrator

    def _build_hooks(self) -> ExecutionHooks:
        """SPEC-003 § 2.1 — bridge orchestrator events onto the ``progress`` seam.

        Each event is delivered as a single dict whose ``"event"`` key is one of
        ``plan_start``, ``step_start``, ``step_complete``, ``step_failed``,
        ``recovery`` or ``plan_complete``.

        Delivery is best-effort in *both* layers: the orchestrator is required to
        isolate hook exceptions, and this bridge isolates them again, so a broken
        renderer can never abort a run. A failure is logged at ``WARNING`` rather
        than swallowed.

        Returns:
            A fully populated :class:`ExecutionHooks`.
        """
        orchestration_module = importlib.import_module("agent_harness.orchestration")

        def emit(kind: str, **fields: Any) -> None:
            callback = self._progress
            if callback is None:
                return
            try:
                callback({"event": kind, **fields})
            except Exception as exc:  # not a bare except: interrupts still propagate
                self._resolve_logger().warning(
                    "harness",
                    "progress_callback_failed",
                    error=str(exc),
                    progress_event=kind,
                )

        return orchestration_module.ExecutionHooks(
            on_plan_start=lambda plan: emit("plan_start", plan_id=plan.id),
            on_step_start=lambda step: emit(
                "step_start",
                step_id=step.id,
                description=step.description,
                tool=step.tool_hint or step.tool_name,
            ),
            on_step_complete=lambda step, result: emit(
                "step_complete",
                step_id=step.id,
                tool=step.tool_name or step.tool_hint,
                success=result.success,
                duration_ms=step.duration_ms,
            ),
            on_step_failed=lambda step, error: emit(
                "step_failed",
                step_id=step.id,
                tool=step.tool_name or step.tool_hint,
                error=error,
            ),
            on_recovery=lambda step, level, action: emit(
                "recovery",
                step_id=step.id,
                level=level,
                action=action,
            ),
            on_plan_complete=lambda plan: emit(
                "plan_complete", plan_id=plan.id, status=plan.status.value
            ),
        )

    def _execute_with_hooks(self, plan: ExecutionPlan) -> ExecutionPlan:
        """SPEC-005 § 1.1 step 6 — execute with the progress seam attached.

        Hooks are attached per run rather than at construction so that a cached
        orchestrator still reports to the current ``progress`` callback.
        """
        orchestrator = self._resolve_orchestrator()
        orchestrator.hooks = self._build_hooks()
        return orchestrator.execute(plan)

    def _resolve_assembler(self) -> Assembler:
        """Return the injected assembler, building and caching one if absent."""
        if self._assembler is not None:
            return self._assembler
        orchestration_module = importlib.import_module("agent_harness.orchestration")
        self._assembler = orchestration_module.Assembler(
            self.config,
            llm_client=self._llm_client,
            logger=self._resolve_logger(),
        )
        return self._assembler

    def _llm_client_or_none(self) -> LLMClient | None:
        """Return the LLM client, or ``None`` when no credentials are available.

        Never silent: the reason is logged at ``WARNING`` (SPEC-006 § 6.1).
        """
        if self._llm_client is not None:
            return self._llm_client
        try:
            return self._resolve_llm_client()
        except Exception as exc:
            self._resolve_logger().warning(
                "harness",
                "llm_client_unavailable",
                reason=str(exc),
            )
            return None

    # -- public API ------------------------------------------------------------

    def plan(self, prompt: str) -> ExecutionPlan:
        """Produce a validated plan without executing it (dry run).

        Args:
            prompt: the task description.

        Returns:
            The :class:`ExecutionPlan` produced by the planner. Plan-level validation
            (circular dependencies, unknown step references, ``max_steps``) is the
            planner's responsibility per SPEC-004 § 4.

        Raises:
            AgentError: ``PROMPT_INVALID`` for an empty or oversized prompt, or any
                error raised while building the client, registry or plan.

        Example:
            >>> plan = harness.plan("Build a REST API")   # doctest: +SKIP (needs I1)
            >>> [step.tool_hint for step in plan.steps]   # doctest: +SKIP (needs I1)
        """
        self._validate_prompt(prompt)
        registry = self._resolve_registry()
        return self._resolve_planner().plan(prompt, registry.list_tools())

    def run(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | None = None,
        output_format: str = "markdown",
    ) -> HarnessResult:
        """Execute the full POEA lifecycle and return the result.

        SPEC-005 § 1.1 steps 1-9. Steps 1-5 propagate their failures; once a plan
        exists (step 6 onward) every failure is contained and reported on the
        returned :class:`HarnessResult`.

        The per-run context is a single mapping shared by the orchestrator and the
        assembler: it is installed as ``plan.context`` so writes cannot diverge
        from reads (SPEC-003 § 4.1, § 6).

        Args:
            prompt: the task description.
            context: caller-supplied context; seeds ``variables`` and
                ``allowed_read_paths``.
            output_format: the requested deliverable format, exposed to the
                assembler through ``context["output_format"]``.

        Returns:
            A :class:`HarnessResult`. ``status`` is ``"completed"``, ``"partial"``
            or ``"failed"``.

        Raises:
            AgentError: for a failure in steps 1-5 (validation, client, registry,
                planning).

        Example:
            >>> result = harness.run("Research AI safety")   # doctest: +SKIP (needs I1)
            >>> result.status                                # doctest: +SKIP (needs I1)
        """
        run_context = self._prepare_run(prompt, context)  # steps 1-4
        run_context["output_format"] = output_format
        registry = self._resolve_registry()
        started = self._clock()

        plan: ExecutionPlan | None = None
        try:
            plan = self._resolve_planner().plan(  # step 5 — raising
                prompt, registry.list_tools(), context=run_context
            )
            self._adopt_context(plan, run_context)
            self._apply_recovery_policy(plan)

            try:  # steps 6-8 — contained
                executed = self._execute_with_hooks(plan)  # step 6
                assembler = self._resolve_assembler()
                assembly = assembler.assemble(executed, run_context)  # step 7
                duration_ms = int((self._clock() - started) * 1000)
                metrics = self._build_metrics(
                    executed, total_duration_ms=duration_ms
                )  # step 8
                self.last_report = self._render_report(executed, metrics, output_format)
            except Exception as exc:  # contained per SPEC-005 § 1.1; not a bare except
                self.last_result = self._contain_failure(plan, run_context, exc)
                return self.last_result
        except KeyboardInterrupt:
            # SPEC-003 § 2: the orchestrator marks the step and re-raises. The
            # harness records a failed result for inspection, then lets the
            # interrupt through so the CLI can exit 130 (SPEC-005 § 2.1). It is
            # never swallowed.
            if plan is not None:
                self.last_result = self._record_interrupt(plan, run_context)
            raise

        self.last_result = HarnessResult(  # step 9
            status=assembly.status,
            final_output=assembly.final_output,
            plan=executed,
            metrics=metrics,
            files_created=self._mirror_files_created(
                [*run_context.get("files_created", []), *assembly.files_created]
            ),
            errors=list(run_context.get("errors", [])),
        )
        return self.last_result

    def set_progress(self, callback: Callable[[dict[str, Any]], None] | None) -> None:
        """Install or replace the progress callback after construction.

        The CLI uses this to attach its console renderer once it knows whether
        the destination is a terminal. Like the constructor seam, delivery is
        best effort: a callback that raises is isolated and logged as
        ``progress_callback_failed`` rather than allowed to abort the run.

        Args:
            callback: receives one event dict per orchestrator event, or
                ``None`` to stop progress reporting.

        Example:
            >>> events = []                               # doctest: +SKIP (needs I1)
            >>> harness.set_progress(events.append)       # doctest: +SKIP (needs I1)
            >>> harness.run("Summarise the report")       # doctest: +SKIP (needs I1)
            >>> events[0]["event"]                        # doctest: +SKIP (needs I1)
            'plan_start'
        """
        self._progress = callback

    def register_tool(self, tool: BaseTool) -> None:
        """Register a tool at runtime (SPEC-005 § 1).

        The tool joins the registry used by every *subsequent* run; a plan already
        produced is unaffected (SPEC-005 § 5). Re-registering an existing name
        overwrites it (SPEC-002 G2).

        Args:
            tool: a ``BaseTool`` *instance*.

        Raises:
            TypeError: if ``tool`` is not a ``BaseTool`` instance — the registry's
                own G1 guard, passed straight through rather than re-implemented.

        Example:
            >>> db = DatabaseQueryTool(db_path="app.db")   # doctest: +SKIP (needs I1)
            >>> harness.register_tool(db)                  # doctest: +SKIP (needs I1)
        """
        self._resolve_registry().register(tool)

    def list_tools(self) -> list[dict[str, Any]]:
        """Return the registry's tool descriptors (SPEC-005 § 1).

        Returns:
            One ``{"name", "description", "capabilities"}`` mapping per tool, in
            the registry's deterministic order (SPEC-002 G3).

        Example:
            >>> for tool in harness.list_tools():   # doctest: +SKIP (needs I1)
            ...     print(tool["name"])
        """
        descriptors: list[dict[str, Any]] = self._resolve_registry().list_tools()
        return descriptors

    # -- validation ------------------------------------------------------------

    def _validate_prompt(self, prompt: str) -> None:
        """SPEC-005 § 1.1 step 1 — reject an unusable prompt.

        The bound counts *characters*, not bytes, and is measured on the raw prompt
        so that padding cannot smuggle an oversized one through.

        Args:
            prompt: the task description.

        Raises:
            AgentError: ``PROMPT_INVALID`` when the prompt is not a string, is empty
                after stripping, or exceeds :data:`MAX_PROMPT_CHARS`.
        """
        if not isinstance(prompt, str) or not prompt.strip():
            raise self._agent_error(
                code="PROMPT_INVALID",
                message="prompt must be a non-empty string",
            )
        if len(prompt) > MAX_PROMPT_CHARS:
            raise self._agent_error(
                code="PROMPT_INVALID",
                message=(
                    f"prompt is {len(prompt)} characters; the maximum is "
                    f"{MAX_PROMPT_CHARS}"
                ),
            )

    @staticmethod
    def _adopt_context(plan: ExecutionPlan, run_context: dict[str, Any]) -> None:
        """Make ``plan.context`` and the run context the *same* object.

        Planner-extracted variables are merged in first, with caller-supplied
        values winning on a key collision. After this call the orchestrator, the
        assembler and the harness all read and write one mapping.

        Args:
            plan: the plan returned by the planner.
            run_context: the per-run context (SPEC-003 § 4.1 layout).
        """
        extracted = plan.context.get("variables") if plan.context else None
        if isinstance(extracted, dict):
            merged = dict(extracted)
            merged.update(run_context["variables"])
            run_context["variables"] = merged
        plan.context = run_context

    def _apply_recovery_policy(self, plan: ExecutionPlan) -> None:
        """SPEC-005 § 2 — honour ``--no-fallback`` by limiting recovery.

        ``--no-fallback`` sets ``execution.enable_replan`` to false, and that
        single switch has two consequences in SPEC-003's recovery cascade:
        Level 3 (replan) is off because the orchestrator reads the same flag,
        and Level 2 (retry with a fallback tool) is off because the fallback
        lists are removed here. What is left is Level 1, retrying the same tool
        — exactly what the spec promises.

        Keying off the config rather than off a separate CLI flag means a user
        who sets ``execution.enable_replan: false`` in ``config.yaml`` gets the
        same behaviour as one who passes the flag.

        Args:
            plan: the freshly built plan, mutated in place before execution.
        """
        if self.config.execution.enable_replan:
            return
        for step in plan.steps:
            step.fallback_tools = []

    def _render_report(
        self, plan: ExecutionPlan, metrics: ExecutionMetrics, output_format: str
    ) -> str:
        """SPEC-005 § 1.1 step 8 — render the report through ``logging/report.py``."""
        report_module = importlib.import_module("agent_harness.logging.report")
        style = output_format if output_format in ("text", "markdown") else "text"
        rendered: str = report_module.render_report(plan, metrics, style=style)
        return rendered

    def _contain_failure(
        self,
        plan: ExecutionPlan,
        run_context: dict[str, Any],
        exc: Exception,
    ) -> HarnessResult:
        """SPEC-005 § 1.1 — contain a step 6-8 failure and still return a result.

        The failure is logged, appended to ``context['errors']`` and reported on the
        result. ``KeyboardInterrupt`` and ``SystemExit`` are deliberately *not*
        caught here, so an interrupt propagates to the CLI (SPEC-005 § 2.1, exit
        code 130).
        """
        record = self._contained_error_record(exc)
        errors: list[dict[str, Any]] = [*run_context.get("errors", []), record]
        run_context["errors"] = errors
        schema_module = importlib.import_module("agent_harness.config.schema")
        plan.status = schema_module.StepStatus.FAILED
        self._resolve_logger().error(
            "harness",
            "lifecycle_step_failed",
            error_code=record["code"],
            error=str(exc),
            plan_id=plan.id,
        )
        return self._failure_result(plan, errors)

    def _contained_error_record(
        self, exc: BaseException, *, step_id: str | None = None
    ) -> dict[str, Any]:
        """Build a context error record for a contained failure.

        Carries the SPEC-003 § 4.1 keys plus the SPEC-001 § 2.4 error identity, so
        either shape of consumer can read it.
        """
        schema_module = importlib.import_module("agent_harness.config.schema")
        if isinstance(exc, schema_module.AgentError):
            code, component = exc.code, exc.component
        else:
            code, component = "SYSTEM_ERROR", "harness"
        return {
            "step_id": step_id,
            "attempt": 0,
            "error": str(exc),
            "recovered": False,
            "level": 4,
            "code": code,
            "component": component,
            "original_error": type(exc).__name__,
        }

    @staticmethod
    def _mirror_files_created(files: Iterable[str] | None) -> list[str]:
        """SPEC-005 § 1.2 — mirror ``context['files_created']``, deduped, in order."""
        seen: set[str] = set()
        ordered: list[str] = []
        for path in files or []:
            if path not in seen:
                seen.add(path)
                ordered.append(path)
        return ordered

    # -- shutdown --------------------------------------------------------------

    def close(self) -> None:
        """Tear down every registered tool (SPEC-002 R8).

        Idempotent: a second call does nothing. A tool whose ``cleanup()`` raises
        is logged and skipped, so one bad teardown cannot prevent the others -
        and the failure is never silenced.

        Example:
            >>> harness = AgentHarness.from_config()   # doctest: +SKIP (needs I1)
            >>> harness.run("Summarise the report")    # doctest: +SKIP (needs I1)
            >>> harness.close()                        # doctest: +SKIP (needs I1)
            >>> harness.close()   # safe to call twice # doctest: +SKIP (needs I1)
        """
        if self._closed:
            return
        self._closed = True
        registry = self._registry
        if registry is None:
            return
        for name in registry.names():
            tool = registry.get(name)
            if tool is None:
                continue
            try:
                tool.cleanup()
            except Exception as exc:  # not a bare except; interrupts propagate
                self._resolve_logger().error(
                    "harness",
                    "tool_cleanup_failed",
                    tool_name=name,
                    error=str(exc),
                )

    def __enter__(self) -> AgentHarness:
        """Enter the context manager.

        Preferred over a manual :meth:`close`, because teardown then happens even
        when the block raises.

        Example:
            >>> with AgentHarness.from_config() as h:  # doctest: +SKIP (needs I1)
            ...     result = h.run("Summarise the report")
            >>> result.status                        # doctest: +SKIP (needs I1)
            'completed'
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> None:
        """Exit the context manager, closing the harness.

        Returns ``None`` so that any in-flight exception continues to propagate:
        a harness must never swallow the caller's error while tidying up.

        Example:
            >>> with AgentHarness.from_config() as h:  # doctest: +SKIP (needs I1)
            ...     raise RuntimeError("caller error")
            Traceback (most recent call last):
                ...
            RuntimeError: caller error
        """
        self.close()

    def _record_interrupt(
        self, plan: ExecutionPlan, run_context: dict[str, Any]
    ) -> HarnessResult:
        """SPEC-003 § 2 — record the failed result for an interrupted run.

        Steps still pending or running are marked ``FAILED`` with
        ``error="interrupted"``; the plan is marked ``FAILED``; the interrupt is
        logged. The caller then re-raises.
        """
        schema_module = importlib.import_module("agent_harness.config.schema")
        unfinished = (
            schema_module.StepStatus.PENDING,
            schema_module.StepStatus.RUNNING,
            schema_module.StepStatus.RETRYING,
        )
        for step in plan.steps:
            if step.status in unfinished:
                step.status = schema_module.StepStatus.FAILED
                if step.error is None:
                    step.error = "interrupted"
        plan.status = schema_module.StepStatus.FAILED
        record = self._contained_error_record(KeyboardInterrupt("interrupted"))
        record["error"] = "interrupted"
        errors: list[dict[str, Any]] = [*run_context.get("errors", []), record]
        run_context["errors"] = errors
        self._resolve_logger().warning("harness", "run_interrupted", plan_id=plan.id)
        return self._failure_result(plan, errors)

    def _build_metrics(
        self, plan: ExecutionPlan, *, total_duration_ms: int = 0
    ) -> ExecutionMetrics:
        """SPEC-005 § 1.1 step 8 — compute metrics for a finished plan.

        LLM usage is read from the client this harness holds, so counters accumulate
        across runs on a reused instance (SPEC-005 § 5).
        """
        schema_module = importlib.import_module("agent_harness.config.schema")
        usage: dict[str, Any] = {}
        client = self._llm_client
        if client is not None:
            counters = client.usage
            usage = {
                "calls": counters.calls,
                "prompt_tokens": counters.prompt_tokens,
                "completion_tokens": counters.completion_tokens,
                "estimated_cost": counters.estimated_cost,
            }
        return schema_module.ExecutionMetrics.from_plan(
            plan, {"total_duration_ms": total_duration_ms}, usage
        )

    def _failure_result(
        self,
        plan: ExecutionPlan,
        errors: list[dict[str, Any]],
        *,
        status: str = "failed",
    ) -> HarnessResult:
        """Build the result returned when a contained lifecycle step failed.

        SPEC-005 § 1.1: once a plan exists the harness always returns a result, so a
        failure in steps 6-8 is reported here rather than raised.

        Args:
            plan: the plan that was being executed.
            errors: the context's error records, mirrored verbatim.
            status: the verdict to report — ``"failed"`` or ``"partial"``.

        Returns:
            A complete :class:`HarnessResult`.
        """
        return HarnessResult(
            status=status,
            final_output=None,
            plan=plan,
            metrics=self._build_metrics(plan),
            files_created=self._mirror_files_created(plan.context.get("files_created")),
            errors=list(errors),
        )

    def _agent_error(self, *, code: str, message: str) -> AgentError:
        """Build an ``AgentError`` attributed to this component.

        Constructed through the real module so the composed system uses Plan 1's type.
        """
        schema_module = importlib.import_module("agent_harness.config.schema")
        return schema_module.AgentError(code=code, message=message, component="harness")
