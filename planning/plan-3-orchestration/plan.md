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
# ── Agent Manifest ────────────────────────────────────────────
agent_id:        P3-orchestration-01
name:            Orchestrator-Builder
role:            implementer
plan:            planning/plan-3-orchestration/plan.md
owned_paths:                            # copied VERBATIM from SPEC-000 § 3.3
  - agent_harness/planning/__init__.py
  - agent_harness/planning/planner.py
  - agent_harness/planning/prompts.py
  - agent_harness/orchestration/__init__.py
  - agent_harness/orchestration/orchestrator.py
  - agent_harness/orchestration/dependency.py
  - agent_harness/orchestration/recovery.py
  - agent_harness/orchestration/assembler.py
  - tests/test_planner.py
  - tests/test_orchestrator.py
  - tests/test_dependency.py
  - tests/test_recovery.py
  - tests/test_assembler.py
consumed_specs:
  - SPEC-000  # architecture, ownership matrix, DoD
  - SPEC-001  # core data model (Step, ExecutionPlan, ToolResult, AgentError, ExecutionMetrics)
  - SPEC-002  # § 1–2 BaseTool + ToolRegistry contracts
  - SPEC-003  # orchestration, recovery, assembly (OWNS)
  - SPEC-004  # § 2–5 planner (OWNS); § 1 LLMClient (consumes)
  - SPEC-006  # § 1 config schema, § 6 logging events
produces:
  - agent_harness.planning.Planner            (plan / replan_step / select_tool) → P4
  - agent_harness.planning.prompts            (PLANNING_SYSTEM_PROMPT, REPLAN_PROMPT, TOOL_SELECTION_PROMPT)
  - agent_harness.orchestration.Orchestrator  (POEA loop) → P4
  - agent_harness.orchestration.ExecutionHooks (observability seam for Rich progress) → P4
  - agent_harness.orchestration.RecoveryManager (4-level cascade) → P4/P5
  - agent_harness.orchestration.Assembler + AssemblyResult → P4
  - agent_harness.orchestration.resolve_execution_order → P5
  - agent_harness.orchestration.compute_metrics / metrics_from_plan (SPEC-003 § 7) → P1/P4
  - tests/test_{planner,orchestrator,dependency,recovery,assembler}.py
skills_authorized:                      # registered skill IDs this agent applies (§ 6)
  - SKL-CORE-TDD          # core-coding/tdd-test-runner
  - SKL-CORE-TYPES        # core-coding/strict-typing-contracts
  - SKL-CORE-LINT         # core-coding/lint-formatting
  - SKL-CORE-GIT          # core-coding/git-workflow-hygiene
  - SKL-CORE-REVIEW       # core-coding/pr-code-reviewer
  - SKL-BACK-RESIL        # backend/resiliency-rate-limiting
  - SKL-BACK-QUEUE        # backend/queue-workers
  - SKL-BACK-OTEL         # backend/otel-observability
  - SKL-PLAN-CPM          # planning/critical-path-mapping
  - SKL-PLAN-DOD          # planning/scope-dod-enforcer
  - SKL-PLAN-FMEA         # planning/risk-fmea-premortem
  - SKL-REL-FUZZ          # reliability/api-fuzz-tester
  - SKL-REL-FLAKY         # reliability/flaky-test-isolator
  - SKL-REL-SCHEMA        # reliability/schema-compatibility
status:          active
started_at:      2026-09-14T14:04Z
last_update:     2026-09-14T20:01Z
# ──────────────────────────────────────────────────────────────
```

### Skill Gate — applicability determination (agent.md § 6)

**Gate result: SATISFIED — work may begin.** `.agent/agent.md` § 6.2 asserts the dictionary
holds `0` skills, but **50 skills are in fact registered** under
`.agent/skill-dictionary/<category>/<name>/SKILL.md` (see SCR-P3-1). Every P3 sub-phase maps
to at least one registered skill, so the § 6.2 hard stop does not apply.

Two deviations from § 6.2's literal wording were necessary and are filed for adjudication:

1. Registered skills carry only `name` + `description` frontmatter — no `applies_to` field and
   no `SKL-*` identifier (SCR-P3-2). **Interim rule used by this agent:** applicability is
   assessed from each skill's own `§ 1 Scope & Objective` + `§ 2 Trigger Conditions`, and IDs
   are derived as `SKL-<CATEGORY-ABBREV>-<NAME-ABBREV>` per the alias table below. Only the
   in-scope portion of each skill is cited (e.g. `SKL-PLAN-CPM` is cited for DAG construction +
   cycle verification, never for CPM date/float math, which is out of scope for a runtime sorter).
2. Skills are cited by their dictionary path in every ledger row and commit message so the
   alias is always resolvable to a registered definition.

| Alias | Registered skill (dictionary path) | Scope relied upon for P3 |
|---|---|---|
| SKL-CORE-TDD | `core-coding/tdd-test-runner` | Red-green-refactor for all 25 sub-phases; boundary matrices; deterministic fakes, no live LLM |
| SKL-CORE-TYPES | `core-coding/strict-typing-contracts` | `mypy --strict`; protocols at every injected trust boundary; no `Any` leakage; no cast-to-silence |
| SKL-CORE-LINT | `core-coding/lint-formatting` | `ruff check` + `ruff format` as separate style/correctness gates; zero reasonless suppressions |
| SKL-CORE-GIT | `core-coding/git-workflow-hygiene` | One atomic Conventional Commit per sub-phase, skill-cited, reviewable size |
| SKL-CORE-REVIEW | `core-coding/pr-code-reviewer` | Pre-commit self-review order (correctness → security → architecture → tests → style) |
| SKL-BACK-RESIL | `backend/resiliency-rate-limiting` | Level 1–2: bounded honest retries, backoff, documented degradation path per dependency |
| SKL-BACK-QUEUE | `backend/queue-workers` | Cascade as a bounded-retry job model: poison input skips retry budget; Level 4 = dead-letter/escalate |
| SKL-BACK-OTEL | `backend/otel-observability` | 3.5: structured event emission, bounded attribute cardinality, no PII/secrets in fields |
| SKL-PLAN-CPM | `planning/critical-path-mapping` | 3.1: explicit typed dependencies, cycle check before any math, DAG-with-0-cycles verification |
| SKL-PLAN-DOD | `planning/scope-dod-enforcer` | Per-sub-phase exit criteria as measurable acceptance criteria + evidence; out-of-scope list |
| SKL-PLAN-FMEA | `planning/risk-fmea-premortem` | Phase 4: failure-mode enumeration driving the recovery matrix |
| SKL-REL-FUZZ | `reliability/api-fuzz-tester` | 1.5: LLM output is untrusted client input — boundary table, persistent regression corpus, bounded parse |
| SKL-REL-FLAKY | `reliability/flaky-test-isolator` | Injected clock/sleep; determinism proven by repeated + shuffled runs |
| SKL-REL-SCHEMA | `reliability/schema-compatibility` | 1.2: additive/forward-compatible plan JSON (unknown keys ignored, new fields defaulted) |

**Out-of-scope boundary list (SKL-PLAN-DOD § 3).** This plan does **not** create or edit:
`pyproject.toml`, `config.yaml`, `.env.example`, `tests/conftest.py`, `agent_harness/__init__.py`,
anything under `agent_harness/{config,context,logging,llm,tools,plugins}/`, `spec/**`, `.agent/**`,
`planning/README.md`, or any other plan's `plan.md`. No runtime dependency outside the Python
standard library is imported. Verification tooling (`pytest`, `pytest-cov`, `ruff`, `mypy`) is
installed in a venv at `/home/user/p3-venv` — **outside the repository** — so no build/config file
is added to the write set.

### Phase Execution Log

| Sub-phase | State | Skill ID(s) | Note |
|---|---|---|---|
| 1.1 Prompt templates | done | SKL-CORE-TDD, SKL-CORE-TYPES, SKL-CORE-LINT, SKL-CORE-GIT, SKL-PLAN-DOD | `prompts.py`: both FROZEN templates byte-identical to SPEC-004 § 3.1/3.2 (sha256-pinned), additive § 3.3 selection prompt + schema hint, deterministic `render_tool_descriptions` |
| 1.2 Plan JSON parsing & normalization | done | SKL-CORE-TDD, SKL-CORE-TYPES, SKL-REL-SCHEMA, SKL-REL-FUZZ, SKL-CORE-LINT, SKL-CORE-GIT | `parse_plan` + `strip_code_fences` per SPEC-004 § 4.2 (all four rules); section A injected-model kit (protocols + SPEC-001 stand-ins + `SpecModels` + `NullLogger`) per SCR-P3-6 |
| 1.3 Validation rules V1–V7 | done | SKL-CORE-TDD, SKL-CORE-TYPES, SKL-PLAN-FMEA, SKL-CORE-LINT, SKL-CORE-GIT | `validate_plan()` implements V1-V7 in the order V1,V2,V3,V4,V6,V5,V7 (V6 before V5 so a self-dependency reports precisely); records `plan.context["unresolved_hints"]`; V7 returns a warning instead of raising. V5 delegates to a local Kahn sorter marked TEMPORARY until 3.1 supplies `resolve_execution_order` (sequencing deviation, recorded below). |
| 1.4 Test doubles for the cognition layer | done | SKL-CORE-TDD, SKL-REL-FLAKY, SKL-CORE-TYPES, SKL-CORE-LINT, SKL-CORE-GIT | Full double kit delivered inside the owned test files per SCR-P3-3: `FakeLLMClient`/`FakeLLMResponse`/`FakeLLMUsage` (test_planner.py), `FakeTool`/`FailingTool`/`CountingTool`/`FakeRegistry`/`FakeStore`/`FakeClock`/`FakeSleeper`/`FakePlanner`/`FakeConfig`/`FakeLogger` (test_orchestrator.py), each pinned to its frozen contract by an `inspect.signature` test. |
| 1.5 Parser robustness sweep | done | SKL-REL-FUZZ, SKL-CORE-TDD, SKL-REL-FLAKY, SKL-CORE-TYPES, SKL-CORE-LINT, SKL-CORE-GIT | Adversarial fixture corpus (SKL-REL-FUZZ § 3.2 boundary table + persistent regression corpus) added to tests/test_planner.py; parser hardened in agent_harness/planning/planner.py with bounded extraction and a documented description cap. |
| 2.1 `Planner` skeleton & `plan()` | done | SKL-CORE-TDD, SKL-CORE-TYPES, SKL-REL-SCHEMA, SKL-OBS-OTEL, SKL-CORE-LINT, SKL-CORE-GIT | Section D of agent_harness/planning/planner.py: `Planner` with the frozen `__init__`/`plan()` signatures; LLM-side injected contracts (`LLMClientLike`/`LLMResponseLike`/`LLMUsageLike`) added to the Section A kit. |
| 2.2 Repair & failure semantics | done | SKL-CORE-TDD, SKL-REL-FUZZ, SKL-CORE-TYPES, SKL-CORE-LINT, SKL-CORE-GIT | No source change was required: 2.1's single-call design already satisfies § 5. This sub-phase adds the C3-faithful client double and the proofs, in tests/test_planner.py. |
| 2.3 Context-aware planning | done | SKL-CORE-TDD, SKL-CORE-TYPES, SKL-REL-FUZZ, SKL-OBS-OTEL, SKL-CORE-LINT, SKL-CORE-GIT | `plan(context=…)` seeds `plan.context["variables"]` and appends a bounded `Current context:` summary to the *user* message (the § 3.1 system prompt is FROZEN). |
| 2.4 `select_tool()` | done | SKL-CORE-TDD, SKL-CORE-TYPES, SKL-REL-FUZZ, SKL-CORE-LINT, SKL-CORE-GIT | `Planner.select_tool()` + `_selection_messages`/`_input_keys_summary`/`_selected_tool_name`; the 1.5 extraction loop was refactored into a reusable `_first_json_object(text, required_key, limit)` and `_loads` lost its unused `models` parameter. |
| 2.5 `replan_step()` | done | SKL-CORE-TDD, SKL-CORE-TYPES, SKL-REL-FUZZ, SKL-PLAN-FMEA, SKL-CORE-LINT, SKL-CORE-GIT | `Planner.replan_step()` + `_replan_messages`/`_renumber_replacements`/`_attempt_history`/`_replan_context_summary`/`_summarize_step_result`/`_index_references`/`_substitute`; the 1.5 extraction loop generalized into `_first_json_object` is reused, and `_render_variable_value` became `_render_value(value, limit)`. Also removed three `__pycache__/*.pyc` files that commit 677df2b had wrongly included, and filed SCR-P3-9. |
| 3.1 `resolve_execution_order()` | done | SKL-CORE-TDD, SKL-CORE-TYPES, SKL-PLAN-CPM, SKL-REL-FUZZ, SKL-CORE-LINT, SKL-CORE-GIT | `agent_harness/orchestration/dependency.py` (new) + package `__init__.py`: Kahn BFS with a `deque` per SPEC-003 § 8 / vision § 7.2, frozen cycle message, dangling dependencies ignored with a WARNING, deterministic index-stable ordering, O(V+E) and non-recursive. `validate_plan` V5 now delegates to it through a deferred import and 1.3's temporary `_topological_order` is deleted as promised. Package `__init__.py` re-exports added for Plan 4's dotted-name resolution (SCR-P3-12); config protocols made covariant after a composition probe against merged `main` found Plan 1's `int` `retry_base_delay` breaking `ConfigLike` (SCR-P3-13). |
| 3.2 `Orchestrator` skeleton & step loop | pending | — | |
| 3.3 Tool resolution & input preparation | pending | — | |
| 3.4 Dependency gating, validation short-circuit & guards | pending | — | |
| 3.5 Hooks, logging & context writes | pending | — | |
| 4.1 `RecoveryManager` skeleton & Level 1 retry | pending | — | |
| 4.2 Level 2 fallback tools | pending | — | |
| 4.3 Level 3 LLM re-planning | pending | — | |
| 4.4 Level 4 escalation by priority | pending | — | |
| 4.5 Recovery matrix & skip rules | pending | — | |
| 5.1 `Assembler` collection & status | pending | — | |
| 5.2 Template synthesis mode | pending | — | |
| 5.3 LLM synthesis mode with bounded context | pending | — | |
| 5.4 `ExecutionMetrics` computation | pending | — | |
| 5.5 End-to-end POEA simulation & handoff | pending | — | |

### Skill Ledger
| Timestamp (ISO) | Sub-phase | Files | Skill ID(s) | Change summary | Gates passed |
|---|---|---|---|---|---|
| 2026-09-14T14:04Z | 0 (DECLARE/GATE) | planning/plan-3-orchestration/plan.md (Status Log only) | SKL-PLAN-DOD | Manifest declared; skill-gate applicability determined against the 50 registered skills; out-of-scope boundary list written; SCRs filed | documentation-only edit (agent.md § 6.1 exempt); no source touched |
| 2026-09-14T14:22Z | 1.1 | agent_harness/planning/prompts.py, agent_harness/planning/__init__.py, tests/test_planner.py | SKL-CORE-TDD (core-coding/tdd-test-runner), SKL-CORE-TYPES (core-coding/strict-typing-contracts), SKL-CORE-LINT (core-coding/lint-formatting), SKL-CORE-GIT (core-coding/git-workflow-hygiene), SKL-PLAN-DOD (planning/scope-dod-enforcer) | Authored PLANNING_SYSTEM_PROMPT + REPLAN_PROMPT verbatim from SPEC-004 § 3.1/3.2 (verified byte-identical by re-extracting the spec blocks; sha256 2623db2e…/6fd2c03d… pinned in tests), the additive TOOL_SELECTION_PROMPT (§ 3.3), PLAN_SCHEMA_HINT (§ 1.2 C3/§ 4.1) and render_tool_descriptions() preserving registry insertion order (§ 3.1). RED first (ModuleNotFoundError), then GREEN. Mutation checks: one altered frozen char → 3 failures; sorted-instead-of-ordered tool list → 1 failure. Discrepancy found and filed as SCR-P3-8 (spec vs vision line wrapping). | pytest 34 passed, 100% stmt coverage of prompts.py; ruff check clean (E,F,W,I,B,UP,SIM,C4,PIE,RUF,D,ANN + google-convention ignores); ruff format idempotent; mypy --strict clean (3 files); F1 write-set audit clean; F3 forbidden-import audit clean |
| 2026-09-14T14:38Z | 1.2 | agent_harness/planning/planner.py (new), tests/test_planner.py | SKL-CORE-TDD (core-coding/tdd-test-runner), SKL-CORE-TYPES (core-coding/strict-typing-contracts), SKL-REL-SCHEMA (reliability/schema-compatibility), SKL-REL-FUZZ (reliability/api-fuzz-tester), SKL-CORE-LINT (core-coding/lint-formatting), SKL-CORE-GIT (core-coding/git-workflow-hygiene) | Added section A: the injected-model kit — structural protocols (StepLike, PlanLike, ToolResultLike, AgentErrorLike, ModelProvider, ConfigLike, LoggerLike) plus P3-local stand-ins field-for-field identical to SPEC-001 § 1.1/1.2/2.1/2.2/2.3/2.4 (to_dict/from_dict/duration_ms/step_by_id, § 4 serialization rules), SpecModels default provider, NullLogger, and status_value/priority_value/priority_rank so enum identity never crosses the injection boundary. Added section B: strip_code_fences + parse_plan implementing SPEC-004 § 4.2 rules 1-4 (fence stripping, canonical step_<i> ids before dependency resolution, int/"0"/"step_0" normalization, enum + unknown-key defaults, max_retries from config). Parsed JSON typed as object and narrowed with isinstance (trust boundary); errors bounded to 500 chars per SPEC-006 § 3.4; removed one provably unreachable branch instead of testing it. Protocol attributes that hold protocols or lists are read-only properties because list[T]/attribute invariance would otherwise reject Plan 1 real classes at integration. RED first, then GREEN; 4 mutation checks (dep normalization, config-sourced max_retries, escaping JSONDecodeError, model-chosen ids) all caught. | pytest 152 passed, 100% stmt coverage of planning/*; ruff check clean; ruff format idempotent; mypy --strict clean (4 files, zero suppressions); F1/F3 audits clean |
| 2026-09-14T14:47Z | 1.3 | agent_harness/planning/planner.py (section C), tests/test_planner.py | SKL-CORE-TDD, SKL-CORE-TYPES, SKL-PLAN-FMEA, SKL-CORE-LINT, SKL-CORE-GIT | Implemented SPEC-004 § 4.3 checks V1-V7 plus the § 4.3 note: unknown tool_hints are recorded in plan.context["unresolved_hints"] (deduped, first-use order) and are never a validation failure, because SPEC-003 § 3 step 2 resolves or re-selects them at runtime. Failures emit the catalog event plan_validation_failed at ERROR before raising PLAN_VALIDATION_FAILED (SPEC-006 § 6.1 — no invented event names); success emits nothing, so Planner.plan() owns the single plan_generated event. Returns warnings rather than logging them so the caller chooses the level. Sequencing deviation: SPEC-004 § 4.3 V5 says to reuse resolve_execution_order, which plan § 3.1 delivers later; _topological_order() is a temporary local Kahn copy with the identical contract (ValueError on cycle) and is deleted at 3.1 — the V5 tests pin behavior, not implementation. RED first, then GREEN; 4 mutation checks (V2 boundary off-by-one, V6 removed, V7 hardened, unknown hint hardened) all caught. | pytest 197 passed, 100% stmt coverage of planning/*; ruff check clean; ruff format idempotent; mypy --strict clean (zero suppressions); F1/F3 audits clean |
| 2026-09-14T14:59Z | 1.4 | tests/test_planner.py, tests/test_orchestrator.py (new) | SKL-CORE-TDD, SKL-REL-FLAKY, SKL-CORE-TYPES, SKL-CORE-LINT, SKL-CORE-GIT | Built the deterministic double kit and the SPEC-000 § 5.4 contract tests that make parallel work safe: FakeLLMClient (scripted complete/complete_json queues, exception injection, C5 usage + cost accounting, § 1.1 role/content message shape), FakeLLMResponse/FakeLLMUsage (SPEC-004 § 1 field order), FakeTool/FailingTool/CountingTool (SPEC-002 § 1 with name/description/capabilities as properties, R1 never-raise, R2 validate-first, R3 context purity, R4 metadata, R8 idempotent cleanup, plus an explicit raise_on_execute escape hatch to test a tool that *violates* R1), FakeRegistry (SPEC-002 § 2 with G1 TypeError, G2 overwrite, G3 insertion order, G5 no-op deregister, sorted names()), FakeStore (SCR-P3-5 snapshot/update, deep-copied both ways), FakeClock and FakeSleeper (injected time and backoff), FakePlanner (SPEC-004 § 2). Contract tests pin every signature by (name, kind, default) triple. Two genuine defects surfaced and were fixed: replan_step's available_tools is POSITIONAL_OR_KEYWORD in SPEC-004 § 2 (no `*` separator) — the real Planner must match; FakeStore needed deep copies or nested context mutations leaked. Double-kit guards prove no socket is opened, no real sleep occurs, and no secret value appears in config output. Determinism evidenced: 12/12 green in fixed order and 12/12 green under pytest-randomly, whole suite 0.35s. | pytest 261 passed, 100% stmt coverage of planning/*; ruff check clean; ruff format idempotent; mypy --strict clean (5 files, zero suppressions); 24/24 determinism runs; F1/F3 audits clean |
| 2026-09-14T15:21Z | 1.5 | agent_harness/planning/planner.py, tests/test_planner.py | SKL-REL-FUZZ, SKL-CORE-TDD, SKL-REL-FLAKY, SKL-CORE-TYPES, SKL-CORE-LINT, SKL-CORE-GIT | Treated LLM output as untrusted client input and swept the real-world variance the plan lists. Prose around JSON now parses via a bounded balanced-brace extractor (`_balanced_object_candidates`, max `MAX_JSON_EXTRACTION_ATTEMPTS = 8` candidates) that respects string literals and escapes; an extracted candidate is only adopted when it contains a `steps` key, which was a genuine defect found while writing the corpus — without that guard the truncated payload `{"steps": [{"description": "a"}` yielded the balanced inner fragment `{"description": "a"}` and silently fabricated a zero-step plan instead of reporting PLAN_PARSE_FAILED. Descriptions are capped at `MAX_STEP_DESCRIPTION_CHARS = 500` with `TRUNCATION_MARKER = "...[truncated]"` (500 matches SPEC-006 § 3.4 and SPEC-004 § 3.2), and a whitespace-only description is capped *without* the marker so truncation never manufactures content that would defeat V3. `RecursionError` from hostile nesting (5,000-deep payloads) is contained into PLAN_PARSE_FAILED; byte payloads decode with errors="replace". Documented rejections that yield a spec error code and never a raw JSONDecodeError: single-quoted pseudo-JSON (quote repair belongs to the SPEC-004 § 1.2 C3 repair round, not the parser), trailing commas, double-encoded JSON strings, unterminated objects, XML, prose plans. Documented pass-throughs: duplicate keys resolve last-wins (RFC 8259 leaves this implementation-defined; Python keeps the last), NaN/Infinity are not rewritten, unicode/RTL/emoji/null-byte/homoglyph descriptions survive verbatim below the cap. Removed an unpinnable `_strip_bom` helper after mutation M6 showed no test could distinguish it — the extraction pass already handles a BOM; fence-strip-before-parse ordering is pinned through the error preview instead. Boundedness is observable: 200 leading decoy objects cause rejection even though a valid plan follows, and a 1 MB payload yields a <700-char message. | pytest 317 passed, 100% stmt coverage; ruff check clean; ruff format idempotent; mypy --strict clean (zero suppressions); 10/10 mutation checks caught (M1 steps-guard, M2/M7 description cap, M3 whitespace marker, M4 RecursionError, M5 attempt bound, M6 preview, M6b candidate limit, M8 string escapes, M9 fence-strip ordering); F1/F3 audits clean |
| 2026-09-14T17:21Z | 2.1 | agent_harness/planning/planner.py, tests/test_planner.py | SKL-CORE-TDD, SKL-CORE-TYPES, SKL-REL-SCHEMA, SKL-OBS-OTEL, SKL-CORE-LINT, SKL-CORE-GIT | Implemented `Planner.__init__(llm_client, config, *, logger=None, models=None)` and `plan(prompt, available_tools, *, context=None)` exactly as SPEC-004 § 2 freezes them, with `models` additive/defaulted/keyword-only per SCR-P3-6. `plan()` composes the § 3.1 system prompt by substituting `{tool_descriptions}` with `render_tool_descriptions(available_tools)`, sends the § 1.1 two-message list (system then user, keys `role`/`content` only) with `schema_hint=PLAN_SCHEMA_HINT` and `temperature=config.llm.temperature`, then normalizes via `parse_plan` (threading `original_prompt`) and validates via `validate_plan` before emitting `plan_generated`. Exactly one `complete_json` round is made — the C3 repair round lives inside the client, so a planner-side retry would break the § 5 budget; a queued client `AgentError` propagates by identity (never re-coded or wrapped) and an unexpected non-AgentError exception is never swallowed. `available_tools` is typed `Sequence[object]` so registry tool objects render as well as `list_tools()` dicts. `select_tool`/`replan_step` are deferred to 2.4/2.5 (their signature pins were written, then moved out of this sub-phase because pinning them now would require stub bodies no test can cover). Event fields follow SKL-OBS-OTEL cardinality/PII discipline: `plan_generated` carries only plan_id, steps and unresolved_hints, promoted to WARNING when V7 returns a warning rather than emitting a second record — the contract `validate_plan` documents. Two of my own 2.1 expectations contradicted behavior pinned in 1.3 and were corrected: `{"steps": "step_0"}` is a V1 validation failure (§ 4.2 tolerates a non-list at parse time), and the `_planner` test helper's `None` sentinel collided with a scripted `None` reply. | pytest 367 passed, 100% stmt coverage; ruff check clean; ruff format idempotent; mypy --strict clean (zero suppressions); 12/12 Section-D mutation checks caught (D1 skip validation, D2 skip normalization, D3 hardcoded temperature, D4 dropped schema_hint, D5 message order, D6 unsubstituted placeholder, D7/D8 plan_generated level+duplicate, D9 planner-side retry, D10 context mutation, D11 original_prompt, D12 hints not checked); F1/F3 audits clean |
| 2026-09-14T17:30Z | 2.2 | tests/test_planner.py | SKL-CORE-TDD, SKL-REL-FUZZ, SKL-CORE-TYPES, SKL-CORE-LINT, SKL-CORE-GIT | Added `RepairingFakeLLMClient`, a double that models SPEC-004 § 1.2 C3 from the client side — strips fences, parses, and on failure sends the decoder error plus the invalid output back for exactly one repair round, then raises `AgentError(PLAN_PARSE_FAILED)` — recording every LLM round's message list so the budget is observable. Its fence stripper is local on purpose: a double that reuses `planner.strip_code_fences` cannot catch a regression in it. Proven: a malformed first reply is repaired and the plan still arrives in ONE `complete_json` call (1 round + 1 repair); the repair message retains the original system/user messages, appends the bad output as an assistant turn and asks for corrected JSON quoting the decoder error; fenced and prose-wrapped replies behave the same; `max_repair_rounds=0` fails on the first bad reply and never consumes the repair; when the repair also fails the planner propagates the client error BY IDENTITY with component "llm" (attributed where it originated) and emits no `plan_generated`. Both required failure codes are reachable: PLAN_PARSE_FAILED (reply parses but is not a plan object, or a step field has the wrong type) and PLAN_VALIDATION_FAILED (empty steps, cycle), plus LLM_CALL_FAILED pass-through. A parametrized budget test asserts `complete_json_calls == 1` and `len(rounds) <= 2` on all four failure paths, and one test pins the leniency that a client returning raw JSON *text* instead of a parsed object still yields a plan. Because 2.1's design already met § 5 there was no RED step, so the tests' bite is proven by a 5-mutation battery instead (E1 planner-side retry, E2 client error re-wrapped/re-coded, E3 plan_generated before validation, E4 warnings swallowed, E5 parse failure swallowed into an empty plan) — all caught. | pytest 388 passed, 100% stmt coverage; ruff check clean; ruff format idempotent; mypy --strict clean (zero suppressions); 5/5 mutation checks caught; F1/F3 audits clean |
| 2026-09-14T18:05Z | 2.3 | agent_harness/planning/planner.py, tests/test_planner.py | SKL-CORE-TDD, SKL-CORE-TYPES, SKL-REL-FUZZ, SKL-OBS-OTEL, SKL-CORE-LINT, SKL-CORE-GIT | Implemented context-aware planning with three additive constants: `MAX_CONTEXT_SUMMARY_CHARS = 2000` (the plan's bound, counted over the whole section header included), `MAX_CONTEXT_VALUE_CHARS = 200` (additive, so one enormous value cannot consume the entire budget and crowd out every other variable) and `CONTEXT_SUMMARY_HEADER = "Current context:"` (wording matches the frozen § 3.2 re-plan prompt, so a model sees the same label in both calls). `_context_variables` reads ONLY the `variables` key — `step_results`/`files_created` belong to the orchestrator's runtime context (SPEC-003 § 4.1) and a plan that has not executed must not claim them — and ignores a non-mapping value rather than raising. Seeding deep-copies, so orchestrator-side mutation of `plan.context` cannot reach the caller's dict and vice versa (§ 5). `_render_context_summary` lists variables in sorted key order (byte-identical prompts however the caller built the dict — SPEC-002 G3's determinism rationale), renders non-string values as JSON with `sort_keys=True`/`ensure_ascii=False` and falls back to `repr` for circular references or unsortable mixed keys, and truncates on LINE boundaries with a single section-level `TRUNCATION_MARKER` rather than mid-value, because a half-written path in a prompt is worse than an omitted one. Two mutation survivors exposed genuinely weak tests, both fixed: the huge-value test also passed when the variable was silently DROPPED (now pins the exact capped rendering), and the section-marker test was confounded because a capped value itself ends with the marker (now uses short values and counts exactly one marker). A hostile `__repr__` is documented as surfacing rather than being swallowed — the planner never guesses. | pytest 426 passed, 100% stmt coverage; ruff check clean; ruff format idempotent; mypy --strict clean (zero suppressions); 10/10 mutation checks caught (F1 shallow copy, F2 no seeding, F3 whole-context seeding, F4 budget ignored, F5 per-value cap, F6 sorted order, F7 summary in the frozen system message, F8 section marker, F9 empty variables, F10 non-mapping leniency); F1/F3 audits clean |
| 2026-09-14T19:17Z | 2.4 | agent_harness/planning/planner.py, tests/test_planner.py | SKL-CORE-TDD, SKL-CORE-TYPES, SKL-REL-FUZZ, SKL-CORE-LINT, SKL-CORE-GIT | Implemented runtime tool selection per SPEC-004 § 2/§ 3.3/§ 5. The decisive reading: § 5 allows "≤ 1 round, no repair", and rule C3 puts the repair round INSIDE `complete_json`, so `select_tool` calls `complete` (text) at temperature 0.0 — hardcoded, not `config.llm.temperature` — and parses the reply itself. The reply is accepted only in the documented `{"tool": name|null}` shape after fence stripping and the bounded prose-extraction pass; the name must match a registered tool EXACTLY (no case folding, no fuzzy repair) so a hallucinated name reaches the orchestrator as "no tool" and SPEC-003 § 3 step 2 fails the step with TOOL_NOT_FOUND rather than guessing a tool that was never offered. Any provider `AgentError` returns `None` instead of propagating, because the frozen step loop branches only on `None` and would have no defined path for an exception — the client still emits its own `llm_call` event so the failure is not lost; unexpected non-AgentError exceptions are never swallowed. The § 3.3 prompt is sent as a SINGLE user turn: the additive template is self-contained, and a lone system message would break providers whose message list must open with a user turn (Anthropic, § 1.3). `str.format` is required there (not `.replace`) because the template doubles the braces of its JSON examples; only the step's input KEYS are sent, never values, per SPEC-006 § 3.4. `select_tool` never mutates the step — writing `step.tool_name` belongs to the orchestrator. One mutation initially survived (coercing a non-string `tool` value) and was shown to be observable only when a tool literally bears that coerced name, so two tests now pin that a JSON number or boolean never selects a tool. | pytest 480 passed, 100% stmt coverage; ruff check clean; ruff format idempotent; mypy --strict clean (zero suppressions); 11/11 mutation checks caught (G1 complete_json/repair round, G2 temperature, G3 unvalidated name, G4 case folding, G5 type coercion, G6 error propagation, G7 blanket swallow, G8 lone system message, G9 replace-vs-format, G10 input values leaked, G11 step mutation); F1/F3 audits clean |
| 2026-09-14T20:01Z | 2.5 | agent_harness/planning/planner.py, tests/test_planner.py, planning/plan-3-orchestration/plan.md (Status Log) | SKL-CORE-TDD, SKL-CORE-TYPES, SKL-REL-FUZZ, SKL-PLAN-FMEA, SKL-CORE-LINT, SKL-CORE-GIT | Implemented recovery Level 3's planning side per SPEC-004 § 2/§ 3.2 and SPEC-003 § 5. One `complete_json` round at `config.llm.temperature` with `PLAN_SCHEMA_HINT` reused for the reply shape (§ 5 allows "1 round + 1 repair" here, unlike select_tool). Three reply envelopes are accepted because § 3.2 asks for "an alternative step (or sequence of steps)" without fixing the envelope: the § 4.1 `{"steps": [...]}` object, a lone step object, a bare array. Replacement steps are normalized by `parse_plan` (so § 4.2 applies unchanged), then re-identified as `<failed_id>r<n>` — canonical `step_i` ids would collide with the plan being repaired. Three inheritance rules follow from § 5: priority comes from the FAILED step, never the model, because Level 4 reads priority and a model answering "low" for a critical deliverable must not dodge `abort_on_critical_failure`; a dependency written as a bare INDEX is remapped to the replacement's new id (that is the convention § 3.1 taught the model), while a `"step_N"` string names an ORIGINAL step and is kept verbatim — the replacement list is not the plan, so `_index_references` recovers the distinction from the raw payload that `parse_plan` erases; a dependency on the failed step itself is dropped as unsatisfiable. `replan_step` never raises for a bad reply: an unparseable reply, an unusable dependency type, or a client `AgentError` all yield `[]` so the cascade escalates to Level 4 with the priority intact; description-less replacements are dropped (they cannot be reported, resolved or re-planned again) and unexpected non-AgentError exceptions are never swallowed. The frozen § 3.2 prompt is filled by a new single-pass `_substitute` engine: chained `str.replace` would rescan values, so a step description containing the literal `{context_summary}` could hijack a later placeholder (mutation-verified), and `str.format` is unusable on the frozen templates because a stray brace in model text would raise. `{attempt_history}` is built from `context["errors"]` scoped to this step, newest `MAX_ATTEMPT_HISTORY_ENTRIES = 10` (additive bound: § 3.2 bounds the summary but not the history, which would otherwise grow with every recovery pass). `{context_summary}` honors the frozen bounds — 500 chars per step output, 4000 total — cutting at the first entry that does not fit so the model sees a contiguous prefix, and additively includes `variables` within that bound because a re-plan that cannot see the user's `data_file` cannot propose a working alternative. Sent as a single user turn for the same provider reason as select_tool. Only input KEYS and prior outputs reach the prompt, never secrets (SPEC-006 § 3.4). Guards on the runtime context (this plan's own typed contract) were removed as unreachable, while guards on model output were kept and are directly unit-tested — a deliberate split. Hygiene: three `__pycache__/*.pyc` files committed by 677df2b are removed and SCR-P3-9 filed (no root `.gitignore`; repo meta is P5's), with the verification harness now clearing and auditing artifacts. | pytest 593 passed, 100% stmt coverage; ruff check clean; ruff format idempotent; mypy --strict clean (zero suppressions); 15/15 mutation checks caught (H1 priority inheritance, H2/H3 r-suffix ids, H4 failed-step dep, H5 index remap, H6 description filter, H7 error propagation, H8 complete-vs-complete_json, H9 history scoping, H10 history bound, H11 500-char output bound, H12 4000-char budget, H13 variables in summary, H14 chained replace, H15 schema hint); 8/8 randomized-order determinism runs; artifact audit clean; F1/F3 audits clean |
| 2026-09-18T05:43Z | 3.1 | agent_harness/orchestration/dependency.py (new), agent_harness/orchestration/__init__.py (new), agent_harness/planning/planner.py, agent_harness/planning/__init__.py, tests/test_dependency.py (new), tests/test_planner.py, planning/plan-3-orchestration/plan.md (Status Log) | SKL-CORE-TDD (core-coding/tdd-test-runner), SKL-CORE-TYPES (core-coding/strict-typing-contracts), SKL-PLAN-CPM (planning/critical-path-mapping — explicit typed dependencies, cycle check before any ordering is handed out, DAG-with-0-cycles verified), SKL-REL-FUZZ (reliability/api-fuzz-tester), SKL-CORE-LINT (core-coding/lint-formatting), SKL-CORE-GIT (core-coding/git-workflow-hygiene) | Delivered SPEC-003 § 8 as frozen: Kahn's algorithm with a `deque` per vision § 7.2, `ValueError("Circular dependency detected in execution plan")` when the ordered output is shorter than the input, dangling `depends_on` ids ignored with one WARNING each, and index-stable deterministic ordering. The signature widens the frozen `list[Step] -> list[Step]` at type level only — `Sequence[_StepT] -> list[_StepT]` — so the orchestrator can pass `plan.steps` (a `Sequence`, since `list` is invariant) and a caller's concrete step type survives the round trip; the bound stays the full `StepLike` because that is the frozen `Step`. Documented boundaries: a self-dependency is a cycle, duplicate `depends_on` entries add one edge each so the step is still released exactly once, duplicate step ids collapse into one node and are reported unorderable by the same length rule (impossible for a parsed plan — SPEC-004 § 4.2 rule 2 canonicalizes ids), non-string ids count as dangling, the caller's list and each step's `depends_on` are never mutated, and the sort is iterative O(V+E) so a 10,000-step chain is pinned under a time bound rather than a recursion limit. V5 in `validate_plan` now delegates here through a **deferred function-level import** and forwards its own logger, and 1.3's temporary `_topological_order` (plus the then-needed `deque` import) is deleted as that row promised; the 1.3 V5 tests pass unchanged because they pinned behavior, not implementation, and five new tests pin the delegation itself — the sorter is called once with the plan's steps, a `NullLogger` is forwarded when none was injected, the frozen cycle message reaches the failure detail verbatim, only `ValueError` is converted (a sorter bug must not be laundered into "the plan has a cycle"), and no `dependency_ignored` can fire in validation mode because V4 rejects unknown ids first. Two integration defects were found and fixed by type-checking a composition probe against merged `main`, where PRs #1/#2 have landed P1/P2/P4: `planning/__init__.py` did not re-export `Planner` although `harness.py` resolves it by dotted name (SCR-P3-12), and `ExecutionConfigLike.retry_base_delay: float` was an invariant mutable attribute that rejected Plan 1's `int = 2`, which made the whole real `Config` fail `ConfigLike` and would have made every P3 entry point refuse the real configuration at I1 — both section protocols are now read-only properties (SCR-P3-13). The probe itself stays outside the repository because it imports concrete Plan 1/2 modules (agent.md F3); it is `mypy --strict` clean and runs `parse_plan` → `validate_plan` → `resolve_execution_order` → `Planner.plan` on P1's real objects, raising P1's real `AgentError(code="PLAN_VALIDATION_FAILED")` on the failure path. Environment incident: the sandbox was recreated from a fresh clone mid-sub-phase, destroying the branch's 12 commits and the `/home/user` tooling (venv, verification harness, mutation scripts) while the working tree survived; the venv and harness were rebuilt (the harness gained two sections — ruff under the repository's own `pyproject.toml`, and a write-set audit driven by `git status`), the branch was re-based onto `origin/main` because its previous base `7dcd637` shares no ancestor with main (a shallow, unrelated history — a pull request from it could not have been mergeable), and the per-sub-phase history could not be reconstructed, so this delivery is re-landed with this ledger as its audit trail. RED first (`ModuleNotFoundError` on the new package), then GREEN. | pytest 657 passed (45 new in tests/test_dependency.py, 19 new in tests/test_planner.py), 100% statement coverage of planning/* and orchestration/*; ruff check clean under both the strict P3 selection and the repository's `pyproject.toml` config; ruff format idempotent; mypy --strict clean (8 files, zero suppressions); 15/15 mutation checks caught (I1 reverse seeding, I2 LIFO, I3 edge for a dangling id, I4 warning dropped, I5 wrong level, I6 wrong component, I7 cycle check off by one, I8 message reworded, I9 zero-degree test dropped, I10 input returned, I11 in-degrees never counted, I12 adjacency reversed, I13 single level drained, I14 caller's `depends_on` mutated, I15 alphabetical instead of topological); 8/8 randomized-order determinism runs; composition probe `mypy --strict` clean and end-to-end OK against merged main; Plan 4's suite measured at 128 failed / 204 passed both with and without P3's files — an identical failure set, pre-existing and caused by P1's closed event catalog (SCR-P3-10 evidence); artifact audit clean; F1/F3 audits clean |

### Spec/Skill Change Requests

Filed per SPEC-000 § 7 / agent.md § 6.5. **None of these block execution** — each records an
interim, spec-conformant resolution this agent proceeds under (agent.md § 7: continue with all
unaffected sub-phases; blocking is limited to the specific sub-phase).

```text
SCR-P3-1: .agent/agent.md § 6.2 + .agent/README.md — dictionary status/path are stale
  problem:   § 6.2 states "The skill dictionary is currently unpopulated (0 registered skills)"
             and both files point at `.agent/skills/skill-dictionary.md`. That path does not
             exist; 50 SKILL.md files ARE registered at `.agent/skill-dictionary/<cat>/<name>/`.
             The binding hard-stop therefore reads as "no work permitted" while the evidence
             says the opposite — an unresolvable gate for all five plans.
  proposed:  Orchestrator updates § 6.2 status + the pointer path and broadcasts
             "gate satisfied, N skills registered" in planning/README.md § 6.
  interim:   P3 treats the gate as SATISFIED (evidence: 50 registered skills) and records the
             applicability determination above. Blocked: no.

SCR-P3-2: .agent/agent.md § 6.2/§ 6.4 — skills have no `applies_to` field and no `SKL-*` ID
  problem:   § 6.2 requires matching a skill's `applies_to` against file paths/change kind, and
             § 6.4/§ 5 require citing a skill ID (e.g. `SKL-TOOL-001`). Registered SKILL.md
             frontmatter has only `name` + `description`; scope lives in prose (§ 1/§ 2).
  proposed:  Orchestrator either (a) ratifies the alias table above + prose-scope matching as the
             project convention, or (b) adds `id` + `applies_to` frontmatter to each SKILL.md.
  interim:   Alias table + prose-scope matching (documented above); commit messages cite both the
             alias and the dictionary path. Blocked: no.

SCR-P3-3: SPEC-000 § 3.3 vs plan § 1.4 — `tests/_p3_doubles.py` is not owned by any plan
  problem:   Sub-phase 1.4 instructs creating `tests/_p3_doubles.py` "(owned by this plan)", but
             SPEC-000 § 3.3 (binding ownership matrix) lists only the five `tests/test_*.py`
             files for P3, and this agent's write-set declaration is absolute. Creating it would
             be an F1 boundary violation and could collide with P5's `tests/` assets.
  proposed:  Either add `tests/_p3_doubles.py` to § 3.3 (P3), or amend plan § 1.4 to "doubles
             declared inside the owned test files".
  interim:   Spec text wins over plan text (planning/README.md § 3): the spec-shaped doubles
             (`FakeLLMClient`, `FakeTool`, `FailingTool`, `CountingTool`, `FakeRegistry`,
             `FakeConfig`, `FakeLogger`, `FakeStore`, `FakeClock`) are declared **inside this
             plan's five owned test files**, no shared module created. Known cost: ~40 lines of
             double scaffolding repeated in 3–4 test files; P5 can dedupe into its own
             `tests/conftest.py` during integration window I2 (additive, P5-owned). Blocked: no.

SCR-P3-4: SPEC-001 § 2.5 / SPEC-003 § 7 — metrics computation has no owning file, and
          `recovered_via` has nowhere to persist
  problem:   (a) SPEC-003 § 7 assigns the `ExecutionMetrics.from_plan` computation rules to P3,
             but the container is P1's (SPEC-001 § 2.5) and SPEC-000 § 3.3 gives P3 no metrics
             module. (b) § 7 defines `recovered_steps` via `metadata["recovered_via"]`, and
             SPEC-003 § 5 Level 2 sets it — but SPEC-001 § 2.1 `Step` has **no `metadata` field**,
             and SPEC-003 § 4.1 freezes the `step_results` entry to six keys, so the marker has no
             spec-defined channel from recovery to metrics.
  proposed:  (a) Ratify P3 implementing the computation as pure functions in
             `orchestration/assembler.py`, so P1's classmethod delegates:
             `ExecutionMetrics(**compute_metrics(...))`. (b) Add `metadata: dict[str, Any] =
             field(default_factory=dict)` to SPEC-001 § 2.1 `Step` (additive, defaulted →
             backward compatible per SKL-REL-SCHEMA).
  interim:   (a) `compute_metrics(...)` + `metrics_from_plan(plan, timings, llm_usage, ...)` live
             in `orchestration/assembler.py`, return a dict keyed exactly by the SPEC-001 § 2.5
             field names, and never construct P1's container. (b) recovery writes `recovered_via`
             to `step.metadata` when the injected Step exposes one, else to the additive
             `plan.context["step_metadata"][step_id]` map; `compute_metrics` reads both channels.
             Blocked: no.

SCR-P3-5: SPEC-003 § 2 / SPEC-005 § 1.1 — `ContextStore` is injected but never specified
  problem:   `Orchestrator.__init__` accepts `context_store: ContextStore | None` and SPEC-005
             § 1.1 step 2 says "Fresh ContextStore per run; seed context['variables'] …", but no
             spec freezes a ContextStore API (SPEC-001/006 define only the § 4.1 context dict).
  proposed:  Freeze the ContextStore contract in SPEC-001 (or SPEC-006 § 5) — at minimum the two
             methods P3 needs: `snapshot() -> dict[str, Any]` and `update(context) -> None`.
  interim:   P3 declares a narrow `ContextStoreLike` protocol with exactly those two methods,
             probes the injected object for them, logs `context_store_unsupported` (WARNING) and
             self-builds the SPEC-003 § 4.1 context when absent. Nothing is silenced; the probe
             result is logged. Blocked: no.

SCR-P3-6: SPEC-003 § 2/§ 5/§ 8, SPEC-004 § 2 — additive keyword-only params on FROZEN signatures
  problem:   Three frozen contracts cannot be implemented as literally written without either
             importing another plan's concrete modules (F3) or losing spec-mandated determinism
             (SPEC-000 § 5.5):
             (a) SPEC-004 § 2 `Planner(llm_client, config, *, logger=None)` must *construct*
                 `Step`/`ExecutionPlan`, which are P1's concrete classes (SPEC-001 § 2.1–2.2).
             (b) SPEC-003 § 5 `attempt_recovery(step, error, context)` must honor
                 `metadata["retryable"] == False` (a ToolResult field it never receives) and the
                 input-validation "skip Level 1" rule.
             (c) SPEC-003 § 8 `resolve_execution_order(steps)` must emit a WARNING for dangling
                 deps but takes no logger; SPEC-006 § 6.2 forbids module-level logger singletons.
             (d) SPEC-003 § 3 step 8 requires a step-timeout guard, untestable without an
                 injected clock (SPEC-000 § 5.5).
  proposed:  Ratify the following as **additive, keyword-only, defaulted** (every frozen
             positional signature and default remains byte-identical, so all existing call sites
             and P5's contract tests keep working):
             `Planner(..., models: ModelProvider | None = None)`;
             `RecoveryManager(..., models=None, executor=None)` and
             `attempt_recovery(..., *, result=None, skip_level_1=False)`;
             `resolve_execution_order(steps, *, logger=None)`;
             `Orchestrator(..., models=None, recovery=None, clock=None, sleep=time.sleep)`;
             `Assembler(..., models=None, clock=None)`.
             Alternatively specify the injection mechanism centrally in SPEC-000 § 4.
  interim:   Implemented exactly as proposed above. All P3 modules type injected collaborators as
             structural Protocols (`StepLike`, `PlanLike`, `ToolLike`, `RegistryLike`,
             `LLMClientLike`, `ConfigLike`, `LoggerLike`) and ship P3-local **spec-conformant
             stand-ins** (field-identical to SPEC-001 § 2.1–2.4) used only when nothing is
             injected. P4's composition root swaps in the real P1/P2 objects with zero P3 edits.
             Status/priority comparisons are done on enum `.value` strings so a mixed graph
             (P1 enums + P3 stand-ins) can never compare unequal. Blocked: no.

SCR-P3-7: SPEC-001 § 2.4 / SPEC-003 § 2 — is `AgentError` raisable?
  problem:   SPEC-001 § 2.4 defines `AgentError` as a plain `@dataclass` (not an `Exception`
             subclass), yet SPEC-003 § 2/§ 5 and the § 3 catalog ("Raised by") require
             `raise AgentError(code="PLAN_ABORTED")`. A non-Exception dataclass cannot be raised.
  proposed:  Confirm `AgentError` subclasses `Exception` (SPEC-001 § 2.4) — `__str__` rendering
             "[code] component(step_id): message" already implies exception semantics.
  interim:   P3's stand-in `AgentError` is a dataclass **and** an `Exception` subclass. At every
             raise site P3 narrows with `isinstance(error, BaseException)`: if the injected model
             provider yields a raisable error it is raised unchanged; otherwise it is wrapped in
             P3's `AgentErrorRaised(RuntimeError)` (exposes `.code`, `.message`, `.error`,
             § 2.4 `__str__`). Both P1 designs therefore work, and no failure is ever silenced.
             Blocked: no.

SCR-P3-8: SPEC-004 § 3.1/§ 3.2 vs vision § 8.1/§ 8.2 — the "verbatim" prompt text is
          not byte-identical between the two documents
  problem:   SPEC-004 declares both FROZEN templates "verbatim from vision § 8.1/§ 8.2",
             but the two renderings differ in line wrapping at exactly two spans
             (whitespace-normalized they are identical, and both are 918 / 391 chars):
             vision keeps "…decompose it into a structured execution plan…" and "…same
             goal using a different approach…" on one line; the spec wraps each at ~85
             columns. A character-for-character conformance test can only satisfy one.
  evidence:  sha256 SPEC-004 § 3.1 = 2623db2ef25350b56abd8e1e287f43a6c2d4bd7809de13f6b4886edda5951f6a
             sha256 vision § 8.1   = 36c964e9b69ec10eedc16934d98521dabccf3ff11d20e4805e27358a9f17a884
             sha256 SPEC-004 § 3.2 = 6fd2c03d351923f124376e196e6f294b96f4acb9a61614034253e8ac1f364a77
             sha256 vision § 8.2   = 27f41a2aebfc353a99638778417597d8c13227cac6cd478e27a3a6f850d6c0cc
  proposed:  Declare SPEC-004 § 3.1/§ 3.2 canonical (this plan's choice: the spec is the
             binding contract per SPEC-000 § 3.6 and plan § 1.1 says "from SPEC-004"), and
             re-wrap the vision code block or annotate it as display-only.
  interim:   `prompts.py` implements the SPEC-004 bytes. `tests/test_planner.py` pins
             (a) byte equality + sha256 for the spec form and (b) the *complete*
             divergence set (`VISION_8_1_8_2_UNWRAPPED_SPANS`, two spans) plus
             whitespace-normalized equality with the vision form — so a ruling for the
             vision rendering is a two-line change, and any *real* text drift still fails.
             Blocked: no.

SCR-P3-9: the repository has no root `.gitignore`, so build artifacts are one
          `git add -A` away from being committed by any agent
  problem:   `.gitignore` does not exist at the repo root. Repo meta (`LICENSE`,
             `.gitignore`, `CONTRIBUTING.md`) is P5's per planning/README.md's ownership
             table, so no other agent may create it — yet every agent runs
             pytest/ruff/mypy, which leave `__pycache__/`, `.mypy_cache/`,
             `.pytest_cache/`, `.ruff_cache/` and `.coverage` in the working tree. P3 hit
             this: commit 677df2b (sub-phase 1.5) included three
             `agent_harness/planning/__pycache__/*.pyc` files. The paths are inside P3's
             owned directory, so P3's own write-set audit (agent.md F1) passed while the
             artifacts were still wrong to commit.
  evidence:  `git ls-files | grep pycache` → 3 files at 677df2b; `git show --stat 677df2b`;
             removed again by `git rm -r --cached` in the sub-phase 2.5 commit.
             `ls -a` at the repo root shows `.mypy_cache/ .pytest_cache/ .ruff_cache/`
             present and untracked.
  proposed:  P5 adds a `.gitignore` covering `__pycache__/`, `*.py[cod]`, `.mypy_cache/`,
             `.pytest_cache/`, `.ruff_cache/`, `.coverage`, `htmlcov/`, `dist/`, `build/`,
             `*.egg-info/`, and strips the three already-committed `.pyc` files from history or via a
             follow-up delete commit. Until P5 delivers it, every plan should keep
             `PYTHONDONTWRITEBYTECODE=1`, point `COVERAGE_FILE` outside the repo, and
             never `git add -A` without first clearing `__pycache__`.
  interim:   P3 removes the artifacts from its own index and working tree, and its
             verification harness now deletes every `__pycache__` directory in the repo
             before reporting, so no later P3 commit can include one. P3 sets
             `PYTHONDONTWRITEBYTECODE=1` and `COVERAGE_FILE` outside the repo for every
             tool invocation. Blocked: no.

SCR-P3-10: SPEC-003 § 8 vs SPEC-006 § 6.1 — the mandated dangling-dependency WARNING has
           no event name, and Plan 1's merged logger treats the catalog as CLOSED
  problem:   § 8 requires a `depends_on` entry naming an unknown id to be "ignored with a
             WARNING", but § 6.1 names no event for it. Plan 1's merged
             `agent_harness/logging/logger.py` implements § 6.1 as a closed
             `EVENTS = frozenset({...18 names...})` and raises
             `ValueError("Unknown logging level or event")` for anything else, so an
             additive name is a hard failure rather than a record. The same conflict is
             already breaking Plan 4 on `main`: 128 tests in `tests/test_harness.py`,
             `test_cli.py` and `test_plugin_loader.py` fail because `harness.py` emits
             `pdf_export_degraded`, `progress_callback_failed` and `llm_client_unavailable`
             (measured identical before and after P3's files land — P3 changes nothing).
  evidence:  `agent_harness/logging/logger.py:18-40,89-90`; probe run
             `pytest tests/test_harness.py tests/test_cli.py tests/test_plugin_loader.py`
             → "128 failed, 204 passed" on a clean `origin/main` worktree AND on this
             branch; first failing frame is `logger.log` raising for `pdf_export_degraded`.
  proposed:  Treat § 6.1 as the required MINIMUM it is titled as. Either (a) P1 extends
             `EVENTS` with the additive names its consumers emit and keeps raising for
             typos, or (b) P1 records an uncatalogued event at WARNING with the original
             name in `metadata` instead of raising. Route at I4; owner P1 (logging), with
             P4 as the second affected consumer.
  interim:   P3 emits `dependency_ignored` (fields `step_id`, `dependency`) at WARNING from
             `resolve_execution_order` and never catches the rejection, so composing with
             today's P1 logger fails loudly instead of silently dropping a spec-mandated
             warning. `test_a_closed_catalog_logger_surfaces_the_conflict` pins this with a
             double that reproduces P1's closed-catalog semantics (declared in
             tests/test_dependency.py, not imported — agent.md F3). Unreachable for a
             validated plan: SPEC-004 § 4.3 V4 rejects unknown ids before execution.
             Blocked: no.

SCR-P3-11: SPEC-003 § 8 — "BFS with a deque" and "stable by original list index" disagree
  problem:   § 8 freezes Kahn's algorithm "matching vision § 7.2" *and* requires
             tie-breaking "stable by original list index". A deque is FIFO, so a step that
             becomes ready later keeps its queue position behind an already-queued step with
             a higher index. Counterexample (input order): step_0←step_3, step_1←step_2,
             step_2, step_3 → the deque yields [step_2, step_3, step_1, step_0]; a strict
             smallest-ready-index tie-break yields [step_2, step_1, step_3, step_0].
  proposed:  Ratify the deque reading. Both orders are deterministic and topologically
             valid, § 8 names the vision algorithm explicitly, and a future parallel
             executor gains nothing from re-sorting the ready set (§ 8's real requirement is
             that the order be reproducible).
  interim:   Implemented as the vision's deque. What "stable by original list index" buys is
             pinned by tests: the ready set is seeded by input index, and one parent
             releases its dependants by their own input index
             (`test_branch_release_order_follows_the_dependants_own_index`), while the FIFO
             nuance is pinned by
             `test_a_step_released_later_keeps_its_breadth_first_position`. Blocked: no.

SCR-P3-12: SPEC-000 § 3.3 — package `__init__.py` files must re-export the names other
           plans resolve by dotted name; no spec says so, and a partial package is a hazard
  problem:   § 3.3 lists `planning/__init__.py` and `orchestration/__init__.py` as P3 files
             but nothing states what they must expose. Plan 4's MERGED composition root
             resolves P3 by dotted name at call time —
             `importlib.import_module("agent_harness.planning").Planner(...)`, and
             `import_module("agent_harness.orchestration").Orchestrator/ExecutionHooks/
             Assembler(...)` (harness.py `_resolve_planner`, `_resolve_orchestrator`,
             `_build_hooks`, `_resolve_assembler`) — while `tests/_p4_stubs.py:stub_modules()`
             skips a dotted name as soon as `importlib.util.find_spec` finds the real module.
             So (i) a submodule-only export breaks the harness with AttributeError, and
             (ii) a PARTIALLY delivered `agent_harness/orchestration` (dependency.py landed,
             orchestrator.py/assembler.py pending) suppresses P4's package-level stub while
             `Orchestrator`, `ExecutionHooks`, `Assembler` and `AssemblyResult` are still
             absent.
  evidence:  `agent_harness/harness.py:454-470,495-511,557-558`; `tests/_p4_stubs.py:1194-1210`
             (the stub map) and `:1236-1240` (`if real_module_available(dotted): continue`).
  proposed:  Record in SPEC-000 § 3.3 or planning/README § 4 step I1 that each plan's package
             `__init__.py` re-exports every name its consumers resolve by dotted name, and
             that I1 opens only when all six orchestration names exist. Optionally P4's
             `stub_modules()` could fall back to attribute-level stubbing
             (`if not hasattr(module, attr)`) so a partially landed package degrades instead
             of breaking. Also note for 3.2: harness.py assigns `orchestrator.hooks = ...`
             AFTER construction and expects it to take effect for that run, so `hooks` must be
             a public mutable attribute read per execution, not cached in `__init__`.
  interim:   `planning/__init__.py` re-exports `Planner`, `parse_plan`, `validate_plan` and
             the prompt templates, pinned by `TestPackageSurfaceForTheCompositionRoot`
             (including harness.py's exact call shape). `orchestration/__init__.py`
             re-exports `resolve_execution_order` now and documents the additive schedule
             (3.2 `Orchestrator`, 3.5 `ExecutionHooks`, 4.1 `RecoveryManager`, 5.1
             `Assembler` + `AssemblyResult`). P3 is not `done` until those land, so the
             integration window has not opened (planning/README § 4). Blocked: no.

SCR-P3-13: SPEC-006 § 1 does not type `retry_base_delay`, and Plan 1's `int` broke P3's
           `ConfigLike` — fixed on the P3 side, recorded so no plan repeats it
  problem:   § 1 shows the bare YAML scalar `retry_base_delay: 2`. P3's
             `ExecutionConfigLike` declared it `float`; Plan 1's merged `ExecutionConfig`
             declares `int = 2`. A mutable protocol attribute is invariant, so P1's section
             did not satisfy the protocol — and since `ConfigLike.execution` is typed
             `ExecutionConfigLike`, the whole `Config` failed to satisfy `ConfigLike`, making
             `parse_plan`, `validate_plan` and `Planner` reject the real configuration object
             under `mypy --strict`. Nothing at runtime would have shown this before I1.
  evidence:  A composition probe type-checked against merged `main` reported
             `note: Following member(s) of "Config" have conflicts: execution: expected
             "ExecutionConfigLike", got "ExecutionConfig"` and
             `retry_base_delay: expected "float", got "int"`. After the fix the probe is
             clean and runs end-to-end (below).
  proposed:  SPEC-006 § 1 could state Python types for the numeric keys (`retry_base_delay:
             float`, `step_timeout: int`, …) so five plans do not each guess. Meanwhile: any
             protocol describing another plan's dataclass should declare read-only members,
             because covariance is the only thing that survives a narrower annotation.
  interim:   `LLMConfigLike` and `ExecutionConfigLike` now declare every member as a
             read-only property (as `ConfigLike.llm/.execution` and `PlanLike.steps` already
             did), pinned by `TestConfigProtocolsStayCovariant`. Verified by probe against
             merged main: `Config`, `ExecutionConfig`, `LLMConfig`, `Step`, `ExecutionPlan`,
             `AgentError`, `ToolResult` (P2) and `StructuredLogger` all satisfy P3's
             protocols under `mypy --strict`, and `parse_plan` → `validate_plan` →
             `resolve_execution_order` → `Planner.plan` runs on P1's real objects, raising
             P1's real `AgentError(code="PLAN_VALIDATION_FAILED")` on the failure path.
             Blocked: no.
```

**Skill Requests (agent.md § 6.5):** _none required._ Every one of the 25 sub-phases is covered by
at least one registered skill (see the alias table). In particular no SKR is filed for the
`tests/_p3_doubles.py` deviation — that is an ownership question (SCR-P3-3), not a technique gap.

### Handoff Note

_Written at sub-phase 5.5._
