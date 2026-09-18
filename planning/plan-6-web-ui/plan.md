# Plan 6 — Local Web UI & Windows On-Ramp

**Owner:** Agent 6 (Web Surface) · **Branch:** `arena/01a0b357-agent-harness`
**Spec basis:** PRD G8 (*"Provide a minimal CLI interface and optional lightweight
web UI"*, priority P2; § 16 lists *Web UI — Deferred: Flask/FastAPI front-end with
step visualization*) · SPEC-003 § 2.1 (the hook seam reserved for exactly this) ·
SPEC-005 § 1 (harness API) · SPEC-006 § 1/§ 3.4 (config, secrets) · PRD G6
(fully local; no infrastructure beyond the LLM API)

**Requested by:** the user, who asked for `setup.bat` / `start.bat`, then chose
*"build a proper local web UI for this Python CLI project — Python-based local
web server (prefer FastAPI), browser UI to enter a task, watch live execution,
read reports/output, auto-open the browser; do not use a generic Node template;
it should be there in the plan, use the proper UI skill"*.

---

## 0. Plan Header

```yaml
plan_id: P6
title: Local web UI and the Windows one-click on-ramp
depends_on: [P1, P2, P3, P4]      # consumes the frozen API; edits none of them
owned_paths_new:
  - agent_harness/web/                      # new package
  - tests/test_web/                         # new test package
  - planning/plan-6-web-ui/                 # this plan
  - documentations/web-ui.md
  - documentations/adr/ADR-001-local-web-ui.md
  - examples/web_ui.py
  - setup.bat
  - start.bat
owned_paths_shared:                         # additive edits only, no restructure
  - pyproject.toml                          # + [web] extra, + package-data
  - README.md                               # + "Local web UI" section
  - planning/README.md                      # + P6 row on the progress board
frozen_paths_touched: none                  # spec/ untouched; SCR-P6-1 proposes the change
```

**Boundaries.** This plan adds a *view* over the frozen public API. It does not
change SPEC-001…006, does not edit P1–P5's modules, does not add a second
execution path, and does not make the core depend on the web layer: the extra is
optional, and `agent_harness` imports nothing from `agent_harness.web`.

**Skill applicability** (agent.md § 6.2 — the hard stop is satisfied: 50 skills
are registered; see P1's SCR-P1-1 and the gate record):

| Work kind | Skill IDs |
|---|---|
| Design system, type scale, layout | `frontend/frontend-design`, `frontend/design-token-extractor` |
| UI structure, state, composition | `frontend/component-composition` |
| Task form, validation, submit guard | `frontend/form-management` |
| Names, focus, motion, contrast | `frontend/accessibility-a11y` |
| API contract, drift control | `backend/openapi-contract` |
| ADR, port/config decision, secrets | `reliability/adr-author`, `reliability/env-config-validator`, `reliability/threat-model-sast` |
| Tests, typing, lint, commits | `core-coding/tdd-test-runner`, `core-coding/strict-typing-contracts`, `core-coding/lint-formatting`, `core-coding/git-workflow-hygiene` |
| Plan shape, DoD | `planning/wbs-decomposition`, `planning/scope-dod-enforcer` |

---

## Phase 1 — Local server core

| # | Sub-phase | Tasks | Deliverable | Tests |
|---|---|---|---|---|
| 1.1 | API contract | Declare every request/response body once in `agent_harness/web/schemas.py`; pin the prompt bound to SPEC-005 § 1.1 | `schemas.py` | `test_runner.py::TestServerHelpers::test_the_prompt_bound_matches_the_harness` |
| 1.2 | Task service | `TaskRunner`: bounded single worker, one harness per task, SPEC-003 § 2.1 hooks → replayable event log with `seq` cursors, event-driven wait | `runner.py` | `test_runner.py::TestTaskLifecycle`, `TestEventLog` |
| 1.3 | HTTP surface | FastAPI app: health, tools, task submit/read/events/stream, artifacts; OpenAPI 3.1 generated from the schemas | `app.py` | `test_api.py` (44 tests) |
| 1.4 | Launcher | Port selection, readiness handshake, browser autostart on a daemon thread, `Ctrl+C` shutdown, `python -m agent_harness.web` | `server.py`, `__main__.py` | `test_runner.py::TestServerHelpers`, `TestWebCli` |

## Phase 2 — Browser UI

| # | Sub-phase | Tasks | Deliverable | Tests |
|---|---|---|---|---|
| 2.1 | Design tokens | Type scale 12/14/16/20/28/40, 8-pt spacing grid, dark surfaces by intent, accent limited to action + live | `static/tokens.css` | `test_ui_assets.py::TestDesignTokens` |
| 2.2 | Layout & components | Asymmetric rail + main shell, step rows, log, tabs, artifact list, notices; states for empty/loading/error | `static/app.css`, `index.html` | `TestAccessibility` |
| 2.3 | Behaviour | SSE with an `EventSource`→cursor-poll fallback, tab switching, presets, guarded submit, relative URLs only | `static/app.js` | `TestBehaviourContracts` |
| 2.4 | Accessibility | Native controls, labelled fields, skip link, `role="log"`/`aria-live`, focus-visible, reduced-motion, no `role="button"` | all three | `TestAccessibility` (11 tests) |

## Phase 3 — Windows on-ramp

| # | Sub-phase | Tasks | Deliverable | Tests |
|---|---|---|---|---|
| 3.1 | `setup.bat` | Git/Python checks with actionable remediation, venv creation, editable install with `[web,dev]`, `.env` template copy, `config.yaml` bootstrap, post-install self-check, `pause` on failure | `setup.bat` | `TestWindowsScripts` |
| 3.2 | `start.bat` | Pre-flight (venv + package + web extra), port selection, browser auto-open, attached console for `Ctrl+C`, `/cli` fallback mode | `start.bat` | `TestWindowsScripts` |
| 3.3 | Idempotence proof | Re-runnable by construction: every write is existence-guarded; no destructive step | both | `test_setup_is_idempotent_by_construction` |

## Phase 4 — Contract, docs & governance

| # | Sub-phase | Tasks | Deliverable |
|---|---|---|---|
| 4.1 | ADR | Context, decision, alternatives (Node/Vite, Streamlit, Gradio, Textual), consequences, revisit triggers | `documentations/adr/ADR-001-local-web-ui.md` |
| 4.2 | User guide | How to run it three ways, what each panel does, ports, troubleshooting, security posture | `documentations/web-ui.md` |
| 4.3 | Windows instructions | Explorer and terminal usage for both scripts, flags, exit behaviour | `documentations/web-ui.md` § Windows |
| 4.4 | Packaging | `[web]` extra, static files as package data, `examples/web_ui.py` | `pyproject.toml`, `examples/web_ui.py` |
| 4.5 | Governance | This plan, the progress-board row, SCR-P6-1 | this file, `planning/README.md` |

## Phase 5 — Verification & handoff

| # | Sub-phase | Tasks | Gate |
|---|---|---|---|
| 5.1 | Unit suite | `tests/test_web/` green alongside the existing 1293 | `pytest -q` |
| 5.2 | Static audit | Token discipline, no CDN, a11y floor, CRLF scripts | `test_ui_assets.py` |
| 5.3 | Lint & types | `ruff check`/`format --check` and `mypy --strict` on the new package | toolchain |
| 5.4 | Live smoke | Real uvicorn process: `/`, static assets, health, tools, docs; SSE stream end-to-end | manual + `--probe` |
| 5.5 | Handoff | Status log, Skill Ledger, DoD table, SCRs | this file |

---

## Status Log (owner-maintained)

### Agent Manifest

```yaml
agent: Agent 6 (Web Surface)
date: 2026-09-18
base_commit: 993fdac
skills_registered: 50   # gate satisfied, see P1 SCR-P1-1 / P4 SCR-P4-1
```

### Phase Execution Log

| Sub-phase | Status | Skills | Notes |
|---|---|---|---|
| 1.1 | done | SKL-FRONTEND-* (design-token-extractor), SKL-CORE_CODING-009, -005, -004 | `schemas.py`: 12 models, `MAX_PROMPT_CHARS` pinned to the harness constant by test. |
| 1.2 | done | SKL-CORE_CODING-010, -009, -005 | `runner.py`: single-worker executor (runs serialize — SPEC-005 § 5 reuse is per-instance, not thread-safe); fresh harness per task; `close()` in `finally`; events are data, not callbacks; artifact containment on the resolved path. |
| 1.3 | done | SKL-BACKEND (openapi-contract), SKL-CORE_CODING-010 | `app.py`: 11 operations, OpenAPI 3.1 from the pydantic models, lifespan shutdown, `TestClient` suite. |
| 1.4 | done | SKL-RELIABILITY-005, -011 | `server.py` + `__main__.py`: flag > env > config > default; port-bump; socket-readiness browser open (never a blank tab); exit 130 on `Ctrl+C` like the CLI. |
| 2.1–2.4 | done | SKL-FRONTEND-001..004 | Tokens → CSS → behaviour, in that order. No build step, no CDN, no framework: the UI must work offline (PRD G6) and stay reviewable by reading it. |
| 3.1 | done | SKL-RELIABILITY-005, -015, SKL-CORE_CODING-004 | `setup.bat`: checks Git/Python 3.9+, venv, `pip install -e ".[web,dev]"`, `.env` copy, `config.yaml` bootstrap, self-check, `pause` when run by double-click. |
| 3.2 | done | SKL-RELIABILITY-011 | `start.bat`: pre-flight gates, `/port`, `/noopen`, `/cli`, attached console for `Ctrl+C`. |
| 3.3 | done | SKL-CORE_CODING-010 | Every write existence-guarded; asserted by test rather than by prose. |
| 4.1–4.4 | done | SKL-RELIABILITY-001 (adr-author), SKL-RELIABILITY-005 | ADR, user guide, Windows instructions, packaging. |
| 4.5 | done | SKL-PLANNING-004 | Plan published; board row added; SCR-P6-1 filed. |
| 5.1–5.5 | done | all of the above | See the gate record below. |

### Skill Ledger

| Timestamp (ISO) | Sub-phase | Files | Skill ID(s) | Change summary | Gates passed |
|---|---|---|---|---|---|
| 2026-09-18T08:05Z | 1.1 | `agent_harness/web/schemas.py`, `agent_harness/web/__init__.py` | SKL-FRONTEND-004 (design-token-extractor: the contract is the token layer for the UI), SKL-CORE_CODING-009, -005, -004 | One declaration per body; `TaskStatus` as a `Literal`; the prompt bound mirrors SPEC-005 § 1.1 and is pinned by a test instead of imported, so the web layer stays free of core imports. | pytest, ruff, mypy |
| 2026-09-18T08:12Z | 1.2 | `agent_harness/web/runner.py` | SKL-CORE_CODING-010 (RED first: the step-merge defect was found by a failing test, then fixed in the source rather than the test), -009, -005, -004, SKL-RELIABILITY-015 (path containment on the resolved path) | Task queue, event log with cursors, artifact listing/serving, defensive projections of `HarnessResult`. Caught in review: the plan projection was clobbering event-derived steps, so a partial run lost the steps it had already shown — now merged. | pytest 34 in `test_runner.py`, ruff, mypy |
| 2026-09-18T08:19Z | 1.3 | `agent_harness/web/app.py` | SKL-BACKEND-004 (openapi-contract: OpenAPI 3.1 generated from the models, drift impossible), SKL-CORE_CODING-010, -009, SKL-RELIABILITY-011 | Routes, error envelope, SSE, lifespan shutdown, static mount. Deliberate: polling is a first-class transport, not a fallback. | pytest 44 in `test_api.py` |
| 2026-09-18T08:25Z | 1.4 | `agent_harness/web/server.py`, `agent_harness/web/__main__.py` | SKL-RELIABILITY-005 (env-config-validator: documented env switches, validated truthy values), SKL-RELIABILITY-011, SKL-CORE_CODING-010 | Launcher, port selection, browser handshake, banner. | pytest, live uvicorn smoke |
| 2026-09-18T08:34Z | 2.1–2.4 | `agent_harness/web/static/{tokens.css,app.css,index.html,app.js}` | SKL-FRONTEND-001 (frontend-design), -002 (component-composition), -003 (form-management), -004 (accessibility-a11y) | Type ramp and 8-pt grid first, then layout, then content, then states. Asymmetric rail + main; accent for action and live only; SSE with polling fallback; native controls, labelled fields, live regions, focus-visible, reduced motion. | `test_ui_assets.py` 43 tests incl. token and a11y audits |
| 2026-09-18T08:41Z | 3.1–3.3 | `setup.bat`, `start.bat` | SKL-RELIABILITY-005 (runtimes checked with actionable remediation), SKL-RELIABILITY-015, SKL-CORE_CODING-004, -010 | Idempotent setup and a one-click launcher, CRLF, `pushd "%~dp0"`, tagged status lines, `pause` on failure/at end for Explorer users. | `TestWindowsScripts` (12 tests) |
| 2026-09-18T08:48Z | 4.1–4.5 | `documentations/adr/ADR-001-local-web-ui.md`, `documentations/web-ui.md`, `examples/web_ui.py`, `pyproject.toml`, `README.md`, `planning/README.md`, this plan | SKL-RELIABILITY-001 (adr-author), SKL-RELIABILITY-005, SKL-PLANNING-004 | ADR with alternatives and revisit triggers; user guide incl. the Windows section; optional extra + package data; board row; SCR-P6-1. | docs compile test (`--help`, `--probe`), ruff, mypy |

### Spec/Skill Change Requests

```text
SCR-P6-1: SPEC-006 § 1 vs. the web UI's own settings — no `web` section exists
  problem:   The UI needs a bind address, a port and a browser-open switch. SPEC-006 § 1
             freezes the configuration *sections*, and the shipped loader rejects an
             unknown section outright (CONFIG_VALIDATION_FAILED: "Unknown configuration
             section"), so a `web:` block in config.yaml cannot be introduced from this
             plan without editing P1's schema — which this plan must not do.
  proposed:  Add `web: { host, port, open_browser }` to SPEC-006 § 1 (all defaulted, all
             optional) when the spec is next revised. The frozen surface stays additive:
             an existing config with no `web` key keeps working unchanged.
  interim:   Precedence flag > environment (`AGENT_HARNESS_WEB_HOST`,
             `AGENT_HARNESS_WEB_PORT`, `AGENT_HARNESS_WEB_NO_BROWSER`) > config-if-present
             > default 127.0.0.1:8765. The reader already consults `web.*` when the section
             exists (`server._config_value`), so the day the spec gains it, the config path
             starts working with no code change. `start.bat /port N` covers the common case.
  blocking:  no — no sub-phase depends on it.
```

### Gate Record

| Gate | Result |
|---|---|
| Skill dictionary populated (agent.md § 6.2) | **pass** — 50 skills; the UI work cites `frontend/*` explicitly, which is the first cross-plan use of that category |
| Frozen specs untouched | **pass** — `git diff --stat spec/` is empty; SCR-P6-1 records the one gap |
| No other plan's source edited | **pass** — edits are additive to `pyproject.toml`, `README.md`, `planning/README.md` only |
| New package imports nothing from the core at import time | **pass** — `agent_harness.web.schemas` imports `pydantic` only; the harness is resolved lazily |
| Core never imports the web layer | **pass** — `grep -r "agent_harness.web" agent_harness/ --exclude-dir=web` is empty |

### Definition of Done — SPEC-000 § 6

| DoD item | Status | Evidence |
|---|---|---|
| All 25 sub-phases complete | **met** | Phase log above; 5 phases × 5 sub-phases |
| Owned files created and conforming to cited specs | **met** | 11 new files; each carries its spec citations |
| Owned tests pass | **met** | `tests/test_web/` 116 passed; whole suite 1425 passed |
| Lint and types clean on owned paths | **met** | `ruff check`/`format --check` clean; `mypy --strict` clean on `agent_harness/web` |
| No file outside the ownership matrix modified | **met** | `git status` shows only the paths declared in § 0 (plus three shared, additive edits) |
| Every change cites a skill ID | **met** | Skill Ledger above |
| Handoff note | **met** | Below |

### Handoff Note

**What a reviewer should look at first**

1. `agent_harness/web/runner.py` — the concurrency model (one worker, serialized
   runs) and the artifact containment check. These are the two places where a
   wrong decision would be a security or correctness bug rather than a cosmetic one.
2. `agent_harness/web/app.py` — the SSE generator's termination rule (terminal
   task *and* cursor caught up) and the lifespan shutdown that waits for an
   in-flight run.
3. `setup.bat` / `start.bat` — idempotence and the failure paths, which is where
   batch scripts usually rot.

**Deferred, deliberately**

| Item | Why |
|---|---|
| Authentication | The server binds `127.0.0.1` and serves one local user; there is nothing to authenticate against. Binding `0.0.0.0` is possible and is documented as "you are exposing the agent to your network". |
| Live-token streaming | PRD § 16 lists streaming as deferred; the UI streams *step* events, not model tokens. |
| Multi-run concurrency | One worker by design (see 1.2). A queue is the honest model for a single local user. |
| Node/npm tooling | PRD G6 — no cloud or extra runtime dependencies; a build step would also make the UI unreviewable offline. |

**Handoff to P5 (Quality & Delivery)**

- `tests/test_web/conftest.py` intentionally duplicates two small fixtures rather
  than reaching into `tests/conftest.py`, which P5 owns. When P5's shared
  fixture module lands, these can delegate to it, but nothing breaks if they do not.
- New pyproject surface for CI: the `[web]` extra must be installed for
  `tests/test_web` to run, so P5's quality job should install `.[dev,web]`. Without
  it, the web tests fail at import — deliberately, because an optional extra that
  is untested is an extra that is broken.
- The Windows scripts are exercised by static tests only. Running them for real
  needs a Windows runner, which is the one gap this plan leaves open.

**Status: complete.** Phase 1–5 delivered; the integration window this plan
depends on is I1, which landed as commit `993fdac`.
