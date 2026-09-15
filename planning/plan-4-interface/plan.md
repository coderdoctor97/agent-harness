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
# ── Agent Manifest ────────────────────────────────────────────
agent_id:        P4-surface-01
name:            Surfacemaker
role:            implementer
plan:            planning/plan-4-interface/plan.md
owned_paths:                            # copied VERBATIM from SPEC-000 § 3.4
  - agent_harness/__init__.py
  - agent_harness/__main__.py
  - agent_harness/harness.py
  - agent_harness/plugins/__init__.py
  - agent_harness/plugins/loader.py
  - plugins/example_hello.py
  - plugins/example_database.py
  - plugins/README.md
  - tests/test_harness.py
  - tests/test_cli.py
  - tests/test_plugin_loader.py
owned_paths_additional:                 # plan-authorized (§ 0 Parallel-work rule); see SCR-P4-4
  - tests/_p4_stubs.py                  # disjoint from P1/P2/P3/P5 paths
consumed_specs:
  - SPEC-000   # architecture, ownership matrix, DoD
  - SPEC-001   # result / plan / metrics / AgentError types
  - SPEC-002   # § 1–2 BaseTool, ToolRegistry, default_tools
  - SPEC-003   # § 2 Orchestrator + ExecutionHooks; § 4.1 context keys; § 6 Assembler
  - SPEC-004   # § 1–2 LLMClient factory, Planner
  - SPEC-005   # harness / CLI / plugins — OWNED
  - SPEC-006   # § 1–3 config schema, redaction, startup warnings
produces:
  - "python -m agent_harness (CLI, SPEC-005 § 2)"
  - "agent_harness.AgentHarness + HarnessResult (Python API, SPEC-005 § 1)"
  - "agent_harness.plugins.loader.discover_tools (SPEC-005 § 3)"
  - "plugins/example_hello.py, plugins/example_database.py, plugins/README.md"
  - "startup warnings (SPEC-005 § 4)"
  - "integration wiring checklist for P5 (Handoff Note)"
skills_authorized:                      # registered skill IDs (§ 6); convention below
  - SKL-CORE_CODING-002   # codebase-semantic-search
  - SKL-CORE_CODING-004   # git-workflow-hygiene
  - SKL-CORE_CODING-005   # lint-formatting
  - SKL-CORE_CODING-007   # pr-code-reviewer
  - SKL-CORE_CODING-009   # strict-typing-contracts
  - SKL-CORE_CODING-010   # tdd-test-runner
  - SKL-RELIABILITY-005   # env-config-validator
  - SKL-RELIABILITY-011   # mcp-tool-builder
  - SKL-RELIABILITY-013   # secret-credential-scanner
  - SKL-RELIABILITY-015   # threat-model-sast
  - SKL-PLANNING-004      # scope-dod-enforcer
status:          active
started_at:      2026-09-14T14:01Z
last_update:     2026-09-15T12:55Z
# ──────────────────────────────────────────────────────────────
```

### Skill Dictionary — ID citation convention (agent.md § 6.4)

`agent.md` § 5/§ 6.4 require every commit and ledger row to cite a **skill ID**
(`SKL-…`), but the 50 registered skills under `.agent/skill-dictionary/<category>/<name>/SKILL.md`
carry only `name` and `description` in their frontmatter — **no `id` and no `applies_to`
field** (verified: `grep -rh -A6 '^---$' .agent/skill-dictionary/*/*/SKILL.md | grep -oE
'^[a-z_]+:'` returns only `name:` and `description:`, 50 of each).

Until the orchestrator publishes canonical IDs (SCR-P4-2), P4 cites the **deterministic
derived ID** `SKL-<CATEGORY>-<NNN>`, where `NNN` is the 1-based alphabetical index of the
skill directory inside its category (`ls -1 .agent/skill-dictionary/<category> | sort`).
Anyone can reproduce the mapping; the orchestrator can renumber it later without ambiguity.

| Derived ID | Skill | Applied by P4 for |
|---|---|---|
| SKL-CORE_CODING-002 | `core-coding/codebase-semantic-search` | impact mapping of stub seams before the I1 swap (5.1, 5.3) |
| SKL-CORE_CODING-004 | `core-coding/git-workflow-hygiene` | atomic, conventional, skill-cited commits; secret-free history |
| SKL-CORE_CODING-005 | `core-coding/lint-formatting` | `ruff check` / `ruff format` gate, idempotency + negative test |
| SKL-CORE_CODING-007 | `core-coding/pr-code-reviewer` | fixed-order self-review pass at 5.5 |
| SKL-CORE_CODING-009 | `core-coding/strict-typing-contracts` | `mypy --strict`, no `Any` leakage, boundary validation |
| SKL-CORE_CODING-010 | `core-coding/tdd-test-runner` | RED→GREEN→REFACTOR for every sub-phase; boundary matrices |
| SKL-RELIABILITY-005 | `reliability/env-config-validator` | startup warnings, precedence chain, config-surface audit (2.5, 5.3) |
| SKL-RELIABILITY-011 | `reliability/mcp-tool-builder` | LLM-facing tool names/descriptions + structured errors in example plugins (3.4) |
| SKL-RELIABILITY-013 | `reliability/secret-credential-scanner` | name-visible/value-invisible assertions; no secret in any output surface (2.5, 3.5) |
| SKL-RELIABILITY-015 | `reliability/threat-model-sast` | plugin trust-boundary assessment, mitigations, security notice (3.3, 3.5) |
| SKL-PLANNING-004 | `planning/scope-dod-enforcer` | DoD conformance evidence at 5.5 |

### Gate Record (agent.md § 6.2 — hard-stop check)

| Check | Result |
|---|---|
| Dictionary location | `.agent/skill-dictionary/<category>/<name>/SKILL.md` |
| Registered skills found | **50** (10 core-coding, 10 backend, 10 frontend, 5 planning, 15 reliability) |
| `agent.md` § 6.2 / `.agent/README.md` claim "`0` registered skills" | **STALE** — see SCR-P4-1. Hard stop **lifted**; coverage exists for every P4 change kind. |
| Index file `.agent/skills/skill-dictionary.md` | **absent** (`find` returns only the `skill-dictionary` directory) — see SCR-P4-1 |
| Coverage for first sub-phase (1.1) | SKL-CORE_CODING-010 (implement + test), -009 (typing), -005 (lint/format), -004 (commit) |
| Residual gap | untrusted dynamic-code-loading isolation — see SKR-P4-1 (`blocked: no`) |

### Toolchain used for gates

No `pyproject.toml` exists yet (P1 owns it), so gates run with explicit CLI flags against a
venv **outside** the repository (`/home/user/.venv-p4`) so no untracked files enter the tree.
See SCR-P4-5.

```text
python 3.11.2 · ruff 0.16.7 · mypy 2.3.1 · pytest 9.1.1 · pytest-cov 7.1.0 · rich 15.0.0
ruff check --target-version py39 --select E,F,W,I,UP,B,SIM,C4,RET,ARG,RUF  <owned paths>
ruff format --target-version py39 --check                                  <owned paths>
mypy --strict --ignore-missing-imports                                     <owned paths>
pytest  tests/test_harness.py tests/test_cli.py tests/test_plugin_loader.py --cov=…
```

### Phase Execution Log
| Sub-phase | State | Skill ID(s) | Note |
|---|---|---|---|
| 1.1 | **done** | SKL-CORE_CODING-010, -009, -005, -004 | Package exports + `HarnessResult` + spec-shaped stub substrate; 14 tests, ruff/mypy clean |
| 1.2 | **done** | SKL-CORE_CODING-010, -009, -005, -004 | `AgentHarness` constructor + `from_config`; 5 injectable seams honoured by identity; dirs created at init; lazy client resolution; 29 tests, 91% cov |
| 1.3 | **done** | SKL-CORE_CODING-010, -009, -005, -004 | `plan()` dry-run entry point; zero tool executions asserted via counting stub; 34 tests, 97% cov |
| 1.4 | **done** | SKL-CORE_CODING-010, -009, -005, -004 | `register_tool()` / `list_tools()`; G1 TypeError passthrough; post-run registration semantics; 41 tests, 97% cov |
| 1.5 | **done** | SKL-CORE_CODING-010, -009, -005, -004 | PROMPT_INVALID boundary matrix + documented raise/contain policy + `_failure_result`; 63 tests, 96% cov |
| 2.1 | **done** | SKL-CORE_CODING-010, -009, -005, -004 | Startup sequence (steps 1-4): fresh context, FROZEN §4.1 keys, construction order; 72 tests, 95% cov |
| 2.2 | **done** | SKL-CORE_CODING-010, -009, -005, -004 | Full `run()` pipeline (steps 5-9); containment proven end-to-end (closes 1.5's deferred assertion); 88 tests, 97% cov |
| 2.3 | **done** | SKL-CORE_CODING-010, -009, -005, -004 | `ExecutionHooks` → `progress` bridge; event order asserted; raising callback isolated + logged; 96 tests, 97% cov |
| 2.4 | **done** | SKL-CORE_CODING-010, -009, -005, -004 | Instance reuse, `close()`/context manager, SIGINT → failed result + re-raise for exit 130; 108 tests, 96% cov |
| 2.5 | **done** | SKL-RELIABILITY-005, SKL-RELIABILITY-013, SKL-CORE_CODING-010, -009, -005, -004 | SPEC-005 § 4 startup warnings: transmitted-var names, wkhtmltopdf degradation, allow_shell, missing key; 119 tests, 96% cov |
| 3.1 | **done** | SKL-CORE_CODING-010, -009, -005, -004, SKL-RELIABILITY-015 | Plugin dir scanning + module loading under synthetic names; per-file isolation from the start; 134 tests |
| 3.2 | **done** | SKL-CORE_CODING-010, -009, -005, -004 | Class detection + the injection matrix (zero-arg / config / llm_client / PLUGIN_SETTINGS / uninstantiable); 149 tests |
| 3.3 | **done** | SKL-RELIABILITY-015, SKL-CORE_CODING-010, -009, -005, -004 | Poisoned-plugin isolation, built-in collision refusal, auto_load kill switch; register_discovered helper; SCR-P4-8; 165 tests |
| 3.4 | **done** | SKL-CORE_CODING-010, -009, -005, -004, SKL-RELIABILITY-015 | Shipped examples plugins/example_hello.py + plugins/example_database.py; three-layer read-only enforcement; 196 tests |
| 3.5 | **done** | SKL-CORE_CODING-010, -005, -004, SKL-RELIABILITY-015 | plugins/README.md author guide with a compile-the-docs test; Phase 3 complete; 207 tests |
| 4.1 | **done** | SKL-CORE_CODING-010, -009, -005, -004, SKL-RELIABILITY-005 | __main__.py argparse per the FROZEN flag table; dotted-path override mapping; SCR-P4-9; 254 tests, __main__ 100% covered |
| 4.2 | **done** | SKL-CORE_CODING-010, -009, -005, -004, SKL-RELIABILITY-011 | CLI dispatch with the full exit-code table, plugin-error footer, process-level tests, plugin discovery wired into the registry; 284 tests |
| 4.3 | **done** | SKL-CORE_CODING-010, -009, -005, -004, SKL-RELIABILITY-011 | Rich tables/panels with plain-text fallback on NO_COLOR, TERM=dumb, non-TTY and missing rich; live progress on stderr; 310 tests |
| 4.4 | **done** | SKL-CORE_CODING-010, -009, -005, -004, SKL-RELIABILITY-005 | --no-fallback limits recovery to Level 1 (fallback lists stripped + replan off); CLI-to-plan proven end to end; 321 tests |
| 4.5 | **done** | SKL-CORE_CODING-010, -009, -005, -004, SKL-RELIABILITY-011 | CLI smoke suite: every documented command through main() against a real harness, all five exit codes, determinism and zero-network guards; 332 tests |
| 5.1 | pending | — | |
| 5.2 | pending | — | |
| 5.3 | pending | — | |
| 5.4 | pending | — | |
| 5.5 | pending | — | |

### Skill Ledger
| Timestamp (ISO) | Sub-phase | Files | Skill ID(s) | Change summary | Gates passed |
|---|---|---|---|---|---|
| 2026-09-14T14:12Z | 1.2 | `agent_harness/harness.py`, `tests/test_harness.py` | SKL-CORE_CODING-010 (RED: 15 failing tests first; mutation check), SKL-CORE_CODING-009 (`mypy --strict` clean, no `Any` leakage), SKL-CORE_CODING-005 (ruff), SKL-CORE_CODING-004 (atomic commit) | `AgentHarness.__init__` + `from_config('./config.yaml')`; collaborators resolved lazily by dotted name at call time (never at import), which is what makes the I1 swap a no-op; `_ensure_directories` per SPEC-005 § 1.2; `_resolve_llm_client` raises `CONFIG_VALIDATION_FAILED` naming the env var + `cp .env.example .env` remediation, while construction itself stays keyless per SPEC-006 K5 | pytest 29 passed; mutation (no-op `_ensure_directories`) caught; ruff check + format --check clean; mypy --strict 0 errors; coverage 91% |
| 2026-09-14T14:05Z | 1.1 | `agent_harness/__init__.py`, `agent_harness/harness.py`, `tests/_p4_stubs.py`, `tests/test_harness.py` | SKL-CORE_CODING-010 (RED→GREEN, boundary + mutation checks), SKL-CORE_CODING-009 (`mypy --strict`, no `Any` leakage), SKL-CORE_CODING-005 (ruff gates + idempotency), SKL-CORE_CODING-004 (atomic skill-cited commit) | Verbatim `__all__`; PEP 562 lazy exports so optional deps never break `import agent_harness`; `__version__` from dist metadata with documented fallback; `HarnessResult` dataclass per SPEC-005 § 1; stub layer installed under real dotted names only where the real module is absent (makes the I1 swap a no-op) | pytest 14 passed; mutation check caught 3/3 seeded defects; ruff check + format --check clean; mypy --strict 0 errors |

| 2026-09-14T14:28Z | 1.3 | `agent_harness/harness.py`, `tests/test_harness.py` | SKL-CORE_CODING-010 (RED: 5 failing tests first; `_FixedPlanner` fixture over mock), SKL-CORE_CODING-009 (`mypy --strict` clean), SKL-CORE_CODING-005 (ruff), SKL-CORE_CODING-004 (atomic commit) | `plan(prompt)` validates the prompt then returns `planner.plan(prompt, registry.list_tools())` with no execution (SPEC-005 § 1.1 step 5); added `_resolve_registry`/`_resolve_planner`/`_validate_prompt`/`_agent_error`. Registry build resolves the LLM client *tolerantly* so `--list-tools` stays keyless per SPEC-006 K5 (warning logged, never silent); planning and execution still raise. | pytest 34 passed; ruff check + format --check clean; mypy --strict 0 errors; coverage 97% |
| 2026-09-14T14:29Z | 1.4 | `agent_harness/harness.py`, `tests/test_harness.py` | SKL-CORE_CODING-010 (RED: 7 failing tests first; boundary matrix for instance-vs-class), SKL-CORE_CODING-009 (`mypy --strict` clean; annotated local instead of a cast at the untyped cross-plan boundary), SKL-CORE_CODING-005 (ruff), SKL-CORE_CODING-004 (atomic commit) | `register_tool(tool)` delegates to `ToolRegistry.register` so the G1 `TypeError` guard is passed through, not re-implemented; `list_tools()` returns the registry's own descriptors. Because the registry is cached, registration after a run reaches only subsequent runs (SPEC-005 § 5) - asserted by inspecting the tool list the planner received on each of two consecutive `plan()` calls. | pytest 41 passed; ruff check + format --check clean; mypy --strict 0 errors; coverage 97% |
| 2026-09-14T14:32Z | 1.5 | `agent_harness/harness.py`, `tests/test_harness.py` | SKL-CORE_CODING-010 (RED: 12 failing tests first; full boundary matrix per input type), SKL-CORE_CODING-009 (`mypy --strict` clean), SKL-CORE_CODING-005 (ruff), SKL-CORE_CODING-004 (atomic commit) | `MAX_PROMPT_CHARS=20_000` enforced on the raw prompt (padding cannot smuggle an oversized one through) counting characters not bytes; non-string inputs rejected. `RAISING_LIFECYCLE_STEPS={3,4,5}` / `CONTAINED_LIFECYCLE_STEPS={6,7,8}` make the SPEC-005 § 1.1 policy executable and tested for non-overlap. `_failure_result` returns a complete `HarnessResult` mirroring `context['errors']` and deduping `files_created` in order (SPEC-005 § 1.2). NOTE: the *end-to-end* containment assertion (run() returning a result instead of raising) needs `run()` and is completed in 2.2. | pytest 63 passed; ruff check + format --check clean; mypy --strict 0 errors; coverage 96% |
| 2026-09-14T14:36Z | 2.1 | `agent_harness/harness.py`, `tests/test_harness.py` | SKL-CORE_CODING-010 (RED: 9 failing tests first; boundary cases for path detection), SKL-CORE_CODING-009 (`mypy --strict` clean), SKL-CORE_CODING-005 (ruff), SKL-CORE_CODING-004 (atomic commit) | `_prepare_run` runs SPEC-005 § 1.1 steps 1-4 in order: validate → fresh `ContextStore` → client → registry. Context keys are asserted to equal exactly the SPEC-003 § 4.1 set. `variables` is seeded from the caller's `context` (copied, never aliased) and `allowed_read_paths` from path-shaped strings found recursively; `_looks_like_path` rejects anything containing whitespace or control characters so prose can never widen read permissions. Construction order (`create_llm_client` before `default_tools`) is asserted with recording wrappers, and an invalid prompt is proven to short-circuit before either is called. | pytest 72 passed; ruff check + format --check clean; mypy --strict 0 errors; coverage 95% |
| 2026-09-14T14:42Z | 2.2 | `agent_harness/harness.py`, `tests/test_harness.py` | SKL-CORE_CODING-010 (RED: 15 failing tests first; mutation check on the containment path), SKL-CORE_CODING-009 (`mypy --strict` clean; annotated locals instead of casts), SKL-CORE_CODING-005 (ruff), SKL-CORE_CODING-004 (atomic commit) | `run()` executes SPEC-005 § 1.1 steps 5-9. Key design: `_adopt_context` installs the per-run context as `plan.context` so the orchestrator, assembler and harness all share ONE mapping and writes cannot diverge from reads (planner-extracted variables merged in, caller-supplied winning). Steps 1-5 propagate; steps 6-8 are contained by `_contain_failure`, which logs at ERROR, appends a record carrying both the SPEC-003 § 4.1 keys and the SPEC-001 § 2.4 error identity, marks the plan FAILED and returns a complete `HarnessResult`. `except Exception` (never bare) deliberately lets `KeyboardInterrupt`/`SystemExit` through for exit code 130. Injectable `clock` keeps timing deterministic (SPEC-000 § 5.5); `last_report` holds the `logging/report.py` render. | pytest 88 passed; mutation (containment replaced by bare re-raise) caught by exactly the 2 containment tests; ruff check + format --check clean; mypy --strict 0 errors; coverage 97% |
| 2026-09-14T14:45Z | 2.3 | `agent_harness/harness.py`, `tests/test_harness.py` | SKL-CORE_CODING-010 (RED: 8 failing tests first; a `_FiringOrchestrator` that exercises all six seams), SKL-CORE_CODING-009 (`mypy --strict` clean), SKL-CORE_CODING-005 (ruff), SKL-CORE_CODING-004 (atomic commit) | `_build_hooks()` maps all six SPEC-003 § 2.1 seams onto one structured `progress(event: dict)` callback (default: silent), which is how the CLI will attach its Rich renderer in Phase 4. Isolation is implemented in BOTH layers - the orchestrator must isolate hook exceptions and the bridge isolates them again - so a broken renderer can never abort a run; the failure is logged at WARNING (`progress_callback_failed`) rather than swallowed. Hooks are attached per run, not at construction, so a cached orchestrator still reports to the current callback. | pytest 96 passed; ruff check + format --check clean; mypy --strict 0 errors; coverage 97% |
| 2026-09-14T14:47Z | 2.4 | `agent_harness/harness.py`, `tests/_p4_stubs.py`, `tests/test_harness.py` | SKL-CORE_CODING-010 (RED: 8 failing tests first; boundary tests for idempotency and failing teardown), SKL-CORE_CODING-009 (`mypy --strict`; caught that `KeyboardInterrupt` is a `BaseException` not an `Exception`), SKL-CORE_CODING-005 (ruff), SKL-CORE_CODING-004 (atomic commit) | Reuse verified: registry and client are built once across runs, contexts do not leak, usage counters accumulate (SPEC-005 § 5). `close()` is idempotent and calls `cleanup()` on every tool; a tool whose cleanup raises is logged (`tool_cleanup_failed`) and skipped so it cannot block the others. `__exit__` returns `None` so in-flight exceptions propagate. On interrupt the harness marks unfinished steps FAILED with `error='interrupted'`, records a complete failed result in `last_result`, logs `run_interrupted`, then RE-RAISES so the CLI can exit 130 - the interrupt is never swallowed (agent.md F7). Stub planner now actually calls the LLM so usage counters move. | pytest 108 passed; ruff check + format --check clean; mypy --strict 0 errors; coverage 96% |
| 2026-09-14T14:50Z | 2.5 | `agent_harness/harness.py`, `tests/test_harness.py` | SKL-RELIABILITY-005 (env-config-validator: boot-time validation, name-visible/value-invisible, precedence, log audit), SKL-RELIABILITY-013 (secret-credential-scanner: no secret value in any output surface; test uses an obviously-fake key matching the documented pattern), SKL-CORE_CODING-010 (RED: 7 failing tests first), SKL-CORE_CODING-009 (`mypy --strict`), SKL-CORE_CODING-005 (ruff), SKL-CORE_CODING-004 (atomic commit) | `_emit_startup_warnings()` emits each SPEC-005 § 4 condition at most once per instance via `_emit_once`: `credentials_transmitted` (WARNING, names only), `pdf_export_degraded` (INFO when `shutil.which('wkhtmltopdf')` is None), `shell_execution_enabled` (WARNING when `security.allow_shell`), `api_key_missing` (WARNING naming the variable plus `cp .env.example .env`). `_read_dotenv_names` reads only NAMES from a local `.env` and tolerates comments/blank/malformed lines and an unreadable file. Two tests enforce the privacy rule directly: no log record contains the fake key, and every record survives `sensitive_data_filter` with 0 matches. | pytest 119 passed; ruff check + format --check clean; mypy --strict 0 errors; coverage 96% |
| 2026-09-14T14:54Z | 3.1 | `agent_harness/plugins/__init__.py`, `agent_harness/plugins/loader.py`, `tests/test_plugin_loader.py` | SKL-CORE_CODING-010 (RED: 15 failing tests first; fixtures written to tmp_path), SKL-RELIABILITY-015 (threat-model-sast: plugin files treated as untrusted third-party code; the loader's failure contract is derived from that boundary), SKL-CORE_CODING-009 (`mypy --strict` clean over 7 files), SKL-CORE_CODING-005 (ruff), SKL-CORE_CODING-004 (atomic commit) | `_iter_plugin_files` expands `~`, skips a missing directory with a DEBUG `plugin_dir_skipped` record, visits directories in argument order and sorts files within each (so order never depends on the filesystem), and skips `_*` files. `_load_plugin_module` executes a file via `spec_from_file_location` under the synthetic name `agent_harness_plugin_<stem>` and NEVER raises - syntax errors, import errors and module-scope failures all become `AgentError(PLUGIN_LOAD_FAILED, recoverable=False)`, with the half-built module removed from `sys.modules`. NOTE: per-file isolation is implemented here rather than deferred to 3.3 because arbitrary files cannot be loaded safely without it; 3.3 adds collision refusal and the `auto_load` short-circuit. `discover_tools` matches the FROZEN signature (asserted by inspect) but returns no tools yet - class detection lands in 3.2. | pytest 134 passed; ruff check + format --check clean; mypy --strict 0 errors (7 files); loader coverage 87%, total 94% |
| 2026-09-14T14:59Z | 3.2 | `agent_harness/plugins/loader.py`, `tests/test_plugin_loader.py` | SKL-CORE_CODING-010 (RED: 11 failing tests written first, then made green; mutation check - blanking INJECTABLE_PARAMS broke exactly the 3 injection tests), SKL-CORE_CODING-009 (mypy --strict clean; inspect.signature(cls) instead of cls.__init__ to avoid the unsound-instance access mypy flags), SKL-CORE_CODING-005 (ruff), SKL-CORE_CODING-004 (atomic commit) | _find_tool_classes keeps every concrete BaseTool subclass, drops the base itself and anything still abstract, and sorts by class name so order never depends on getmembers. _build_kwargs resolves each constructor parameter by name: config/llm_client are injected, any other name is looked up in the class's PLUGIN_SETTINGS, and a defaulted parameter is left alone; a required parameter with no source yields AgentError(PLUGIN_LOAD_FAILED) naming the parameter. _instantiate wraps construction so a raising __init__ costs only its own tool. The loader now imports BaseTool itself via _base_tool_type(), so a plugin is judged against exactly the class the registry accepts. Removed the temporary noqa: ARG001 on llm_client - it is now genuinely used. | pytest 149 passed; ruff check + format --check clean; mypy --strict 0 errors (7 files); loader coverage 91%, total 94% |
| 2026-09-14T15:02Z | 3.3 | `agent_harness/plugins/loader.py`, `tests/test_plugin_loader.py`, `planning/plan-4-interface/plan.md` (SCR-P4-8) | SKL-RELIABILITY-015 (threat-model-sast: deny-by-default registration, zero silent suppression, hostile-property guard), SKL-CORE_CODING-010 (RED: 9 failing tests; mutation check - removing the collision guard broke exactly the 3 collision tests), SKL-CORE_CODING-009 (mypy --strict clean), SKL-CORE_CODING-005 (ruff), SKL-CORE_CODING-004 (atomic commit) | register_discovered(registry, tools, *, logger) refuses any name already in the registry, logging WARNING plugin_name_collision, because SPEC-002 G2 would otherwise let a plugin overwrite a built-in; the run() lifecycle registers default_tools() first, so order is what protects built-ins. _safe_tool_name guards the plugin-authored name property, so a tool that raises from name becomes an error record instead of crashing discovery or the log line. Poisoned-plugin corpus proven contained: syntax error, failing import, raising constructor, raising name property - four bad files yield four AgentError(PLUGIN_LOAD_FAILED, recoverable=False) and zero tools, and discovery still returns. auto_load=false returns before any import happens (asserted via sys.modules). SCR-P4-8 filed: step 5 cannot run inside the FROZEN discover_tools signature, so registration is a sibling helper. | pytest 165 passed; ruff check + format --check clean; mypy --strict 0 errors (7 files); loader coverage 94%, total 95% |
| 2026-09-14T15:08Z | 3.4 | `plugins/example_hello.py`, `plugins/example_database.py`, `tests/test_plugin_loader.py` | SKL-RELIABILITY-015 (threat-model-sast: a DB tool is the highest-risk plugin, so three independent layers; mutation-checked), SKL-CORE_CODING-010 (29 acceptance tests; three mutation checks prove the controls bite), SKL-CORE_CODING-009 (mypy --strict clean over 9 files; ClassVar for PLUGIN_SETTINGS), SKL-CORE_CODING-005 (ruff), SKL-CORE_CODING-004 (atomic commit) | HelloTool is the Developer README's minimal shape (name/description/capabilities verbatim) with a real validate_input gate. DatabaseQueryTool takes db_path supplied by PLUGIN_SETTINGS so the loader can build it, and enforces read-only at three independent layers: (1) driver - connection opened mode=ro plus PRAGMA query_only=ON, so SQLite itself refuses a write even if validation were bypassed; (2) statement - one statement only, comments and string literals stripped before scanning; (3) keyword - word-boundary matching over a superset of the README list (adds ATTACH, DETACH, PRAGMA, REPLACE, TRUNCATE, VACUUM, ANALYZE, REINDEX), so created_at is not rejected for containing CREATE and 'DROP me a line' inside a literal is not mistaken for a statement. Both files carry a documented temporary type: ignore[misc] on the BaseTool subclass line because Plan 2's module does not exist until I1; it is listed on the 5.1 swap checklist. | pytest 196 passed; ruff check + format --check clean; mypy --strict 0 errors (9 files); example_database 91%, example_hello 96%, total 95%. Mutation checks: removing mode=ro + query_only -> 2 failures; substring instead of word-boundary keyword match -> 1 failure; removing the single-statement check -> 1 failure; restored -> 77 passed |
| 2026-09-14T15:11Z | 3.5 | `plugins/README.md`, `tests/test_plugin_loader.py` | SKL-CORE_CODING-010 (12 doc tests, one of which compiles and executes the README's own code block; mutation check - changing text.split() to text.split(',') inside the README block failed the docs test), SKL-RELIABILITY-015 (security notice states the no-sandbox reality, the review-before-install rule and that a plugin spawning subprocesses bypasses the shell whitelist entirely), SKL-CORE_CODING-005 (ruff), SKL-CORE_CODING-004 (atomic commit) | Eight sections: where plugins live (dirs, ~ expansion, sorted *.py, _ prefix skip, auto_load kill switch); the BaseTool contract table R1-R8 plus ToolResult; the three construction conventions with a PLUGIN_SETTINGS example; the failure contract table (what becomes AgentError, what is silently skipped, what loses a collision); the security notice; a complete copyable plugin fenced between BEGIN/END-COPYABLE-PLUGIN markers; manual registration; and a troubleshooting table keyed to the log events an author will actually see. TestReadmeExampleCompiles extracts the marked block, writes it to tmp, discovers it, registers it and asserts the arithmetic - so the documented example cannot drift from working code. TestReadmeContent asserts the guide covers dirs, PLUGIN_SETTINGS, the SPEC-002 4 capability vocabulary, the security notice, security.allow_shell, and the three plugin log events. | pytest 207 passed; ruff check + format --check clean; mypy --strict 0 errors (9 files); total coverage 95%. Mutation check: breaking the README's fenced block failed test_the_documented_plugin_actually_works; restored -> 88 plugin tests pass |
| 2026-09-14T15:16Z | 4.1 | `agent_harness/__main__.py`, `tests/test_cli.py` (new), `planning/plan-4-interface/plan.md` (SCR-P4-9) | SKL-CORE_CODING-010 (RED: 47 CLI tests written against a module that did not exist; two mutation checks), SKL-RELIABILITY-005 (env-config-validator: env vars validated - an invalid AGENT_HARNESS_LOG_LEVEL is ignored rather than corrupting the config, an empty AGENT_HARNESS_CONFIG is treated as unset), SKL-CORE_CODING-009 (mypy --strict clean over 11 files), SKL-CORE_CODING-005 (ruff), SKL-CORE_CODING-004 (atomic commit) | build_parser() reproduces the FROZEN usage line exactly (asserted whitespace-normalised, since argparse re-wraps to terminal width): metavars PATH/DIR/LEVEL/N and [prompt] as specced. --max-steps uses a _positive_int type so 0, negatives and non-integers all exit 2 with a message naming the flag. --log-level uses a custom type rather than choices so lowercase input is accepted while the stored value stays canonical. parse_args enforces the one cross-flag rule - prompt required unless --list-tools. read_prompt handles '-' as stdin, strips it, and exits 2 on empty input; a literal '-' inside a longer prompt is left alone. resolve_config_path is flag > AGENT_HARNESS_CONFIG > ./config.yaml. collect_overrides emits dotted paths only for flags the user passed, and apply_cli_overrides prefers config.apply_overrides when present (the seam 4.1 names) with typed-attribute assignment as the fallback - see SCR-P4-9. Exit-code constants EXIT_OK/FAILED/USAGE/PARTIAL/INTERRUPTED are declared now for 4.2. No main() yet: dispatch is sub-phase 4.2. | pytest 254 passed (47 new CLI tests); ruff check + format --check clean; mypy --strict 0 errors (11 files); __main__.py 100% covered, total 95%. Mutation checks: allowing max_steps=0 -> 2 failures; making the env log level beat the flag -> 1 failure; restored -> 47 passed |
| 2026-09-14T15:22Z | 4.2 | `agent_harness/__main__.py`, `agent_harness/harness.py`, `tests/test_cli.py` | SKL-CORE_CODING-010 (RED: 30 new tests against a nonexistent main(); two mutation checks), SKL-RELIABILITY-011 (graceful-degradation: harness.close() in a finally so tool cleanup runs on success, failure and interrupt alike), SKL-CORE_CODING-009 (mypy --strict clean over 11 files), SKL-CORE_CODING-005 (ruff), SKL-CORE_CODING-004 (atomic commit) | main(argv, *, harness_factory=None) parses, resolves the prompt, loads+overrides config, then dispatches to _cmd_list_tools / _cmd_dry_run / _cmd_run. STATUS_EXIT_CODES maps completed/partial/failed to 0/3/1; KeyboardInterrupt -> 130; an escaping AgentError -> 1 with the code and message on stderr; argparse SystemExit -> its own code (0 for -h, 2 for a usage error). close() runs in a finally on every path. AgentError is caught via a lazily-resolved type so no cross-plan import happens at module scope. The harness now completes SPEC-005 1.1 step 4: _load_plugins registers discovered plugins AFTER default_tools, which is what makes the collision rule work, and records failures on harness.plugin_errors for the --list-tools footer. Rendering is deliberately plain text here; 4.3 adds Rich. Six tests run the real entry point in a fresh interpreter via runpy/subprocess, including python -m agent_harness --help, a usage error at exit 2, --list-tools at exit 0 with no OPENAI_API_KEY, and a run at exit 1 when the key is absent. | pytest 284 passed (77 CLI); ruff check + format --check clean; mypy --strict 0 errors (11 files); __main__ 96% covered, total 95%. Mutation checks: mapping partial->0 broke exactly test_partial_exits_three; removing the finally close() broke the 3 teardown tests; restored -> 77 passed |
| 2026-09-14T15:32Z | 4.3 | `agent_harness/__main__.py`, `agent_harness/harness.py`, `tests/test_cli.py` | SKL-RELIABILITY-011 (graceful-degradation: four independent reasons to fall back to plain text, and a vanished console cannot abort a run), SKL-CORE_CODING-010 (RED: 26 new tests; two mutation checks), SKL-CORE_CODING-009 (mypy --strict clean over 11 files), SKL-CORE_CODING-005 (ruff), SKL-CORE_CODING-004 (atomic commit) | use_rich(stream) returns True only when rich imports, the stream is a TTY, NO_COLOR is not set to a non-empty value and TERM is not dumb - any one of those degrades to plain text. The three renderers take rich=False and have styled counterparts (_rich_tools_table, _rich_plan_table, _rich_result_panel) rendered through _rich_string, which uses force_terminal + export_text(styles=True) because it writes to a buffer, not the real stream. main() evaluates the decision once and passes it down. _live_progress builds the callback installed via the new AgentHarness.set_progress; it writes to STDERR so a piped stdout still carries only the deliverable, prints one line per known orchestrator event via PROGRESS_LINES, prints nothing for unknown events so a future event cannot crash an older CLI, and swallows OSError so a dead console cannot abort a run. _cmd_run additionally prints the SPEC-006 7 execution report via render_report(plan, metrics, style='text'), contained so a reporting failure cannot change the exit code. NOTED: pytest replaces sys.stdout after fixtures run, so patching it in a fixture cannot work - the styled dispatch tests patch the use_rich decision point instead, with detection covered separately. | pytest 310 passed (103 CLI); ruff check + format --check clean; mypy --strict 0 errors (11 files); __main__ 94% covered, total 94%. Mutation checks: removing the NO_COLOR check broke test_no_color_forces_plain; blanking the progress template broke the 2 progress-rendering tests; restored -> 103 passed |
| 2026-09-14T15:36Z | 4.4 | `agent_harness/harness.py`, `tests/test_harness.py`, `tests/test_cli.py` | SKL-CORE_CODING-010 (RED: 2 failing tests first; mutation check - removing the policy call broke exactly the 2 harness tests and the CLI end-to-end test), SKL-RELIABILITY-005 (env-config-validator: the log-level chain CLI > env > file > defaults asserted at the harness boundary, not just at the parser), SKL-CORE_CODING-009 (mypy --strict caught a real defect - see notes), SKL-CORE_CODING-005 (ruff), SKL-CORE_CODING-004 (atomic commit) | AgentHarness._apply_recovery_policy runs between planning and execution: when config.execution.enable_replan is false it clears every step's fallback_tools. Keying off the config rather than a separate CLI flag means a user who sets enable_replan: false in config.yaml gets identical behaviour, and it is one switch with two consequences - Level 3 (replan) is off because the orchestrator reads the same flag, Level 2 (fallback tools) is off because the lists are removed here, leaving Level 1 exactly as SPEC-005 2 promises. Only the fallback list is mutated; tool, description and dependencies are asserted unchanged. CAUGHT BY MYPY: the first draft of the orchestrator double assigned StepStatus.COMPLETED, which does not exist in SPEC-001 1.1 (the member is SUCCESS). The tests still passed because the AttributeError was contained by the harness and orchestrator.seen was already populated - a false green. Fixed, and the tests now also assert result.status == 'completed' so a contained failure can never masquerade as a pass again. | pytest 321 passed (110 CLI); ruff check + format --check clean; mypy --strict 0 errors (11 files); total coverage 95%. Mutation check: removing the _apply_recovery_policy call broke test_fallbacks_are_stripped_when_replan_is_disabled, test_the_policy_is_applied_per_run and test_no_fallback_strips_the_fallback_lists; restored -> all green |
| 2026-09-15T12:55Z | 4.5 | `tests/test_cli.py` | SKL-CORE_CODING-010 (11 smoke tests through main() against a REAL AgentHarness, not a double; the failed-run scenario was a genuine false green until fixed - see notes), SKL-RELIABILITY-011 (graceful-degradation: determinism and zero-network guards), SKL-CORE_CODING-009 (mypy --strict clean over 11 files), SKL-CORE_CODING-005 (ruff), SKL-CORE_CODING-004 (atomic commit) | TestCliSmoke drives every documented command through main(): --list-tools (exit 0, registry table), --dry-run (exit 0, five-column plan table, dependency edge rendered), successful run (exit 0, deliverable + status line), partial run (exit 3), failed run (exit 1), interrupt (exit 130 with a note on stderr), '-' reading the prompt from stdin into the planner, a genuinely broken plugin file surfacing in the --list-tools footer through the real discovery path, and byte-identical stdout across two identical invocations. TestNoNetwork monkeypatches socket.socket and socket.create_connection to raise, then runs list-tools, dry-run and a full run, so any future network call fails the suite rather than making a call. DEFECT FOUND AND FIXED: the first draft of _SmokeOrchestrator marked step 0 successful for every outcome, so the 'failed' scenario produced a partial result and exited 3 instead of 1 - the stub assembler calls a run partial as soon as one step succeeds. Fixed, with the reason recorded in the docstring. | pytest 332 passed; ruff check + format --check clean; mypy --strict 0 errors (11 files); total coverage 95%. Process-level re-check after rebuilding the toolchain: `python -m agent_harness --help` prints the FROZEN usage line and exits 0; no arguments exits 2; `--max-steps 0` exits 2 |
### Spec/Skill Change Requests

**SCR-P4-9** — plan-4 § 4.1 vs. SPEC-006 § 1.1 — *problem:* sub-phase 4.1 maps CLI flags
onto config "via `Config.apply_overrides` (P1 seam)", but the FROZEN `Config` surface in
SPEC-006 § 1.1 declares only `from_file`, `from_dict`, attribute access, `get()` and
`to_dict()`. `apply_overrides` is not in the spec, so P1 is not obliged to provide it.
*resolution applied:* `apply_cli_overrides()` builds a dotted-path mapping
(`execution.output_dir`, `execution.max_steps`, `logging.level`,
`execution.enable_replan`) and calls `config.apply_overrides(mapping)` when the attribute
exists, falling back to direct typed-attribute assignment on the section dataclass when it
does not. Both paths write identical keys, so the CLI behaves the same either way and the
I1 swap needs no CLI change. *proposed change:* add
`config.apply_overrides(mapping: dict[str, Any]) -> None` to SPEC-006 § 1.1, or strike the
reference from plan-4 § 4.1. *blocking:* **no.**

**SCR-P4-8** — SPEC-005 § 3 step 5 vs. the FROZEN `discover_tools` signature — *problem:*
step 5 says discovery must "register discovered instances with the registry; name collisions
with built-ins are refused", but the FROZEN signature in the same section takes no registry
(`plugin_dirs, *, config, llm_client, logger`), so registration cannot happen inside
`discover_tools`. *resolution applied:* registration lives in a sibling public helper
`agent_harness/plugins/loader.py:register_discovered(registry, tools, *, logger=None)
-> list[BaseTool]`, called by the harness at `run()` lifecycle step 4 after
`default_tools()` has populated the registry. The FROZEN signature is untouched. The helper
also guards `tool.name`, because that property is plugin-authored and may raise.
*proposed change:* add `register_discovered` to SPEC-005 § 3, or add a keyword-only
`registry=None` parameter to `discover_tools` and let it register when supplied.
*blocking:* **no.**

**SCR-P4-1** — `agent.md` § 6.1/§ 6.2, `.agent/README.md`, `planning/README.md` § 2.3 —
*problem:* all three point the skill gate at `.agent/skills/skill-dictionary.md`, which does
not exist, and § 6.2 asserts "0 registered skills", which is false: 50 skills are registered
under `.agent/skill-dictionary/<category>/<name>/SKILL.md`. *proposed change:* repoint the
three references to the actual directory and replace the § 6.2 hard-stop text with a live
count. *blocking:* **no** — P4 verified coverage directly and proceeded.

**SCR-P4-2** — `agent.md` § 6.1(2), § 6.3, § 6.4 vs. the registered `SKILL.md` frontmatter —
*problem:* the gate and the ledger both require machine-citable skill **IDs** and an
`applies_to` field; registered skills expose neither (only `name`, `description`).
*proposed change:* add `id:` and `applies_to:` (path globs + change kinds) to every
`SKILL.md` frontmatter. *interim:* P4 uses the derived-ID convention documented above.
*blocking:* **no.**

**SCR-P4-3** — SPEC-005 § 3 vs. Developer README § Plugin Auto-Discovery — *problem:* the
vision's snippet declares `discover_tools(plugin_dirs) -> list[type[BaseTool]]` (classes),
while FROZEN SPEC-005 § 3 declares
`discover_tools(plugin_dirs, *, config=None, llm_client=None, logger=None) -> tuple[list[BaseTool], list[AgentError]]`
(instances + errors). *resolution applied:* the spec wins (SPEC-000 § 3 conflict rule); P4
implements the SPEC-005 signature. *proposed change:* add a note to the Developer README
(P5 owns doc additions) that the shipped loader returns instances and errors.
*blocking:* **no.**

**SCR-P4-4** — SPEC-000 § 3.4 — *problem:* the plan's § 0 Parallel-work rule assigns
`tests/_p4_stubs.py` to P4, but § 3.4 does not list it, so strictly the file is outside the
ownership matrix. It is disjoint from every other plan's paths (P1 owns `tests/test_config.py`
…, P5 owns `tests/conftest.py` + `tests/integration/`), so there is no conflict.
*proposed change:* add `tests/_p4_stubs.py` to § 3.4. *blocking:* **no.**

**SCR-P4-5** — SPEC-000 § 4 / SPEC-006 § 1 — *problem:* `pyproject.toml` (P1) does not exist
during parallel execution, so there is no committed ruff/mypy/coverage configuration for the
gates, and `rich` is not yet a declared dependency. *proposed change:* P1 lands the
`pyproject.toml` with ruff/mypy/pytest-cov config and `rich>=13`; P5 wires the CI gate from
it. *interim:* P4 runs the gates with the explicit CLI flags recorded above.
*blocking:* **no.**

**SCR-P4-7** — SPEC-005 § 4 vs. SPEC-006 K5 — *problem:* SPEC-005 § 4 makes a missing API
key "Fatal at harness init", but SPEC-006 K5 requires the missing key to be detected at
`create_llm_client()` time so that `--list-tools` works without credentials — and
`--list-tools` must construct a harness to list the registry. The two cannot both hold.
*resolution applied:* construction does **not** raise; `AgentHarness._resolve_llm_client()`
raises `AgentError(CONFIG_VALIDATION_FAILED)` on first use, keeping SPEC-005 § 4's
remediation text (`cp .env.example .env`) and satisfying K5's keyless-listing requirement.
*proposed change:* reword SPEC-005 § 4 row 4 to "fatal at first LLM use (harness `run()`),
not at init". *blocking:* **no.**

**SCR-P4-6** — SPEC-001 § 2.4 vs. SPEC-004 § 1.3 / SPEC-006 K5 / SPEC-005 § 1.1, § 2.1 —
*problem:* `AgentError` is specified under "Dataclasses" as a plain `@dataclass`, yet the
specs `raise` it in at least four places ("raises `AgentError(code="CONFIG_VALIDATION_FAILED")`",
"unhandled `AgentError`" as CLI exit 1). A plain dataclass cannot be raised — verified:
`TypeError: exceptions must derive from BaseException`. *resolution applied:* the P4 stub
declares `@dataclass class AgentError(Exception)`, which satisfies both the dataclass shape
(`to_dict()`, `__str__`, field order) and the raise sites. *proposed change:* SPEC-001 § 2.4
should state that `AgentError` inherits `Exception`; **Plan 1 must do the same**, otherwise
the composition root's `except AgentError` paths and the CLI's exit-code 1 mapping cannot
work at I1. *blocking:* **no** for P4 (stub conforms), but it is an I1 blocker for the
composed system.

**SKR-P4-1:**
```yaml
needed_for:     3.1–3.3 — plugin auto-discovery: loading untrusted *.py via importlib,
                per-file exception isolation, built-in name-collision refusal
change_kind:    implement
target_paths:   agent_harness/plugins/loader.py
gap:            No registered skill covers *implementing* isolation controls for
                dynamically loaded third-party code. `threat-model-sast` (SKL-RELIABILITY-015)
                explicitly delegates "implementing individual controls" out of scope; it
                covers the assessment and mitigation tracking only. `auth-security`
                (SKL-BACKEND-001) is authN/authZ, not code loading. SPEC-006 § 4 sandbox is
                P2's code_execute sandbox, not the plugin loader.
proposed_skill: "untrusted-code-loader-isolation" — scope: importing/executing third-party
                modules at runtime (importlib, entry points, hot reload). Directives: (1)
                never let one module's failure abort host startup; (2) deny-by-default name
                registration — host namespaces win over plugin names; (3) synthetic module
                names + explicit sys.modules policy to avoid clobbering; (4) no silent
                suppression — every swallowed failure becomes a typed, surfaced error;
                (5) privilege statement in author-facing docs. Gates: poisoned-module test
                corpus (syntax error, import error, raising constructor, abstract-only class,
                name collision) + host-survival assertion + zero-silent-swallow audit.
blocked:        no (partial work continuing on 3.1–3.3 under the composition
                SKL-CORE_CODING-010 + SKL-CORE_CODING-009 + SKL-RELIABILITY-015;
                orchestrator to adjudicate whether that composition satisfies § 6.1(2)
                or whether the dedicated skill must be registered first)
```

### Handoff Note
_Written at Phase 5.5._
