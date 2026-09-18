# Planning — Index & Orchestrator

**Project:** Agent Harness (see [`../documentations/Agent_Harness_PRD_Developer_README.md`](../documentations/Agent_Harness_PRD_Developer_README.md))
**State:** FOUNDATION — plans approved, implementation gated on skill-dictionary population
([`../.agent/skills/skill-dictionary.md`](../.agent/skills/skill-dictionary.md))

This README is the **orchestrator document** for the five implementation plans. It defines
the workstreams, proves their independence, and specifies the protocol agents follow while
executing them concurrently.

---

## 1. Workstream Index

| Plan | Workstream | One-line mission | Plan file |
|---|---|---|---|
| **P1** | Core Foundation | Data model, configuration, context store, structured logging, LLM client abstraction — the substrate every other plan consumes | [`plan-1-foundation/plan.md`](plan-1-foundation/plan.md) |
| **P2** | Tool System | `BaseTool`/`ToolResult`/`ToolRegistry`, all 10 built-in tools, code sandbox & shell whitelist enforcement | [`plan-2-tools/plan.md`](plan-2-tools/plan.md) |
| **P3** | Planning & Orchestration | Planner + prompts, POEA orchestrator loop, dependency resolution, 4-level recovery cascade, assembler | [`plan-3-orchestration/plan.md`](plan-3-orchestration/plan.md) |
| **P4** | Harness Surface | `AgentHarness` facade & composition root, CLI, plugin auto-discovery, shipped example plugins | [`plan-4-interface/plan.md`](plan-4-interface/plan.md) |
| **P5** | Quality & Delivery | Shared test fixtures, integration/e2e suite, CI, examples, contributor docs, release readiness | [`plan-5-quality/plan.md`](plan-5-quality/plan.md) |

Each plan contains **5 implementation phases**, each phase contains **5 sub-phases**
(25 sub-phases per plan, 125 project-wide). Sub-phase IDs are `<plan>.<phase>.<sub>`,
e.g. `2.3.4` = Plan 2, Phase 3, Sub-phase 4.

---

## 2. Independence Guarantee

The five plans are **mutually independent** and can be executed simultaneously by five
different agents. Independence is structural, enforced by three mechanisms:

### 2.1 Disjoint file ownership

Every path in the future repository is owned by exactly one plan (full matrix:
[`../spec/SPEC-000-architecture-boundaries.md`](../spec/SPEC-000-architecture-boundaries.md) § 3).

| Plan | Owns (top-level) | Never touches |
|---|---|---|
| P1 | `agent_harness/{config,context,logging,llm}/`, `pyproject.toml`, `config.yaml`, `.env.example`, its unit tests | Everything else |
| P2 | `agent_harness/tools/`, `tests/test_tools/` | Everything else |
| P3 | `agent_harness/{planning,orchestration}/`, its unit tests | Everything else |
| P4 | `agent_harness/{harness.py,__main__.py,__init__.py,plugins/}`, `plugins/`, its unit tests | Everything else |
| P5 | `tests/conftest.py`, `tests/integration/`, `examples/`, `.github/`, repo meta (`LICENSE`, `.gitignore`, `CONTRIBUTING.md`), docs additions | Any implementation module |

No plan reads or imports another plan's **concrete code** during parallel execution —
only its **spec**.

### 2.2 Contract-first parallelism

Cross-plan dependencies exist only as frozen interfaces in `../spec/`:

```text
P2 (tools)  ──uses──▶  SPEC-001 data model ──built by── P1
P3 (orch)   ──uses──▶  SPEC-002 tool contract ──built by── P2   (develops against mocks)
P3 (orch)   ──uses──▶  SPEC-004 LLMClient ──built by── P1        (develops against MockLLMClient)
P4 (surface)──uses──▶  SPEC-001..004, 006 ──built by── P1/P2/P3  (composition root; wires real modules LAST)
P5 (quality)──uses──▶  all specs                                  (integration tests after P4 wiring)
```

Because each consumer codes against the spec + mocks, **no plan ever waits for another**.
Real-module wiring happens once, in P4 Phase 5 / P5 Phase 2 (integration window, § 4).

### 2.3 Skill-gated execution

No plan may write any source code until the
[skill dictionary](../.agent/skills/skill-dictionary.md) contains an active skill covering
the change (`.agent/agent.md` § 6). This gate applies identically to all five plans, so it
never creates inter-plan coupling — only a shared start condition.

---

## 3. Execution Protocol (for each concurrent agent)

1. **Declare** — add your Agent Manifest (`.agent/agent.md` § 1) to your plan's Status Log.
2. **Gate** — verify at least one registered skill covers your first sub-phase; otherwise
   file `SKR` and set status `blocked` (§ 6.2 of agent.md).
3. **Execute** — work sub-phases in order within your plan; phases may overlap only where
   your plan explicitly says so. One sub-phase = one reviewable change set.
4. **Verify** — per sub-phase: owned tests + `ruff` + `mypy --strict` on owned paths only.
5. **Record** — append the Skill Ledger row and tick the sub-phase checkbox in your plan.
6. **Escalate** — spec gaps → `SCR`; missing skills → `SKR`; both go in your plan file and
   are broadcast here (§ 6).
7. **Finish** — meet the Definition of Done (SPEC-000 § 6), write the Handoff Note in your
   plan, set manifest status `done`.

**Conflict rule:** if two agents believe they own the same path, both stop and the
orchestrator adjudicates from SPEC-000 § 3. Spec text always wins over plan text.

---

## 4. Integration Window (post-parallel)

After all five plans report `done`, integration proceeds in this fixed order (led by P4
and P5 agents; others on standby for fixes within their owned paths):

| Step | Action | Lead |
|---|---|---|
| I1 | P4 composition root swaps mocks for real P1/P2/P3 modules (owned by P4) | P4 |
| I2 | P5 `tests/conftest.py` fixtures finalized; full unit suite green | P5 |
| I3 | Integration suite (`tests/integration/`) executed against the composed system | P5 |
| I4 | Defects routed to the owning plan's agent; fixes require skills like any change | Owner |
| I5 | CI green on the integration branch → v0.1.0 release checklist (P5 Phase 5) | P5 |

---

## 5. Progress Board

Update one row per plan (orchestrator or plan owner):

| Plan | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Phase 5 | Status | Agent |
|---|---|---|---|---|---|---|---|
| P1 Foundation | ✅ 5/5 | ✅ 5/5 | ✅ 5/5 | ✅ 5/5 | ✅ 5/5 | ✅ done — packages, `pyproject.toml` and all four suites green; SCR-P1-3's editable-install verification completed at I1 | Agent 1 |
| P2 Tools | ✅ 5/5 | ✅ 5/5 | ✅ 5/5 | ✅ 5/5 | ✅ 5/5 | ✅ done — `tests/test_tools/` green (owner log: 230 tests, handoff at 5.5) | Agent 2 |
| P3 Orchestration | ✅ 5/5 | ✅ 5/5 | 🟨 1/5 | ⬜ 0/5 | ⬜ 0/5 | 🟡 code complete, **owner log stale** — `orchestrator.py`/`recovery.py`/`assembler.py` and `tests/test_orchestrator.py` are present and green, but 3.2–5.5 are still marked `pending` in plan-3's Phase Execution Log | Agent 3 |
| P4 Surface | ✅ 5/5 | ✅ 5/5 | ✅ 5/5 | ✅ 5/5 | ✅ 5/5 | ✅ done — 5.1's swap **executed at I1** (commit `993fdac`, SCR-P4-12); suite green | Agent 4 |
| P5 Quality | ⬜ 0/5 | ⬜ 0/5 | ⬜ 0/5 | ⬜ 0/5 | ⬜ 0/5 | ⬜ not started — owns `tests/conftest.py`, `tests/integration/`, CI, examples, release | — |
| P6 Web UI | ✅ 5/5 | ✅ 5/5 | ✅ 5/5 | ✅ 5/5 | ✅ 5/5 | ✅ done (user-requested: local web UI + Windows scripts) — see `planning/plan-6-web-ui/plan.md` | Agent 6 |

> **Board reconciliation (2026-09-18, I1).** Rows above were updated from each plan's own
> status log plus the evidence in `main`: every P1–P4 package is present, `git log` shows
> the merges, and the full unit suite is green (1425 passed at the time of writing).
> Two rows need their owner's attention rather than an edit here: **P3** must mark 3.2–5.5
> done in its own log (the code shipped), and **P5** is the only unstarted plan. The gate
> column that read "gated (no skills)" was stale — 50 skills are registered.

Legend: ⬜ pending · 🟨 in progress · ✅ done · 🟥 blocked. A phase counts done at 5/5 sub-phases.

---

## 6. Broadcasts & Change Control

- **SCR/SKR adjudication** — per SPEC-000 § 7 and agent.md § 6.5. Approved changes are
  logged here with date, ID, affected specs/plans, and required re-reads.
- **Broadcast log** (append-only):

| Date | ID | Summary | Affected plans |
|---|---|---|---|
| 2026-09-14 | INIT | Foundation published; all plans gated on skill-dictionary population | P1–P5 |
| 2026-09-18 | I1 | Composition root swapped onto the real P1–P3 modules; P4 suite green (SCR-P4-11, SCR-P4-12) | P4 |
| 2026-09-18 | P6 | New plan published: local web UI (PRD G8, FastAPI + SSE) and the Windows on-ramp (`setup.bat`, `start.bat`); SCR-P6-1 filed for a `web` config section | P1 (SCR), P5 (CI installs `.[dev,web]`), P6 |

---

## 7. Repository Map (foundation deliverables)

```text
agent-harness/
├── README.md                     ← global project README (vision overview + governance)
├── planning/                     ← this directory: 5 independent plans + orchestrator
│   ├── README.md
│   ├── plan-1-foundation/plan.md
│   ├── plan-2-tools/plan.md
│   ├── plan-3-orchestration/plan.md
│   ├── plan-4-interface/plan.md
│   └── plan-5-quality/plan.md
├── .agent/                       ← agent governance
│   ├── README.md
│   ├── agent.md                  ← standard agent format + binding rules
│   └── skills/skill-dictionary.md← skill registry (awaiting population)
├── spec/                         ← frozen contracts (SPEC-000 … SPEC-006)
└── documentations/               ← verbatim vision + doc index
```
