# Plan 4 — Harness Surface

**Plan ID:** P4 · **Workstream:** `AgentHarness` Facade, Composition Root, CLI, Plugin System
**Execution:** independent — may run concurrently with P1–P3, P5 · **Sub-phases:** 25 (5 phases × 5)

---

## 0. Plan Header

| Field | Value |
|---|---|
| Mission | Deliver the L3 surface: the public `AgentHarness` API, the composition root that wires all layers, the CLI, and plugin auto-discovery with shipped examples — per SPEC-005. |
| Owned paths | SPEC-000 § 3.4 — `agent_harness/__init__.py`, `agent_harness/__main__.py`, `agent_harness/harness.py`, `agent_harness/plugins/`, `plugins/` (examples + README), `tests/test_harness.py`, `tests/test_cli.py`, `tests/test_plugin_loader.py` |
| Consumed specs | SPEC-000, SPEC-001 (result/plan/metrics types), SPEC-002 § 1–2 (registry, `default_tools`), SPEC-003 § 2 (orchestrator + hooks), SPEC-004 § 1–2 (LLM factory, planner), SPEC-005 (owns), SPEC-006 § 1–3 (config, redaction, startup warnings) |
| Produces for others | The runnable product: `python -m agent_harness`, `AgentHarness` Python API, plugin mechanism (US-4), startup warnings; integration wiring checklist for P5 |
| Parallel-work rule | P1–P3 modules may not exist yet → build against **spec-shaped stubs** owned by this plan in `tests/_p4_stubs.py` (stub Config/LLM factory/Planner/Orchestrator/Assembler/registry). Phase 5 swaps stubs for real modules during the integration window (planning/README § 4, step I1). |
| Skill gate | ⛔ No source change until an active skill covers it (`.agent/agent.md` § 6). Dictionary currently empty → status: gated. |

**Independence declaration.** This plan touches only its owned paths. It never edits
`tools/`, `planning/`, `orchestration/`, `config/`, `llm/`, `logging/`, or `context/`; it
composes them. Composition correctness is verified twice: against stubs now (parallel),
against real modules at I1 (integration window).

---

## Phase 1 — Public API Surface

> Outcome: the frozen API shape of SPEC-005 § 1, testable in isolation with stubs.

### Sub-phase 1.1 — Package exports & `HarnessResult`
- **Tasks:** `agent_harness/__init__.py` exporting exactly `__all__ = ["AgentHarness", "Config", "HarnessResult", "__version__"]`; `HarnessResult` dataclass per SPEC-005 § 1 (status/final_output/plan/metrics/files_created/errors); lazy imports so `import agent_harness` never fails on optional deps.
- **Deliverable:** package public surface.
- **Exit criteria:** export-list test matches spec verbatim; `__version__` sourced from package metadata.

### Sub-phase 1.2 — `AgentHarness` skeleton
- **Tasks:** constructor + `from_config()` classmethod per SPEC-005 § 1; injectable seams for tests (`llm_client=None`, `planner=None`, `orchestrator=None`, `assembler=None`, `registry=None`) defaulting to real construction; output/temp dir creation at init (§ 1.2).
- **Deliverable:** `harness.py` skeleton.
- **Exit criteria:** instantiable with stub config; dirs created; injected stubs honored end-to-end in a smoke test.

### Sub-phase 1.3 — `plan()` (dry-run API)
- **Tasks:** `plan(prompt)` → validated `ExecutionPlan` without execution (SPEC-005 § 1); shares prompt validation with `run()`.
- **Deliverable:** planning-only entry point.
- **Exit criteria:** stub planner test: returns plan, executes zero tools (asserted via counting stub).

### Sub-phase 1.4 — `register_tool()` & `list_tools()`
- **Tasks:** runtime registration with `TypeError` guard (registry contract G1 passthrough), effect scoped to subsequent runs (SPEC-005 § 5); `list_tools()` delegates to registry.
- **Deliverable:** runtime extensibility API.
- **Exit criteria:** tests: register-then-list, invalid object rejection, post-run registration semantics.

### Sub-phase 1.5 — Prompt validation & error surface
- **Tasks:** `PROMPT_INVALID` rules per SPEC-005 § 1.1 step 1 (non-empty after strip, ≤ 20 000 chars); `AgentError` propagation policy: raise for steps 3–5, contain for 6–8 (§ 1.1); `errors` list on `HarnessResult` mirrors `context["errors"]`.
- **Deliverable:** input gate + error policy.
- **Exit criteria:** boundary tests (empty, whitespace, 20 001 chars); contained-failure test returns a `failed`/`partial` result instead of raising.

---

## Phase 2 — Composition Root & Run Lifecycle

> Outcome: `run()` executing the full SPEC-005 § 1.1 lifecycle against stubs, ready for real-module swap.

### Sub-phase 2.1 — Startup sequence
- **Tasks:** implement lifecycle steps 2–4: fresh `ContextStore` per run, seed `variables` + `allowed_read_paths` from the `context` argument, `create_llm_client(config)`, registry build via `default_tools(config, llm_client)` + plugin discovery (Phase 3) + runtime tools.
- **Deliverable:** composition wiring in `harness.py`.
- **Exit criteria:** stub-level test asserts construction order and that context seeding matches SPEC-003 § 4.1 keys.

### Sub-phase 2.2 — Execute → assemble → report pipeline
- **Tasks:** lifecycle steps 5–9: `Planner.plan(prompt, registry.list_tools(), context=…)`, `Orchestrator.execute(plan)`, `Assembler.assemble(plan, context)`, `ExecutionMetrics.from_plan(...)`, report rendering via `logging/report.py`, `HarnessResult` construction.
- **Deliverable:** complete `run()` flow.
- **Exit criteria:** stub pipeline test: statuses map correctly (`completed`/`partial`/`failed`), metrics/report invoked, files_created mirrored + deduped.

### Sub-phase 2.3 — Hooks wiring for progress output
- **Tasks:** build `ExecutionHooks` (SPEC-003 § 2.1) bridging orchestrator events to an injectable `progress` callback (default: no-op; CLI supplies Rich renderer in Phase 4); guarantee hook exceptions never abort runs.
- **Deliverable:** progress seam.
- **Exit criteria:** callback receives start/complete/fail/recovery events in order; raising callback isolated.

### Sub-phase 2.4 — Reuse, shutdown & interrupt semantics
- **Tasks:** instance reuse across runs (fresh context/plan; reused registry+client; accumulating `usage`, per SPEC-005 § 5); `close()`/context-manager support calling tool `cleanup()`; SIGINT → orchestrator interrupt contract surfaces as `failed` result with `interrupted` error.
- **Deliverable:** lifecycle robustness.
- **Exit criteria:** two sequential runs test (isolation + accumulation); cleanup called even on failure; simulated interrupt test.

### Sub-phase 2.5 — Startup warnings (SPEC-005 § 4)
- **Tasks:** one-time warnings: `.env` keys about to be transmitted (names only), missing `wkhtmltopdf` → degraded pdf note, `allow_shell=true` warning, missing API key fatal with `cp .env.example .env` remediation.
- **Deliverable:** UX warning layer.
- **Exit criteria:** each condition produces exactly one warning (deduped across runs); no secret values in any message (asserted with sensitive-pattern scan).

---

## Phase 3 — Plugin System

> Outcome: US-4 complete — drop a `BaseTool` file into a plugins dir, get it registered.

### Sub-phase 3.1 — Directory scanning & module loading
- **Tasks:** `plugins/loader.py` per SPEC-005 § 3 steps 1–3: `~` expansion, missing-dir skip, sorted deterministic scan, `importlib.util.spec_from_file_location` under synthetic module names.
- **Deliverable:** scanner core.
- **Exit criteria:** temp-dir tests: discovery order deterministic, nonexistent dir silent, non-plugin `.py` ignored.

### Sub-phase 3.2 — Class detection & instantiation conventions
- **Tasks:** steps 3–4: concrete `BaseTool` subclass detection (abstract skipped); instantiation: zero-arg → direct; `config`/`llm_client` kwargs → injected; `PLUGIN_SETTINGS: dict` → literal kwargs; else record `PLUGIN_LOAD_FAILED`.
- **Deliverable:** instantiation matrix.
- **Exit criteria:** one test per convention + uninstantiable case; discovered tools satisfy `isinstance(tool, BaseTool)` (stub base).

### Sub-phase 3.3 — Isolation, collisions & registration
- **Tasks:** steps 5–7: per-file exception isolation (returns errors, never aborts startup), built-in name collision refusal with WARNING, `auto_load=false` short-circuit; `discover_tools()` signature per spec (tuple of tools + errors).
- **Deliverable:** hardened loader.
- **Exit criteria:** poisoned-plugin test (syntax error, import error, raising constructor) → startup survives, error surfaced; collision test.

### Sub-phase 3.4 — Shipped example plugins
- **Tasks:** `plugins/example_hello.py` (HelloTool, Developer README shape) and `plugins/example_database.py` (DatabaseQueryTool: read-only SQLite, SELECT-only validation, dangerous-keyword blocking); both import from `agent_harness.tools.base` only.
- **Deliverable:** two working examples.
- **Exit criteria:** loader discovers both from the shipped dir; database tool validation rejects DROP/DELETE/INSERT with clear messages (unit tests in `tests/test_plugin_loader.py`).

### Sub-phase 3.5 — Plugin docs & security notice
- **Tasks:** `plugins/README.md`: how to write/install plugins, settings conventions, capability-tag vocabulary pointer (SPEC-002 § 4), security notice (plugins run with full user privileges; review before install; shell-capable plugins need `allow_shell`).
- **Deliverable:** plugin author guide.
- **Exit criteria:** doc example compiles as a plugin in a test (write-to-tmp → discover → register).

---

## Phase 4 — CLI

> Outcome: `python -m agent_harness` fully matching the frozen CLI contract.

### Sub-phase 4.1 — Argument parsing
- **Tasks:** `__main__.py` argparse per SPEC-005 § 2: positional prompt (optional with `--list-tools`; `-` = stdin), `--config`, `--output-dir`, `--log-level`, `--dry-run`, `--list-tools`, `--max-steps`, `--no-fallback`; flag → config override mapping via `Config.apply_overrides` (P1 seam).
- **Deliverable:** CLI parser.
- **Exit criteria:** parser table test: every flag produces the documented override; usage errors exit 2.

### Sub-phase 4.2 — Command dispatch & exit codes
- **Tasks:** dispatch: `--list-tools` → registry table + plugin-error footer, no LLM key needed (SPEC-006 K5); `--dry-run` → plan render; else `run()`; exit codes 0/1/2/3/130 per SPEC-005 § 2.1.
- **Deliverable:** dispatch layer.
- **Exit criteria:** subprocess-level tests (with stub harness via env-switchable entry or dependency-injected main) assert each exit code.

### Sub-phase 4.3 — Rich console rendering + graceful degradation
- **Tasks:** plan table (id, description, tool, priority, deps), live step progress via Phase-2.3 hooks, final report from `render_report(..., style="text")`; plain-text fallback when not a TTY or `NO_COLOR`/`TERM=dumb`.
- **Deliverable:** console UX.
- **Exit criteria:** capsys tests for both modes; no ANSI codes in piped output.

### Sub-phase 4.4 — `--no-fallback` & guard flags
- **Tasks:** implement `--no-fallback` exactly per SPEC-005 § 2 (disable replan + strip fallback tools at harness level before execution), `--max-steps` positive-int validation, log-level override chain (SPEC-006 § 1.2).
- **Deliverable:** behavior flags.
- **Exit criteria:** stub-orchestrator test proves fallback lists stripped and `enable_replan=false`; invalid `--max-steps 0` exits 2.

### Sub-phase 4.5 — CLI smoke suite
- **Tasks:** end-to-end CLI tests through `main(argv)`: dry-run, list-tools, successful run, partial run, failed run, interrupt — all with stubs and `MockLLMClient`-shaped fakes; capture stdout snapshots.
- **Deliverable:** `tests/test_cli.py` complete.
- **Exit criteria:** suite green, deterministic, zero network; snapshots reviewed against SPEC-005 § 2.

---

## Phase 5 — Integration Readiness & Handoff

> Outcome: composition verified, real-module swap checklist ready, P5 unblocked for I2/I3.

### Sub-phase 5.1 — Stub → real module swap plan (I1)
- **Tasks:** write the wiring checklist mapping every stub seam to its real symbol (`create_llm_client`, `default_tools`, `Planner`, `Orchestrator`, `Assembler`, `ExecutionMetrics.from_plan`, `render_report`, `ContextStore`, `Config.from_file`); execute the swap during the integration window; keep stubs for tests.
- **Deliverable:** swap checklist + swapped composition root.
- **Exit criteria:** `run()` against real P1–P3 modules passes the stub-era test suite unchanged (contract equivalence proof).

### Sub-phase 5.2 — Programmatic API documentation
- **Tasks:** docstring-level usage per Developer README § Python API (run, plan, register_tool, custom context, dry-run) mirrored into module docstrings; no separate docs file (P5 owns docs additions).
- **Deliverable:** self-documenting API.
- **Exit criteria:** every public method has a usage example in its docstring; doctest-style examples pass.

### Sub-phase 5.3 — Config-surface verification
- **Tasks:** audit that every `config.yaml` key (SPEC-006 § 1) is either consumed by this plan or passed to the correct layer; CLI overrides cover the documented four; unmapped keys reported as SCRs if found.
- **Deliverable:** config-consumption matrix in Handoff Note.
- **Exit criteria:** matrix complete with 0 unmapped keys (or filed SCRs).

### Sub-phase 5.4 — Troubleshooting alignment
- **Tasks:** map each Developer README troubleshooting entry (missing key, ModuleNotFoundError, wkhtmltopdf, rate limit, hang, too many steps) to a concrete CLI message/exit code/warning produced by this plan; adjust messages for clarity.
- **Deliverable:** troubleshooting conformance table.
- **Exit criteria:** each scenario reproducible with a documented command; messages name the fix.

### Sub-phase 5.5 — Definition of Done & handoff
- **Tasks:** full owned suite + coverage ≥ 80 %; ruff/mypy clean; Handoff Note for P5 (integration entry points, env-switch for CLI tests, example prompts that exercise each layer, known degraded modes) and orchestrator (I1 completion status).
- **Deliverable:** P4 conformance report + handoff.
- **Exit criteria:** SPEC-000 § 6 Definition of Done satisfied for P4.

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
