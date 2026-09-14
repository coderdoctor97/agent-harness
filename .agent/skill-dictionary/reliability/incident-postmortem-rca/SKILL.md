---
name: incident-postmortem-rca
description: "Author blameless incident postmortems with UTC timelines, evidence-based 5-Whys, severity classification, and owned, tracked preventive actions."
---

# Incident Postmortem & RCA

## 1. Scope & Objective
- Turn incidents into durable organizational learning: blameless postmortem authoring, evidence-verified timelines, root-cause chains, and preventive actions that actually close.
- In scope: postmortem documents, timeline construction, 5-Whys analysis, action-item tracking.
- Out of scope (delegate): real-time incident response; the technical fixes themselves (owning skills); architecture changes (ADR process).

## 2. Trigger Conditions
- Commands: "write the postmortem for the outage", "why did that happen", "recurring incident on X", "document this near-miss".
- Intent patterns: Sev1/Sev2 incidents resolved; repeat incidents; near-misses worth recording.
- Orchestration tags: `ops:postmortem`, `ops:rca`, `gate:learning`.

## 3. Core Directives & Standards
1. **Blameless, always:** the analysis targets systems and processes, never individuals — a postmortem that assigns personal blame fails its purpose and its culture.
2. **The timeline starts at first signal, not discovery:** UTC timestamps from alerts, logs, and deploys; every key event is evidence-referenced, and "someone noticed" is not an event type.
3. **5-Whys stop at systemic causes, not adjectives:** "the deploy broke it" is a fact; "nobody tested the migration path" is a cause; "people were tired" is a non-answer that needs one more why.
4. **Every action item has an owner, a due date, and a type** (prevent / detect / mitigate); "the team will look into it" is not an action item.
5. **Severity is classified (impact × duration)** and published within 5 business days; actions are tracked to closure on a board, and closure rate is reviewed monthly — untracked actions are the failure mode.

## 4. Execution Workflow
1. **Intake & Analysis:** Gather raw evidence: alerts, logs, deploy records, chat transcripts, monitoring graphs; establish first-signal time; classify severity (impact × duration).
2. **Implementation:** Build the UTC timeline (signal → detection → mitigation → resolution); run the 5-Whys with evidence at each level; write the narrative (what happened, why, what we learned, what we'll change); draft action items (owner + date + type).
3. **Validation:** Independent review: 5 timeline points spot-checked against logs; the root-cause chain has evidence at each level (opinions are labeled as such); every action item has owner + date; team sign-off confirms blameless tone; publish and register actions on the tracking board.

## 5. Antipatterns & Prohibited Behaviors
- Blame assignment, even subtle ("the intern's mistake" — the system let one mistake take down prod).
- "User error" as a root cause (the system should have prevented, detected, or degraded).
- Postmortems without a timeline (narratives that can't be verified).
- Action items without owners or dates (learning that evaporates).
- Writing the postmortem as therapy instead of a document (the insights die in the doc).

## 6. Definition of Done & Quality Guardrails
- Document published ≤ 5 business days after resolution.
- Timeline spot-checked against evidence (5 points verified); root-cause chain ≥ 3 Whys deep with evidence.
- 100% of action items have owner + due date + type; all registered on the tracking board.
- Severity classification recorded; closure review scheduled (monthly tracking visible).
