---
name: critical-path-mapping
description: "Build dependency graphs and run CPM: early/late dates, float, critical and near-critical paths, bottleneck detection, and what-if scenarios."
---

# Critical Path Mapping

## 1. Scope & Objective
- Turn a WBS into a schedule with real dependencies: critical path method (CPM) analysis, float computation, bottleneck identification, and scenario (what-if) analysis.
- In scope: dependency graph construction, CPM math, bottleneck reports, schedule risk scenarios.
- Out of scope (delegate): WBS authoring → `wbs-decomposition`; people and throughput → `capacity-leveling`.

## 2. Trigger Conditions
- Commands: "when can we ship", "what's the critical path", "what's blocking X", "if task Y slips a week, what happens".
- Intent patterns: WBS complete and scheduling needed; schedule risk questions; dependency-change impact questions.
- Orchestration tags: `plan:schedule`, `plan:criticalpath`.

## 3. Core Directives & Standards
1. **Dependencies are typed and explicit:** finish-start / start-start / finish-to-finish with lags — a bare "A before B" is insufficient for float math.
2. **CPM is computed, not estimated:** early/late start-finish and float per task; the critical path is the zero-float chain; the critical path's duration equals the project duration (a sanity invariant).
3. **Near-critical is reported:** tasks with float ≤ 5 working days are as dangerous as critical ones and get the same attention.
4. **Bottlenecks are identified structurally:** high in-degree × duration nodes, single-owner critical tasks, and serialization risks are listed with mitigation options.
5. **The graph is recomputed on every dependency change** — dates are never hand-adjusted after a change, or the math silently lies.

## 4. Execution Workflow
1. **Intake & Analysis:** Ingest the WBS + durations + dependency matrix; check the graph for cycles before any math (a cycle means the plan is unbuildable, not just risky).
2. **Implementation:** Build the DAG; run forward/backward passes (ES/EF/LS/LF/float); identify the critical path, near-critical tasks, and top bottleneck nodes; run ≥ 2 what-if scenarios (e.g., key task slips 1 week; a resource is unavailable 3 days).
3. **Validation:** No cycles; critical path duration = project duration (invariant check); spot-check float math on 3 random tasks by hand; scenario outputs answer the "what happens" question with dates, not adjectives.

## 5. Antipatterns & Prohibited Behaviors
- A Gantt chart with no dependency data (parallelism assumed, not modeled).
- Adding a magic "buffer task" instead of analyzing where float actually lives.
- Hand-editing dates after a dependency change.
- Ignoring near-critical tasks (the plan breaks there first in practice).
- Confusing CPM with resource constraints (single-person tasks treated as parallel — flag the overload explicitly).

## 6. Definition of Done & Quality Guardrails
- DAG with 0 cycles (verified).
- CPM table per task (ES/EF/LS/LF/float) delivered with the project duration.
- Critical path and near-critical set named; top bottlenecks listed with ≥ 1 mitigation option each.
- ≥ 2 what-if scenarios documented with concrete date impacts.
