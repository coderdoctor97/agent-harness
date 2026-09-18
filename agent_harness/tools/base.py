"""Base tool contracts and result types.

Spec: SPEC-001 §2.3 (ToolResult), SPEC-002 §1 (BaseTool)
"""

from __future__ import annotations

import time
import warnings
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


def _get_max_output_bytes(config: Any) -> int:
    """Resolve max_output_bytes from config with safe defaults.

    Spec: SPEC-006 §1 — security.max_output_bytes defaults to 1000000.
    Duck-typed to avoid importing concrete Config.
    """
    default = 1_000_000
    if config is None:
        return default
    try:
        sec = getattr(config, "security", None)
        if sec is None and isinstance(config, dict):
            sec = config.get("security")
        if sec is None:
            return default
        # sec could be dict or object
        if isinstance(sec, dict):
            val = sec.get("max_output_bytes", default)
        else:
            val = getattr(sec, "max_output_bytes", default)
        if isinstance(val, int) and val > 0:
            return val
        return default
    except Exception:  # noqa: BLE001
        return default


def _truncate_output(output: Any, max_bytes: int) -> tuple[Any, bool]:
    """Truncate textual output per R5.

    Returns (maybe_truncated_output, was_truncated).
    """
    if isinstance(output, str):
        encoded = output.encode("utf-8")
        if len(encoded) > max_bytes:
            # Truncate to max_bytes, ensure marker fits
            marker = "...[truncated]"
            marker_bytes = marker.encode("utf-8")
            # Reserve space for marker
            allowed = max_bytes - len(marker_bytes)
            allowed = max(allowed, 0)
            truncated_bytes = encoded[:allowed]
            # Decode safely, ignoring partial utf-8 at boundary
            truncated_str = truncated_bytes.decode("utf-8", errors="ignore") + marker
            return truncated_str, True
    return output, False


def run_tool(
    tool: BaseTool,
    input_data: dict[str, Any],
    context: dict[str, Any],
    *,
    config: Any = None,
    logger: Any = None,
) -> ToolResult:
    """Uniform execution wrapper enforcing R1/R2/R4/R5.

    Spec: SPEC-002 §1.1 R1,R2,R4,R5 and SPEC-006 §4 S6.

    - Calls validate_input first (R2)
    - Times execution and catches escaping exceptions (R1)
    - Applies output truncation at max_output_bytes (R5)
    - Ensures metadata tool_name and duration_ms (R4)
    - Emits tool_executed log fields when logger provided
    """
    start = time.monotonic()
    tool_name: str = getattr(tool, "name", "unknown")
    max_bytes = _get_max_output_bytes(config)

    # R2 — validate first
    try:
        is_valid, err_msg = tool.validate_input(input_data)
    except Exception as exc:  # noqa: BLE001  # pragma: no cover - defensive
        duration_ms = int((time.monotonic() - start) * 1000)
        result = fail(
            f"validate_input raised: {exc}",
            retryable=False,
            tool_name=tool_name,
            duration_ms=duration_ms,
        )
        _emit_tool_log(logger, tool_name, duration_ms, result, input_data)
        return result

    if not is_valid:
        duration_ms = int((time.monotonic() - start) * 1000)
        # Preserve spec error code semantics via message prefix
        msg = err_msg or "Input validation failed"
        # Ensure message signals TOOL_INPUT_INVALID for orchestrator
        if "TOOL_INPUT_INVALID" not in msg:
            msg = f"TOOL_INPUT_INVALID: {msg}"
        result = fail(
            msg, retryable=False, tool_name=tool_name, duration_ms=duration_ms
        )
        _emit_tool_log(logger, tool_name, duration_ms, result, input_data)
        return result

    # Execute with R1 catch-all
    try:
        raw = tool.execute(input_data, context)
        duration_ms = int((time.monotonic() - start) * 1000)
        # Normalise if tool returned None or wrong type (defensive)
        if not isinstance(raw, ToolResult):
            result = fail(
                f"Tool {tool_name} returned non-ToolResult: {type(raw)!r}",
                retryable=False,
                tool_name=tool_name,
                duration_ms=duration_ms,
            )
        else:
            result = raw
            # R4 — ensure required metadata
            result.metadata.setdefault("tool_name", tool_name)
            result.metadata["tool_name"] = tool_name
            result.metadata.setdefault("duration_ms", duration_ms)
            result.metadata["duration_ms"] = duration_ms
            # R5 — truncation
            truncated_out, was_truncated = _truncate_output(result.output, max_bytes)
            if was_truncated:
                result.output = truncated_out
                result.metadata["truncated"] = True
    except Exception as exc:  # noqa: BLE001  # R1 — never raise
        duration_ms = int((time.monotonic() - start) * 1000)
        result = fail(
            f"Unhandled exception in {tool_name}: {exc}",
            retryable=False,
            tool_name=tool_name,
            duration_ms=duration_ms,
        )

    # Ensure R4 even for exception path (already set via fail)
    if "tool_name" not in result.metadata:
        result.metadata["tool_name"] = tool_name
    if "duration_ms" not in result.metadata:
        result.metadata["duration_ms"] = int((time.monotonic() - start) * 1000)

    _emit_tool_log(
        logger, tool_name, result.metadata.get("duration_ms", 0), result, input_data
    )
    return result


def _emit_tool_log(
    logger: Any,
    tool_name: str,
    duration_ms: int,
    result: ToolResult,
    input_data: dict[str, Any],
) -> None:
    """Emit tool_executed event via injected logger if available."""
    if logger is None:
        return
    fields: dict[str, Any] = {
        "tool_name": tool_name,
        "duration_ms": duration_ms,
        "status": "success" if result.success else "failure",
        "retryable": result.metadata.get("retryable", False),
        "truncated": result.metadata.get("truncated", False),
    }
    # Include error for failures (bounded length)
    if result.error:
        fields["error"] = result.error[:500]
    try:
        # Prefer StructuredLogger.log signature: log(level, component, event, **fields)
        if hasattr(logger, "log"):
            # Try structured style
            try:
                logger.log("INFO", "tools", "tool_executed", **fields)
                return
            except TypeError:
                pass
        # Fallback to info/warning
        if hasattr(logger, "info"):
            logger.info("tools", "tool_executed", **fields)
        elif hasattr(logger, "warning") and not result.success:
            logger.warning("tools", "tool_executed", **fields)
    except Exception:  # noqa: BLE001, S110
        # Logging must never break tool execution
        pass


class ToolRegistry:
    """Registry for tool discovery, registration, and lookup.

    Spec: SPEC-002 §2 — FROZEN contract.
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance. Spec: SPEC-002 §2 G1/G2."""
        if not isinstance(tool, BaseTool):
            raise TypeError("Tool must implement BaseTool interface")
        name: str = tool.name
        if name in self._tools:
            warnings.warn(
                f"Tool {name!r} already registered — overwriting",
                UserWarning,
                stacklevel=2,
            )
        self._tools[name] = tool

    def get(self, name: str) -> BaseTool | None:
        """Lookup tool by name."""
        return self._tools.get(name)

    def find_by_capability(self, capability: str) -> list[BaseTool]:
        """Find tools declaring a given capability tag."""
        return [t for t in self._tools.values() if capability in t.capabilities]

    def list_tools(self) -> list[dict[str, Any]]:
        """List registered tools with description/capabilities (insertion order)."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "capabilities": list(t.capabilities),
            }
            for t in self._tools.values()
        ]

    def deregister(self, name: str) -> None:
        """Remove tool; no-op if unknown (G5)."""
        self._tools.pop(name, None)

    def names(self) -> list[str]:
        """Sorted tool names for deterministic prompts."""
        return sorted(self._tools.keys())
