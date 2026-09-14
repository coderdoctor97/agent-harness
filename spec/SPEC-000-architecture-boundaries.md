# SPEC-000 — Architecture, Module Boundaries & Conformance

**Version:** 1.0.0 · **Status:** FROZEN · **Owner:** Orchestrator · **Applies to:** All plans

---

## 1. Purpose

This spec fixes the architecture, the module map, and the **file-ownership matrix** that
makes the five planning workstreams mutually independent. No two plans may own, create,
or edit the same path. Independence is enforced by disjoint ownership, not by hope.

---

## 2. Architecture Summary

Agent Harness implements a **POEA loop** (Plan → Orchestrate → Execute → Adapt):

```text
prompt → Planner → ExecutionPlan → Orchestrator ⇄ ToolRegistry / Tools
                                          │
                                          ├─ Observer/Recovery (retry → fallback → re-plan → escalate)
                                          ▼
                                    Assembler → HarnessResult (+ ExecutionMetrics, report, logs)
```

Component → module mapping and the layer each belongs to:

| Layer | Component | Module path | Plan |
|---|---|---|---|
| L0 Foundation | Data model, config, context, logging, LLM client | `agent_harness/config/`, `agent_harness/context/`, `agent_harness/logging/`, `agent_harness/llm/` | P1 |
| L1 Capability | Tools, registry, sandbox | `agent_harness/tools/` | P2 |
| L2 Cognition | Planner, prompts, orchestrator, dependency, recovery, assembler | `agent_harness/planning/`, `agent_harness/orchestration/` | P3 |
| L3 Surface | Harness facade, CLI, plugins, public exports | `agent_harness/harness.py`, `agent_harness/__main__.py`, `agent_harness/__init__.py`, `agent_harness/plugins/`, `plugins/` | P4 |
| L4 Assurance | Test infra, integration tests, CI, examples, docs, delivery hygiene | `tests/conftest.py`, `tests/integration/`, `examples/`, `.github/`, repo meta files | P5 |

**Dependency direction is strictly downward:** L3 → L2 → L1 → L0. A lower layer MUST NOT
import from a higher layer. L4 may import anything (tests only).

---

## 3. File Ownership Matrix (Binding)

### 3.1 Plan 1 — Core Foundation

```text
pyproject.toml            config.yaml              .env.example
agent_harness/config/__init__.py     agent_harness/config/loader.py
agent_harness/config/schema.py       agent_harness/context/__init__.py
agent_harness/context/store.py       agent_harness/logging/__init__.py
agent_harness/logging/logger.py      agent_harness/logging/report.py
agent_harness/llm/__init__.py        agent_harness/llm/client.py
agent_harness/llm/providers.py
tests/test_config.py  tests/test_context.py  tests/test_logging.py  tests/test_llm.py
```

### 3.2 Plan 2 — Tool System

```text
agent_harness/tools/__init__.py      agent_harness/tools/base.py
agent_harness/tools/web_search.py    agent_harness/tools/web_scrape.py
agent_harness/tools/code_execute.py  agent_harness/tools/file_read.py
agent_harness/tools/file_write.py    agent_harness/tools/llm_extract.py
agent_harness/tools/llm_synthesize.py agent_harness/tools/pdf_export.py
agent_harness/tools/csv_process.py   agent_harness/tools/shell_command.py
tests/test_tools/   (entire directory)
```

### 3.3 Plan 3 — Planning & Orchestration

```text
agent_harness/planning/__init__.py   agent_harness/planning/planner.py
agent_harness/planning/prompts.py    agent_harness/orchestration/__init__.py
agent_harness/orchestration/orchestrator.py
agent_harness/orchestration/dependency.py
agent_harness/orchestration/recovery.py
agent_harness/orchestration/assembler.py
tests/test_planner.py  tests/test_orchestrator.py  tests/test_dependency.py
tests/test_recovery.py tests/test_assembler.py
```

### 3.4 Plan 4 — Harness Surface

```text
agent_harness/__init__.py            agent_harness/__main__.py
agent_harness/harness.py             agent_harness/plugins/__init__.py
agent_harness/plugins/loader.py      plugins/example_hello.py
plugins/example_database.py          plugins/README.md
tests/test_harness.py  tests/test_cli.py  tests/test_plugin_loader.py
```

### 3.5 Plan 5 — Quality & Delivery

```text
tests/conftest.py                    tests/integration/   (entire directory)
examples/                            .github/workflows/
LICENSE                              .gitignore           CONTRIBUTING.md
PRD.md (pointer stub)                documentations/ (additions only; the verbatim
                                     vision file is READ-ONLY for everyone)
README.md (maintenance after foundation handoff)
```

### 3.6 Shared / Read-Only Paths

| Path | Rule |
|---|---|
| `documentations/Agent_Harness_PRD_Developer_README.md` | **READ-ONLY.** Verbatim vision. Never edited by any plan. |
| `spec/**` | **READ-ONLY** for plans. Changes only via orchestrator change control. |
| `.agent/**` | **READ-ONLY** for plans. Skill dictionary is populated only through the designated skill-registration process. |
| `planning/**` | Each plan edits **only its own** `plan.md` status log section, plus the orchestrator edits `planning/README.md`. |

---

## 4. Package-Level Conventions

| Item | Standard |
|---|---|
| Language | Python ≥ 3.9 (3.11+ recommended); `from __future__ import annotations` where needed for PEP 604/585 syntax |
| Typing | Full type hints on all public signatures; `mypy --strict` clean |
| Lint/Format | `ruff check` and `ruff format` clean |
| Docstrings | Google style; every public module/class/function; include `Spec:` citation |
| Tests | `pytest`; > 80 % coverage target; no network or live LLM calls in unit tests |
| Commits | Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`), scoped by plan, e.g. `feat(tools): add web_search [P2][SKL-xxx]` |
| Skill citation | Every commit that touches source code cites the skill ID(s) used — see `.agent/agent.md` § 6 |
| Import rule | No cross-plan imports of *concrete* modules during parallel work; consume via spec-defined interfaces and local mocks |
| Error handling | Raise/return only spec-defined error types; never bare `except:`; never swallow errors silently |
| Secrets | Never hardcode keys; always resolve through `api_key_env` indirection (SPEC-006 § 3) |

---

## 5. Testing Standards

1. **Unit tests are plan-local.** Each plan writes and owns tests for its modules under
   the paths listed in § 3. Unit tests must not depend on `tests/conftest.py` fixtures
   owned by Plan 5 beyond plain `pytest`; shared fixtures are additive only.
2. **No live external calls** in unit tests: HTTP, LLM APIs, and subprocess execution are
   mocked/faked. Sandbox tests (P2) may spawn real local subprocesses with trivial code.
3. **Integration tests** (`tests/integration/`, owned by P5) run the composed system with
   stub LLM/network layers and are marked `@pytest.mark.integration`.
4. **Contract tests.** Each consumer plan includes at least one test asserting that its
   mock of a consumed interface matches the spec signature (argument names, order,
   return type). This is the mechanism that makes parallel work safe.
5. **Determinism.** Tests must be deterministic: fixed seeds, frozen timestamps via
   injection, no reliance on wall-clock or execution order.

---

## 6. Definition of Done (per plan)

A plan is DONE when all of the following hold:

- [ ] All 25 sub-phases marked complete in the plan's status log.
- [ ] All owned files created and conforming to their cited specs.
- [ ] Owned unit tests pass; coverage of owned modules ≥ 80 %.
- [ ] `ruff check`, `ruff format --check`, `mypy --strict` clean on owned paths.
- [ ] No file outside the plan's ownership matrix was created or modified.
- [ ] Every source-code change cites at least one registered skill ID.
- [ ] Handoff note appended to the plan's status log: deviations (none expected),
      spec-gap requests, and integration notes for Plans 4/5.

---

## 7. Change Control

1. An agent needing a spec change files a **Spec Change Request (SCR)** in its plan's
   status log: `SCR-<plan>-<n>: <spec-id> <section> — problem — proposed change`.
2. The orchestrator (human or coordinator agent) adjudicates, updates `spec/`, bumps the
   spec version, and broadcasts the change in `planning/README.md` § Broadcasts.
3. Until adjudicated, the agent continues with all *unaffected* sub-phases. Blocking is
   limited to the specific sub-phase.
