"""Prompt templates for the Plan 3 cognition layer.

Spec: SPEC-004 § 3 (prompt templates). ``PLANNING_SYSTEM_PROMPT`` (§ 3.1) and
``REPLAN_PROMPT`` (§ 3.2) are **FROZEN content** and are reproduced here
character for character; ``tests/test_planner.py`` pins both by equality and by
SHA-256 digest so any drift fails the suite.

``TOOL_SELECTION_PROMPT`` is the additive template of SPEC-004 § 3.3 and
``PLAN_SCHEMA_HINT`` is the ``schema_hint`` argument that
``LLMClient.complete_json`` appends to the system message (SPEC-004 § 1.2 C3).

Rendering note (SCR-P3-8): SPEC-004 § 3.1/§ 3.2 declare their content "verbatim
from vision § 8.1/§ 8.2", yet the two documents are not byte-identical — the
vision leaves two sentences unwrapped where the spec wraps them at ~85 columns
(whitespace-normalized the two are identical). This module implements the
**SPEC-004 bytes**, the binding contract for Plan 3; the complete divergence set
is pinned in ``tests/test_planner.py`` so an orchestrator ruling for the vision
form is a two-line change.

Skills applied: SKL-CORE-TYPES (core-coding/strict-typing-contracts) — no ``Any``
leaks across the public boundary; SKL-CORE-TDD (core-coding/tdd-test-runner).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

__all__ = [
    "PLANNING_SYSTEM_PROMPT",
    "PLAN_SCHEMA_HINT",
    "REPLAN_PROMPT",
    "TOOL_SELECTION_PROMPT",
    "render_tool_descriptions",
]

PLANNING_SYSTEM_PROMPT = """\
You are a task planning agent. Given a user's request, decompose it into a structured
execution plan with ordered steps. Available tools: {tool_descriptions}

For each step, specify:
- description: What this step accomplishes
- tool_hint: Which tool to use (from available tools)
- input_data: Parameters for the tool
- priority: "critical" | "high" | "medium" | "low"
- depends_on: List of step indices this step depends on (e.g., ["step_0"])
- fallback_tools: Alternative tools if the primary fails

Rules:
1. Break complex tasks into atomic, testable steps
2. Each step should have a single clear objective
3. Declare dependencies explicitly — don't assume sequential execution
4. Always include fallback tools where alternatives exist
5. Mark steps that produce the final deliverable as "critical" priority
6. Prefer specific tool hints over generic ones

Respond with valid JSON matching the ExecutionPlan schema."""
# FROZEN — SPEC-004 § 3.1 (verbatim from vision § 8.1). Do not edit; file an SCR.

REPLAN_PROMPT = """\
A step in the execution plan has failed after all retries and fallbacks.

Failed step: {step_description}
Tool used: {tool_name}
Error: {error_message}
Previous attempts: {attempt_history}
Available tools: {tool_descriptions}
Current context: {context_summary}

Generate an alternative step (or sequence of steps) to achieve the same goal using a
different approach. Respond with valid JSON."""
# FROZEN — SPEC-004 § 3.2 (verbatim from vision § 8.2). Do not edit; file an SCR.

TOOL_SELECTION_PROMPT = """\
You are selecting exactly one tool for one step of an execution plan.

Step description: {step_description}
Step input keys: {input_keys}
Available tools: {tool_descriptions}

Respond with a single JSON object and nothing else: {{"tool": "<tool_name>"}} when one
of the available tools can perform the step, or {{"tool": null}} when none of them can.
Never invent a tool name that is not listed above."""
# Additive — SPEC-004 § 3.3: the model answers ``{"tool": "<name>"}`` or
# ``{"tool": null}``. The JSON examples are written with doubled braces so that
# ``str.format`` emits real braces while ``{step_description}``, ``{input_keys}`` and
# ``{tool_descriptions}`` remain substitutable.

PLAN_SCHEMA_HINT = """\
Respond with a single JSON object of the shape:
{"steps": [{"description": str, "tool_hint": str, "input_data": object,
"priority": "critical" | "high" | "medium" | "low", "depends_on": [str],
"fallback_tools": [str]}]}
"steps" is required and must be a non-empty array. "description" and "tool_hint" are
required non-empty strings per step. "input_data" defaults to an empty object,
"priority" defaults to "high", "depends_on" and "fallback_tools" default to empty
arrays. "depends_on" entries reference step ids of the form "step_<index>", where the
index is the position of the referenced step in the "steps" array. No prose, no
markdown fences, no keys other than those listed."""
# Schema hint appended to the system message by ``complete_json`` (SPEC-004 § 1.2 C3);
# plan schema per SPEC-004 § 4.1.


def _tool_field(tool: object, key: str) -> object:
    """Read ``key`` from a tool descriptor given as a mapping or as an object.

    ``ToolRegistry.list_tools()`` returns mappings (SPEC-002 § 2), but tool
    *instances* expose the same three attributes (SPEC-002 § 1), so both shapes are
    accepted; a missing field degrades to an empty string instead of raising.

    Args:
        tool: One entry of ``available_tools``.
        key: ``"name"``, ``"description"`` or ``"capabilities"``.

    Returns:
        The raw field value, or ``""`` when the tool does not carry it.
    """
    if isinstance(tool, Mapping):
        return tool.get(key, "")
    return getattr(tool, key, "")


def _capability_names(value: object) -> list[str]:
    """Normalize a ``capabilities`` field into a list of strings.

    Args:
        value: The raw field value; expected to be a sequence of strings.

    Returns:
        Capability names in declared order, with empty entries dropped. A bare string
        is treated as a single capability, and any non-iterable value yields an empty
        list rather than raising — the prompt is best-effort decoration, never a
        failure path.
    """
    if value is None:
        return []
    items: Iterable[object]
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, Iterable):
        items = value
    else:
        return []
    return [name for item in items if (name := str(item))]


def render_tool_descriptions(available_tools: Sequence[object] | None) -> str:
    """Render ``available_tools`` into the deterministic list of SPEC-004 § 3.1.

    One line per tool, in the exact format ``- name: description [capabilities: a, b]``;
    the bracketed suffix is omitted when the tool declares no capabilities. Input order
    is preserved verbatim (SPEC-002 § 2 G3 makes ``list_tools()`` insertion-ordered, so
    preserving it keeps planning prompts reproducible across runs).

    Args:
        available_tools: ``ToolRegistry.list_tools()`` output, or ``None``.

    Returns:
        The rendered block; the empty string when there are no tools.
    """
    if not available_tools:
        return ""
    lines: list[str] = []
    for tool in available_tools:
        name = str(_tool_field(tool, "name"))
        description = str(_tool_field(tool, "description"))
        capabilities = _capability_names(_tool_field(tool, "capabilities"))
        line = f"- {name}: {description}"
        if capabilities:
            line += f" [capabilities: {', '.join(capabilities)}]"
        lines.append(line)
    return "\n".join(lines)
