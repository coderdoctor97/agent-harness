---
name: wbs-decomposition
description: "Decompose work into a hierarchical WBS obeying the 100% rule: deliverable-oriented nodes, 8/80-hour tasks, owned leaves with DoD and dependencies."
---

# WBS Decomposition

## 1. Scope & Objective
- Break a project or initiative into a work breakdown structure that is complete, unambiguous, and executable: levels, deliverables, owners, and dependencies.
- In scope: WBS authoring and baselining; scope completeness checks.
- Out of scope (delegate): scheduling and float → `critical-path-mapping`; resourcing → `capacity-leveling`; acceptance criteria → `scope-dod-enforcer`.

## 2. Trigger Conditions
- Commands: "break this down", "create the WBS for X", "this epic is too big", "kickoff planning".
- Intent patterns: new project/initiative kickoff; a scope description with no tasks; recurring "who owns what" confusion.
- Orchestration tags: `plan:wbs`, `plan:decompose`.

## 3. Core Directives & Standards
1. **100% rule:** each level must sum to exactly 100% of its parent's scope — nothing missing, nothing extra; the check is performed level by level, not by feel.
2. **Deliverable-oriented nodes:** nouns, not verbs ("API contract" and "billing module", not "work on billing" or "do the API").
3. **8/80 rule:** leaf tasks sized 8–80 hours; smaller leaves merge, larger leaves split (no task is both a milestone and a to-do).
4. **Every leaf is executable:** single owner, definition of done, and explicit dependency references (WBS IDs) — an ownerless or DoD-less leaf is invalid.
5. **Out-of-scope is written, not assumed:** the boundary list is part of the WBS deliverable and is stakeholder-reviewed.

## 4. Execution Workflow
1. **Intake & Analysis:** Gather the requirement document, constraints, and success criteria; identify the major deliverables (level-1 candidates) before detailing anything.
2. **Implementation:** Build L0 (project) → L1 (phases/milestones) → L2 (deliverables) → L3 (tasks); apply the 100% rule at each level; assign owners, DoD, and dependency IDs to every leaf; write the out-of-scope list.
3. **Validation:** 100% rule verified per level (checklist, not eyeball); every leaf has owner + DoD + dependencies; no leaf outside the 8/80 band without a recorded reason; stakeholder review sign-off captured; baseline versioned.

## 5. Antipatterns & Prohibited Behaviors
- A WBS that is really a to-do list (verbs, no deliverables, no levels).
- Ten levels of decomposition for a two-week feature (over-engineering the plan).
- The 10% that's always missing (integration, testing, deployment, docs — the classic gaps).
- Ownerless tasks and DoD-less leaves.
- Treating the WBS as carved in stone (no re-baselining process when scope legitimately changes).

## 6. Definition of Done & Quality Guardrails
- WBS delivered as diagram + table with stable IDs (WBS-1.2.3 format).
- 100% rule verified at every level (checklist attached).
- 100% of leaves have owner + DoD + dependency references.
- Out-of-scope list approved by stakeholders; baseline versioned with date.
