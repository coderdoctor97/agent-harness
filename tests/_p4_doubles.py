"""Test doubles for Plan 4's suite, written against the **real** Plan 1-3 modules.

Until the integration window opened, Plan 4's tests ran against ``tests/_p4_stubs.py``
— spec-shaped stand-ins installed *under the real dotted module names*, because Plans
1-3 did not exist on disk during parallel execution.

At integration step I1 the real modules became importable, the fake ones stepped
aside, and two stub-era habits stopped being valid (SCR-P4-11):

* identity assertions such as ``BaseTool is stubs.BaseTool`` can only hold while the
  real class is unimportable, and
* a test cannot raise *its own* ``AgentError`` and expect production code to catch it,
  because ``except AgentError`` matches the shipped class only.

This module keeps the small set of collaborator doubles the suite genuinely needs, but
every double now implements the shipped interface — most names here are simple
re-exports of the real classes, so ``doubles.BaseTool`` *is* Plan 2's ``BaseTool``. The
remaining hand-written doubles (``StubEchoTool``, ``StubPlanner``, ``RecordingLogger``)
subclass or mirror the real contract, so a test can no longer pass by accident of a
type that exists only in this file.

Spec: SPEC-000 § 5.4 (contract tests) · SPEC-001 § 2 · SPEC-002 § 1-2 · SPEC-003 § 2-6
· SPEC-004 § 1-2 · SPEC-006 § 6.2
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# ---------------------------------------------------------------------------
# Real modules, re-exported under the names the suite uses.
# ---------------------------------------------------------------------------
from agent_harness.config import (  # noqa: F401
    AgentError,
    Config,
    ErrorCode,
    ExecutionConfig,
    ExecutionMetrics,
    ExecutionPlan,
    LLMConfig,
    LoggingConfig,
    PluginsConfig,
    SearchConfig,
    SecurityConfig,
    Step,
    StepStatus,
    TaskPriority,
    derive_plan_status,
    sensitive_data_filter,
)
from agent_harness.context import ContextStore  # noqa: F401
from agent_harness.llm import (  # noqa: F401
    LLMClient,
    LLMResponse,
    LLMUsage,
    MockLLMClient,
)
from agent_harness.logging import StructuredLogger, render_report  # noqa: F401
from agent_harness.orchestration import (  # noqa: F401
    Assembler,
    AssemblyResult,
    ExecutionHooks,
    Orchestrator,
    RecoveryManager,
    resolve_execution_order,
)
from agent_harness.planning import Planner, parse_plan, validate_plan  # noqa: F401
from agent_harness.tools import (  # noqa: F401
    BaseTool,
    ToolRegistry,
    ToolResult,
    default_tools,
    fail,
    ok,
    run_tool,
)

# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class StubEchoTool(BaseTool):
    """A real ``BaseTool`` that echoes its input and counts the calls it receives.

    Subclassing the shipped ``BaseTool`` matters: the registry's G1 guard
    (SPEC-002 § 2) rejects anything that is not one, so a double that only *looks*
    like a tool cannot be registered at all.
    """

    def __init__(self, name: str = "stub_echo", *, fail: bool = False) -> None:
        """Record the name and the scripted outcome.

        Args:
            name: the tool name, used as the registry key.
            fail: when true, ``execute`` returns a failed ``ToolResult``.
        """
        self._name = name
        self._fail = fail
        #: How many times ``execute`` ran (also asserted by the suite).
        self.execute_calls = 0
        #: How many times ``cleanup`` ran.
        self.cleanup_calls = 0
        #: Every ``(input_data, context)`` pair handed to ``execute``.
        self.executions: list[tuple[dict[str, Any], dict[str, Any]]] = []

    @property
    def name(self) -> str:
        """The registry key."""
        return self._name

    @property
    def description(self) -> str:
        """An LLM-facing description."""
        return f"echo tool {self._name}"

    @property
    def capabilities(self) -> list[str]:
        """One capability tag, so capability lookups have something to find."""
        return ["echo"]

    def execute(
        self, input_data: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        """Echo the input, or fail when scripted to."""
        self.execute_calls += 1
        self.executions.append((dict(input_data), context))
        if self._fail:
            return fail(f"{self._name} failed", tool_name=self._name, duration_ms=0)
        return ok(input_data, tool_name=self._name, duration_ms=0)

    def cleanup(self) -> None:
        """Count the teardown (SPEC-002 R8)."""
        self.cleanup_calls += 1


class StubPlanner(Planner):
    """A scripted planner: same interface as the shipped ``Planner``, no LLM round.

    Tests that exercise the harness's *plumbing* (lifecycle order, containment,
    hooks, reuse) should not depend on prompt parsing, so this double returns a
    canned plan and records how it was called.
    """

    def __init__(
        self,
        plan: ExecutionPlan | None = None,
        *,
        llm_client: Any = None,
        config: Any = None,
        logger: Any = None,
        models: Any = None,
        fresh: bool = True,
    ) -> None:
        """Store the canned plan; every other argument matches the real signature.

        Args:
            plan: the canned plan handed back by :meth:`plan`.
            llm_client: passed through to the real ``Planner``.
            config: passed through to the real ``Planner``.
            logger: passed through to the real ``Planner``.
            models: passed through to the real ``Planner``.
            fresh: deep-copy the canned plan per call, mirroring the real planner —
                which builds a new plan object every time. ``False`` keeps one shared
                object, for tests that assert identity across calls.
        """
        super().__init__(
            llm_client if llm_client is not None else MockLLMClient(),
            config if config is not None else Config(),
            logger=logger,
            models=models,
        )
        self._plan = plan if plan is not None else one_step_plan()
        self._fresh = fresh
        #: One entry per ``plan()`` call: prompt, tools and context.
        self.calls: list[dict[str, Any]] = []

    @property
    def prompts(self) -> list[str]:
        """Prompts this planner was asked about, in order."""
        return [call["prompt"] for call in self.calls]

    @property
    def plan_calls(self) -> list[dict[str, Any]]:
        """Alias kept for tests that read the recorded calls directly."""
        return self.calls

    def plan(
        self,
        prompt: str,
        available_tools: Any,
        *,
        context: dict[str, Any] | None = None,
    ) -> ExecutionPlan:
        """Record the call and return the canned plan (SPEC-004 § 2)."""
        self.calls.append(
            {
                "prompt": prompt,
                "available_tools": list(available_tools),
                "context": context,
            }
        )
        result = deepcopy(self._plan) if self._fresh else self._plan
        if not result.original_prompt:
            # The real planner threads the caller's prompt onto the plan
            # (SPEC-004 § 4.2); the double mirrors that so metrics computed from the
            # plan see the prompt the harness was asked about.
            result.original_prompt = prompt
        return result

    def select_tool(
        self, step: Any, available_tools: Any, *, context: dict[str, Any] | None = None
    ) -> str:
        """Select the step's hint, mirroring the real selection contract."""
        del available_tools, context
        return str(getattr(step, "tool_hint", "") or getattr(step, "tool_name", ""))

    def replan_step(
        self, step: Any, error: Any, context: dict[str, Any] | None = None, **_: Any
    ) -> list[Any]:
        """Return no replacements: scripted re-planning is a P5 scenario."""
        del step, error, context
        return []


class RecordingLogger:
    """A SPEC-006 § 6.2-shaped logger that keeps its records for assertion.

    Plan 4's startup warnings, teardown failures and interrupt notices are observed
    through the injected logger seam, so the double must speak the real protocol
    (``log``/``debug``/``info``/``warning``/``error``/``child``) without touching the
    filesystem.
    """

    def __init__(self, config: Config | None = None) -> None:
        """Accept the config a real logger takes, and start empty."""
        del config
        #: One mapping per emitted record, with at least ``level``/``event``.
        self.records: list[dict[str, Any]] = []
        self._component: str | None = None
        self._bound: dict[str, Any] = {}

    @staticmethod
    def default() -> RecordingLogger:
        """The no-argument constructor real code expects (SPEC-006 § 6.2)."""
        return RecordingLogger()

    def child(self, component: str, **bound_fields: Any) -> RecordingLogger:
        """Bind a component and extra fields on a copy, as the real logger does."""
        child = RecordingLogger()
        child.records = self.records  # shared sink: this is a recorder, not a tree
        child._component = component
        child._bound = {**self._bound, **bound_fields}
        return child

    def log(self, level: str, component: str, event: str, **fields: Any) -> None:
        """Record one event."""
        self.records.append(
            {
                **self._bound,
                **fields,
                "level": level,
                "component": component,
                "event": event,
            }
        )

    def debug(self, component: str, event: str | None = None, **fields: Any) -> None:
        """Record a DEBUG event."""
        self.log("DEBUG", component, event or "", **fields)

    def info(self, component: str, event: str | None = None, **fields: Any) -> None:
        """Record an INFO event."""
        self.log("INFO", component, event or "", **fields)

    def warning(self, component: str, event: str | None = None, **fields: Any) -> None:
        """Record a WARNING event."""
        self.log("WARNING", component, event or "", **fields)

    def error(self, component: str, event: str | None = None, **fields: Any) -> None:
        """Record an ERROR event."""
        self.log("ERROR", component, event or "", **fields)


def one_step_plan(
    *,
    tool: str = "web_search",
    step_id: str = "step_0",
    priority: TaskPriority = TaskPriority.CRITICAL,
    prompt: str = "",
    description: str = "do the thing",
) -> ExecutionPlan:
    """Build the single-step plan most harness tests execute (SPEC-001 § 2.2)."""
    return ExecutionPlan(
        original_prompt=prompt,
        steps=[
            Step(
                id=step_id,
                description=description,
                tool_hint=tool,
                priority=priority,
            )
        ],
    )


def two_step_plan() -> ExecutionPlan:
    """Build a two-step plan: one working tool, then one failing tool."""
    return ExecutionPlan(
        original_prompt="a task",
        steps=[
            Step(
                id="step_0",
                description="works",
                tool_hint="good_tool",
                priority=TaskPriority.HIGH,
            ),
            Step(
                id="step_1",
                description="fails",
                tool_hint="bad_tool",
                priority=TaskPriority.LOW,
                depends_on=["step_0"],
            ),
        ],
    )


def stub_registry(*, good: bool = True, bad: bool = True) -> ToolRegistry:
    """A registry holding the echo tools the harness tests run plans against.

    ``web_search`` is present because that is the tool ``one_step_plan`` names, so
    a plan can execute end-to-end without a real (networked) built-in tool.
    """
    registry = ToolRegistry()
    if good:
        registry.register(StubEchoTool("web_search"))
        registry.register(StubEchoTool("good_tool"))
    if bad:
        registry.register(StubEchoTool("bad_tool", fail=True))
    return registry


def no_network_tools() -> list[BaseTool]:
    """Echo doubles standing in for the built-in tools, so execution stays offline."""
    return [StubEchoTool(name) for name in ("web_search", "web_scrape", "file_write")]
