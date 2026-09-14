---
name: scope-dod-enforcer
description: "Enforce scope discipline: written acceptance criteria, global + per-task Definition of Done, explicit out-of-scope boundaries, and a change-control process."
---

# Scope & DoD Enforcer

## 1. Scope & Objective
- Keep work inside its agreed boundaries: acceptance criteria before work starts, a global plus per-task Definition of Done, explicit out-of-scope lists, and a real change-control path for scope movement.
- In scope: defining and policing scope, DoD checklists, completion verification, change requests.
- Out of scope (delegate): WBS structure → `wbs-decomposition`; capacity math → `capacity-leveling`.

## 2. Trigger Conditions
- Commands: "define the scope for X", "is this done?", "this keeps growing", "how do we handle this new request".
- Intent patterns: task completion claims; scope-creep signals ("while I'm at it…"); ambiguous requirements; release go/no-go.
- Orchestration tags: `plan:scope`, `plan:dod`, `gate:completion`.

## 3. Core Directives & Standards
1. **No work starts without measurable acceptance criteria** (Given/When/Then) agreed before implementation — criteria written after the code is acceptance theater.
2. **DoD is two-tier:** a global baseline (tests, lint, types, docs, CI green, review passed) plus per-task criteria; "code compiles" is not a DoD.
3. **Out-of-scope is written down:** the boundary list is a deliverable, reviewed with the scope itself; absence of a list means absence of a boundary.
4. **Scope change is a decision, not a drift:** accept-and-rebaseline or reject — recorded with the impact (schedule/capacity); silent inclusion is prohibited.
5. **"Done" means demonstrated:** completion requires evidence per criterion (test name, recording, output) and the requester's sign-off — not the implementer's word.

## 4. Execution Workflow
1. **Intake & Analysis:** Extract acceptance criteria per work item from the requirements; draft the per-task DoD on top of the global baseline; draft the out-of-scope list.
2. **Implementation (enforcement):** During execution, check work against the criteria continuously; route new requests through the change decision (in-scope / out-of-scope / change-request); on completion, collect evidence per criterion.
3. **Validation:** Each criterion demonstrated (evidence attached); DoD checklist 100% checked; diff audit shows no out-of-scope items landed without a change record; sign-off from the requester, not just the builder.

## 5. Antipatterns & Prohibited Behaviors
- "Done" without a demonstration or evidence.
- Acceptance criteria written after the fact to match whatever was built.
- Silent scope inclusion ("sure, I'll add that while I'm in there").
- A DoD that stops at "compiles and lints".
- Rubber-stamp sign-off (the requester never actually sees the result).

## 6. Definition of Done & Quality Guardrails
- 100% of completed items carry acceptance criteria + demonstration evidence + requester sign-off.
- 0 out-of-scope items in diffs without a recorded change decision.
- Global DoD checklist template in use for every task (auditable).
- Change log current: every accepted/rejected scope movement recorded with impact.
