---
name: risk-fmea-premortem
description: "Identify and score failure modes with FMEA (RPN = Severity × Occurrence × Detection) plus a concrete premortem, producing an owned, mitigated risk register."
---

# Risk FMEA & Premortem

## 1. Scope & Objective
- Surface, score, and mitigate the ways a project or system will fail: FMEA failure-mode analysis with RPN scoring, a premortem narrative, and a living risk register.
- In scope: failure enumeration, scoring, mitigation design, register maintenance.
- Out of scope (delegate): schedule risk mechanics → `critical-path-mapping`; post-incident analysis → `incident-postmortem-rca`.

## 2. Trigger Conditions
- Commands: "what could go wrong", "do a risk analysis for X", "premortem this launch", "score these risks".
- Intent patterns: kickoff, pre-release gates, high-stakes changes (migrations, launches, big refactors), architecture decisions.
- Orchestration tags: `plan:risk`, `plan:premortem`, `gate:risk`.

## 3. Core Directives & Standards
1. **RPN = Severity × Occurrence × Detection, each scored 1–10 with a written rationale** — unscored-by-reason scores are all 5s in disguise and are rejected.
2. **Thresholds drive action:** RPN ≥ 100 → mitigation required before the gate; 50–99 → mitigation planned with a date; < 50 → accepted and documented.
3. **Every risk has an owner, a mitigation, an early-warning indicator, and a review date** — a risk without an owner is a wish, not a register entry.
4. **The premortem is concrete:** written from the assumed-failed future ("the launch failed because…"), specific to this system, not a generic "communication issues" list.
5. **Scoring is independent-then-reconciled:** at least two people score separately, then reconcile differences — single-scoring FMEA is theater.

## 4. Execution Workflow
1. **Intake & Analysis:** Define the scope, constraints, and known prior incidents in the domain; enumerate components/stages where failure is possible.
2. **Implementation:** For each failure mode: describe the mechanism (not just the outcome), score S/O/D with rationales, compute RPN, design mitigations (with early-warning indicators) for RPN ≥ 50; write the premortem narrative; build the register.
3. **Validation:** Independent scoring reconciliation completed; 100% of RPN ≥ 100 items have owner + mitigation + early-warning; premortem reviewed by the team; register versioned with a review date (≤ 2 weeks out) and linked to tasks.

## 5. Antipatterns & Prohibited Behaviors
- Scoring without rationales (everything ends up 5 × 5 × 5 = 125, which is uninformative).
- Generic risks ("technical debt", "communication") with no failure mechanism.
- Mitigations without owners or triggers ("we'll watch it").
- A register written once and never reviewed (rotates into fiction).
- Suppressing risks that are inconvenient (the scoring team self-censors).

## 6. Definition of Done & Quality Guardrails
- Risk register delivered: failure modes with mechanisms, S/O/D + rationales, RPN, status.
- 100% of RPN ≥ 100 items have owner + mitigation + early-warning indicator.
- Premortem narrative written, concrete, and team-reviewed.
- Review date set (≤ 2 weeks) and the register versioned with a change log.
