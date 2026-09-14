# Agent Standard — Agent Harness

**Version:** 1.0.0 · **Status:** BINDING · **Applies to:** every agent (human-directed or
autonomous) that reads, plans, or writes anything in this repository.

This document defines the **standard agent format** for the project. An "agent" is any
actor assigned one of the five workstreams in [`../planning/README.md`](../planning/README.md).
Nothing in this file is advisory; §6 in particular is a hard gate.

---

## 1. Agent Definition Format

Every agent MUST be declared in this exact structure before it touches the repository.
The declaration is stored as the **Agent Manifest** block at the top of the agent's own
plan file status log (`planning/plan-N-*/plan.md` § Status Log), or in a separate
`agent-card.md` when the orchestrator requests one.

```yaml
# ── Agent Manifest ────────────────────────────────────────────
agent_id:        P2-tools-01            # <plan>-<workstream>-<instance>
name:            Toolsmith
role:            implementer            # implementer | reviewer | orchestrator | tester
plan:            planning/plan-2-tools/plan.md
owned_paths:                            # MUST be copied verbatim from SPEC-000 § 3
  - agent_harness/tools/
  - tests/test_tools/
consumed_specs:                         # specs this agent codes against
  - SPEC-001  # core data model
  - SPEC-002  # tool system (owns)
  - SPEC-006  # sandbox, logging, config
produces:                               # artifacts handed to other plans
  - agent_harness.tools.default_tools()
  - tests/test_tools/*
skills_authorized:                      # skill IDs this agent may apply (§ 6)
  - PENDING                             # empty until the dictionary is populated
status:          idle                   # idle | active | blocked | done
started_at:      null
last_update:     null
# ──────────────────────────────────────────────────────────────
```

Field rules:

| Field | Requirement |
|---|---|
| `agent_id` | Unique across the project. Prefix must match the assigned plan. |
| `owned_paths` | Verbatim subset of SPEC-000 § 3 for that plan. An agent with paths outside its plan's list is **invalid** and must not run. |
| `consumed_specs` | Must list every spec whose contracts the agent implements or depends on. |
| `skills_authorized` | Populated only from registered skill IDs in `skills/skill-dictionary.md`. `PENDING` while the dictionary is empty. |
| `status` | Kept current; `blocked` requires a blocking reason line immediately below the manifest. |

---

## 2. Required Agent Sections

An agent's working document (its plan file plus manifest) must contain these sections:

1. **Mission** — one paragraph: what outcome this agent produces and for whom.
2. **Boundaries** — owned paths, read-only paths, forbidden actions (§ 4).
3. **Contracts In / Out** — which specs it consumes and which interfaces it publishes.
4. **Phase Execution Log** — the 5 × 5 sub-phase checklist from its plan, each marked
   `pending / in-progress / done / blocked` with a one-line note.
5. **Skill Ledger** — append-only table: `timestamp · sub-phase · file(s) · skill_id(s) · summary`
   (§ 6.4). This is the audit trail proving skill compliance.
6. **Spec Change Requests** — SCR entries per SPEC-000 § 7.
7. **Handoff Note** — deviations, integration notes for Plan 4/5, known limitations.

---

## 3. Standard Agent Lifecycle

```text
0. DECLARE   write the Agent Manifest; confirm owned_paths against SPEC-000 § 3
1. ORIENT    read the vision (documentations/), the consumed specs, and the plan file
2. GATE      confirm at least one applicable registered skill exists for the work
             → if none: STOP, set status blocked, file a Skill Request (§ 6.5)
3. EXECUTE   work sub-phase by sub-phase, in order; one sub-phase = one coherent change
4. VERIFY    per sub-phase: tests + ruff + mypy on owned paths only
5. RECORD    append to the Skill Ledger and Phase Execution Log
6. REPORT    update status; raise SCRs; write the Handoff Note at plan completion
```

An agent never jumps ahead of a `blocked` sub-phase without orchestrator approval, and
never marks a sub-phase `done` without a Skill Ledger entry covering it.

---

## 4. Agent Boundaries

### 4.1 Forbidden actions (all agents, always)

| # | Prohibition |
|---|---|
| F1 | Creating, editing, moving, or deleting any file outside `owned_paths` |
| F2 | Editing anything in `spec/`, `.agent/`, or `documentations/Agent_Harness_PRD_Developer_README.md` |
| F3 | Importing or reading another plan's concrete modules during parallel execution — consume the spec, use `MockLLMClient` / mock tools instead |
| F4 | Any source-code change without an applicable registered skill (§ 6) |
| F5 | Weakening security controls: sandbox patterns, shell whitelist, redaction, path guards |
| F6 | Committing secrets, real API keys, `.env`, or anything matched by `security.sensitive_patterns` |
| F7 | Silencing failures: bare `except:`, `pass` on error paths, deleting failing tests, lowering coverage gates |
| F8 | Adding dependencies not listed in SPEC-006 / `pyproject.toml` without an approved SCR |
| F9 | Changing a FROZEN interface unilaterally — file an SCR instead |
| F10 | Marking work complete that was not verified (tests, lint, types) |

### 4.2 Read-only shared assets

`spec/**`, `.agent/**`, the verbatim vision document, and other plans' `plan.md` files.
Reading is encouraged; writing is a boundary violation.

---

## 5. Work Product Standards

| Aspect | Standard |
|---|---|
| Language/versions | Python ≥ 3.9, target 3.11; `from __future__ import annotations` where needed |
| Typing | `mypy --strict` clean on owned paths; no `Any` leakage across public boundaries |
| Style | `ruff format` + `ruff check` clean; Google-style docstrings |
| Traceability | Every public module/class/function docstring cites its spec section, e.g. `Spec: SPEC-002 § 3.1` |
| Tests | Owned unit tests, deterministic, no live network/LLM calls; ≥ 80 % coverage of owned modules |
| Errors | Only spec-defined `AgentError` codes; tools never raise out of `execute()` |
| Logging | Via injected `StructuredLogger`; events from the SPEC-006 § 6.1 catalog only |
| Commits | Conventional Commits, plan-scoped, skill-cited: `feat(tools): add web_search [P2][SKL-TOOL-001]` |
| Sub-phase granularity | One sub-phase = one reviewable change set; do not batch multiple sub-phases into a single commit |

---

## 6. Skill Dictionary Mandate (BINDING)

### 6.1 The rule

> **An agent MUST 100% use a skill from
> [`skills/skill-dictionary.md`](skills/skill-dictionary.md) to implement any change —
> even a single change — in the source code.**

"Source code" means every file under `agent_harness/`, `tests/`, `plugins/`, `examples/`,
`.github/`, plus `pyproject.toml`, `config.yaml`, and `.env.example`. Documentation-only
edits inside an agent's own `plan.md` status sections are exempt.

Concretely, for **each** change:

1. **Coverage** — 100 % of the change must be produced by applying one or more registered
   skills. There is no permitted unskilled portion: not a line, not an import, not a
   renamed variable, not a deleted blank line, not a "trivial fix".
2. **Applicability** — the chosen skill's `applies_to` must match the file paths and the
   change kind. A skill used outside its declared scope counts as **no skill**.
3. **Complete application** — every step of the skill's procedure must be followed,
   including its quality gates. Partial application counts as **no skill**.
4. **No improvisation** — if a needed technique has no registered skill, the agent stops
   and files a Skill Request (§ 6.5). It does not invent the technique inline.
5. **No self-registration** — agents may not add, edit, or "temporarily" register skills.
   The dictionary is populated only through the designated skill-registration process.
6. **Precedence** — when several skills apply, use the most specific. Compose multiple
   skills when a change spans concerns (e.g. implement a tool + write its tests); cite all
   of them.

### 6.2 Hard stop condition

**The skill dictionary is currently unpopulated (`0` registered skills).** Therefore, at
this moment, **no agent may make any source-code change whatsoever**. Agents may only:
declare their manifest, read the vision and specs, prepare their plan status log, and file
Skill Requests. The moment the dictionary receives skill definitions (via the upcoming
prompt), work may begin — and only within those skills' coverage.

### 6.3 Verification checklist (run before committing any change)

- [ ] Every modified file is inside my `owned_paths`.
- [ ] For every modified file I can name the skill ID(s) that produced the change.
- [ ] Each cited skill's `applies_to` covers that file and change kind.
- [ ] I followed each cited skill's procedure steps and passed its quality gates.
- [ ] The Skill Ledger has an entry for this change set.
- [ ] The commit message cites the skill ID(s).
- [ ] No portion of the diff is unattributed to a skill.

If any box is unchecked → the change is **rejected**; revert it and resolve the gap.

### 6.4 Skill Ledger format (append-only)

```markdown
| Timestamp (ISO) | Sub-phase | Files | Skill ID(s) | Change summary | Gates passed |
|---|---|---|---|---|---|
| 2026-09-14T10:12Z | 2.1 | agent_harness/tools/base.py | SKL-TOOL-001 | Added BaseTool ABC | tests, ruff, mypy |
```

The ledger is the audit artifact. A sub-phase with no ledger row is treated as not done.

### 6.5 Skill Request format

When work is blocked by a missing skill, file it in the plan's Spec/Skill request section:

```markdown
SKR-<plan>-<n>:
  needed_for:    <sub-phase id + description>
  change_kind:   implement | test | refactor | fix | document | configure
  target_paths:  <files/dirs>
  gap:           <what no registered skill covers>
  proposed_skill: <suggested name, scope, procedure outline, quality gates>
  blocked:       yes | no (partial work continuing on <sub-phases>)
```

The orchestrator adjudicates Skill Requests together with SCRs. Requests never justify
proceeding without a skill.

---

## 7. Reporting & Escalation

| Situation | Action |
|---|---|
| Sub-phase complete | Mark `done` in the Phase Execution Log + append Skill Ledger row |
| Blocked by missing skill | File `SKR`, set `status: blocked`, continue unaffected sub-phases |
| Blocked by spec gap/defect | File `SCR` (SPEC-000 § 7), set `status: blocked` for that sub-phase |
| Blocked by another plan's deliverable | Do not wait — build the spec-conformant mock, note it in the Handoff Note |
| Boundary violation observed (any agent) | Report to the orchestrator immediately; do not "fix" it yourself |
| Plan complete | Write the Handoff Note, set `status: done`, notify the orchestrator |

Status updates go into the plan's Status Log — never into `spec/` or another plan's file.

---

## 8. Agent Roles

| Role | May write source? | Notes |
|---|---|---|
| `implementer` | Yes — within owned paths and skill coverage | One per plan during parallel execution |
| `tester` | Yes — only test files it owns | May not modify implementation files; files SCRs for defects |
| `reviewer` | No | Produces review notes and conformance findings against the specs |
| `orchestrator` | No source; owns `planning/README.md`, adjudicates SCR/SKR, and is the only role that may apply approved changes to `spec/` and the skill dictionary (via the registration process) |

All roles are equally bound by § 6.
