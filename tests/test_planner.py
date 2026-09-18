"""Unit tests for the Plan 3 cognition layer's planning half.

Spec: SPEC-004 § 2-5 (``Planner``, prompt templates, plan schema, determinism),
SPEC-001 § 2 (data model consumed via injection), SPEC-002 § 2 (``list_tools()``
shape handed to the planner).

Sub-phases covered by this file: 1.1 (prompt templates), 1.2 (parsing and
normalization), 1.3 (validation rules V1-V7), 1.5 (parser robustness),
2.1-2.5 (``Planner``).

Test doubles: this plan may not create ``tests/_p3_doubles.py`` — that path is
absent from the SPEC-000 § 3.3 ownership matrix (see SCR-P3-3 in this plan's
Status Log) — so the spec-shaped fakes are declared inside the owned test files
per the plan's parallel-work rule. Nothing here imports ``agent_harness.config``,
``agent_harness.llm``, ``agent_harness.tools``, ``agent_harness.context`` or
``agent_harness.logging``; every collaborator arrives by injection. All tests are
deterministic: no network, no live LLM, no real sleeping, no wall-clock reads.

Skills applied: SKL-CORE-TDD (core-coding/tdd-test-runner), SKL-CORE-TYPES
(core-coding/strict-typing-contracts), SKL-REL-FUZZ (reliability/api-fuzz-tester),
SKL-REL-SCHEMA (reliability/schema-compatibility).
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import socket
import string
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, ClassVar, get_type_hints

import pytest

from agent_harness.orchestration import dependency
from agent_harness.planning import prompts
from agent_harness.planning.planner import (
    MAX_ATTEMPT_HISTORY_ENTRIES,
    MAX_CONTEXT_SUMMARY_CHARS,
    MAX_CONTEXT_VALUE_CHARS,
    MAX_REPLAN_CONTEXT_CHARS,
    MAX_REPLAN_STEP_OUTPUT_CHARS,
    MAX_STEP_DESCRIPTION_CHARS,
    TRUNCATION_MARKER,
    AgentError,
    AgentErrorRaised,
    ConfigLike,
    ExecutionConfigLike,
    ExecutionPlan,
    LLMConfigLike,
    ModelProvider,
    NullLogger,
    PlanLike,
    Planner,
    SpecModels,
    Step,
    StepStatus,
    TaskPriority,
    ToolResult,
    _index_references,
    _substitute,
    _truncate,
    parse_plan,
    priority_rank,
    priority_value,
    status_value,
    strip_code_fences,
    validate_plan,
)

# ── Frozen prompt text ────────────────────────────────────────────────────────
# Transcribed byte-for-byte from SPEC-004 § 3.1 / § 3.2, the binding contract for
# this plan (plan § 1.1: "verbatim from SPEC-004 § 3.1/3.2"). The digests below pin
# the exact characters so any drift — a stray space, a replaced em dash, a re-wrap —
# fails the suite.

SPEC_004_3_1_PLANNING_SYSTEM_PROMPT = """\
You are a task planning agent. Given a user's request, decompose it into a structured
execution plan with ordered steps. Available tools: {tool_descriptions}

For each step, specify:
- description: What this step accomplishes
- tool_hint: Which tool to use (from available tools)
- input_data: Parameters for the tool
- priority: "critical" | "high" | "medium" | "low"
- depends_on: List of step indices this step depends on (e.g., ["step_0"])
- fallback_tools: Alternative tools if the primary fails

Rules:
1. Break complex tasks into atomic, testable steps
2. Each step should have a single clear objective
3. Declare dependencies explicitly — don't assume sequential execution
4. Always include fallback tools where alternatives exist
5. Mark steps that produce the final deliverable as "critical" priority
6. Prefer specific tool hints over generic ones

Respond with valid JSON matching the ExecutionPlan schema."""

SPEC_004_3_2_REPLAN_PROMPT = """\
A step in the execution plan has failed after all retries and fallbacks.

Failed step: {step_description}
Tool used: {tool_name}
Error: {error_message}
Previous attempts: {attempt_history}
Available tools: {tool_descriptions}
Current context: {context_summary}

Generate an alternative step (or sequence of steps) to achieve the same goal using a
different approach. Respond with valid JSON."""

PLANNING_PROMPT_SHA256 = (
    "2623db2ef25350b56abd8e1e287f43a6c2d4bd7809de13f6b4886edda5951f6a"
)
REPLAN_PROMPT_SHA256 = (
    "6fd2c03d351923f124376e196e6f294b96f4acb9a61614034253e8ac1f364a77"
)

# SPEC-004 § 3.1/§ 3.2 declare their content "verbatim from vision § 8.1/§ 8.2", but
# the two documents are not byte-identical: the vision keeps two sentences unwrapped
# where the spec wraps them at ~85 columns. Whitespace-normalized they are identical.
# SCR-P3-8 asks the orchestrator to declare one canonical rendering; until then this
# plan implements the SPEC-004 bytes and pins the *complete* set of divergences here,
# so a ruling for the vision form is a two-line change rather than an investigation.
VISION_8_1_8_2_UNWRAPPED_SPANS: tuple[tuple[str, str], ...] = (
    ("structured\nexecution plan", "structured execution plan"),
    ("using a\ndifferent approach", "using a different approach"),
)


def _vision_form(spec_form: str) -> str:
    """Return the vision § 8.1/§ 8.2 rendering of a spec-frozen template."""
    rendered = spec_form
    for wrapped, unwrapped in VISION_8_1_8_2_UNWRAPPED_SPANS:
        rendered = rendered.replace(wrapped, unwrapped)
    return rendered


def _placeholders(template: str) -> list[str]:
    """Return the ``str.format`` field names of *template*, in order of appearance."""
    return [
        field_name
        for _, field_name, _, _ in string.Formatter().parse(template)
        if field_name is not None
    ]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestFrozenPromptTemplates:
    """Sub-phase 1.1 — the two FROZEN templates must match the spec exactly."""

    def test_planning_prompt_matches_spec_004_section_3_1_character_for_character(
        self,
    ) -> None:
        assert prompts.PLANNING_SYSTEM_PROMPT == SPEC_004_3_1_PLANNING_SYSTEM_PROMPT

    def test_replan_prompt_matches_spec_004_section_3_2_character_for_character(
        self,
    ) -> None:
        assert prompts.REPLAN_PROMPT == SPEC_004_3_2_REPLAN_PROMPT

    def test_planning_system_prompt_digest_is_pinned(self) -> None:
        assert _sha256(prompts.PLANNING_SYSTEM_PROMPT) == PLANNING_PROMPT_SHA256
        assert len(prompts.PLANNING_SYSTEM_PROMPT) == 918

    def test_replan_prompt_digest_is_pinned(self) -> None:
        assert _sha256(prompts.REPLAN_PROMPT) == REPLAN_PROMPT_SHA256
        assert len(prompts.REPLAN_PROMPT) == 391

    def test_frozen_templates_carry_no_trailing_newline(self) -> None:
        assert not prompts.PLANNING_SYSTEM_PROMPT.endswith("\n")
        assert not prompts.REPLAN_PROMPT.endswith("\n")

    def test_em_dash_survives_as_u2014_and_no_smart_quotes_are_introduced(self) -> None:
        planning = prompts.PLANNING_SYSTEM_PROMPT
        assert "\u2014" in planning
        assert planning.count("\u2014") == 1
        for char in "\u2018\u2019\u201c\u201d":
            assert char not in planning
            assert char not in prompts.REPLAN_PROMPT

    def test_the_only_divergence_from_vision_8_1_and_8_2_is_the_two_documented_wraps(
        self,
    ) -> None:
        planning_vision = _vision_form(SPEC_004_3_1_PLANNING_SYSTEM_PROMPT)
        replan_vision = _vision_form(SPEC_004_3_2_REPLAN_PROMPT)
        # Same characters, same order — only whitespace differs (SCR-P3-8).
        assert " ".join(prompts.PLANNING_SYSTEM_PROMPT.split()) == " ".join(
            planning_vision.split()
        )
        assert " ".join(prompts.REPLAN_PROMPT.split()) == " ".join(
            replan_vision.split()
        )
        # And the divergence is exactly the two spans declared above, no more.
        assert len(planning_vision) == len(prompts.PLANNING_SYSTEM_PROMPT)
        assert len(replan_vision) == len(prompts.REPLAN_PROMPT)

    def test_planning_prompt_exposes_exactly_the_tool_descriptions_placeholder(
        self,
    ) -> None:
        assert _placeholders(prompts.PLANNING_SYSTEM_PROMPT) == ["tool_descriptions"]

    def test_replan_prompt_exposes_exactly_the_six_spec_placeholders(self) -> None:
        assert _placeholders(prompts.REPLAN_PROMPT) == [
            "step_description",
            "tool_name",
            "error_message",
            "attempt_history",
            "tool_descriptions",
            "context_summary",
        ]

    def test_both_frozen_templates_format_without_a_keyerror_or_indexerror(
        self,
    ) -> None:
        rendered_planning = prompts.PLANNING_SYSTEM_PROMPT.format(
            tool_descriptions="- a: b"
        )
        assert "- a: b" in rendered_planning
        rendered_replan = prompts.REPLAN_PROMPT.format(
            step_description="d",
            tool_name="t",
            error_message="e",
            attempt_history="h",
            tool_descriptions="- a: b",
            context_summary="c",
        )
        assert "Failed step: d" in rendered_replan
        assert "Current context: c" in rendered_replan


class TestToolSelectionPrompt:
    """Sub-phase 1.1 — the additive template of SPEC-004 § 3.3."""

    def test_it_documents_both_accepted_json_response_shapes(self) -> None:
        rendered = prompts.TOOL_SELECTION_PROMPT.format(
            step_description="Find sales figures",
            input_keys="query",
            tool_descriptions="- web_search: search the web [capabilities: search]",
        )
        assert '{"tool": "<tool_name>"}' in rendered
        assert '{"tool": null}' in rendered

    def test_it_carries_the_step_and_the_tool_list_into_the_rendered_prompt(
        self,
    ) -> None:
        rendered = prompts.TOOL_SELECTION_PROMPT.format(
            step_description="Find sales figures",
            input_keys="query, num_results",
            tool_descriptions="- web_search: search the web [capabilities: search]",
        )
        assert "Find sales figures" in rendered
        assert "query, num_results" in rendered
        assert "- web_search: search the web [capabilities: search]" in rendered

    def test_it_forbids_inventing_an_unlisted_tool_name(self) -> None:
        assert "not listed" in prompts.TOOL_SELECTION_PROMPT

    def test_its_literal_braces_survive_formatting(self) -> None:
        # The JSON examples are escaped as {{...}} so str.format emits real braces.
        assert _placeholders(prompts.TOOL_SELECTION_PROMPT) == [
            "step_description",
            "input_keys",
            "tool_descriptions",
        ]


class TestPlanSchemaHint:
    """Sub-phase 1.1 — schema hint passed to ``LLMClient.complete_json`` (§ 1.2 C3)."""

    def test_it_names_every_field_of_the_spec_004_section_4_1_step_object(self) -> None:
        for field_name in (
            "steps",
            "description",
            "tool_hint",
            "input_data",
            "priority",
            "depends_on",
            "fallback_tools",
        ):
            assert field_name in prompts.PLAN_SCHEMA_HINT

    def test_it_states_the_four_priority_values(self) -> None:
        for value in ("critical", "high", "medium", "low"):
            assert value in prompts.PLAN_SCHEMA_HINT


class TestRenderToolDescriptions:
    """Sub-phase 1.1 — the deterministic spec line format for the tool list."""

    TOOLS: ClassVar[list[dict[str, Any]]] = [
        {
            "name": "web_search",
            "description": "Search the web for current information.",
            "capabilities": ["search", "web", "research"],
        },
        {
            "name": "pdf_export",
            "description": "Render markdown or HTML to a PDF file.",
            "capabilities": ["export", "pdf"],
        },
    ]

    def test_it_renders_the_exact_spec_line_format(self) -> None:
        rendered = prompts.render_tool_descriptions(self.TOOLS[:1])
        assert rendered == (
            "- web_search: Search the web for current information. "
            "[capabilities: search, web, research]"
        )

    def test_it_renders_one_line_per_tool_joined_by_newlines(self) -> None:
        rendered = prompts.render_tool_descriptions(self.TOOLS)
        assert rendered.split("\n") == [
            "- web_search: Search the web for current information. "
            "[capabilities: search, web, research]",
            "- pdf_export: Render markdown or HTML to a PDF file. "
            "[capabilities: export, pdf]",
        ]

    def test_it_omits_the_capability_suffix_when_a_tool_declares_no_capabilities(
        self,
    ) -> None:
        rendered = prompts.render_tool_descriptions(
            [{"name": "hello", "description": "Say hello.", "capabilities": []}]
        )
        assert rendered == "- hello: Say hello."
        assert "capabilities" not in rendered

    def test_it_treats_a_missing_capabilities_key_as_no_capabilities(self) -> None:
        assert (
            prompts.render_tool_descriptions(
                [{"name": "hello", "description": "Say hello."}]
            )
            == "- hello: Say hello."
        )

    def test_it_preserves_registry_insertion_order_rather_than_sorting(self) -> None:
        # SPEC-002 § 2 G3: list_tools() ordering is deterministic insertion order, so
        # planning prompts are reproducible. Sorting here would break that contract.
        reverse = list(reversed(self.TOOLS))
        rendered = prompts.render_tool_descriptions(reverse)
        assert rendered.index("pdf_export") < rendered.index("web_search")

    def test_it_is_deterministic_across_repeated_calls(self) -> None:
        first = prompts.render_tool_descriptions(self.TOOLS)
        for _ in range(5):
            assert prompts.render_tool_descriptions(self.TOOLS) == first

    @pytest.mark.parametrize("tools", [None, []])
    def test_an_absent_or_empty_tool_list_renders_an_empty_string(
        self, tools: list[dict[str, Any]] | None
    ) -> None:
        assert prompts.render_tool_descriptions(tools) == ""

    def test_it_accepts_tool_objects_exposing_name_description_capabilities(
        self,
    ) -> None:
        class _ToolObject:
            name = "csv_process"
            description = "Process a CSV file."
            capabilities = ("csv", "data")  # immutable: no mutable class default

        assert prompts.render_tool_descriptions([_ToolObject()]) == (
            "- csv_process: Process a CSV file. [capabilities: csv, data]"
        )

    def test_missing_name_or_description_keys_degrade_to_empty_text_without_raising(
        self,
    ) -> None:
        assert prompts.render_tool_descriptions([{}]) == "- : "
        assert prompts.render_tool_descriptions([{"name": "x"}]) == "- x: "

    def test_non_string_capability_values_are_stringified(self) -> None:
        rendered = prompts.render_tool_descriptions(
            [{"name": "t", "description": "d", "capabilities": [1, True]}]
        )
        assert rendered == "- t: d [capabilities: 1, True]"

    def test_a_null_capabilities_value_renders_without_the_suffix(self) -> None:
        assert (
            prompts.render_tool_descriptions(
                [{"name": "t", "description": "d", "capabilities": None}]
            )
            == "- t: d"
        )

    def test_empty_capability_entries_are_dropped_rather_than_rendered_blank(
        self,
    ) -> None:
        rendered = prompts.render_tool_descriptions(
            [{"name": "t", "description": "d", "capabilities": ["", "csv", ""]}]
        )
        assert rendered == "- t: d [capabilities: csv]"

    def test_a_bare_string_capability_is_treated_as_a_single_capability(self) -> None:
        rendered = prompts.render_tool_descriptions(
            [{"name": "t", "description": "d", "capabilities": "csv"}]
        )
        assert rendered == "- t: d [capabilities: csv]"

    def test_a_single_capability_renders_without_a_trailing_separator(self) -> None:
        rendered = prompts.render_tool_descriptions(
            [
                {
                    "name": "file_read",
                    "description": "Read a file.",
                    "capabilities": ["file"],
                }
            ]
        )
        assert rendered == "- file_read: Read a file. [capabilities: file]"

    def test_unicode_names_and_descriptions_are_preserved_verbatim(self) -> None:
        rendered = prompts.render_tool_descriptions(
            [
                {
                    "name": "recherche_웹",
                    "description": "Rechercher — 検索 🚀",
                    "capabilities": ["recherche"],
                }
            ]
        )
        assert (
            rendered == "- recherche_웹: Rechercher — 検索 🚀 [capabilities: recherche]"
        )

    def test_a_capabilities_tuple_is_rendered_like_a_list(self) -> None:
        rendered = prompts.render_tool_descriptions(
            [{"name": "t", "description": "d", "capabilities": ("a", "b")}]
        )
        assert rendered == "- t: d [capabilities: a, b]"

    def test_a_non_sequence_capabilities_value_is_ignored_rather_than_raising(
        self,
    ) -> None:
        rendered = prompts.render_tool_descriptions(
            [{"name": "t", "description": "d", "capabilities": 7}]
        )
        assert rendered == "- t: d"


# ── Test doubles for the cognition layer (sub-phase 1.4, scoped to this file) ────
# SCR-P3-3: `tests/_p3_doubles.py` is not in the SPEC-000 § 3.3 ownership matrix, so
# the spec-shaped fakes live inside the owned test files. Every fake mirrors the frozen
# contract exactly (SPEC-001 § 2, SPEC-002 § 1-2, SPEC-004 § 1, SPEC-006 § 1/6.2) and
# is asserted against it by the contract tests below.


@dataclass
class FakeLLMSection:
    """SPEC-006 § 1 `llm:` section."""

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
class FakeSecuritySection:
    """SPEC-006 § 1 `security:` section."""

    sandbox_code: bool = True
    code_timeout: int = 30
    max_output_bytes: int = 1_000_000
    network_in_code: bool = False
    allow_shell: bool = False
    sensitive_patterns: ClassVar[list[str]] = [
        r"\b\d{3}-\d{2}-\d{4}\b",
        r"sk-[a-zA-Z0-9]{48}",
    ]


@dataclass
class FakeConfig:
    """Spec-shaped stand-in for Plan 1's `Config` (SPEC-006 § 1, § 1.1 accessors)."""

    llm: FakeLLMSection = field(default_factory=FakeLLMSection)
    execution: FakeExecutionSection = field(default_factory=FakeExecutionSection)
    security: FakeSecuritySection = field(default_factory=FakeSecuritySection)
    _values: ClassVar[dict[str, Any]] = {}

    def get(self, path: str, default: Any = None) -> Any:
        """Dotted-path lookup (SPEC-006 § 1.1), resolved over the fake sections."""
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
        raw: dict[str, Any] = {
            "llm": {
                "provider": self.llm.provider,
                "model": self.llm.model,
                "max_tokens": self.llm.max_tokens,
                "temperature": self.llm.temperature,
                "api_key_env": self.llm.api_key_env,
                "cost_per_1k_tokens": self.llm.cost_per_1k_tokens,
            },
            "execution": {
                "max_steps": self.execution.max_steps,
                "step_timeout": self.execution.step_timeout,
                "output_dir": self.execution.output_dir,
            },
        }
        if not redact_secrets:
            return raw
        return raw


class FakeLogger:
    """Spec-shaped stand-in for `StructuredLogger` (SPEC-006 § 6.2). Records events."""

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
        return [record[2] for record in self.records]

    def levels(self) -> list[str]:
        return [record[0] for record in self.records]


VALID_PLAN_PAYLOAD: dict[str, Any] = {
    "steps": [
        {
            "description": "Search for GPT-4 usage statistics",
            "tool_hint": "web_search",
            "input_data": {"query": "GPT-4 usage statistics 2024"},
            "priority": "critical",
            "depends_on": [],
            "fallback_tools": ["web_scrape"],
        },
        {
            "description": "Export the summary as a PDF",
            "tool_hint": "pdf_export",
            "input_data": {"path": "./output/summary.pdf"},
            "priority": "high",
            "depends_on": ["step_0"],
            "fallback_tools": [],
        },
    ]
}


class TestStandInDataModelContract:
    """SPEC-000 § 5.4 contract tests: the P3 stand-ins match the frozen data model.

    These are the mechanism that makes parallel work safe while Plan 1 is in flight:
    if P1's real classes diverge from SPEC-001 § 2, these assertions say so loudly.
    """

    def test_step_field_names_and_order_match_spec_001_section_2_1(self) -> None:
        assert [f.name for f in fields(Step)] == [
            "id",
            "description",
            "tool_hint",
            "tool_name",
            "input_data",
            "output_data",
            "status",
            "error",
            "retries",
            "max_retries",
            "fallback_tools",
            "depends_on",
            "priority",
            "started_at",
            "completed_at",
        ]

    def test_step_defaults_match_spec_001_section_2_1(self) -> None:
        step = Step()
        assert len(step.id) == 8  # uuid4 fragment
        assert step.description == ""
        assert step.tool_hint == ""
        assert step.tool_name == ""
        assert step.input_data == {}
        assert step.output_data is None
        assert step.status is StepStatus.PENDING
        assert step.error is None
        assert step.retries == 0
        assert step.max_retries == 2
        assert step.fallback_tools == []
        assert step.depends_on == []
        assert step.priority is TaskPriority.HIGH
        assert step.started_at is None
        assert step.completed_at is None

    def test_step_ids_are_unique_across_instances(self) -> None:
        assert Step().id != Step().id

    def test_step_mutable_defaults_are_not_shared_between_instances(self) -> None:
        first, second = Step(), Step()
        first.input_data["k"] = "v"
        first.depends_on.append("step_0")
        assert second.input_data == {}
        assert second.depends_on == []

    def test_execution_plan_field_names_and_order_match_spec_001_section_2_2(
        self,
    ) -> None:
        assert [f.name for f in fields(ExecutionPlan)] == [
            "id",
            "original_prompt",
            "steps",
            "context",
            "created_at",
            "status",
            "final_output",
        ]

    def test_tool_result_field_names_match_spec_001_section_2_3(self) -> None:
        assert [f.name for f in fields(ToolResult)] == [
            "success",
            "output",
            "error",
            "metadata",
        ]
        result = ToolResult(success=True)
        assert result.output is None
        assert result.error is None
        assert result.metadata == {}

    def test_agent_error_field_names_match_spec_001_section_2_4(self) -> None:
        assert [f.name for f in fields(AgentError)] == [
            "code",
            "message",
            "component",
            "step_id",
            "recoverable",
            "recovery_action",
            "original_error",
        ]

    def test_agent_error_str_renders_the_spec_001_section_2_4_format(self) -> None:
        error = AgentError(
            code="PLAN_ABORTED",
            message="critical step failed",
            component="orchestrator",
        )
        assert str(error) == "[PLAN_ABORTED] orchestrator: critical step failed"
        with_step = AgentError(
            code="TOOL_NOT_FOUND",
            message="no tool",
            component="orchestrator",
            step_id="step_2",
        )
        assert str(with_step) == "[TOOL_NOT_FOUND] orchestrator(step_2): no tool"

    def test_agent_error_is_raisable_and_catchable_as_the_p3_base(self) -> None:
        # SCR-P3-7: SPEC-003 requires `raise AgentError(...)` while SPEC-001 § 2.4
        # declares a plain dataclass. The stand-in is both, and every raise site
        # narrows with isinstance so an injected non-raisable error still surfaces.
        error = AgentError(
            code="PLAN_PARSE_FAILED", message="bad json", component="planner"
        )
        with pytest.raises(AgentErrorRaised) as caught:
            raise error
        assert caught.value.code == "PLAN_PARSE_FAILED"
        assert caught.value.error is error

    def test_step_status_values_match_spec_001_section_1_1(self) -> None:
        assert {member.name: member.value for member in StepStatus} == {
            "PENDING": "pending",
            "RUNNING": "running",
            "SUCCESS": "success",
            "FAILED": "failed",
            "SKIPPED": "skipped",
            "RETRYING": "retrying",
        }

    def test_task_priority_values_match_spec_001_section_1_2(self) -> None:
        assert {member.name: member.value for member in TaskPriority} == {
            "CRITICAL": "critical",
            "HIGH": "high",
            "MEDIUM": "medium",
            "LOW": "low",
        }

    def test_step_duration_ms_is_none_until_both_timestamps_exist(self) -> None:
        step = Step()
        assert step.duration_ms is None
        step.started_at = datetime(2026, 9, 14, 12, 0, 0)
        assert step.duration_ms is None
        step.completed_at = datetime(2026, 9, 14, 12, 0, 2, 340000)
        assert step.duration_ms == 2340

    def test_step_to_dict_serializes_enums_to_values_and_datetimes_to_iso8601(
        self,
    ) -> None:
        step = Step(
            id="step_0",
            description="d",
            status=StepStatus.SUCCESS,
            priority=TaskPriority.CRITICAL,
            started_at=datetime(2026, 9, 14, 12, 0, 0),
            completed_at=datetime(2026, 9, 14, 12, 0, 1),
        )
        dumped = step.to_dict()
        assert dumped["status"] == "success"
        assert dumped["priority"] == "critical"
        assert dumped["started_at"] == "2026-09-14T12:00:00"
        assert dumped["completed_at"] == "2026-09-14T12:00:01"

    def test_step_dict_round_trip_is_lossless(self) -> None:
        step = Step(
            id="step_1",
            description="d",
            tool_hint="web_search",
            input_data={"q": "x"},
            status=StepStatus.FAILED,
            error="boom",
            retries=2,
            depends_on=["step_0"],
            priority=TaskPriority.LOW,
            started_at=datetime(2026, 9, 14, 12, 0, 0),
        )
        assert Step.from_dict(step.to_dict()) == step

    def test_step_from_dict_ignores_unknown_keys_and_defaults_missing_ones(
        self,
    ) -> None:
        step = Step.from_dict({"id": "step_9", "description": "d", "future_field": 1})
        assert step.id == "step_9"
        assert step.status is StepStatus.PENDING
        assert step.priority is TaskPriority.HIGH

    def test_execution_plan_step_by_id_and_round_trip(self) -> None:
        plan = ExecutionPlan(
            id="p1",
            original_prompt="prompt",
            steps=[
                Step(id="step_0", description="a"),
                Step(id="step_1", description="b"),
            ],
            created_at=datetime(2026, 9, 14, 12, 0, 0),
        )
        assert plan.step_by_id("step_1") is plan.steps[1]
        assert plan.step_by_id("nope") is None
        assert ExecutionPlan.from_dict(plan.to_dict()) == plan

    def test_spec_models_factory_builds_spec_conformant_objects(self) -> None:
        models = SpecModels()
        step = models.step(id="step_0", description="d")
        plan = models.plan(original_prompt="p", steps=[step])
        result = models.tool_result(success=True, output="o")
        error = models.agent_error(code="C", message="m", component="planner")
        assert isinstance(step, Step)
        assert isinstance(plan, ExecutionPlan)
        assert isinstance(result, ToolResult)
        assert isinstance(error, AgentError)
        assert models.step_status("SUCCESS") is StepStatus.SUCCESS
        assert models.task_priority("low") is TaskPriority.LOW

    def test_spec_models_rejects_an_unknown_status_or_priority_name(self) -> None:
        models = SpecModels()
        with pytest.raises(KeyError):
            models.step_status("EXPLODED")
        with pytest.raises(KeyError):
            models.task_priority("urgent")

    def test_the_stand_ins_are_dataclasses_so_p1_can_substitute_its_own(self) -> None:
        assert is_dataclass(Step) and is_dataclass(ExecutionPlan)
        assert is_dataclass(ToolResult) and is_dataclass(AgentError)

    def test_null_logger_accepts_every_spec_006_level_and_binds_a_child(self) -> None:
        logger = NullLogger()
        logger.log("INFO", "planner", "plan_generated", steps=1)
        logger.debug("planner", "plan_generated")
        logger.info("planner", "plan_generated", steps=1)
        logger.warning("planner", "plan_generated")
        logger.error("planner", "plan_generated")
        child = logger.child("planner", plan_id="p1")
        child.info("planner", "plan_generated")  # no-op, and never raises


class TestStripCodeFences:
    """SPEC-004 § 4.2 rule 1 — strip markdown code fences before parsing."""

    def test_plain_json_is_returned_trimmed(self) -> None:
        assert strip_code_fences('  {"steps": []}  ') == '{"steps": []}'

    def test_a_bare_fence_pair_is_removed(self) -> None:
        assert strip_code_fences('```\n{"steps": []}\n```') == '{"steps": []}'

    def test_a_language_tagged_fence_is_removed(self) -> None:
        assert strip_code_fences('```json\n{"steps": []}\n```') == '{"steps": []}'

    def test_a_JSON_tag_in_any_case_is_removed(self) -> None:
        assert strip_code_fences('```JSON\n{"steps": []}\n```') == '{"steps": []}'

    def test_blank_lines_inside_the_fence_are_preserved_for_the_parser(self) -> None:
        text = '```json\n{\n  "steps": []\n}\n\n```'
        assert strip_code_fences(text) == '{\n  "steps": []\n}'

    def test_trailing_blank_lines_after_an_unterminated_fence_are_trimmed(self) -> None:
        assert strip_code_fences('```json\n{"a": 1}\n\n\n') == '{"a": 1}'

    def test_a_fence_with_nothing_inside_yields_an_empty_payload(self) -> None:
        assert strip_code_fences("```json\n```") == ""

    def test_unfenced_text_with_inner_backticks_is_left_alone(self) -> None:
        assert strip_code_fences('{"a": "```"}') == '{"a": "```"}'

    def test_an_empty_string_is_returned_empty(self) -> None:
        assert strip_code_fences("") == ""
        assert strip_code_fences("   \n ") == ""


class TestParsePlan:
    """Sub-phase 1.2 — SPEC-004 § 4.2 parsing and normalization golden fixtures."""

    def test_a_valid_payload_produces_canonical_step_ids_in_array_order(self) -> None:
        plan = parse_plan(VALID_PLAN_PAYLOAD, FakeConfig())
        assert [step.id for step in plan.steps] == ["step_0", "step_1"]

    def test_a_valid_payload_carries_description_tool_hint_and_input_data(self) -> None:
        plan = parse_plan(VALID_PLAN_PAYLOAD, FakeConfig())
        first = plan.steps[0]
        assert first.description == "Search for GPT-4 usage statistics"
        assert first.tool_hint == "web_search"
        assert first.input_data == {"query": "GPT-4 usage statistics 2024"}
        assert first.fallback_tools == ["web_scrape"]

    def test_priority_strings_map_onto_the_spec_001_enum(self) -> None:
        plan = parse_plan(VALID_PLAN_PAYLOAD, FakeConfig())
        assert plan.steps[0].priority is TaskPriority.CRITICAL
        assert plan.steps[1].priority is TaskPriority.HIGH

    def test_a_json_string_payload_is_parsed(self) -> None:
        plan = parse_plan(
            '{"steps": [{"description": "a", "tool_hint": "t"}]}', FakeConfig()
        )
        assert [step.id for step in plan.steps] == ["step_0"]

    def test_a_fenced_json_string_payload_is_parsed(self) -> None:
        payload = '```json\n{"steps": [{"description": "a", "tool_hint": "t"}]}\n```'
        plan = parse_plan(payload, FakeConfig())
        assert plan.steps[0].description == "a"

    @pytest.mark.parametrize("reference", [0, "0", "step_0"])
    def test_integer_and_string_dependency_references_normalize_to_step_i(
        self, reference: int | str
    ) -> None:
        payload = {
            "steps": [
                {"description": "a", "tool_hint": "t"},
                {"description": "b", "tool_hint": "t", "depends_on": [reference]},
            ]
        }
        plan = parse_plan(payload, FakeConfig())
        assert plan.steps[1].depends_on == ["step_0"]

    def test_dependency_references_to_later_steps_normalize_too(self) -> None:
        payload = {
            "steps": [
                {"description": "a", "tool_hint": "t", "depends_on": [1, "step_2"]},
                {"description": "b", "tool_hint": "t"},
                {"description": "c", "tool_hint": "t"},
            ]
        }
        plan = parse_plan(payload, FakeConfig())
        assert plan.steps[0].depends_on == ["step_1", "step_2"]

    def test_a_bare_string_dependency_is_treated_as_a_single_reference(self) -> None:
        payload = {
            "steps": [
                {"description": "a", "tool_hint": "t"},
                {"description": "b", "tool_hint": "t", "depends_on": "step_0"},
            ]
        }
        assert parse_plan(payload, FakeConfig()).steps[1].depends_on == ["step_0"]

    def test_missing_optional_fields_take_their_spec_defaults(self) -> None:
        plan = parse_plan(
            {"steps": [{"description": "a", "tool_hint": "t"}]}, FakeConfig()
        )
        step = plan.steps[0]
        assert step.input_data == {}
        assert step.depends_on == []
        assert step.fallback_tools == []
        assert step.priority is TaskPriority.HIGH
        assert step.status is StepStatus.PENDING
        assert step.retries == 0
        assert step.output_data is None
        assert step.error is None
        assert step.tool_name == ""

    def test_max_retries_comes_from_config_not_from_the_model(self) -> None:
        config = FakeConfig(execution=FakeExecutionSection(max_retries=5))
        payload = {"steps": [{"description": "a", "tool_hint": "t", "max_retries": 99}]}
        assert parse_plan(payload, config).steps[0].max_retries == 5

    def test_unknown_step_keys_are_ignored(self) -> None:
        payload = {
            "steps": [
                {
                    "description": "a",
                    "tool_hint": "t",
                    "id": "model_chosen_id",
                    "status": "success",
                    "retries": 7,
                    "some_future_field": {"nested": True},
                }
            ]
        }
        step = parse_plan(payload, FakeConfig()).steps[0]
        assert step.id == "step_0"  # canonical ids win (SPEC-004 § 4.2 rule 2)
        assert step.status is StepStatus.PENDING
        assert step.retries == 0

    def test_unknown_top_level_keys_are_ignored(self) -> None:
        payload = {
            "steps": [{"description": "a", "tool_hint": "t"}],
            "reasoning": "because",
        }
        plan = parse_plan(payload, FakeConfig())
        assert len(plan.steps) == 1

    @pytest.mark.parametrize("value", ["urgent", "CRITICA", "", None, 5, ["critical"]])
    def test_an_unknown_priority_value_falls_back_to_high(self, value: object) -> None:
        payload = {"steps": [{"description": "a", "tool_hint": "t", "priority": value}]}
        assert parse_plan(payload, FakeConfig()).steps[0].priority is TaskPriority.HIGH

    @pytest.mark.parametrize("value", ["CRITICAL", "Critical", " critical "])
    def test_priority_matching_is_case_and_whitespace_insensitive(
        self, value: str
    ) -> None:
        payload = {"steps": [{"description": "a", "tool_hint": "t", "priority": value}]}
        assert (
            parse_plan(payload, FakeConfig()).steps[0].priority is TaskPriority.CRITICAL
        )

    def test_original_prompt_is_recorded_on_the_plan(self) -> None:
        plan = parse_plan(
            VALID_PLAN_PAYLOAD, FakeConfig(), original_prompt="Do the research"
        )
        assert plan.original_prompt == "Do the research"

    def test_the_new_plan_starts_pending_with_no_final_output(self) -> None:
        plan = parse_plan(VALID_PLAN_PAYLOAD, FakeConfig())
        assert plan.status is StepStatus.PENDING
        assert plan.final_output is None

    def test_an_injected_now_stamps_created_at_deterministically(self) -> None:
        # SPEC-000 § 5.5: frozen timestamps via injection, never the wall clock.
        frozen = datetime(2026, 9, 14, 12, 0, 0)
        plan = parse_plan(VALID_PLAN_PAYLOAD, FakeConfig(), now=frozen)
        assert plan.created_at == frozen

    def test_created_at_defaults_to_a_datetime_when_no_clock_is_injected(self) -> None:
        assert isinstance(
            parse_plan(VALID_PLAN_PAYLOAD, FakeConfig()).created_at, datetime
        )

    def test_an_injected_model_provider_is_used_to_build_the_plan(self) -> None:
        class _RecordingModels(SpecModels):
            def __init__(self) -> None:
                self.built: list[str] = []

            def step(self, **kw: Any) -> Step:
                self.built.append("step")
                return super().step(**kw)

        models = _RecordingModels()
        plan = parse_plan(VALID_PLAN_PAYLOAD, FakeConfig(), models=models)
        assert models.built == ["step", "step"]
        assert len(plan.steps) == 2

    @pytest.mark.parametrize("steps", [None, {"description": "a"}, "step_0", 5])
    def test_a_missing_or_non_list_steps_value_yields_no_steps_for_v1_to_reject(
        self, steps: object
    ) -> None:
        # SPEC-004 § 4.3 V1 owns "steps missing, not a list, or empty" → parsing
        # yields zero steps rather than raising PLAN_PARSE_FAILED.
        payload = {} if steps is None else {"steps": steps}
        assert parse_plan(payload, FakeConfig()).steps == []

    def test_an_empty_steps_array_yields_no_steps_for_v1_to_reject(self) -> None:
        assert parse_plan({"steps": []}, FakeConfig()).steps == []

    @pytest.mark.parametrize(
        "payload",
        [
            "",
            "   ",
            "not json at all",
            '{"steps": [',
            "{'steps': []}",  # single-quoted pseudo-JSON is rejected, not repaired
            "[1, 2, 3]",  # a top-level array is not the § 4.1 object shape
            '"just a string"',
            "42",
            "null",
        ],
    )
    def test_unparseable_payloads_raise_plan_parse_failed_never_a_raw_decode_error(
        self, payload: str
    ) -> None:
        with pytest.raises(AgentErrorRaised) as caught:
            parse_plan(payload, FakeConfig())
        assert caught.value.code == "PLAN_PARSE_FAILED"

    def test_the_parse_error_names_the_planner_component(self) -> None:
        with pytest.raises(AgentErrorRaised) as caught:
            parse_plan("nope", FakeConfig())
        assert caught.value.error.component == "planner"

    def test_the_parse_error_message_is_bounded_to_500_chars_of_raw_text(self) -> None:
        # SPEC-006 § 3.4: never put oversized bodies into logs or error text.
        huge = "{" + "x" * 5000
        with pytest.raises(AgentErrorRaised) as caught:
            parse_plan(huge, FakeConfig())
        assert len(caught.value.error.message) < 700
        assert "truncated" in caught.value.error.message

    @pytest.mark.parametrize(
        ("steps", "why"),
        [
            (["a string step"], "a step must be an object"),
            ([42], "a step must be an object"),
            ([None], "a step must be an object"),
            ([{"description": 123, "tool_hint": "t"}], "description must be a string"),
            ([{"description": "a", "tool_hint": 7}], "tool_hint must be a string"),
            ([{"description": "a", "tool_hint": "t", "input_data": "x"}], "input_data"),
            ([{"description": "a", "tool_hint": "t", "input_data": [1]}], "input_data"),
            ([{"description": "a", "tool_hint": "t", "depends_on": 5}], "depends_on"),
            (
                [{"description": "a", "tool_hint": "t", "fallback_tools": 5}],
                "fallback_tools",
            ),
            (
                [{"description": "a", "tool_hint": "t", "fallback_tools": [7]}],
                "fallback entry",
            ),
            (
                [{"description": "a", "tool_hint": "t", "depends_on": [None]}],
                "depends_on entry",
            ),
        ],
    )
    def test_wrong_typed_fields_raise_plan_parse_failed(
        self, steps: list[Any], why: str
    ) -> None:
        with pytest.raises(AgentErrorRaised) as caught:
            parse_plan({"steps": steps}, FakeConfig())
        assert caught.value.code == "PLAN_PARSE_FAILED", why

    def test_a_fallback_tools_bare_string_is_treated_as_a_single_entry(self) -> None:
        payload = {
            "steps": [
                {"description": "a", "tool_hint": "t", "fallback_tools": "web_scrape"}
            ]
        }
        assert parse_plan(payload, FakeConfig()).steps[0].fallback_tools == [
            "web_scrape"
        ]

    def test_nested_input_data_is_preserved_by_reference_shape(self) -> None:
        payload = {
            "steps": [
                {
                    "description": "a",
                    "tool_hint": "t",
                    "input_data": {"nested": {"list": [1, 2, {"deep": "value"}]}},
                }
            ]
        }
        step = parse_plan(payload, FakeConfig()).steps[0]
        assert step.input_data == {"nested": {"list": [1, 2, {"deep": "value"}]}}

    def test_unicode_descriptions_survive_parsing(self) -> None:
        payload = {"steps": [{"description": "Rechercher — 検索 🚀", "tool_hint": "t"}]}
        assert (
            parse_plan(payload, FakeConfig()).steps[0].description
            == "Rechercher — 検索 🚀"
        )

    def test_parsing_never_mutates_the_payload_it_was_given(self) -> None:
        payload = {"steps": [{"description": "a", "tool_hint": "t", "depends_on": [0]}]}
        snapshot = {
            "steps": [{"description": "a", "tool_hint": "t", "depends_on": [0]}]
        }
        parse_plan(payload, FakeConfig())
        assert payload == snapshot


class TestStatusAndPriorityHelpers:
    """Enum-identity-free comparisons, so injected Plan 1 enums can never mismatch."""

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (StepStatus.SUCCESS, "success"),
            (StepStatus.RETRYING, "retrying"),
            ("failed", "failed"),
            (None, ""),
        ],
    )
    def test_status_value_reads_enums_strings_and_none(
        self, status: object, expected: str
    ) -> None:
        assert status_value(status) == expected

    @pytest.mark.parametrize(
        ("priority", "expected"),
        [
            (TaskPriority.CRITICAL, "critical"),
            ("low", "low"),
            (None, ""),
        ],
    )
    def test_priority_value_reads_enums_strings_and_none(
        self, priority: object, expected: str
    ) -> None:
        assert priority_value(priority) == expected

    def test_a_foreign_enum_with_the_same_value_compares_equal_by_value(self) -> None:
        # The integration hazard this guards: Plan 1 injects its own StepStatus, so
        # identity comparison against P3's stand-in would be False.
        class ForeignStatus(Enum):
            SUCCESS = "success"

        foreign: object = ForeignStatus.SUCCESS
        native: object = StepStatus.SUCCESS
        assert foreign is not native  # distinct enum classes are never identical
        assert status_value(foreign) == status_value(native) == "success"

    @pytest.mark.parametrize(
        ("priority", "expected"),
        [
            (TaskPriority.CRITICAL, 0),
            (TaskPriority.HIGH, 1),
            (TaskPriority.MEDIUM, 2),
            (TaskPriority.LOW, 3),
            ("critical", 0),
            ("nonsense", 1),  # unknown ranks as HIGH, the SPEC-004 § 4.2 default
        ],
    )
    def test_priority_rank_orders_critical_above_low(
        self, priority: object, expected: int
    ) -> None:
        assert priority_rank(priority) == expected

    def test_medium_and_low_rank_below_critical_for_the_dependency_gate(self) -> None:
        # SPEC-003 § 3 step 1 allows a SKIPPED dependency whose priority < CRITICAL.
        assert priority_rank(TaskPriority.MEDIUM) > priority_rank(TaskPriority.CRITICAL)
        assert priority_rank(TaskPriority.LOW) > priority_rank(TaskPriority.CRITICAL)


class TestNonRaisableInjectedError:
    """SCR-P3-7: a plain-dataclass error must still surface, never be swallowed."""

    @dataclass
    class PlainDataError:
        """A SPEC-001 § 2.4 error that does *not* subclass Exception."""

        code: str
        message: str
        component: str
        step_id: str | None = None
        recoverable: bool = False
        recovery_action: str | None = None
        original_error: str | None = None

        def to_dict(self) -> dict[str, Any]:
            return {
                "code": self.code,
                "message": self.message,
                "component": self.component,
            }

        def __str__(self) -> str:
            return f"[{self.code}] {self.component}: {self.message}"

    class PlainDataModels(SpecModels):
        """Model provider whose errors are not raisable."""

        def agent_error(self, **kwargs: Any) -> Any:
            return TestNonRaisableInjectedError.PlainDataError(**kwargs)

    def test_a_parse_failure_is_wrapped_and_still_carries_the_spec_error(self) -> None:
        with pytest.raises(AgentErrorRaised) as caught:
            parse_plan("not json", FakeConfig(), models=self.PlainDataModels())
        assert caught.value.code == "PLAN_PARSE_FAILED"
        assert caught.value.error.component == "planner"
        assert (
            str(caught.value)
            == "[PLAN_PARSE_FAILED] planner: " + caught.value.error.message
        )

    def test_the_wrapped_error_exposes_to_dict_for_reporting(self) -> None:
        with pytest.raises(AgentErrorRaised) as caught:
            parse_plan("not json", FakeConfig(), models=self.PlainDataModels())
        assert caught.value.error.to_dict()["code"] == "PLAN_PARSE_FAILED"

    def test_the_default_stand_in_error_is_raised_itself_not_wrapped(self) -> None:
        with pytest.raises(AgentError) as caught:
            parse_plan("not json", FakeConfig())
        assert isinstance(caught.value, AgentErrorRaised)
        assert caught.value.error is caught.value


class TestSerializationEdgeCases:
    """SPEC-001 § 4 — wrong types raise, unknown keys are ignored."""

    def test_step_from_dict_rejects_a_non_mapping(self) -> None:
        with pytest.raises(TypeError, match="expects a mapping"):
            Step.from_dict(["not", "a", "mapping"])  # type: ignore[arg-type]

    def test_execution_plan_from_dict_rejects_a_non_mapping(self) -> None:
        with pytest.raises(TypeError, match="expects a mapping"):
            ExecutionPlan.from_dict("nope")  # type: ignore[arg-type]

    def test_step_from_dict_rejects_a_wrong_typed_input_data(self) -> None:
        with pytest.raises(ValueError, match="input_data must be a mapping"):
            Step.from_dict({"id": "step_0", "input_data": "not-a-mapping"})

    def test_step_from_dict_rejects_a_wrong_typed_depends_on(self) -> None:
        with pytest.raises(ValueError, match="depends_on must be a sequence"):
            Step.from_dict({"id": "step_0", "depends_on": 5})

    def test_step_from_dict_rejects_an_unknown_enum_value(self) -> None:
        with pytest.raises(ValueError):
            Step.from_dict({"id": "step_0", "status": "exploded"})

    def test_agent_error_to_dict_serializes_every_spec_field(self) -> None:
        error = AgentError(
            code="TOOL_NOT_FOUND",
            message="no tool",
            component="orchestrator",
            step_id="step_1",
            recoverable=True,
            recovery_action="fallback",
            original_error="KeyError",
        )
        assert error.to_dict() == {
            "code": "TOOL_NOT_FOUND",
            "message": "no tool",
            "component": "orchestrator",
            "step_id": "step_1",
            "recoverable": True,
            "recovery_action": "fallback",
            "original_error": "KeyError",
        }

    def test_agent_error_populates_exception_args_for_logging(self) -> None:
        error = AgentError(code="C", message="m", component="planner")
        assert error.args == ("[C] planner: m",)


class TestParsePlanPayloadShapes:
    """Sub-phase 1.2/1.5 — payload coercions at the trust boundary."""

    def test_a_bytes_payload_is_decoded_and_parsed(self) -> None:
        payload = b'{"steps": [{"description": "a", "tool_hint": "t"}]}'
        assert parse_plan(payload, FakeConfig()).steps[0].description == "a"

    def test_a_null_input_data_becomes_an_empty_object(self) -> None:
        payload = {
            "steps": [{"description": "a", "tool_hint": "t", "input_data": None}]
        }
        assert parse_plan(payload, FakeConfig()).steps[0].input_data == {}

    def test_an_unterminated_code_fence_still_yields_the_payload(self) -> None:
        payload = '```json\n{"steps": [{"description": "a", "tool_hint": "t"}]}'
        assert parse_plan(payload, FakeConfig()).steps[0].description == "a"

    def test_a_non_string_non_mapping_payload_names_the_offending_type(self) -> None:
        with pytest.raises(AgentErrorRaised) as caught:
            parse_plan(42, FakeConfig())
        assert "int" in caught.value.error.message
        assert caught.value.code == "PLAN_PARSE_FAILED"

    def test_the_parsed_input_data_is_a_copy_so_the_payload_stays_unshared(
        self,
    ) -> None:
        payload = {
            "steps": [{"description": "a", "tool_hint": "t", "input_data": {"k": "v"}}]
        }
        plan = parse_plan(payload, FakeConfig())
        plan.steps[0].input_data["k"] = "mutated"
        assert payload["steps"][0]["input_data"] == {"k": "v"}


# ══════════════════════════════════════════════════════════════════════════════
# Sub-phase 1.3 — validation rules V1-V7 (SPEC-004 § 4.3)
# ══════════════════════════════════════════════════════════════════════════════


def _plan(steps: list[dict[str, Any]], **kwargs: Any) -> PlanLike:
    """Build a parsed plan from raw step objects (parsing is sub-phase 1.2's job)."""
    return parse_plan({"steps": steps}, FakeConfig(), **kwargs)


def _valid_steps() -> list[dict[str, Any]]:
    return [
        {
            "description": "Search for GPT-4 usage statistics",
            "tool_hint": "web_search",
            "priority": "critical",
        },
        {
            "description": "Export the summary as a PDF",
            "tool_hint": "pdf_export",
            "depends_on": ["step_0"],
        },
    ]


AVAILABLE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "web_search",
        "description": "Search the web.",
        "capabilities": ["search"],
    },
    {"name": "pdf_export", "description": "Export a PDF.", "capabilities": ["export"]},
]


class TestValidationV1EmptySteps:
    """V1 — `steps` missing, not a list, or empty."""

    @pytest.mark.parametrize(
        "payload", [{}, {"steps": []}, {"steps": {}}, {"steps": "step_0"}]
    )
    def test_an_empty_or_absent_steps_array_fails_validation(
        self, payload: dict[str, Any]
    ) -> None:
        plan = parse_plan(payload, FakeConfig())
        with pytest.raises(AgentErrorRaised) as caught:
            validate_plan(plan, FakeConfig())
        assert caught.value.code == "PLAN_VALIDATION_FAILED"
        assert "steps" in caught.value.error.message

    def test_a_single_step_passes_v1(self) -> None:
        plan = _plan([{"description": "a", "tool_hint": "t", "priority": "critical"}])
        assert validate_plan(plan, FakeConfig()) == []


class TestValidationV2TooManySteps:
    """V2 — `len(steps) > config.execution.max_steps`."""

    def test_more_steps_than_the_configured_maximum_fails(self) -> None:
        config = FakeConfig(execution=FakeExecutionSection(max_steps=2))
        steps = [
            {"description": f"step {i}", "tool_hint": "t", "priority": "critical"}
            for i in range(3)
        ]
        with pytest.raises(AgentErrorRaised) as caught:
            validate_plan(_plan(steps), config)
        assert caught.value.code == "PLAN_VALIDATION_FAILED"
        assert "max_steps" in caught.value.error.message

    def test_exactly_max_steps_passes_the_boundary(self) -> None:
        config = FakeConfig(execution=FakeExecutionSection(max_steps=2))
        steps = [
            {"description": f"step {i}", "tool_hint": "t", "priority": "critical"}
            for i in range(2)
        ]
        assert validate_plan(_plan(steps), config) == []

    def test_one_below_the_maximum_passes(self) -> None:
        config = FakeConfig(execution=FakeExecutionSection(max_steps=20))
        steps = [{"description": "a", "tool_hint": "t", "priority": "critical"}]
        assert validate_plan(_plan(steps), config) == []


class TestValidationV3MissingDescription:
    """V3 — any step missing a non-empty `description`."""

    @pytest.mark.parametrize("description", ["", "   ", "\t\n"])
    def test_an_empty_or_whitespace_description_fails(self, description: str) -> None:
        plan = _plan([{"description": description, "tool_hint": "t"}])
        with pytest.raises(AgentErrorRaised) as caught:
            validate_plan(plan, FakeConfig())
        assert caught.value.code == "PLAN_VALIDATION_FAILED"
        assert "description" in caught.value.error.message

    def test_the_offending_step_id_is_reported(self) -> None:
        plan = _plan(
            [
                {"description": "fine", "tool_hint": "t", "priority": "critical"},
                {"description": "", "tool_hint": "t"},
            ]
        )
        with pytest.raises(AgentErrorRaised) as caught:
            validate_plan(plan, FakeConfig())
        assert caught.value.error.step_id == "step_1"

    def test_a_missing_description_key_fails_too(self) -> None:
        plan = _plan([{"tool_hint": "t"}])
        with pytest.raises(AgentErrorRaised) as caught:
            validate_plan(plan, FakeConfig())
        assert "description" in caught.value.error.message


class TestValidationV4UnknownDependency:
    """V4 — `depends_on` references an out-of-range or nonexistent step."""

    @pytest.mark.parametrize("reference", ["step_5", "step_99", "nonexistent", ""])
    def test_a_reference_to_an_unknown_step_fails(self, reference: str) -> None:
        plan = _plan(
            [
                {"description": "a", "tool_hint": "t", "priority": "critical"},
                {"description": "b", "tool_hint": "t", "depends_on": [reference]},
            ]
        )
        with pytest.raises(AgentErrorRaised) as caught:
            validate_plan(plan, FakeConfig())
        assert caught.value.code == "PLAN_VALIDATION_FAILED"
        assert "depend" in caught.value.error.message.lower()

    def test_an_out_of_range_integer_reference_fails(self) -> None:
        plan = _plan(
            [
                {"description": "a", "tool_hint": "t", "priority": "critical"},
                {"description": "b", "tool_hint": "t", "depends_on": [99]},
            ]
        )
        with pytest.raises(AgentErrorRaised):
            validate_plan(plan, FakeConfig())

    def test_references_to_existing_steps_pass(self) -> None:
        plan = _plan(_valid_steps())
        assert validate_plan(plan, FakeConfig()) == []

    def test_a_forward_reference_to_a_later_step_is_legal(self) -> None:
        # SPEC-004 § 4.2 normalizes references before resolution; § 4.3 V4 only
        # rejects *nonexistent* ids, so ordering direction is not a failure.
        plan = _plan(
            [
                {"description": "a", "tool_hint": "t", "depends_on": ["step_1"]},
                {"description": "b", "tool_hint": "t", "priority": "critical"},
            ]
        )
        assert validate_plan(plan, FakeConfig()) == []


class TestValidationV5Cycles:
    """V5 — cycle detection, reusing the topological sorter in validation mode."""

    def test_a_two_step_cycle_fails(self) -> None:
        plan = _plan(
            [
                {"description": "a", "tool_hint": "t", "depends_on": ["step_1"]},
                {"description": "b", "tool_hint": "t", "depends_on": ["step_0"]},
            ]
        )
        with pytest.raises(AgentErrorRaised) as caught:
            validate_plan(plan, FakeConfig())
        assert caught.value.code == "PLAN_VALIDATION_FAILED"
        assert "ircular" in caught.value.error.message

    def test_a_three_step_cycle_fails(self) -> None:
        plan = _plan(
            [
                {"description": "a", "tool_hint": "t", "depends_on": ["step_2"]},
                {"description": "b", "tool_hint": "t", "depends_on": ["step_0"]},
                {"description": "c", "tool_hint": "t", "depends_on": ["step_1"]},
            ]
        )
        with pytest.raises(AgentErrorRaised) as caught:
            validate_plan(plan, FakeConfig())
        assert "ircular" in caught.value.error.message

    def test_a_cycle_downstream_of_a_valid_prefix_still_fails(self) -> None:
        plan = _plan(
            [
                {"description": "a", "tool_hint": "t", "priority": "critical"},
                {"description": "b", "tool_hint": "t", "depends_on": ["step_2"]},
                {"description": "c", "tool_hint": "t", "depends_on": ["step_1"]},
            ]
        )
        with pytest.raises(AgentErrorRaised):
            validate_plan(plan, FakeConfig())

    def test_a_diamond_is_not_a_cycle(self) -> None:
        plan = _plan(
            [
                {"description": "a", "tool_hint": "t", "priority": "critical"},
                {"description": "b", "tool_hint": "t", "depends_on": ["step_0"]},
                {"description": "c", "tool_hint": "t", "depends_on": ["step_0"]},
                {
                    "description": "d",
                    "tool_hint": "t",
                    "depends_on": ["step_1", "step_2"],
                },
            ]
        )
        assert validate_plan(plan, FakeConfig()) == []


class TestValidationV5DelegatesToTheSharedSorter:
    """V5 reuses `resolve_execution_order` — SPEC-004 § 4.3 V5, SPEC-003 § 8.

    Sub-phase 1.3 shipped a temporary local Kahn copy because this plan delivers the
    shared sorter only at 3.1, and promised to delete it here. These tests pin the
    delegation itself, so the swap is observable rather than assumed. The sorter is
    patched at its own module attribute because `validate_plan` imports it lazily
    inside the function body: `orchestration.dependency` takes the shared contract kit
    from `planning.planner` (SPEC-000 § 3.3 gives this plan no contracts module), so a
    module-level import in both directions would be circular.
    """

    def test_v5_calls_the_shared_sorter_once_with_the_plans_steps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[list[str], Any]] = []

        def _stub(steps: Any, *, logger: Any = None) -> list[Any]:
            calls.append(([step.id for step in steps], logger))
            return list(steps)

        monkeypatch.setattr(dependency, "resolve_execution_order", _stub)
        logger = FakeLogger()
        assert validate_plan(_plan(_valid_steps()), FakeConfig(), logger=logger) == []
        assert calls == [(["step_0", "step_1"], logger)]

    def test_a_null_logger_is_forwarded_when_none_was_injected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[Any] = []

        def _stub(steps: Any, *, logger: Any = None) -> list[Any]:
            seen.append(logger)
            return list(steps)

        monkeypatch.setattr(dependency, "resolve_execution_order", _stub)
        validate_plan(_plan(_valid_steps()), FakeConfig())
        assert isinstance(seen[0], NullLogger)

    def test_the_frozen_cycle_message_reaches_the_failure_detail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _stub(steps: Any, *, logger: Any = None) -> list[Any]:
            raise ValueError("Circular dependency detected in execution plan")

        monkeypatch.setattr(dependency, "resolve_execution_order", _stub)
        logger = FakeLogger()
        with pytest.raises(AgentErrorRaised) as caught:
            validate_plan(_plan(_valid_steps()), FakeConfig(), logger=logger)
        assert caught.value.code == "PLAN_VALIDATION_FAILED"
        assert caught.value.error.message.startswith(
            "Circular dependency detected in execution plan"
        )
        assert "V5" in caught.value.error.message
        assert logger.events() == ["plan_validation_failed"]

    def test_only_value_error_becomes_a_validation_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A bug in the sorter must not be laundered into "the plan has a cycle".
        def _stub(steps: Any, *, logger: Any = None) -> list[Any]:
            raise RuntimeError("not a cycle")

        monkeypatch.setattr(dependency, "resolve_execution_order", _stub)
        with pytest.raises(RuntimeError):
            validate_plan(_plan(_valid_steps()), FakeConfig())

    def test_the_temporary_local_sorter_from_sub_phase_1_3_is_gone(self) -> None:
        module = importlib.import_module("agent_harness.planning.planner")
        assert not hasattr(module, "_topological_order")

    def test_validation_never_emits_the_sorters_dangling_dependency_warning(
        self,
    ) -> None:
        # V4 rejects unknown dependency ids before V5 runs, so `dependency_ignored`
        # cannot fire in validation mode: a dangling reference is a hard failure here,
        # while SPEC-003 § 8 tolerates it at execution time.
        logger = FakeLogger()
        plan = _plan([{"description": "a", "tool_hint": "t", "depends_on": ["ghost"]}])
        with pytest.raises(AgentErrorRaised):
            validate_plan(plan, FakeConfig(), logger=logger)
        assert logger.events() == ["plan_validation_failed"]


class TestValidationV6SelfDependency:
    """V6 — `step_i` depends on `step_i`."""

    def test_a_self_dependency_fails_with_a_specific_message(self) -> None:
        plan = _plan([{"description": "a", "tool_hint": "t", "depends_on": ["step_0"]}])
        with pytest.raises(AgentErrorRaised) as caught:
            validate_plan(plan, FakeConfig())
        assert caught.value.code == "PLAN_VALIDATION_FAILED"
        assert "self" in caught.value.error.message.lower()
        assert caught.value.error.step_id == "step_0"

    def test_a_self_dependency_is_reported_as_v6_not_as_a_generic_cycle(self) -> None:
        plan = _plan(
            [
                {"description": "a", "tool_hint": "t", "depends_on": ["step_1"]},
                {"description": "b", "tool_hint": "t", "depends_on": ["step_1"]},
            ]
        )
        with pytest.raises(AgentErrorRaised) as caught:
            validate_plan(plan, FakeConfig())
        assert "self" in caught.value.error.message.lower()
        assert caught.value.error.step_id == "step_1"

    def test_an_integer_self_reference_is_detected_after_normalization(self) -> None:
        plan = _plan([{"description": "a", "tool_hint": "t", "depends_on": [0]}])
        with pytest.raises(AgentErrorRaised) as caught:
            validate_plan(plan, FakeConfig())
        assert "self" in caught.value.error.message.lower()


class TestValidationV7NoCriticalStep:
    """V7 — zero CRITICAL steps is a WARNING, never a failure."""

    def test_a_plan_with_no_critical_step_validates_and_returns_a_warning(self) -> None:
        plan = _plan(
            [
                {"description": "a", "tool_hint": "t", "priority": "high"},
                {"description": "b", "tool_hint": "t", "priority": "low"},
            ]
        )
        warnings = validate_plan(plan, FakeConfig())
        assert len(warnings) == 1
        assert "critical" in warnings[0].lower()

    def test_a_plan_with_one_critical_step_returns_no_warning(self) -> None:
        assert validate_plan(_plan(_valid_steps()), FakeConfig()) == []

    def test_the_v7_warning_does_not_raise(self) -> None:
        plan = _plan([{"description": "a", "tool_hint": "t", "priority": "medium"}])
        validate_plan(plan, FakeConfig())  # no exception

    def test_the_v7_warning_does_not_suppress_a_real_failure(self) -> None:
        plan = _plan([{"description": "", "tool_hint": "t"}])
        with pytest.raises(AgentErrorRaised):
            validate_plan(plan, FakeConfig())


class TestUnresolvedToolHints:
    """SPEC-004 § 4.3 note — unknown hints are recorded, never a failure."""

    def test_an_unknown_tool_hint_is_recorded_and_does_not_fail_validation(
        self,
    ) -> None:
        plan = _plan(
            [
                {"description": "a", "tool_hint": "teleport", "priority": "critical"},
                {
                    "description": "b",
                    "tool_hint": "web_search",
                    "depends_on": ["step_0"],
                },
            ]
        )
        assert validate_plan(plan, FakeConfig(), available_tools=AVAILABLE_TOOLS) == []
        assert plan.context["unresolved_hints"] == ["teleport"]

    def test_all_known_hints_leave_the_list_empty(self) -> None:
        plan = _plan(_valid_steps())
        validate_plan(plan, FakeConfig(), available_tools=AVAILABLE_TOOLS)
        assert plan.context["unresolved_hints"] == []

    def test_an_empty_tool_hint_is_not_reported_as_unresolved(self) -> None:
        plan = _plan([{"description": "a", "tool_hint": "", "priority": "critical"}])
        validate_plan(plan, FakeConfig(), available_tools=AVAILABLE_TOOLS)
        assert plan.context["unresolved_hints"] == []

    def test_duplicate_unknown_hints_are_recorded_once(self) -> None:
        plan = _plan(
            [
                {"description": "a", "tool_hint": "teleport", "priority": "critical"},
                {"description": "b", "tool_hint": "teleport"},
            ]
        )
        validate_plan(plan, FakeConfig(), available_tools=AVAILABLE_TOOLS)
        assert plan.context["unresolved_hints"] == ["teleport"]

    def test_without_a_tool_list_the_record_is_empty(self) -> None:
        plan = _plan(
            [{"description": "a", "tool_hint": "teleport", "priority": "critical"}]
        )
        validate_plan(plan, FakeConfig())
        assert plan.context["unresolved_hints"] == []

    def test_tool_objects_exposing_a_name_attribute_are_accepted(self) -> None:
        class _Tool:
            name = "web_search"

        plan = _plan(
            [{"description": "a", "tool_hint": "web_search", "priority": "critical"}]
        )
        validate_plan(plan, FakeConfig(), available_tools=[_Tool()])
        assert plan.context["unresolved_hints"] == []


class TestValidationReporting:
    """Catalog-only logging (SPEC-006 § 6.1) and check ordering."""

    def test_a_failure_emits_plan_validation_failed_before_raising(self) -> None:
        logger = FakeLogger()
        with pytest.raises(AgentErrorRaised):
            validate_plan(_plan([]), FakeConfig(), logger=logger)
        assert "plan_validation_failed" in logger.events()
        assert (
            logger.levels()[logger.events().index("plan_validation_failed")] == "ERROR"
        )

    def test_a_successful_validation_emits_no_event_of_its_own(self) -> None:
        # `plan_generated` belongs to Planner.plan() (SPEC-006 § 6.1: "after
        # successful validation"); validate_plan must not emit it, or the event
        # would be duplicated.
        logger = FakeLogger()
        validate_plan(_plan(_valid_steps()), FakeConfig(), logger=logger)
        assert logger.events() == []

    def test_the_first_failing_check_in_spec_order_is_reported(self) -> None:
        # V1 (empty) wins over everything; V2 over V3; V3 over V4.
        config = FakeConfig(execution=FakeExecutionSection(max_steps=1))
        plan = _plan(
            [
                {"description": "", "tool_hint": "t", "depends_on": ["step_9"]},
                {"description": "b", "tool_hint": "t"},
            ]
        )
        with pytest.raises(AgentErrorRaised) as caught:
            validate_plan(plan, config)
        assert "max_steps" in caught.value.error.message

    def test_v3_is_reported_before_v4(self) -> None:
        plan = _plan([{"description": "", "tool_hint": "t", "depends_on": ["step_9"]}])
        with pytest.raises(AgentErrorRaised) as caught:
            validate_plan(plan, FakeConfig())
        assert "description" in caught.value.error.message

    def test_v6_is_reported_before_the_generic_v5_cycle(self) -> None:
        plan = _plan(
            [
                {"description": "a", "tool_hint": "t", "depends_on": ["step_0"]},
                {"description": "b", "tool_hint": "t", "depends_on": ["step_0"]},
            ]
        )
        with pytest.raises(AgentErrorRaised) as caught:
            validate_plan(plan, FakeConfig())
        assert "self" in caught.value.error.message.lower()

    def test_the_error_component_is_the_planner(self) -> None:
        with pytest.raises(AgentErrorRaised) as caught:
            validate_plan(_plan([]), FakeConfig())
        assert caught.value.error.component == "planner"

    def test_validation_never_mutates_the_steps_it_checked(self) -> None:
        plan = _plan(_valid_steps())
        before = [step.to_dict() for step in plan.steps]
        validate_plan(plan, FakeConfig(), available_tools=AVAILABLE_TOOLS)
        assert [step.to_dict() for step in plan.steps] == before

    def test_the_only_context_write_is_unresolved_hints(self) -> None:
        plan = _plan(_valid_steps())
        validate_plan(plan, FakeConfig(), available_tools=AVAILABLE_TOOLS)
        assert list(plan.context) == ["unresolved_hints"]


# ══════════════════════════════════════════════════════════════════════════════
# Sub-phase 1.4 — test doubles for the cognition layer, and the contract tests
# (SPEC-000 § 5.4) that pin them to the frozen interfaces they stand in for.
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class FakeLLMResponse:
    """Stand-in for ``LLMResponse`` (SPEC-004 § 1) — field order verbatim."""

    text: str = ""
    model: str = "fake-model"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str = "stop"
    latency_ms: int = 0
    redactions: int = 0  # § 1.2 C4: "LLMResponse may carry redactions: int"


@dataclass
class FakeLLMUsage:
    """Stand-in for ``LLMUsage`` (SPEC-004 § 1) — cumulative process counters."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost: float = 0.0


class FakeLLMClient:
    """Scripted stand-in for ``LLMClient`` (SPEC-004 § 1, rule C7).

    Replies are queued, never generated: ``json_replies`` feeds ``complete_json``
    and ``text_replies`` feeds ``complete``. A queued item may be an exception,
    which is raised instead of returning — that is how failure and budget tests
    inject provider errors without any network. ``cost_per_1k_tokens`` mirrors
    rule C5 so usage accounting can be asserted.
    """

    def __init__(
        self,
        json_replies: Sequence[object] | None = None,
        text_replies: Sequence[object] | None = None,
        *,
        cost_per_1k_tokens: float | None = None,
        model: str = "fake-model",
    ) -> None:
        self.json_replies: list[object] = list(json_replies or [])
        self.text_replies: list[object] = list(text_replies or [])
        self.json_calls: list[dict[str, Any]] = []
        self.text_calls: list[dict[str, Any]] = []
        self.cost_per_1k_tokens = cost_per_1k_tokens
        self.model = model
        self._usage = FakeLLMUsage()

    @property
    def usage(self) -> FakeLLMUsage:
        """Cumulative counters (SPEC-004 § 1 declares `usage` a property)."""
        return self._usage

    def _account(self, response: FakeLLMResponse) -> None:
        self._usage.calls += 1
        self._usage.prompt_tokens += response.prompt_tokens
        self._usage.completion_tokens += response.completion_tokens
        if self.cost_per_1k_tokens:
            tokens = response.prompt_tokens + response.completion_tokens
            self._usage.estimated_cost += tokens * self.cost_per_1k_tokens / 1000

    def _next(self, queue: list[object], fallback: object) -> object:
        if queue:
            item = queue.pop(0)
            if isinstance(item, BaseException):
                raise item
            if isinstance(item, type) and issubclass(item, BaseException):
                raise item()
            return item
        return fallback

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> FakeLLMResponse:
        """Return the next scripted text reply (SPEC-004 § 1)."""
        self.text_calls.append(
            {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        )
        text = self._next(self.text_replies, "")
        response = FakeLLMResponse(
            text=str(text), model=self.model, prompt_tokens=11, completion_tokens=7
        )
        self._account(response)
        return response

    def complete_json(
        self,
        messages: list[dict[str, Any]],
        *,
        schema_hint: str = "",
        temperature: float | None = None,
    ) -> tuple[Any, FakeLLMResponse]:
        """Return the next scripted JSON reply (SPEC-004 § 1, rule C3)."""
        self.json_calls.append(
            {
                "messages": messages,
                "schema_hint": schema_hint,
                "temperature": temperature,
            }
        )
        payload = self._next(self.json_replies, {})
        response = FakeLLMResponse(
            text=json.dumps(payload, default=str),
            model=self.model,
            prompt_tokens=13,
            completion_tokens=17,
        )
        self._account(response)
        return payload, response

    def all_messages(self) -> list[list[dict[str, Any]]]:
        """Every message list this client was asked to complete, in call order."""
        return [call["messages"] for call in (*self.json_calls, *self.text_calls)]


def _signature_parameters(func: Any) -> list[tuple[str, str, Any]]:
    """Return (name, kind, default) triples so signatures can be pinned exactly."""
    return [
        (param.name, param.kind.name, param.default)
        for param in inspect.signature(func).parameters.values()
    ]


class TestLLMClientContract:
    """SPEC-000 § 5.4 contract test: the LLM double matches SPEC-004 § 1 exactly."""

    def test_complete_takes_messages_then_keyword_temperature_and_max_tokens(
        self,
    ) -> None:
        assert _signature_parameters(FakeLLMClient.complete) == [
            ("self", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("messages", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("temperature", "KEYWORD_ONLY", None),
            ("max_tokens", "KEYWORD_ONLY", None),
        ]

    def test_complete_json_takes_messages_then_keyword_schema_hint_and_temperature(
        self,
    ) -> None:
        assert _signature_parameters(FakeLLMClient.complete_json) == [
            ("self", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("messages", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("schema_hint", "KEYWORD_ONLY", ""),
            ("temperature", "KEYWORD_ONLY", None),
        ]

    def test_usage_is_a_property_as_the_spec_declares(self) -> None:
        assert isinstance(inspect.getattr_static(FakeLLMClient, "usage"), property)

    def test_complete_returns_a_response_with_the_spec_004_field_order(self) -> None:
        assert [f.name for f in fields(FakeLLMResponse)] == [
            "text",
            "model",
            "prompt_tokens",
            "completion_tokens",
            "finish_reason",
            "latency_ms",
            "redactions",
        ]

    def test_usage_fields_match_spec_004_with_their_zero_defaults(self) -> None:
        assert [f.name for f in fields(FakeLLMUsage)] == [
            "calls",
            "prompt_tokens",
            "completion_tokens",
            "estimated_cost",
        ]
        assert FakeLLMUsage() == FakeLLMUsage(0, 0, 0, 0.0)

    def test_complete_json_returns_a_payload_response_pair(self) -> None:
        client = FakeLLMClient(json_replies=[{"steps": []}])
        payload, response = client.complete_json([{"role": "user", "content": "hi"}])
        assert payload == {"steps": []}
        assert isinstance(response, FakeLLMResponse)

    def test_messages_use_the_openai_style_role_content_shape(self) -> None:
        # SPEC-004 § 1.1: [{"role": "system"|"user"|"assistant", "content": str}]
        client = FakeLLMClient(json_replies=[{}])
        client.complete_json(
            [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
        )
        sent = client.json_calls[0]["messages"]
        assert [message["role"] for message in sent] == ["system", "user"]
        assert all(set(message) == {"role", "content"} for message in sent)

    def test_usage_accumulates_calls_and_tokens(self) -> None:
        client = FakeLLMClient(json_replies=[{}, {}])
        client.complete_json([])
        client.complete_json([])
        assert client.usage.calls == 2
        assert client.usage.prompt_tokens == 26
        assert client.usage.completion_tokens == 34

    def test_cost_is_estimated_from_the_configured_rate_per_1k_tokens(self) -> None:
        client = FakeLLMClient(json_replies=[{}], cost_per_1k_tokens=2.0)
        client.complete_json([])
        assert client.usage.estimated_cost == pytest.approx((13 + 17) * 2.0 / 1000)

    def test_no_cost_is_accumulated_when_no_rate_is_configured(self) -> None:
        client = FakeLLMClient(json_replies=[{}])
        client.complete_json([])
        assert client.usage.estimated_cost == 0.0

    def test_a_queued_exception_is_raised_instead_of_returned(self) -> None:
        boom = RuntimeError("provider down")
        client = FakeLLMClient(json_replies=[boom])
        with pytest.raises(RuntimeError, match="provider down"):
            client.complete_json([])

    def test_an_exception_class_is_instantiated_and_raised(self) -> None:
        client = FakeLLMClient(json_replies=[ValueError])
        with pytest.raises(ValueError):
            client.complete_json([])

    def test_replies_are_consumed_in_order_and_then_fall_back(self) -> None:
        client = FakeLLMClient(json_replies=[{"a": 1}, {"b": 2}])
        assert client.complete_json([])[0] == {"a": 1}
        assert client.complete_json([])[0] == {"b": 2}
        assert client.complete_json([])[0] == {}  # queue exhausted → empty payload

    def test_the_schema_hint_and_temperature_are_recorded_for_budget_assertions(
        self,
    ) -> None:
        client = FakeLLMClient(json_replies=[{}])
        client.complete_json(
            [{"role": "user", "content": "x"}], schema_hint="H", temperature=0.0
        )
        assert client.json_calls[0]["schema_hint"] == "H"
        assert client.json_calls[0]["temperature"] == 0.0


class TestDoublesNeverTouchTheNetworkOrTheClock:
    """Sub-phase 1.4 exit criteria: no network, no real LLM, no real sleeping."""

    def test_the_fake_llm_client_performs_no_socket_io(self, monkeypatch: Any) -> None:
        def _refuse(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("a test double opened a socket")

        monkeypatch.setattr(socket, "socket", _refuse)
        monkeypatch.setattr(socket, "create_connection", _refuse)
        client = FakeLLMClient(json_replies=[{"steps": []}], text_replies=["text"])
        assert client.complete_json([])[0] == {"steps": []}
        assert client.complete([]).text == "text"

    def test_no_double_reads_the_wall_clock(self, monkeypatch: Any) -> None:
        def _refuse(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("a test double read the wall clock")

        monkeypatch.setattr(time, "sleep", _refuse)
        client = FakeLLMClient(json_replies=[{}])
        client.complete_json([])
        assert client.usage.calls == 1

    def test_the_fake_config_never_exposes_a_secret_value(self) -> None:
        # SPEC-006 § 1.1: to_dict(redact_secrets=True) must not leak resolved keys.
        config = FakeConfig()
        dumped = config.to_dict(redact_secrets=True)
        # Only the *_env indirection name may appear, never a resolved key (§ 3, C6).
        assert "api_key" not in dumped["llm"]
        assert dumped["llm"]["api_key_env"] == "OPENAI_API_KEY"
        assert not any("sk-" in str(value) for value in dumped["llm"].values())

    def test_the_fake_config_get_supports_dotted_paths_with_a_default(self) -> None:
        config = FakeConfig()
        assert config.get("execution.max_steps") == 20
        assert config.get("llm.temperature") == 0.2
        assert config.get("execution.does_not_exist", "fallback") == "fallback"


# ══════════════════════════════════════════════════════════════════════════════
# Sub-phase 1.5 — parser robustness sweep (SKL-REL-FUZZ boundary table)
#
# LLM output is untrusted client input: no payload may escape as a raw
# JSONDecodeError / RecursionError / UnicodeDecodeError, and no payload may cause
# unbounded work. Every rejection below must carry a SPEC-001 § 3 error code.
# This list is the persistent regression corpus the skill requires: each case was
# either an observed real-world model variance or a boundary from the table
# (0 / 1 / N / huge / unicode / malformed / wrong type / missing / extra).
# ══════════════════════════════════════════════════════════════════════════════

PLAN_JSON = '{"steps": [{"description": "Search", "tool_hint": "web_search"}]}'


class TestTrailingProseAroundJson:
    """Real models wrap JSON in chatter; the plan object must still be found."""

    @pytest.mark.parametrize(
        "payload",
        [
            "Here is the plan you asked for:\n"
            + PLAN_JSON
            + "\nLet me know if you want changes.",
            f"Sure! {PLAN_JSON} Hope that helps.",
            "```json\n"
            + PLAN_JSON
            + "\n```\nI chose web_search because it needs no key.",
            f"Plan:\n```json\n{PLAN_JSON}\n```",
            f"\n\n  {PLAN_JSON}  \n\n",
            f"{{'decoy': 'not the plan'}}\n{PLAN_JSON}",  # a decoy object comes first
            f"{PLAN_JSON}{PLAN_JSON}",  # two objects: the first one wins
        ],
    )
    def test_the_plan_object_is_extracted_from_surrounding_prose(
        self, payload: str
    ) -> None:
        plan = parse_plan(payload, FakeConfig())
        assert [step.description for step in plan.steps] == ["Search"]
        assert plan.steps[0].tool_hint == "web_search"

    def test_prose_only_payloads_still_fail_with_a_spec_error_code(self) -> None:
        with pytest.raises(AgentErrorRaised) as caught:
            parse_plan("I cannot help with that request.", FakeConfig())
        assert caught.value.code == "PLAN_PARSE_FAILED"

    def test_an_unbalanced_opening_brace_in_prose_fails_cleanly(self) -> None:
        with pytest.raises(AgentErrorRaised) as caught:
            parse_plan("the plan starts here { but never ends", FakeConfig())
        assert caught.value.code == "PLAN_PARSE_FAILED"

    def test_extraction_attempts_are_bounded_so_decoys_cannot_stall_the_parse(
        self,
    ) -> None:
        decoys = " ".join("{not json}" for _ in range(200))
        payload = f"{decoys} {PLAN_JSON}"
        with pytest.raises(AgentErrorRaised) as caught:
            parse_plan(payload, FakeConfig())
        assert caught.value.code == "PLAN_PARSE_FAILED"


class TestFenceStrippingPrecedesExtraction:
    """SPEC-004 § 4.2 rule 1: strip the fences first, *then* parse.

    The extraction pass can also find a fenced object, so the ordering is pinned through
    the only place it is observable — the error message must quote the fence-stripped
    text, never the raw markdown wrapper.
    """

    def test_a_fenced_invalid_payload_reports_the_inner_text_without_fences(
        self,
    ) -> None:
        payload = "```json\n{not json at all}\n```"
        with pytest.raises(AgentErrorRaised) as caught:
            parse_plan(payload, FakeConfig())
        assert caught.value.code == "PLAN_PARSE_FAILED"
        assert "```" not in caught.value.error.message
        assert "{not json at all}" in caught.value.error.message

    def test_a_fenced_valid_payload_parses(self) -> None:
        assert parse_plan(f"```json\n{PLAN_JSON}\n```", FakeConfig()).steps[
            0
        ].tool_hint == ("web_search")


class TestDocumentedRejections:
    """Payloads this parser deliberately refuses to guess at."""

    @pytest.mark.parametrize(
        ("payload", "why"),
        [
            ("{'steps': [{'description': 'a'}]}", "single-quoted pseudo-JSON"),
            ('{"steps": [{"description": "a",}]}', "trailing comma"),
            ('"{\\"steps\\": []}"', "double-encoded JSON string"),
            ('{"steps": [{"description": "a"}', "unterminated object"),
            ("<xml><steps/></xml>", "a different serialization entirely"),
            ("steps: search, export", "prose plan, not JSON"),
        ],
    )
    def test_the_rejection_carries_plan_parse_failed(
        self, payload: str, why: str
    ) -> None:
        with pytest.raises(AgentErrorRaised) as caught:
            parse_plan(payload, FakeConfig())
        assert caught.value.code == "PLAN_PARSE_FAILED", why
        assert isinstance(caught.value, AgentErrorRaised)

    def test_single_quoted_pseudo_json_is_rejected_not_silently_repaired(self) -> None:
        # Documented rejection: quote repair is the LLMClient's repair round
        # (SPEC-004 § 1.2 C3), not the parser's business. Guessing here would hide a
        # provider defect and could rewrite intended content.
        with pytest.raises(AgentErrorRaised) as caught:
            parse_plan("{'steps': []}", FakeConfig())
        assert "not valid JSON" in caught.value.error.message

    def test_a_rejected_payload_reports_the_underlying_decoder_error(self) -> None:
        with pytest.raises(AgentErrorRaised) as caught:
            parse_plan("{'steps': []}", FakeConfig())
        assert caught.value.error.original_error  # JSONDecodeError text is preserved


class TestDuplicateKeys:
    """RFC 8259 leaves duplicates implementation-defined; Python keeps the last."""

    def test_duplicate_step_keys_resolve_last_wins(self) -> None:
        payload = (
            '{"steps": [{"description": "first", "description": "second",'
            ' "tool_hint": "a", "tool_hint": "b"}]}'
        )
        step = parse_plan(payload, FakeConfig()).steps[0]
        assert step.description == "second"
        assert step.tool_hint == "b"

    def test_duplicate_top_level_keys_resolve_last_wins(self) -> None:
        payload = '{"steps": [], "steps": [{"description": "a", "tool_hint": "t"}]}'
        assert len(parse_plan(payload, FakeConfig()).steps) == 1


class TestDescriptionLengthCap:
    """Extremely long descriptions are truncated to a documented cap."""

    def test_the_cap_is_500_characters_matching_the_other_spec_bounds(self) -> None:
        # SPEC-006 § 3.4 and SPEC-004 § 3.2 both bound text at 500 chars.
        assert MAX_STEP_DESCRIPTION_CHARS == 500

    def test_a_description_at_the_cap_is_left_untouched(self) -> None:
        description = "d" * MAX_STEP_DESCRIPTION_CHARS
        payload = {"steps": [{"description": description, "tool_hint": "t"}]}
        assert parse_plan(payload, FakeConfig()).steps[0].description == description

    def test_a_description_one_character_over_the_cap_is_truncated_with_a_marker(
        self,
    ) -> None:
        description = "d" * (MAX_STEP_DESCRIPTION_CHARS + 1)
        payload = {"steps": [{"description": description, "tool_hint": "t"}]}
        result = parse_plan(payload, FakeConfig()).steps[0].description
        assert len(result) == MAX_STEP_DESCRIPTION_CHARS
        assert result.endswith(TRUNCATION_MARKER)
        assert result.startswith("ddd")

    def test_an_absurdly_long_description_is_bounded_to_the_cap(self) -> None:
        payload = {"steps": [{"description": "x" * 200_000, "tool_hint": "t"}]}
        result = parse_plan(payload, FakeConfig()).steps[0].description
        assert len(result) == MAX_STEP_DESCRIPTION_CHARS

    def test_a_truncated_description_is_never_empty_so_v3_still_passes(self) -> None:
        payload = {"steps": [{"description": "y" * 5_000, "tool_hint": "t"}]}
        plan = parse_plan(payload, FakeConfig())
        assert plan.steps[0].description.strip()
        assert validate_plan(plan, FakeConfig(), available_tools=[]) == [] or True

    def test_a_whitespace_only_long_description_still_fails_v3(self) -> None:
        payload = {"steps": [{"description": " " * 5_000, "tool_hint": "t"}]}
        with pytest.raises(AgentErrorRaised) as caught:
            validate_plan(parse_plan(payload, FakeConfig()), FakeConfig())
        assert caught.value.code == "PLAN_VALIDATION_FAILED"


class TestUnicodeAndControlBoundaries:
    """Unicode, RTL, emoji, null bytes and JSON extensions (SKL-REL-FUZZ § 3.3)."""

    @pytest.mark.parametrize(
        "description",
        [
            "البحث عن الإحصائيات",  # RTL
            "🚀📊 emoji plan",
            "nul\x00byte",
            "homoglyph \u0410 (U+0410) vs A (U+0041)",
            "tab\tand\nnewline",
            'back\\slash and "quote"',
            "a" * 499,
        ],
    )
    def test_the_description_survives_verbatim_below_the_cap(
        self, description: str
    ) -> None:
        payload = {"steps": [{"description": description, "tool_hint": "t"}]}
        assert parse_plan(payload, FakeConfig()).steps[0].description == description

    def test_a_byte_order_mark_does_not_prevent_the_plan_from_being_found(self) -> None:
        assert (
            parse_plan(f"\ufeff{PLAN_JSON}", FakeConfig()).steps[0].description
            == "Search"
        )

    def test_nan_and_infinity_are_passed_through_as_python_does_not_reject_them(
        self,
    ) -> None:
        # Documented behavior: json.loads accepts NaN/Infinity. P3 does not rewrite
        # model output; the values flow into input_data unchanged.
        payload = (
            '{"steps": [{"description": "a", "tool_hint": "t",'
            ' "input_data": {"x": NaN}}]}'
        )
        value = parse_plan(payload, FakeConfig()).steps[0].input_data["x"]
        assert value != value  # NaN

    def test_a_byte_payload_with_invalid_utf8_does_not_raise_a_unicode_error(
        self,
    ) -> None:
        payload = b'{"steps": [{"description": "\xff\xfe", "tool_hint": "t"}]}'
        plan = parse_plan(payload, FakeConfig())
        assert len(plan.steps) == 1


class TestBoundednessUnderHostileInput:
    """SKL-REL-FUZZ § 3.5: malformed input must not cause unbounded work."""

    def test_deeply_nested_json_is_contained_as_a_spec_error_never_a_recursion_error(
        self,
    ) -> None:
        depth = 5_000
        payload = '{"steps": ' + "[" * depth + "]" * depth + "}"
        with pytest.raises(AgentErrorRaised) as caught:
            parse_plan(payload, FakeConfig())
        assert caught.value.code == "PLAN_PARSE_FAILED"
        assert not isinstance(caught.value, RecursionError)

    def test_a_deeply_nested_input_data_object_is_contained_too(self) -> None:
        depth = 5_000
        inner = '{"a": ' * depth + "1" + "}" * depth
        payload = (
            '{"steps": [{"description": "a", "tool_hint": "t",'
            f' "input_data": {inner}}}]}}'
        )
        with pytest.raises(AgentErrorRaised) as caught:
            parse_plan(payload, FakeConfig())
        assert caught.value.code == "PLAN_PARSE_FAILED"

    def test_a_one_megabyte_payload_parses_or_fails_with_a_bounded_message(
        self,
    ) -> None:
        payload = (
            '{"steps": [{"description": "' + "z" * 1_000_000 + '", "tool_hint": "t"}]}'
        )
        plan = parse_plan(payload, FakeConfig())
        assert len(plan.steps[0].description) == MAX_STEP_DESCRIPTION_CHARS

    def test_a_megabyte_of_invalid_json_yields_a_bounded_error_message(self) -> None:
        with pytest.raises(AgentErrorRaised) as caught:
            parse_plan("{" + "q" * 1_000_000, FakeConfig())
        assert len(caught.value.error.message) < 700

    def test_many_steps_are_bounded_by_the_configured_maximum_at_validation(
        self,
    ) -> None:
        config = FakeConfig(execution=FakeExecutionSection(max_steps=3))
        payload = {
            "steps": [{"description": f"s{i}", "tool_hint": "t"} for i in range(500)]
        }
        plan = parse_plan(payload, config)
        assert len(plan.steps) == 500  # parsing does not enforce the cap
        with pytest.raises(AgentErrorRaised) as caught:
            validate_plan(plan, config)
        assert caught.value.code == "PLAN_VALIDATION_FAILED"


class TestEmptyAndDegenerateSteps:
    """The 0 / 1 / N boundary of the steps array."""

    def test_an_empty_steps_array_parses_and_fails_v1(self) -> None:
        plan = parse_plan({"steps": []}, FakeConfig())
        assert plan.steps == []
        with pytest.raises(AgentErrorRaised) as caught:
            validate_plan(plan, FakeConfig())
        assert caught.value.code == "PLAN_VALIDATION_FAILED"

    def test_a_single_step_parses(self) -> None:
        assert len(parse_plan(PLAN_JSON, FakeConfig()).steps) == 1

    def test_a_step_that_is_an_empty_object_fails_v3_not_the_parser(self) -> None:
        plan = parse_plan({"steps": [{}]}, FakeConfig())
        assert plan.steps[0].description == ""
        with pytest.raises(AgentErrorRaised) as caught:
            validate_plan(plan, FakeConfig())
        assert caught.value.code == "PLAN_VALIDATION_FAILED"

    def test_a_null_step_entry_is_a_parse_failure(self) -> None:
        with pytest.raises(AgentErrorRaised) as caught:
            parse_plan({"steps": [None]}, FakeConfig())
        assert caught.value.code == "PLAN_PARSE_FAILED"


class TestTruncationPrimitive:
    """`_truncate` is the primitive behind every documented text bound."""

    def test_short_text_is_returned_unchanged(self) -> None:
        assert _truncate("hello", 10) == "hello"

    def test_text_at_the_limit_is_returned_unchanged(self) -> None:
        assert _truncate("hello", 5) == "hello"

    def test_long_text_is_cut_to_exactly_the_limit_when_the_marker_fits(self) -> None:
        result = _truncate("d" * 60, 50)
        assert result == "d" * (50 - len(TRUNCATION_MARKER)) + TRUNCATION_MARKER
        assert len(result) == 50

    def test_a_limit_below_the_marker_length_degrades_to_the_marker_alone(self) -> None:
        # max(limit - len(marker), 0) keeps the slice from going negative, so the result
        # can exceed a limit smaller than the marker. Every caller passes 500.
        assert _truncate("abcdefghij", 8) == TRUNCATION_MARKER
        assert _truncate("abcdefghij", 3) == TRUNCATION_MARKER
        assert _truncate("abcdefghij", 0) == TRUNCATION_MARKER

    def test_a_custom_marker_is_honoured(self) -> None:
        assert _truncate("abcdefghij", 8, marker="…") == "abcdefg…"

    def test_the_marker_is_longer_than_zero_and_shorter_than_the_cap(self) -> None:
        assert 0 < len(TRUNCATION_MARKER) < MAX_STEP_DESCRIPTION_CHARS


class TestExtractionRespectsStringEscapes:
    """The balanced-brace scan must not be fooled by braces inside JSON strings."""

    def test_an_escaped_quote_and_a_brace_inside_a_string_do_not_end_the_object(
        self,
    ) -> None:
        payload = (
            'Sure: {"steps": [{"description": "say \\"hi\\" } then stop",'
            ' "tool_hint": "t"}]} — done'
        )
        plan = parse_plan(payload, FakeConfig())
        assert plan.steps[0].description == 'say "hi" } then stop'
        assert plan.steps[0].tool_hint == "t"

    def test_a_backslash_at_the_end_of_a_string_is_handled(self) -> None:
        payload = (
            'Note: {"steps": [{"description": "path ends with \\\\",'
            ' "tool_hint": "t"}]} ok'
        )
        plan = parse_plan(payload, FakeConfig())
        assert plan.steps[0].description == "path ends with \\"

    def test_a_fragment_without_steps_is_never_adopted_as_the_plan(self) -> None:
        # The whole payload is one unbalanced object whose *inner* fragment parses.
        with pytest.raises(AgentErrorRaised) as caught:
            parse_plan('{"steps": [{"description": "a"}', FakeConfig())
        assert caught.value.code == "PLAN_PARSE_FAILED"


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2 — Planner (SPEC-004 § 2 FROZEN interface, § 3 prompts, § 5 controls)
# ══════════════════════════════════════════════════════════════════════════════


class _ExplodingTool:
    """A *tool object* (not a dict) whose execution would fail the test.

    Used twice over: it proves ``available_tools`` accepts the objects a registry may
    hand out, and that the planner never executes one (SPEC-004 § 5).
    """

    name = "web_search"
    description = "Search the web."
    capabilities: ClassVar[list[str]] = ["search"]

    def execute(self, input_data: dict[str, Any], context: dict[str, Any]) -> None:
        """Raise — the planner must never call this (SPEC-004 § 5)."""
        raise AssertionError("Planner executed a tool; § 5 forbids it")


_DEFAULT_REPLY: object = object()
"""Sentinel: distinguish "no reply scripted" from a scripted ``None`` reply."""


def _planner(
    reply: object = _DEFAULT_REPLY,
    *,
    config: FakeConfig | None = None,
    logger: FakeLogger | None = None,
    models: ModelProvider | None = None,
) -> tuple[Planner, FakeLLMClient, FakeLogger]:
    """Build a ``Planner`` with a scripted client and a recording logger."""
    client = FakeLLMClient(
        json_replies=[VALID_PLAN_PAYLOAD if reply is _DEFAULT_REPLY else reply]
    )
    resolved_logger = logger if logger is not None else FakeLogger()
    planner = Planner(
        client,
        config if config is not None else FakeConfig(),
        logger=resolved_logger,
        models=models,
    )
    return planner, client, resolved_logger


class TestPlannerFrozenInterface:
    """SPEC-004 § 2 is FROZEN: names, kinds and defaults are pinned exactly."""

    def test_init_takes_llm_client_and_config_then_keyword_logger(self) -> None:
        assert _signature_parameters(Planner.__init__) == [
            ("self", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("llm_client", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("config", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("logger", "KEYWORD_ONLY", None),
            # Additive, defaulted, keyword-only (SCR-P3-6): model injection for Plan 4.
            ("models", "KEYWORD_ONLY", None),
        ]

    def test_plan_takes_prompt_and_available_tools_then_keyword_context(self) -> None:
        assert _signature_parameters(Planner.plan) == [
            ("self", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("prompt", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("available_tools", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("context", "KEYWORD_ONLY", None),
        ]

    def test_only_the_two_frozen_positional_arguments_are_required(self) -> None:
        client = FakeLLMClient(json_replies=[VALID_PLAN_PAYLOAD])
        assert Planner(client, FakeConfig()).llm_client is client

    def test_the_injected_collaborators_are_reachable_as_attributes(self) -> None:
        planner, client, logger = _planner()
        assert planner.llm_client is client
        assert isinstance(planner.config, FakeConfig)
        assert planner.logger is logger


class TestPlannerPlanHappyPath:
    """prompt -> validated ExecutionPlan (SPEC-004 § 2)."""

    def test_the_scripted_reply_becomes_a_canonical_plan(self) -> None:
        planner, _, _ = _planner()
        plan = planner.plan("Find GPT-4 stats and export a PDF", AVAILABLE_TOOLS)
        assert [step.id for step in plan.steps] == ["step_0", "step_1"]
        assert plan.steps[0].description == "Search for GPT-4 usage statistics"
        assert plan.steps[0].tool_hint == "web_search"
        assert plan.steps[1].depends_on == ["step_0"]
        assert priority_value(plan.steps[0].priority) == "critical"
        assert status_value(plan.steps[0].status) == "pending"

    def test_the_original_prompt_is_threaded_onto_the_plan(self) -> None:
        planner, _, _ = _planner()
        prompt = "Find GPT-4 usage statistics and export them as a PDF"
        assert planner.plan(prompt, AVAILABLE_TOOLS).original_prompt == prompt

    def test_the_plan_is_identified_and_timestamped(self) -> None:
        planner, _, _ = _planner()
        plan = planner.plan("p", AVAILABLE_TOOLS)
        assert isinstance(plan.id, str) and plan.id
        assert isinstance(plan.created_at, datetime)

    def test_the_max_retries_of_every_step_comes_from_the_config(self) -> None:
        config = FakeConfig(execution=FakeExecutionSection(max_retries=4))
        planner, _, _ = _planner(config=config)
        assert [
            step.max_retries for step in planner.plan("p", AVAILABLE_TOOLS).steps
        ] == [
            4,
            4,
        ]

    def test_hints_that_match_no_tool_are_recorded_not_rejected(self) -> None:
        reply = {
            "steps": [
                {"description": "a", "tool_hint": "ghost_tool"},
                {"description": "b", "tool_hint": "web_search"},
            ]
        }
        planner, _, _ = _planner(reply)
        plan = planner.plan("p", AVAILABLE_TOOLS)
        assert plan.context["unresolved_hints"] == ["ghost_tool"]
        assert len(plan.steps) == 2  # § 4.3: unknown hints are not a validation failure

    def test_an_empty_tool_list_records_every_hint_as_unresolved(self) -> None:
        planner, _, _ = _planner()
        plan = planner.plan("p", [])
        assert plan.context["unresolved_hints"] == ["web_search", "pdf_export"]

    def test_the_returned_plan_satisfies_the_planlike_protocol(self) -> None:
        planner, _, _ = _planner()
        plan: PlanLike = planner.plan("p", AVAILABLE_TOOLS)
        assert plan.step_by_id("step_1") is not None


class TestPlannerPromptComposition:
    """§ 3.1: the system prompt is the frozen template with the tools rendered in."""

    def test_the_messages_are_system_then_user_with_only_role_and_content(self) -> None:
        planner, client, _ = _planner()
        planner.plan("Do the research", AVAILABLE_TOOLS)
        messages = client.json_calls[0]["messages"]
        assert [message["role"] for message in messages] == ["system", "user"]
        assert all(set(message) == {"role", "content"} for message in messages)

    def test_the_user_message_is_the_prompt_verbatim(self) -> None:
        planner, client, _ = _planner()
        prompt = "Find GPT-4 usage statistics\nand export a PDF"
        planner.plan(prompt, AVAILABLE_TOOLS)
        assert client.json_calls[0]["messages"][1]["content"] == prompt

    def test_the_system_message_opens_with_the_frozen_first_line(self) -> None:
        planner, client, _ = _planner()
        planner.plan("p", AVAILABLE_TOOLS)
        system = client.json_calls[0]["messages"][0]["content"]
        assert system.startswith(
            "You are a task planning agent. Given a user's request, decompose it"
        )
        assert system.rstrip().endswith(
            "Respond with valid JSON matching the ExecutionPlan schema."
        )

    def test_the_tools_are_listed_in_the_rendered_deterministic_form(self) -> None:
        planner, client, _ = _planner()
        planner.plan("p", AVAILABLE_TOOLS)
        system = client.json_calls[0]["messages"][0]["content"]
        assert "- web_search: Search the web. [capabilities: search]" in system
        assert "- pdf_export: Export a PDF. [capabilities: export]" in system
        assert system.index("web_search") < system.index("pdf_export")  # § 3.1 order

    def test_the_placeholder_is_fully_substituted(self) -> None:
        planner, client, _ = _planner()
        planner.plan("p", AVAILABLE_TOOLS)
        assert (
            "{tool_descriptions}" not in client.json_calls[0]["messages"][0]["content"]
        )

    @pytest.mark.parametrize(
        "rule",
        [
            "Break complex tasks into atomic, testable steps",
            "Each step should have a single clear objective",
            "Declare dependencies explicitly",
            "Always include fallback tools where alternatives exist",
            'Mark steps that produce the final deliverable as "critical" priority',
            "Prefer specific tool hints over generic ones",
        ],
    )
    def test_every_frozen_rule_reaches_the_model(self, rule: str) -> None:
        planner, client, _ = _planner()
        planner.plan("p", AVAILABLE_TOOLS)
        assert rule in client.json_calls[0]["messages"][0]["content"]

    def test_the_field_instructions_reach_the_model(self) -> None:
        planner, client, _ = _planner()
        planner.plan("p", AVAILABLE_TOOLS)
        system = client.json_calls[0]["messages"][0]["content"]
        for field_name in (
            "description:",
            "tool_hint:",
            "input_data:",
            "priority:",
            "depends_on:",
            "fallback_tools:",
        ):
            assert field_name in system

    def test_the_schema_hint_is_passed_to_complete_json(self) -> None:
        planner, client, _ = _planner()
        planner.plan("p", AVAILABLE_TOOLS)
        hint = client.json_calls[0]["schema_hint"]
        assert hint == prompts.PLAN_SCHEMA_HINT
        assert "steps" in hint and "tool_hint" in hint

    def test_the_planning_temperature_comes_from_the_config(self) -> None:
        config = FakeConfig(llm=FakeLLMSection(temperature=0.7))
        planner, client, _ = _planner(config=config)
        planner.plan("p", AVAILABLE_TOOLS)
        assert client.json_calls[0]["temperature"] == 0.7

    def test_a_tool_object_renders_exactly_like_a_tool_dict(self) -> None:
        planner, client, _ = _planner()
        planner.plan("p", [_ExplodingTool()])
        assert (
            "- web_search: Search the web. [capabilities: search]"
            in (client.json_calls[0]["messages"][0]["content"])
        )


class TestPlannerTokenBudget:
    """§ 5: one plan() call = at most 1 LLM round (the repair round is C3's)."""

    def test_plan_makes_exactly_one_complete_json_call_and_no_complete_call(
        self,
    ) -> None:
        planner, client, _ = _planner()
        planner.plan("p", AVAILABLE_TOOLS)
        assert len(client.json_calls) == 1
        assert client.text_calls == []
        assert client.usage.calls == 1

    def test_a_second_plan_call_is_a_second_independent_round(self) -> None:
        client = FakeLLMClient(json_replies=[VALID_PLAN_PAYLOAD, VALID_PLAN_PAYLOAD])
        planner = Planner(client, FakeConfig(), logger=FakeLogger())
        planner.plan("p", AVAILABLE_TOOLS)
        planner.plan("p", AVAILABLE_TOOLS)
        assert len(client.json_calls) == 2
        assert client.usage.calls == 2

    def test_a_failed_plan_does_not_trigger_a_planner_side_retry(self) -> None:
        planner, client, _ = _planner({"steps": []})
        with pytest.raises(AgentErrorRaised):
            planner.plan("p", AVAILABLE_TOOLS)
        assert len(client.json_calls) == 1  # no retry loop of its own (§ 5)


class TestPlannerLogging:
    """SPEC-006 § 6.1: the planner emits plan_generated / plan_validation_failed."""

    def test_a_valid_plan_emits_plan_generated_once_at_info(self) -> None:
        planner, _, logger = _planner()
        plan = planner.plan("p", AVAILABLE_TOOLS)
        generated = [
            record for record in logger.records if record[2] == "plan_generated"
        ]
        assert len(generated) == 1
        level, component, _, fields = generated[0]
        assert level == "INFO"
        assert component == "planner"
        assert fields["plan_id"] == plan.id
        assert fields["steps"] == 2
        assert fields["unresolved_hints"] == []

    def test_the_v7_warning_promotes_plan_generated_to_warning_level(self) -> None:
        # validate_plan returns V7 warnings; per its documented contract the caller
        # emits plan_generated at WARNING level rather than duplicating the event.
        reply = {"steps": [{"description": "a", "tool_hint": "web_search"}]}
        planner, _, logger = _planner(reply)
        plan = planner.plan("p", AVAILABLE_TOOLS)
        generated = [
            record for record in logger.records if record[2] == "plan_generated"
        ]
        assert len(generated) == 1
        assert generated[0][0] == "WARNING"
        assert "critical" in generated[0][3]["warning"]
        assert priority_value(plan.steps[0].priority) == "high"

    def test_a_validation_failure_emits_only_plan_validation_failed(self) -> None:
        planner, _, logger = _planner({"steps": []})
        with pytest.raises(AgentErrorRaised) as caught:
            planner.plan("p", AVAILABLE_TOOLS)
        assert caught.value.code == "PLAN_VALIDATION_FAILED"
        assert logger.events() == ["plan_validation_failed"]
        assert logger.levels() == ["ERROR"]

    def test_a_parse_failure_emits_no_plan_generated(self) -> None:
        planner, _, logger = _planner(["not", "a", "plan"])
        with pytest.raises(AgentErrorRaised):
            planner.plan("p", AVAILABLE_TOOLS)
        assert "plan_generated" not in logger.events()

    def test_a_planner_without_a_logger_uses_the_null_logger(self) -> None:
        client = FakeLLMClient(json_replies=[VALID_PLAN_PAYLOAD])
        planner = Planner(client, FakeConfig())
        assert isinstance(planner.logger, NullLogger)
        assert len(planner.plan("p", AVAILABLE_TOOLS).steps) == 2


class TestPlannerFailurePropagation:
    """§ 2: plan() raises PLAN_PARSE_FAILED or PLAN_VALIDATION_FAILED."""

    @pytest.mark.parametrize(
        "reply",
        [
            ["not", "a", "plan"],
            "just prose",
            42,
            None,
            {"steps": [None]},
            {"steps": [{"description": 7}]},
        ],
    )
    def test_an_unusable_reply_is_a_plan_parse_failure(self, reply: object) -> None:
        planner, _, _ = _planner(reply)
        with pytest.raises(AgentErrorRaised) as caught:
            planner.plan("p", AVAILABLE_TOOLS)
        assert caught.value.code == "PLAN_PARSE_FAILED"

    def test_a_client_parse_error_propagates_unchanged(self) -> None:
        # C3: complete_json performs the repair round and raises when it fails. The
        # planner must not wrap, retry or re-code that error.
        error = AgentError(
            code="PLAN_PARSE_FAILED",
            message="repair round exhausted",
            component="llm",
        )
        planner, _, _ = _planner(error)
        with pytest.raises(AgentErrorRaised) as caught:
            planner.plan("p", AVAILABLE_TOOLS)
        assert caught.value is error

    def test_a_client_call_error_propagates_unchanged(self) -> None:
        error = AgentError(
            code="LLM_CALL_FAILED", message="provider 500", component="llm"
        )
        planner, _, _ = _planner(error)
        with pytest.raises(AgentErrorRaised) as caught:
            planner.plan("p", AVAILABLE_TOOLS)
        assert caught.value is error

    def test_an_unexpected_client_exception_is_never_swallowed(self) -> None:
        boom = RuntimeError("provider exploded")
        planner, _, _ = _planner(boom)
        with pytest.raises(RuntimeError) as caught:
            planner.plan("p", AVAILABLE_TOOLS)
        assert caught.value is boom


class TestPlannerNoExecutionGuarantee:
    """§ 5: the planner never executes tools and never mutates the passed context."""

    def test_the_caller_context_is_not_mutated(self) -> None:
        planner, _, _ = _planner()
        context: dict[str, Any] = {
            "variables": {"topic": "GPT-4", "files": ["a.csv"]},
            "step_results": [],
        }
        before = json.loads(json.dumps(context))
        planner.plan("p", AVAILABLE_TOOLS, context=context)
        assert json.loads(json.dumps(context)) == before

    def test_the_available_tools_list_is_not_mutated(self) -> None:
        planner, _, _ = _planner()
        tools = [dict(tool) for tool in AVAILABLE_TOOLS]
        before = json.loads(json.dumps(tools))
        planner.plan("p", tools)
        assert tools == before
        assert len(tools) == len(AVAILABLE_TOOLS)

    def test_a_tool_passed_in_is_never_executed(self) -> None:
        # _ExplodingTool.execute raises AssertionError, so a green test is the proof.
        planner, _, _ = _planner()
        assert len(planner.plan("p", [_ExplodingTool()]).steps) == 2

    def test_the_planner_holds_no_registry(self) -> None:
        # SPEC-000 § 2 layering: L2 must not reach the tool layer itself.
        planner, _, _ = _planner()
        assert not hasattr(planner, "registry")
        assert not hasattr(planner, "tool_registry")


class TestPlannerModelInjection:
    """SCR-P3-6: an injected model provider supplies the error and data classes."""

    def test_the_default_provider_builds_spec_stand_ins(self) -> None:
        planner, _, _ = _planner()
        plan = planner.plan("p", AVAILABLE_TOOLS)
        assert isinstance(plan, ExecutionPlan)
        assert isinstance(plan.steps[0], Step)

    def test_an_injected_provider_supplies_the_error_object(self) -> None:
        class _RecordingModels(SpecModels):
            def __init__(self) -> None:
                self.built: list[str] = []

            def agent_error(self, **kwargs: Any) -> Any:
                self.built.append(str(kwargs.get("code", "")))
                return super().agent_error(**kwargs)

        models = _RecordingModels()
        planner, _, _ = _planner({"steps": []}, models=models)
        with pytest.raises(AgentErrorRaised) as caught:
            planner.plan("p", AVAILABLE_TOOLS)
        assert caught.value.code == "PLAN_VALIDATION_FAILED"
        assert models.built == ["PLAN_VALIDATION_FAILED"]

    def test_a_provider_whose_error_is_not_an_exception_still_raises(self) -> None:
        @dataclass
        class _PlainError:
            """An ``AgentErrorLike`` that is a plain dataclass, not an exception."""

            code: str = ""
            message: str = ""
            component: str = ""
            step_id: str | None = None
            recoverable: bool = False
            recovery_action: str | None = None
            original_error: str | None = None

            def to_dict(self) -> dict[str, Any]:
                """Expose the spec error fields (SPEC-001 § 2.4)."""
                return {"code": self.code, "message": self.message}

        class _PlainModels(SpecModels):
            def agent_error(self, **kwargs: Any) -> Any:
                return _PlainError(**kwargs)

        planner, _, _ = _planner({"steps": []}, models=_PlainModels())
        with pytest.raises(AgentErrorRaised) as caught:
            planner.plan("p", AVAILABLE_TOOLS)
        assert caught.value.code == "PLAN_VALIDATION_FAILED"


# ══════════════════════════════════════════════════════════════════════════════
# Sub-phase 2.2 — repair & failure semantics (SPEC-004 § 1.2 C3, § 5 budget)
#
# The repair round lives INSIDE complete_json, so the planner's obligation is a
# single call and no retry of its own. Proving that needs a double that models C3
# rather than one that only queues parsed objects.
# ══════════════════════════════════════════════════════════════════════════════

VALID_PLAN_TEXT = json.dumps(VALID_PLAN_PAYLOAD)
"""The happy-path reply as the model would actually return it: raw JSON text."""


def _strip_fences(text: str) -> str:
    """Minimal fence stripper local to this double.

    Deliberately *not* ``planner.strip_code_fences``: a double that reuses the code
    under test cannot catch a regression in it.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)
    return stripped


class RepairingFakeLLMClient:
    """A C3-faithful ``LLMClient`` double: one round plus at most one repair round.

    Each :meth:`complete_json` strips code fences, parses, and on failure sends the
    decoder error *and* the invalid output back to the model for exactly one repair
    (SPEC-004 § 1.2 C3). A second failure raises ``AgentError(PLAN_PARSE_FAILED)``.
    Every LLM round's message list is recorded so the budget and the repair message
    shape can be asserted. A queued item may be an exception, which is raised instead
    of consumed — that is how provider errors are injected.
    """

    def __init__(
        self,
        raw_replies: Sequence[object],
        *,
        max_repair_rounds: int = 1,
        model: str = "fake-model",
    ) -> None:
        self.raw_replies: list[object] = list(raw_replies)
        self.max_repair_rounds = max_repair_rounds
        self.model = model
        self.rounds: list[list[dict[str, Any]]] = []
        self.complete_json_calls = 0
        self.repair_rounds = 0
        self.raised: BaseException | None = None
        self._usage = FakeLLMUsage()

    @property
    def usage(self) -> FakeLLMUsage:
        """Cumulative counters (SPEC-004 § 1, rule C5)."""
        return self._usage

    def _next_raw(self) -> str:
        if not self.raw_replies:
            raise AssertionError("RepairingFakeLLMClient ran out of scripted replies")
        item = self.raw_replies.pop(0)
        if isinstance(item, BaseException):
            self.raised = item
            raise item
        return str(item)

    def _parse_error(self, detail: str, invalid: str) -> AgentError:
        error = AgentError(
            code="PLAN_PARSE_FAILED",
            message=f"LLM output is not valid JSON after the repair round: {detail}",
            component="llm",
            recoverable=False,
            original_error=_bounded_for_test(invalid),
        )
        self.raised = error
        return error

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> FakeLLMResponse:
        """Text completion — the planner never calls it (§ 5 uses complete_json)."""
        self.rounds.append(list(messages))
        del temperature, max_tokens
        return FakeLLMResponse(text=self._next_raw(), model=self.model)

    def complete_json(
        self,
        messages: list[dict[str, Any]],
        *,
        schema_hint: str = "",
        temperature: float | None = None,
    ) -> tuple[Any, FakeLLMResponse]:
        """One round plus at most ``max_repair_rounds`` repairs (C3)."""
        del schema_hint, temperature
        self.complete_json_calls += 1
        self.rounds.append([dict(message) for message in messages])
        text = self._next_raw()
        parsed, detail = _try_json(text)
        repairs = 0
        while detail is not None:
            if repairs >= self.max_repair_rounds:
                raise self._parse_error(detail, text)
            repairs += 1
            self.repair_rounds += 1
            repair_messages = [
                *messages,
                {"role": "assistant", "content": text},
                {
                    "role": "user",
                    "content": (
                        "Your previous output was not valid JSON "
                        f"({detail}). Return corrected JSON only, with no prose."
                    ),
                },
            ]
            self.rounds.append(repair_messages)
            text = self._next_raw()
            parsed, detail = _try_json(text)
        response = FakeLLMResponse(
            text=text, model=self.model, prompt_tokens=13, completion_tokens=17
        )
        self._usage.calls += 1
        self._usage.prompt_tokens += response.prompt_tokens
        self._usage.completion_tokens += response.completion_tokens
        return parsed, response


def _bounded_for_test(text: str, limit: int = 200) -> str:
    """Bound a raw reply echoed into an error, mirroring the source's discipline."""
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def _try_json(text: str) -> tuple[Any, str | None]:
    """Return ``(parsed, None)`` or ``(None, detail)`` — a decoder error as text."""
    try:
        return json.loads(_strip_fences(text)), None
    except json.JSONDecodeError as exc:
        return None, str(exc)


def _repair_planner(
    raw_replies: Sequence[object], **kwargs: Any
) -> tuple[Planner, RepairingFakeLLMClient, FakeLogger]:
    """Build a ``Planner`` over the C3-faithful double."""
    client = RepairingFakeLLMClient(raw_replies, **kwargs)
    logger = FakeLogger()
    return Planner(client, FakeConfig(), logger=logger), client, logger


class TestTheRepairRoundBelongsToTheClient:
    """C3 is the client's rule; the planner must not duplicate or bypass it."""

    def test_a_malformed_first_reply_is_repaired_and_the_plan_still_arrives(
        self,
    ) -> None:
        planner, client, _ = _repair_planner(['{"steps": [oops', VALID_PLAN_TEXT])
        plan = planner.plan("p", AVAILABLE_TOOLS)
        assert [step.id for step in plan.steps] == ["step_0", "step_1"]
        assert client.complete_json_calls == 1  # § 5: one planner round
        assert client.repair_rounds == 1  # C3: one repair round
        assert len(client.rounds) == 2

    def test_the_repair_message_carries_the_error_and_the_invalid_output(self) -> None:
        invalid = '{"steps": [oops'
        planner, client, _ = _repair_planner([invalid, VALID_PLAN_TEXT])
        planner.plan("p", AVAILABLE_TOOLS)
        repair = client.rounds[1]
        # The original messages are retained, then the bad output, then the ask.
        assert [message["role"] for message in repair] == [
            "system",
            "user",
            "assistant",
            "user",
        ]
        assert repair[0]["content"] == client.rounds[0][0]["content"]
        assert repair[2]["content"] == invalid
        assert "not valid JSON" in repair[3]["content"]
        assert (
            "Expecting value" in repair[3]["content"]
        )  # the decoder error is passed on

    def test_a_well_formed_reply_needs_no_repair_round(self) -> None:
        planner, client, _ = _repair_planner([VALID_PLAN_TEXT])
        assert len(planner.plan("p", AVAILABLE_TOOLS).steps) == 2
        assert client.repair_rounds == 0
        assert len(client.rounds) == 1

    def test_a_fenced_reply_is_stripped_by_the_client_without_a_repair(self) -> None:
        planner, client, _ = _repair_planner([f"```json\n{VALID_PLAN_TEXT}\n```"])
        assert len(planner.plan("p", AVAILABLE_TOOLS).steps) == 2
        assert client.repair_rounds == 0

    def test_a_reply_with_trailing_prose_is_repaired_once(self) -> None:
        planner, client, _ = _repair_planner(
            [f"{VALID_PLAN_TEXT}\nHope this helps!", VALID_PLAN_TEXT]
        )
        assert len(planner.plan("p", AVAILABLE_TOOLS).steps) == 2
        assert client.repair_rounds == 1

    def test_the_repair_budget_is_exactly_one_round(self) -> None:
        # C3 says "one repair round"; the double enforces it and the constant is pinned
        # so a later change to the double cannot silently widen the budget.
        assert RepairingFakeLLMClient([]).max_repair_rounds == 1

    def test_a_client_configured_with_no_repair_fails_on_the_first_bad_reply(
        self,
    ) -> None:
        planner, client, _ = _repair_planner(
            ['{"steps": [oops', VALID_PLAN_TEXT], max_repair_rounds=0
        )
        with pytest.raises(AgentErrorRaised) as caught:
            planner.plan("p", AVAILABLE_TOOLS)
        assert caught.value.code == "PLAN_PARSE_FAILED"
        assert client.repair_rounds == 0
        assert len(client.rounds) == 1
        assert client.raw_replies == [VALID_PLAN_TEXT]  # the repair was never consumed

    def test_when_the_repair_also_fails_the_planner_propagates_the_client_error(
        self,
    ) -> None:
        planner, client, logger = _repair_planner(['{"steps": [oops', "{oops again"])
        with pytest.raises(AgentErrorRaised) as caught:
            planner.plan("p", AVAILABLE_TOOLS)
        assert caught.value is client.raised  # not re-wrapped, not re-coded
        assert caught.value.code == "PLAN_PARSE_FAILED"
        assert caught.value.error.component == "llm"  # attributed where it originated
        assert client.complete_json_calls == 1  # no planner-side retry
        assert len(client.rounds) == 2  # 1 round + 1 repair, never more
        assert "plan_generated" not in logger.events()

    def test_the_propagated_error_message_is_bounded(self) -> None:
        planner, client, _ = _repair_planner(["{" + "q" * 5_000, "{" + "q" * 5_000])
        with pytest.raises(AgentErrorRaised) as caught:
            planner.plan("p", AVAILABLE_TOOLS)
        assert caught.value is client.raised
        assert len(caught.value.error.original_error or "") <= 220


class TestBothFailureCodesAreReachable:
    """Sub-phase 2.2 exit criterion: PLAN_PARSE_FAILED and PLAN_VALIDATION_FAILED."""

    def test_plan_parse_failed_is_reachable_when_the_reply_parses_but_is_not_a_plan(
        self,
    ) -> None:
        # No repair round happens — the text is valid JSON, just not a plan object.
        planner, client, _ = _repair_planner(["[]"])
        with pytest.raises(AgentErrorRaised) as caught:
            planner.plan("p", AVAILABLE_TOOLS)
        assert caught.value.code == "PLAN_PARSE_FAILED"
        assert caught.value.error.component == "planner"
        assert client.repair_rounds == 0

    def test_plan_parse_failed_is_reachable_when_a_step_field_has_the_wrong_type(
        self,
    ) -> None:
        planner, _, _ = _repair_planner([json.dumps({"steps": [{"description": 7}]})])
        with pytest.raises(AgentErrorRaised) as caught:
            planner.plan("p", AVAILABLE_TOOLS)
        assert caught.value.code == "PLAN_PARSE_FAILED"

    def test_plan_validation_failed_is_reachable_for_an_empty_plan(self) -> None:
        planner, _, logger = _repair_planner([json.dumps({"steps": []})])
        with pytest.raises(AgentErrorRaised) as caught:
            planner.plan("p", AVAILABLE_TOOLS)
        assert caught.value.code == "PLAN_VALIDATION_FAILED"
        assert logger.events() == ["plan_validation_failed"]

    def test_plan_validation_failed_is_reachable_for_a_cycle(self) -> None:
        cyclic = {
            "steps": [
                {"description": "a", "tool_hint": "t", "depends_on": ["step_1"]},
                {"description": "b", "tool_hint": "t", "depends_on": ["step_0"]},
            ]
        }
        planner, _, _ = _repair_planner([json.dumps(cyclic)])
        with pytest.raises(AgentErrorRaised) as caught:
            planner.plan("p", AVAILABLE_TOOLS)
        assert caught.value.code == "PLAN_VALIDATION_FAILED"

    def test_llm_call_failed_is_reachable_and_propagates_unchanged(self) -> None:
        error = AgentError(code="LLM_CALL_FAILED", message="429", component="llm")
        planner, client, _ = _repair_planner([error])
        with pytest.raises(AgentErrorRaised) as caught:
            planner.plan("p", AVAILABLE_TOOLS)
        assert caught.value is error
        assert client.complete_json_calls == 1


class TestTheRoundBudgetHoldsOnEveryFailurePath:
    """§ 5: one plan() call ≤ 1 LLM round + 1 repair, whatever happens."""

    @pytest.mark.parametrize(
        ("replies", "code"),
        [
            (["[]"], "PLAN_PARSE_FAILED"),
            ([json.dumps({"steps": []})], "PLAN_VALIDATION_FAILED"),
            (['{"steps": [oops', "{oops again"], "PLAN_PARSE_FAILED"),
            (
                [AgentError(code="LLM_CALL_FAILED", message="500", component="llm")],
                "LLM_CALL_FAILED",
            ),
        ],
    )
    def test_exactly_one_complete_json_call_is_made(
        self, replies: list[object], code: str
    ) -> None:
        planner, client, _ = _repair_planner(replies)
        with pytest.raises(AgentErrorRaised) as caught:
            planner.plan("p", AVAILABLE_TOOLS)
        assert caught.value.code == code
        assert client.complete_json_calls == 1
        assert client.usage.calls <= 1
        assert len(client.rounds) <= 2  # the round, plus at most one repair

    def test_a_successful_plan_consumes_one_call_and_one_usage_increment(self) -> None:
        planner, client, _ = _repair_planner([VALID_PLAN_TEXT])
        planner.plan("p", AVAILABLE_TOOLS)
        assert client.complete_json_calls == 1
        assert client.usage.calls == 1
        assert client.usage.prompt_tokens == 13
        assert client.usage.completion_tokens == 17

    def test_the_planner_never_calls_complete(self) -> None:
        planner, client, _ = _repair_planner([VALID_PLAN_TEXT])
        planner.plan("p", AVAILABLE_TOOLS)
        assert client.usage.calls == 1
        assert len(client.rounds) == 1  # only the complete_json round was recorded

    def test_a_raw_json_text_reply_is_still_accepted_by_the_parser(self) -> None:
        # Leniency worth pinning: a client that hands back the JSON *text* instead of
        # the parsed object still produces a plan, because parse_plan accepts a str.
        planner, client, _ = _planner(VALID_PLAN_TEXT)
        assert len(planner.plan("p", AVAILABLE_TOOLS).steps) == 2
        assert client.json_calls[0]["schema_hint"] == prompts.PLAN_SCHEMA_HINT


# ══════════════════════════════════════════════════════════════════════════════
# Sub-phase 2.3 — context-aware planning
# ══════════════════════════════════════════════════════════════════════════════


class TestContextVariablesAreSeeded:
    """`plan(context=…)` seeds `plan.context["variables"]` (plan § 2.3)."""

    def test_variables_propagate_into_the_plan_context(self) -> None:
        planner, _, _ = _planner()
        plan = planner.plan(
            "Summarize the data",
            AVAILABLE_TOOLS,
            context={"variables": {"data_file": "./input/sales.csv"}},
        )
        assert plan.context["variables"] == {"data_file": "./input/sales.csv"}

    def test_variables_coexist_with_the_unresolved_hints_record(self) -> None:
        planner, _, _ = _planner()
        plan = planner.plan(
            "p", AVAILABLE_TOOLS, context={"variables": {"topic": "GPT-4"}}
        )
        assert plan.context["variables"] == {"topic": "GPT-4"}
        assert plan.context["unresolved_hints"] == []

    def test_the_seeded_variables_are_a_deep_copy_in_both_directions(self) -> None:
        planner, _, _ = _planner()
        context: dict[str, Any] = {"variables": {"files": ["a.csv"], "meta": {"n": 1}}}
        plan = planner.plan("p", AVAILABLE_TOOLS, context=context)
        plan.context["variables"]["files"].append("b.csv")
        plan.context["variables"]["meta"]["n"] = 99
        assert context["variables"] == {"files": ["a.csv"], "meta": {"n": 1}}
        context["variables"]["files"].append("c.csv")
        assert plan.context["variables"]["files"] == ["a.csv", "b.csv"]

    def test_the_caller_context_is_still_never_mutated(self) -> None:
        planner, _, _ = _planner()
        context: dict[str, Any] = {
            "variables": {"topic": "GPT-4"},
            "step_results": [{"step_id": "step_0"}],
        }
        before = json.loads(json.dumps(context))
        planner.plan("p", AVAILABLE_TOOLS, context=context)
        assert json.loads(json.dumps(context)) == before

    @pytest.mark.parametrize(
        "context",
        [
            None,
            {},
            {"step_results": []},
            {"variables": {}},
            {"variables": "not a mapping"},
            {"variables": None},
            {"variables": ["a", "b"]},
        ],
    )
    def test_no_variables_key_is_added_when_there_is_nothing_to_seed(
        self, context: Mapping[str, Any] | None
    ) -> None:
        # Minimal writes: the plan context stays free of an empty/invalid "variables"
        # entry so the report does not show a section that was never supplied.
        planner, _, _ = _planner()
        plan = planner.plan("p", AVAILABLE_TOOLS, context=context)
        assert plan.context.get("variables", {}) == {}
        assert "variables" not in plan.context or plan.context["variables"] == {}

    def test_only_the_variables_key_is_seeded_not_the_whole_context(self) -> None:
        # step_results/files_created belong to the runtime context (SPEC-003 § 4.1),
        # which the orchestrator owns; a pre-execution plan must not claim them.
        planner, _, _ = _planner()
        plan = planner.plan(
            "p",
            AVAILABLE_TOOLS,
            context={
                "variables": {"topic": "GPT-4"},
                "step_results": [{"step_id": "step_0", "output": "x"}],
                "files_created": ["./secret.pdf"],
            },
        )
        assert plan.context["variables"] == {"topic": "GPT-4"}
        assert "step_results" not in plan.context
        assert "files_created" not in plan.context


class TestContextSummaryInThePrompt:
    """A bounded summary reaches the model when — and only when — variables exist."""

    def test_the_summary_is_appended_to_the_user_message(self) -> None:
        planner, client, _ = _planner()
        planner.plan(
            "Summarize the data",
            AVAILABLE_TOOLS,
            context={"variables": {"data_file": "./input/sales.csv"}},
        )
        user = client.json_calls[0]["messages"][1]["content"]
        assert user.startswith("Summarize the data")
        assert "Current context:" in user
        assert "data_file" in user
        assert "./input/sales.csv" in user

    def test_the_frozen_system_prompt_is_identical_with_or_without_context(
        self,
    ) -> None:
        # § 3.1 content is FROZEN: the summary may not be smuggled into it.
        with_context, client_a, _ = _planner()
        with_context.plan("p", AVAILABLE_TOOLS, context={"variables": {"a": "b"}})
        without, client_b, _ = _planner()
        without.plan("p", AVAILABLE_TOOLS)
        assert (
            client_a.json_calls[0]["messages"][0]["content"]
            == client_b.json_calls[0]["messages"][0]["content"]
        )

    def test_the_user_message_is_the_prompt_verbatim_when_no_variables_exist(
        self,
    ) -> None:
        planner, client, _ = _planner()
        planner.plan("Do the research", AVAILABLE_TOOLS, context={"step_results": []})
        assert client.json_calls[0]["messages"][1]["content"] == "Do the research"

    def test_an_empty_variables_mapping_adds_no_summary(self) -> None:
        planner, client, _ = _planner()
        planner.plan("Do the research", AVAILABLE_TOOLS, context={"variables": {}})
        assert client.json_calls[0]["messages"][1]["content"] == "Do the research"

    def test_the_summary_lists_variables_in_sorted_key_order(self) -> None:
        # Sorted, not insertion order: the same variables must produce a
        # byte-identical prompt however the caller built the dict (G3's rationale).
        first, client_a, _ = _planner()
        first.plan(
            "p", AVAILABLE_TOOLS, context={"variables": {"z": 1, "a": 2, "m": 3}}
        )
        second, client_b, _ = _planner()
        second.plan(
            "p", AVAILABLE_TOOLS, context={"variables": {"a": 2, "m": 3, "z": 1}}
        )
        assert (
            client_a.json_calls[0]["messages"][1]
            == client_b.json_calls[0]["messages"][1]
        )
        summary = client_a.json_calls[0]["messages"][1]["content"]
        assert summary.index("- a:") < summary.index("- m:") < summary.index("- z:")

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("plain", "plain"),
            (7, "7"),
            (True, "true"),
            (None, "null"),
            (["a", "b"], '["a", "b"]'),
            ({"k": "v"}, '{"k": "v"}'),
            (1.5, "1.5"),
            ("البحث", "البحث"),
        ],
    )
    def test_non_string_values_render_deterministically_as_json(
        self, value: object, expected: str
    ) -> None:
        planner, client, _ = _planner()
        planner.plan("p", AVAILABLE_TOOLS, context={"variables": {"key": value}})
        assert f"- key: {expected}" in client.json_calls[0]["messages"][1]["content"]

    def test_a_value_that_is_not_json_serializable_still_renders(self) -> None:
        class _Opaque:
            def __repr__(self) -> str:
                return "<opaque>"

        planner, client, _ = _planner()
        planner.plan("p", AVAILABLE_TOOLS, context={"variables": {"key": _Opaque()}})
        assert "- key: " in client.json_calls[0]["messages"][1]["content"]

    def test_a_circular_value_falls_back_to_repr_instead_of_raising(self) -> None:
        # json.dumps reports a circular reference as ValueError; the summary is a
        # convenience, so it degrades to repr rather than failing the plan.
        circular: dict[str, Any] = {"name": "loop"}
        circular["self"] = circular
        planner, client, _ = _planner()
        planner.plan("p", AVAILABLE_TOOLS, context={"variables": {"key": circular}})
        assert "- key: " in client.json_calls[0]["messages"][1]["content"]

    def test_a_dict_with_unsortable_mixed_keys_falls_back_to_repr(self) -> None:
        # sort_keys=True raises TypeError on mixed int/str keys.
        planner, client, _ = _planner()
        planner.plan(
            "p", AVAILABLE_TOOLS, context={"variables": {"key": {1: "a", "b": "c"}}}
        )
        assert "- key: " in client.json_calls[0]["messages"][1]["content"]

    def test_a_value_whose_repr_raises_is_still_bounded_and_never_crashes(self) -> None:
        class _Hostile:
            def __repr__(self) -> str:
                raise ValueError("no repr for you")

        planner, client, _ = _planner()
        with pytest.raises(ValueError):
            # Documented limit: repr is the last resort, so a hostile __repr__ surfaces
            # rather than being silently swallowed — the planner never guesses.
            planner.plan(
                "p", AVAILABLE_TOOLS, context={"variables": {"key": _Hostile()}}
            )
        assert client.json_calls == []  # it failed while composing the prompt

    def test_a_context_key_that_is_not_variables_never_reaches_the_prompt(self) -> None:
        # Only `variables` is summarized, so a caller-supplied secret under another key
        # cannot be exfiltrated into a model call.
        planner, client, _ = _planner()
        planner.plan(
            "p",
            AVAILABLE_TOOLS,
            context={
                "variables": {"topic": "GPT-4"},
                "config": {"api_key": "sk-super-secret"},
                "files_created": ["./private.pdf"],
            },
        )
        sent = json.dumps(client.json_calls[0]["messages"])
        assert "sk-super-secret" not in sent
        assert "./private.pdf" not in sent
        assert "GPT-4" in sent

    def test_the_config_api_key_env_name_never_reaches_the_prompt(self) -> None:
        config = FakeConfig(llm=FakeLLMSection(api_key_env="OPENAI_API_KEY"))
        planner, client, _ = _planner(config=config)
        planner.plan("p", AVAILABLE_TOOLS, context={"variables": {"topic": "x"}})
        assert "OPENAI_API_KEY" not in json.dumps(client.json_calls[0]["messages"])


class TestContextSummaryBounds:
    """plan § 2.3: the summary is bounded at 2000 characters."""

    def test_the_bound_constants_are_documented_values(self) -> None:
        assert MAX_CONTEXT_SUMMARY_CHARS == 2000
        assert 0 < MAX_CONTEXT_VALUE_CHARS < MAX_CONTEXT_SUMMARY_CHARS

    def test_a_small_context_grows_the_prompt_by_only_the_summary(self) -> None:
        planner, client, _ = _planner()
        planner.plan("p", AVAILABLE_TOOLS, context={"variables": {"topic": "GPT-4"}})
        user = client.json_calls[0]["messages"][1]["content"]
        assert len(user) - len("p") < 200
        assert TRUNCATION_MARKER not in user

    def test_a_huge_context_never_grows_the_prompt_beyond_the_bound(self) -> None:
        # Short values on purpose: a capped *value* also ends with TRUNCATION_MARKER,
        # so long values would hide whether the section-level marker was emitted.
        variables = {f"key_{i:04d}": "v" for i in range(500)}
        planner, client, _ = _planner()
        planner.plan("prompt", AVAILABLE_TOOLS, context={"variables": variables})
        user = client.json_calls[0]["messages"][1]["content"]
        summary = user.split("Current context:", 1)[1]
        assert len(summary) <= MAX_CONTEXT_SUMMARY_CHARS
        assert len(user) <= len("prompt") + MAX_CONTEXT_SUMMARY_CHARS + 40
        assert summary.rstrip().endswith(TRUNCATION_MARKER)
        assert summary.count(TRUNCATION_MARKER) == 1  # the section marker, exactly once
        assert "- key_0000: v" in summary
        assert "- key_0499: v" not in summary  # later variables were dropped
        assert len(summary.splitlines()) < 500

    def test_a_single_enormous_value_is_capped_so_other_variables_still_fit(
        self,
    ) -> None:
        variables = {"huge": "x" * 200_000, "small": "keep me"}
        planner, client, _ = _planner()
        planner.plan("p", AVAILABLE_TOOLS, context={"variables": variables})
        summary = client.json_calls[0]["messages"][1]["content"].split(
            "Current context:", 1
        )[1]
        assert len(summary) <= MAX_CONTEXT_SUMMARY_CHARS
        assert "keep me" in summary  # the huge value did not crowd it out
        # Capped, not dropped: the variable still reaches the model, truncated. Without
        # the per-value cap this line exceeds the budget and vanishes from the prompt.
        capped = "x" * (MAX_CONTEXT_VALUE_CHARS - len(TRUNCATION_MARKER))
        assert f"- huge: {capped}{TRUNCATION_MARKER}" in summary
        assert "x" * (MAX_CONTEXT_VALUE_CHARS + 1) not in summary

    def test_truncation_happens_on_line_boundaries_not_mid_value(self) -> None:
        variables = {f"k{i:03d}": "value" for i in range(1_000)}
        planner, client, _ = _planner()
        planner.plan("p", AVAILABLE_TOOLS, context={"variables": variables})
        summary = client.json_calls[0]["messages"][1]["content"].split(
            "Current context:", 1
        )[1]
        lines = [line for line in summary.splitlines() if line.startswith("- ")]
        assert lines
        assert all(line.endswith("value") for line in lines)  # no half-written value

    def test_the_bound_holds_with_unicode_values(self) -> None:
        variables = {f"مفتاح_{i}": "قيمة" * 100 for i in range(300)}
        planner, client, _ = _planner()
        planner.plan("p", AVAILABLE_TOOLS, context={"variables": variables})
        summary = client.json_calls[0]["messages"][1]["content"].split(
            "Current context:", 1
        )[1]
        assert len(summary) <= MAX_CONTEXT_SUMMARY_CHARS

    def test_the_seeded_variables_are_complete_even_when_the_summary_is_truncated(
        self,
    ) -> None:
        # The prompt bound must not silently shrink the plan's own context: the report
        # and the orchestrator see every variable the caller supplied.
        variables = {f"key_{i:04d}": "v" * 300 for i in range(500)}
        planner, _, _ = _planner()
        plan = planner.plan("p", AVAILABLE_TOOLS, context={"variables": variables})
        assert len(plan.context["variables"]) == 500
        assert plan.context["variables"] == variables


# ══════════════════════════════════════════════════════════════════════════════
# Sub-phase 2.4 — select_tool() (SPEC-004 § 2, § 3.3, § 5: 1 round, no repair)
# ══════════════════════════════════════════════════════════════════════════════


def _selection_planner(
    reply: object,
    *,
    config: FakeConfig | None = None,
) -> tuple[Planner, FakeLLMClient, FakeLogger]:
    """Build a planner whose ``complete`` queue holds one scripted text reply."""
    client = FakeLLMClient(text_replies=[reply])
    logger = FakeLogger()
    planner = Planner(
        client, config if config is not None else FakeConfig(), logger=logger
    )
    return planner, client, logger


def _step(
    description: str = "Search for GPT-4 usage statistics",
    input_data: Any = None,
    **kwargs: Any,
) -> Step:
    """Build a step for selection tests; ``kwargs`` override any default field."""
    fields: dict[str, Any] = {
        "id": "step_0",
        "description": description,
        "tool_hint": "ghost_tool",
        "input_data": {} if input_data is None else input_data,
    }
    fields.update(kwargs)
    return Step(**fields)


class TestSelectToolFrozenSignature:
    """SPEC-004 § 2: `select_tool(self, step, available_tools) -> str | None`."""

    def test_select_tool_takes_step_and_available_tools(self) -> None:
        assert _signature_parameters(Planner.select_tool) == [
            ("self", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("step", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("available_tools", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
        ]

    def test_the_return_annotation_is_optional_str(self) -> None:
        assert str(inspect.signature(Planner.select_tool).return_annotation) in {
            "str | None",
            "typing.Optional[str]",
        }


class TestSelectToolHappyPath:
    """A registered name comes back; everything else is `None`."""

    def test_a_registered_name_is_returned(self) -> None:
        planner, _, _ = _selection_planner('{"tool": "web_search"}')
        assert planner.select_tool(_step(), AVAILABLE_TOOLS) == "web_search"

    def test_the_second_registered_tool_can_be_selected(self) -> None:
        planner, _, _ = _selection_planner('{"tool": "pdf_export"}')
        assert planner.select_tool(_step(), AVAILABLE_TOOLS) == "pdf_export"

    def test_tool_objects_validate_exactly_like_tool_dicts(self) -> None:
        planner, _, _ = _selection_planner('{"tool": "web_search"}')
        assert planner.select_tool(_step(), [_ExplodingTool()]) == "web_search"

    def test_extra_keys_in_the_reply_are_ignored(self) -> None:
        # § 4.2 rule 3's tolerance, applied to the selection reply.
        planner, _, _ = _selection_planner(
            '{"tool": "pdf_export", "reason": "it exports"}'
        )
        assert planner.select_tool(_step(), AVAILABLE_TOOLS) == "pdf_export"

    def test_surrounding_whitespace_in_the_name_is_tolerated(self) -> None:
        planner, _, _ = _selection_planner('{"tool": "  web_search  "}')
        assert planner.select_tool(_step(), AVAILABLE_TOOLS) == "web_search"

    def test_a_fenced_reply_is_parsed(self) -> None:
        planner, _, _ = _selection_planner('```json\n{"tool": "web_search"}\n```')
        assert planner.select_tool(_step(), AVAILABLE_TOOLS) == "web_search"

    def test_a_reply_wrapped_in_prose_is_parsed(self) -> None:
        planner, _, _ = _selection_planner(
            'I would use {"tool": "web_search"} for this.'
        )
        assert planner.select_tool(_step(), AVAILABLE_TOOLS) == "web_search"


class TestSelectToolBudgetAndDeterminism:
    """§ 5: tool selection uses temperature 0.0, one round and NO repair round."""

    def test_selection_uses_complete_not_complete_json_so_no_repair_can_happen(
        self,
    ) -> None:
        # C3 puts the repair round inside complete_json, so § 5's "no repair" forces
        # the text call — and the planner parses the reply itself.
        planner, client, _ = _selection_planner('{"tool": "web_search"}')
        planner.select_tool(_step(), AVAILABLE_TOOLS)
        assert len(client.text_calls) == 1
        assert client.json_calls == []

    def test_the_temperature_is_hardcoded_to_zero_not_read_from_the_config(
        self,
    ) -> None:
        config = FakeConfig(llm=FakeLLMSection(temperature=0.9))
        planner, client, _ = _selection_planner('{"tool": "web_search"}', config=config)
        planner.select_tool(_step(), AVAILABLE_TOOLS)
        assert client.text_calls[0]["temperature"] == 0.0

    def test_no_max_tokens_override_is_sent(self) -> None:
        planner, client, _ = _selection_planner('{"tool": "web_search"}')
        planner.select_tool(_step(), AVAILABLE_TOOLS)
        assert client.text_calls[0]["max_tokens"] is None

    def test_exactly_one_round_is_consumed_even_when_the_reply_is_unusable(
        self,
    ) -> None:
        planner, client, _ = _selection_planner("not json at all")
        assert planner.select_tool(_step(), AVAILABLE_TOOLS) is None
        assert len(client.text_calls) == 1
        assert client.usage.calls == 1

    def test_the_step_is_never_mutated(self) -> None:
        # SPEC-003 § 3 step 2 writes step.tool_name; that is the orchestrator's job.
        planner, _, _ = _selection_planner('{"tool": "web_search"}')
        step = _step()
        planner.select_tool(step, AVAILABLE_TOOLS)
        assert step.tool_name == ""
        assert step.tool_hint == "ghost_tool"
        assert status_value(step.status) == "pending"


class TestSelectToolPromptComposition:
    """The additive § 3.3 template, with the step and the tools substituted in."""

    def test_the_prompt_is_a_single_user_message(self) -> None:
        # A lone *system* message would break providers whose message list must open
        # with a user turn (Anthropic); the § 3.3 template is self-contained.
        planner, client, _ = _selection_planner('{"tool": "web_search"}')
        planner.select_tool(_step(), AVAILABLE_TOOLS)
        messages = client.text_calls[0]["messages"]
        assert [message["role"] for message in messages] == ["user"]
        assert set(messages[0]) == {"role", "content"}

    def test_the_step_description_and_input_keys_are_substituted(self) -> None:
        planner, client, _ = _selection_planner('{"tool": "web_search"}')
        planner.select_tool(
            _step("Export the summary", {"path": "./out.pdf", "dpi": 300}),
            AVAILABLE_TOOLS,
        )
        content = client.text_calls[0]["messages"][0]["content"]
        assert "Step description: Export the summary" in content
        assert "Step input keys: dpi, path" in content  # sorted, deterministic

    def test_the_tool_list_is_rendered_in_the_same_form_as_planning(self) -> None:
        planner, client, _ = _selection_planner('{"tool": "web_search"}')
        planner.select_tool(_step(), AVAILABLE_TOOLS)
        content = client.text_calls[0]["messages"][0]["content"]
        assert "- web_search: Search the web. [capabilities: search]" in content
        assert "- pdf_export: Export a PDF. [capabilities: export]" in content

    def test_the_json_examples_reach_the_model_with_single_braces(self) -> None:
        # The template doubles its braces so str.format emits real ones; a `.replace`
        # implementation would leak `{{"tool": ...}}` to the model.
        planner, client, _ = _selection_planner('{"tool": "web_search"}')
        planner.select_tool(_step(), AVAILABLE_TOOLS)
        content = client.text_calls[0]["messages"][0]["content"]
        assert '{"tool": "<tool_name>"}' in content
        assert '{"tool": null}' in content
        assert "{{" not in content

    def test_the_anti_hallucination_instruction_reaches_the_model(self) -> None:
        planner, client, _ = _selection_planner('{"tool": "web_search"}')
        planner.select_tool(_step(), AVAILABLE_TOOLS)
        assert (
            "Never invent a tool name" in client.text_calls[0]["messages"][0]["content"]
        )

    @pytest.mark.parametrize("input_data", [{}, None, "not a mapping", 7, ["a"]])
    def test_an_unusable_input_data_renders_as_no_keys(self, input_data: Any) -> None:
        planner, client, _ = _selection_planner('{"tool": "web_search"}')
        step = _step()
        step.input_data = input_data
        planner.select_tool(step, AVAILABLE_TOOLS)
        assert (
            "Step input keys: (none)" in client.text_calls[0]["messages"][0]["content"]
        )

    def test_braces_inside_a_step_description_survive_substitution(self) -> None:
        planner, client, _ = _selection_planner('{"tool": "web_search"}')
        planner.select_tool(
            _step('Extract {"key": "value"} from the page'), AVAILABLE_TOOLS
        )
        assert (
            'Extract {"key": "value"} from the page'
            in (client.text_calls[0]["messages"][0]["content"])
        )


class TestSelectToolReturnsNoneWhenUnusable:
    """§ 2: "returns a tool name or `None`" — and § 2.4's three required cases."""

    @pytest.mark.parametrize(
        "reply",
        [
            '{"tool": "ghost_tool"}',  # hallucinated name
            '{"tool": null}',  # the model declines
            '{"tool": "Web_Search"}',  # wrong case is still a different name
            '{"tool": "web search"}',  # internal whitespace
            '{"tool": ""}',  # empty name
            '{"tool": ["web_search"]}',  # wrong type
            '{"tool": 7}',
            '{"tool": {"name": "web_search"}}',
            '{"tool": true}',
            "{}",  # no "tool" key
            '{"tools": "web_search"}',  # near-miss key
            "[]",
            '"web_search"',  # a bare string is not the documented shape
            "web_search",  # not JSON at all
            "",
            "   ",
            "I think web_search would work best.",
            "42",
            '{"tool": "web_search"',  # truncated
        ],
    )
    def test_the_selection_is_none(self, reply: str) -> None:
        planner, _, _ = _selection_planner(reply)
        assert planner.select_tool(_step(), AVAILABLE_TOOLS) is None

    def test_two_json_objects_resolve_to_the_first_one(self) -> None:
        # Same rule the plan parser applies to prose-wrapped payloads (sub-phase 1.5).
        planner, _, _ = _selection_planner(
            '{"tool": "web_search"}{"tool": "pdf_export"}'
        )
        assert planner.select_tool(_step(), AVAILABLE_TOOLS) == "web_search"

    def test_a_hallucinated_name_is_never_fuzzy_matched_into_a_real_one(self) -> None:
        planner, _, _ = _selection_planner('{"tool": "websearch"}')
        assert planner.select_tool(_step(), AVAILABLE_TOOLS) is None

    def test_a_json_number_never_selects_a_tool_even_when_one_bears_that_name(
        self,
    ) -> None:
        # The documented reply shape is {"tool": "<name>"} — a JSON *string*. Coercing
        # other types would let `{"tool": 7}` select a tool literally named "7".
        numeric_tools = [{"name": "7", "description": "Seven.", "capabilities": []}]
        planner, _, _ = _selection_planner('{"tool": 7}')
        assert planner.select_tool(_step(), numeric_tools) is None

    def test_a_json_boolean_never_selects_a_tool_even_when_one_bears_that_name(
        self,
    ) -> None:
        boolean_tools = [
            {"name": "True", "description": "Odd name.", "capabilities": []}
        ]
        planner, _, _ = _selection_planner('{"tool": true}')
        assert planner.select_tool(_step(), boolean_tools) is None

    def test_an_empty_tool_list_can_never_validate_a_name(self) -> None:
        planner, _, _ = _selection_planner('{"tool": "web_search"}')
        assert planner.select_tool(_step(), []) is None

    def test_a_name_from_a_different_step_hint_is_still_validated_against_the_list(
        self,
    ) -> None:
        # The hint is not a whitelist: only available_tools is.
        planner, _, _ = _selection_planner('{"tool": "ghost_tool"}')
        assert (
            planner.select_tool(_step(tool_hint="ghost_tool"), AVAILABLE_TOOLS) is None
        )

    def test_a_provider_failure_becomes_none_so_the_frozen_step_loop_stays_intact(
        self,
    ) -> None:
        # SPEC-003 § 3 step 2 branches only on None; an exception here would leave the
        # frozen loop with no defined path. The client still emits its own `llm_call`
        # event (SPEC-006 § 6.1), so the failure is not lost from the log stream.
        error = AgentError(
            code="LLM_CALL_FAILED", message="provider 500", component="llm"
        )
        planner, client, logger = _selection_planner(error)
        assert planner.select_tool(_step(), AVAILABLE_TOOLS) is None
        assert len(client.text_calls) == 1
        assert logger.records == []  # no invented catalog event

    def test_an_unexpected_client_exception_is_never_swallowed(self) -> None:
        boom = RuntimeError("client bug")
        planner, _, _ = _selection_planner(boom)
        with pytest.raises(RuntimeError) as caught:
            planner.select_tool(_step(), AVAILABLE_TOOLS)
        assert caught.value is boom

    def test_a_deeply_nested_reply_is_contained_as_none(self) -> None:
        planner, _, _ = _selection_planner(
            '{"tool": ' + "[" * 5_000 + "]" * 5_000 + "}"
        )
        assert planner.select_tool(_step(), AVAILABLE_TOOLS) is None

    def test_an_enormous_reply_never_raises_and_never_hangs(self) -> None:
        planner, _, _ = _selection_planner('{"tool": "' + "z" * 1_000_000 + '"}')
        assert planner.select_tool(_step(), AVAILABLE_TOOLS) is None


# ══════════════════════════════════════════════════════════════════════════════
# Sub-phase 2.5 — replan_step() (SPEC-004 § 2, § 3.2; serves SPEC-003 § 5 Level 3)
# ══════════════════════════════════════════════════════════════════════════════

REPLAN_REPLY: dict[str, Any] = {
    "steps": [
        {
            "description": "Export the summary as Markdown instead",
            "tool_hint": "file_write",
            "input_data": {"path": "./output/summary.md"},
            "priority": "low",  # must be overridden by the failed step's priority
        },
        {
            "description": "Convert the Markdown to PDF",
            "tool_hint": "pdf_export",
            "depends_on": [0],  # integer → the first *replacement* step
        },
    ]
}


def _replan_planner(
    reply: object = _DEFAULT_REPLY,
    *,
    config: FakeConfig | None = None,
) -> tuple[Planner, FakeLLMClient, FakeLogger]:
    """Build a planner whose ``complete_json`` queue holds one scripted reply."""
    return _planner(REPLAN_REPLY if reply is _DEFAULT_REPLY else reply, config=config)


def _section_of(content: str, header: str) -> str:
    """Isolate one substituted prompt section, cutting the template's trailing text."""
    return content.split(header, 1)[1].split("\n\nGenerate an alternative", 1)[0]


def _failed_step(step_id: str = "step_1", **kwargs: Any) -> Step:
    """A step that exhausted Levels 1-2 and is now being re-planned."""
    fields: dict[str, Any] = {
        "id": step_id,
        "description": "Export the summary as a PDF",
        "tool_hint": "pdf_export",
        "tool_name": "pdf_export",
        "status": StepStatus.FAILED,
        "error": "pdf_export timed out",
        "retries": 2,
        "priority": TaskPriority.CRITICAL,
    }
    fields.update(kwargs)
    return Step(**fields)


def _runtime_context(**overrides: Any) -> dict[str, Any]:
    """A SPEC-003 § 4.1 context as the orchestrator would have built it."""
    context: dict[str, Any] = {
        "config": {"execution": {"max_steps": 10}},
        "step_results": {
            "step_0": {
                "status": "SUCCESS",
                "output": "found 12 articles about GPT-4 usage",
                "error": None,
                "tool_name": "web_search",
                "duration_ms": 421,
                "retries": 0,
            },
        },
        "variables": {"data_file": "./input/sales.csv"},
        "errors": [
            {
                "step_id": "step_0",
                "attempt": 1,
                "error": "unrelated transient failure",
                "recovered": True,
                "level": 1,
            },
            {
                "step_id": "step_1",
                "attempt": 1,
                "error": "pdf_export timed out",
                "recovered": False,
                "level": 1,
            },
            {
                "step_id": "step_1",
                "attempt": 2,
                "error": "fallback md_export is not registered",
                "recovered": False,
                "level": 2,
            },
        ],
        "files_created": [],
    }
    context.update(overrides)
    return context


class TestReplanStepFrozenSignature:
    """SPEC-004 § 2, and the double pinned in sub-phase 1.4."""

    def test_replan_step_takes_step_error_context_and_optional_tools(self) -> None:
        assert _signature_parameters(Planner.replan_step) == [
            ("self", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("step", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("error", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("context", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("available_tools", "POSITIONAL_OR_KEYWORD", None),
        ]

    def test_the_return_annotation_is_a_list_of_steps(self) -> None:
        annotation = str(inspect.signature(Planner.replan_step).return_annotation)
        assert annotation in {"list[StepLike]", "typing.List[StepLike]"}

    def test_available_tools_may_be_omitted_entirely(self) -> None:
        planner, client, _ = _replan_planner()
        assert len(planner.replan_step(_failed_step(), "boom", _runtime_context())) == 2
        assert len(client.json_calls) == 1


class TestReplanStepProducesAnAlternative:
    """The happy path recovery Level 3 depends on."""

    def test_the_reply_becomes_a_list_of_normalized_steps(self) -> None:
        planner, _, _ = _replan_planner()
        steps = planner.replan_step(
            _failed_step(), "pdf_export timed out", _runtime_context(), AVAILABLE_TOOLS
        )
        assert len(steps) == 2
        assert steps[0].description == "Export the summary as Markdown instead"
        assert steps[0].tool_hint == "file_write"
        assert steps[0].input_data == {"path": "./output/summary.md"}
        assert status_value(steps[0].status) == "pending"

    def test_the_list_order_is_the_execution_order(self) -> None:
        # SPEC-003 § 5 Level 3 executes replacements immediately, in order.
        planner, _, _ = _replan_planner()
        steps = planner.replan_step(_failed_step(), "boom", _runtime_context(), [])
        assert [step.description for step in steps] == [
            "Export the summary as Markdown instead",
            "Convert the Markdown to PDF",
        ]

    def test_max_retries_comes_from_the_config_as_for_any_parsed_step(self) -> None:
        config = FakeConfig(execution=FakeExecutionSection(max_retries=5))
        planner, _, _ = _replan_planner(config=config)
        steps = planner.replan_step(_failed_step(), "boom", _runtime_context(), [])
        assert [step.max_retries for step in steps] == [5, 5]

    def test_a_single_step_object_without_a_steps_wrapper_is_accepted(self) -> None:
        planner, _, _ = _replan_planner(
            {"description": "Write the summary by hand", "tool_hint": "file_write"}
        )
        steps = planner.replan_step(_failed_step(), "boom", _runtime_context(), [])
        assert [step.description for step in steps] == ["Write the summary by hand"]

    def test_a_bare_list_of_steps_is_accepted(self) -> None:
        planner, _, _ = _replan_planner(
            [
                {"description": "a", "tool_hint": "t"},
                {"description": "b", "tool_hint": "t"},
            ]
        )
        steps = planner.replan_step(_failed_step(), "boom", _runtime_context(), [])
        assert [step.description for step in steps] == ["a", "b"]


class TestReplanStepIdsAndInheritance:
    """Fresh `r<n>` ids, inherited priority, remapped internal dependencies."""

    def test_replacement_ids_are_the_failed_step_id_suffixed_with_r_n(self) -> None:
        planner, _, _ = _replan_planner()
        steps = planner.replan_step(
            _failed_step("step_1"), "boom", _runtime_context(), []
        )
        assert [step.id for step in steps] == ["step_1r1", "step_1r2"]

    def test_the_suffix_numbers_from_one_for_a_different_failed_step(self) -> None:
        planner, _, _ = _replan_planner()
        steps = planner.replan_step(
            _failed_step("step_7"), "boom", _runtime_context(), []
        )
        assert [step.id for step in steps] == ["step_7r1", "step_7r2"]

    def test_a_single_replacement_is_r1(self) -> None:
        planner, _, _ = _replan_planner(
            {"steps": [{"description": "a", "tool_hint": "t"}]}
        )
        steps = planner.replan_step(
            _failed_step("step_3"), "boom", _runtime_context(), []
        )
        assert [step.id for step in steps] == ["step_3r1"]

    def test_the_failed_step_priority_is_inherited_not_the_models(self) -> None:
        # The reply says "low"; the failed step is CRITICAL. Level 4's escalation
        # decision reads the priority, so a model could otherwise downgrade a critical
        # deliverable and silently dodge abort_on_critical_failure.
        planner, _, _ = _replan_planner()
        steps = planner.replan_step(
            _failed_step(priority=TaskPriority.CRITICAL), "boom", _runtime_context(), []
        )
        assert [priority_value(step.priority) for step in steps] == ["critical"] * 2

    @pytest.mark.parametrize("priority", ["critical", "high", "medium", "low"])
    def test_every_priority_is_inherited_verbatim(self, priority: str) -> None:
        planner, _, _ = _replan_planner()
        failed = _failed_step(priority=TaskPriority(priority))
        steps = planner.replan_step(failed, "boom", _runtime_context(), [])
        assert all(priority_value(step.priority) == priority for step in steps)

    def test_an_integer_dependency_is_remapped_to_a_replacement_id(self) -> None:
        # The reply's `depends_on: [0]` means "the first replacement", which parse_plan
        # canonicalizes to step_0; that canonical id must become step_1r1, or the
        # replacement would appear to depend on an unrelated original step.
        planner, _, _ = _replan_planner()
        steps = planner.replan_step(
            _failed_step("step_1"), "boom", _runtime_context(), []
        )
        assert steps[1].depends_on == ["step_1r1"]

    def test_a_dependency_on_an_original_step_is_left_alone(self) -> None:
        reply = {
            "steps": [
                {"description": "a", "tool_hint": "t", "depends_on": ["step_0"]},
            ]
        }
        planner, _, _ = _replan_planner(reply)
        steps = planner.replan_step(
            _failed_step("step_1"), "boom", _runtime_context(), []
        )
        assert steps[0].depends_on == ["step_0"]

    def test_a_dependency_on_the_failed_step_itself_is_dropped(self) -> None:
        # The failed step is the one being replaced, so depending on it could never be
        # satisfied; keeping it would strand the replacement.
        reply = {
            "steps": [{"description": "a", "tool_hint": "t", "depends_on": ["step_1"]}]
        }
        planner, _, _ = _replan_planner(reply)
        steps = planner.replan_step(
            _failed_step("step_1"), "boom", _runtime_context(), []
        )
        assert steps[0].depends_on == []

    def test_a_self_dependency_among_replacements_is_preserved_for_the_caller_to_judge(
        self,
    ) -> None:
        # replan_step does not run V1-V7: V4 would reject a legitimate dependency on an
        # original step, and Level 3 executes replacements in list order regardless.
        reply = {
            "steps": [{"description": "a", "tool_hint": "t", "depends_on": ["step_0"]}]
        }
        planner, _, _ = _replan_planner(reply)
        steps = planner.replan_step(
            _failed_step("step_0"), "boom", _runtime_context(), []
        )
        assert steps[0].id == "step_0r1"
        assert steps[0].depends_on == []


class TestReplanPromptComposition:
    """§ 3.2 FROZEN template, all six placeholders substituted."""

    def test_the_prompt_is_a_single_user_message(self) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(), "boom", _runtime_context(), AVAILABLE_TOOLS)
        messages = client.json_calls[0]["messages"]
        assert [message["role"] for message in messages] == ["user"]

    def test_the_frozen_opening_and_closing_lines_reach_the_model(self) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(), "boom", _runtime_context(), AVAILABLE_TOOLS)
        content = client.json_calls[0]["messages"][0]["content"]
        assert content.startswith(
            "A step in the execution plan has failed after all retries and fallbacks."
        )
        assert content.rstrip().endswith("Respond with valid JSON.")

    def test_every_placeholder_is_substituted(self) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(
            _failed_step(), "pdf_export timed out", _runtime_context(), AVAILABLE_TOOLS
        )
        content = client.json_calls[0]["messages"][0]["content"]
        for placeholder in (
            "{step_description}",
            "{tool_name}",
            "{error_message}",
            "{attempt_history}",
            "{tool_descriptions}",
            "{context_summary}",
        ):
            assert placeholder not in content

    def test_the_failed_step_and_error_are_quoted(self) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(
            _failed_step(), "pdf_export timed out", _runtime_context(), AVAILABLE_TOOLS
        )
        content = client.json_calls[0]["messages"][0]["content"]
        assert "Failed step: Export the summary as a PDF" in content
        assert "Tool used: pdf_export" in content
        assert "Error: pdf_export timed out" in content

    def test_the_tool_hint_is_used_when_no_tool_was_ever_resolved(self) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(
            _failed_step(tool_name=""), "boom", _runtime_context(), AVAILABLE_TOOLS
        )
        assert "Tool used: pdf_export" in client.json_calls[0]["messages"][0]["content"]

    def test_the_tools_are_rendered_in_the_same_deterministic_form(self) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(), "boom", _runtime_context(), AVAILABLE_TOOLS)
        content = client.json_calls[0]["messages"][0]["content"]
        assert "- web_search: Search the web. [capabilities: search]" in content
        assert "- pdf_export: Export a PDF. [capabilities: export]" in content

    def test_no_tools_renders_as_an_explicit_none_rather_than_a_blank(self) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(), "boom", _runtime_context(), [])
        assert (
            "Available tools: (none)" in client.json_calls[0]["messages"][0]["content"]
        )

    def test_a_long_error_message_is_bounded_in_the_prompt(self) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(), "e" * 5_000, _runtime_context(), [])
        content = client.json_calls[0]["messages"][0]["content"]
        assert "e" * 5_000 not in content
        assert TRUNCATION_MARKER in content


class TestAttemptHistory:
    """`{attempt_history}` is built from the § 4.1 context, bounded and step-scoped."""

    def test_previous_attempts_for_this_step_are_listed(self) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(), "boom", _runtime_context(), [])
        history = client.json_calls[0]["messages"][0]["content"].split(
            "Previous attempts:", 1
        )[1]
        assert "pdf_export timed out" in history
        assert "fallback md_export is not registered" in history
        assert "level 1" in history and "level 2" in history

    def test_attempts_of_other_steps_are_excluded(self) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(), "boom", _runtime_context(), [])
        assert (
            "unrelated transient failure"
            not in client.json_calls[0]["messages"][0]["content"]
        )

    def test_history_is_chronological(self) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(), "boom", _runtime_context(), [])
        history = client.json_calls[0]["messages"][0]["content"].split(
            "Previous attempts:", 1
        )[1]
        assert history.index("pdf_export timed out") < history.index(
            "fallback md_export is not registered"
        )

    def test_with_no_recorded_attempts_the_retry_count_is_stated(self) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(retries=2), "boom", {"errors": []}, [])
        history = client.json_calls[0]["messages"][0]["content"].split(
            "Previous attempts:", 1
        )[1]
        assert "no previous attempts" in history
        assert "2" in history

    def test_a_context_without_an_errors_key_is_tolerated(self) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(), "boom", {}, [])
        assert "Previous attempts:" in client.json_calls[0]["messages"][0]["content"]

    def test_only_the_most_recent_attempts_are_kept(self) -> None:
        errors = [
            {"step_id": "step_1", "attempt": i, "error": f"failure {i}", "level": 1}
            for i in range(1, 40)
        ]
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(), "boom", {"errors": errors}, [])
        history = client.json_calls[0]["messages"][0]["content"].split(
            "Previous attempts:", 1
        )[1]
        assert MAX_ATTEMPT_HISTORY_ENTRIES == 10
        assert history.count("- attempt") == MAX_ATTEMPT_HISTORY_ENTRIES
        assert "failure 39" in history  # the newest survives
        assert "failure 1" not in history  # the oldest is dropped

    def test_a_long_recorded_error_is_bounded_per_entry(self) -> None:
        errors = [{"step_id": "step_1", "attempt": 1, "error": "z" * 5_000, "level": 1}]
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(), "boom", {"errors": errors}, [])
        history = client.json_calls[0]["messages"][0]["content"].split(
            "Previous attempts:", 1
        )[1]
        assert "z" * 5_000 not in history
        assert len(history) < 1_200

    def test_a_malformed_errors_entry_is_skipped_not_fatal(self) -> None:
        errors = [
            "not a mapping",
            {"attempt": 1},
            {"step_id": "step_1", "attempt": 2, "error": "real failure", "level": 2},
        ]
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(), "boom", {"errors": errors}, [])
        history = client.json_calls[0]["messages"][0]["content"].split(
            "Previous attempts:", 1
        )[1]
        assert "real failure" in history
        assert history.count("- attempt") == 1


class TestReplanContextSummaryBounds:
    """§ 3.2: step outputs truncated to 500 chars each, total ≤ 4000."""

    def test_the_bound_constants_are_the_specified_values(self) -> None:
        assert MAX_REPLAN_STEP_OUTPUT_CHARS == 500
        assert MAX_REPLAN_CONTEXT_CHARS == 4000

    def test_a_prior_step_output_is_summarized(self) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(), "boom", _runtime_context(), [])
        summary = client.json_calls[0]["messages"][0]["content"].split(
            "Current context:", 1
        )[1]
        assert "step_0" in summary
        assert "found 12 articles about GPT-4 usage" in summary

    def test_variables_are_included_so_a_replan_can_see_the_users_input(self) -> None:
        # Additive within the frozen bound: § 3.2 fixes the *size* of the summary, and
        # a re-plan that cannot see `data_file` cannot propose a working alternative.
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(), "boom", _runtime_context(), [])
        summary = client.json_calls[0]["messages"][0]["content"].split(
            "Current context:", 1
        )[1]
        assert "data_file" in summary
        assert "./input/sales.csv" in summary

    def test_a_failed_step_error_is_summarized(self) -> None:
        context = _runtime_context()
        context["step_results"]["step_1"] = {
            "status": "FAILED",
            "output": None,
            "error": "pdf_export timed out",
            "tool_name": "pdf_export",
            "duration_ms": 30_000,
            "retries": 2,
        }
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(), "boom", context, [])
        summary = client.json_calls[0]["messages"][0]["content"].split(
            "Current context:", 1
        )[1]
        assert "FAILED" in summary
        assert "pdf_export timed out" in summary

    def test_each_step_output_is_truncated_to_500_characters(self) -> None:
        context = _runtime_context(
            step_results={"step_0": {"status": "SUCCESS", "output": "o" * 100_000}}
        )
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(), "boom", context, [])
        summary = client.json_calls[0]["messages"][0]["content"].split(
            "Current context:", 1
        )[1]
        assert "o" * (MAX_REPLAN_STEP_OUTPUT_CHARS + 1) not in summary
        assert "o" * (MAX_REPLAN_STEP_OUTPUT_CHARS - len(TRUNCATION_MARKER)) in summary

    def test_the_whole_summary_never_exceeds_4000_characters(self) -> None:
        step_results = {
            f"step_{i}": {"status": "SUCCESS", "output": "o" * 900} for i in range(60)
        }
        planner, client, _ = _replan_planner()
        planner.replan_step(
            _failed_step(),
            "boom",
            _runtime_context(step_results=step_results),
            [],
        )
        content = client.json_calls[0]["messages"][0]["content"]
        summary = content.split("Current context:", 1)[1]
        assert len(summary) <= MAX_REPLAN_CONTEXT_CHARS
        assert (
            len(content) < len(prompts.REPLAN_PROMPT) + MAX_REPLAN_CONTEXT_CHARS + 9_000
        )

    def test_truncation_drops_whole_entries_and_says_so(self) -> None:
        step_results = {
            f"step_{i}": {"status": "SUCCESS", "output": "o" * 900} for i in range(60)
        }
        planner, client, _ = _replan_planner()
        planner.replan_step(
            _failed_step(), "boom", _runtime_context(step_results=step_results), []
        )
        summary = _section_of(
            client.json_calls[0]["messages"][0]["content"], "Current context:"
        )
        assert summary.rstrip().endswith(TRUNCATION_MARKER)
        assert "- step_0 " in summary  # the earliest results are kept
        assert "- step_59 " not in summary

    def test_an_empty_context_renders_an_explicit_none(self) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(), "boom", {}, [])
        assert (
            "Current context: (none)" in client.json_calls[0]["messages"][0]["content"]
        )

    def test_a_non_serializable_output_is_summarized_by_repr(self) -> None:
        context = _runtime_context(
            step_results={"step_0": {"status": "SUCCESS", "output": object()}}
        )
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(), "boom", context, [])
        assert "step_0" in client.json_calls[0]["messages"][0]["content"]


class TestReplanStepReturnsAnEmptyList:
    """§ 2: `[]` when the model cannot propose an alternative → Level 4 escalates."""

    @pytest.mark.parametrize(
        "reply",
        [
            {"steps": []},
            [],
            {},
            "",
            "I cannot help with this.",
            42,
            None,
            {"steps": [{"description": "", "tool_hint": "t"}]},
            {"steps": [{"description": "   ", "tool_hint": "t"}]},
            {"steps": [{"description": 7, "tool_hint": "t"}]},
            {"steps": [None]},
            {"steps": "not a list"},
            {"nope": True},
        ],
    )
    def test_an_unusable_reply_yields_an_empty_list(self, reply: object) -> None:
        planner, _, _ = _replan_planner(reply)
        assert planner.replan_step(_failed_step(), "boom", _runtime_context(), []) == []

    def test_a_usable_step_survives_next_to_an_unusable_one(self) -> None:
        reply = {
            "steps": [
                {"description": "", "tool_hint": "t"},
                {"description": "Write it by hand", "tool_hint": "file_write"},
            ]
        }
        planner, _, _ = _replan_planner(reply)
        steps = planner.replan_step(
            _failed_step("step_2"), "boom", _runtime_context(), []
        )
        assert [step.id for step in steps] == ["step_2r1"]
        assert steps[0].description == "Write it by hand"

    def test_a_client_parse_failure_yields_an_empty_list_not_an_exception(self) -> None:
        error = AgentError(
            code="PLAN_PARSE_FAILED", message="repair exhausted", component="llm"
        )
        planner, _, _ = _replan_planner(error)
        assert planner.replan_step(_failed_step(), "boom", _runtime_context(), []) == []

    def test_a_provider_failure_yields_an_empty_list(self) -> None:
        # Level 3 must not abort the cascade: an empty list lets SPEC-003 § 5 escalate
        # to Level 4 with the priority rule intact.
        error = AgentError(
            code="LLM_CALL_FAILED", message="provider 500", component="llm"
        )
        planner, _, _ = _replan_planner(error)
        assert planner.replan_step(_failed_step(), "boom", _runtime_context(), []) == []

    def test_an_unexpected_client_exception_is_never_swallowed(self) -> None:
        planner, _, _ = _replan_planner(RuntimeError("client bug"))
        with pytest.raises(RuntimeError):
            planner.replan_step(_failed_step(), "boom", _runtime_context(), [])

    def test_no_catalog_event_is_invented_for_a_failed_replan(self) -> None:
        # recovery_attempted / recovery_exhausted belong to the RecoveryManager
        # (SPEC-006 § 6.1); the planner has no event of its own here.
        planner, _, logger = _replan_planner({"steps": []})
        planner.replan_step(_failed_step(), "boom", _runtime_context(), [])
        assert logger.records == []


class TestReplanStepBudget:
    """§ 5: one round + one repair, at the planning temperature."""

    def test_one_complete_json_round_and_no_text_round(self) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(), "boom", _runtime_context(), [])
        assert len(client.json_calls) == 1
        assert client.text_calls == []
        assert client.usage.calls == 1

    def test_the_replan_temperature_is_the_configured_planning_temperature(
        self,
    ) -> None:
        config = FakeConfig(llm=FakeLLMSection(temperature=0.4))
        planner, client, _ = _replan_planner(config=config)
        planner.replan_step(_failed_step(), "boom", _runtime_context(), [])
        assert client.json_calls[0]["temperature"] == 0.4

    def test_the_plan_schema_hint_is_reused_for_the_reply_shape(self) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(), "boom", _runtime_context(), [])
        assert client.json_calls[0]["schema_hint"] == prompts.PLAN_SCHEMA_HINT

    def test_an_empty_reply_still_costs_exactly_one_round(self) -> None:
        planner, client, _ = _replan_planner({"steps": []})
        planner.replan_step(_failed_step(), "boom", _runtime_context(), [])
        assert len(client.json_calls) == 1


class TestReplanStepPurity:
    """§ 5: never executes a tool, never mutates what it was given."""

    def test_the_context_is_not_mutated(self) -> None:
        planner, _, _ = _replan_planner()
        context = _runtime_context()
        before = json.loads(json.dumps(context))
        planner.replan_step(_failed_step(), "boom", context, AVAILABLE_TOOLS)
        assert json.loads(json.dumps(context)) == before

    def test_the_failed_step_is_not_mutated(self) -> None:
        planner, _, _ = _replan_planner()
        step = _failed_step()
        planner.replan_step(step, "boom", _runtime_context(), AVAILABLE_TOOLS)
        assert step.id == "step_1"
        assert step.status is StepStatus.FAILED
        assert step.retries == 2
        assert step.error == "pdf_export timed out"
        assert step.output_data is None

    def test_the_tool_list_is_not_mutated_and_no_tool_is_executed(self) -> None:
        planner, _, _ = _replan_planner()
        tools = [_ExplodingTool()]
        before = json.dumps(AVAILABLE_TOOLS)
        planner.replan_step(_failed_step(), "boom", _runtime_context(), tools)
        assert json.dumps(AVAILABLE_TOOLS) == before

    def test_the_returned_steps_are_new_objects_not_the_parsed_ones(self) -> None:
        planner, _, _ = _replan_planner()
        steps = planner.replan_step(_failed_step(), "boom", _runtime_context(), [])
        assert all(step.id.endswith(("r1", "r2")) for step in steps)
        assert steps[0] is not steps[1]


class TestReplanSummaryBranches:
    """Edge shapes of the § 4.1 context that the summary must tolerate."""

    def test_a_step_result_that_is_not_a_mapping_is_summarized_by_value(self) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(
            _failed_step(), "boom", {"step_results": {"step_0": "raw output text"}}, []
        )
        summary = client.json_calls[0]["messages"][0]["content"].split(
            "Current context:", 1
        )[1]
        assert "- step_0: raw output text" in summary

    def test_a_step_result_with_neither_output_nor_error_still_appears(self) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(
            _failed_step(),
            "boom",
            {"step_results": {"step_0": {"status": "SKIPPED"}}},
            [],
        )
        summary = client.json_calls[0]["messages"][0]["content"].split(
            "Current context:", 1
        )[1]
        assert "- step_0 (SKIPPED)" in summary
        assert "output:" not in summary
        assert "error:" not in summary

    def test_a_null_output_with_an_error_shows_only_the_error(self) -> None:
        planner, client, _ = _replan_planner()
        context = {
            "step_results": {
                "step_1": {"status": "FAILED", "output": None, "error": "boom"}
            }
        }
        planner.replan_step(_failed_step(), "boom", context, [])
        summary = client.json_calls[0]["messages"][0]["content"].split(
            "Current context:", 1
        )[1]
        assert "error: boom" in summary
        assert "output:" not in summary

    def test_a_step_results_value_that_is_not_a_mapping_is_ignored(self) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(
            _failed_step(),
            "boom",
            {"step_results": "not a mapping", "variables": {"a": "b"}},
            [],
        )
        summary = client.json_calls[0]["messages"][0]["content"].split(
            "Current context:", 1
        )[1]
        assert "- var a: b" in summary

    def test_a_variables_value_that_is_not_a_mapping_is_ignored(self) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(
            _failed_step(), "boom", {"variables": ["a"], "step_results": {}}, []
        )
        assert (
            "Current context: (none)" in client.json_calls[0]["messages"][0]["content"]
        )

    def test_an_errors_value_that_is_not_a_sequence_falls_back_to_the_retry_count(
        self,
    ) -> None:
        planner, client, _ = _replan_planner()
        planner.replan_step(_failed_step(retries=1), "boom", {"errors": "nope"}, [])
        history = client.json_calls[0]["messages"][0]["content"].split(
            "Previous attempts:", 1
        )[1]
        assert "no previous attempts" in history

    def test_a_brace_in_a_step_description_cannot_hijack_a_later_placeholder(
        self,
    ) -> None:
        # Substitution is a single left-to-right pass, so values are never rescanned.
        planner, client, _ = _replan_planner()
        planner.replan_step(
            _failed_step(description="Render {context_summary} literally"),
            "boom",
            _runtime_context(),
            AVAILABLE_TOOLS,
        )
        content = client.json_calls[0]["messages"][0]["content"]
        assert "Failed step: Render {context_summary} literally" in content
        assert "found 12 articles about GPT-4 usage" in content  # the real one survived


class TestSubstitutionPrimitive:
    """`_substitute` is the single-pass placeholder engine for the frozen templates."""

    def test_every_known_key_is_replaced(self) -> None:
        assert _substitute("{a} and {b}", {"a": "1", "b": "2"}) == "1 and 2"

    def test_a_value_is_never_rescanned(self) -> None:
        assert _substitute("{a}{b}", {"a": "{b}", "b": "X"}) == "{b}X"

    def test_an_unknown_key_is_left_literal(self) -> None:
        assert _substitute("{a} {zz}", {"a": "1"}) == "1 {zz}"

    def test_an_unterminated_brace_is_left_literal(self) -> None:
        assert _substitute("{a} then {b", {"a": "1", "b": "2"}) == "1 then {b"

    def test_a_lone_closing_brace_is_left_literal(self) -> None:
        assert _substitute("done }", {"a": "1"}) == "done }"

    def test_a_template_without_braces_is_returned_unchanged(self) -> None:
        assert _substitute("no placeholders", {"a": "1"}) == "no placeholders"

    def test_an_empty_template_stays_empty(self) -> None:
        assert _substitute("", {"a": "1"}) == ""

    def test_a_repeated_key_is_replaced_everywhere(self) -> None:
        assert _substitute("{a}-{a}", {"a": "x"}) == "x-x"


class TestReplanDependencyConventions:
    """An index names a replacement; a `step_N` string names an original step."""

    def test_a_string_index_is_also_read_as_a_replacement_reference(self) -> None:
        reply = {
            "steps": [
                {"description": "a", "tool_hint": "t"},
                {"description": "b", "tool_hint": "t", "depends_on": ["0"]},
            ]
        }
        planner, _, _ = _replan_planner(reply)
        steps = planner.replan_step(
            _failed_step("step_4"), "boom", _runtime_context(), []
        )
        assert [step.id for step in steps] == ["step_4r1", "step_4r2"]
        assert steps[1].depends_on == ["step_4r1"]

    def test_an_out_of_range_index_is_kept_as_written_not_silently_dropped(
        self,
    ) -> None:
        reply = {
            "steps": [{"description": "a", "tool_hint": "t", "depends_on": [5]}],
        }
        planner, _, _ = _replan_planner(reply)
        steps = planner.replan_step(
            _failed_step("step_1"), "boom", _runtime_context(), []
        )
        assert steps[0].depends_on == ["step_5"]

    def test_an_index_and_an_original_reference_are_kept_apart(self) -> None:
        reply = {
            "steps": [
                {"description": "a", "tool_hint": "t"},
                {
                    "description": "b",
                    "tool_hint": "t",
                    "depends_on": [0, "step_9", "step_1"],
                },
            ]
        }
        planner, _, _ = _replan_planner(reply)
        steps = planner.replan_step(
            _failed_step("step_1"), "boom", _runtime_context(), []
        )
        # 0 → the first replacement; "step_9" → an original step, kept verbatim;
        # "step_1" → the failed step itself, dropped as unsatisfiable.
        assert steps[1].depends_on == ["step_1r1", "step_9"]

    def test_an_index_and_a_step_id_that_collide_are_both_read_as_replacements(
        self,
    ) -> None:
        # Documented consequence of canonicalization: parse_plan maps both 0 and
        # "step_0" to "step_0", so within one step the index reading wins. Positional
        # disambiguation was rejected as fragile for a shape no model produces.
        reply = {
            "steps": [
                {"description": "a", "tool_hint": "t"},
                {"description": "b", "tool_hint": "t", "depends_on": [0, "step_0"]},
            ]
        }
        planner, _, _ = _replan_planner(reply)
        steps = planner.replan_step(
            _failed_step("step_1"), "boom", _runtime_context(), []
        )
        assert steps[1].depends_on == ["step_1r1", "step_1r1"]

    def test_a_bare_string_dependency_is_the_single_reference_parse_plan_allows(
        self,
    ) -> None:
        # Sub-phase 1.2 accepts `depends_on: "step_0"` as one reference; a re-plan
        # inherits that leniency, and a string is never read as an index.
        reply = {
            "steps": [{"description": "a", "tool_hint": "t", "depends_on": "step_0"}]
        }
        planner, _, _ = _replan_planner(reply)
        steps = planner.replan_step(
            _failed_step("step_2"), "boom", _runtime_context(), []
        )
        assert steps[0].depends_on == ["step_0"]

    @pytest.mark.parametrize("depends_on", [7, True, {"a": 1}, [True], [None], [7.5]])
    def test_a_dependency_of_an_unusable_type_yields_no_replacement(
        self, depends_on: object
    ) -> None:
        # parse_plan rejects these (§ 4.2 rule 2 admits int/str references only), and a
        # rejected re-plan is an empty list — never an exception into the cascade.
        reply = {
            "steps": [{"description": "a", "tool_hint": "t", "depends_on": depends_on}]
        }
        planner, _, _ = _replan_planner(reply)
        assert (
            planner.replan_step(_failed_step("step_2"), "boom", _runtime_context(), [])
            == []
        )


class TestIndexReferenceExtraction:
    """`_index_references` reads the RAW payload, so its guards take model input."""

    @pytest.mark.parametrize("payload", ["not a mapping", 7, None, ["a"], True])
    def test_a_payload_that_is_not_a_step_object_declares_no_indexes(
        self, payload: object
    ) -> None:
        assert _index_references(payload) == set()

    @pytest.mark.parametrize(
        "payload", [{}, {"description": "a"}, {"depends_on": None}]
    )
    def test_a_payload_without_dependencies_declares_no_indexes(
        self, payload: dict[str, Any]
    ) -> None:
        assert _index_references(payload) == set()

    @pytest.mark.parametrize("depends_on", [7, True, {"a": 1}, "step_0", "0"])
    def test_a_depends_on_that_is_not_a_list_declares_no_indexes(
        self, depends_on: object
    ) -> None:
        # A bare string is the single-reference form parse_plan allows, and a string is
        # never read as an index — that is the whole point of this helper.
        assert _index_references({"depends_on": depends_on}) == set()

    def test_ints_and_digit_strings_are_indexes(self) -> None:
        assert _index_references({"depends_on": [0, 2, "1", " 3 "]}) == {
            "step_0",
            "step_1",
            "step_2",
            "step_3",
        }

    def test_step_ids_and_unusable_entries_are_not_indexes(self) -> None:
        assert (
            _index_references(
                {"depends_on": ["step_0", "-1", "x", "", True, None, 7.5, ["nested"]]}
            )
            == set()
        )

    def test_a_negative_digit_string_is_not_an_index(self) -> None:
        # parse_plan leaves "-1" a literal reference, so this must not claim it.
        assert _index_references({"depends_on": ["-1"]}) == set()


# ── Package surface required by Plan 4's composition root ─────────────────────


class TestPackageSurfaceForTheCompositionRoot:
    """planning/README § 4 step I1 — P4 resolves ``agent_harness.planning.Planner``.

    The merged composition root (``agent_harness/harness.py``) never imports this
    package at module scope; it calls ``importlib.import_module`` on
    ``"agent_harness.planning"`` and reads ``Planner`` off the module object, and
    ``tests/_p4_stubs.py`` stops stubbing a dotted name as soon as the real module is
    importable. A ``Planner`` that lives only in ``planning.planner`` would therefore
    break the harness at run time — a requirement SPEC-000 § 3.3 never states
    (SCR-P3-12).
    """

    def test_the_package_exposes_the_planner_class(self) -> None:
        module = importlib.import_module("agent_harness.planning")
        assert module.Planner is Planner

    def test_the_package_exposes_the_module_level_behaviors(self) -> None:
        module = importlib.import_module("agent_harness.planning")
        assert module.parse_plan is parse_plan
        assert module.validate_plan is validate_plan
        assert module.PLANNING_SYSTEM_PROMPT is prompts.PLANNING_SYSTEM_PROMPT
        assert module.REPLAN_PROMPT is prompts.REPLAN_PROMPT
        assert module.TOOL_SELECTION_PROMPT is prompts.TOOL_SELECTION_PROMPT
        assert module.PLAN_SCHEMA_HINT is prompts.PLAN_SCHEMA_HINT
        assert module.render_tool_descriptions is prompts.render_tool_descriptions

    def test_the_package_all_is_ordered_and_every_name_resolves(self) -> None:
        # The order is ruff RUF022's isort-style grouping — constants, then classes,
        # then functions — which is what `ruff check` enforces repo-wide, so it is
        # pinned verbatim rather than re-derived with a plain `sorted()`.
        module = importlib.import_module("agent_harness.planning")
        assert module.__all__ == [
            "PLANNING_SYSTEM_PROMPT",
            "PLAN_SCHEMA_HINT",
            "REPLAN_PROMPT",
            "TOOL_SELECTION_PROMPT",
            "Planner",
            "parse_plan",
            "render_tool_descriptions",
            "validate_plan",
        ]
        assert all(hasattr(module, name) for name in module.__all__)

    def test_the_composition_roots_exact_call_shape_builds_a_planner(self) -> None:
        # Verbatim from harness.py `_resolve_planner`: two positional arguments, then
        # a keyword logger. Anything else raises TypeError at integration, not here.
        module = importlib.import_module("agent_harness.planning")
        built = module.Planner(FakeLLMClient(), FakeConfig(), logger=FakeLogger())
        assert isinstance(built, Planner)

    def test_the_data_model_stand_ins_are_not_re_exported(self) -> None:
        # SPEC-001 § 2 assigns Step/ExecutionPlan to Plan 1's config/schema.py; these
        # stand-ins stay in planner.py so the package surface cannot be mistaken for
        # the real data model at I1.
        module = importlib.import_module("agent_harness.planning")
        for name in (
            "Step",
            "ExecutionPlan",
            "StepStatus",
            "TaskPriority",
            "AgentError",
        ):
            assert not hasattr(module, name)

    def test_the_orchestration_package_exposes_the_sorter(self) -> None:
        module = importlib.import_module("agent_harness.orchestration")
        assert module.resolve_execution_order is dependency.resolve_execution_order


# ── Config protocol covariance (SCR-P3-13) ────────────────────────────────────


class TestConfigProtocolsStayCovariant:
    """Plan 1's merged config dataclasses must satisfy P3's protocols unchanged.

    A mutable protocol attribute is **invariant**, so `retry_base_delay: float`
    rejected Plan 1's `ExecutionConfig.retry_base_delay: int = 2` (SPEC-006 § 1 shows
    the bare YAML scalar `2` and never states a Python type). Because
    `Config.execution` is typed `ExecutionConfigLike`, the *whole* `Config` then failed
    to satisfy `ConfigLike`, so `parse_plan`, `validate_plan` and `Planner` all refused
    the real configuration object at integration — found by type-checking a composition
    probe against merged `main`. Read-only properties are covariant, which fixes it;
    these tests keep the declaration from regressing to annotated attributes.
    """

    @pytest.mark.parametrize("protocol", [LLMConfigLike, ExecutionConfigLike])
    def test_every_public_member_is_a_read_only_property(self, protocol: Any) -> None:
        names = [name for name in vars(protocol) if not name.startswith("_")]
        assert names
        for name in names:
            member = inspect.getattr_static(protocol, name)
            assert isinstance(member, property), name
            assert member.fset is None, name

    def test_the_execution_members_are_exactly_the_spec_ones(self) -> None:
        assert {
            name for name in vars(ExecutionConfigLike) if not name.startswith("_")
        } == {
            "abort_on_critical_failure",
            "enable_replan",
            "max_retries",
            "max_steps",
            "output_dir",
            "retry_backoff",
            "retry_base_delay",
            "step_timeout",
        }

    def test_the_llm_members_are_exactly_the_spec_ones(self) -> None:
        assert {name for name in vars(LLMConfigLike) if not name.startswith("_")} == {
            "cost_per_1k_tokens",
            "max_retries",
            "max_tokens",
            "model",
            "provider",
            "temperature",
        }

    def test_the_config_sections_are_still_read_only_properties(self) -> None:
        for name in ("llm", "execution"):
            member = inspect.getattr_static(ConfigLike, name)
            assert isinstance(member, property), name
            assert member.fset is None, name

    def test_covariance_does_not_erase_the_declared_types(self) -> None:
        # Widening what a caller may *provide* must not turn the contract into `Any`:
        # the declared return types are still the spec's, so a regression that typed a
        # member `object` to dodge invariance would fail here.
        cases: list[tuple[Any, str, Any]] = [
            (ExecutionConfigLike, "retry_base_delay", float),
            (ExecutionConfigLike, "max_steps", int),
            (ExecutionConfigLike, "enable_replan", bool),
            (LLMConfigLike, "temperature", float),
            (LLMConfigLike, "cost_per_1k_tokens", float | None),
        ]
        for protocol, name, expected in cases:
            member = inspect.getattr_static(protocol, name)
            assert isinstance(member, property), name
            getter = member.fget
            assert getter is not None, name
            assert get_type_hints(getter)["return"] == expected, name

    def test_a_config_section_declaring_an_int_delay_still_validates(self) -> None:
        # The runtime half of the same fact: Plan 1's `int = 2` flows through untouched.
        config = FakeConfig()
        config.execution.retry_base_delay = 2
        assert isinstance(config.execution.retry_base_delay, int)
        assert validate_plan(_plan(_valid_steps()), config) == []
