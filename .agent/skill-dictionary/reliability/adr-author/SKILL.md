---
name: adr-author
description: "Write MADR-compliant architecture decision records: context, decision, alternatives with trade-off tables, and a supersede-not-delete status lifecycle."
---

# ADR Author

## 1. Scope & Objective
- Capture architecture decisions as MADR-compliant records: context, the decision, alternatives considered, consequences, and a status lifecycle — short, honest, and reviewable.
- In scope: authoring, reviewing, and superseding ADRs; maintaining the ADR index.
- Out of scope (delegate): diagrams referenced by the ADR → `arch-diagram-generator`; implementing the decision.

## 2. Trigger Conditions
- Commands: "write an ADR for X", "why did we pick Y?", "document this decision", "we're reversing decision Z".
- Intent patterns: significant technology/design choices made; design reviews concluding; a prior decision being overturned.
- Orchestration tags: `docs:adr`, `arch:decide`.

## 3. Core Directives & Standards
1. **MADR format, one page max:** Context → Decision → Consequences (positive/negative/risks) with a trade-off table; if it runs longer, the decision is too big or the writing is too loose.
2. **Alternatives are mandatory:** ≥ 2 real alternatives with reasons for rejection; an ADR without alternatives is a decision dump, not a record.
3. **Status lifecycle is enforced:** `proposed → accepted → superseded by #N`; ADRs are never deleted — wrong decisions are superseded, and the chain stays auditable.
4. **Consequences are honest,** including the negatives and the open questions; a record that only lists benefits failed its purpose.
5. **Accepted only after review:** ≥ 2 stakeholders review before status flips; accepted ADRs link to the issues/diagrams they reference.

## 4. Execution Workflow
1. **Intake & Analysis:** Identify the decision and its context (constraints, forces, stakeholders); collect the real alternatives (≥ 2) and the criteria that matter.
2. **Implementation:** Draft the ADR: context, decision, criteria × options trade-off table, consequences (pros/cons/risks), open questions; number it sequentially; store under `docs/adr/`; add to the index.
3. **Validation:** Review pass — alternatives genuine? consequences honest (negatives included)? status correct? links resolve?; review recorded; status flips to `accepted` only with the sign-offs.

## 5. Antipatterns & Prohibited Behaviors
- ADRs without alternatives (announcing a fait accompli).
- ADRs describing code instead of decisions (that's documentation's job).
- Statuses stuck on `proposed` for months with no review happening.
- Writing the ADR six months after the fact, from memory, with no context.
- Deleting "wrong" ADRs instead of superseding them (audit trail destroyed).

## 6. Definition of Done & Quality Guardrails
- ADR in MADR format, ≤ 1 page, numbered sequentially, index updated.
- ≥ 2 alternatives with explicit rejection reasons in the trade-off table.
- Status `accepted` with recorded reviewer sign-offs (or `proposed` with a scheduled review).
- Supersession chain intact (no orphaned or deleted records).
