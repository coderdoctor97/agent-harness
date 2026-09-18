"""Unit tests for the Plan 3 orchestration half.

Spec: SPEC-003 (orchestrator, dependency resolution, recovery, assembly),
SPEC-002 § 1-2 (``BaseTool`` / ``ToolRegistry`` contracts, consumed via
injection), SPEC-001 § 2 (data model), SPEC-006 § 1/6 (config, log events).

Sub-phases covered by this file: 1.4 (test doubles + the contract tests that pin
them), then 3.2-3.5 (``Orchestrator``) and 5.5 (end-to-end POEA simulation).
``resolve_execution_order`` is tested in ``tests/test_dependency.py``, the recovery
cascade in ``tests/test_recovery.py`` and the assembler in ``tests/test_assembler.py``.

Test doubles: SCR-P3-3 records that ``tests/_p3_doubles.py`` is absent from the
SPEC-000 § 3.3 ownership matrix, so this plan declares its spec-shaped fakes inside
the test files it owns. Nothing here imports ``agent_harness.tools``,
``agent_harness.config``, ``agent_harness.llm``, ``agent_harness.context`` or
``agent_harness.logging``; every collaborator is injected. Tests are deterministic:
no network, no live LLM, no real sleeping, no wall-clock reads (SPEC-000 § 5.5).

Skills applied: SKL-CORE-TDD (core-coding/tdd-test-runner — fixtures over mocks,
boundary matrices), SKL-CORE-TYPES (core-coding/strict-typing-contracts),
SKL-REL-FLAKY (reliability/flaky-test-isolator — fake clocks and sleeps),
SKL-BACK-OTEL (backend/otel-observability — bounded, catalog-only log fields).
"""

from __future__ import annotations

import copy
import inspect
import socket
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta
from typing import Any

import pytest

from agent_harness.planning.planner import (
    ExecutionPlan,
    PlanLike,
    SpecModels,
    Step,
    StepLike,
    StepStatus,
    TaskPriority,
    ToolResult,
    ToolResultLike,
)

# ══════════════════════════════════════════════════════════════════════════════
# Sub-phase 1.4 — the spec-shaped double kit for the cognition layer
# ══════════════════════════════════════════════════════════════════════════════

HOOK_NAMES: tuple[str, ...] = (
    "on_plan_start",
    "on_step_start",
    "on_step_complete",
    "on_step_failed",
    "on_recovery",
    "on_plan_complete",
)
"""The six ``ExecutionHooks`` callbacks of SPEC-003 § 2.1, pinned from 1.4 onward."""


@dataclass
class FakeLLMSection:
    """SPEC-006 § 1 `llm:` section, defaults verbatim."""

    provider: str = "openai"
    model: str = "gpt-4o"
    fallback_model: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.2
    timeout: int = 60
    max_retries: int = 3
    cost_per_1k_tokens: float | None = None


@dataclass
class FakeExecutionSection:
    """SPEC-006 § 1 `execution:` section, defaults verbatim."""

    max_steps: int = 20
    step_timeout: int = 120
    max_retries: int = 2
    retry_backoff: str = "exponential"
    retry_base_delay: float = 2.0
    enable_replan: bool = True
    abort_on_critical_failure: bool = True
    output_dir: str = "./output"
    temp_dir: str = "./tmp"


@dataclass
class FakeConfig:
    """Spec-shaped stand-in for Plan 1's `Config` (SPEC-006 § 1, § 1.1)."""

    llm: FakeLLMSection = field(default_factory=FakeLLMSection)
    execution: FakeExecutionSection = field(default_factory=FakeExecutionSection)

    def get(self, path: str, default: Any = None) -> Any:
        """Dotted-path lookup (SPEC-006 § 1.1)."""
        node: Any = self
        for part in path.split("."):
            node = (
                getattr(node, part, None)
                if not isinstance(node, dict)
                else node.get(part)
            )
            if node is None:
                return default
        return node

    def to_dict(self, redact_secrets: bool = True) -> dict[str, Any]:
        """Secret-free dump (SPEC-006 § 1.1): only `*_env` names ever appear."""
        return {
            "llm": {
                "provider": self.llm.provider,
                "model": self.llm.model,
                "max_tokens": self.llm.max_tokens,
                "api_key_env": self.llm.api_key_env,
            },
            "execution": {
                "max_steps": self.execution.max_steps,
                "step_timeout": self.execution.step_timeout,
                "output_dir": self.execution.output_dir,
            },
        }


class FakeLogger:
    """Stand-in for `StructuredLogger` (SPEC-006 § 6.2) that records every call."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str, str, dict[str, Any]]] = []

    def log(self, level: str, component: str, event: str, **kw: Any) -> None:
        self.records.append((level, component, event, kw))

    def debug(self, component: str, event: str, **kw: Any) -> None:
        self.log("DEBUG", component, event, **kw)

    def info(self, component: str, event: str, **kw: Any) -> None:
        self.log("INFO", component, event, **kw)

    def warning(self, component: str, event: str, **kw: Any) -> None:
        self.log("WARNING", component, event, **kw)

    def error(self, component: str, event: str, **kw: Any) -> None:
        self.log("ERROR", component, event, **kw)

    def child(self, component: str, **bound: Any) -> FakeLogger:
        clone = FakeLogger()
        clone.records = self.records
        return clone

    def events(self) -> list[str]:
        """Event names in emission order."""
        return [record[2] for record in self.records]

    def levels(self) -> list[str]:
        """Levels in emission order."""
        return [record[0] for record in self.records]

    def fields_of(self, event: str) -> list[dict[str, Any]]:
        """Field mappings recorded for *event*, in emission order."""
        return [record[3] for record in self.records if record[2] == event]


class FakeClock:
    """Deterministic clock: every read advances by a fixed step (SPEC-000 § 5.5).

    ``now()`` returns datetimes and ``monotonic()`` returns seconds, so a step's
    wall-clock duration and the SPEC-003 § 3 step-8 timeout guard can both be
    exercised without ever reading the real clock.
    """

    def __init__(
        self,
        start: datetime | None = None,
        *,
        step_seconds: float = 1.0,
        readings: Sequence[float] | None = None,
    ) -> None:
        self.start = start or datetime(2026, 9, 14, 12, 0, 0)
        self.step_seconds = step_seconds
        self._readings = list(readings) if readings is not None else None
        self._ticks = 0

    def now(self) -> datetime:
        """Return the current fake timestamp, then advance."""
        elapsed = self._advance()
        return self.start + timedelta(seconds=elapsed)

    def monotonic(self) -> float:
        """Return the current fake monotonic reading, then advance."""
        return self._advance()

    def _advance(self) -> float:
        if self._readings is not None:
            value = self._readings[min(self._ticks, len(self._readings) - 1)]
        else:
            value = self._ticks * self.step_seconds
        self._ticks += 1
        return value

    @property
    def ticks(self) -> int:
        """How many times the clock was read."""
        return self._ticks


class FakeSleeper:
    """Records backoff delays instead of sleeping (SPEC-003 § 5, injectable `sleep`)."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        """Record *seconds* and return immediately."""
        self.delays.append(seconds)


class FakeTool:
    """Spec-shaped stand-in for `BaseTool` (SPEC-002 § 1).

    Honors R1 (``execute`` never raises — a queued exception becomes a failure
    result), R2 (``validate_input`` runs first), R4 (every result carries
    ``tool_name`` and ``duration_ms``) and R8 (``cleanup`` is idempotent and safe
    before any execution). Set ``raise_on_execute`` to model a *defective* tool
    that violates R1, which the orchestrator must still survive.
    """

    def __init__(
        self,
        name: str = "fake_tool",
        description: str = "A fake tool for deterministic tests.",
        capabilities: Sequence[str] = (),
        *,
        results: Sequence[ToolResultLike | BaseException] | None = None,
        output: Any = "fake output",
        success: bool = True,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
        valid: bool = True,
        validation_message: str = "",
        required_keys: Sequence[str] = (),
        raise_on_execute: BaseException | None = None,
        duration_ms: int = 5,
    ) -> None:
        self._name = name
        self._description = description
        self._capabilities = list(capabilities)
        self._results: list[ToolResultLike | BaseException] = list(results or [])
        self._output = output
        self._success = success
        self._error = error
        self._metadata = dict(metadata or {})
        self._valid = valid
        self._validation_message = validation_message
        self._required_keys = list(required_keys)
        self._raise_on_execute = raise_on_execute
        self._duration_ms = duration_ms
        self.executions: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.validations: list[dict[str, Any]] = []
        self.cleanup_calls = 0

    @property
    def name(self) -> str:
        """Tool name (SPEC-002 § 1, R6)."""
        return self._name

    @property
    def description(self) -> str:
        """LLM-facing description (SPEC-002 § 1, R7)."""
        return self._description

    @property
    def capabilities(self) -> list[str]:
        """Capability tags (SPEC-002 § 1)."""
        return self._capabilities

    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str]:
        """Validate required keys, then the scripted verdict (SPEC-002 § 1, R2)."""
        self.validations.append(input_data)
        missing = [key for key in self._required_keys if key not in input_data]
        if missing:
            return False, f"missing required keys: {', '.join(missing)}"
        return self._valid, self._validation_message

    def execute(
        self, input_data: dict[str, Any], context: dict[str, Any]
    ) -> ToolResultLike:
        """Return the next scripted result (SPEC-002 § 1, R1/R4)."""
        self.executions.append((input_data, context))
        if self._raise_on_execute is not None:
            raise self._raise_on_execute
        if self._results:
            queued = self._results.pop(0)
            if isinstance(queued, BaseException):
                # R1: a real tool catches its own exceptions and returns a result.
                return ToolResult(
                    success=False,
                    error=f"{type(queued).__name__}: {queued}",
                    metadata=self._result_metadata(retryable=False),
                )
            return queued
        return ToolResult(
            success=self._success,
            output=self._output if self._success else None,
            error=self._error,
            metadata=self._result_metadata(),
        )

    def _result_metadata(self, retryable: bool | None = None) -> dict[str, Any]:
        metadata = {"tool_name": self._name, "duration_ms": self._duration_ms}
        metadata.update(self._metadata)
        if retryable is not None:
            metadata["retryable"] = retryable
        return metadata

    def cleanup(self) -> None:
        """Record the call; idempotent and safe before any execution (R8)."""
        self.cleanup_calls += 1


class FailingTool(FakeTool):
    """A tool that always fails, with a configurable transient/permanent verdict."""

    def __init__(
        self,
        name: str = "failing_tool",
        error: str = "tool failed",
        *,
        retryable: bool = True,
        capabilities: Sequence[str] = (),
    ) -> None:
        super().__init__(
            name,
            f"A tool that always fails ({error}).",
            capabilities,
            success=False,
            error=error,
            metadata={"retryable": retryable},
        )


class CountingTool(FakeTool):
    """A tool that fails ``failures`` times and then succeeds (retry/Level-1 tests)."""

    def __init__(
        self,
        name: str = "counting_tool",
        *,
        failures: int = 1,
        output: Any = "recovered output",
        error: str = "transient failure",
        retryable: bool = True,
        capabilities: Sequence[str] = (),
    ) -> None:
        queued: list[ToolResultLike] = [
            ToolResult(
                success=False,
                error=error,
                metadata={
                    "tool_name": name,
                    "duration_ms": 1,
                    "retryable": retryable,
                },
            )
            for _ in range(failures)
        ]
        super().__init__(
            name,
            f"A tool that fails {failures} time(s) then succeeds.",
            capabilities,
            results=queued,
            output=output,
        )
        self.failures_before_success = failures

    @property
    def call_count(self) -> int:
        """How many times `execute` ran."""
        return len(self.executions)


class FakeRegistry:
    """Dict-backed stand-in for `ToolRegistry` (SPEC-002 § 2, rules G1-G5)."""

    def __init__(self, tools: Sequence[FakeTool] | None = None) -> None:
        self._tools: dict[str, FakeTool] = {}
        self.overwritten: list[str] = []
        for tool in tools or ():
            self.register(tool)

    def register(self, tool: Any) -> None:
        """Register *tool*, overwriting an existing name and recording it (G1, G2).

        SPEC-002 G2 says a re-registration "overwrites and logs a WARNING", but
        SPEC-006 § 6.1 defines no tool-registration event and agent.md § 5 forbids
        inventing one — so the double records the overwrite for assertions instead.
        """
        if not isinstance(tool, FakeTool):
            raise TypeError(f"register() expects a BaseTool, got {type(tool).__name__}")
        if tool.name in self._tools:
            self.overwritten.append(tool.name)
        self._tools[tool.name] = tool

    def get(self, name: str) -> FakeTool | None:
        """Return the tool registered under *name*, or ``None``."""
        return self._tools.get(name)

    def find_by_capability(self, capability: str) -> list[FakeTool]:
        """Return every tool declaring *capability*, in insertion order."""
        return [
            tool for tool in self._tools.values() if capability in tool.capabilities
        ]

    def list_tools(self) -> list[dict[str, Any]]:
        """Return descriptors in insertion order so prompts are reproducible (G3)."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "capabilities": list(tool.capabilities),
            }
            for tool in self._tools.values()
        ]

    def deregister(self, name: str) -> None:
        """Remove *name*; unknown names are a no-op (G5)."""
        self._tools.pop(name, None)

    def names(self) -> list[str]:
        """Return registered names, sorted (SPEC-002 § 2)."""
        return sorted(self._tools)


class FakeStore:
    """Stand-in for the unspecified `ContextStore` (SCR-P3-5 interim contract)."""

    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self._context: dict[str, Any] = dict(initial or {})
        self.updates: list[dict[str, Any]] = []

    def snapshot(self) -> dict[str, Any]:
        """Return a deep copy of the seeded context, so callers cannot mutate it."""
        return copy.deepcopy(self._context)

    def update(self, context: dict[str, Any]) -> None:
        """Persist a deep copy of the final context and record the call."""
        self._context = copy.deepcopy(context)
        self.updates.append(copy.deepcopy(self._context))


class FakePlanner:
    """Stand-in for `Planner` (SPEC-004 § 2): scripted selection/re-planning."""

    def __init__(
        self,
        *,
        selected_tool: str | None = None,
        selections: Sequence[str | None] | None = None,
        replacement_steps: Sequence[StepLike] | None = None,
        replacement_script: Sequence[Sequence[StepLike]] | None = None,
    ) -> None:
        self.selected_tool = selected_tool
        self.selections: list[str | None] = list(selections) if selections else []
        self.replacement_steps: list[StepLike] = list(replacement_steps or [])
        self.replacement_script: list[list[StepLike]] = [
            list(steps) for steps in (replacement_script or [])
        ]
        self.plan_calls: list[dict[str, Any]] = []
        self.replan_calls: list[dict[str, Any]] = []
        self.select_calls: list[dict[str, Any]] = []

    def plan(
        self,
        prompt: str,
        available_tools: list[dict[str, Any]],
        *,
        context: dict[str, Any] | None = None,
    ) -> PlanLike:
        """Return a single-step plan; records the call."""
        self.plan_calls.append(
            {"prompt": prompt, "available_tools": available_tools, "context": context}
        )
        models = SpecModels()
        return models.plan(
            original_prompt=prompt,
            steps=[models.step(id="step_0", description=prompt, tool_hint="fake_tool")],
        )

    def replan_step(
        self,
        step: StepLike,
        error: str,
        context: dict[str, Any],
        available_tools: list[dict[str, Any]] | None = None,
    ) -> list[StepLike]:
        """Return the next scripted replacement list; records the call."""
        self.replan_calls.append(
            {
                "step": step,
                "error": error,
                "context": context,
                "available_tools": available_tools,
            }
        )
        if self.replacement_script:
            return self.replacement_script.pop(0)
        return list(self.replacement_steps)

    def select_tool(
        self, step: StepLike, available_tools: list[dict[str, Any]]
    ) -> str | None:
        """Return the next scripted selection; records the call."""
        self.select_calls.append({"step": step, "available_tools": available_tools})
        if self.selections:
            return self.selections.pop(0)
        return self.selected_tool


def _signature_parameters(func: Any) -> list[tuple[str, str, Any]]:
    """Return (name, kind, default) triples so signatures can be pinned exactly."""
    return [
        (param.name, param.kind.name, param.default)
        for param in inspect.signature(func).parameters.values()
    ]


class TestBaseToolContract:
    """SPEC-000 § 5.4 contract test: the tool double matches SPEC-002 § 1."""

    def test_name_description_and_capabilities_are_properties(self) -> None:
        for attribute in ("name", "description", "capabilities"):
            assert isinstance(inspect.getattr_static(FakeTool, attribute), property), (
                attribute
            )

    def test_execute_takes_input_data_then_context_positionally(self) -> None:
        assert _signature_parameters(FakeTool.execute) == [
            ("self", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("input_data", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("context", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
        ]

    def test_validate_input_returns_a_verdict_message_pair(self) -> None:
        tool = FakeTool()
        assert tool.validate_input({}) == (True, "")
        rejected = FakeTool(valid=False, validation_message="nope")
        assert rejected.validate_input({}) == (False, "nope")

    def test_cleanup_is_a_no_op_that_is_safe_before_any_execution(self) -> None:
        tool = FakeTool()
        tool.cleanup()
        tool.cleanup()
        assert tool.cleanup_calls == 2

    def test_required_keys_are_enforced_by_validate_input(self) -> None:
        tool = FakeTool(required_keys=["query"])
        assert tool.validate_input({})[0] is False
        assert "query" in tool.validate_input({})[1]
        assert tool.validate_input({"query": "x"})[0] is True

    def test_execute_never_raises_for_a_queued_exception_rule_r1(self) -> None:
        tool = FakeTool(results=[RuntimeError("boom")])
        result = tool.execute({}, {})
        assert result.success is False
        assert "RuntimeError: boom" in (result.error or "")

    def test_every_result_carries_tool_name_and_duration_ms_rule_r4(self) -> None:
        result = FakeTool(name="web_search").execute({}, {})
        assert result.metadata["tool_name"] == "web_search"
        assert isinstance(result.metadata["duration_ms"], int)

    def test_execute_receives_the_prepared_input_and_context_untouched_rule_r3(
        self,
    ) -> None:
        tool = FakeTool()
        context = {"variables": {"a": 1}}
        tool.execute({"q": "x"}, context)
        assert tool.executions == [({"q": "x"}, {"variables": {"a": 1}})]
        assert context == {"variables": {"a": 1}}  # tools never mutate context

    def test_a_tool_that_violates_r1_still_raises_so_the_orchestrator_can_be_tested(
        self,
    ) -> None:
        tool = FakeTool(raise_on_execute=RuntimeError("defective tool"))
        with pytest.raises(RuntimeError, match="defective tool"):
            tool.execute({}, {})

    def test_scripted_results_are_consumed_in_order_then_the_default_is_used(
        self,
    ) -> None:
        tool = FakeTool(
            results=[ToolResult(success=False, error="first")],
            output="second",
        )
        assert tool.execute({}, {}).success is False
        assert tool.execute({}, {}).output == "second"

    def test_a_failing_tool_reports_its_retryable_verdict(self) -> None:
        assert FailingTool(retryable=True).execute({}, {}).metadata["retryable"] is True
        assert (
            FailingTool(retryable=False).execute({}, {}).metadata["retryable"] is False
        )

    def test_a_counting_tool_fails_n_times_then_succeeds(self) -> None:
        tool = CountingTool(failures=2)
        assert tool.execute({}, {}).success is False
        assert tool.execute({}, {}).success is False
        assert tool.execute({}, {}).success is True
        assert tool.call_count == 3


class TestToolRegistryContract:
    """SPEC-000 § 5.4 contract test: the registry double matches SPEC-002 § 2."""

    def test_it_exposes_exactly_the_six_spec_methods(self) -> None:
        expected = {
            "register",
            "get",
            "find_by_capability",
            "list_tools",
            "deregister",
            "names",
        }
        assert expected <= set(dir(FakeRegistry))
        for name in expected:
            assert callable(getattr(FakeRegistry, name)), name

    def test_get_signature_is_name_in_tool_out(self) -> None:
        assert _signature_parameters(FakeRegistry.get) == [
            ("self", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("name", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
        ]

    def test_register_rejects_a_non_tool_with_type_error_rule_g1(self) -> None:
        with pytest.raises(TypeError):
            FakeRegistry().register("not a tool")

    def test_re_registering_a_name_overwrites_it_rule_g2(self) -> None:
        registry = FakeRegistry()
        registry.register(FakeTool(name="t", output="first"))
        registry.register(FakeTool(name="t", output="second"))
        tool = registry.get("t")
        assert tool is not None
        assert tool.execute({}, {}).output == "second"

    def test_list_tools_preserves_insertion_order_rule_g3(self) -> None:
        registry = FakeRegistry(
            [FakeTool(name="zeta"), FakeTool(name="alpha"), FakeTool(name="mid")]
        )
        assert [entry["name"] for entry in registry.list_tools()] == [
            "zeta",
            "alpha",
            "mid",
        ]

    def test_list_tools_entries_carry_the_three_spec_keys(self) -> None:
        entry = FakeRegistry([FakeTool(name="t", capabilities=["a"])]).list_tools()[0]
        assert set(entry) == {"name", "description", "capabilities"}
        assert entry["capabilities"] == ["a"]

    def test_get_of_an_unknown_name_returns_none(self) -> None:
        assert FakeRegistry().get("nope") is None

    def test_deregister_of_an_unknown_name_is_a_no_op_rule_g5(self) -> None:
        registry = FakeRegistry([FakeTool(name="t")])
        registry.deregister("nope")
        assert registry.names() == ["t"]

    def test_deregister_removes_a_known_tool(self) -> None:
        registry = FakeRegistry([FakeTool(name="t")])
        registry.deregister("t")
        assert registry.get("t") is None

    def test_names_is_sorted_for_deterministic_prompts(self) -> None:
        registry = FakeRegistry([FakeTool(name="zeta"), FakeTool(name="alpha")])
        assert registry.names() == ["alpha", "zeta"]

    def test_find_by_capability_returns_matches_in_insertion_order(self) -> None:
        registry = FakeRegistry(
            [
                FakeTool(name="a", capabilities=["search"]),
                FakeTool(name="b", capabilities=["scrape"]),
                FakeTool(name="c", capabilities=["search"]),
            ]
        )
        assert [t.name for t in registry.find_by_capability("search")] == ["a", "c"]
        assert registry.find_by_capability("nope") == []


class TestPlannerContract:
    """SPEC-000 § 5.4 contract test: the planner double matches SPEC-004 § 2."""

    def test_plan_takes_prompt_and_available_tools_then_keyword_context(self) -> None:
        assert _signature_parameters(FakePlanner.plan) == [
            ("self", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("prompt", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("available_tools", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("context", "KEYWORD_ONLY", None),
        ]

    def test_replan_step_takes_step_error_context_and_optional_available_tools(
        self,
    ) -> None:
        # SPEC-004 § 2 writes replan_step with no `*` separator, so available_tools is
        # POSITIONAL_OR_KEYWORD — unlike plan()'s keyword-only `context`. Pinned here
        # because the real Planner must accept it positionally too.
        assert _signature_parameters(FakePlanner.replan_step) == [
            ("self", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("step", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("error", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("context", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("available_tools", "POSITIONAL_OR_KEYWORD", None),
        ]

    def test_select_tool_takes_step_and_available_tools(self) -> None:
        assert _signature_parameters(FakePlanner.select_tool) == [
            ("self", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("step", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("available_tools", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
        ]

    def test_plan_returns_a_plan_and_replan_returns_a_step_list(self) -> None:
        planner = FakePlanner(
            replacement_steps=[Step(id="step_0r1", description="alt")]
        )
        plan = planner.plan("do it", [])
        assert isinstance(plan, ExecutionPlan)
        assert (
            planner.replan_step(plan.steps[0], "boom", {}) == planner.replacement_steps
        )

    def test_select_tool_returns_a_name_or_none(self) -> None:
        assert (
            FakePlanner(selected_tool="web_search").select_tool(Step(), [])
            == "web_search"
        )
        assert FakePlanner(selected_tool=None).select_tool(Step(), []) is None

    def test_the_replacement_script_is_consumed_in_order(self) -> None:
        first = [Step(id="step_0r1", description="a")]
        second: list[StepLike] = []
        planner = FakePlanner(replacement_script=[first, second])
        assert planner.replan_step(Step(), "e", {}) == first
        assert planner.replan_step(Step(), "e", {}) == second
        assert planner.replan_step(Step(), "e", {}) == []


class TestContextStoreContract:
    """SCR-P3-5: the interim ContextStore contract this plan codes against."""

    def test_snapshot_returns_a_copy_so_the_store_cannot_be_mutated_by_reference(
        self,
    ) -> None:
        store = FakeStore({"variables": {"topic": "GPT-4"}})
        snapshot = store.snapshot()
        snapshot["variables"]["topic"] = "changed"
        assert store.snapshot() == {"variables": {"topic": "GPT-4"}}

    def test_update_persists_the_final_context(self) -> None:
        store = FakeStore()
        store.update({"files_created": ["./output/a.pdf"]})
        assert store.snapshot() == {"files_created": ["./output/a.pdf"]}
        assert len(store.updates) == 1

    def test_an_empty_store_seeds_an_empty_context(self) -> None:
        assert FakeStore().snapshot() == {}

    def test_update_takes_a_deep_copy_so_later_mutation_does_not_rewrite_history(
        self,
    ) -> None:
        store = FakeStore()
        context: dict[str, Any] = {"files_created": []}
        store.update(context)
        context["files_created"].append("./output/late.pdf")
        assert store.snapshot() == {"files_created": []}
        assert store.updates == [{"files_created": []}]


class TestClockAndSleeperDoubles:
    """SPEC-000 § 5.5 / SPEC-003 § 5: determinism by injection, never real time."""

    def test_the_clock_advances_by_a_fixed_step_on_every_read(self) -> None:
        clock = FakeClock(step_seconds=2.0)
        assert clock.monotonic() == 0.0
        assert clock.monotonic() == 2.0
        assert clock.monotonic() == 4.0

    def test_the_clock_returns_datetimes_from_a_frozen_start(self) -> None:
        clock = FakeClock(datetime(2026, 9, 14, 12, 0, 0), step_seconds=1.5)
        assert clock.now() == datetime(2026, 9, 14, 12, 0, 0)
        assert clock.now() == datetime(2026, 9, 14, 12, 0, 1, 500000)

    def test_an_explicit_reading_sequence_is_replayed_and_then_held(self) -> None:
        clock = FakeClock(readings=[0.0, 200.0])
        assert [clock.monotonic() for _ in range(3)] == [0.0, 200.0, 200.0]

    def test_the_sleeper_records_delays_without_blocking(self) -> None:
        sleeper = FakeSleeper()
        for delay in (2.0, 4.0, 8.0):
            sleeper(delay)
        assert sleeper.delays == [2.0, 4.0, 8.0]

    def test_the_doubles_never_open_a_socket_or_sleep_for_real(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _refuse(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("a test double touched the network or slept")

        monkeypatch.setattr(socket, "socket", _refuse)
        monkeypatch.setattr(socket, "create_connection", _refuse)
        monkeypatch.setattr(time, "sleep", _refuse)
        counting = CountingTool(failures=1)
        registry = FakeRegistry([counting, FailingTool()])
        sleeper = FakeSleeper()
        assert registry.get("counting_tool") is counting
        counting.execute({}, {})
        sleeper(2.0)
        assert counting.call_count == 1
        assert sleeper.delays == [2.0]


class TestStepAndResultDoubles:
    """The injected model stand-ins behave like the SPEC-001 § 2 data model."""

    def test_a_step_can_be_built_with_the_canonical_planner_id_shape(self) -> None:
        step = Step(id="step_0", description="d", tool_hint="web_search")
        assert step.status is StepStatus.PENDING
        assert step.priority is TaskPriority.HIGH

    def test_a_tool_result_defaults_to_success_with_no_error(self) -> None:
        result = ToolResult(success=True, output="x")
        assert result.error is None
        assert result.metadata == {}

    def test_tool_result_field_order_matches_spec_001_section_2_3(self) -> None:
        assert [f.name for f in fields(ToolResult)] == [
            "success",
            "output",
            "error",
            "metadata",
        ]

    def test_step_like_is_satisfied_by_the_stand_in_step(self) -> None:
        step: StepLike = Step(id="step_0", description="d")
        assert step.depends_on == []

    def test_tool_result_like_is_satisfied_by_the_stand_in_result(self) -> None:
        result: ToolResultLike = ToolResult(success=True)
        assert result.success is True


class TestPlanBuilder:
    """Helper used across the orchestration tests, pinned so it stays trustworthy."""

    def test_a_plan_is_built_with_canonical_ids_and_dependencies(self) -> None:
        models = SpecModels()
        plan = models.plan(
            original_prompt="p",
            steps=[
                models.step(id="step_0", description="a", tool_hint="t"),
                models.step(
                    id="step_1", description="b", tool_hint="t", depends_on=["step_0"]
                ),
            ],
        )
        assert [step.id for step in plan.steps] == ["step_0", "step_1"]
        second = plan.step_by_id("step_1")
        assert second is not None
        assert second.depends_on == ["step_0"]
        assert plan.step_by_id("nope") is None

    def test_the_default_step_priorities_and_statuses_are_the_spec_defaults(
        self,
    ) -> None:
        models = SpecModels()
        step = models.step(id="step_0", description="a")
        assert models.step_status("PENDING") is StepStatus.PENDING
        assert models.task_priority("HIGH") is TaskPriority.HIGH
        assert step.status is StepStatus.PENDING

    def test_execution_hooks_placeholder_names_are_reserved_for_subphase_3_5(
        self,
    ) -> None:
        # ExecutionHooks is production code delivered in 3.2/3.5; this constant keeps
        # the six callback names of SPEC-003 § 2.1 pinned from the double kit onwards.
        assert HOOK_NAMES == (
            "on_plan_start",
            "on_step_start",
            "on_step_complete",
            "on_step_failed",
            "on_recovery",
            "on_plan_complete",
        )
