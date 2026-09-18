"""Plan 3 cognition layer — planning half.

Spec: SPEC-004 § 2-5 (``Planner``, prompt templates, plan schema, determinism),
SPEC-000 § 2 (layer L2 Cognition).

This package turns a natural-language prompt into a validated ``ExecutionPlan``.
It never executes tools and never mutates a caller's context (SPEC-004 § 5).

Every collaborator — the LLM client, the configuration object, the logger, and the
data-model classes themselves — arrives by injection and is typed structurally, so
this package imports no concrete module from Plan 1 (``agent_harness.config``,
``agent_harness.llm``, ``agent_harness.context``, ``agent_harness.logging``) or
Plan 2 (``agent_harness.tools``). Plan 4's composition root substitutes the real
objects with no change here (SCR-P3-6).

Public surface
--------------
Plan 4's merged composition root resolves this package **by dotted name** at call
time — ``importlib.import_module("agent_harness.planning")`` and then
``module.Planner(llm_client, config, logger=...)`` (see ``agent_harness/harness.py``
and integration-window step I1 in planning/README § 4) — so ``Planner`` must be an
attribute of the package itself, not only of :mod:`agent_harness.planning.planner`
(SCR-P3-12). Exported here are the behaviors SPEC-004 § 2/§ 4 names as this
package's API: :class:`Planner`, :func:`parse_plan`, :func:`validate_plan` and the
prompt templates.

The data-model stand-ins (``Step``, ``ExecutionPlan``, ``StepStatus``,
``TaskPriority``, ``AgentError``) stay in :mod:`agent_harness.planning.planner` and
are deliberately **not** re-exported: SPEC-001 § 2 assigns those classes to Plan 1's
``agent_harness/config/schema.py``, and they exist here only so this package can be
built and tested while Plan 1 is absent. At integration Plan 4 injects the real
classes through ``ModelProvider`` and nothing in this package changes (SCR-P3-6).
"""

from __future__ import annotations

from agent_harness.planning.planner import Planner, parse_plan, validate_plan
from agent_harness.planning.prompts import (
    PLAN_SCHEMA_HINT,
    PLANNING_SYSTEM_PROMPT,
    REPLAN_PROMPT,
    TOOL_SELECTION_PROMPT,
    render_tool_descriptions,
)

__all__ = [
    "PLANNING_SYSTEM_PROMPT",
    "PLAN_SCHEMA_HINT",
    "REPLAN_PROMPT",
    "TOOL_SELECTION_PROMPT",
    "Planner",
    "parse_plan",
    "render_tool_descriptions",
    "validate_plan",
]
