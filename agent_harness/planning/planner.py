"""LLM task decomposition: plan parsing, validation and the ``Planner``.

Spec: SPEC-004 § 2 (``Planner`` interface, FROZEN), § 4 (plan JSON schema,
parsing/normalization rules and validation checks V1-V7), § 5 (determinism and
cost controls); SPEC-001 § 1-2 (data model), § 3 (error codes); SPEC-000 § 2
(layer L2 Cognition).

Layering and parallel execution
------------------------------
This module sits at L2 and must not import any concrete module from Plan 1
(``agent_harness.config``, ``agent_harness.llm``, ``agent_harness.context``,
``agent_harness.logging``) or Plan 2 (``agent_harness.tools``) — SPEC-000 § 4 and
agent.md F3. Every collaborator therefore arrives by **injection** and is typed
**structurally** (``typing.Protocol``): ``LLMClientLike``, ``ConfigLike``,
``LoggerLike``, ``ModelProvider``.

Because SPEC-001 § 2 places the data-model classes in Plan 1's
``agent_harness/config/schema.py`` while SPEC-004 § 2 requires *this* module to
construct ``Step`` and ``ExecutionPlan`` objects, section A below ships P3-local
**spec-conformant stand-ins** — field-for-field identical to SPEC-001 § 1-2.4 and
pinned by contract tests in ``tests/test_planner.py`` (SPEC-000 § 5.4). They are
used only when no ``ModelProvider`` is injected; Plan 4's composition root passes
the real Plan 1 classes and nothing here changes (SCR-P3-6). Statuses and
priorities are always compared through their ``.value`` strings, so a graph mixing
injected Plan 1 enums with these stand-ins can never compare unequal.

Section A also hosts the shared injected-contract kit for
``agent_harness.orchestration`` because SPEC-000 § 3.3 gives this plan no separate
contracts module to put it in.

``Any`` usage (strict-typing-contracts § 3.2 allowlist, with reasons)
--------------------------------------------------------------------
``Any`` appears only where a frozen contract already types it that way and is
never propagated into a P3-authored signature:

* ``input_data``/``output_data``/``context``/``final_output``/``metadata`` —
  verbatim ``Any``-typed fields of SPEC-001 § 2.1-2.3 and SPEC-003 § 4.1.
* ``status``/``priority`` on the ``*Like`` protocols — enum *identity* differs
  between an injected Plan 1 model set and these stand-ins; both are narrowed
  immediately by :func:`status_value` / :func:`priority_value`.
* ``**fields`` on ``LoggerLike`` and the return of ``ConfigLike.get`` — the
  signatures of SPEC-006 § 6.2 and § 1.1 respectively.
* Parsed-JSON values are typed ``object`` and narrowed with ``isinstance``, not
  ``Any``: LLM output is a trust boundary (strict-typing-contracts § 3.4).

Skills applied: SKL-CORE-TYPES (core-coding/strict-typing-contracts),
SKL-CORE-TDD (core-coding/tdd-test-runner), SKL-REL-SCHEMA
(reliability/schema-compatibility — additive/forward-compatible schema reading),
SKL-REL-FUZZ (reliability/api-fuzz-tester — untrusted input, bounded errors).
"""

from __future__ import annotations

import copy
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from datetime import datetime
from enum import Enum
from typing import Any, ClassVar, NoReturn, Protocol

from agent_harness.planning.prompts import (
    PLAN_SCHEMA_HINT,
    PLANNING_SYSTEM_PROMPT,
    REPLAN_PROMPT,
    TOOL_SELECTION_PROMPT,
    render_tool_descriptions,
)

__all__ = [
    "CONTEXT_SUMMARY_HEADER",
    "MAX_ATTEMPT_HISTORY_ENTRIES",
    "MAX_CONTEXT_SUMMARY_CHARS",
    "MAX_CONTEXT_VALUE_CHARS",
    "MAX_JSON_EXTRACTION_ATTEMPTS",
    "MAX_RAW_PAYLOAD_CHARS",
    "MAX_REPLAN_CONTEXT_CHARS",
    "MAX_REPLAN_STEP_OUTPUT_CHARS",
    "MAX_STEP_DESCRIPTION_CHARS",
    "TRUNCATION_MARKER",
    "AgentError",
    "AgentErrorLike",
    "AgentErrorRaised",
    "ConfigLike",
    "ExecutionConfigLike",
    "ExecutionPlan",
    "LLMClientLike",
    "LLMConfigLike",
    "LLMResponseLike",
    "LLMUsageLike",
    "LoggerLike",
    "ModelProvider",
    "NullLogger",
    "PlanLike",
    "Planner",
    "SpecModels",
    "Step",
    "StepLike",
    "StepStatus",
    "TaskPriority",
    "ToolResult",
    "ToolResultLike",
    "parse_plan",
    "priority_rank",
    "priority_value",
    "render_tool_descriptions",
    "status_value",
    "strip_code_fences",
    "validate_plan",
]

# ══════════════════════════════════════════════════════════════════════════════
# A. Injected model contracts (SPEC-001 § 1-2) and their P3-local stand-ins
# ══════════════════════════════════════════════════════════════════════════════


class StepStatus(Enum):
    """Step lifecycle states.

    Spec: SPEC-001 § 1.1 — FROZEN member names and values.
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class TaskPriority(Enum):
    """Step failure semantics.

    Spec: SPEC-001 § 1.2 — FROZEN member names and values. Ascending severity is
    CRITICAL > HIGH > MEDIUM > LOW; :data:`PRIORITY_RANK` makes that ordering
    explicit for the dependency gate (SPEC-003 § 3 step 1) and Level 4 escalation
    (SPEC-003 § 5).
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


PRIORITY_RANK: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}
"""Severity order of SPEC-001 § 1.2, lowest number = most severe."""


def status_value(status: object) -> str:
    """Return the SPEC-001 § 1.1 string value of a status.

    Accepts an ``Enum`` member (Plan 1's or this module's), a bare string, or
    ``None``, so callers never compare enum *identity* across injection
    boundaries.

    Args:
        status: A status enum member, its string value, or ``None``.

    Returns:
        The lower-case status value; ``""`` when ``status`` is ``None``.
    """
    if status is None:
        return ""
    return str(status.value if isinstance(status, Enum) else status)


def priority_value(priority: object) -> str:
    """Return the SPEC-001 § 1.2 string value of a priority.

    Args:
        priority: A priority enum member, its string value, or ``None``.

    Returns:
        The lower-case priority value; ``""`` when ``priority`` is ``None``.
    """
    if priority is None:
        return ""
    return str(priority.value if isinstance(priority, Enum) else priority)


def priority_rank(priority: object) -> int:
    """Return the severity rank of *priority* (0 = CRITICAL, 3 = LOW).

    Args:
        priority: A priority enum member or its string value.

    Returns:
        The rank from :data:`PRIORITY_RANK`; unknown values rank as HIGH (1), the
        default SPEC-004 § 4.2 assigns to unrecognized priorities.
    """
    return PRIORITY_RANK.get(priority_value(priority), PRIORITY_RANK["high"])


class StepLike(Protocol):
    """Structural type of a plan step (SPEC-001 § 2.1).

    ``status`` and ``priority`` are ``Any`` because enum identity differs between
    an injected Plan 1 model set and :class:`Step`; read them through
    :func:`status_value` / :func:`priority_value` and write them through
    :meth:`ModelProvider.step_status` / :meth:`ModelProvider.task_priority`.
    """

    id: str
    description: str
    tool_hint: str
    tool_name: str
    input_data: dict[str, Any]
    output_data: Any
    status: Any
    error: str | None
    retries: int
    max_retries: int
    fallback_tools: list[str]
    depends_on: list[str]
    priority: Any
    started_at: datetime | None
    completed_at: datetime | None

    @property
    def duration_ms(self) -> int | None:
        """Elapsed milliseconds, or ``None`` unless both timestamps are set."""
        ...

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe mapping (SPEC-001 § 4)."""
        ...


class PlanLike(Protocol):
    """Structural type of an execution plan (SPEC-001 § 2.2).

    ``steps`` is a read-only property returning a ``Sequence``: ``list`` is
    invariant, so declaring it as a mutable ``list[StepLike]`` attribute would
    reject every concrete plan whose steps are a narrower type — including Plan 1's
    real ``ExecutionPlan`` at integration. The orchestrator mutates the *steps*
    (status, output, timings), never the list itself, so read-only is sufficient.
    """

    id: str
    original_prompt: str
    context: dict[str, Any]
    created_at: datetime
    status: Any
    final_output: Any

    @property
    def steps(self) -> Sequence[StepLike]:
        """The plan's steps, in declaration order."""
        ...

    def step_by_id(self, step_id: str) -> StepLike | None:
        """Return the step with this id, or ``None``."""
        ...

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe mapping (SPEC-001 § 4)."""
        ...


class ToolResultLike(Protocol):
    """Structural type of a tool result (SPEC-001 § 2.3, FROZEN cross-plan contract)."""

    success: bool
    output: Any
    error: str | None
    metadata: dict[str, Any]


class AgentErrorLike(Protocol):
    """Structural type of a spec error (SPEC-001 § 2.4)."""

    code: str
    message: str
    component: str
    step_id: str | None
    recoverable: bool
    recovery_action: str | None
    original_error: str | None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe mapping."""
        ...


class AgentErrorRaised(RuntimeError):
    """Raised when an injected ``AgentError`` object is not itself raisable.

    SPEC-003 § 2/§ 5 require ``raise AgentError(code=...)`` while SPEC-001 § 2.4
    declares ``AgentError`` as a plain dataclass (SCR-P3-7). Every raise site in
    this plan narrows with ``isinstance(error, BaseException)``: a raisable
    injected error propagates unchanged, and anything else is wrapped here so the
    failure is never swallowed.

    Attributes:
        error: The spec-shaped error object (SPEC-001 § 2.4).
        code: The SPEC-001 § 3 error code, hoisted for convenient ``except`` handling.
    """

    def __init__(self, error: AgentErrorLike) -> None:
        """Wrap *error* as an exception.

        Args:
            error: The spec-shaped error object to surface.
        """
        super().__init__(error.message)
        self.error: AgentErrorLike = error
        self.code: str = error.code

    def __str__(self) -> str:
        """Render the wrapped error per SPEC-001 § 2.4."""
        return str(self.error)


@dataclass
class AgentError(AgentErrorRaised):
    """P3-local stand-in for SPEC-001 § 2.4 ``AgentError`` — a dataclass *and* raisable.

    Field names, order, types and defaults are verbatim from the spec. Plan 4 may
    inject Plan 1's real class instead; nothing in this plan depends on this one.
    """

    code: str
    message: str
    component: str
    step_id: str | None = None
    recoverable: bool = False
    recovery_action: str | None = None
    original_error: str | None = None

    def __post_init__(self) -> None:
        """Populate ``Exception.args`` so the error survives logging and pickling."""
        RuntimeError.__init__(self, str(self))
        self.error = self

    def __str__(self) -> str:
        """Render ``"[code] component(step_id): message"`` (SPEC-001 § 2.4)."""
        location = f"({self.step_id})" if self.step_id else ""
        return f"[{self.code}] {self.component}{location}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        """Serialize every field to a JSON-safe mapping (SPEC-001 § 2.4)."""
        return {
            "code": self.code,
            "message": self.message,
            "component": self.component,
            "step_id": self.step_id,
            "recoverable": self.recoverable,
            "recovery_action": self.recovery_action,
            "original_error": self.original_error,
        }


@dataclass
class ToolResult:
    """P3-local stand-in for SPEC-001 § 2.3 ``ToolResult``.

    Plan 2 owns the real class (``agent_harness/tools/base.py``); this copy exists
    so recovery and the assembler can synthesize results while Plan 2 is in flight.
    """

    success: bool
    output: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _datetime_or_none(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp, passing ``None`` and ``datetime`` through."""
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


class _DataclassLike(Protocol):
    """Any dataclass instance — lets :func:`_dump_fields` stay suppression-free."""

    __dataclass_fields__: ClassVar[dict[str, Any]]


def _dump_fields(instance: _DataclassLike) -> dict[str, Any]:
    """Serialize dataclass fields to JSON-safe values (SPEC-001 § 4).

    Enums become their ``.value``, datetimes become ISO-8601 strings, and
    list/dict fields are copied so the dump never aliases live state.
    """
    dumped: dict[str, Any] = {}
    for spec_field in dataclass_fields(instance):
        value = getattr(instance, spec_field.name)
        if isinstance(value, Enum):
            dumped[spec_field.name] = value.value
        elif isinstance(value, datetime):
            dumped[spec_field.name] = value.isoformat()
        elif isinstance(value, list):
            dumped[spec_field.name] = list(value)
        elif isinstance(value, dict):
            dumped[spec_field.name] = dict(value)
        else:
            dumped[spec_field.name] = value
    return dumped


@dataclass
class Step:
    """P3-local stand-in for SPEC-001 § 2.1 ``Step`` — fields verbatim from the spec.

    Invariants enforced by the spec and relied on here: ``id`` is unique within a
    plan, ``retries <= max_retries``, ``status == SUCCESS`` implies ``error is
    None`` and ``status == FAILED`` implies ``error is not None``.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str = ""
    tool_hint: str = ""
    tool_name: str = ""
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: Any = None
    status: StepStatus = StepStatus.PENDING
    error: str | None = None
    retries: int = 0
    max_retries: int = 2
    fallback_tools: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    priority: TaskPriority = TaskPriority.HIGH
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def duration_ms(self) -> int | None:
        """Elapsed milliseconds, or ``None`` unless both timestamps are set."""
        if self.started_at is None or self.completed_at is None:
            return None
        return int((self.completed_at - self.started_at).total_seconds() * 1000)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe mapping (SPEC-001 § 4)."""
        return _dump_fields(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> Step:
        """Rebuild a step, ignoring unknown keys and defaulting missing ones.

        Args:
            data: A mapping produced by :meth:`to_dict` (or an LLM step object).

        Returns:
            The reconstructed step.

        Raises:
            TypeError: When *data* is not a mapping.
            ValueError: When a value has the wrong type or an unknown enum value.
        """
        if not isinstance(data, Mapping):
            raise TypeError(
                f"Step.from_dict expects a mapping, got {type(data).__name__}"
            )
        known = {spec_field.name for spec_field in dataclass_fields(cls)}
        kwargs: dict[str, Any] = {
            key: value for key, value in data.items() if key in known
        }
        if "status" in kwargs:
            kwargs["status"] = StepStatus(str(kwargs["status"]))
        if "priority" in kwargs:
            kwargs["priority"] = TaskPriority(str(kwargs["priority"]))
        for key in ("started_at", "completed_at"):
            if key in kwargs:
                kwargs[key] = _datetime_or_none(kwargs[key])
        for key in ("retries", "max_retries"):
            if key in kwargs:
                kwargs[key] = int(str(kwargs[key]))
        if "input_data" in kwargs:
            kwargs["input_data"] = dict(
                _require_mapping(kwargs["input_data"], "input_data")
            )
        for key in ("fallback_tools", "depends_on"):
            if key in kwargs:
                kwargs[key] = list(_require_sequence(kwargs[key], key))
        return cls(**kwargs)


@dataclass
class ExecutionPlan:
    """P3-local stand-in for SPEC-001 § 2.2 ``ExecutionPlan`` — fields verbatim."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    original_prompt: str = ""
    steps: list[Step] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    status: StepStatus = StepStatus.PENDING
    final_output: Any = None

    def step_by_id(self, step_id: str) -> Step | None:
        """Return the step with this id, or ``None`` when the plan has no such step."""
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe mapping that round-trips (SPEC-001 § 4)."""
        dumped = _dump_fields(self)
        dumped["steps"] = [step.to_dict() for step in self.steps]
        return dumped

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> ExecutionPlan:
        """Rebuild a plan, ignoring unknown keys and defaulting missing ones.

        Args:
            data: A mapping produced by :meth:`to_dict`.

        Returns:
            The reconstructed plan.

        Raises:
            TypeError: When *data* is not a mapping.
            ValueError: When a value has the wrong type or an unknown enum value.
        """
        if not isinstance(data, Mapping):
            raise TypeError(
                f"ExecutionPlan.from_dict expects a mapping, got {type(data).__name__}"
            )
        raw_steps = data.get("steps", [])
        steps = [
            Step.from_dict(_require_mapping(step, "steps entry"))
            for step in _require_sequence(raw_steps, "steps")
        ]
        kwargs: dict[str, Any] = {"steps": steps}
        for key in ("id", "original_prompt"):
            if key in data:
                kwargs[key] = str(data[key])
        if "context" in data:
            kwargs["context"] = dict(_require_mapping(data["context"], "context"))
        if "created_at" in data:
            created = _datetime_or_none(data["created_at"])
            kwargs["created_at"] = created if created is not None else datetime.now()
        if "status" in data:
            kwargs["status"] = StepStatus(str(data["status"]))
        if "final_output" in data:
            kwargs["final_output"] = data["final_output"]
        return cls(**kwargs)


def _require_mapping(value: object, name: str) -> Mapping[str, Any]:
    """Narrow *value* to a mapping or raise ``ValueError`` naming the field."""
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping, got {type(value).__name__}")
    return value


def _require_sequence(value: object, name: str) -> Sequence[object]:
    """Narrow *value* to a non-string sequence, else raise ``ValueError``."""
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a sequence, got {type(value).__name__}")
    return value


class ModelProvider(Protocol):
    """Factory for the SPEC-001 § 2 data-model objects this plan builds.

    Plan 4's composition root injects a provider backed by Plan 1's real classes;
    :class:`SpecModels` is the default so the cognition layer is buildable and
    testable while Plan 1 is still in flight (SCR-P3-6).
    """

    def step(self, **kwargs: Any) -> StepLike:
        """Build a step (SPEC-001 § 2.1) from keyword fields."""
        ...

    def plan(self, **kwargs: Any) -> PlanLike:
        """Build an execution plan (SPEC-001 § 2.2) from keyword fields."""
        ...

    def tool_result(
        self,
        *,
        success: bool,
        output: Any = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResultLike:
        """Build a tool result (SPEC-001 § 2.3)."""
        ...

    def agent_error(
        self,
        *,
        code: str,
        message: str,
        component: str,
        step_id: str | None = None,
        recoverable: bool = False,
        recovery_action: str | None = None,
        original_error: str | None = None,
    ) -> AgentErrorLike:
        """Build a spec error (SPEC-001 § 2.4)."""
        ...

    def step_status(self, name: str) -> Any:
        """Return the ``StepStatus`` member with this name (SPEC-001 § 1.1).

        Raises:
            KeyError: When no such member exists.
        """
        ...

    def task_priority(self, name: str) -> Any:
        """Return the ``TaskPriority`` member with this name (SPEC-001 § 1.2).

        Raises:
            KeyError: When no such member exists.
        """
        ...


class SpecModels:
    """Default :class:`ModelProvider`, building the P3-local spec stand-ins."""

    def step(self, **kwargs: Any) -> Step:
        """Build a :class:`Step`."""
        return Step(**kwargs)

    def plan(self, **kwargs: Any) -> ExecutionPlan:
        """Build an :class:`ExecutionPlan`."""
        return ExecutionPlan(**kwargs)

    def tool_result(
        self,
        *,
        success: bool,
        output: Any = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Build a :class:`ToolResult`."""
        return ToolResult(
            success=success, output=output, error=error, metadata=dict(metadata or {})
        )

    def agent_error(
        self,
        *,
        code: str,
        message: str,
        component: str,
        step_id: str | None = None,
        recoverable: bool = False,
        recovery_action: str | None = None,
        original_error: str | None = None,
    ) -> AgentError:
        """Build an :class:`AgentError`."""
        return AgentError(
            code=code,
            message=message,
            component=component,
            step_id=step_id,
            recoverable=recoverable,
            recovery_action=recovery_action,
            original_error=original_error,
        )

    def step_status(self, name: str) -> StepStatus:
        """Look up a :class:`StepStatus` member by name."""
        return StepStatus[name.upper()]

    def task_priority(self, name: str) -> TaskPriority:
        """Look up a :class:`TaskPriority` member by name."""
        return TaskPriority[name.upper()]


class LoggerLike(Protocol):
    """Structural type of ``StructuredLogger`` (SPEC-006 § 6.2).

    Only events from the SPEC-006 § 6.1 catalog are ever passed as ``event``
    (agent.md § 5); no P3 module invents an event name.
    """

    def log(self, level: str, component: str, event: str, **fields: Any) -> None:
        """Emit one structured record."""
        ...

    def debug(self, component: str, event: str, **fields: Any) -> None:
        """Emit a DEBUG record."""
        ...

    def info(self, component: str, event: str, **fields: Any) -> None:
        """Emit an INFO record."""
        ...

    def warning(self, component: str, event: str, **fields: Any) -> None:
        """Emit a WARNING record."""
        ...

    def error(self, component: str, event: str, **fields: Any) -> None:
        """Emit an ERROR record."""
        ...

    def child(self, component: str, **bound_fields: Any) -> LoggerLike:
        """Return a logger with *component* and extra fields bound."""
        ...


class NullLogger:
    """No-op :class:`LoggerLike` used when no logger is injected.

    SPEC-006 § 6.2 forbids module-level logger singletons, so this is a class that
    callers instantiate per object; it exists so the cognition layer never has to
    branch on ``logger is None`` at every call site.
    """

    def log(self, level: str, component: str, event: str, **fields: Any) -> None:
        """Discard the record."""

    def debug(self, component: str, event: str, **fields: Any) -> None:
        """Discard the record."""

    def info(self, component: str, event: str, **fields: Any) -> None:
        """Discard the record."""

    def warning(self, component: str, event: str, **fields: Any) -> None:
        """Discard the record."""

    def error(self, component: str, event: str, **fields: Any) -> None:
        """Discard the record."""

    def child(self, component: str, **bound_fields: Any) -> NullLogger:
        """Return this logger; there is nothing to bind."""
        return self


class LLMConfigLike(Protocol):
    """Structural type of the ``llm:`` config section (SPEC-006 § 1).

    Every member is a **read-only property**, because P3 only reads configuration and
    a mutable protocol attribute is invariant: declaring ``temperature: float`` would
    reject a concrete section that annotates the same value more narrowly. Covariance
    is what lets Plan 1's merged ``LLMConfig`` dataclass satisfy this protocol
    unchanged at integration, exactly as :class:`ConfigLike` relies on for its
    sections. A plain attribute still satisfies a read-only property, so test doubles
    need no change.
    """

    @property
    def provider(self) -> str:
        """``llm.provider`` — openai | anthropic | local (SPEC-006 § 1)."""
        ...

    @property
    def model(self) -> str:
        """``llm.model`` — the primary model name (SPEC-006 § 1)."""
        ...

    @property
    def max_tokens(self) -> int:
        """``llm.max_tokens`` — per-call completion budget (SPEC-006 § 1)."""
        ...

    @property
    def temperature(self) -> float:
        """``llm.temperature`` — planning temperature (SPEC-004 § 5, SPEC-006 § 1)."""
        ...

    @property
    def max_retries(self) -> int:
        """``llm.max_retries`` — client-level retries (SPEC-006 § 1)."""
        ...

    @property
    def cost_per_1k_tokens(self) -> float | None:
        """``llm.cost_per_1k_tokens`` — optional, for cost estimates (SPEC-006 § 1)."""
        ...


class ExecutionConfigLike(Protocol):
    """Structural type of the ``execution:`` config section (SPEC-006 § 1).

    Read-only properties for the covariance reason given on :class:`LLMConfigLike`.
    ``retry_base_delay`` is the case that made it concrete: SPEC-006 § 1 shows the
    bare YAML scalar ``retry_base_delay: 2`` without stating a Python type, Plan 1's
    merged ``ExecutionConfig`` declares it ``int = 2``, and this plan reads it as a
    number of seconds. An invariant ``float`` attribute rejected Plan 1's ``int``
    outright — so the whole ``Config`` failed to satisfy :class:`ConfigLike`, and
    every P3 entry point refused the real configuration object at integration. A
    covariant property accepts ``int`` where ``float`` is declared (SCR-P3-13).
    """

    @property
    def max_steps(self) -> int:
        """``execution.max_steps`` — the step-loop guard (SPEC-003 § 3 step 8)."""
        ...

    @property
    def step_timeout(self) -> int:
        """``execution.step_timeout`` — per-step seconds (SPEC-003 § 3 step 8)."""
        ...

    @property
    def max_retries(self) -> int:
        """``execution.max_retries`` — the step default (SPEC-004 § 4.2 rule 4)."""
        ...

    @property
    def retry_backoff(self) -> str:
        """``execution.retry_backoff`` — exponential | linear | fixed (SPEC-006 § 1)."""
        ...

    @property
    def retry_base_delay(self) -> float:
        """``execution.retry_base_delay`` — base seconds (an ``int`` satisfies it)."""
        ...

    @property
    def enable_replan(self) -> bool:
        """``execution.enable_replan`` — gates recovery Level 3 (SPEC-003 § 5)."""
        ...

    @property
    def abort_on_critical_failure(self) -> bool:
        """``execution.abort_on_critical_failure`` — gates PLAN_ABORTED (§ 2)."""
        ...

    @property
    def output_dir(self) -> str:
        """``execution.output_dir`` — where deliverables are written (SPEC-006 § 1)."""
        ...


class ConfigLike(Protocol):
    """Structural type of Plan 1's ``Config`` (SPEC-006 § 1, § 1.1 accessors).

    The section attributes are read-only properties so that a concrete config whose
    sections carry *extra* keys (Plan 1's full SPEC-006 § 1 schema) still satisfies
    this protocol; ``list``/attribute invariance would otherwise reject it.
    """

    @property
    def llm(self) -> LLMConfigLike:
        """The ``llm:`` section (SPEC-006 § 1)."""
        ...

    @property
    def execution(self) -> ExecutionConfigLike:
        """The ``execution:`` section (SPEC-006 § 1)."""
        ...

    def get(self, path: str, default: Any = None) -> Any:
        """Dotted-path lookup (SPEC-006 § 1.1)."""
        ...

    def to_dict(self, redact_secrets: bool = True) -> dict[str, Any]:
        """Secret-free dump, safe for logs and context (SPEC-006 § 1.1)."""
        ...


class LLMResponseLike(Protocol):
    """Structural type of SPEC-004 § 1 ``LLMResponse`` — fields verbatim, in order."""

    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str
    latency_ms: int


class LLMUsageLike(Protocol):
    """Structural type of SPEC-004 § 1 ``LLMUsage`` — cumulative process counters."""

    calls: int
    prompt_tokens: int
    completion_tokens: int
    estimated_cost: float


class LLMClientLike(Protocol):
    """Structural type of Plan 1's ``LLMClient`` (SPEC-004 § 1, FROZEN).

    The planner depends on this interface only — never on a provider SDK and never on
    ``agent_harness.llm`` (SPEC-000 § 2 layering, agent.md F3). Rule C3 puts fence
    stripping, JSON parsing and the single repair round *inside* ``complete_json``, so
    the planner makes exactly one call per :meth:`Planner.plan` (§ 5 token budget) and
    treats a raised ``AgentError`` as final.
    """

    @property
    def usage(self) -> LLMUsageLike:
        """Cumulative usage counters (SPEC-004 § 1 declares ``usage`` a property)."""
        ...

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponseLike:
        """Return one text completion (SPEC-004 § 1)."""
        ...

    def complete_json(
        self,
        messages: list[dict[str, Any]],
        *,
        schema_hint: str = "",
        temperature: float | None = None,
    ) -> tuple[Any, LLMResponseLike]:
        """Return ``(parsed_json, response)`` (SPEC-004 § 1, rule C3).

        The parsed value is typed ``Any`` because that is the frozen contract: it is
        untrusted model output, and :func:`parse_plan` narrows it with ``isinstance``
        rather than trusting it (strict-typing-contracts § 3.4).
        """
        ...


# ══════════════════════════════════════════════════════════════════════════════
# B. Plan JSON parsing and normalization (SPEC-004 § 4.1-4.2)
# ══════════════════════════════════════════════════════════════════════════════

MAX_RAW_PAYLOAD_CHARS = 500
"""Bound on raw LLM text echoed into an error message (SPEC-006 § 3.4)."""

MAX_STEP_DESCRIPTION_CHARS = 500
"""Cap on a step description, with an explicit marker beyond it (sub-phase 1.5).

500 matches the other text bounds in the specs — SPEC-006 § 3.4 (log content) and
SPEC-004 § 3.2 (per-step output in a re-plan context summary) — so a description can
travel into a prompt, a log line and the execution report without any of them having
to truncate again. The cap protects the report and the re-plan prompt from a model
that dumps a document into ``description``.
"""

TRUNCATION_MARKER = "...[truncated]"
"""Marker appended to truncated text, matching SPEC-002 R5's convention."""

MAX_CONTEXT_SUMMARY_CHARS = 2000
"""Bound on the ``Current context:`` section of a planning prompt (plan § 2.3).

The whole section is counted, header included, so the user message can never grow by
more than this plus the two separator newlines.
"""

MAX_CONTEXT_VALUE_CHARS = 200
"""Bound on a single variable's rendered value inside the context summary.

Additive to the plan's 2000-char bound and deliberately much smaller: without it one
enormous value (a pasted document, a base64 blob) would consume the entire budget and
crowd out every other variable the model needs. 200 keeps at least a handful of
variables visible in the worst case.
"""

CONTEXT_SUMMARY_HEADER = "Current context:"
"""Header of the bounded context section appended to the planning user message.

The wording matches the ``Current context:`` line of the frozen § 3.2 re-plan prompt so
a model sees the same label in both calls. The § 3.1 system prompt is FROZEN, so the
summary can only ever be appended to the *user* message.
"""

MAX_REPLAN_STEP_OUTPUT_CHARS = 500
"""Per-step output bound inside a re-plan context summary (SPEC-004 § 3.2)."""

MAX_REPLAN_CONTEXT_CHARS = 4000
"""Total bound on the re-plan ``{context_summary}`` section (SPEC-004 § 3.2)."""

MAX_ATTEMPT_HISTORY_ENTRIES = 10
"""How many recorded attempts reach the re-plan prompt (additive bound).

SPEC-004 § 3.2 bounds the context summary but not ``{attempt_history}``, and an
unbounded history would grow with every recovery pass until the prompt, not the plan,
was the largest thing in the process. Ten entries cover the realistic cascade —
Level 1 retries (``max_retries`` defaults to 2), Level 2 fallbacks and earlier Level 3
re-plans — and the *newest* are kept, since they explain the current failure. Each
entry's error text is additionally bounded by :data:`MAX_RAW_PAYLOAD_CHARS`.
"""

MAX_JSON_EXTRACTION_ATTEMPTS = 8
"""How many balanced ``{…}`` candidates are tried when prose wraps the JSON.

A hostile payload could contain thousands of brace-delimited decoys; bounding the
attempts keeps parse time linear in the payload size (SKL-REL-FUZZ: malformed input
must not trigger unbounded work). Eight is enough for the observed real-world shape —
chatter, a fenced block, and at most a stray brace pair before the plan object.
"""


def _fail(
    models: ModelProvider,
    code: str,
    message: str,
    *,
    step_id: str | None = None,
    original_error: str | None = None,
) -> NoReturn:
    """Build a spec error and raise it, whatever the injected model provider returns.

    Args:
        models: The active model provider.
        code: A SPEC-001 § 3 error code.
        message: Human-readable failure detail, already bounded.
        step_id: Offending step id, when the failure is step-scoped.
        original_error: Underlying exception text, when there was one.

    Raises:
        AgentErrorRaised: Always — either the injected error object itself when it
            is raisable, or a wrapper carrying it (SCR-P3-7).
    """
    error = models.agent_error(
        code=code,
        message=message,
        component="planner",
        step_id=step_id,
        recoverable=False,
        original_error=original_error,
    )
    if isinstance(error, BaseException):
        raise error
    raise AgentErrorRaised(error)


def _bounded(text: str, limit: int = MAX_RAW_PAYLOAD_CHARS) -> str:
    """Truncate *text* to *limit* characters with an explicit marker."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...[truncated {len(text) - limit} chars]"


def _truncate(text: str, limit: int, marker: str = TRUNCATION_MARKER) -> str:
    """Truncate *text* to exactly *limit* characters, marker included.

    Args:
        text: The text to bound.
        limit: Maximum length of the result.
        marker: Suffix that makes the truncation explicit.

    Returns:
        *text* unchanged when it already fits, otherwise the leading
        ``limit - len(marker)`` characters followed by *marker*.
    """
    if len(text) <= limit:
        return text
    return text[: max(limit - len(marker), 0)] + marker


def _balanced_object_candidates(text: str, limit: int) -> list[str]:
    """Return up to *limit* balanced ``{…}`` substrings of *text*, outermost first.

    String literals and escapes are respected, so braces inside a JSON string do not
    affect the depth count. Each candidate starts at a later ``{`` than the previous
    one, which lets the caller skip a decoy object embedded in prose.

    Args:
        text: Raw model output.
        limit: Maximum number of candidates to produce (boundedness guard).

    Returns:
        Candidate substrings in order of their opening brace; empty when there is no
        ``{`` at all.
    """
    candidates: list[str] = []
    start = text.find("{")
    while start != -1 and len(candidates) < limit:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : index + 1])
                    break
        start = text.find("{", start + 1)
    return candidates


def strip_code_fences(text: str) -> str:
    """Remove a surrounding markdown code fence (SPEC-004 § 4.2 rule 1).

    Handles a bare ``` fence and a language-tagged one (``json``, ``JSON``), and
    leaves text without an opening fence untouched — including text that merely
    contains backticks inside a JSON string.

    Args:
        text: Raw model output.

    Returns:
        The payload text with any outer fence removed and surrounding whitespace
        trimmed.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    body = stripped.split("\n")[1:]
    # `stripped` has no trailing whitespace, so the last line is the closing fence
    # (possibly indented) when one is present at all.
    if body and body[-1].strip().startswith("```"):
        body.pop()
    return "\n".join(body).strip()


def _loads(text: str) -> tuple[object, str | None]:
    """Parse *text* as JSON, containing every decoder failure.

    Args:
        text: Candidate JSON text.

    Returns:
        ``(parsed, None)`` on success, or ``(None, reason)`` when decoding failed.
        ``RecursionError`` (hostile nesting depth) is contained here so it can never
        escape as an unspecified exception; byte payloads are decoded with ``"replace"``
        before they reach this function, so no ``UnicodeDecodeError`` is possible.
    """
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, str(exc)
    except RecursionError as exc:
        return None, f"payload nests too deeply to parse safely: {exc}"


def _first_json_object(
    text: str, required_key: str, limit: int
) -> Mapping[str, object] | None:
    """Return the first balanced JSON object in *text* that carries *required_key*.

    This is the prose-tolerance pass: models wrap JSON in chatter, fences or a stray
    brace pair. Requiring *required_key* matters — a truncated payload such as
    ``'{"steps": [{"description": "a"}'`` contains the balanced inner fragment
    ``'{"description": "a"}'``, and adopting it would silently fabricate an empty plan
    instead of reporting the parse failure. The same guard keeps
    :meth:`Planner.select_tool` from latching onto an unrelated object in a chatty
    reply.

    Args:
        text: Raw model output.
        required_key: The key that identifies the object being looked for.
        limit: Maximum number of candidates to try (boundedness guard).

    Returns:
        The first matching object, or ``None`` when there is none.
    """
    for candidate in _balanced_object_candidates(text, limit):
        parsed, _detail = _loads(candidate)
        if isinstance(parsed, Mapping) and required_key in parsed:
            return parsed
    return None


def _payload_mapping(models: ModelProvider, payload: object) -> Mapping[str, object]:
    """Coerce *payload* into the JSON object shape of SPEC-004 § 4.1.

    Args:
        models: The active model provider, used to build the error.
        payload: Raw model output (``str``, ``bytes`` or an already-parsed mapping).

    Returns:
        The parsed mapping.

    Raises:
        AgentErrorRaised: With code ``PLAN_PARSE_FAILED`` when the payload is not a
            JSON object — never a raw ``JSONDecodeError`` (plan § 1.5 exit criteria).
    """
    if isinstance(payload, Mapping):
        return payload
    if isinstance(payload, bytes | bytearray):
        payload = payload.decode("utf-8", "replace")
    if not isinstance(payload, str):
        return _fail(
            models,
            "PLAN_PARSE_FAILED",
            f"Plan payload must be a JSON string or object, "
            f"got {type(payload).__name__}",
        )
    text = strip_code_fences(payload)
    if not text:
        return _fail(models, "PLAN_PARSE_FAILED", "Plan payload is empty")
    parsed, decode_error = _loads(text)
    if decode_error is not None and parsed is None:
        # Prose around the JSON: look for the first balanced object that parses AND is a
        # plan object (see _first_json_object for why the key requirement matters).
        parsed = _first_json_object(text, "steps", MAX_JSON_EXTRACTION_ATTEMPTS)
    if parsed is None:
        return _fail(
            models,
            "PLAN_PARSE_FAILED",
            f"Plan payload is not valid JSON: {decode_error}. "
            f"Payload preview: {_bounded(text)}",
            original_error=decode_error,
        )
    if not isinstance(parsed, Mapping):
        return _fail(
            models,
            "PLAN_PARSE_FAILED",
            f"Plan payload must be a JSON object with a 'steps' array (§ 4.1), got "
            f"{type(parsed).__name__}. Payload preview: {_bounded(text)}",
        )
    return parsed


def _dependency_references(
    models: ModelProvider, value: object, step_id: str
) -> list[str]:
    """Normalize ``depends_on`` into canonical ``step_<i>`` ids (§ 4.2 rule 2).

    Accepts the three reference forms the spec names — ``0``, ``"0"`` and
    ``"step_0"`` — plus a bare string for a single dependency. Out-of-range and
    nonexistent references are *not* rejected here; validation check V4 owns that.

    Args:
        models: The active model provider, used to build the error.
        value: The raw ``depends_on`` value, or ``None`` when absent.
        step_id: Canonical id of the step being parsed, for error reporting.

    Returns:
        Normalized dependency ids in declared order.

    Raises:
        AgentErrorRaised: With code ``PLAN_PARSE_FAILED`` when the value or one of
            its entries has a type no reference form can express.
    """
    if value is None:
        return []
    entries: Sequence[object]
    if isinstance(value, str):
        entries = [value]
    elif isinstance(value, Sequence):
        entries = value
    else:
        return _fail(
            models,
            "PLAN_PARSE_FAILED",
            f"depends_on must be a list of step references, got {type(value).__name__}",
            step_id=step_id,
        )
    references: list[str] = []
    for entry in entries:
        if isinstance(entry, bool) or not isinstance(entry, int | str):
            return _fail(
                models,
                "PLAN_PARSE_FAILED",
                f"depends_on entries must be step indices or ids, "
                f"got {type(entry).__name__}",
                step_id=step_id,
            )
        if isinstance(entry, int):
            references.append(f"step_{entry}")
            continue
        text = entry.strip()
        references.append(f"step_{int(text)}" if text.isdigit() else text)
    return references


def _tool_names(
    models: ModelProvider, value: object, key: str, step_id: str
) -> list[str]:
    """Normalize a list of tool names (``fallback_tools``).

    Args:
        models: The active model provider, used to build the error.
        value: The raw value, or ``None`` when absent.
        key: Field name, for error reporting.
        step_id: Canonical id of the step being parsed.

    Returns:
        Tool names in declared order.

    Raises:
        AgentErrorRaised: With code ``PLAN_PARSE_FAILED`` on a non-sequence value or
            a non-string entry.
    """
    if value is None:
        return []
    entries: Sequence[object]
    if isinstance(value, str):
        entries = [value]
    elif isinstance(value, Sequence):
        entries = value
    else:
        return _fail(
            models,
            "PLAN_PARSE_FAILED",
            f"{key} must be a list of tool names, got {type(value).__name__}",
            step_id=step_id,
        )
    names: list[str] = []
    for entry in entries:
        if not isinstance(entry, str):
            return _fail(
                models,
                "PLAN_PARSE_FAILED",
                f"{key} entries must be tool names, got {type(entry).__name__}",
                step_id=step_id,
            )
        names.append(entry)
    return names


def _model_priority(models: ModelProvider, value: object) -> Any:
    """Map a raw ``priority`` value onto a ``TaskPriority`` member (§ 4.2 rule 3).

    Unknown values — including non-strings — default to HIGH rather than failing.

    Args:
        models: The active model provider.
        value: The raw ``priority`` value, or ``None`` when absent.

    Returns:
        The resolved priority member.
    """
    candidate = value.strip().upper() if isinstance(value, str) else ""
    try:
        return models.task_priority(candidate or "HIGH")
    except (KeyError, ValueError):
        # Providers look members up by name (KeyError) or by value (ValueError);
        # either way an unrecognized priority defaults to HIGH (§ 4.2 rule 3).
        return models.task_priority("HIGH")


def _cap_description(description: str) -> str:
    """Bound a step description to :data:`MAX_STEP_DESCRIPTION_CHARS`.

    A whitespace-only description is capped *without* the truncation marker: adding the
    marker would turn an empty description into non-empty text and let it past the V3
    check, so truncation must never manufacture content.

    Args:
        description: The raw description from the model.

    Returns:
        The description, at most :data:`MAX_STEP_DESCRIPTION_CHARS` characters long.
    """
    if len(description) <= MAX_STEP_DESCRIPTION_CHARS:
        return description
    if not description.strip():
        return description[:MAX_STEP_DESCRIPTION_CHARS]
    return _truncate(description, MAX_STEP_DESCRIPTION_CHARS)


def _parse_step(
    models: ModelProvider, config: ConfigLike, raw: object, index: int
) -> StepLike:
    """Normalize one raw step object into a spec-shaped step (§ 4.2 rules 2-4).

    Args:
        models: The active model provider.
        config: Injected configuration; supplies ``execution.max_retries``.
        raw: One entry of the payload's ``steps`` array.
        index: Position in the array, which fixes the canonical ``step_<index>`` id.

    Returns:
        The normalized step, with status PENDING and ``retries`` 0.

    Raises:
        AgentErrorRaised: With code ``PLAN_PARSE_FAILED`` when *raw* is not an
            object or a field has a type the spec cannot express.
    """
    step_id = f"step_{index}"
    if not isinstance(raw, Mapping):
        return _fail(
            models,
            "PLAN_PARSE_FAILED",
            f"Each step must be a JSON object, got {type(raw).__name__}",
            step_id=step_id,
        )
    description = raw.get("description", "")
    if not isinstance(description, str):
        return _fail(
            models,
            "PLAN_PARSE_FAILED",
            f"description must be a string, got {type(description).__name__}",
            step_id=step_id,
        )
    # Bound the description so a model that dumps a document into it cannot inflate
    # the prompt, the log line or the execution report (see MAX_STEP_DESCRIPTION_CHARS).
    description = _cap_description(description)
    tool_hint = raw.get("tool_hint", "")
    if not isinstance(tool_hint, str):
        return _fail(
            models,
            "PLAN_PARSE_FAILED",
            f"tool_hint must be a string, got {type(tool_hint).__name__}",
            step_id=step_id,
        )
    raw_input = raw.get("input_data", {})
    if raw_input is None:
        raw_input = {}
    if not isinstance(raw_input, Mapping):
        return _fail(
            models,
            "PLAN_PARSE_FAILED",
            f"input_data must be a JSON object, got {type(raw_input).__name__}",
            step_id=step_id,
        )
    # Canonical ids are assigned in array order *before* dependencies are resolved
    # (§ 4.2 rule 2), and unknown keys — including a model-chosen "id", "status",
    # "retries" or "max_retries" — are ignored (§ 4.2 rules 3-4).
    return models.step(
        id=step_id,
        description=description,
        tool_hint=tool_hint,
        tool_name="",
        input_data=dict(raw_input),
        output_data=None,
        status=models.step_status("PENDING"),
        error=None,
        retries=0,
        max_retries=int(config.execution.max_retries),
        fallback_tools=_tool_names(
            models, raw.get("fallback_tools"), "fallback_tools", step_id
        ),
        depends_on=_dependency_references(models, raw.get("depends_on"), step_id),
        priority=_model_priority(models, raw.get("priority")),
        started_at=None,
        completed_at=None,
    )


def parse_plan(
    payload: object,
    config: ConfigLike,
    *,
    original_prompt: str = "",
    models: ModelProvider | None = None,
    now: datetime | None = None,
) -> PlanLike:
    """Parse raw model output into an ``ExecutionPlan`` (SPEC-004 § 4.2).

    Applies the four normalization rules in order: strip code fences and parse
    JSON; assign canonical ``step_0 … step_n`` ids in array order before resolving
    ``depends_on`` (integer, numeric-string and ``step_<i>`` references all
    normalize); default unknown enum values and ignore unknown keys; take each
    step's ``max_retries`` from ``config.execution.max_retries``.

    Validation (V1-V7) is deliberately **not** performed here — see
    :func:`validate_plan` — so a structurally parseable but invalid plan reaches
    validation and reports the precise ``PLAN_VALIDATION_FAILED`` condition.

    Args:
        payload: Raw model output: a JSON string (fenced or not), bytes, or an
            already-parsed mapping.
        config: Injected configuration (SPEC-006 § 1).
        original_prompt: The user prompt this plan answers.
        models: Model provider; defaults to :class:`SpecModels`.
        now: Timestamp for ``created_at``; defaults to the current time. Inject it
            in tests for determinism (SPEC-000 § 5.5).

    Returns:
        A pending plan whose steps carry canonical ids.

    Raises:
        AgentErrorRaised: With code ``PLAN_PARSE_FAILED`` when the payload is not a
            JSON object or a field type is not expressible in the § 4.1 schema.
    """
    provider = models if models is not None else SpecModels()
    data = _payload_mapping(provider, payload)
    raw_steps = data.get("steps")
    steps: list[StepLike] = []
    if isinstance(raw_steps, Sequence) and not isinstance(raw_steps, str | bytes):
        steps = [
            _parse_step(provider, config, raw, index)
            for index, raw in enumerate(raw_steps)
        ]
    # A missing, non-list or empty `steps` is validation check V1's business
    # (SPEC-004 § 4.3), not a parse error: parsing yields zero steps and validation
    # raises PLAN_VALIDATION_FAILED with the precise condition.
    return provider.plan(
        original_prompt=original_prompt,
        steps=steps,
        context={},
        created_at=now if now is not None else datetime.now(),
        status=provider.step_status("PENDING"),
        final_output=None,
    )


# ══════════════════════════════════════════════════════════════════════════════
# C. Plan validation, checks V1-V7 (SPEC-004 § 4.3)
# ══════════════════════════════════════════════════════════════════════════════


def _tool_names_of(available_tools: Sequence[object] | None) -> set[str]:
    """Collect the registered tool names from ``ToolRegistry.list_tools()`` output.

    Accepts mappings (SPEC-002 § 2) and tool objects exposing ``name``
    (SPEC-002 § 1); anything else is ignored rather than raising.

    Args:
        available_tools: The tool descriptors the planner was given, or ``None``.

    Returns:
        The set of non-empty tool names.
    """
    names: set[str] = set()
    for tool in available_tools or ():
        raw = (
            tool.get("name", "")
            if isinstance(tool, Mapping)
            else getattr(tool, "name", "")
        )
        if isinstance(raw, str) and raw:
            names.add(raw)
    return names


def validate_plan(
    plan: PlanLike,
    config: ConfigLike,
    *,
    available_tools: Sequence[object] | None = None,
    logger: LoggerLike | None = None,
    models: ModelProvider | None = None,
) -> list[str]:
    """Validate a parsed plan against SPEC-004 § 4.3 checks V1-V7.

    Checks run in the order V1, V2, V3, V4, V6, V5, V7. V6 is deliberately tested
    before V5 because a self-dependency is a specific cycle and deserves the precise
    message; both map to the same error code. All of V1-V6 raise; V7 returns a
    warning instead, per § 4.3 ("produces a WARNING (not a failure)").

    On success ``plan.context["unresolved_hints"]`` records every ``tool_hint`` that
    matches no name in *available_tools* (§ 4.3 note). An unknown hint is **not** a
    validation failure: the orchestrator resolves or re-selects it at runtime
    (SPEC-003 § 3 step 2). That key is the only context write this function performs.

    Args:
        plan: The parsed plan to validate.
        config: Injected configuration; supplies ``execution.max_steps``.
        available_tools: ``ToolRegistry.list_tools()`` output. When ``None`` the
            unresolved-hint record stays empty rather than flagging every hint.
        logger: Injected logger; a failure emits the catalog event
            ``plan_validation_failed`` (SPEC-006 § 6.1) before raising.
        models: Model provider used to build the error object.

    Returns:
        Warnings that do not fail validation (V7 only); empty when none apply. The
        caller emits ``plan_generated`` — at WARNING level when this list is
        non-empty — so the event is never duplicated (SPEC-006 § 6.1).

    Raises:
        AgentErrorRaised: With code ``PLAN_VALIDATION_FAILED`` for V1-V6.
    """
    provider = models if models is not None else SpecModels()
    log = logger if logger is not None else NullLogger()
    steps = list(plan.steps)

    def fail(message: str, *, step_id: str | None = None) -> NoReturn:
        """Log the catalog event and raise the spec error (SPEC-006 § 6.1)."""
        log.error(
            "planner",
            "plan_validation_failed",
            plan_id=plan.id,
            step_id=step_id,
            detail=message,
        )
        _fail(provider, "PLAN_VALIDATION_FAILED", message, step_id=step_id)

    # V1 — steps missing, not a list, or empty.
    if not steps:
        fail(
            "Execution plan has no steps: 'steps' must be a non-empty array "
            "(SPEC-004 § 4.3 V1)"
        )
    # V2 — more steps than the configured maximum.
    max_steps = int(config.execution.max_steps)
    if len(steps) > max_steps:
        fail(
            f"Execution plan has {len(steps)} steps, exceeding "
            f"execution.max_steps={max_steps} (SPEC-004 § 4.3 V2)"
        )
    # V3 — every step needs a non-empty description.
    for step in steps:
        if not step.description.strip():
            fail(
                f"Step {step.id} has no description (SPEC-004 § 4.3 V3)",
                step_id=step.id,
            )
    # V4 — dependencies must reference steps that exist in this plan.
    known_ids = {step.id for step in steps}
    for step in steps:
        for dependency in step.depends_on:
            if dependency not in known_ids:
                fail(
                    f"Step {step.id} depends on unknown step '{dependency}' "
                    f"(SPEC-004 § 4.3 V4)",
                    step_id=step.id,
                )
    # V6 — before V5, so a self-dependency reports precisely rather than as a cycle.
    for step in steps:
        if step.id in step.depends_on:
            fail(
                f"Step {step.id} has a self-dependency (SPEC-004 § 4.3 V6)",
                step_id=step.id,
            )
    # V5 — cycle detection through the shared sorter (SPEC-003 § 8), whose
    # ValueError message is frozen and is surfaced verbatim in the failure detail.
    # Deferred import: `agent_harness.orchestration.dependency` imports the shared
    # contract kit from this module (SPEC-000 § 3.3 gives this plan no separate
    # contracts module), so importing it here at module level would be circular.
    from agent_harness.orchestration.dependency import resolve_execution_order

    try:
        resolve_execution_order(steps, logger=log)
    except ValueError as exc:
        fail(f"{exc} (SPEC-004 § 4.3 V5)")
    # V7 — zero CRITICAL steps warns but never fails.
    warnings: list[str] = []
    if not any(priority_value(step.priority) == "critical" for step in steps):
        warnings.append(
            "Plan has no step with priority 'critical'; nothing is marked as "
            "producing the final deliverable (SPEC-004 § 4.3 V7)"
        )
    hints: list[str] = []
    if available_tools is not None:
        registered = _tool_names_of(available_tools)
        for step in steps:
            hint = step.tool_hint
            if hint and hint not in registered and hint not in hints:
                hints.append(hint)
    plan.context["unresolved_hints"] = hints
    return warnings


# ══════════════════════════════════════════════════════════════════════════════
# D. The Planner (SPEC-004 § 2 FROZEN interface, § 3 prompts, § 5 controls)
# ══════════════════════════════════════════════════════════════════════════════


def _context_variables(context: Mapping[str, Any] | None) -> dict[str, Any]:
    """Extract the caller's ``variables`` mapping, or an empty dict.

    Only ``variables`` is read: ``step_results`` and ``files_created`` belong to the
    runtime context the orchestrator owns (SPEC-003 § 4.1), and a plan that has not
    executed yet must not claim them. A non-mapping ``variables`` value is ignored
    rather than raising — the caller's context is input, not a contract.

    Args:
        context: The optional seed context passed to :meth:`Planner.plan`.

    Returns:
        A shallow copy of the variables, empty when there are none.
    """
    if not isinstance(context, Mapping):
        return {}
    variables = context.get("variables")
    if not isinstance(variables, Mapping):
        return {}
    return dict(variables)


def _render_value(value: object, limit: int) -> str:
    """Render one untrusted value as bounded, deterministic text.

    Args:
        value: Any value read from model output or from the runtime context.
        limit: Maximum length of the result, marker included.

    Returns:
        The value itself when it is a string (it reads better unquoted), otherwise its
        JSON form with sorted keys and ``ensure_ascii=False`` so unicode survives
        verbatim. Values JSON cannot represent — a circular reference, a dict with
        unsortable mixed keys — fall back to ``repr``; a ``__repr__`` that raises is
        left to surface, because the planner never guesses.
    """
    if isinstance(value, str):
        rendered = value
    else:
        try:
            rendered = json.dumps(
                value, ensure_ascii=False, sort_keys=True, default=repr
            )
        except (TypeError, ValueError):
            rendered = repr(value)
    return _truncate(rendered, limit)


def _render_context_summary(variables: Mapping[str, Any]) -> str:
    """Render the bounded ``Current context:`` prompt section (plan § 2.3).

    Variables are listed in sorted key order so the same variables always produce a
    byte-identical prompt, however the caller built the dict — the determinism
    rationale of SPEC-002 G3. Truncation happens on line boundaries, never mid-value:
    a half-written path or secret in a prompt is worse than an omitted one, and the
    :data:`TRUNCATION_MARKER` says plainly that something was dropped.

    Args:
        variables: The caller's variables; empty means no section at all.

    Returns:
        The section text including its header, at most
        :data:`MAX_CONTEXT_SUMMARY_CHARS` characters; ``""`` when there is nothing to
        summarize.
    """
    if not variables:
        return ""
    budget = MAX_CONTEXT_SUMMARY_CHARS - len(CONTEXT_SUMMARY_HEADER) - 1
    lines: list[str] = []
    used = 0
    dropped = False
    for key in sorted(variables, key=str):
        line = f"- {key}: {_render_value(variables[key], MAX_CONTEXT_VALUE_CHARS)}"
        cost = len(line) + (1 if lines else 0)
        if used + cost > budget:
            dropped = True
            continue
        lines.append(line)
        used += cost
    if dropped:
        while lines and used + 1 + len(TRUNCATION_MARKER) > budget:
            used -= len(lines.pop()) + (1 if lines else 0)
        lines.append(TRUNCATION_MARKER)
    return "\n".join([CONTEXT_SUMMARY_HEADER, *lines])


def _substitute(template: str, values: Mapping[str, str]) -> str:
    """Replace every ``{key}`` of *template* in a single left-to-right pass.

    ``str.replace`` chained over the six placeholders of the frozen § 3.2 re-plan
    prompt would rescan earlier values, so a step description containing the literal
    text ``{context_summary}`` could hijack a later placeholder. ``str.format`` is not
    usable either: the frozen templates carry no doubled braces, and a description with
    a stray ``{`` would raise. Values are therefore inserted verbatim and never
    rescanned, and an unknown or malformed brace sequence is left literal.

    Args:
        template: Text containing ``{key}`` placeholders.
        values: Replacement text per key.

    Returns:
        The substituted template.
    """
    pieces: list[str] = []
    rest = template
    while rest:
        open_brace = rest.find("{")
        if open_brace == -1:
            pieces.append(rest)
            break
        close_brace = rest.find("}", open_brace)
        if close_brace == -1:
            pieces.append(rest)
            break
        key = rest[open_brace + 1 : close_brace]
        if key in values:
            pieces.append(rest[:open_brace])
            pieces.append(values[key])
        else:
            pieces.append(rest[: close_brace + 1])
        rest = rest[close_brace + 1 :]
    return "".join(pieces)


def _replacement_payloads(payload: object) -> list[object]:
    """Extract the step objects from a re-plan reply.

    Args:
        payload: Whatever ``complete_json`` parsed, of unknown shape.

    Returns:
        The raw step payloads, empty when the reply offers no alternative. Three shapes
        are accepted because § 3.2 asks for "an alternative step (or sequence of
        steps)" without fixing the envelope: the § 4.1 ``{"steps": [...]}`` object, a
        lone step object, and a bare array.
    """
    if isinstance(payload, Mapping):
        steps = payload.get("steps")
        if isinstance(steps, Sequence) and not isinstance(steps, (str, bytes)):
            return list(steps)
        if "description" in payload or "tool_hint" in payload:
            return [payload]
        return []
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return list(payload)
    return []


def _index_references(payload: object) -> set[str]:
    """Return the canonical ids a step payload referenced by bare *index*.

    :func:`parse_plan` canonicalizes ``0``, ``"0"`` and ``"step_0"`` all to
    ``"step_0"``, which is right for a plan and wrong for a replacement list: there an
    index means "the nth new step" while ``"step_N"`` names an original step. This
    recovers the distinction from the raw payload.

    Args:
        payload: One raw step payload from the re-plan reply.

    Returns:
        Canonical ids (``"step_<i>"``) that were written as indexes; empty when the
        payload is not a mapping or declares no dependencies.
    """
    if not isinstance(payload, Mapping):
        return set()
    raw = payload.get("depends_on")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return set()
    indexed: set[str] = set()
    for reference in raw:
        if isinstance(reference, bool):
            continue  # bool is an int in Python; reading True as index 1 is a guess
        if isinstance(reference, int):
            indexed.add(f"step_{reference}")
        elif isinstance(reference, str) and reference.strip().isdigit():
            # Mirrors § 4.2 rule 2 exactly: parse_plan canonicalizes a digit string and
            # nothing else, so "-1" stays a literal reference there and must not become
            # an index here.
            indexed.add(f"step_{int(reference.strip())}")
    return indexed


def _attempt_history(step: StepLike, context: Mapping[str, Any]) -> str:
    """Render the ``{attempt_history}`` section of the § 3.2 prompt.

    Built from ``context["errors"]`` (SPEC-003 § 4.1), which the recovery cascade
    appends to on every attempt, and scoped to *this* step: another step's failures are
    noise that could push the model toward an unrelated approach. Malformed entries are
    skipped rather than raising — the context is input, not a contract.

    Args:
        step: The failed step; its id selects the entries and its retry count is the
            fallback when nothing was recorded.
        context: The runtime context, read only.

    Returns:
        At most :data:`MAX_ATTEMPT_HISTORY_ENTRIES` newest attempts, one per line.
    """
    entries = context.get("errors")
    lines: list[str] = []
    if isinstance(entries, Sequence) and not isinstance(entries, (str, bytes)):
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            if str(entry.get("step_id", "")) != step.id:
                continue
            error = _truncate(str(entry.get("error", "")), MAX_RAW_PAYLOAD_CHARS)
            lines.append(
                f"- attempt {entry.get('attempt', '?')} "
                f"(level {entry.get('level', '?')}, "
                f"recovered={entry.get('recovered', False)}): {error}"
            )
    if not lines:
        return f"(no previous attempts recorded; retries used: {step.retries})"
    return "\n".join(lines[-MAX_ATTEMPT_HISTORY_ENTRIES:])


def _summarize_step_result(step_id: object, result: object) -> str:
    """Render one ``context["step_results"]`` entry as a single bounded line.

    Args:
        step_id: The entry's key.
        result: The § 4.1 result mapping, or any other value a caller stored.

    Returns:
        ``- <id> (<status>); output: …; error: …`` with each field bounded to
        :data:`MAX_REPLAN_STEP_OUTPUT_CHARS`.
    """
    if not isinstance(result, Mapping):
        return f"- {step_id}: {_render_value(result, MAX_REPLAN_STEP_OUTPUT_CHARS)}"
    parts = [f"- {step_id} ({result.get('status', '?')})"]
    output = result.get("output")
    if output is not None:
        parts.append(f"output: {_render_value(output, MAX_REPLAN_STEP_OUTPUT_CHARS)}")
    error = result.get("error")
    if error:
        parts.append(f"error: {_truncate(str(error), MAX_REPLAN_STEP_OUTPUT_CHARS)}")
    return "; ".join(parts)


def _replan_context_summary(context: Mapping[str, Any]) -> str:
    """Render the bounded ``{context_summary}`` of the § 3.2 prompt.

    Bounds are the frozen ones: each step output is truncated to
    :data:`MAX_REPLAN_STEP_OUTPUT_CHARS` and the whole section to
    :data:`MAX_REPLAN_CONTEXT_CHARS`. Including the caller's ``variables`` alongside the
    step outputs is additive *within* that bound — § 3.2 fixes the size of the summary,
    and a re-plan that cannot see the user's ``data_file`` cannot propose a working
    alternative.

    Entries are kept in order and the section is cut at the first entry that does not
    fit, so what the model sees is a contiguous prefix of the run so far rather than a
    scattered sample; :data:`TRUNCATION_MARKER` says plainly that the rest was dropped.

    Args:
        context: The runtime context (SPEC-003 § 4.1), read only.

    Returns:
        The summary text, or ``"(none)"`` when the context carries nothing to summarize.
    """
    lines: list[str] = []
    variables = context.get("variables")
    if isinstance(variables, Mapping):
        for key in sorted(variables, key=str):
            lines.append(
                f"- var {key}: {_render_value(variables[key], MAX_CONTEXT_VALUE_CHARS)}"
            )
    step_results = context.get("step_results")
    if isinstance(step_results, Mapping):
        for step_id, result in step_results.items():
            lines.append(_summarize_step_result(step_id, result))
    if not lines:
        return "(none)"
    budget = MAX_REPLAN_CONTEXT_CHARS - len(TRUNCATION_MARKER) - 1
    kept: list[str] = []
    used = 0
    for line in lines:
        cost = len(line) + (1 if kept else 0)
        if used + cost > budget:
            kept.append(TRUNCATION_MARKER)
            break
        kept.append(line)
        used += cost
    return "\n".join(kept)


def _input_keys_summary(input_data: object) -> str:
    """Render a step's ``input_data`` as its sorted key list for the § 3.3 prompt.

    Only the *keys* are sent, never the values: a step's input can contain file
    contents or credentials the selection decision does not need, and SPEC-006 § 3.4
    keeps such text out of anything that leaves the process.

    Args:
        input_data: The step's input mapping; anything else renders as no keys.

    Returns:
        A comma-separated sorted key list, or ``"(none)"`` when there are no keys.
    """
    if not isinstance(input_data, Mapping) or not input_data:
        return "(none)"
    return ", ".join(sorted((str(key) for key in input_data), key=str))


def _selected_tool_name(value: object, available_tools: Sequence[object]) -> str | None:
    """Validate a model's selection against the registered tool names.

    Args:
        value: The ``"tool"`` member of the reply, of unknown type.
        available_tools: ``ToolRegistry.list_tools()`` output.

    Returns:
        The name when it is a string that exactly matches a registered tool; ``None``
        otherwise. Matching is exact — no case folding, no fuzzy repair — because a
        hallucinated name must reach the orchestrator as "no tool" (SPEC-003 § 3 step 2
        then fails the step with ``TOOL_NOT_FOUND``) rather than being guessed into a
        tool that was never offered.
    """
    if not isinstance(value, str):
        return None
    name = value.strip()
    return name if name in _tool_names_of(available_tools) else None


class Planner:
    """LLM task decomposition — the frozen interface of SPEC-004 § 2.

    ``plan()`` composes the § 3.1 system prompt with the rendered tool list, makes a
    single ``complete_json`` round, then normalizes and validates the reply so an
    invalid plan can never be returned (§ 2). ``select_tool()`` (sub-phase 2.4) and
    ``replan_step()`` (sub-phase 2.5) complete the interface.

    The planner holds no registry, executes no tool and never mutates the context it is
    given (§ 5, SPEC-000 § 2): tools arrive as the ``list_tools()`` payload the caller
    already has.
    """

    def __init__(
        self,
        llm_client: LLMClientLike,
        config: ConfigLike,
        *,
        logger: LoggerLike | None = None,
        models: ModelProvider | None = None,
    ) -> None:
        """Store the injected collaborators.

        Args:
            llm_client: Any SPEC-004 § 1 client (Plan 1's, or a test double).
            config: Injected configuration; supplies ``llm.temperature`` and the
                ``execution`` limits the validator reads.
            logger: Injected logger; defaults to :class:`NullLogger` because SPEC-006
                § 6.2 forbids module-level logger singletons.
            models: Provider of the SPEC-001 § 2 data-model classes. Defaults to
                :class:`SpecModels`; Plan 4's composition root injects Plan 1's
                (SCR-P3-6).
        """
        self.llm_client = llm_client
        self.config = config
        self.logger: LoggerLike = logger if logger is not None else NullLogger()
        self._models: ModelProvider = models if models is not None else SpecModels()

    def plan(
        self,
        prompt: str,
        available_tools: Sequence[object],
        *,
        context: Mapping[str, Any] | None = None,
    ) -> PlanLike:
        """Decompose *prompt* into a validated execution plan (SPEC-004 § 2).

        Exactly one ``complete_json`` round is made: the repair round of rule C3 lives
        inside the client, so a planner-side retry would break the § 5 budget.

        Args:
            prompt: The user request to decompose.
            available_tools: ``ToolRegistry.list_tools()`` output (SPEC-002 § 2). Typed
                as a read-only sequence so tool *objects* are accepted as well as dicts;
                § 2 writes ``list[dict]`` and a list satisfies this. Never mutated.
            context: Optional seed context, never mutated (§ 5). Its ``variables``
                mapping is deep-copied into ``plan.context["variables"]`` and, when
                non-empty, summarized in the user message within
                :data:`MAX_CONTEXT_SUMMARY_CHARS`. Other keys (``step_results``,
                ``files_created``) belong to the orchestrator's runtime context
                (SPEC-003 § 4.1) and are ignored.

        Returns:
            A plan whose steps carry canonical ``step_i`` ids and whose ``tool_hint``
            values have been checked against *available_tools* — unknown hints are
            recorded in ``plan.context["unresolved_hints"]``, not rejected (§ 4.3).

        Raises:
            AgentErrorRaised: ``PLAN_PARSE_FAILED`` when the reply is not a plan object
                (including a client error after its repair round), or
                ``PLAN_VALIDATION_FAILED`` for checks V1-V6. Never both, never neither:
                a returned plan is always valid.
        """
        variables = _context_variables(context)
        parsed, _response = self.llm_client.complete_json(
            self._planning_messages(prompt, available_tools, variables),
            schema_hint=PLAN_SCHEMA_HINT,
            temperature=self.config.llm.temperature,
        )
        plan = parse_plan(
            parsed, self.config, original_prompt=prompt, models=self._models
        )
        if variables:
            # Deep copy: the orchestrator mutates plan.context during execution, and
            # § 5 forbids the planner from mutating what it was given — either way the
            # two dicts must not share nested objects.
            plan.context["variables"] = copy.deepcopy(variables)
        warnings = validate_plan(
            plan,
            self.config,
            available_tools=available_tools,
            logger=self.logger,
            models=self._models,
        )
        self._emit_plan_generated(plan, warnings)
        return plan

    def select_tool(
        self, step: StepLike, available_tools: Sequence[object]
    ) -> str | None:
        """Pick the one registered tool that can perform *step* (SPEC-004 § 2, § 3.3).

        Called by the orchestrator when a ``tool_hint`` resolves to nothing
        (SPEC-003 § 3 step 2). Per § 5 this is a single round at temperature 0.0 with
        **no repair round** — which is why it calls ``complete`` rather than
        ``complete_json``: rule C3 puts the repair round inside ``complete_json``, so
        using it would spend a round the budget does not allow. The reply is therefore
        parsed here.

        Args:
            step: The step needing a tool. Never mutated — writing ``step.tool_name``
                is the orchestrator's job (SPEC-003 § 3 step 2).
            available_tools: ``ToolRegistry.list_tools()`` output; the only whitelist.

        Returns:
            A registered tool name, or ``None`` when the model declines, names a tool
            that is not registered, or returns anything other than the documented
            ``{"tool": name|null}`` shape. A provider failure also returns ``None``:
            SPEC-003 § 3 step 2 branches only on ``None``, so raising here would leave
            the frozen step loop with no defined path — and the client still emits its
            own ``llm_call`` event (SPEC-006 § 6.1), so the failure stays in the log
            stream. Unexpected non-``AgentError`` exceptions are never swallowed.
        """
        try:
            response = self.llm_client.complete(
                self._selection_messages(step, available_tools), temperature=0.0
            )
        except AgentErrorRaised:
            return None
        text = response.text
        parsed, _detail = _loads(strip_code_fences(text))
        if not isinstance(parsed, Mapping) or "tool" not in parsed:
            parsed = _first_json_object(text, "tool", MAX_JSON_EXTRACTION_ATTEMPTS)
        if not isinstance(parsed, Mapping):
            return None
        return _selected_tool_name(parsed.get("tool"), available_tools)

    def replan_step(
        self,
        step: StepLike,
        error: str,
        context: Mapping[str, Any],
        available_tools: Sequence[object] | None = None,
    ) -> list[StepLike]:
        """Propose replacement steps for a step that exhausted Levels 1-2 (§ 2, § 3.2).

        This is recovery Level 3 (SPEC-003 § 5): the caller executes the returned steps
        immediately, in order, and the first success recovers the original step.

        One ``complete_json`` round is spent — the repair round of rule C3 lives inside
        the client, which is exactly the § 5 budget for a re-plan ("≤ 1 round + 1
        repair"). Unlike :meth:`plan`, this method never raises for a bad reply: an
        unusable alternative is reported as ``[]`` so the cascade can escalate to
        Level 4 with the failed step's priority intact.

        Args:
            step: The failed step. Read only — its status, retries and error belong to
                the orchestrator and the recovery manager.
            error: The failure text to quote in the prompt.
            context: The runtime context (SPEC-003 § 4.1), read only. Supplies the
                attempt history and the bounded context summary.
            available_tools: ``ToolRegistry.list_tools()`` output; ``None`` renders as
                ``(none)``, and the model is then expected to decline.

        Returns:
            Replacement steps with fresh ids ``<failed_id>r<n>``, the failed step's
            priority inherited, and internal dependencies remapped to those new ids.
            ``[]`` when the model cannot propose an alternative.
        """
        try:
            parsed, _response = self.llm_client.complete_json(
                self._replan_messages(step, error, context, available_tools),
                schema_hint=PLAN_SCHEMA_HINT,
                temperature=self.config.llm.temperature,
            )
        except AgentErrorRaised:
            # Level 3 declines; SPEC-003 § 5 escalates to Level 4. The client's own
            # `llm_call` event still records why (SPEC-006 § 6.1).
            return []
        payloads = _replacement_payloads(parsed)
        if not payloads:
            return []
        try:
            parsed_plan = parse_plan(
                {"steps": payloads}, self.config, models=self._models
            )
        except AgentErrorRaised:
            return []
        return self._renumber_replacements(list(parsed_plan.steps), payloads, step)

    def _renumber_replacements(
        self,
        steps: list[StepLike],
        payloads: Sequence[object],
        failed_step: StepLike,
    ) -> list[StepLike]:
        """Give replacement steps their final ids, priority and dependencies.

        ``parse_plan`` assigns canonical ``step_i`` ids relative to the *replacement*
        list, which would collide with the ids of the plan being repaired, so every id
        becomes ``<failed_id>r<n>``. Three rules follow from SPEC-003 § 5:

        * Priority is inherited from the failed step, not taken from the model —
          Level 4's escalation decision reads the priority, so a model that answered
          "low" for a critical deliverable must not be able to dodge
          ``abort_on_critical_failure``.
        * A dependency written as a bare *index* (``0``, ``"1"``) is remapped to the new
          id of that replacement, because § 3.1 taught the model that an index refers to
          a position in the list it was just given.
        * A dependency written as ``"step_N"`` names an ORIGINAL plan step and is kept
          verbatim — a replacement may legitimately need the output of a step that
          already succeeded. The replacement list is not the plan, so the two
          conventions must not be conflated.
        * A dependency on the failed step itself is dropped: that step is the one being
          replaced, so the dependency could never be satisfied.

        Args:
            steps: The parsed replacement steps, mutated in place (they were created by
                :func:`parse_plan` for this call and are shared with nothing).
            payloads: The raw step payloads, index-aligned with *steps*; consulted to
                tell an index reference from a ``step_N`` reference, a distinction
                :func:`parse_plan` erases when it canonicalizes both.
            failed_step: The step being replaced.

        Returns:
            The replacements with a non-empty description, in the order the model gave
            them. A description-less step cannot be reported, resolved or re-planned
            again, so it is dropped; when nothing remains the caller returns ``[]``.
        """
        # parse_plan yields exactly one step per payload and raises rather than
        # dropping, so the two sequences are index-aligned; strict=True turns a broken
        # invariant into a loud failure instead of a silent dependency misalignment.
        pairs = list(zip(steps, payloads, strict=True))
        usable = [(step, raw) for step, raw in pairs if step.description.strip()]
        new_ids = {
            step.id: f"{failed_step.id}r{index}"
            for index, (step, _) in enumerate(usable, start=1)
        }
        result: list[StepLike] = []
        for step, raw in usable:
            indexed = _index_references(raw)
            remapped: list[str] = []
            for dependency in step.depends_on:
                if dependency == failed_step.id:
                    continue  # the step being replaced: never satisfiable
                if dependency in indexed:
                    # Written as an index, so it names a replacement. An out-of-range
                    # index has no replacement to map to and is kept as written rather
                    # than silently dropped.
                    remapped.append(new_ids.get(dependency, dependency))
                else:
                    remapped.append(dependency)  # an original plan step id
            step.depends_on = remapped
            step.id = new_ids[step.id]
            step.priority = failed_step.priority
            result.append(step)
        return result

    def _replan_messages(
        self,
        step: StepLike,
        error: str,
        context: Mapping[str, Any],
        available_tools: Sequence[object] | None,
    ) -> list[dict[str, Any]]:
        """Build the frozen § 3.2 re-plan prompt as a single user turn.

        Single turn for the same reason as :meth:`_selection_messages`: the template
        already carries the step, the error, the history, the tools and the context, and
        a lone system message would break providers whose message list must open with a
        user turn.

        Args:
            step: Supplies the description and the tool that was used.
            error: The failure text, bounded before it reaches the prompt.
            context: Supplies the attempt history and the context summary.
            available_tools: Rendered into ``{tool_descriptions}``.

        Returns:
            A one-message list in the § 1.1 shape.
        """
        tool_descriptions = render_tool_descriptions(available_tools)
        content = _substitute(
            REPLAN_PROMPT,
            {
                "step_description": step.description,
                "tool_name": step.tool_name or step.tool_hint,
                "error_message": _truncate(str(error), MAX_RAW_PAYLOAD_CHARS),
                "attempt_history": _attempt_history(step, context),
                "tool_descriptions": tool_descriptions or "(none)",
                "context_summary": _replan_context_summary(context),
            },
        )
        return [{"role": "user", "content": content}]

    def _selection_messages(
        self, step: StepLike, available_tools: Sequence[object]
    ) -> list[dict[str, Any]]:
        """Build the § 3.3 selection prompt as a single user turn.

        The additive template is self-contained — it names the step, its input keys and
        the tools — so a second message would only duplicate it. A lone *system*
        message is avoided deliberately: providers whose message list must open with a
        user turn (Anthropic, SPEC-004 § 1.3) would reject it.

        ``str.format`` is required here rather than ``str.replace``: the template
        doubles the braces of its JSON examples so that formatting emits real ones.

        Args:
            step: Supplies the description and the input key names.
            available_tools: Rendered into the ``{tool_descriptions}`` placeholder.

        Returns:
            A one-message list in the § 1.1 shape.
        """
        content = TOOL_SELECTION_PROMPT.format(
            step_description=step.description,
            input_keys=_input_keys_summary(step.input_data),
            tool_descriptions=render_tool_descriptions(available_tools),
        )
        return [{"role": "user", "content": content}]

    def _planning_messages(
        self,
        prompt: str,
        available_tools: Sequence[object],
        variables: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Build the § 1.1 message list: the frozen system prompt, then the request.

        Args:
            prompt: The user request.
            available_tools: Rendered into the ``{tool_descriptions}`` placeholder.
            variables: Caller-supplied context variables; when non-empty a bounded
                summary is appended to the *user* message. The § 3.1 system prompt is
                frozen, so it can never carry the summary.

        Returns:
            ``[{"role": "system", …}, {"role": "user", …}]`` — the only two keys the
            § 1.1 message format defines.
        """
        system = PLANNING_SYSTEM_PROMPT.replace(
            "{tool_descriptions}", render_tool_descriptions(available_tools)
        )
        user = prompt
        summary = _render_context_summary(variables or {})
        if summary:
            user = f"{prompt}\n\n{summary}"
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def _emit_plan_generated(self, plan: PlanLike, warnings: list[str]) -> None:
        """Emit the ``plan_generated`` catalog event (SPEC-006 § 6.1).

        Emitted once, after successful validation, with the step count and the
        unresolved hints the event is required to carry. A V7 warning promotes the same
        event to WARNING level instead of adding a second record, which is the contract
        :func:`validate_plan` documents for its return value.

        Args:
            plan: The validated plan.
            warnings: Warnings returned by :func:`validate_plan` (V7 only).
        """
        fields: dict[str, Any] = {
            "plan_id": plan.id,
            "steps": len(plan.steps),
            "unresolved_hints": list(plan.context.get("unresolved_hints", [])),
        }
        if warnings:
            self.logger.warning(
                "planner", "plan_generated", warning=warnings[0], **fields
            )
        else:
            self.logger.info("planner", "plan_generated", **fields)
