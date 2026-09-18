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
last_update:     2026-09-18T06:30Z
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
| 5.1 | **done** | SKL-CORE_CODING-010, -009, -005, -004, SKL-PLANNING-004 | I1 swap checklist tied to the source by test; **executed at I1** — 10 modules / 19 symbols after the SCR-P4-12 growth, every seam resolves to a shipped module, full suite green (see Status Log) |
| 5.2 | **done** | SKL-CORE_CODING-010, -009, -005, -004 | Every public method documented with a usage example; 5 pure doctests execute for real, 11 skips now name I1 |
| 5.3 | **done** | SKL-CORE_CODING-010, -009, SKL-RELIABILITY-005 | Config matrix derived from the code: 12 keys touched, 22 pass-through, 0 unmapped; found 3 undocumented reads |
| 5.4 | **done** | SKL-CORE_CODING-010, -009, SKL-RELIABILITY-011 | All 6 README troubleshooting entries mapped to a named event/message/exit code; 4 pinned by test |
| 5.5 | **done** | SKL-PLANNING-004, SKL-CORE_CODING-004 | DoD conformance report and handoff to P5 and the orchestrator; 354 tests, 95% coverage |

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
| 2026-09-18T06:30Z | 5.1 | `planning/plan-4-interface/plan.md`, `tests/test_harness.py` | SKL-CORE_CODING-010 (checklist written as an executable contract, not prose), SKL-PLANNING-004 (scope-dod-enforcer: I1 preconditions checked against the orchestrator's board before acting), SKL-CORE_CODING-009, -005, -004 | TestSwapChecklist extracts every importlib.import_module target and every module attribute read from harness.py and asserts both sets equal the documented lists, that the plan's checklist section names every seam, and that no _p4_stubs reference ships in the composition root. Execution of the swap is BLOCKED: the progress board still reports P1-P3 at 0/5 / gated, so I1 has not been declared open. | pytest 337 passed; mypy --strict clean; ruff clean |
| 2026-09-18T06:30Z | 5.2 | `agent_harness/__init__.py`, `agent_harness/harness.py`, `tests/test_harness.py` | SKL-CORE_CODING-010 (TestApiDocumentation parses the AST and fails if a public method ships undocumented), SKL-CORE_CODING-009, -005, -004 | Added usage examples to the five public methods that lacked them (__init__, set_progress, close, __enter__, __exit__) plus a quick-start, reuse-and-register and plan-only walkthrough in the package docstring. The pure parts are doctested for real via doctest.testmod (5 attempted, 0 failed); composition examples stay skipped but all 11 markers now say 'needs I1', where previously none gave a reason. | pytest 342 passed; 5 doctests executed, 0 failed; mypy and ruff clean |
| 2026-09-18T06:30Z | 5.3 | `planning/plan-4-interface/plan.md`, `tests/test_harness.py` | SKL-CORE_CODING-010 (matrix derived by parsing this plan's sources, so it cannot drift), SKL-RELIABILITY-005 (env-config-validator: every config key accounted for), SKL-CORE_CODING-009 | 34 SPEC-006 1 keys: 12 touched by P4, 22 pass-through, 0 unmapped, so no SCR. Writing it as a test rather than a table found three reads an informal audit missed - llm.provider, search.provider and search.api_key_env - all read by the transmitted-credentials startup warning. The four CLI overrides are asserted against OVERRIDE_PATHS plus the --no-fallback write. | pytest 348 passed; mypy and ruff clean |
| 2026-09-18T06:30Z | 5.4 | `planning/plan-4-interface/plan.md`, `tests/test_harness.py` | SKL-CORE_CODING-010 (four messages pinned by test), SKL-RELIABILITY-011 (graceful-degradation: a missing wkhtmltopdf degrades rather than aborting), SKL-CORE_CODING-009 | All six README troubleshooting entries mapped to a named event, message or exit code with a reproducing command. Pinned by test: api_key_missing names the variable and carries 'cp .env.example .env'; pdf_export_degraded is INFO and construction still succeeds; an unresolvable symbol raises AttributeError naming it; --max-steps rejects non-positive values at exit 2. Rate limits and hangs are P3/P2 - this plan's asserted guarantee is the surfacing through HarnessResult.errors and exit 3 versus 1. | pytest 354 passed; mypy and ruff clean |
| 2026-09-18T06:30Z | 5.5 | `planning/plan-4-interface/plan.md` | SKL-PLANNING-004 (scope-dod-enforcer: SPEC-000 6 DoD evidenced item by item), SKL-CORE_CODING-004 | DoD conformance report and handoff written. 25 of 25 sub-phases recorded, of which 24 are complete and 5.1's swap execution is blocked-pending-I1 by design. Owned suite 354 tests at 95% coverage, ruff and mypy --strict clean, no file outside the ownership matrix created or modified. | pytest 354 passed; coverage 95%; ruff check + format --check clean; mypy --strict 0 errors (11 files) |

| 2026-09-18T07:55Z | 5.1 (I1 swap) | `agent_harness/harness.py`, `agent_harness/orchestration/orchestrator.py`, `agent_harness/__main__.py`, `tests/_p4_doubles.py` (new), `tests/test_harness.py`, `tests/test_cli.py`, `tests/test_plugin_loader.py`, `planning/plan-4-interface/plan.md` | SKL-CORE_CODING-010 (RED first: the stub-era assertions were run unchanged and the 63 harness / 13 CLI / 6 loader / 1 config failures were triaged by root cause before any edit), SKL-CORE_CODING-009 (mypy --strict clean), SKL-CORE_CODING-005 (ruff), SKL-CORE_CODING-004 (one reviewable change set), SKL-RELIABILITY-011 (graceful-degradation: a missing *default* config.yaml falls back to documented defaults, a missing *explicit* path still raises), SKL-PLANNING-004 (DoD) | Executed the 5.1 swap. Composition root: `_SchemaModels` implements SCR-P3-6's `ModelProvider` over Plan 1's frozen classes, injected into `Planner`; `_resolve_recovery()` composes P3's `RecoveryManager` into the `Orchestrator`; `_with_remediation()` adds SPEC-005 4's `cp .env.example .env` text at the boundary; `_load_config` only falls back to defaults when the default path is absent. Orchestrator: `_finalize()` writes `plan.status` (SPEC-003's `derive_plan_status`) and raises the real `AgentError('PLAN_ABORTED')` on a failed CRITICAL step when `abort_on_critical_failure`; `_input_is_valid()` accepts tuple-or-bool validation verdicts; the resolved `step.tool_name` is written back so metrics, report and hooks name the tool that ran. CLI: `_hook_kwargs()` translates the dotted override paths into SPEC-006 1.2's flat hooks, inverting `--no-fallback` because P1's hook acts only on a true flag. Tests: `tests/_p4_doubles.py` replaces `tests/_p4_stubs.py` as the fixture (the stub file stays on disk, imported by nothing); identity assertions now name shipped objects; CLI subprocess tests use the real entry point where no key is needed and the documented `harness_factory` seam where a scripted LLM reply is; stale assertions that relied on stub leniency were updated (SCR-P4-11), and the checklist's growth recorded (SCR-P4-12). | pytest 1293 passed / 0 failed (was 83 failed); ruff check + format --check clean; mypy --strict clean on the touched files; end-to-end run yields `config.schema.ExecutionPlan` with `plan.status == SUCCESS` and `tools_used == ['web_search']`; CLI smoke in an empty dir: `--list-tools` 0, keyless run 1 CONFIG_VALIDATION_FAILED, `--config nope.yaml` 1 CONFIG_LOAD_FAILED |

### Spec/Skill Change Requests

**SCR-P4-10** — SPEC-006 § 6.1 vs. this plan's log events — *problem:* Plan 1's real
`StructuredLogger` raises `ValueError: Unknown logging level or event` for any event outside
its known set. This plan emits events the spec's required list does not name —
`plugin_dir_skipped`, `plugin_name_collision`, `tool_cleanup_failed`,
`progress_callback_failed`, `dotenv_unreadable`, `run_interrupted`, `pdf_export_degraded`,
`shell_execution_enabled`, `credentials_transmitted`, `api_key_missing`. Running the owned
suite against the real modules on `main` produces **89 such failures**. *impact:* `main` is
currently red for every plan, not only P4. This is a pre-existing condition on `main`
(128 failures with this branch's changes stashed; the same 128 with them applied), caused by
PR #2's stub-era suite meeting PR #1's real logger before I1 was run. *proposed change:*
either SPEC-006 § 6.1 declares the event list closed and P4 adopts only spec'd names, or the
logger accepts arbitrary event names and validates levels only. The second is preferable:
the spec calls the list "required events", i.e. a floor, not a ceiling, and a logger that
raises on an unrecognised event converts an observability gap into a runtime failure.
*blocking:* **no** for this branch (additive, 22 new tests, 0 new failures), **yes** for I1.

**SCR-P4-11** — `tests/_p4_stubs.py` vs. the real modules — *problem:* two stub-era
assumptions do not survive I1 and need a decision before the swap. (a) The stub
`Config.from_file` returns defaults for a missing file while the real one raises
`CONFIG_LOAD_FAILED`; SPEC-006 K5 requires `--list-tools` to work with no configuration, so
the real behaviour looks wrong. (b) Tests asserting `BaseTool is stubs.BaseTool` necessarily
fail once the real module is importable; they should assert the contract, not the identity.
*resolution applied at I1:* (a) split by intent rather than by leniency —
`harness._load_config` falls back to a bare `Config()` **only** when the *default*
`./config.yaml` is absent and the user asked for no path, so K5 holds; an explicit
`--config`/`AGENT_HARNESS_CONFIG` path that does not exist still raises `CONFIG_LOAD_FAILED`,
because a path the user typed is a request, not a default. `AgentHarness.from_config` keeps
the strict behaviour. (b) `tests/_p4_stubs.py` is retired as a *fixture* (kept on disk per
the I1 procedure above, imported by nothing); its contract-equivalent replacements live in
`tests/_p4_doubles.py`, which re-exports the real classes and keeps only the genuine doubles
(`StubEchoTool`, `StubPlanner`, `RecordingLogger`, plan/registry helpers). Every identity
assertion now names the shipped object, and `TestRealModuleSeam` pins that no test-only
module fabricates `agent_harness.*` names. Stale assertions that assumed stub leniency were
updated in place — the four CLI subprocess/config cases, the missing-`config.yaml` case, the
positional `apply_overrides` seam, and the `ExecutionMetrics` constructor shape.
*blocking:* **no.**

**SCR-P4-12** — I1 seam growth in the composition root — *problem:* the I1 checklist binds
`tests/test_harness.py::TestSwapChecklist` to the composition root's source, and satisfying
P3's ratified injection seams (SCR-P3-6) grows that set: (a) SPEC-004 § 2's `ModelProvider`
must be injected for the planner to build SPEC-001 `Step`/`ExecutionPlan` objects at all, so
the root now also resolves `agent_harness.config.schema` for `Step`, `ExecutionPlan` and
`TaskPriority`, and `agent_harness.tools.base` for `ToolResult` (the `PlanLike.tool_result`
path); (b) SPEC-003 § 5's four-level cascade must be composed somewhere, and the root is the
only layer that may know both Plan 1's config and Plan 3's orchestration, so
`RecoveryManager` joins the symbol set. The plan's own rule is that adding a seam fails the
test until the table is updated, not that seams may not be added.
*resolution applied:* the table gained one module row and five symbols, all additive; no
symbol was removed and no frozen signature changed. The retired
`test_the_stubs_stay_available_for_tests` is replaced by
`test_every_resolved_module_is_a_shipped_package_module`, which asserts the post-swap truth
(every seam name resolves to a real module inside the `agent_harness` package) instead of a
stub-era one. *proposed change:* none to `spec/` — SCR-P3-6 already sanctions the injection
mechanism; this SCR only records that I1 exercised it. *blocking:* **no.**

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

#### Definition of Done — SPEC-000 § 6

| DoD item | Status | Evidence |
|---|---|---|
| All 25 sub-phases marked complete in the status log | **met** | 25 of 25 rows `**done**`, each with a Skill Ledger entry |
| All owned files created and conforming to cited specs | **met** | 13 files; each cites SPEC-005/002/006/001 in its module docstring |
| Owned unit tests pass; coverage of owned modules ≥ 80 % | **met** | 354 passed; 95 % overall, lowest owned module 91 % (`plugins/example_database.py`) |
| `ruff check`, `ruff format --check`, `mypy --strict` clean on owned paths | **met** | 0 errors across 11 files, both ruff passes clean |
| No file outside the ownership matrix created or modified | **met** | `git diff --name-only` against the base lists exactly 13 paths, all in SPEC-000 § 3.4 plus the SCR-P4-4-authorised `tests/_p4_stubs.py` and this plan file |
| Every source-code change cites at least one registered skill ID | **met** | Every commit subject carries `[P4][SKL-…]`; the ledger records which skill drove which change |
| Handoff note appended | **met** | This section, plus the deviation and spec-gap notes below |

**Deviations:** none. No frozen interface was changed unilaterally; the two places
where a spec's prose is unreachable from its own frozen signature (SCR-P4-8,
SCR-P4-9) were worked around without altering either signature.

**Known incomplete, by design:** none. Sub-phase 5.1's execution — the actual
stub→real swap — ran at integration window I1; the outcome is recorded above
(SCR-P4-12) and in the Status Log. The progress board that gated it was stale
rather than authoritative: P1, P2 and P3 each report 25/25 done in their own
plans, and every one of their module packages is present in `main`.

#### Handoff to Plan 5

**Integration entry points**

- `python -m agent_harness` — `agent_harness/__main__.py:main(argv, *, harness_factory=None)`.
  The `harness_factory` keyword is the documented test seam: it receives the
  loaded config and returns anything with `list_tools()`, `plan()`, `run()`,
  `set_progress()` and `close()`.
- `from agent_harness import AgentHarness, Config, HarnessResult, __version__` —
  the frozen `__all__`, in that order.
- `agent_harness.plugins.loader.discover_tools(plugin_dirs, *, config, llm_client,
  logger)` and `register_discovered(registry, tools, *, logger)`.

**Environment switches useful for CI**

- `NO_COLOR=1` or `TERM=dumb` — forces plain-text output, so snapshot tests are
  stable and never contain ANSI.
- `AGENT_HARNESS_CONFIG` — config path without a flag; `AGENT_HARNESS_LOG_LEVEL`
  — log level without a flag. Both sit below a flag and above the file.
- Remove `OPENAI_API_KEY` to exercise the keyless path: `--list-tools` must still
  exit 0 (SPEC-006 K5), a run must exit 1.

**Example prompts that exercise each layer**

- `--list-tools` — registry plus plugin discovery, no LLM call.
- `--dry-run "Summarise the quarterly report"` — planner only.
- `"Research recent AI safety papers and summarise them"` — planner, tools,
  orchestrator, recovery cascade, assembler.
- `--max-steps 2 "Write a long report"` — forces the step budget to bite.
- `--no-fallback "Do something risky"` — recovery limited to Level 1.

**Known degraded modes**

- No `wkhtmltopdf` → `INFO pdf_export_degraded`; PDF export falls back, everything
  else works.
- No `rich` → plain-text console. Not a failure; the package imports either way.
- A plugin that fails to load → `WARNING plugin_failed`, tool absent, harness
  starts. Never fatal.

#### Handoff to the orchestrator

1. **I1 is ready but not open.** The progress board in `planning/README.md` § 5
   still shows P1, P2 and P3 at `0/5` / `gated (no skills)`, while all seven of
   their module packages are present in `main` via merged PRs. Please confirm
   whether the board is stale. If P1–P3 are in fact done, the I1 checklist above
   can be executed immediately; the swap is designed to need no code change here.
2. **SCR-P4-6 needs a decision from Plan 1.** `AgentError` must derive from
   `Exception`. Until it does, this plan's `except AgentError` paths cannot
   function against the real module, and I1's contract-equivalence test will fail
   on the first contained failure.
3. **SCR-P4-5:** `pyproject.toml` must carry the ruff/mypy/pytest configuration
   and `rich>=13`. This plan cannot own that file, so its gate runner currently
   lives outside the repository.
4. **Ten escalations are open** (SCR-P4-1 … -9, SKR-P4-1) in the section below.
   None blocked delivery; SCR-P4-6 is the only one that can break I1.

#### I1 swap checklist

The composition root resolves every Plan 1-3 collaborator **by dotted name at
call time** through `importlib.import_module`, never by module-level import. That
is the whole point of the design: the swap below is a change of *what is
installed under those names*, not a change to this plan's code.

`tests/test_harness.py::TestSwapChecklist` ties this table to the source. Adding
or removing a seam fails that test until the table is updated, so the checklist
cannot silently drift.

**Modules resolved** (`agent_harness.plugins.loader` is excluded — it is P4's own):

| # | Dotted module | Owner | Symbols read from it |
|---|---|---|---|
| 1 | `agent_harness.config` | P1 | `Config` |
| 2 | `agent_harness.config.schema` | P1 | `AgentError`, `Step`, `ExecutionPlan`, `TaskPriority` |
| 3 | `agent_harness.context` | P1 | `ContextStore` |
| 4 | `agent_harness.llm` | P1 | `create_llm_client` |
| 5 | `agent_harness.logging` | P1 | `StructuredLogger` |
| 6 | `agent_harness.logging.report` | P1 | `render_report` |
| 7 | `agent_harness.orchestration` | P3 | `Orchestrator`, `ExecutionHooks`, `ExecutionMetrics`, `Assembler`, `RecoveryManager`, `StepStatus` |
| 8 | `agent_harness.planning` | P3 | `Planner` |
| 9 | `agent_harness.tools` | P2 | `ToolRegistry`, `default_tools` |
| 10 | `agent_harness.tools.base` | P2 | `ToolResult` |

Symbol set asserted by the test: `AgentError`, `Assembler`, `Config`,
`ContextStore`, `ExecutionHooks`, `ExecutionMetrics`, `ExecutionPlan`,
`Orchestrator`, `Planner`, `RecoveryManager`, `Step`, `StepStatus`,
`StructuredLogger`, `TaskPriority`, `ToolRegistry`, `ToolResult`,
`create_llm_client`, `default_tools`, `render_report`.

**I1 outcome (SCR-P4-12).** The swap grew the table by one module and five
symbols, all additive and all traceable to P3's ratified injection seams
(SCR-P3-6): the planner builds its plans through a `ModelProvider`, so Plan 4
injects one backed by `Step`/`ExecutionPlan`/`TaskPriority`/`ToolResult` instead
of letting P3's spec-shaped stand-ins through; and SPEC-003 § 5's recovery
cascade is composed from `RecoveryManager` at the root. No symbol was removed
and no signature changed, so the swap itself remains a change of *what is
installed under those names*. The fourth checklist assertion
(`test_the_stubs_stay_available_for_tests`) was retired rather than rewritten:
after I1 every seam name resolves inside `agent_harness`, so the meaningful
statement is that each of them is a shipped package module — which is what that
test now asserts.

**Procedure at I1**

1. Confirm on the orchestrator's progress board that P1, P2 and P3 all report
   done. *Code being merged is not the same as the plan reporting done.*
2. Rebase this branch onto `main` so the real packages are importable.
3. Run the owned suite with the stubs **not** installed
   (`tests/_p4_stubs.py` is only activated by the `stubbed` fixture). Every test
   must pass unchanged — that is the contract-equivalence proof 5.1 asks for.
4. Delete nothing. `tests/_p4_stubs.py` stays: the suite must remain runnable
   without P1-P3 present, which is what keeps it deterministic and offline.
5. Remove the two temporary `# type: ignore[misc]` comments on the `BaseTool`
   subclass lines in `plugins/example_hello.py` and `plugins/example_database.py`,
   which exist only because `agent_harness.tools.base` was absent.
6. Re-run `bash gates.sh`; `mypy --strict` must stay clean.

**Known contract risks to check at step 3**

- `AgentError` must derive from `Exception` (SCR-P4-6). If P1 shipped a plain
  dataclass, the harness's `except AgentError` paths cannot work.
- `Config.apply_overrides` is used when present and skipped when absent
  (SCR-P4-9). Either is fine; no CLI change is needed.
- `ExecutionMetrics.from_plan(plan, timings, llm_usage)` and
  `render_report(plan, metrics, *, style)` signatures must match SPEC-003 §6 and
  SPEC-006 §7, which is what the stubs were written against.

#### Troubleshooting conformance

Every entry in the Developer README's troubleshooting section maps to a concrete
signal this plan produces. `tests/test_harness.py::TestTroubleshootingMessages`
pins the four P4 owns; the other two are owned downstream and this plan's job is
the surfacing.

| README symptom | Reproduce with | Signal P4 produces | Exit |
|---|---|---|---|
| `OPENAI_API_KEY not set` | `env -u OPENAI_API_KEY python -m agent_harness "x"` | `WARNING api_key_missing` naming the variable, `remediation="cp .env.example .env and add your key"` | 0 for `--list-tools` (SPEC-006 K5); 1 for a run |
| `ModuleNotFoundError: No module named 'agent_harness'` | `python -c "import agent_harness; agent_harness.Nope"` | `AttributeError` naming the attribute; a genuinely missing owner module raises `ImportError` naming that module, never a bare failure | n/a |
| `wkhtmltopdf not found` | `python -m agent_harness "x"` with no `wkhtmltopdf` on `PATH` | `INFO pdf_export_degraded`, naming `wkhtmltopdf` — informational, construction still succeeds | unchanged |
| `Rate limit exceeded` | P3's recovery cascade | Not P4's to detect. Surfaced through `HarnessResult.errors`, and exit 3 vs 1 tells a caller whether anything was salvaged | 3 or 1 |
| Code execution hangs | P2's `execution.step_timeout` | Not P4's to detect. Surfaces as a failed step in the plan and in `HarnessResult.errors` | 3 or 1 |
| Agent produces too many steps | `python -m agent_harness --max-steps 3 "x"` | Overrides `execution.max_steps`. A non-positive or non-integer value is a usage error naming the flag, not a silent no-op | 0, or 2 for a bad value |

Two additions beyond the README, both warned at startup because they are
surprises a user would otherwise discover late: `shell_execution_enabled`
(`WARNING`) when `security.allow_shell` is true, and `credentials_transmitted`
(`WARNING`) naming the environment variables that would go over the network.

One deliberate divergence worth stating: a missing API key is **not** fatal at
construction. SPEC-005 § 4 says it should be, but SPEC-006 K5 requires
`--list-tools` to work without credentials, and `--list-tools` must construct a
harness. The two cannot both hold; SCR-P4-7 records the resolution in favour of
K5, with the failure raised at first LLM use instead.

#### Config-surface matrix

All 34 keys of the SPEC-006 § 1 schema are accounted for: **12 are touched by
this plan, 22 are passed through untouched**. `tests/test_harness.py::
TestConfigSurface` derives the "touched" set by parsing this plan's own sources
for `config.<section>.<key>` reads and `config.get("...")` lookups, so the matrix
cannot drift from the code. **Unmapped keys: 0** — no SCR required.

| Section | Key | P4's relationship | Consumed by |
|---|---|---|---|
| `llm` | `provider` | read — startup warning names the live providers | P4 + P1 |
| `llm` | `api_key_env` | read — startup warning names the env var at risk | P4 + P1 |
| `llm` | `model`, `fallback_model`, `base_url`, `max_tokens`, `temperature`, `timeout`, `max_retries`, `cost_per_1k_tokens` | pass-through | P1 |
| `execution` | `max_steps` | **CLI write** (`--max-steps`), not read here | P3 |
| `execution` | `output_dir` | read (`_ensure_directories`) + **CLI write** (`--output-dir`) | P4 |
| `execution` | `temp_dir` | read (`_ensure_directories`) | P4 |
| `execution` | `enable_replan` | read (`_apply_recovery_policy`) + **CLI write** (`--no-fallback`) | P4 + P3 |
| `execution` | `step_timeout`, `max_retries`, `retry_backoff`, `retry_base_delay`, `abort_on_critical_failure` | pass-through | P3 |
| `search` | `provider`, `api_key_env` | read — startup warning on transmitted credentials | P4 + P2 |
| `search` | `max_results` | pass-through | P2 |
| `security` | `allow_shell` | read — startup warning `shell_execution_enabled` | P4 + P2 |
| `security` | `sandbox_code`, `code_timeout`, `max_output_bytes`, `network_in_code`, `sensitive_patterns` | pass-through | P2 / P1 |
| `logging` | `level` | **CLI write** (`--log-level`, `AGENT_HARNESS_LOG_LEVEL`), not read here | P1 |
| `logging` | `file`, `format`, `console` | pass-through | P1 |
| `plugins` | `dirs`, `auto_load` | read (`_load_plugins`, `discover_tools`) | P4 |

The four CLI overrides are exactly the ones SPEC-005 § 2 documents, asserted by
test against `OVERRIDE_PATHS` plus the `--no-fallback` write.

Worth recording: writing this as a test rather than a table found three reads an
informal audit had missed — `llm.provider`, `search.provider` and
`search.api_key_env`. They are legitimate (the transmitted-credentials warning
cannot name what it does not look up), but they were undocumented until now.

**Status: I1 EXECUTED.** The checklist above ran against the real Plan 1-3
modules: the composition root composes `_SchemaModels` (P1's `Step`/`ExecutionPlan`/
`TaskPriority`/`ToolResult`), `RecoveryManager` (P3's cascade) and every other seam
by dotted name, the stub-era test assumptions were replaced by assertions on the
shipped objects, and the full suite is green with the stubs uninstalled. The 9-module
/ 14-symbol table this section was written around was correct for the pre-swap
source; the swap itself grew it to 10 modules / 19 symbols, which SCR-P4-12 records
and the checklist table above now carries. `tests/_p4_stubs.py` was not deleted
(procedure step 4) — it remains on disk, imported by nothing, with its contract
equivalent in `tests/_p4_doubles.py`.
