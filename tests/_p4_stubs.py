"""Spec-shaped stubs for Plan 4's parallel-execution phase.

Plan 4 (L3 Surface) composes the modules owned by Plans 1-3 (L0-L2). Those modules do
not exist on disk during parallel execution, so this file provides **spec-shaped**
stand-ins and a mechanism for installing them under their *real* dotted names.

Design notes (see ``planning/plan-4-interface/plan.md`` § 0 Parallel-work rule):

* Every stub mirrors a FROZEN spec contract: SPEC-001 (data model), SPEC-002 § 1-2
  (``BaseTool`` / ``ToolRegistry`` / ``default_tools``), SPEC-003 § 2/§ 4/§ 6
  (orchestrator, hooks, context, assembler), SPEC-004 § 1-2 (LLM client + factory,
  planner), SPEC-006
  § 1/§ 3/§ 6 (config, redaction, structured logger, report).
* :func:`stub_modules` registers a stub under the **real** dotted name (e.g.
  ``agent_harness.tools.base``) but *only when the real module is absent*. Once
  Plans 1-3 land (integration-window step I1) the real modules are importable, the
  stubs step aside, and ``agent_harness.harness`` runs the identical code path
  against real code — no edit to the composition root is required. That is what
  makes the I1 swap a no-op.

This file is a test helper only. It is never imported by ``agent_harness/``.

Spec: SPEC-000 § 5.4 (contract tests) · SPEC-001 · SPEC-002 § 1-2 · SPEC-003 § 2 ·
SPEC-004 § 1-2 · SPEC-005 § 1 · SPEC-006 § 1-3
"""

from __future__ import annotations

import contextlib
import dataclasses
import importlib.util
import os
import re
import sys
import types
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# SPEC-001 § 1 — Enumerations (FROZEN)
# ---------------------------------------------------------------------------


class StepStatus(Enum):
    """SPEC-001 § 1.1 — terminal and transient step states."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class TaskPriority(Enum):
    """SPEC-001 § 1.2 — failure semantics per priority."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ---------------------------------------------------------------------------
# SPEC-001 § 2 — Dataclasses (FROZEN field names/types/defaults)
# ---------------------------------------------------------------------------


@dataclass
class Step:
    """SPEC-001 § 2.1 — a single unit of work."""

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
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> int | None:
        """SPEC-001 § 2.1 — ``None`` unless both timestamps are set."""
        if self.started_at is None or self.completed_at is None:
            return None
        delta = self.completed_at - self.started_at
        return int(delta.total_seconds() * 1000)

    def to_dict(self) -> dict[str, Any]:
        """SPEC-001 § 4 — JSON-safe serialisation."""
        return {
            "id": self.id,
            "description": self.description,
            "tool_hint": self.tool_hint,
            "tool_name": self.tool_name,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "status": self.status.value,
            "error": self.error,
            "retries": self.retries,
            "max_retries": self.max_retries,
            "fallback_tools": list(self.fallback_tools),
            "depends_on": list(self.depends_on),
            "priority": self.priority.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Step:
        """SPEC-001 § 4 — unknown keys ignored, missing keys defaulted."""
        return cls(
            id=data.get("id", cls().id),
            description=data.get("description", ""),
            tool_hint=data.get("tool_hint", ""),
            tool_name=data.get("tool_name", ""),
            input_data=dict(data.get("input_data", {})),
            output_data=data.get("output_data"),
            status=StepStatus(data.get("status", "pending")),
            error=data.get("error"),
            retries=data.get("retries", 0),
            max_retries=data.get("max_retries", 2),
            fallback_tools=list(data.get("fallback_tools", [])),
            depends_on=list(data.get("depends_on", [])),
            priority=TaskPriority(data.get("priority", "high")),
            started_at=_parse_dt(data.get("started_at")),
            completed_at=_parse_dt(data.get("completed_at")),
            metadata=dict(data.get("metadata", {})),
        )


def _parse_dt(value: Any) -> datetime | None:
    """Parse an ISO-8601 string, tolerating ``None``."""
    if value is None:
        return None
    return datetime.fromisoformat(value)


@dataclass
class ExecutionPlan:
    """SPEC-001 § 2.2 — an ordered set of steps produced by the planner."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    original_prompt: str = ""
    steps: list[Step] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    status: StepStatus = StepStatus.PENDING
    final_output: Any = None

    def step_by_id(self, sid: str) -> Step | None:
        """SPEC-001 § 2.2 — lookup by step id."""
        for step in self.steps:
            if step.id == sid:
                return step
        return None

    def to_dict(self) -> dict[str, Any]:
        """SPEC-001 § 4 — JSON-safe serialisation."""
        return {
            "id": self.id,
            "original_prompt": self.original_prompt,
            "steps": [s.to_dict() for s in self.steps],
            "context": self.context,
            "created_at": self.created_at.isoformat(),
            "status": self.status.value,
            "final_output": self.final_output,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ExecutionPlan:
        """SPEC-001 § 4 — inverse of :meth:`to_dict`."""
        return cls(
            id=data.get("id", cls().id),
            original_prompt=data.get("original_prompt", ""),
            steps=[Step.from_dict(s) for s in data.get("steps", [])],
            context=dict(data.get("context", {})),
            created_at=_parse_dt(data.get("created_at")) or datetime.now(),
            status=StepStatus(data.get("status", "pending")),
            final_output=data.get("final_output"),
        )


@dataclass
class ToolResult:
    """SPEC-001 § 2.3 — the only thing a tool may return (FROZEN)."""

    success: bool
    output: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentError(Exception):
    """SPEC-001 § 2.4 — the single structured error type.

    SPEC-001 lists this under *Dataclasses*, yet SPEC-004 § 1.3, SPEC-006 K5 and
    SPEC-005 § 1.1/§ 2.1 all ``raise`` it. A plain dataclass cannot be raised
    (``TypeError: exceptions must derive from BaseException``), so the dataclass also
    inherits :class:`Exception`. See SCR-P4-6 — Plan 1 must do the same or the
    composition root's ``except AgentError`` paths cannot work.
    """

    code: str
    message: str
    component: str
    step_id: str | None = None
    recoverable: bool = False
    recovery_action: str | None = None
    original_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """SPEC-001 § 2.4 — JSON-safe serialisation."""
        return {
            "code": self.code,
            "message": self.message,
            "component": self.component,
            "step_id": self.step_id,
            "recoverable": self.recoverable,
            "recovery_action": self.recovery_action,
            "original_error": self.original_error,
        }

    def __str__(self) -> str:
        """SPEC-001 § 2.4 — ``[code] component(step_id): message``."""
        return f"[{self.code}] {self.component}({self.step_id}): {self.message}"


@dataclass
class ExecutionMetrics:
    """SPEC-001 § 2.5 — post-run accounting."""

    plan_id: str
    prompt_length: int
    total_steps: int
    successful_steps: int
    failed_steps: int
    recovered_steps: int
    skipped_steps: int
    total_retries: int
    total_duration_ms: int
    llm_calls: int
    llm_tokens_used: int
    llm_estimated_cost: float
    tools_used: list[str] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """SPEC-001 § 2.5 — JSON-safe serialisation."""
        return {
            "plan_id": self.plan_id,
            "prompt_length": self.prompt_length,
            "total_steps": self.total_steps,
            "successful_steps": self.successful_steps,
            "failed_steps": self.failed_steps,
            "recovered_steps": self.recovered_steps,
            "skipped_steps": self.skipped_steps,
            "total_retries": self.total_retries,
            "total_duration_ms": self.total_duration_ms,
            "llm_calls": self.llm_calls,
            "llm_tokens_used": self.llm_tokens_used,
            "llm_estimated_cost": self.llm_estimated_cost,
            "tools_used": list(self.tools_used),
            "files_created": list(self.files_created),
            "errors": [dict(e) for e in self.errors],
        }

    @classmethod
    def from_plan(
        cls,
        plan: ExecutionPlan,
        timings: Mapping[str, Any],
        llm_usage: Mapping[str, Any],
    ) -> ExecutionMetrics:
        """SPEC-003 § 7 — compute metrics from a finished plan.

        Args:
            plan: the executed plan.
            timings: ``{"total_duration_ms": int}``.
            llm_usage: ``{"calls": int, "prompt_tokens": int, "completion_tokens": int,
                "estimated_cost": float}``.
        """
        steps = plan.steps
        success = [s for s in steps if s.status == StepStatus.SUCCESS]
        recovered = [
            s
            for s in success
            if s.retries > 0 or s.metadata.get("recovered_via") is not None
        ]
        tools_used: list[str] = []
        for step in steps:
            name = step.tool_name or step.tool_hint
            if name and name not in tools_used:
                tools_used.append(name)
        return cls(
            plan_id=plan.id,
            prompt_length=len(plan.original_prompt),
            total_steps=len(steps),
            successful_steps=len(success),
            failed_steps=len([s for s in steps if s.status == StepStatus.FAILED]),
            recovered_steps=len(recovered),
            skipped_steps=len([s for s in steps if s.status == StepStatus.SKIPPED]),
            total_retries=sum(s.retries for s in steps),
            total_duration_ms=int(timings.get("total_duration_ms", 0)),
            llm_calls=int(llm_usage.get("calls", 0)),
            llm_tokens_used=int(llm_usage.get("prompt_tokens", 0))
            + int(llm_usage.get("completion_tokens", 0)),
            llm_estimated_cost=float(llm_usage.get("estimated_cost", 0.0)),
            tools_used=tools_used,
            files_created=list(plan.context.get("files_created", [])),
            errors=[dict(e) for e in plan.context.get("errors", [])],
        )


# ---------------------------------------------------------------------------
# SPEC-006 § 1 — Configuration schema (FROZEN keys and defaults)
# ---------------------------------------------------------------------------


@dataclass
class LLMConfig:
    """SPEC-006 § 1 — ``llm`` section."""

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
class ExecutionConfig:
    """SPEC-006 § 1 — ``execution`` section."""

    max_steps: int = 20
    step_timeout: int = 120
    max_retries: int = 2
    retry_backoff: str = "exponential"
    retry_base_delay: int = 2
    enable_replan: bool = True
    abort_on_critical_failure: bool = True
    output_dir: str = "./output"
    temp_dir: str = "./tmp"


@dataclass
class SearchConfig:
    """SPEC-006 § 1 — ``search`` section."""

    provider: str = "duckduckgo"
    api_key_env: str = "SEARCH_API_KEY"
    max_results: int = 10


@dataclass
class SecurityConfig:
    """SPEC-006 § 1 — ``security`` section."""

    sandbox_code: bool = True
    code_timeout: int = 30
    max_output_bytes: int = 1000000
    network_in_code: bool = False
    allow_shell: bool = False
    sensitive_patterns: list[str] = field(
        default_factory=lambda: [r"\b\d{3}-\d{2}-\d{4}\b", r"sk-[a-zA-Z0-9]{48}"]
    )


@dataclass
class LoggingConfig:
    """SPEC-006 § 1 — ``logging`` section."""

    level: str = "INFO"
    file: str = "./logs/agent_harness.log"
    format: str = "json"
    console: bool = True


@dataclass
class PluginsConfig:
    """SPEC-006 § 1 — ``plugins`` section."""

    dirs: list[str] = field(
        default_factory=lambda: ["./plugins", "~/.agent_harness/plugins"]
    )
    auto_load: bool = True


_SECTION_NAMES = ("llm", "execution", "search", "security", "logging", "plugins")

#: Key suffixes that hold credential material. ``*_env`` keys hold only the *name* of an
#: environment variable and are therefore safe to surface (SPEC-006 § 1.1).
_SECRET_KEY_SUFFIXES = ("_key", "_token", "_secret", "_password")


def _build_section(section_cls: type[Any], raw: Any) -> Any:
    """Instantiate one config section, ignoring keys the dataclass does not declare.

    SPEC-006 § 1: unknown keys inside a known section are ignored.

    Args:
        section_cls: the section dataclass.
        raw: a mapping of raw values (``None`` is tolerated).

    Returns:
        A populated section instance.
    """
    known = {f.name for f in dataclasses.fields(section_cls())}
    values = dict(raw or {})
    return section_cls(**{k: v for k, v in values.items() if k in known})


@dataclass
class Config:
    """SPEC-006 § 1/§ 1.1 — typed configuration root."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    plugins: PluginsConfig = field(default_factory=PluginsConfig)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Config:
        """SPEC-006 § 1.1 — build from a raw mapping."""
        raw = dict(data)
        return cls(
            llm=_build_section(LLMConfig, raw.get("llm")),
            execution=_build_section(ExecutionConfig, raw.get("execution")),
            search=_build_section(SearchConfig, raw.get("search")),
            security=_build_section(SecurityConfig, raw.get("security")),
            logging=_build_section(LoggingConfig, raw.get("logging")),
            plugins=_build_section(PluginsConfig, raw.get("plugins")),
        )

    @classmethod
    def from_file(cls, path: str) -> Config:
        """SPEC-006 § 1.1 — build from a YAML file.

        The stub refuses to invent config content: a missing file yields defaults,
        which is what makes ``--list-tools`` work with no configuration present
        (SPEC-006 K5). A present file raises, because parsing YAML is Plan 1's job.
        """
        if not os.path.exists(path):
            return cls()
        raise AgentError(
            code="CONFIG_LOAD_FAILED",
            message=(
                "the P4 stub Config does not parse YAML; install the real Plan 1 "
                f"config loader (attempted path: {path})"
            ),
            component="config",
        )

    def get(self, dotted: str, default: Any = None) -> Any:
        """SPEC-006 § 1.1 — dotted-path lookup."""
        node: Any = self
        for part in dotted.split("."):
            node = getattr(node, part, None)
            if node is None:
                return default
        return node

    def to_dict(self, redact_secrets: bool = True) -> dict[str, Any]:
        """SPEC-006 § 1.1 — safe for logs and context.

        Resolved secret values never appear; only ``*_env`` *names* do.
        """
        out: dict[str, Any] = {}
        for name in _SECTION_NAMES:
            section = getattr(self, name)
            out[name] = {
                f.name: getattr(section, f.name) for f in dataclasses.fields(section)
            }
        if redact_secrets:
            for section_values in out.values():
                for key in list(section_values):
                    if key.endswith("_env"):
                        continue  # an env-var *name* is not a secret
                    if key.endswith(_SECRET_KEY_SUFFIXES):
                        section_values[key] = "[REDACTED]"
        return out


# ---------------------------------------------------------------------------
# SPEC-006 § 3.2 — redaction utility
# ---------------------------------------------------------------------------


def sensitive_data_filter(
    text: str, patterns: list[str] | None = None
) -> tuple[str, int]:
    """SPEC-006 § 3.2 — replace sensitive matches with ``[REDACTED]``.

    Returns:
        The filtered text and the number of replacements made.
    """
    if patterns is None:
        patterns = SecurityConfig().sensitive_patterns
    total = 0
    for pattern in patterns:
        text, count = re.subn(pattern, "[REDACTED]", text)
        total += count
    return text, total


# ---------------------------------------------------------------------------
# SPEC-004 § 1 — LLM client interface
# ---------------------------------------------------------------------------


@dataclass
class LLMResponse:
    """SPEC-004 § 1 — one model completion."""

    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str
    latency_ms: int
    redactions: int = 0


@dataclass
class LLMUsage:
    """SPEC-004 § 1 — cumulative process-lifetime counters."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Expose counters for :meth:`ExecutionMetrics.from_plan`."""
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "estimated_cost": self.estimated_cost,
        }


class LLMClient(ABC):
    """SPEC-004 § 1 — the only interface any LLM consumer may depend on."""

    @abstractmethod
    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """SPEC-004 § 1 — single completion."""

    @abstractmethod
    def complete_json(
        self,
        messages: list[dict[str, Any]],
        *,
        schema_hint: str = "",
        temperature: float | None = None,
    ) -> tuple[Any, LLMResponse]:
        """SPEC-004 § 1 — JSON-mode completion."""

    @property
    @abstractmethod
    def usage(self) -> LLMUsage:
        """SPEC-004 § 1 — cumulative usage counters."""


class MockLLMClient(LLMClient):
    """SPEC-004 § 1.2 C7 — scripted responses; deterministic, no network."""

    def __init__(self, responses: list[Any] | None = None) -> None:
        """Seed the scripted response queue."""
        self._responses: list[Any] = list(responses or [])
        self._usage = LLMUsage()
        self.calls_made: list[dict[str, Any]] = []

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Return the next scripted response, or a deterministic default."""
        self.calls_made.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        self._usage.calls += 1
        text = self._responses.pop(0) if self._responses else "stub response"
        return LLMResponse(
            text=str(text),
            model="stub-model",
            prompt_tokens=10,
            completion_tokens=5,
            finish_reason="stop",
            latency_ms=1,
        )

    def complete_json(
        self,
        messages: list[dict[str, Any]],
        *,
        schema_hint: str = "",
        temperature: float | None = None,
    ) -> tuple[Any, LLMResponse]:
        """Return the next scripted payload as parsed JSON."""
        self.calls_made.append({"schema_hint": schema_hint})
        response = self.complete(messages, temperature=temperature)
        return response.text, response

    @property
    def usage(self) -> LLMUsage:
        """Cumulative usage."""
        return self._usage


def create_llm_client(config: Config) -> LLMClient:
    """SPEC-004 § 1.3 — factory; missing API key raises ``CONFIG_VALIDATION_FAILED``.

    SPEC-006 K5: the key is checked *here*, not at config load, so ``--list-tools``
    works without credentials.
    """
    import os

    env_name = config.llm.api_key_env
    if not os.environ.get(env_name):
        raise AgentError(
            code="CONFIG_VALIDATION_FAILED",
            message=(
                f"API key environment variable '{env_name}' is not set. "
                "Remediation: cp .env.example .env and add your key."
            ),
            component="llm",
        )
    return MockLLMClient()


# ---------------------------------------------------------------------------
# SPEC-002 § 1-2 — Tool contract and registry
# ---------------------------------------------------------------------------


class BaseTool(ABC):
    """SPEC-002 § 1 — the tool contract every plugin implements.

    Declared abstract exactly as the FROZEN spec does. This matters beyond fidelity:
    the plugin loader (SPEC-005 § 3 step 3) must be able to *skip* classes with
    remaining abstract methods, which only works if they really are abstract.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """SPEC-002 R6 — unique snake_case identifier."""

    @property
    @abstractmethod
    def description(self) -> str:
        """SPEC-002 R7 — written for LLM consumption."""

    @property
    def capabilities(self) -> list[str]:
        """SPEC-002 § 1 — capability tags."""
        return []

    @abstractmethod
    def execute(
        self, input_data: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        """SPEC-002 R1 — never raises; returns ``ToolResult``."""

    def validate_input(
        self,
        input_data: dict[str, Any],  # noqa: ARG002 - SPEC-002 § 1: base accepts any input
    ) -> tuple[bool, str]:
        """SPEC-002 § 1 — input gate; the base is permissive by contract."""
        return True, ""

    def cleanup(self) -> None:  # noqa: B027 - SPEC-002 § 1 makes this a concrete no-op
        """SPEC-002 R8 — idempotent teardown."""


class ToolRegistry:
    """SPEC-002 § 2 — ordered, name-keyed tool collection."""

    def __init__(self) -> None:
        """Start empty; insertion order is preserved (G3)."""
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """SPEC-002 G1/G2 — ``TypeError`` unless ``BaseTool``; re-register wins."""
        if not isinstance(tool, BaseTool):
            raise TypeError(f"expected a BaseTool instance, got {type(tool).__name__}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        """SPEC-002 § 2 — lookup by name."""
        return self._tools.get(name)

    def find_by_capability(self, capability: str) -> list[BaseTool]:
        """SPEC-002 § 2 — capability lookup."""
        return [t for t in self._tools.values() if capability in t.capabilities]

    def list_tools(self) -> list[dict[str, Any]]:
        """SPEC-002 § 2 — deterministic dicts for planning prompts."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "capabilities": list(t.capabilities),
            }
            for t in self._tools.values()
        ]

    def deregister(self, name: str) -> None:
        """SPEC-002 G5 — unknown name is a no-op."""
        self._tools.pop(name, None)

    def names(self) -> list[str]:
        """SPEC-002 § 2 — sorted names."""
        return sorted(self._tools)


class StubEchoTool(BaseTool):
    """A minimal tool used by P4 tests; not part of the shipped product."""

    def __init__(self, name: str = "stub_echo", *, fail: bool = False) -> None:
        """Configure name and whether execution should fail."""
        self._name = name
        self._fail = fail
        self.cleanup_calls = 0
        self.execute_calls = 0
        self.seen_contexts: list[dict[str, Any]] = []
        self.injected_llm_client: LLMClient | None = None

    @property
    def name(self) -> str:
        """Tool name."""
        return self._name

    @property
    def description(self) -> str:
        """LLM-facing description."""
        return "Echoes input back. Input: {text: str}. Output: str."

    @property
    def capabilities(self) -> list[str]:
        """Capability tags."""
        return ["echo", "testing"]

    def execute(
        self, input_data: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        """Return the input text, or a deterministic failure."""
        self.execute_calls += 1
        self.seen_contexts.append(context)
        if self._fail:
            return ToolResult(
                success=False,
                error="stub failure",
                metadata={
                    "tool_name": self._name,
                    "duration_ms": 0,
                    "retryable": False,
                },
            )
        return ToolResult(
            success=True,
            output=input_data.get("text", ""),
            metadata={"tool_name": self._name, "duration_ms": 0},
        )

    def cleanup(self) -> None:
        """Count cleanups so tests can assert teardown."""
        self.cleanup_calls += 1


def default_tools(config: Config, llm_client: LLMClient) -> list[BaseTool]:
    """SPEC-002 § 2 — the built-in tool set usable under the given config.

    ``shell_command`` appears only when ``security.allow_shell`` is true, mirroring the
    rule the real Plan 2 factory follows; the LLM-backed tools record which client they
    would use so tests can assert the client is threaded through.
    """
    llm_tool = StubEchoTool("llm_synthesize")
    llm_tool.injected_llm_client = llm_client
    tools: list[BaseTool] = [
        StubEchoTool("web_search"),
        StubEchoTool("file_write"),
        llm_tool,
    ]
    if config.security.allow_shell:
        tools.append(StubEchoTool("shell_command"))
    return tools


# ---------------------------------------------------------------------------
# SPEC-003 § 2 — Orchestrator + hooks
# ---------------------------------------------------------------------------


@dataclass
class ExecutionHooks:
    """SPEC-003 § 2.1 — best-effort observability seam."""

    on_plan_start: Callable[[ExecutionPlan], None] | None = None
    on_step_start: Callable[[Step], None] | None = None
    on_step_complete: Callable[[Step, ToolResult], None] | None = None
    on_step_failed: Callable[[Step, str], None] | None = None
    on_recovery: Callable[[Step, int, str], None] | None = None
    on_plan_complete: Callable[[ExecutionPlan], None] | None = None


class Orchestrator:
    """SPEC-003 § 2 — the POEA step loop."""

    def __init__(
        self,
        registry: ToolRegistry,
        config: Config,
        *,
        llm_client: LLMClient | None = None,
        planner: Any | None = None,
        context_store: Any | None = None,
        logger: Any | None = None,
        hooks: ExecutionHooks | None = None,
    ) -> None:
        """Store the injected collaborators."""
        self.registry = registry
        self.config = config
        self.llm_client = llm_client
        self.planner = planner
        self.context_store = context_store
        self.logger = logger
        self.hooks = hooks

    def execute(self, plan: ExecutionPlan) -> ExecutionPlan:
        """SPEC-003 § 2 — execute every step, mutating ``plan`` in place."""
        if self.hooks and self.hooks.on_plan_start:
            self.hooks.on_plan_start(plan)
        for step in plan.steps:
            if self.hooks and self.hooks.on_step_start:
                self.hooks.on_step_start(step)
            tool = self.registry.get(step.tool_hint or step.tool_name)
            started = datetime.now()
            if tool is None:
                step.status = StepStatus.FAILED
                step.error = f"tool not found: {step.tool_hint}"
            else:
                step.tool_name = tool.name
                result = tool.execute(step.input_data, plan.context)
                if result.success:
                    step.status = StepStatus.SUCCESS
                    step.output_data = result.output
                else:
                    step.status = StepStatus.FAILED
                    step.error = result.error
            step.started_at = started
            step.completed_at = datetime.now()
            if self.hooks:
                if step.status is StepStatus.SUCCESS and self.hooks.on_step_complete:
                    self.hooks.on_step_complete(step, ToolResult(success=True))
                elif step.status is StepStatus.FAILED and self.hooks.on_step_failed:
                    self.hooks.on_step_failed(step, step.error or "")
        plan.status = (
            StepStatus.SUCCESS
            if all(s.status is StepStatus.SUCCESS for s in plan.steps)
            else StepStatus.FAILED
        )
        if self.hooks and self.hooks.on_plan_complete:
            self.hooks.on_plan_complete(plan)
        return plan


# ---------------------------------------------------------------------------
# SPEC-003 § 6 — Assembler
# ---------------------------------------------------------------------------


@dataclass
class AssemblyResult:
    """SPEC-003 § 6 — the synthesised deliverable."""

    status: str
    final_output: Any
    output_format: str
    files_created: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class Assembler:
    """SPEC-003 § 6 — final deliverable synthesis."""

    def __init__(
        self,
        config: Config,
        *,
        llm_client: LLMClient | None = None,
        logger: Any | None = None,
    ) -> None:
        """Store the injected collaborators."""
        self.config = config
        self.llm_client = llm_client
        self.logger = logger

    def assemble(self, plan: ExecutionPlan, context: dict[str, Any]) -> AssemblyResult:
        """SPEC-003 § 6 rules 1-6 — template mode always works without an LLM."""
        succeeded = [s for s in plan.steps if s.status == StepStatus.SUCCESS]
        files = list(context.get("files_created", []))
        missing = [s for s in plan.steps if s.status is not StepStatus.SUCCESS]
        if succeeded and not missing:
            status = "completed"
        elif succeeded or files:
            status = "partial"
        else:
            status = "failed"
        body = (
            "\n".join(
                f"## {s.description or s.id}\n\n{s.output_data}" for s in succeeded
            )
            or "No deliverable produced."
        )
        notes = [
            f"step {s.id} did not succeed ({s.status.value}): "
            f"{s.error or 'no error recorded'}"
            for s in missing
        ]
        return AssemblyResult(
            status=status,
            final_output=body,
            output_format="markdown",
            files_created=files,
            notes=notes,
        )


# ---------------------------------------------------------------------------
# SPEC-004 § 2 — Planner
# ---------------------------------------------------------------------------


class Planner:
    """SPEC-004 § 2 — turns a prompt into a validated plan."""

    def __init__(
        self, llm_client: LLMClient, config: Config, *, logger: Any | None = None
    ) -> None:
        """Store the injected collaborators."""
        self.llm_client = llm_client
        self.config = config
        self.logger = logger
        self.plan_calls: list[dict[str, Any]] = []
        self.replan_calls: list[dict[str, Any]] = []

    def plan(
        self,
        prompt: str,
        available_tools: list[dict[str, Any]],
        *,
        context: dict[str, Any] | None = None,
    ) -> ExecutionPlan:
        """Return a single-step plan naming the first available tool.

        The real planner asks the model for the plan (SPEC-004 § 2), so this stub
        does too: usage counters must move for accounting to be meaningful.
        """
        self.plan_calls.append(
            {"prompt": prompt, "available_tools": available_tools, "context": context}
        )
        self.llm_client.complete_json(
            [{"role": "user", "content": prompt}], schema_hint="execution-plan"
        )
        tool_name = available_tools[0]["name"] if available_tools else ""
        step = Step(
            id="step_0",
            description=prompt[:80],
            tool_hint=tool_name,
            input_data={"text": prompt},
        )
        return ExecutionPlan(
            original_prompt=prompt,
            steps=[step],
            context=dict(context or {}),
            status=StepStatus.PENDING,
        )

    def replan_step(
        self,
        step: Step,
        error: str,
        context: dict[str, Any],
    ) -> list[Step]:
        """SPEC-004 § 2 — produce replacement steps; the stub proposes none."""
        self.replan_calls.append(
            {"step_id": step.id, "error": error, "context": context}
        )
        return []


# ---------------------------------------------------------------------------
# SPEC-003 § 4.1 — Context store
# ---------------------------------------------------------------------------


class ContextStore:
    """SPEC-003 § 4.1 — the FROZEN context layout."""

    def __init__(self, config: Config) -> None:
        """Initialise every key in the frozen layout."""
        self.config = config
        self.data: dict[str, Any] = {
            "config": config.to_dict(redact_secrets=True),
            "step_results": {},
            "variables": {},
            "errors": [],
            "files_created": [],
            "llm_client": None,
            "allowed_read_paths": [],
            "allowed_write_paths": [],
        }

    def __getitem__(self, key: str) -> Any:
        """Read a context key."""
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        """Write a context key."""
        self.data[key] = value

    def as_dict(self) -> dict[str, Any]:
        """Expose the raw mapping."""
        return self.data


# ---------------------------------------------------------------------------
# SPEC-006 § 6.2 — Structured logger
# ---------------------------------------------------------------------------


class StructuredLogger:
    """SPEC-006 § 6.2 — JSONL logger; dependency-injected everywhere."""

    def __init__(self, config: Config | None = None) -> None:
        """Bind the config (may be ``None`` for :meth:`default`)."""
        self.config = config
        self.records: list[dict[str, Any]] = []
        self._bound: dict[str, Any] = {}

    def log(self, level: str, component: str, event: str, **fields: Any) -> None:
        """Append one record."""
        record: dict[str, Any] = {
            "level": level,
            "component": component,
            "event": event,
            **self._bound,
            **fields,
        }
        self.records.append(record)

    def debug(self, component: str, event: str, **fields: Any) -> None:
        """DEBUG-level record."""
        self.log("DEBUG", component, event, **fields)

    def info(self, component: str, event: str, **fields: Any) -> None:
        """INFO-level record."""
        self.log("INFO", component, event, **fields)

    def warning(self, component: str, event: str, **fields: Any) -> None:
        """WARNING-level record."""
        self.log("WARNING", component, event, **fields)

    def error(self, component: str, event: str, **fields: Any) -> None:
        """ERROR-level record."""
        self.log("ERROR", component, event, **fields)

    def child(self, component: str, **bound_fields: Any) -> StructuredLogger:
        """Return a logger with bound component/fields."""
        clone = StructuredLogger(self.config)
        clone.records = self.records
        clone._bound = {**self._bound, "component": component, **bound_fields}
        return clone

    @staticmethod
    def default() -> StructuredLogger:
        """SPEC-006 § 6.2 — no-config fallback for tests."""
        return StructuredLogger()


def render_report(
    plan: ExecutionPlan, metrics: ExecutionMetrics, *, style: str = "text"
) -> str:
    """SPEC-006 § 7 — pure report rendering (no I/O)."""
    lines = [
        "EXECUTION REPORT",
        f"Plan: {metrics.plan_id}",
        f"Status: {plan.status.value}",
        f"Steps: {metrics.successful_steps}/{metrics.total_steps} succeeded",
        f"Duration: {metrics.total_duration_ms} ms",
    ]
    if style == "markdown":
        lines = [f"# {line}" if i == 0 else f"- {line}" for i, line in enumerate(lines)]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Stub-module installation under real dotted names
# ---------------------------------------------------------------------------

#: Dotted names the composition root imports -> the stub attributes they expose.
STUB_MODULE_CONTENTS: dict[str, dict[str, Any]] = {
    "agent_harness.config": {
        "Config": Config,
        "LLMConfig": LLMConfig,
        "ExecutionConfig": ExecutionConfig,
        "SearchConfig": SearchConfig,
        "SecurityConfig": SecurityConfig,
        "LoggingConfig": LoggingConfig,
        "PluginsConfig": PluginsConfig,
        "sensitive_data_filter": sensitive_data_filter,
    },
    "agent_harness.config.schema": {
        "Config": Config,
        "Step": Step,
        "ExecutionPlan": ExecutionPlan,
        "ToolResult": ToolResult,
        "AgentError": AgentError,
        "ExecutionMetrics": ExecutionMetrics,
        "StepStatus": StepStatus,
        "TaskPriority": TaskPriority,
    },
    "agent_harness.context": {"ContextStore": ContextStore},
    "agent_harness.context.store": {"ContextStore": ContextStore},
    "agent_harness.logging": {"StructuredLogger": StructuredLogger},
    "agent_harness.logging.logger": {"StructuredLogger": StructuredLogger},
    "agent_harness.logging.report": {"render_report": render_report},
    "agent_harness.llm": {
        "LLMClient": LLMClient,
        "LLMResponse": LLMResponse,
        "LLMUsage": LLMUsage,
        "MockLLMClient": MockLLMClient,
        "create_llm_client": create_llm_client,
    },
    "agent_harness.llm.client": {
        "LLMClient": LLMClient,
        "LLMResponse": LLMResponse,
        "LLMUsage": LLMUsage,
        "MockLLMClient": MockLLMClient,
        "create_llm_client": create_llm_client,
    },
    "agent_harness.tools": {
        "BaseTool": BaseTool,
        "ToolResult": ToolResult,
        "ToolRegistry": ToolRegistry,
        "default_tools": default_tools,
    },
    "agent_harness.tools.base": {
        "BaseTool": BaseTool,
        "ToolResult": ToolResult,
    },
    "agent_harness.planning": {"Planner": Planner},
    "agent_harness.planning.planner": {"Planner": Planner},
    "agent_harness.orchestration": {
        "Orchestrator": Orchestrator,
        "ExecutionHooks": ExecutionHooks,
        "Assembler": Assembler,
        "AssemblyResult": AssemblyResult,
    },
    "agent_harness.orchestration.orchestrator": {
        "Orchestrator": Orchestrator,
        "ExecutionHooks": ExecutionHooks,
    },
    "agent_harness.orchestration.assembler": {
        "Assembler": Assembler,
        "AssemblyResult": AssemblyResult,
    },
}


def real_module_available(name: str) -> bool:
    """Return ``True`` when the real module is importable (its owning plan landed)."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


@contextlib.contextmanager
def stub_modules(
    contents: Mapping[str, Mapping[str, Any]] | None = None,
) -> Iterator[list[str]]:
    """Install stubs under real dotted names, only where the real module is absent.

    Yields:
        The dotted names actually stubbed. Names already provided by Plans 1-3 are
        left untouched, so after integration-window step I1 the same test exercises
        the real modules with no change to the composition root.
    """
    mapping = dict(contents) if contents is not None else dict(STUB_MODULE_CONTENTS)
    installed: list[str] = []
    saved: dict[str, types.ModuleType | None] = {}
    saved_attrs: dict[tuple[str, str], Any] = {}
    try:
        for dotted in sorted(mapping):
            if real_module_available(dotted):
                continue
            saved[dotted] = sys.modules.get(dotted)
            module = sys.modules.get(dotted)
            if module is None:
                module = types.ModuleType(dotted)
                module.__doc__ = (
                    f"P4 spec-shaped stub for {dotted} (tests/_p4_stubs.py)."
                )
                sys.modules[dotted] = module
            for attr, value in mapping[dotted].items():
                if not hasattr(module, attr):
                    saved_attrs[(dotted, attr)] = getattr(module, attr, None)
                setattr(module, attr, value)
            parent, _, leaf = dotted.rpartition(".")
            if parent and parent in sys.modules:
                saved_attrs[(parent, leaf)] = getattr(sys.modules[parent], leaf, None)
                setattr(sys.modules[parent], leaf, module)
            installed.append(dotted)
        yield installed
    finally:
        for dotted, previous in saved.items():
            if previous is None:
                sys.modules.pop(dotted, None)
            else:
                sys.modules[dotted] = previous
        for (owner, attr), previous in saved_attrs.items():
            if owner in sys.modules:
                if previous is None:
                    with contextlib.suppress(AttributeError):
                        delattr(sys.modules[owner], attr)
                else:
                    setattr(sys.modules[owner], attr, previous)
