# Agent Harness

**Local-first, general-purpose autonomous agent execution framework.**

Give it one natural-language prompt. It decomposes the prompt into a multi-step plan,
selects and invokes tools (web search, code execution, file I/O, data transformation),
recovers from failures automatically, and delivers an assembled output — with full
transparency and extensibility.

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> ## 🟢 Repository state: IMPLEMENTED (v0.1.0, integration in progress)
> Plans 1–4 are delivered: the configuration and LLM layer, the tool system, the
> planning/orchestration/recovery layer and the CLI + plugin surface all exist and
> pass their suites (see each plan's Status Log under `planning/`). Plan 5 (quality,
> CI, examples, release) has not started, and the integration windows in
> [`planning/README.md`](planning/README.md) § 4 are how the layers are being proven
> together.
>
> The **skill gate is satisfied** — the dictionary is populated (50 skills at
> [`.agent/skill-dictionary/`](.agent/skill-dictionary)); see [`.agent/agent.md`](.agent/agent.md) § 6.

---

## Table of Contents

1. [Vision](#vision)
2. [How It Works — the POEA Loop](#how-it-works--the-poea-loop)
3. [Repository Layout](#repository-layout)
4. [The Five Independent Plans](#the-five-independent-plans)
5. [Specifications](#specifications)
6. [Agent Governance & the Skill Mandate](#agent-governance--the-skill-mandate)
7. [For Agents: How to Start Work](#for-agents-how-to-start-work)
8. [For Humans: Reading Order](#for-humans-reading-order)
9. [Usage](#usage)
10. [Roadmap](#roadmap)
11. [License](#license)

---

## Vision

Modern LLMs are powerful reasoning engines but remain stateless, single-turn text
generators without built-in agency. Turning an LLM into an *agent* — something that can
plan, act, observe, and adapt across multiple steps — requires orchestration
infrastructure: task decomposition, tool selection and dispatch, state management, failure
recovery, and output assembly.

Agent Harness provides that infrastructure as a lean, local-first harness with a
well-defined tool interface and a plan-execute-observe loop — production-grade agentic
behavior without heavy abstractions or cloud dependencies.

| Persona | Need served |
|---|---|
| Student/Researcher | Automate multi-step research workflows (search → extract → synthesize → report) from a single prompt |
| Developer | Scaffold projects, generate boilerplate, run code, process data files autonomously |
| Startup Operator | Prototype internal automation without DevOps overhead |
| AI/ML Practitioner | Experiment with agentic architectures, custom tools, and orchestration strategies locally |

**Goals (P0):** single-prompt → multi-step plan · pluggable tool execution · automatic
failure recovery (retry → fallback → re-plan) · full execution transparency.
**Non-goals:** SaaS deployment, auth/multi-tenancy, managed hosting, real-time collaboration.

The complete, authoritative vision (PRD + Developer README) is preserved verbatim at
[`documentations/Agent_Harness_PRD_Developer_README.md`](documentations/Agent_Harness_PRD_Developer_README.md).

---

## How It Works — the POEA Loop

```text
USER PROMPT
     │
     ▼
PLANNER (LLM) ── decomposes into ordered sub-tasks → ExecutionPlan
     │
     ▼
ORCHESTRATOR ── iterates steps, resolves dependencies (DAG), selects tools
     │              │
     │              ▼
     │        TOOL EXECUTION (search / code / file / llm / csv / shell / pdf …)
     │              │
     │              ▼
     │        OBSERVER / ADAPTER
     │          success → feed result into next step's context
     │          failure → Level 1 RETRY → Level 2 FALLBACK TOOL
     │                    → Level 3 LLM RE-PLAN → Level 4 ESCALATE by priority
     ▼
ASSEMBLER ── combines step outputs → final deliverable + execution report + metrics
```

Ten built-in tools ship in the design: `web_search`, `web_scrape`, `code_execute`
(sandboxed), `file_read`, `file_write`, `llm_extract`, `llm_synthesize`, `pdf_export`,
`csv_process`, `shell_command` (whitelisted, opt-in). Custom tools plug in by implementing
`BaseTool` and dropping a file into `plugins/`.

---

## Repository Layout

```text
agent-harness/
├── README.md                          ← this file (global project README)
│
├── planning/                          ← implementation plans + orchestrator
│   ├── README.md                      ← INDEX & ORCHESTRATOR for the 5 plans
│   ├── plan-1-foundation/plan.md      ← P1: data model, config, context, logging, LLM client
│   ├── plan-2-tools/plan.md           ← P2: tool interface, registry, 10 built-in tools, sandbox
│   ├── plan-3-orchestration/plan.md   ← P3: planner, orchestrator, recovery, assembler
│   ├── plan-4-interface/plan.md       ← P4: harness API, composition root, CLI, plugins
│   └── plan-5-quality/plan.md         ← P5: test infra, integration suite, CI, docs, release
│
├── .agent/                            ← agent governance (rules & skills)
│   ├── README.md
│   ├── agent.md                       ← standard agent format + BINDING rules
│   └── skills/
│       └── skill-dictionary.md        ← skill registry — AWAITING POPULATION
│
├── spec/                              ← frozen implementation contracts
│   ├── README.md                      ← spec index + conformance rules
│   ├── SPEC-000-architecture-boundaries.md
│   ├── SPEC-001-core-data-model.md
│   ├── SPEC-002-tool-system.md
│   ├── SPEC-003-orchestration-recovery.md
│   ├── SPEC-004-planner-llm.md
│   ├── SPEC-005-harness-cli-plugins.md
│   └── SPEC-006-config-security-logging.md
│
└── documentations/                    ← authoritative product documentation
    ├── README.md                      ← docs index
    └── Agent_Harness_PRD_Developer_README.md   ← the vision, verbatim & READ-ONLY
```

---

## The Five Independent Plans

The project is partitioned into **five mutually independent workstreams** that separate
agents can execute **simultaneously**. Each plan contains **5 implementation phases**, each
phase contains **5 sub-phases** (25 sub-phases per plan; 125 project-wide).

| Plan | Workstream | Owns (future source paths) | Plan file |
|---|---|---|---|
| **P1** | Core Foundation | `agent_harness/{config,context,logging,llm}/`, `pyproject.toml`, `config.yaml`, `.env.example` | [`planning/plan-1-foundation/plan.md`](planning/plan-1-foundation/plan.md) |
| **P2** | Tool System | `agent_harness/tools/` | [`planning/plan-2-tools/plan.md`](planning/plan-2-tools/plan.md) |
| **P3** | Planning & Orchestration | `agent_harness/{planning,orchestration}/` | [`planning/plan-3-orchestration/plan.md`](planning/plan-3-orchestration/plan.md) |
| **P4** | Harness Surface | `agent_harness/{harness.py,__main__.py,__init__.py,plugins/}`, `plugins/` | [`planning/plan-4-interface/plan.md`](planning/plan-4-interface/plan.md) |
| **P5** | Quality & Delivery | `tests/conftest.py`, `tests/integration/`, `examples/`, `.github/`, repo meta & docs | [`planning/plan-5-quality/plan.md`](planning/plan-5-quality/plan.md) |

**How independence is guaranteed** (details: [`planning/README.md`](planning/README.md) § 2):

- **Disjoint file ownership** — every repository path belongs to exactly one plan
  (matrix in [SPEC-000 § 3](spec/SPEC-000-architecture-boundaries.md)). No two agents ever
  touch the same file.
- **Contract-first parallelism** — cross-plan dependencies exist only as frozen interfaces
  in `spec/`. Consumers code against specs and mocks; no plan waits on another's code.
- **Single integration window** — real modules are wired together once, after parallel
  completion (P4 composition → P5 integration suite).

---

## Specifications

`spec/` holds the binding contracts that make concurrent execution safe. Specs are
**FROZEN**: implementation must conform; changes go through Spec Change Requests only.

| ID | Covers |
|---|---|
| [SPEC-000](spec/SPEC-000-architecture-boundaries.md) | Architecture layers, file-ownership matrix, coding/testing standards, Definition of Done, change control |
| [SPEC-001](spec/SPEC-001-core-data-model.md) | `Step`, `ExecutionPlan`, `ToolResult`, `AgentError`, `ExecutionMetrics`, error-code catalog, serialization |
| [SPEC-002](spec/SPEC-002-tool-system.md) | `BaseTool` behavioral rules, `ToolRegistry`, full I/O contract for all 10 built-in tools |
| [SPEC-003](spec/SPEC-003-orchestration-recovery.md) | Orchestrator step loop, hooks, context layout & placeholders, 4-level recovery cascade, assembler, metrics rules |
| [SPEC-004](spec/SPEC-004-planner-llm.md) | `LLMClient` interface & provider rules, `Planner` interface, frozen prompt templates, plan JSON schema & validation |
| [SPEC-005](spec/SPEC-005-harness-cli-plugins.md) | Public API, `run()` lifecycle, CLI flags & exit codes, plugin discovery & isolation |
| [SPEC-006](spec/SPEC-006-config-security-logging.md) | Config schema & precedence, privacy/redaction, code sandbox layers, shell whitelist, log schema & events, report |

---

## Agent Governance & the Skill Mandate

All work in this repository is performed by declared agents following
[`.agent/agent.md`](.agent/agent.md): a standard manifest format, lifecycle, boundaries
(ten explicit prohibitions), work-product standards, and reporting duties.

The centerpiece is the **skill mandate**:

> ### Every source-code change — even a single change — must be implemented by 100%
> ### applying a skill registered in the
> ### [skill dictionary](.agent/skills/skill-dictionary.md).
>
> - No unskilled remainder is permitted: not a line, not an import, not a "trivial fix".
> - A skill used outside its declared scope, or partially applied, counts as **no skill**.
> - Missing skill ⇒ agent **stops** and files a Skill Request — never improvises.
> - Every change is cited in an append-only **Skill Ledger** and in the commit message.
>
> **The dictionary is currently empty (0 registered skills) — awaiting population via a
> subsequent prompt. Until then, all source-code work is halted project-wide.**

---

## For Agents: How to Start Work

1. Read the vision: [`documentations/Agent_Harness_PRD_Developer_README.md`](documentations/Agent_Harness_PRD_Developer_README.md).
2. Read your governance: [`.agent/agent.md`](.agent/agent.md) — then declare your **Agent Manifest** (§ 1) in your plan's Status Log.
3. Read your contracts: [`spec/README.md`](spec/README.md) + the specs your plan consumes.
4. Open your plan in [`planning/`](planning/) and follow its 5 × 5 sub-phases in order.
5. **Check the skill gate** before any edit: [`.agent/skills/skill-dictionary.md`](.agent/skills/skill-dictionary.md). Empty ⇒ stay in read/plan mode and file Skill Requests.
6. Coordinate through [`planning/README.md`](planning/README.md) (progress board, broadcasts) — never by editing another plan's files.

## For Humans: Reading Order

| # | Read | Why |
|---|---|---|
| 1 | `documentations/Agent_Harness_PRD_Developer_README.md` | The product vision (PRD + developer guide) |
| 2 | `planning/README.md` | How the work is partitioned and orchestrated |
| 3 | `.agent/agent.md` + `.agent/skills/skill-dictionary.md` | Who may change code, and under which rules |
| 4 | `spec/README.md` → SPEC-000 → the rest | The frozen contracts implementation must satisfy |
| 5 | The five `plan.md` files | Phase-by-phase execution detail |

---

## Usage

### Windows: one click

Double-click **`setup.bat`** once, add your API key to the `.env` it creates, then
double-click **`start.bat`** any time after that to launch the local web UI in your
browser. Both scripts are idempotent and leave no background service behind.
`start.bat /cli` runs tasks in the terminal instead; `start.bat /help` lists the flags.

### Local web UI

```bash
pip install "agent-harness[web]"
python -m agent_harness.web          # http://localhost:8765 — browser opens itself
```

Enter a task, watch the plan execute step by step with live status and a raw event
log, then read the assembled deliverable, the execution report, the metrics and every
file the run produced. See [`documentations/web-ui.md`](documentations/web-ui.md) for
the full guide and [`ADR-001`](documentations/adr/ADR-001-local-web-ui.md) for why it
is built this way.

```bash
# CLI (SPEC-005)
python -m agent_harness "Research the top 5 AI models, compare them, and create a PDF report"
python -m agent_harness --dry-run "..."      # inspect the plan without executing
python -m agent_harness --list-tools         # show the tool registry
```

```python
# Python API (SPEC-005)
from agent_harness import AgentHarness, Config

harness = AgentHarness(Config.from_file("./config.yaml"))
result = harness.run("Read data.csv and generate a bar chart of sales by region")
print(result.status, result.files_created, result.metrics)
```

```python
# Custom tool (SPEC-002): implement BaseTool, drop the file into plugins/
```

---

## Roadmap

| Stage | Content | Status |
|---|---|---|
| Foundation | Vision ingested; specs frozen; 5 plans authored; agent governance + skill mandate established | ✅ Done |
| Skill population | 50 skill definitions registered under `.agent/skill-dictionary/` | ✅ Done |
| Parallel implementation | P1–P4 executed concurrently by four agents under skill enforcement; P5 not started | 🟡 P1–P4 done (100/125 sub-phases) |
| Integration window | Composition swap (**I1 done** — commit `993fdac`), full test suite (I2–I3), defect routing (I4) | 🟡 I1 done; I2–I5 pending P5 |
| Local web UI & Windows on-ramp | `agent_harness.web` (FastAPI + SSE), `setup.bat`, `start.bat` — PRD G8 | ✅ Done (plan 6) |
| v0.1.0 release | CI green, security review, demos, tag (I5) | ⬜ |

Progress is tracked on the board in [`planning/README.md`](planning/README.md) § 5.

---

## License

MIT (planned — `LICENSE` file is delivered by Plan 5). Architecture inspired by
[Arena.ai](https://arena.ai) Agent Mode's execution model.
