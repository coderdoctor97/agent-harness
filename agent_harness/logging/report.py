"""Pure execution report rendering. Spec: SPEC-006 §7; vision §10.2."""

from __future__ import annotations

from agent_harness.config import ExecutionMetrics, ExecutionPlan, StepStatus


def render_report(
    plan: ExecutionPlan, metrics: ExecutionMetrics, *, style: str = "text"
) -> str:
    """Render equivalent text or Markdown summaries without I/O. Spec: SPEC-006 §7."""
    if style not in {"text", "markdown"}:
        raise ValueError("style must be text or markdown")
    banner = "═" * 59
    status = (
        "COMPLETED" if plan.status == StepStatus.SUCCESS else plan.status.value.upper()
    )
    lines = (
        [banner, "EXECUTION REPORT", banner]
        if style == "text"
        else ["# EXECUTION REPORT", ""]
    )
    lines += [
        f"Plan ID: {plan.id}",
        f'Prompt: "{plan.original_prompt}"',
        f"Status: {status}",
        f"Duration: {metrics.total_duration_ms / 1000:.1f}s",
        f"Steps: {metrics.total_steps} total | {metrics.successful_steps} success | "
        f"{metrics.failed_steps} failed | {metrics.skipped_steps} skipped | {metrics.recovered_steps} retried (recovered)",
        f"LLM Tokens: {metrics.llm_tokens_used:,} (est. cost: ${metrics.llm_estimated_cost:.3f})",
        f"Files Created: {', '.join(metrics.files_created) or 'None'}",
        "",
        "Step Details:" if style == "text" else "## Step Details",
    ]
    results = plan.context.get("step_results", {})
    recovered_ids = {e.get("step_id") for e in metrics.errors if e.get("recovered")}
    for index, step in enumerate(plan.steps, 1):
        recovered = (
            step.retries > 0
            or step.id in recovered_ids
            or bool(results.get(step.id, {}).get("recovered_via"))
            or bool(results.get(step.id, {}).get("metadata", {}).get("recovered_via"))
        )
        if step.status == StepStatus.SUCCESS:
            marker = "⟳" if recovered else "✓"
        elif step.status == StepStatus.FAILED:
            marker = "✗"
        else:
            marker = "–"
        retry = (
            f", {step.retries} retr{'y' if step.retries == 1 else 'ies'}"
            if step.retries
            else ""
        )
        line = f"[{marker}] Step {index}: {step.description} ({(step.duration_ms or 0) / 1000:.1f}s, {step.tool_name}{retry})"
        lines.append(("- " if style == "markdown" else "") + line)
    lines += ["", "Errors Encountered:" if style == "text" else "## Errors Encountered"]
    for error in metrics.errors:
        recovery = " → recovered" if error.get("recovered") else ""
        lines.append(
            f"Step {error.get('step_id', 'unknown')}, Attempt {error.get('attempt', 0)}: {error.get('error', '')}{recovery}"
        )
    if not metrics.errors:
        lines.append("None")
    if style == "text":
        lines.append(banner)
    return "\n".join(lines) + "\n"
