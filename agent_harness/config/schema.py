"""Shared foundation data contracts. Spec: SPEC-001; SPEC-006 §1."""

from __future__ import annotations

import math
import os
import uuid
from dataclasses import dataclass, field, fields
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Optional,
    TypeVar,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

if TYPE_CHECKING:
    from agent_harness.logging import StructuredLogger

T = TypeVar("T", bound="_Serializable")


class _Serializable:
    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-safe mapping. Spec: SPEC-001 §4."""
        return {
            f.name: _json_value(getattr(self, f.name)) for f in fields(cast(Any, self))
        }

    @classmethod
    def from_dict(cls: type[T], d: dict[str, Any]) -> T:
        """Ignore unknown keys, validate types and decode values. Spec: SPEC-001 §4."""
        try:
            if not isinstance(d, dict):
                raise ValueError("expected a mapping")
            hints = get_type_hints(cls)
            values = {
                f.name: _decode(d[f.name], hints[f.name])
                for f in fields(cast(Any, cls))
                if f.name in d
            }
            result = cls(**values)
            if isinstance(result, Step):
                result.validate()
            if isinstance(result, ExecutionPlan):
                ids = [s.id for s in result.steps]
                if len(set(ids)) != len(ids):
                    raise ValueError("duplicate step IDs")
                if any(dep not in ids for s in result.steps for dep in s.depends_on):
                    raise ValueError("unknown dependency")
            return result
        except (ValueError, TypeError, AgentError) as exc:
            if cls.__name__ in ("Step", "ExecutionPlan"):
                raise AgentError(
                    "PLAN_PARSE_FAILED", "Invalid plan data", "planner"
                ) from exc
            raise ValueError(f"Invalid {cls.__name__} data") from exc


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, _Serializable):
        return value.to_dict()
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise ValueError("JSON object keys must be strings")
        return {k: _json_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_value(v) for v in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError("value is not JSON serializable")


def _decode(value: Any, hint: Any) -> Any:
    if hint is Any:
        return _json_value(value)
    origin, args = get_origin(hint), get_args(hint)
    if origin is Union:
        if value is None and type(None) in args:
            return None
        return _decode(value, next(a for a in args if a is not type(None)))
    if origin is list:
        if not isinstance(value, list):
            raise ValueError("expected list")
        return [_decode(v, args[0]) for v in value]
    if origin is dict:
        if not isinstance(value, dict):
            raise ValueError("expected dictionary")
        return {_decode(k, args[0]): _decode(v, args[1]) for k, v in value.items()}
    if hint is datetime:
        if not isinstance(value, str):
            raise ValueError("expected ISO datetime")
        return datetime.fromisoformat(value)
    if isinstance(hint, type) and issubclass(hint, Enum):
        return hint(value)
    if isinstance(hint, type) and issubclass(hint, _Serializable):
        return hint.from_dict(value)
    if hint is float and type(value) in (int, float) and math.isfinite(value):
        return float(value)
    if type(value) is not hint:
        raise ValueError("wrong field type")
    return value


class StepStatus(Enum):
    """Execution lifecycle values. Spec: SPEC-001 §1.1."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class TaskPriority(Enum):
    """Failure priority semantics. Spec: SPEC-001 §1.2."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class AgentError(_Serializable, Exception):
    """Structured, catchable failure preserving frozen fields. Spec: SPEC-001 §2.4."""

    code: str
    message: str
    component: str
    step_id: Optional[str] = None
    recoverable: bool = False
    recovery_action: Optional[str] = None
    original_error: Optional[str] = None

    def __post_init__(self) -> None:
        """Preserve exception reconstruction and frozen code strings. Spec: SPEC-001 §2.4."""
        if isinstance(self.code, Enum):
            self.code = str(self.code.value)
        Exception.__init__(
            self,
            self.code,
            self.message,
            self.component,
            self.step_id,
            self.recoverable,
            self.recovery_action,
            self.original_error,
        )

    def __str__(self) -> str:
        """Render a stable diagnostic. Spec: SPEC-001 §2.4."""
        return f"[{self.code}] {self.component}({self.step_id}): {self.message}"


@dataclass
class Step(_Serializable):
    """Single mutable execution unit. Spec: SPEC-001 §2.1."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str = ""
    tool_hint: str = ""
    tool_name: str = ""
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: Any = None
    status: StepStatus = StepStatus.PENDING
    error: Optional[str] = None
    retries: int = 0
    max_retries: int = 2
    fallback_tools: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    priority: TaskPriority = TaskPriority.HIGH
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def validate(self) -> None:
        """Check post-transition invariants. Spec: SPEC-001 §2.1."""
        problem = ""
        if not 0 <= self.retries <= self.max_retries:
            problem = "retries must be between zero and max_retries"
        elif self.status == StepStatus.SUCCESS and self.error is not None:
            problem = "successful step must not carry an error"
        elif self.status == StepStatus.FAILED and self.error is None:
            problem = "failed step must carry an error"
        if problem:
            raise AgentError("PLAN_VALIDATION_FAILED", problem, "planner", self.id)

    @property
    def duration_ms(self) -> Optional[int]:
        """Elapsed milliseconds if timestamps are available. Spec: SPEC-001 §2.1."""
        if self.started_at is None or self.completed_at is None:
            return None
        return int((self.completed_at - self.started_at).total_seconds() * 1000)


@dataclass
class ExecutionPlan(_Serializable):
    """Full mutable task plan. Spec: SPEC-001 §2.2."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    original_prompt: str = ""
    steps: list[Step] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    status: StepStatus = StepStatus.PENDING
    final_output: Any = None

    def step_by_id(self, sid: str) -> Optional[Step]:
        """Find a step or return None. Spec: SPEC-001 §2.2."""
        return next((step for step in self.steps if step.id == sid), None)


def derive_plan_status(plan: ExecutionPlan) -> tuple[StepStatus, dict[str, bool]]:
    """Derive terminal status without mutating the plan. Spec: SPEC-001 §2.2."""
    required = [
        s
        for s in plan.steps
        if s.priority in (TaskPriority.CRITICAL, TaskPriority.HIGH)
    ]
    degraded = any(
        s.status in (StepStatus.FAILED, StepStatus.SKIPPED) for s in plan.steps
    )
    if any(s.status in (StepStatus.FAILED, StepStatus.SKIPPED) for s in required):
        return StepStatus.FAILED, {"degraded": True}
    if any(
        s.status not in (StepStatus.SUCCESS, StepStatus.FAILED, StepStatus.SKIPPED)
        for s in plan.steps
    ):
        return StepStatus.PENDING, {"degraded": degraded}
    return StepStatus.SUCCESS, {"degraded": degraded}


class ErrorCode(str, Enum):
    """Frozen cross-component error catalog. Spec: SPEC-001 §3."""

    CONFIG_LOAD_FAILED = "CONFIG_LOAD_FAILED"
    CONFIG_VALIDATION_FAILED = "CONFIG_VALIDATION_FAILED"
    PROMPT_INVALID = "PROMPT_INVALID"
    PLAN_PARSE_FAILED = "PLAN_PARSE_FAILED"
    PLAN_VALIDATION_FAILED = "PLAN_VALIDATION_FAILED"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_INPUT_INVALID = "TOOL_INPUT_INVALID"
    TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
    SANDBOX_VIOLATION = "SANDBOX_VIOLATION"
    SANDBOX_TIMEOUT = "SANDBOX_TIMEOUT"
    LLM_CALL_FAILED = "LLM_CALL_FAILED"
    LLM_RATE_LIMITED = "LLM_RATE_LIMITED"
    RECOVERY_EXHAUSTED = "RECOVERY_EXHAUSTED"
    PLAN_ABORTED = "PLAN_ABORTED"
    PLUGIN_LOAD_FAILED = "PLUGIN_LOAD_FAILED"
    SYSTEM_ERROR = "SYSTEM_ERROR"


@dataclass
class ExecutionMetrics(_Serializable):
    """Execution counters and artifacts. Spec: SPEC-001 §2.5; SPEC-003 §7."""

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
    tools_used: list[str]
    files_created: list[str]
    errors: list[dict[str, Any]]

    @classmethod
    def from_plan(
        cls, plan: ExecutionPlan, timings: dict[str, float], llm_usage: object
    ) -> ExecutionMetrics:
        """Compute metrics without importing orchestration. Spec: SPEC-003 §7.

        Args:
            plan: Completed plan; context carries errors/files/step_results.
            timings: Orchestrator wall-clock measurement, total_duration_ms key.
            llm_usage: LLMUsage-compatible object or mapping, including estimated_cost.
        """

        def usage(name: str) -> float:
            value = (
                llm_usage.get(name, 0)
                if isinstance(llm_usage, dict)
                else getattr(llm_usage, name, 0)
            )
            return float(value)

        results = plan.context.get("step_results", {})
        recovered_ids = {
            e.get("step_id")
            for e in plan.context.get("errors", [])
            if e.get("recovered")
        }
        recovered = sum(
            s.status == StepStatus.SUCCESS
            and (
                s.retries > 0
                or s.id in recovered_ids
                or bool(results.get(s.id, {}).get("recovered_via"))
                or bool(results.get(s.id, {}).get("metadata", {}).get("recovered_via"))
            )
            for s in plan.steps
        )
        tokens = int(usage("prompt_tokens") + usage("completion_tokens"))
        has_cost = (
            "estimated_cost" in llm_usage
            if isinstance(llm_usage, dict)
            else hasattr(llm_usage, "estimated_cost")
        )
        rate = (
            plan.context.get("config", {}).get("llm", {}).get("cost_per_1k_tokens")
            or 0.0
        )
        cost = usage("estimated_cost") if has_cost else tokens * float(rate) / 1000
        return cls(
            plan.id,
            len(plan.original_prompt),
            len(plan.steps),
            sum(s.status == StepStatus.SUCCESS for s in plan.steps),
            sum(s.status == StepStatus.FAILED for s in plan.steps),
            recovered,
            sum(s.status == StepStatus.SKIPPED for s in plan.steps),
            sum(s.retries for s in plan.steps),
            int(timings.get("total_duration_ms", 0)),
            int(usage("calls")),
            tokens,
            cost,
            list(dict.fromkeys(s.tool_name for s in plan.steps if s.tool_name)),
            list(plan.context.get("files_created", [])),
            [_json_value(e) for e in plan.context.get("errors", [])],
        )


@dataclass
class LLMConfig(_Serializable):
    """Typed llm settings. Spec: SPEC-006 §1."""

    provider: str = "openai"
    model: str = "gpt-4o"
    fallback_model: Optional[str] = None
    api_key_env: str = "OPENAI_API_KEY"
    base_url: Optional[str] = None
    max_tokens: int = 4096
    temperature: float = 0.2
    timeout: int = 60
    max_retries: int = 3
    cost_per_1k_tokens: Optional[float] = None


@dataclass
class ExecutionConfig(_Serializable):
    """Typed execution settings. Spec: SPEC-006 §1."""

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
class SearchConfig(_Serializable):
    """Typed search settings. Spec: SPEC-006 §1."""

    provider: str = "duckduckgo"
    api_key_env: str = "SEARCH_API_KEY"
    max_results: int = 10


@dataclass
class SecurityConfig(_Serializable):
    """Typed security settings. Spec: SPEC-006 §1."""

    sandbox_code: bool = True
    code_timeout: int = 30
    max_output_bytes: int = 1000000
    network_in_code: bool = False
    allow_shell: bool = False
    sensitive_patterns: list[str] = field(
        default_factory=lambda: ["\\b\\d{3}-\\d{2}-\\d{4}\\b", "sk-[a-zA-Z0-9]{48}"]
    )


@dataclass
class LoggingConfig(_Serializable):
    """Typed logging settings. Spec: SPEC-006 §1."""

    level: str = "INFO"
    file: str = "./logs/agent_harness.log"
    format: str = "json"
    console: bool = True


@dataclass
class PluginsConfig(_Serializable):
    """Typed plugins settings. Spec: SPEC-006 §1."""

    dirs: list[str] = field(
        default_factory=lambda: ["./plugins", "~/.agent_harness/plugins"]
    )
    auto_load: bool = True


@dataclass
class Config(_Serializable):
    """Typed aggregate configuration. Spec: SPEC-006 §1.1."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    plugins: PluginsConfig = field(default_factory=PluginsConfig)

    def get(self, path: str, default: object = None) -> object:
        """Look up a public dotted configuration path. Spec: SPEC-006 §1.1."""
        current: object = self
        for part in path.split("."):
            if part.startswith("_") or not hasattr(current, "__dataclass_fields__"):
                return default
            if part not in getattr(current, "__dataclass_fields__"):
                return default
            current = getattr(current, part)
        return current

    @classmethod
    def from_dict(
        cls, d: dict[str, Any], *, logger: StructuredLogger | None = None
    ) -> Config:
        """Load typed configuration from a mapping. Spec: SPEC-006 §1.1."""
        from .loader import load_config_dict

        return load_config_dict(d, logger=logger)

    @classmethod
    def from_file(
        cls, path: str | Path | None = None, *, logger: StructuredLogger | None = None
    ) -> Config:
        """Load YAML and adjacent environment file. Spec: SPEC-006 §1.1."""
        from .loader import load_config_file

        return load_config_file(path, logger=logger)

    def apply_overrides(self, **kwargs: object) -> Config:
        """Apply CLI hooks atomically above environment values. Spec: SPEC-006 §1.2.

        Hooks: output_dir, log_level, max_steps, no_fallback. None means absent.
        P4 must additionally strip plan fallback_tools for no_fallback.
        """
        from .loader import load_config_dict

        paths = {
            "output_dir": ("execution", "output_dir"),
            "log_level": ("logging", "level"),
            "max_steps": ("execution", "max_steps"),
        }
        data = self.to_dict(redact_secrets=False)
        for key, value in kwargs.items():
            if key not in {*paths, "no_fallback"}:
                raise AgentError(
                    "CONFIG_VALIDATION_FAILED", "Unknown CLI override", "config"
                )
            if value is None:
                continue
            if key == "no_fallback":
                if type(value) is not bool:
                    raise AgentError(
                        "CONFIG_VALIDATION_FAILED",
                        "no_fallback must be boolean",
                        "config",
                    )
                if value:
                    data["execution"]["enable_replan"] = False
            else:
                section, field_name = paths[key]
                data[section][field_name] = value
        replacement = load_config_dict(data, apply_env=False)
        for section_field in fields(self):
            setattr(self, section_field.name, getattr(replacement, section_field.name))
        return self

    def to_dict(self, redact_secrets: bool = True) -> dict[str, Any]:
        """Dump configuration without resolved credentials. Spec: SPEC-006 §1.1, §3."""
        from .loader import sensitive_data_filter

        data = super().to_dict()
        if not redact_secrets:
            return data
        secrets = [
            os.environ.get(self.llm.api_key_env, ""),
            os.environ.get(self.search.api_key_env, ""),
        ]

        def clean(value: Any) -> Any:
            if isinstance(value, str):
                return sensitive_data_filter(value, (), secrets=secrets)[0]
            if isinstance(value, list):
                return [clean(item) for item in value]
            if isinstance(value, dict):
                return {
                    k: (v if k.endswith("_env") else clean(v)) for k, v in value.items()
                }
            return value

        return cast(dict[str, Any], clean(data))
