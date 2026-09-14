"""Base tool contracts and result types.

Spec: SPEC-001 §2.3 (ToolResult), SPEC-002 §1 (BaseTool)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    """Standardized result from any tool execution.

    Spec: SPEC-001 §2.3 — FROZEN shape.
    """

    success: bool
    output: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def ok(output: Any = None, **meta: Any) -> ToolResult:
    """Create a successful result with required metadata defaults.

    Spec: SPEC-002 §1.1 R4 — auto-sets tool_name and duration_ms if absent.
    """
    metadata: dict[str, Any] = dict(meta)
    metadata.setdefault("tool_name", "")
    metadata.setdefault("duration_ms", 0)
    return ToolResult(success=True, output=output, error=None, metadata=metadata)


def fail(error: str, *, retryable: bool = False, **meta: Any) -> ToolResult:
    """Create a failure result with required metadata defaults.

    Spec: SPEC-002 §1.1 R4 — auto-sets tool_name and duration_ms if absent.
    """
    metadata: dict[str, Any] = dict(meta)
    metadata.setdefault("tool_name", "")
    metadata.setdefault("duration_ms", 0)
    metadata["retryable"] = retryable
    return ToolResult(success=False, output=None, error=error, metadata=metadata)


class BaseTool(ABC):
    """Abstract base for all tools.

    Spec: SPEC-002 §1 — FROZEN contract.

    Rules:
    R1 — Never raise: execute() must catch its own exceptions and return
         ToolResult(success=False).
    R2 — Validate first: execute() must call validate_input() and return
         TOOL_INPUT_INVALID on rejection.
    R3 — Pure w.r.t. context: tools read from context but must not mutate it.
    R4 — Metadata: every result must set metadata[\"tool_name\"] and
         metadata[\"duration_ms\"]; set retryable when transient.
    R5 — Output limits: textual output truncated to
         config.security.max_output_bytes with \"...[truncated]\" marker.
    R6 — Naming: name is snake_case, unique, ≤40 chars.
    R7 — Description: LLM-facing, ≤300 chars, states inputs/outputs.
    R8 — Cleanup: idempotent and safe even if execute() never ran.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool identifier (snake_case). Spec: SPEC-002 §1 R6."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable LLM-facing description. Spec: SPEC-002 §1 R7."""
        ...

    @property
    def capabilities(self) -> list[str]:
        """Tags describing tool capabilities. Spec: SPEC-002 §1."""
        return []

    @abstractmethod
    def execute(
        self, input_data: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        """Execute tool with given input and shared context.

        Spec: SPEC-002 §1.
        """
        ...

    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str]:
        """Optional input validation.

        Returns (is_valid, error_message). Spec: SPEC-002 §1.
        """
        return True, ""

    def cleanup(self) -> None:
        """Optional cleanup after execution. Idempotent per R8."""
        return
