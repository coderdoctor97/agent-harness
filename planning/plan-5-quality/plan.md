# Plan 5 — Quality & Delivery

**Plan ID:** P5 · **Workstream:** Test Infrastructure, Integration Suite, CI, Examples, Docs & Release
**Execution:** independent — may run concurrently with P1–P4 · **Sub-phases:** 25 (5 phases × 5)

---

## 0. Plan Header

| Field | Value |
|---|---|
| Mission | Deliver the L4 assurance layer: shared test fixtures, the integration/e2e suite proving the four user stories, CI pipelines, runnable examples, contributor documentation, and v0.1.0 release readiness. |
| Owned paths | SPEC-000 § 3.5 — `tests/conftest.py`, `tests/integration/`, `examples/`, `.github/workflows/`, `LICENSE`, `.gitignore`, `CONTRIBUTING.md`, `PRD.md` (pointer stub), `documentations/` additions (never the verbatim vision file), root `README.md` maintenance after foundation handoff |
| Consumed specs | All — SPEC-000 (testing standards, DoD), SPEC-001–006 (behavior under test), plus the vision's § 12 user stories and § 14 success metrics |
| Produces for others | Shared fixtures for every plan's tests; CI gates; release checklist; the acceptance evidence that the composed system meets the vision |
| Parallel-work rule | Implementation modules don't exist yet → author fixtures, test plans, CI, and docs **spec-first**; integration test bodies are written now against spec contracts and executed at the integration window (planning/README § 4, steps I2–I3). Unit-test *files* belong to P1–P4; P5 never edits them. |
| Skill gate | ⛔ No source change until an active skill covers it (`.agent/agent.md` § 6). Dictionary currently empty → status: gated. Note: test code, CI YAML, and example scripts are source code under agent.md § 6.1. |

**Independence declaration.** This plan touches only its owned paths. It reads every spec
and every plan, imports implementation modules **only inside integration tests executed at
I3**, and files defects to owning plans instead of fixing them (SPEC-000 § 3.5, § 8 roles).

---

## Phase 1 — QA Infrastructure

> Outcome: the shared test substrate all plans can rely on, and the quality gates defined.

### Sub-phase 1.1 — `tests/conftest.py` shared fixtures
- **Tasks:** spec-shaped fixtures: `mock_llm_client` (scripted, per SPEC-004 § 1.2 C7), `tool_registry` (empty + populated variants), `sample_config` (SPEC-006 § 1 defaults, tmp dirs), `tmp_workspace` (output/temp/logs), `fake_logger` (event capture), `sample_plan` (valid 4-step plan matching vision § 5.2). **Additive only** — plan-local tests must pass without these (SPEC-000 § 5.1).
- **Deliverable:** `tests/conftest.py`.
- **Exit criteria:** fixtures self-test (a `tests/integration/test_fixtures.py` sanity module); no fixture performs network/LLM I/O.

### Sub-phase 1.2 — Test ownership map enforcement
- **Tasks:** codify the SPEC-000 § 3 test-path ownership as a check script/CI step: fail if a plan's commit touches another plan's test paths; document map in `CONTRIBUTING.md` (Phase 4).
- **Deliverable:** ownership guard (script under `.github/` or `tests/integration/`).
- **Exit criteria:** guard demonstrated on a synthetic violation in CI dry-run.

### Sub-phase 1.3 — Markers, coverage & determinism gates
- **Tasks:** verify pytest config (owned by P1 in `pyproject.toml`) exposes `integration` marker, testpaths, and coverage flags; define gate values: coverage ≥ 80 % per owned-module group, `--strict-markers`; document the injected-clock/injected-sleep determinism requirements (SPEC-000 § 5.5) for test authors.
- **Deliverable:** gate definitions in `CONTRIBUTING.md` + CI flags.
- **Exit criteria:** `pytest -m "not integration"` runs offline in CI; coverage gate wired (enforced from Phase 3).

### Sub-phase 1.4 — Integration test scaffolding
- **Tasks:** create `tests/integration/` package: `README.md` (what runs here, when), harness bootstrap helper that composes the real system with `MockLLMClient` and network-stubbed tools, scenario naming convention `test_<US-id>_<behavior>.py`.
- **Deliverable:** integration scaffolding.
- **Exit criteria:** bootstrap helper compiles against spec stubs; skips gracefully (with reason) when implementation modules are absent — so CI stays green during parallel development.

### Sub-phase 1.5 — Quality tooling baseline docs
- **Tasks:** document the exact commands (`ruff check`, `ruff format --check`, `mypy --strict`, `pytest`, `pytest --cov`) and the per-plan scope rule ("lint/type/test **your owned paths**"); pre-commit guidance (optional, not enforced).
- **Deliverable:** QA baseline section in `CONTRIBUTING.md` (draft; finalized 4.1).
- **Exit criteria:** a newcomer can run the full gate from the doc alone.

---

## Phase 2 — Integration & Acceptance Suite

> Outcome: executable proof of the vision's user stories and recovery semantics (bodies written now; run at I3).

### Sub-phase 2.1 — `test_full_plan.py` (happy path)
- **Tasks:** end-to-end: prompt → plan (mock LLM scripted plan per vision § 5.2) → execute with stubbed web tools → assemble → assert `HarnessResult.status == "completed"`, files created, metrics consistent (SPEC-003 § 7), report renders.
- **Deliverable:** e2e happy-path suite.
- **Exit criteria:** mirrors vision § 10.2 report example; deterministic (fixed clock/sleep injection).

### Sub-phase 2.2 — US-1 research automation acceptance
- **Tasks:** encode every US-1 acceptance criterion as an assertion: ≥ 3 steps; correct tool per step; PDF (or degraded markdown) in output dir; search failure → alternative provider path exercised; execution report completeness.
- **Deliverable:** `test_us1_research.py`.
- **Exit criteria:** criterion-to-test traceability table in the module docstring.

### Sub-phase 2.3 — US-2 code generation acceptance + US-3 recovery
- **Tasks:** US-2: task-mode `code_execute` flow, syntax-error → regenerate-with-error-context retry, `chart.png`-class artifact + saved generated code. US-3 (`test_recovery_e2e.py`): primary fail → fallback → re-plan → continue-with-available-data for non-critical; all attempts logged (SPEC-006 § 6.1 events).
- **Deliverable:** `test_us2_codegen.py`, `test_recovery_e2e.py`.
- **Exit criteria:** each US-2/US-3 checkbox from vision § 12 maps to a named assertion.

### Sub-phase 2.4 — US-4 plugin integration
- **Tasks:** temp plugins dir with a generated `BaseTool` file → startup auto-discovery → tool appears in `list_tools()` → LLM (mocked) selects it when prompt mentions its capability → executed in a plan; poisoned plugin isolation verified at system level.
- **Deliverable:** `test_us4_plugins.py`.
- **Exit criteria:** all five US-4 acceptance criteria asserted.

### Sub-phase 2.5 — Metrics & success-criteria instrumentation tests
- **Tasks:** verify `ExecutionMetrics` fields against hand-computed scenarios; wire the vision § 14.1 metric formulas (plan completion rate, step success rate, recovery success rate) as an aggregate report over the integration suite results.
- **Deliverable:** `test_metrics.py` + metrics aggregation helper.
- **Exit criteria:** formula outputs reproducible from recorded fixtures; helper documented for release evidence (Phase 5.2).

---

## Phase 3 — CI/CD & Repository Hygiene

> Outcome: automated gates on GitHub and a clean, secret-free repository.

### Sub-phase 3.1 — `.gitignore`
- **Tasks:** cover `output/`, `logs/`, `tmp/`, `.env`, `venv/`, `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `*.egg-info/`, `dist/`, `build/`, `.coverage`, OS junk (`.DS_Store`).
- **Deliverable:** `.gitignore`.
- **Exit criteria:** `git status` on a simulated dirty tree shows only intended files.

### Sub-phase 3.2 — `LICENSE` & `PRD.md` pointer
- **Tasks:** MIT `LICENSE` (per vision badge) with copyright placeholder; `PRD.md` as a short pointer stub to `documentations/Agent_Harness_PRD_Developer_README.md` (vision Part 1) — no content duplication.
- **Deliverable:** `LICENSE`, `PRD.md`.
- **Exit criteria:** pointer resolves; license year/holder documented as release-time fill-ins.

### Sub-phase 3.3 — CI workflow: quality gates
- **Tasks:** `.github/workflows/ci.yml`: on push/PR → matrix (ubuntu-latest; Python 3.9/3.11) → install `.[dev]` → `ruff check` → `ruff format --check` → `mypy --strict` → `pytest -m "not integration"` with coverage gate → upload coverage artifact.
- **Deliverable:** CI quality workflow.
- **Exit criteria:** workflow YAML lint-clean (actionlint or equivalent); skips gracefully while implementation is absent (Phase 1.4 skip behavior).

### Sub-phase 3.4 — CI workflow: integration job
- **Tasks:** second job: `pytest -m integration` with stubbed network/LLM (no secrets required); optional secret-gated live smoke job (`OPENAI_API_KEY` present → run one dry-run + one minimal live plan), `continue-on-error: false` only when secrets exist.
- **Deliverable:** integration + optional live workflows.
- **Exit criteria:** secretless fork PRs pass; live job documented and disabled by default.

### Sub-phase 3.5 — Release automation prep
- **Tasks:** versioning policy doc (semver + Conventional Commits, per vision Contributing); tag-driven build job skeleton (`python -m build`, artifact upload — publishing deferred, NG1 local-first); release checklist template.
- **Deliverable:** release workflow skeleton + checklist.
- **Exit criteria:** dry-run of build job produces sdist/wheel artifacts in CI.

---

## Phase 4 — Examples & Documentation

> Outcome: the vision's demo promise (3 example prompts) and contributor-facing docs.

### Sub-phase 4.1 — `CONTRIBUTING.md`
- **Tasks:** consolidate: dev setup (vision Contributing), code standards, **test-ownership map** (1.2), quality gates (1.5), skill-dictionary mandate summary with pointer to `.agent/agent.md` § 6, PR checklist (vision's, extended with Skill Ledger + owned-paths items), SCR/SKR process.
- **Deliverable:** `CONTRIBUTING.md`.
- **Exit criteria:** PR checklist includes every SPEC-000 § 6 DoD item.

### Sub-phase 4.2 — Example scripts
- **Tasks:** `examples/research_report.py` (US-1 flow), `examples/code_generation.py` (US-2 flow), `examples/data_analysis.py` (CSV → chart-class flow) — each a runnable script using the public `AgentHarness` API with a `--mock` flag defaulting to `MockLLMClient` so examples run without keys.
- **Deliverable:** three examples.
- **Exit criteria:** `--mock` mode executes green in CI (integration job); README snippet in each file header.

### Sub-phase 4.3 — `documentations/` additions
- **Tasks:** author `documentations/architecture-notes.md` (layer map L0–L4, dependency rule, composition-root explanation) and `documentations/testing-guide.md` (how to run/unit vs integration, determinism rules, doubles conventions); add index entries in `documentations/README.md`; **never touch** the verbatim vision file.
- **Deliverable:** two developer docs + index update.
- **Exit criteria:** all cross-links resolve; content consistent with SPEC-000/003/005.

### Sub-phase 4.4 — Root `README.md` maintenance pass
- **Tasks:** update the foundation README's status board (plan progress), quick-start (once P4 CLI exists), and document map; keep vision fidelity; verify badges/links.
- **Deliverable:** refreshed root README.
- **Exit criteria:** link-check clean; status board matches `planning/README.md` § 5.

### Sub-phase 4.5 — Documentation accuracy audit
- **Tasks:** line-by-line compare shipped docs (README, CONTRIBUTING, documentations additions, examples) against specs and actual CLI/API behavior recorded in P4's handoff; file SCRs for any spec/doc divergence found.
- **Deliverable:** audit report in Status Log.
- **Exit criteria:** zero unexplained divergences; all findings dispositioned (fixed in owned docs or filed as SCR).

---

## Phase 5 — Acceptance & Release Readiness

> Outcome: v0.1.0 gate evidence — executed at/after the integration window (I2–I5).

### Sub-phase 5.1 — Full-suite green run (I2/I3)
- **Tasks:** execute unit suites of all plans + P5 integration suite against the composed system (post-I1); triage failures to owning plans (defect routing per planning/README § 4 I4); re-run until green.
- **Deliverable:** green run log + defect routing record.
- **Exit criteria:** 100 % of unit + integration tests pass on the CI matrix.

### Sub-phase 5.2 — Success-metrics evidence
- **Tasks:** run the § 2.5 aggregation over the acceptance scenarios; record plan completion, step success, recovery success rates vs vision § 14.1 targets; document gaps as known limitations (targets are runtime-population goals, not CI gates).
- **Deliverable:** metrics evidence sheet in Status Log.
- **Exit criteria:** every § 14.1 metric has a measured value or a documented reason it's not CI-measurable.

### Sub-phase 5.3 — Demo dry-run
- **Tasks:** execute the 3 example prompts in `--mock` mode; capture expected outputs (plan previews + assembled artifacts) as golden references under `examples/expected/`; verify US-1–US-4 narratives hold end-to-end.
- **Deliverable:** demo script + golden outputs.
- **Exit criteria:** demos reproducible from a clean checkout with documented commands.

### Sub-phase 5.4 — Security review pass
- **Tasks:** verify at system level: sandbox layers S1–S8 (SPEC-006 § 4) active through `code_execute` in a real plan; shell whitelist + `allow_shell=false` default; redaction pipeline active on LLM outbound (C4); no secrets in logs/reports/artifacts (scan outputs with `sensitive_patterns`); path guards hold through tools.
- **Deliverable:** security review checklist (all items pass/fail + evidence links).
- **Exit criteria:** zero open critical findings; any finding routed to owner plan before release.

### Sub-phase 5.5 — v0.1.0 release (I5)
- **Tasks:** finalize `LICENSE` holder/year, README quick-start verification on clean venv (vision Setup Success Rate goal), CHANGELOG from Conventional Commits, tag `v0.1.0`, run release checklist (3.5), archive CI evidence.
- **Deliverable:** tagged v0.1.0 + release notes.
- **Exit criteria:** SPEC-000 § 6 DoD satisfied for P5; release checklist 100 % complete.

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
