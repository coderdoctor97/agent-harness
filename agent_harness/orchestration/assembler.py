"""Output assembly from executed plans. Spec: SPEC-003 §6."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AssemblyResult:
    """The assembled deliverable. Spec: SPEC-003 §6."""

    status: str
    final_output: Any
    files_created: list[str] = field(default_factory=list)


class Assembler:
    """Combine step outputs into a final deliverable. Spec: SPEC-003 §6."""

    def __init__(
        self,
        config: Any,
        *,
        llm_client: Any = None,
        logger: Any = None,
    ) -> None:
        """Wire config and optional LLM for synthesis mode."""
        self.config = config
        self.llm_client = llm_client
        self.logger = logger

    def assemble(self, plan: Any, context: dict[str, Any]) -> AssemblyResult:
        """Assemble the final output from an executed plan.

        Rules (SPEC-003 §6):
        1. Collect SUCCESS step outputs in order
        2. Determine status: completed/partial/failed
        3. Synthesize (LLM or template mode)
        4. Propagate files_created
        """
        from agent_harness.config.schema import StepStatus

        step_results = context.get("step_results", {})
        files_created = list(context.get("files_created", []))

        # Collect successful step outputs in plan order
        successful_outputs = []
        failed_count = 0
        skipped_count = 0
        for step in plan.steps:
            status_value = step.status.value if hasattr(step.status, "value") else str(step.status)
            if status_value in ("success", "SUCCESS"):
                if step.output_data is not None:
                    successful_outputs.append((step, step.output_data))
            elif status_value in ("failed", "FAILED"):
                failed_count += 1
            elif status_value in ("skipped", "SKIPPED"):
                skipped_count += 1

        # Determine status
        total = len(plan.steps)
        if not successful_outputs and failed_count > 0:
            status = "failed"
            final_output = None
        elif failed_count > 0 or skipped_count > 0:
            status = "partial"
            final_output = self._synthesize(plan, successful_outputs, context)
        else:
            status = "completed"
            final_output = self._synthesize(plan, successful_outputs, context)

        return AssemblyResult(
            status=status,
            final_output=final_output,
            files_created=files_created,
        )

    def _synthesize(
        self, plan: Any, successful_outputs: list[tuple[Any, Any]], context: dict[str, Any]
    ) -> str | None:
        """Combine step outputs into a final deliverable.

        Template mode (LLM-free): deterministic markdown assembly.
        LLM mode: single bounded call, falls back to template on failure.
        """
        output_format = context.get("output_format", "markdown")

        # Try LLM synthesis if available
        if self.llm_client and output_format != "json":
            try:
                return self._llm_synthesize(plan, successful_outputs, context)
            except Exception:
                pass  # Fall back to template mode

        # Template mode (works with llm_client=None)
        return self._template_synthesize(plan, successful_outputs, context)

    def _llm_synthesize(
        self, plan: Any, successful_outputs: list[tuple[Any, Any]], context: dict[str, Any]
    ) -> str:
        """Single bounded LLM call to synthesize the final output."""
        parts = []
        for step, output in successful_outputs:
            parts.append(f"Step {step.id}: {step.description}\n{output}")
        combined = "\n\n".join(parts)

        # Truncate to fit token budget
        max_chars = getattr(self.config.llm, "max_tokens", 4000) * 4
        if len(combined) > max_chars:
            combined = combined[:max_chars] + "\n...[truncated]"

        prompt = context.get("original_prompt", "Synthesize these results")
        messages = [
            {
                "role": "system",
                "content": "You are a helpful assistant. Synthesize the following step results into a coherent final output.",
            },
            {
                "role": "user",
                "content": f"Original task: {prompt}\n\nStep results:\n{combined}\n\nProvide the final deliverable.",
            },
        ]
        response = self.llm_client.complete(messages)
        return response.text

    def _template_synthesize(
        self, plan: Any, successful_outputs: list[tuple[Any, Any]], context: dict[str, Any]
    ) -> str:
        """Deterministic markdown assembly without LLM."""
        lines = []
        prompt = context.get("original_prompt", "")
        if prompt:
            lines.append(f"# Task: {prompt}")
            lines.append("")

        for step, output in successful_outputs:
            lines.append(f"## {step.description}")
            lines.append("")
            if isinstance(output, str):
                lines.append(output)
            else:
                lines.append(f"```\n{output}\n```")
            lines.append("")

        # Notes for skipped/degraded steps
        notes = []
        for step in plan.steps:
            status_value = step.status.value if hasattr(step.status, "value") else str(step.status)
            if status_value in ("skipped", "SKIPPED"):
                notes.append(f"- Step {step.id} was skipped: {step.error or 'dependency failed'}")
            elif status_value in ("failed", "FAILED"):
                notes.append(f"- Step {step.id} failed: {step.error or 'unknown error'}")

        if notes:
            lines.append("## Notes")
            lines.append("")
            lines.extend(notes)
            lines.append("")

        return "\n".join(lines)
