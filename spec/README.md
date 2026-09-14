# Specification Index — Agent Harness

> **Status:** FOUNDATION PHASE — these specs are the single source of truth for all
> implementation work. No implementation source code exists yet.

The `spec/` directory contains the binding contracts that allow the five planning
workstreams (see [`../planning/README.md`](../planning/README.md)) to be executed
**concurrently and independently** by separate agents. Every plan codes against these
specs — never against another plan's in-progress source files.

---

## Spec Catalog

| ID | Document | Scope | Primary Owner (Plan) | Consumers |
|---|---|---|---|---|
| SPEC-000 | [Architecture, Boundaries & Conformance](SPEC-000-architecture-boundaries.md) | Module map, file-ownership matrix, conformance & testing rules | Orchestrator (shared) | All plans |
| SPEC-001 | [Core Data Model](SPEC-001-core-data-model.md) | `Step`, `ExecutionPlan`, `StepStatus`, `TaskPriority`, `AgentError`, `ExecutionMetrics` | Plan 1 | Plans 2, 3, 4, 5 |
| SPEC-002 | [Tool System](SPEC-002-tool-system.md) | `BaseTool`, `ToolResult`, `ToolRegistry`, built-in tool I/O catalog | Plan 2 | Plans 3, 4, 5 |
| SPEC-003 | [Orchestration, Recovery & Assembly](SPEC-003-orchestration-recovery.md) | POEA loop, dependency resolution, recovery cascade, assembler | Plan 3 | Plans 4, 5 |
| SPEC-004 | [Planner & LLM Client](SPEC-004-planner-llm.md) | Planning/re-planning prompts, plan JSON schema, `LLMClient` interface | Plan 3 (planner), Plan 1 (LLM client) | Plans 2, 4, 5 |
| SPEC-005 | [Harness API, CLI & Plugins](SPEC-005-harness-cli-plugins.md) | `AgentHarness`, `HarnessResult`, CLI contract, plugin discovery | Plan 4 | Plan 5 |
| SPEC-006 | [Configuration, Security & Observability](SPEC-006-config-security-logging.md) | `config.yaml` schema, env vars, sandbox rules, log schema, reports | Plan 1 | All plans |

---

## Conformance Rules (Binding)

1. **Spec-first.** If implementation reveals a spec gap or defect, the agent MUST stop,
   record the issue in its plan's status log, and request a spec change through the
   orchestrator (`planning/README.md` § Change Control). Agents MUST NOT unilaterally
   deviate from a spec, and MUST NOT edit files in `spec/`.
2. **Contract stability.** Interfaces marked **FROZEN** in a spec may not change after
   implementation begins without orchestrator approval, because other plans build
   against them in parallel.
3. **Mock-first development.** Where a plan consumes another plan's module (e.g., Plan 3
   consumes `ToolRegistry`), it develops and tests against a mock that satisfies the
   spec exactly. Integration happens only in Plan 4 (composition) and Plan 5
   (integration tests).
4. **Skill enforcement.** Every source-code change made while implementing any spec
   requires an applicable skill from
   [`.agent/skills/skill-dictionary.md`](../.agent/skills/skill-dictionary.md).
   See `.agent/agent.md` § 6 for the full rule.
5. **Traceability.** Every module, class, and public function implemented must cite the
   spec section it realizes (docstring reference, e.g. `Spec: SPEC-002 §3.1`).

---

## Relationship to the Vision

The authoritative product vision is
[`../documentations/Agent_Harness_PRD_Developer_README.md`](../documentations/Agent_Harness_PRD_Developer_README.md)
(copied verbatim; never modified). These specs **refine and partition** that vision into
implementable contracts. In case of conflict: vision wins on *product intent*; specs win
on *interface detail and module boundaries*.
