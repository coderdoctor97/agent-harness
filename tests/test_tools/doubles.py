"""Shared test doubles for P2 and downstream consumers.

Spec: SPEC-001 §2.3 (ToolResult), SPEC-004 §1 (LLMClient), SPEC-006 §1 (Config)
Provides FakeConfig, FakeLLMClient, FakeLogger, EchoTool/BoomTool pattern for P3/P4.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_harness.tools.base import BaseTool, ToolResult

# ── Config fakes (duck-typed to match SPEC-006 §1) ────────────────────────────


@dataclass
class FakeSecurityConfig:
    """Spec: SPEC-006 §1 security section."""

    sandbox_code: bool = True
    code_timeout: int = 30
    max_output_bytes: int = 1_000_000
    network_in_code: bool = False
    allow_shell: bool = False
    sensitive_patterns: list[str] = field(default_factory=list)


@dataclass
class FakeExecutionConfig:
    """Spec: SPEC-006 §1 execution section."""

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
class FakeSearchConfig:
    """Spec: SPEC-006 §1 search section."""

    provider: str = "duckduckgo"
    api_key_env: str = "SEARCH_API_KEY"
    max_results: int = 10


@dataclass
class FakeLLMConfig:
    """Spec: SPEC-006 §1 llm section."""

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
class FakeLoggingConfig:
    """Spec: SPEC-006 §1 logging section."""

    level: str = "INFO"
    file: str = "./logs/agent_harness.log"
    format: str = "json"
    console: bool = True


@dataclass
class FakeConfig:
    """Spec-shaped Config fake (duck-typed)."""

    llm: FakeLLMConfig = field(default_factory=FakeLLMConfig)
    execution: FakeExecutionConfig = field(default_factory=FakeExecutionConfig)
    search: FakeSearchConfig = field(default_factory=FakeSearchConfig)
    security: FakeSecurityConfig = field(default_factory=FakeSecurityConfig)
    logging: FakeLoggingConfig = field(default_factory=FakeLoggingConfig)

    def get(self, dotted_path: str, default: Any = None) -> Any:
        """Dotted-path lookup like real Config.get."""
        cur: Any = self
        for part in dotted_path.split("."):
            if isinstance(cur, dict):
                cur = cur.get(part, default)
            else:
                cur = getattr(cur, part, default)
            if cur is default:
                return default
        return cur

    def to_dict(self, redact_secrets: bool = True) -> dict[str, Any]:
        """Return dict representation (secrets redacted)."""
        return {
            "llm": {
                "provider": self.llm.provider,
                "model": self.llm.model,
                "api_key_env": self.llm.api_key_env,
            },
            "execution": {
                "max_steps": self.execution.max_steps,
                "output_dir": self.execution.output_dir,
                "temp_dir": self.execution.temp_dir,
            },
            "search": {
                "provider": self.search.provider,
                "max_results": self.search.max_results,
            },
            "security": {
                "max_output_bytes": self.security.max_output_bytes,
                "sandbox_code": self.security.sandbox_code,
            },
        }


# ── LLM fakes (SPEC-004 §1) ──────────────────────────────────────────────────


@dataclass
class LLMResponse:
    """Spec: SPEC-004 §1 LLMResponse."""

    text: str
    model: str = "fake-model"
    prompt_tokens: int = 10
    completion_tokens: int = 10
    finish_reason: str = "stop"
    latency_ms: int = 5


@dataclass
class LLMUsage:
    """Spec: SPEC-004 §1 LLMUsage."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost: float = 0.0


class FakeLLMClient:
    """Scripted LLM client for deterministic tests.

    Spec: SPEC-004 §1 contract, plus C7 MockLLMClient behaviour.
    Pass a queue of texts or (text, LLMResponse) tuples.
    """

    def __init__(
        self,
        responses: list[str | LLMResponse] | None = None,
        *,
        json_responses: list[Any] | None = None,
    ) -> None:
        self._responses: list[str | LLMResponse] = list(responses or [])
        self._json_responses: list[Any] = list(json_responses or [])
        self.calls: list[list[dict[str, str]]] = []
        self._usage = LLMUsage()

    @property
    def usage(self) -> LLMUsage:
        return self._usage

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.calls.append(messages)
        self._usage.calls += 1
        self._usage.prompt_tokens += 5
        self._usage.completion_tokens += 5
        if self._responses:
            nxt = self._responses.pop(0)
            if isinstance(nxt, LLMResponse):
                return nxt
            return LLMResponse(text=nxt)
        # default canned
        return LLMResponse(text="fake completion")

    def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        schema_hint: str = "",
        temperature: float | None = None,
    ) -> tuple[Any, LLMResponse]:
        self.calls.append(messages)
        self._usage.calls += 1
        if self._json_responses:
            data = self._json_responses.pop(0)
            resp = LLMResponse(text=str(data))
            return data, resp
        # fallback to complete then try parse
        resp = self.complete(messages, temperature=temperature)
        # naive JSON parse attempt
        import json

        try:
            # strip fences
            t = resp.text.strip()
            if t.startswith("```"):
                t = t.split("\n", 1)[-1]
                t = t.removesuffix("```")
            data = json.loads(t)
            return data, resp
        except Exception:  # noqa: BLE001
            return resp.text, resp


# ── Logger fake (SPEC-006 §6.2) ─────────────────────────────────────────────


class FakeLogger:
    """Records structured log events."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.component: str = "test"

    def log(self, level: str, component: str, event: str, **fields: Any) -> None:
        self.events.append(
            {"level": level, "component": component, "event": event, **fields}
        )

    def debug(self, component: str, event: str, **fields: Any) -> None:
        self.log("DEBUG", component, event, **fields)

    def info(self, component: str, event: str, **fields: Any) -> None:
        self.log("INFO", component, event, **fields)

    def warning(self, component: str, event: str, **fields: Any) -> None:
        self.log("WARNING", component, event, **fields)

    def error(self, component: str, event: str, **fields: Any) -> None:
        self.log("ERROR", component, event, **fields)

    def child(self, component: str, **bound_fields: Any) -> FakeLogger:
        child = FakeLogger()
        child.component = component
        # share events list for visibility
        child.events = self.events
        return child

    @staticmethod
    def default() -> FakeLogger:
        return FakeLogger()


# ── Tool doubles ─────────────────────────────────────────────────────────────


class EchoTool(BaseTool):
    """Deterministic success tool (P3/P5 pattern)."""

    def __init__(
        self,
        name: str = "echo_tool",
        output: Any = "echo",
        capabilities: list[str] | None = None,
    ) -> None:
        self._name = name
        self._output = output
        self._caps = capabilities or ["testing"]
        self.calls: list[tuple[dict[str, Any], dict[str, Any]]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Echo tool {self._name}: returns configured output."

    @property
    def capabilities(self) -> list[str]:
        return self._caps

    def execute(
        self, input_data: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        self.calls.append((dict(input_data), dict(context)))
        return ToolResult(
            success=True,
            output=self._output,
            metadata={"tool_name": self._name, "duration_ms": 1},
        )


class BoomTool(BaseTool):
    """Deterministic failure tool (tests R1, retry)."""

    def __init__(
        self, name: str = "boom_tool", error: str = "boom", retryable: bool = False
    ) -> None:
        self._name = name
        self._error = error
        self._retryable = retryable

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Boom tool {self._name}: always fails."

    @property
    def capabilities(self) -> list[str]:
        return ["testing"]

    def execute(
        self, input_data: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        return ToolResult(
            success=False,
            error=self._error,
            metadata={
                "tool_name": self._name,
                "duration_ms": 1,
                "retryable": self._retryable,
            },
        )

    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str]:
        return True, ""


# ── Workspace helper ─────────────────────────────────────────────────────────


def tmp_workspace() -> Path:
    """Create a temporary workspace directory (caller should cleanup)."""
    td = tempfile.mkdtemp(prefix="agent_harness_test_")
    return Path(td)
