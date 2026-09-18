"""Plan 3 cognition layer — orchestration half.

Spec: SPEC-003 § 1-8 (``Orchestrator``, ``ExecutionHooks``, ``RecoveryManager``,
``Assembler``, ``resolve_execution_order``), SPEC-000 § 2 (layer L2 Cognition).

This package executes a validated ``ExecutionPlan``: it orders the steps by
dependency (:mod:`agent_harness.orchestration.dependency`), runs the POEA step loop
(:mod:`agent_harness.orchestration.orchestrator`), applies the 4-level recovery
cascade (:mod:`agent_harness.orchestration.recovery`) and synthesizes the final
deliverable (:mod:`agent_harness.orchestration.assembler`).

Like :mod:`agent_harness.planning`, every collaborator — the tool registry, the
configuration object, the LLM client, the planner, the context store, the logger and
the data-model classes — arrives by injection and is typed structurally, so nothing
here imports a concrete module from Plan 1 (``agent_harness.config``,
``agent_harness.llm``, ``agent_harness.context``, ``agent_harness.logging``) or
Plan 2 (``agent_harness.tools``). Plan 4's composition root substitutes the real
objects with no change here (SCR-P3-6).

Public surface
--------------
Plan 4's merged composition root resolves this package **by dotted name** at call
time (``importlib.import_module("agent_harness.orchestration")`` and then
``module.Orchestrator(...)``, ``module.ExecutionHooks(...)``, ``module.Assembler(...)``
— see ``agent_harness/harness.py`` and the integration-window step I1 in
planning/README § 4), so every name SPEC-003 puts in this package must be an
attribute of the package itself, not only of its submodule (SCR-P3-12). The re-exports
below are therefore additive per sub-phase, exactly as the modules land:

===========================  ====================================  ============
Name                         Module                                Sub-phase
===========================  ====================================  ============
``resolve_execution_order``  ``orchestration.dependency``          3.1 (this)
``Orchestrator``             ``orchestration.orchestrator``        3.2
``ExecutionHooks``           ``orchestration.orchestrator``        3.5
``RecoveryManager``          ``orchestration.recovery``            4.1
``Assembler``                ``orchestration.assembler``           5.1
``AssemblyResult``           ``orchestration.assembler``           5.1
===========================  ====================================  ============

Until a row lands, ``agent_harness.orchestration`` is a *partially* delivered
package: importing it succeeds while the pending names are absent. Plan 4's test
double installer (``tests/_p4_stubs.py``) skips a dotted name as soon as the real
module is importable, so the composition root needs all six names before the
integration window opens (planning/README § 4: integration runs after all five plans
report ``done``). SCR-P3-12 records this sequencing constraint.
"""

from __future__ import annotations

from agent_harness.orchestration.dependency import resolve_execution_order

__all__ = ["resolve_execution_order"]
