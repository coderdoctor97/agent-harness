"""Base tool contracts and result types.

Spec: SPEC-001 §2.3 (ToolResult), SPEC-002 §1 (BaseTool)
"""

from __future__ import annotations

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
    # Preserve explicit retryable in meta if provided
    # (set above, so if caller passed retryable via meta we override; use param)
    # Already set correctly.
    return ToolResult(success=False, output=None, error=error, metadata=metadata)
