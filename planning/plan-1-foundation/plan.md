# Plan 1 — Core Foundation

**Plan ID:** P1 · **Workstream:** Data Model, Configuration, Context, Logging & LLM Client
**Execution:** independent — may run concurrently with P2–P5 · **Sub-phases:** 25 (5 phases × 5)

---

## 0. Plan Header

| Field | Value |
|---|---|
| Mission | Deliver the L0 substrate every other plan consumes: typed core data model, configuration system, context store, structured logging/reporting, and the provider-agnostic LLM client — exactly per SPEC-001, SPEC-004 § 1, SPEC-006. |
| Owned paths | SPEC-000 § 3.1 — `agent_harness/config/`, `agent_harness/context/`, `agent_harness/logging/`, `agent_harness/llm/`, `pyproject.toml`, `config.yaml`, `.env.example`, `tests/test_config.py`, `tests/test_context.py`, `tests/test_logging.py`, `tests/test_llm.py` |
| Consumed specs | SPEC-000, SPEC-001 (owns), SPEC-004 § 1 (owns LLM client), SPEC-006 (owns config/logging; enforces) |
| Produces for others | `Step`, `ExecutionPlan`, `AgentError`, `ExecutionMetrics` (P3/P4); `Config` (all); `ContextStore` (P3); `StructuredLogger` (all); `LLMClient` + `MockLLMClient` (P2/P3/P4/P5); `default config.yaml` (P4/P5); packaging baseline (P5 CI) |
| External deps | None on other plans. Mocks nothing; everything here is self-contained. |
| Skill gate | ⛔ No source change until an active skill covers it (`.agent/agent.md` § 6). Dictionary currently empty → status: gated. |

**Independence declaration.** This plan touches only its owned paths, imports nothing from
`agent_harness.tools`, `planning`, `orchestration`, `harness`, or `plugins`, and can be
completed start-to-finish while P2–P5 run in parallel.

---

## Phase 1 — Packaging & Module Scaffolding

> Outcome: an installable package skeleton with pinned tooling, default config, and env
> template — so all later phases (and P5's CI) have a stable base.

### Sub-phase 1.1 — Project metadata & dependencies
- **Tasks:** author `pyproject.toml` per vision § Installation: name `agent-harness`, version `0.1.0`, `requires-python >=3.9`; runtime deps (`openai`, `pyyaml`, `python-dotenv`, `requests`, `beautifulsoup4`, `duckduckgo-search`, `pdfkit`, `rich`); extras `dev` (`pytest`, `pytest-cov`, `ruff`, `mypy`) and `anthropic`.
- **Deliverable:** `pyproject.toml`.
- **Exit criteria:** `pip install -e ".[dev]"` succeeds on a clean venv; dependency versions match the vision document.

### Sub-phase 1.2 — Toolchain configuration blocks
- **Tasks:** add spec-mandated `[tool.ruff]`, `[tool.mypy]` (`strict = true`), and `[tool.pytest.ini_options]` sections exactly as fixed by SPEC-000 § 4–5 (markers: `integration`; testpaths: `tests`).
- **Deliverable:** toolchain sections inside `pyproject.toml`.
- **Exit criteria:** `ruff check`, `mypy`, `pytest` all runnable with zero configuration outside `pyproject.toml`.

### Sub-phase 1.3 — Owned package skeleton
- **Tasks:** create `config/`, `context/`, `logging/`, `llm/` subpackages with docstring-only `__init__.py` files (no logic yet); module files created empty-with-docstring per SPEC-000 § 3.1.
- **Deliverable:** importable `agent_harness.config|context|logging|llm` namespaces.
- **Exit criteria:** `python -c "import agent_harness.config"` etc. succeed; mypy clean on skeletons.

### Sub-phase 1.4 — Default `config.yaml`
- **Tasks:** write `config.yaml` containing every key of SPEC-006 § 1 with the exact stated defaults, including additive keys (`fallback_model`, `max_retries`, `cost_per_1k_tokens`, `enable_replan`, `abort_on_critical_failure`, `allow_shell`).
- **Deliverable:** `config.yaml`.
- **Exit criteria:** file parses as YAML; key-for-key diff against SPEC-006 § 1 shows no omission.

### Sub-phase 1.5 — `.env.example` & secret hygiene baseline
- **Tasks:** write `.env.example` listing all env vars of SPEC-006 § 2 with placeholders and comments; verify no real secret patterns; note that `.gitignore` ownership belongs to P5 (do not create it).
- **Deliverable:** `.env.example`.
- **Exit criteria:** `security.sensitive_patterns` regexes match nothing in the file; documented in handoff that `.env` must be ignored by P5's `.gitignore`.

---

## Phase 2 — Core Data Model (SPEC-001)

> Outcome: every shared type implemented, validated, and round-trippable — the contract P2/P3/P4 code against.

### Sub-phase 2.1 — Enumerations
- **Tasks:** implement `StepStatus` and `TaskPriority` exactly per SPEC-001 § 1 (members, values).
- **Deliverable:** enums in `config/schema.py`.
- **Exit criteria:** value set matches spec; `StepStatus("pending")`-style construction works.

### Sub-phase 2.2 — `Step` dataclass & invariants
- **Tasks:** implement `Step` per SPEC-001 § 2.1 (all fields/defaults); enforce invariants (status↔error consistency, `retries ≤ max_retries`) via a `validate()` method raising `AgentError`-class errors; implement `duration_ms` property.
- **Deliverable:** `Step` + validation.
- **Exit criteria:** unit tests cover every invariant, including both violation and satisfaction.

### Sub-phase 2.3 — `ExecutionPlan` dataclass
- **Tasks:** implement `ExecutionPlan` per SPEC-001 § 2.2; `step_by_id()`; plan-status derivation rule (SUCCESS/FAILED per spec) as a pure helper.
- **Deliverable:** `ExecutionPlan`.
- **Exit criteria:** tests for status derivation incl. degraded (`metadata["degraded"]`) case.

### Sub-phase 2.4 — `AgentError` & error-code catalog
- **Tasks:** implement `AgentError` per SPEC-001 § 2.4; encode the full SPEC-001 § 3 code catalog as constants/enum; `__str__` format `"[code] component(step_id): message"`.
- **Deliverable:** `AgentError` + `ErrorCode` catalog.
- **Exit criteria:** every catalog code present; string format asserted in tests.

### Sub-phase 2.5 — Serialization layer
- **Tasks:** implement `to_dict`/`from_dict` for `Step`, `ExecutionPlan`, `AgentError`, `ExecutionMetrics` per SPEC-001 § 4 (enums→values, datetimes→ISO-8601, unknown keys ignored, round-trip equality); `ExecutionMetrics` dataclass + `from_plan` signature stub delegating computation rules to P3 (SPEC-003 § 7) — P1 provides the container and serialization only.
- **Deliverable:** full JSON-safe round-trip for all types.
- **Exit criteria:** property-style round-trip tests pass for nested plans with all statuses; `ExecutionMetrics.to_dict()` JSON-serializable.

---

## Phase 3 — Configuration System (SPEC-006 § 1–3)

> Outcome: typed, validated, precedence-correct configuration with secret indirection.

### Sub-phase 3.1 — Config dataclasses & schema
- **Tasks:** typed section dataclasses (`LLMConfig`, `ExecutionConfig`, `SearchConfig`, `SecurityConfig`, `LoggingConfig`, `PluginsConfig`) mirroring SPEC-006 § 1 exactly; aggregate `Config` with attribute access and dotted `config.get("a.b")`.
- **Deliverable:** `config/schema.py` config types.
- **Exit criteria:** mypy strict clean; defaults match spec table key-for-key (test asserts full dump).

### Sub-phase 3.2 — YAML + `.env` loader
- **Tasks:** `Config.from_file()`/`from_dict()`: YAML parse, `python-dotenv` loading, unknown-section error / unknown-key warning behavior per SPEC-006 § 1.
- **Deliverable:** `config/loader.py` core.
- **Exit criteria:** tests for: valid file, missing file (`CONFIG_LOAD_FAILED`), unknown section, unknown key warning.

### Sub-phase 3.3 — Validation rules K1–K5
- **Tasks:** implement SPEC-006 § 1.3: enum checks, positivity, temperature range, regex compilation of `sensitive_patterns`, lazy dir creation policy, deferred API-key check.
- **Deliverable:** validation pass inside loader.
- **Exit criteria:** each K-rule has a failing-input and passing-input test.

### Sub-phase 3.4 — Precedence & overrides
- **Tasks:** implement precedence chain CLI-flag hooks (expose `Config.apply_overrides(**kwargs)` for P4) > env (`AGENT_HARNESS_CONFIG`, `AGENT_HARNESS_LOG_LEVEL`, `AGENT_HARNESS_OUTPUT_DIR`) > file > defaults, per SPEC-006 § 1.2.
- **Deliverable:** override machinery.
- **Exit criteria:** precedence matrix test (all 4 layers, conflicting values).

### Sub-phase 3.5 — Secret handling & redaction utility
- **Tasks:** `api_key_env` indirection (never store key values in `Config.to_dict()`); shared `sensitive_data_filter(text) -> (text, count)` per SPEC-006 § 3.2; `to_dict(redact_secrets=True)`.
- **Deliverable:** redaction utilities + safe dump.
- **Exit criteria:** tests prove keys absent from dumps/context and that SSN/API-key patterns are redacted with counts.

---

## Phase 4 — Context Store, Structured Logging & Reports

> Outcome: state carriage across steps and full observability per SPEC-003 § 4 / SPEC-006 § 6–7.

### Sub-phase 4.1 — `ContextStore`
- **Tasks:** implement store exposing the FROZEN layout of SPEC-003 § 4.1 as a plain dict-compatible object (`as_dict()`, typed accessors for `step_results`, `variables`, `files_created`, `errors`); fresh-per-run factory.
- **Deliverable:** `context/store.py`.
- **Exit criteria:** layout test asserts every spec key exists after init; dict interop (`store.as_dict()` consumable by tools).

### Sub-phase 4.2 — Context recording & size guards
- **Tasks:** `record_step_result()` writing the exact SPEC-003 § 4.1 entry shape; `add_error()`; `add_file()` (dedupe, order); context size measurement (`context_size_bytes` for logs) with configurable soft cap that truncates stored step outputs beyond N bytes (keeping type + marker).
- **Deliverable:** guarded recording API.
- **Exit criteria:** tests for dedupe, ordering, truncation marker, and byte-size reporting.

### Sub-phase 4.3 — `StructuredLogger`
- **Tasks:** implement SPEC-006 § 6.2 API (`log`, level helpers, `child()`, `default()`); JSONL file sink + console sink; ISO-8601 timestamps; component/plan/step binding via `child()`.
- **Deliverable:** `logging/logger.py`.
- **Exit criteria:** emitted lines parse as JSON and contain all fields of the SPEC-006 § 6 schema; `child()` bindings verified.

### Sub-phase 4.4 — Redaction pipeline & log safety
- **Tasks:** route all log field values through `sensitive_data_filter`; enforce SPEC-006 § 3.4 (no keys, no provider bodies, >500-char content truncated); level filtering per config.
- **Deliverable:** safe logging pipeline.
- **Exit criteria:** adversarial test: logging a fake API key + long blob yields redacted/truncated output only.

### Sub-phase 4.5 — Execution report renderer
- **Tasks:** `render_report(plan, metrics, style)` per SPEC-006 § 7: pure function; `text` style reproduces the vision § 10.2 layout incl. `[✓] [✗] [⟳] [–]` markers and Errors section; `markdown` style equivalent.
- **Deliverable:** `logging/report.py`.
- **Exit criteria:** golden-file test against a fixed plan+metrics fixture for both styles; no I/O performed.

---

## Phase 5 — LLM Client Abstraction & Handoff

> Outcome: the single LLM gateway used by P2/P3/P4, with providers, accounting, redaction, and a mock for everyone's tests.

### Sub-phase 5.1 — `LLMClient` ABC & data types
- **Tasks:** implement FROZEN interface SPEC-004 § 1 (`complete`, `complete_json`, `usage`; `LLMResponse`, `LLMUsage`).
- **Deliverable:** `llm/client.py` interface layer.
- **Exit criteria:** contract test: signature/return types match spec verbatim (this test is the mock-agreement anchor for P2/P3).

### Sub-phase 5.2 — `MockLLMClient`
- **Tasks:** scripted-queue mock per SPEC-004 § 1.2 C7: queued responses, optional JSON payloads, deterministic usage counters, optional failure injection (`raise_on_call=n`).
- **Deliverable:** `MockLLMClient` in `llm/client.py`.
- **Exit criteria:** P5/other plans can rely on it: documented in handoff; tests cover queue exhaustion behavior.

### Sub-phase 5.3 — Provider adapters & factory
- **Tasks:** `OpenAIClient` (honoring `base_url`), `AnthropicClient` (guarded import, message translation), `LocalCompatClient`; `create_llm_client(config)` per SPEC-004 § 1.3 with `CONFIG_VALIDATION_FAILED` on missing key env var.
- **Deliverable:** `llm/providers.py`.
- **Exit criteria:** adapter HTTP layer fully mocked in tests; factory error paths covered; anthropic-extra-missing path covered.

### Sub-phase 5.4 — Reliability, accounting & redaction behavior C1–C6
- **Tasks:** transient-retry with backoff + `Retry-After` (C1); fallback model (C2); `complete_json` fence-stripping + one repair round (C3); outbound redaction with `redactions` count (C4); usage/cost accumulation (C5); no-secrets-in-logs audit (C6).
- **Deliverable:** hardened client behaviors.
- **Exit criteria:** per-rule tests: retry schedule timing (injected sleep), repair-round success/failure, cost math, redaction counts.

### Sub-phase 5.5 — Conformance verification & handoff
- **Tasks:** run full owned test suite + coverage ≥ 80 %; ruff/mypy clean; verify every public symbol cites its spec section; append Handoff Note: exported API summary for P2–P5, `MockLLMClient` usage guide, config keys P4 must surface via CLI, redaction utility location for P2 tools.
- **Deliverable:** P1 conformance report inside Status Log; progress board updated.
- **Exit criteria:** SPEC-000 § 6 Definition of Done fully satisfied for P1.

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
