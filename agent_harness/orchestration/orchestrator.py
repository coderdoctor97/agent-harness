"""POEA step loop orchestrator. Spec: SPEC-003 §2-3."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from agent_harness.tools.base import ToolRegistry


@dataclass
class ExecutionHooks:
    """Observable seams for progress rendering. Spec: SPEC-003 §2.1."""

    on_plan_start: Callable[[Any], None] | None = None
    on_step_start: Callable[[Any], None] | None = None
    on_step_complete: Callable[[Any, Any], None] | None = None
    on_step_failed: Callable[[Any, Any], None] | None = None
    on_recovery: Callable[[Any, int, str], None] | None = None
    on_plan_complete: Callable[[Any], None] | None = None


class Orchestrator:
    """Execute a validated plan step-by-step. Spec: SPEC-003 §2-3."""

    def __init__(
        self,
        registry: Any,
        config: Any,
        *,
        llm_client: Any = None,
        planner: Any = None,
        context_store: Any = None,
        logger: Any = None,
        recovery: Any = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        """Wire collaborators. All optional except registry+config."""
        self.registry = registry
        self.config = config
        self.llm_client = llm_client
        self.planner = planner
        self.context_store = context_store
        self.logger = logger
        self.recovery = recovery
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self.hooks: ExecutionHooks | None = None

    def execute(self, plan: Any) -> Any:
        """Iterate steps in dependency order, applying the POEA loop."""
        from agent_harness.orchestration.dependency import resolve_execution_order

        ordered = resolve_execution_order(plan.steps)
        context = plan.context or {}

        if self.hooks and self.hooks.on_plan_start:
            self._safe_hook(lambda: self.hooks.on_plan_start(plan))

        for step in ordered:
            self._execute_step(step, plan, context)

        if self.hooks and self.hooks.on_plan_complete:
            self._safe_hook(lambda: self.hooks.on_plan_complete(plan))

        return plan

    def _execute_step(self, step: Any, plan: Any, context: dict[str, Any]) -> None:
        """Run one step through tool resolution → execution → recording."""
        from agent_harness.config.schema import StepStatus

        step.status = StepStatus.RUNNING
        if self.hooks and self.hooks.on_step_start:
            self._safe_hook(lambda: self.hooks.on_step_start(step))

        try:
            tool_name = self._resolve_tool_name(step, plan)
            tool = self.registry.get(tool_name) if tool_name else None
            if tool is None:
                error = f"Tool not found: {tool_name or step.tool_hint}"
                self._mark_failed(step, error, context)
                return

            input_data = self._resolve_input(step, context)
            if not tool.validate_input(input_data):
                error = f"Invalid input for {tool_name}"
                self._mark_failed(step, error, context)
                return

            started = self._clock()
            step.started_at = datetime.fromtimestamp(started, tz=timezone.utc)
            result = tool.execute(input_data, context)
            step.completed_at = datetime.fromtimestamp(self._clock(), tz=timezone.utc)

            if result.success:
                step.status = StepStatus.SUCCESS
                step.output_data = result.output
                if self.hooks and self.hooks.on_step_complete:
                    self._safe_hook(
                        lambda: self.hooks.on_step_complete(step, result)
                    )
                context.setdefault("step_results", {})[step.id] = {
                    "type": type(result.output).__name__,
                    "output": result.output,
                    "tool": tool_name,
                    "duration_ms": step.duration_ms,
                }
                if "file_write" in (tool_name or ""):
                    path = result.output if isinstance(result.output, str) else None
                    if path:
                        files = context.setdefault("files_created", [])
                        if path not in files:
                            files.append(path)
            else:
                error = result.error or "Tool execution failed"
                self._attempt_recovery(step, result, context, error)

        except KeyboardInterrupt:
            step.status = StepStatus.FAILED
            step.error = "interrupted"
            raise
        except Exception as exc:
            self._mark_failed(step, str(exc), context)

    def _resolve_tool_name(self, step: Any, plan: Any) -> str | None:
        """Pick the tool: hint → tool_name → LLM selection."""
        if step.tool_name:
            return step.tool_name
        if step.tool_hint:
            if self.registry.get(step.tool_hint):
                return step.tool_hint
        if self.planner and hasattr(self.planner, "select_tool"):
            try:
                selected = self.planner.select_tool(step, self.registry.list_tools())
                if selected:
                    return selected
            except Exception:
                pass
        return step.tool_hint or step.tool_name

    def _resolve_input(self, step: Any, context: dict[str, Any]) -> dict[str, Any]:
        """Substitute placeholders in step.input."""
        import re

        def substitute(value: Any) -> Any:
            if isinstance(value, str):
                pattern = r"\{\{(step|var|config|prompt):([^}]+)\}\}"
                def replacer(match: re.Match) -> str:
                    kind, ref = match.group(1), match.group(2)
                    if kind == "step":
                        step_id, _, field = ref.partition(".")
                        step_result = context.get("step_results", {}).get(step_id, {})
                        return str(step_result.get(field or "output", match.group(0)))
                    elif kind == "var":
                        return str(context.get("variables", {}).get(ref, match.group(0)))
                    elif kind == "prompt":
                        return str(context.get("original_prompt", match.group(0)))
                    return match.group(0)
                return re.sub(pattern, replacer, value)
            elif isinstance(value, dict):
                return {k: substitute(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [substitute(v) for v in value]
            return value

        return substitute(dict(step.input_data or {}))

    def _mark_failed(self, step: Any, error: str, context: dict[str, Any]) -> None:
        """Mark a step failed and record the error."""
        from agent_harness.config.schema import StepStatus

        step.status = StepStatus.FAILED
        step.error = error
        if self.hooks and self.hooks.on_step_failed:
            self._safe_hook(lambda: self.hooks.on_step_failed(step, error))
        errors = context.setdefault("errors", [])
        errors.append({
            "step_id": step.id,
            "attempt": 0,
            "error": error,
            "recovered": False,
            "level": 4,
        })

    def _attempt_recovery(
        self, step: Any, result: Any, context: dict[str, Any], error: str
    ) -> None:
        """Delegate to RecoveryManager if available, else mark failed."""
        if self.recovery:
            try:
                self.recovery.attempt_recovery(step, result, context, self)
                return
            except Exception:
                pass
        self._mark_failed(step, error, context)

    def _safe_hook(self, fn: Callable[[], None]) -> None:
        """Call a hook, isolating exceptions."""
        try:
            fn()
        except Exception:
            pass
