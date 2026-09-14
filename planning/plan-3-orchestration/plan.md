# Plan 3 — Planning & Orchestration

**Plan ID:** P3 · **Workstream:** Planner, Orchestrator, Dependency Resolution, Recovery, Assembler
**Execution:** independent — may run concurrently with P1, P2, P4, P5 · **Sub-phases:** 25 (5 phases × 5)

---

## 0. Plan Header

| Field | Value |
|---|---|
| Mission | Deliver the L2 cognition layer: LLM planning + re-planning, the POEA execution loop, DAG ordering, the 4-level recovery cascade, and final output assembly — per SPEC-003 and SPEC-004 § 2–5. |
| Owned paths | SPEC-000 § 3.3 — `agent_harness/planning/`, `agent_harness/orchestration/`, `tests/test_planner.py`, `tests/test_orchestrator.py`, `tests/test_dependency.py`, `tests/test_recovery.py`, `tests/test_assembler.py` |
| Consumed specs | SPEC-000, SPEC-001 (data model), SPEC-002 § 1–2 (tool + registry contracts), SPEC-003 (owns), SPEC-004 § 2–5 (owns planner; consumes LLM client § 1), SPEC-006 § 1/6 (config, log events) |
| Produces for others | `Planner` (P4); `Orchestrator` + `ExecutionHooks` (P4 progress rendering); `RecoveryManager` (P4/P5); `Assembler` + `AssemblyResult` (P4); `resolve_execution_order` (P5 integration) |
| Parallel-work rule | P1's data model and P2's registry may not exist yet → use **spec-shaped fakes** declared in this plan's test files (`FakeRegistry`, `FakeLLMClient`, `FakeTool`, `FakeConfig`) matching SPEC-001/002/004 exactly. Never import from `agent_harness.tools`, `config`, `llm`, `context`, or `logging` concrete modules; accept them injected. |
| Skill gate | ⛔ No source change until an active skill covers it (`.agent/agent.md` § 6). Dictionary currently empty → status: gated. |

**Independence declaration.** This plan touches only its owned paths. Data types arrive via
constructor injection and spec-defined duck types, so the full POEA loop is buildable and
testable while P1/P2 are still in flight.

---

## Phase 1 — Plan Parsing, Prompts & Validation

> Outcome: correct, validated `ExecutionPlan` objects from raw LLM output, with no execution logic yet.

### Sub-phase 1.1 — Prompt templates
- **Tasks:** author `planning/prompts.py` containing `PLANNING_SYSTEM_PROMPT` and `REPLAN_PROMPT` **verbatim** from SPEC-004 § 3.1/3.2, plus the additive `TOOL_SELECTION_PROMPT` (§ 3.3) and the `render_tool_descriptions(available_tools)` helper producing the deterministic `- name: description [capabilities: …]` list.
- **Deliverable:** `prompts.py`.
- **Exit criteria:** character-for-character diff test against the spec strings; rendering is deterministic across runs (sorted/insertion order preserved).

### Sub-phase 1.2 — Plan JSON parsing & normalization
- **Tasks:** `parse_plan(payload, config) -> ExecutionPlan` per SPEC-004 § 4.2: fence stripping, canonical `step_i` ID assignment before dependency resolution, integer/string dependency normalization, enum defaults, unknown-key tolerance.
- **Deliverable:** parser inside `planning/planner.py`.
- **Exit criteria:** golden-fixture tests: valid plan, fenced plan, integer deps, missing optional fields, unknown keys.

### Sub-phase 1.3 — Validation rules V1–V7
- **Tasks:** implement SPEC-004 § 4.3 checks; raise `AgentError(code="PLAN_VALIDATION_FAILED")`; V7 (zero critical steps) emits a warning, not an error; record `plan.context["unresolved_hints"]`.
- **Deliverable:** `validate_plan()`.
- **Exit criteria:** one failing + one passing test per rule; cycle detection reuses the Phase-3 topological sorter in validation mode.

### Sub-phase 1.4 — Test doubles for the cognition layer
- **Tasks:** create `tests/_p3_doubles.py` (owned by this plan): `FakeLLMClient` (scripted `complete`/`complete_json`, usage counters, failure injection), `FakeTool`/`FailingTool`/`CountingTool`, `FakeRegistry` (dict-backed, spec-shaped), `FakeConfig`, `FakeLogger`, `FakeStore`.
- **Deliverable:** deterministic double kit.
- **Exit criteria:** doubles satisfy the frozen contracts; whole suite runs with no network, no real LLM, no sleeping.

### Sub-phase 1.5 — Parser robustness sweep
- **Tasks:** handle real-world LLM variance: trailing prose around JSON, single-quoted pseudo-JSON (documented rejection), duplicate step keys, extremely long descriptions (truncate to a documented cap), empty `steps`.
- **Deliverable:** hardened parser + documented limits.
- **Exit criteria:** adversarial fixture set passes; each rejection yields a spec error code, never a raw `JSONDecodeError`.

---

## Phase 2 — Planner

> Outcome: prompt → validated plan, plus tool selection and step re-planning entry points.

### Sub-phase 2.1 — `Planner` skeleton & `plan()`
- **Tasks:** implement the FROZEN interface SPEC-004 § 2; `plan()` composes the system prompt with rendered tool descriptions + user prompt, calls `llm_client.complete_json(schema_hint=…)`, parses, validates, returns.
- **Deliverable:** `planning/planner.py`.
- **Exit criteria:** happy path with `FakeLLMClient`; prompt content asserted (tools listed, rules present).

### Sub-phase 2.2 — Repair & failure semantics
- **Tasks:** rely on `complete_json` repair round (SPEC-004 § 1.2 C3); on final parse failure raise `AgentError(PLAN_PARSE_FAILED)`; enforce the token/round budget of SPEC-004 § 5 (≤ 1 round + 1 repair).
- **Deliverable:** bounded-failure planning.
- **Exit criteria:** call-count assertions prove the budget; both failure codes reachable in tests.

### Sub-phase 2.3 — Context-aware planning
- **Tasks:** accept optional `context` to seed `plan.context["variables"]` (e.g. user-supplied `data_file`); include a bounded context summary in the planning prompt when variables exist (≤ 2000 chars).
- **Deliverable:** context-seeded plans.
- **Exit criteria:** test: variables propagate into `plan.context`; prompt grows only within the bound.

### Sub-phase 2.4 — `select_tool()`
- **Tasks:** implement per SPEC-004 § 2: temperature 0.0, single round no repair, parse `{"tool": name|null}`, validate the name against `available_tools`, return `None` when unusable.
- **Deliverable:** runtime tool selection for the orchestrator.
- **Exit criteria:** tests: valid pick, hallucinated name → `None`, null response → `None`.

### Sub-phase 2.5 — `replan_step()`
- **Tasks:** implement per SPEC-004 § 2 + § 3.2: build `attempt_history` and bounded `context_summary` (500 chars/step, ≤ 4000 total), parse into `list[Step]`, assign fresh IDs suffixed `r<n>`, inherit priority from the failed step, return `[]` when the model cannot help.
- **Deliverable:** re-planning path used by recovery Level 3.
- **Exit criteria:** tests: alternative produced, empty-list path, bound enforcement on context summary.

---

## Phase 3 — Orchestrator Core Loop

> Outcome: the POEA runtime executing a plan step-by-step with dependency ordering and context flow.

### Sub-phase 3.1 — `resolve_execution_order()`
- **Tasks:** implement SPEC-003 § 8: Kahn BFS with `deque`, stable tie-break by original index, dangling-dependency warning, `ValueError("Circular dependency detected in execution plan")`.
- **Deliverable:** `orchestration/dependency.py`.
- **Exit criteria:** vision-derived tests: linear chain, diamond, cycle raises, dangling dep ignored, determinism across repeated calls.

### Sub-phase 3.2 — `Orchestrator` skeleton & step-loop scaffolding
- **Tasks:** implement the FROZEN constructor and `execute(plan)` signature (SPEC-003 § 2); loop skeleton per § 3 with status transitions and timings; inject registry/config/llm/planner/store/logger/hooks — all optional except registry+config.
- **Deliverable:** `orchestration/orchestrator.py`.
- **Exit criteria:** a two-step all-success fake plan executes in dependency order; every step reaches a terminal status with timestamps.

### Sub-phase 3.3 — Tool resolution & input preparation
- **Tasks:** § 3 steps 2–3: hint → `tool_name` → LLM `select_tool` fallback → `TOOL_NOT_FOUND`; placeholder resolution engine for `{{step:id}}`, `{{step:id.output}}`, `{{var:name}}`, `{{config:path}}`, `{{prompt}}` per SPEC-003 § 4.2 (whole-value vs embedded substitution, unresolved → warning + literal).
- **Deliverable:** resolution + substitution.
- **Exit criteria:** placeholder matrix tests (each pattern, nested dict/list, type preservation, unresolved case); unresolvable tool fails the step and enters recovery.

### Sub-phase 3.4 — Dependency gating, validation short-circuit & guards
- **Tasks:** § 3 steps 1, 4, 8: unmet-dependency skip rule; `validate_input` rejection skips Level 1 (SPEC-003 § 5 note); `max_steps` and `step_timeout` guards; `files_created` recording after successful `file_write`.
- **Deliverable:** complete guard set.
- **Exit criteria:** tests: skipped-dependency chain, timeout (injected clock), max_steps truncation with remaining steps marked SKIPPED.

### Sub-phase 3.5 — Hooks, logging & context writes
- **Tasks:** fire all `ExecutionHooks` at the right moments with exception isolation (SPEC-003 § 2.1); emit SPEC-006 § 6.1 events (`step_started/completed/failed/skipped`, `tool_executed`, `output_written`); write `context["step_results"]` entries in the exact § 4.1 shape.
- **Deliverable:** observable orchestrator.
- **Exit criteria:** `FakeLogger` captures the full event sequence for a mixed success/failure plan; a raising hook does not abort execution; context entry shape asserted key-by-key.

---

## Phase 4 — Recovery Cascade

> Outcome: the vision's self-healing behavior — retry → fallback → re-plan → escalate (US-3).

### Sub-phase 4.1 — `RecoveryManager` skeleton & Level 1 retry
- **Tasks:** implement the interface of SPEC-003 § 5; exponential/linear/fixed backoff from config using the **injected `sleep`**; status transitions RUNNING → RETRYING → RUNNING; `context["errors"]` append per attempt.
- **Deliverable:** `orchestration/recovery.py`.
- **Exit criteria:** recorded sleep sequence matches `base * 2^(n-1)` (and the other two policies); retry count never exceeds `max_retries`.

### Sub-phase 4.2 — Level 2 fallback tools
- **Tasks:** iterate `step.fallback_tools` in order; skip unregistered tools; same prepared input; on validation mismatch skip that fallback without counting an attempt; on success set `step.tool_name` and `metadata["recovered_via"]="fallback:<name>"`.
- **Deliverable:** fallback cascade.
- **Exit criteria:** tests: first-fallback success, second-after-first-unregistered, all-fallbacks-fail → Level 3, validation-mismatch skip.

### Sub-phase 4.3 — Level 3 LLM re-planning
- **Tasks:** invoke `planner.replan_step(...)`, execute replacement steps in order through the same tool-resolution path, first success recovers the original step; honor `config.execution.enable_replan` and missing-planner skip; log `recovery_attempted` with `level=3`.
- **Deliverable:** re-plan integration.
- **Exit criteria:** tests: successful alternative, empty alternative list, replan disabled, planner absent.

### Sub-phase 4.4 — Level 4 escalation by priority
- **Tasks:** implement the exact CRITICAL/HIGH/MEDIUM/LOW semantics of SPEC-003 § 5 Level 4, including `abort_on_critical_failure` raise vs plan-status FAILED, degraded marking for HIGH, notes for MEDIUM, silence for LOW.
- **Deliverable:** escalation policy.
- **Exit criteria:** 4 × 2 (abort flag) priority matrix test; error chain recorded in `context["errors"]`.

### Sub-phase 4.5 — Recovery matrix & skip rules
- **Tasks:** wire the "skip Level 1" conditions (`retryable == False`, `SANDBOX_VIOLATION`, input-validation failure); full-cascade orchestration test reproducing US-3 acceptance criteria end-to-end with fakes.
- **Deliverable:** verified cascade.
- **Exit criteria:** a single test walks Level 1 → 2 → 3 → 4 with recorded attempts; each US-3 criterion maps to an assertion.

---

## Phase 5 — Assembler, Metrics & Handoff

> Outcome: coherent final deliverables (even when degraded) and verified conformance.

### Sub-phase 5.1 — `Assembler` collection & status
- **Tasks:** implement SPEC-003 § 6 rules 1–4: ordered SUCCESS-output collection, `completed`/`partial`/`failed` determination, `files_created` propagation.
- **Deliverable:** `orchestration/assembler.py`.
- **Exit criteria:** status-decision truth table test (file deliverable present/absent × steps skipped/failed).

### Sub-phase 5.2 — Template synthesis mode (LLM-free guarantee)
- **Tasks:** deterministic markdown assembly: one section per successful step, notes for skipped/degraded, error chain appendix; must work with `llm_client=None`.
- **Deliverable:** template mode.
- **Exit criteria:** golden-output test with no LLM present; notes always appended (rule 6).

### Sub-phase 5.3 — LLM synthesis mode with bounded context
- **Tasks:** rule 5: single bounded LLM call (truncate step outputs to fit `config.llm.max_tokens`), fall back to template mode on any LLM failure; `output_format` handling (`text`/`markdown`/`json`/`file`).
- **Deliverable:** synthesis mode.
- **Exit criteria:** truncation bound asserted via fake client prompt length; LLM-failure fallback test.

### Sub-phase 5.4 — `ExecutionMetrics` computation
- **Tasks:** implement `from_plan(plan, timings, llm_usage)` per the SPEC-003 § 7 rule table (recovered-step definition, wall-clock duration, token/cost accumulation, unique tool order).
- **Deliverable:** metrics builder (container type owned by P1; computation owned here).
- **Exit criteria:** each field rule has a test; numbers verified against a hand-computed fixture.

### Sub-phase 5.5 — End-to-end POEA simulation & handoff
- **Tasks:** full-loop test with fakes: prompt → plan → execute (incl. one recovery) → assemble → metrics; verify all SPEC-006 events emitted in order; coverage ≥ 80 %; ruff/mypy clean; Handoff Note for P4 (composition wiring order, hooks usage for Rich progress, `--no-fallback` mapping to `enable_replan`) and P5 (integration scenarios, deterministic doubles available for reuse).
- **Deliverable:** P3 conformance report + handoff.
- **Exit criteria:** SPEC-000 § 6 Definition of Done satisfied for P3.

---

## Status Log (owner-maintained)

### Agent Manifest
```yaml
# PASTE the manifest from .agent/agent.md § 1 here when the plan is claimed
```

### Phase Execution Log
| Sub-phase | State | Skill ID(s) | Note |
|---|---|---|---|
| 1.1 – 5.5 (25 rows) | pending | — | gated: skill dictionary empty |

### Skill Ledger
| Timestamp (ISO) | Sub-phase | Files | Skill ID(s) | Change summary | Gates passed |
|---|---|---|---|---|---|
| — | — | — | — | _no source changes permitted yet_ | — |

### Spec/Skill Change Requests
_None filed._

### Handoff Note
_Written at Phase 5.5._
