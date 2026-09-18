"""4-level recovery cascade. Spec: SPEC-003 §5."""

from __future__ import annotations

from typing import Any


class RecoveryManager:
    """Apply the 4-level recovery cascade: retry → fallback → replan → escalate."""

    def __init__(
        self,
        config: Any,
        *,
        logger: Any = None,
        sleep: Any = None,
    ) -> None:
        """Wire config and logger."""
        self.config = config
        self.logger = logger
        self._sleep = sleep or (lambda _: None)

    def attempt_recovery(
        self, step: Any, result: Any, context: dict[str, Any], orchestrator: Any
    ) -> bool:
        """Run the cascade. Returns True if recovered, False otherwise."""
        from agent_harness.config.schema import StepStatus

        retryable = getattr(result, "metadata", {}).get("retryable", False)
        max_retries = getattr(self.config.execution, "max_retries", 3)

        # Level 1: Retry the same tool
        if retryable and max_retries > 0:
            if self._retry(step, result, context, orchestrator, max_retries):
                return True

        # Level 2: Fallback tools
        fallback_tools = getattr(step, "fallback_tools", [])
        if fallback_tools and self.config.execution.enable_replan:
            if self._try_fallbacks(step, fallback_tools, context, orchestrator):
                return True

        # Level 3: LLM re-planning
        if self.config.execution.enable_replan and orchestrator.planner:
            if self._replan(step, result, context, orchestrator):
                return True

        # Level 4: Escalate by priority
        self._escalate(step, context)
        step.status = StepStatus.FAILED
        step.error = getattr(result, "error", "Recovery exhausted")
        errors = context.setdefault("errors", [])
        errors.append({
            "step_id": step.id,
            "attempt": max_retries,
            "error": step.error,
            "recovered": False,
            "level": 4,
        })
        return False

    def _retry(
        self, step: Any, result: Any, context: dict[str, Any], orchestrator: Any, max_retries: int
    ) -> bool:
        """Level 1: Retry with exponential backoff."""
        from agent_harness.config.schema import StepStatus

        base_delay = getattr(self.config.execution, "retry_base_delay", 2)
        for attempt in range(1, max_retries + 1):
            delay = base_delay * (2 ** (attempt - 1))
            self._sleep(delay)
            if orchestrator.hooks and orchestrator.hooks.on_recovery:
                orchestrator._safe_hook(
                    lambda: orchestrator.hooks.on_recovery(step, 1, f"retry #{attempt}")
                )
            step.status = StepStatus.RETRYING
            try:
                tool = orchestrator.registry.get(step.tool_name)
                if not tool:
                    continue
                input_data = orchestrator._resolve_input(step, context)
                new_result = tool.execute(input_data, context)
                if new_result.success:
                    step.status = StepStatus.SUCCESS
                    step.output_data = new_result.output
                    if orchestrator.hooks and orchestrator.hooks.on_step_complete:
                        orchestrator._safe_hook(
                            lambda: orchestrator.hooks.on_step_complete(step, new_result)
                        )
                    context.setdefault("step_results", {})[step.id] = {
                        "type": type(new_result.output).__name__,
                        "output": new_result.output,
                        "tool": step.tool_name,
                        "duration_ms": step.duration_ms,
                    }
                    return True
            except Exception:
                continue
        return False

    def _try_fallbacks(
        self, step: Any, fallback_tools: list[str], context: dict[str, Any], orchestrator: Any
    ) -> bool:
        """Level 2: Try fallback tools in order."""
        from agent_harness.config.schema import StepStatus

        for fallback_name in fallback_tools:
            tool = orchestrator.registry.get(fallback_name)
            if not tool:
                continue
            if orchestrator.hooks and orchestrator.hooks.on_recovery:
                orchestrator._safe_hook(
                    lambda: orchestrator.hooks.on_recovery(step, 2, f"fallback:{fallback_name}")
                )
            try:
                input_data = orchestrator._resolve_input(step, context)
                if not tool.validate_input(input_data):
                    continue
                result = tool.execute(input_data, context)
                if result.success:
                    step.tool_name = fallback_name
                    step.status = StepStatus.SUCCESS
                    step.output_data = result.output
                    if orchestrator.hooks and orchestrator.hooks.on_step_complete:
                        orchestrator._safe_hook(
                            lambda: orchestrator.hooks.on_step_complete(step, result)
                        )
                    context.setdefault("step_results", {})[step.id] = {
                        "type": type(result.output).__name__,
                        "output": result.output,
                        "tool": fallback_name,
                        "duration_ms": step.duration_ms,
                    }
                    return True
            except Exception:
                continue
        return False

    def _replan(
        self, step: Any, result: Any, context: dict[str, Any], orchestrator: Any
    ) -> bool:
        """Level 3: Ask the LLM for alternative steps."""
        from agent_harness.config.schema import StepStatus

        planner = orchestrator.planner
        if not planner or not hasattr(planner, "replan_step"):
            return False
        if orchestrator.hooks and orchestrator.hooks.on_recovery:
            orchestrator._safe_hook(
                lambda: orchestrator.hooks.on_recovery(step, 3, "replan")
            )
        try:
            alternatives = planner.replan_step(
                step, result, context, orchestrator.registry.list_tools()
            )
            if not alternatives:
                return False
            # Execute replacement steps
            for alt_step in alternatives:
                orchestrator._execute_step(alt_step, type(step).__new__(type(step)), context)
                if alt_step.status == StepStatus.SUCCESS:
                    step.status = StepStatus.SUCCESS
                    step.output_data = alt_step.output_data
                    return True
            return False
        except Exception:
            return False

    def _escalate(self, step: Any, context: dict[str, Any]) -> None:
        """Level 4: Escalate by priority."""
        priority = getattr(step, "priority", None)
        priority_value = getattr(priority, "value", str(priority)) if priority else "medium"
        errors = context.setdefault("errors", [])
        errors.append({
            "step_id": step.id,
            "attempt": 0,
            "error": f"Escalated: priority={priority_value}",
            "recovered": False,
            "level": 4,
        })
