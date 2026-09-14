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
| P1 Foundation | ⬜ 0/5 | ⬜ 0/5 | ⬜ 0/5 | ⬜ 0/5 | ⬜ 0/5 | 🟡 gated (no skills) | — |
| P2 Tools | ⬜ 0/5 | ⬜ 0/5 | ⬜ 0/5 | ⬜ 0/5 | ⬜ 0/5 | 🟡 gated (no skills) | — |
| P3 Orchestration | ⬜ 0/5 | ⬜ 0/5 | ⬜ 0/5 | ⬜ 0/5 | ⬜ 0/5 | 🟡 gated (no skills) | — |
| P4 Surface | ⬜ 0/5 | ⬜ 0/5 | ⬜ 0/5 | ⬜ 0/5 | ⬜ 0/5 | 🟡 gated (no skills) | — |
| P5 Quality | ⬜ 0/5 | ⬜ 0/5 | ⬜ 0/5 | ⬜ 0/5 | ⬜ 0/5 | 🟡 gated (no skills) | — |

Legend: ⬜ pending · 🟨 in progress · ✅ done · 🟥 blocked. A phase counts done at 5/5 sub-phases.

---

## 6. Broadcasts & Change Control

- **SCR/SKR adjudication** — per SPEC-000 § 7 and agent.md § 6.5. Approved changes are
  logged here with date, ID, affected specs/plans, and required re-reads.
- **Broadcast log** (append-only):

| Date | ID | Summary | Affected plans |
|---|---|---|---|
| 2026-09-14 | INIT | Foundation published; all plans gated on skill-dictionary population | P1–P5 |

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
