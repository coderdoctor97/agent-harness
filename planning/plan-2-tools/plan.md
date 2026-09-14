# Plan 2 — Tool System

**Plan ID:** P2 · **Workstream:** Tool Interface, Registry, Built-in Tools & Sandbox
**Execution:** independent — may run concurrently with P1, P3–P5 · **Sub-phases:** 25 (5 phases × 5)

---

## 0. Plan Header

| Field | Value |
|---|---|
| Mission | Deliver the L1 capability layer: `BaseTool`/`ToolResult`/`ToolRegistry` plus all 10 built-in tools with their exact I/O contracts and the security sandbox, per SPEC-002 and SPEC-006 § 4–5. |
| Owned paths | SPEC-000 § 3.2 — `agent_harness/tools/` (all files), `tests/test_tools/` |
| Consumed specs | SPEC-000, SPEC-001 § 2.3 (`ToolResult` shape), SPEC-002 (owns), SPEC-004 § 1 (`LLMClient` for LLM tools), SPEC-006 § 1/4/5 (config, sandbox, whitelist) |
| Produces for others | `ToolRegistry` + `BaseTool` (P3 orchestrator, P4 plugins); `default_tools(config, llm_client)` (P4 composition); `ToolResult` re-export (plugin authors) |
| Parallel-work rule | P1's `Config`/`LLMClient` may not exist yet → develop against **spec-shaped local fakes** inside `tests/test_tools/` (owned by this plan). Never import `agent_harness.config` or `agent_harness.llm` types beyond what SPEC-001/004 freeze; accept them as injected duck-typed objects. |
| Skill gate | ⛔ No source change until an active skill covers it (`.agent/agent.md` § 6). Dictionary currently empty → status: gated. |

**Independence declaration.** This plan touches only `agent_harness/tools/` and
`tests/test_tools/`. It imports nothing from `planning`, `orchestration`, `harness`,
`plugins`, `context`, or `logging`; logger and config arrive by injection.

---

## Phase 1 — Tool Foundation

> Outcome: the contracts every other tool and the orchestrator rely on, fully tested.

### Sub-phase 1.1 — `ToolResult` & result helpers
- **Tasks:** implement `ToolResult` exactly per SPEC-001 § 2.3; helpers `ok(output, **meta)`, `fail(error, *, retryable=False, **meta)` that auto-set `tool_name`/`duration_ms` metadata (SPEC-002 § 1.1 R4).
- **Deliverable:** `tools/base.py` result layer.
- **Exit criteria:** field set frozen-match test; helpers populate required metadata keys.

### Sub-phase 1.2 — `BaseTool` ABC
- **Tasks:** implement the FROZEN ABC per SPEC-002 § 1 (`name`, `description`, `capabilities`, `execute`, `validate_input`, `cleanup`); document rules R1–R8 as the class docstring contract.
- **Deliverable:** `BaseTool`.
- **Exit criteria:** abstract instantiation raises; defaults for `capabilities`/`validate_input`/`cleanup` behave per spec.

### Sub-phase 1.3 — Execution wrapper enforcing R1/R2/R4/R5
- **Tasks:** a `run_tool(tool, input_data, context, *, config, logger)` helper (or `BaseTool.__call__`-style wrapper) that: calls `validate_input` first (R2), times execution, catches escaping exceptions into `ToolResult(success=False)` (R1), applies output truncation at `max_output_bytes` (R5), emits `tool_executed` log fields.
- **Deliverable:** uniform execution path in `tools/base.py`.
- **Exit criteria:** a deliberately raising fake tool yields a failure result, never an exception; truncation marker + `metadata["truncated"]` asserted.

### Sub-phase 1.4 — `ToolRegistry`
- **Tasks:** implement SPEC-002 § 2 exactly: `register` (TypeError guard G1), `get`, `find_by_capability`, `list_tools` (insertion-ordered G3), `deregister` (no-op G5), `names()`; overwrite warning G2.
- **Deliverable:** `ToolRegistry` in `tools/base.py`.
- **Exit criteria:** every rule G1–G5 has a dedicated test; duplicate-name warning captured.

### Sub-phase 1.5 — Shared test doubles & fixture kit
- **Tasks:** build `tests/test_tools/doubles.py`: `FakeConfig` (spec-shaped attribute tree), `FakeLLMClient` (scripted completions), `FakeLogger` (records events), `EchoTool`/`BoomTool` (success/failure), tmp workspace fixture.
- **Deliverable:** reusable doubles for this plan (and documented as the pattern for P3/P4 in the handoff).
- **Exit criteria:** doubles satisfy SPEC-001/004/006 shapes; suite runs with zero network/subprocess.

---

## Phase 2 — Retrieval Tools (web_search, web_scrape)

> Outcome: the research entry points of the harness, provider-pluggable and fully mocked in tests.

### Sub-phase 2.1 — Search provider abstraction
- **Tasks:** internal `SearchProvider` protocol (`search(query, num_results, region) -> list[RawResult]`) with DuckDuckGo (default, keyless), SerpAPI, Bing adapters selected by `config.search.provider`; API key resolved via `config.search.api_key_env`.
- **Deliverable:** provider layer inside `tools/web_search.py`.
- **Exit criteria:** provider selection matrix test; missing key produces a clear `retryable=False` failure.

### Sub-phase 2.2 — `web_search` tool
- **Tasks:** implement I/O contract SPEC-002 § 3.1: inputs (`query` required, `num_results` default from config, `region`), normalized output `{title,url,snippet}`; capabilities `["search","web","research"]`; empty results = success with `metadata["no_results"]`.
- **Deliverable:** `web_search`.
- **Exit criteria:** contract test against spec table incl. the empty-result semantics (critical for US-3 recovery testing by P3/P5).

### Sub-phase 2.3 — `web_scrape` tool
- **Tasks:** implement SPEC-002 § 3.2: requests + BeautifulSoup extraction, optional CSS selector, `max_length` truncation, 20 s timeout, descriptive User-Agent, strip `script/style/nav`.
- **Deliverable:** `web_scrape`.
- **Exit criteria:** HTML fixture tests (selector hit/miss, truncation, non-200, timeout → `retryable=True`).

### Sub-phase 2.4 — Network failure classification
- **Tasks:** map provider/HTTP errors onto `retryable` metadata: timeouts, 429/5xx → retryable; 4xx (not 429), DNS failure, invalid URL → not retryable; errors worded for LLM re-planning consumption.
- **Deliverable:** error-classification layer for both web tools.
- **Exit criteria:** classification table test per error class; messages include the status code/URL.

### Sub-phase 2.5 — Retrieval tool hardening & tests
- **Tasks:** input validation completeness, output size caps (R5), deterministic ordering of results, `metadata["query"]`/`["provider"]` for logging; consolidate unit tests (no live HTTP anywhere).
- **Deliverable:** hardened retrieval tools + suite.
- **Exit criteria:** coverage of both modules ≥ 80 %; ruff/mypy clean.

---

## Phase 3 — Execution Tools & Sandbox (code_execute, shell_command)

> Outcome: safe local computation — the vision's security-critical surface (SPEC-006 § 4–5).

### Sub-phase 3.1 — `CodeSandbox` core
- **Tasks:** implement layers S3/S4/S5/S6/S8 of SPEC-006 § 4: temp script, `subprocess.run([sys.executable, …], shell=False)`, scrubbed env (PATH, PYTHONPATH="", LANG, TMPDIR, PYTHONIOENCODING only), timeout with process-group kill, output cap, guaranteed cleanup.
- **Deliverable:** sandbox engine inside `tools/code_execute.py`.
- **Exit criteria:** real trivial subprocess test passes; env-leak test proves parent env vars (incl. fake `OPENAI_API_KEY`) are invisible to the child.

### Sub-phase 3.2 — Static analysis layers S1/S2/S7
- **Tasks:** blocked-pattern scan (verbatim list, SPEC-006 § 4) then AST analysis: blocked imports, `eval/exec/compile/__import__` calls, dunder attribute access, network modules when `network_in_code=false`.
- **Deliverable:** pre-execution rejection pipeline.
- **Exit criteria:** every blocked construct has a rejection test; benign code (loops, stdlib math/json/csv) passes; violations return `SANDBOX_VIOLATION`, `retryable=False`.

### Sub-phase 3.3 — `code_execute` tool surface
- **Tasks:** SPEC-002 § 3.3 contract: exactly-one-of `code`/`task` validation; stdout as output, stderr/returncode in metadata; timeout → `SANDBOX_TIMEOUT`; honor `config.security.sandbox_code=false` (direct exec, documented risk) .
- **Deliverable:** `code_execute`.
- **Exit criteria:** contract tests for both input modes, non-zero exit, timeout (1 s cap), metadata completeness.

### Sub-phase 3.4 — Task-mode code generation
- **Tasks:** `task` mode: prompt injected `llm_client` for code, save generated code to `config.execution.temp_dir`, report `metadata["generated_code_path"]`; on execution failure include stderr in the result so recovery can regenerate with error context (US-2).
- **Deliverable:** LLM-assisted task mode.
- **Exit criteria:** `FakeLLMClient` returns canned code → executed; failure path surfaces stderr + generated path.

### Sub-phase 3.5 — `shell_command` + whitelist
- **Tasks:** SPEC-002 § 3.10 + SPEC-006 § 5: whitelist matching (single/two-token), metacharacter rejection, `shell=False` argv execution, disabled-by-default behavior keyed to `config.security.allow_shell`.
- **Deliverable:** `shell_command`.
- **Exit criteria:** whitelist accept/reject matrix test; metacharacter injection attempts all rejected; disabled-mode message verified.

---

## Phase 4 — File & Data Tools

> Outcome: local I/O and data transformation with path-safety guarantees.

### Sub-phase 4.1 — `file_read`
- **Tasks:** SPEC-002 § 3.4: format auto-detection by extension; CSV→list[dict], JSON→object, TXT/MD→str, PDF→text (pypdf-class extraction guarded by availability); encoding param; missing-path suggestions (up to 3 similar names).
- **Deliverable:** `file_read`.
- **Exit criteria:** per-format fixture tests; suggestion behavior test; PDF-unavailable degrades with clear error.

### Sub-phase 4.2 — Path-safety guard (shared)
- **Tasks:** implement the allowed-root resolution used by `file_read`/`file_write` (SPEC-002 § 3.4/3.5 Safety rows): workspace roots, `output_dir`, `context["allowed_read_paths"|"allowed_write_paths"]`; `..` traversal rejection with `SANDBOX_VIOLATION`.
- **Deliverable:** `_paths.py`-internal guard (inside owned dir).
- **Exit criteria:** traversal attack tests (absolute escape, symlink-style, encoded `..`) all blocked.

### Sub-phase 4.3 — `file_write`
- **Tasks:** SPEC-002 § 3.5: atomic temp+replace write, `create_dirs`, output-dir restriction, confirmed path as output.
- **Deliverable:** `file_write`.
- **Exit criteria:** atomicity test (no partial file on simulated failure); dir creation; restriction enforcement.

### Sub-phase 4.4 — `csv_process`
- **Tasks:** SPEC-002 § 3.9: ordered operation pipeline (`filter/sort/head/tail/select/rename/aggregate`), per-operation validation with index in error, optional `output_path` write via the 4.3 machinery.
- **Deliverable:** `csv_process`.
- **Exit criteria:** each operation type tested incl. chaining and unknown-op/missing-column errors.

### Sub-phase 4.5 — `pdf_export` with degraded mode
- **Tasks:** SPEC-002 § 3.8: markdown/HTML → PDF via pdfkit when `wkhtmltopdf` present; binary detection at construction; degraded markdown fallback with `metadata["degraded"]`/`["actual_format"]`; `page_size` passthrough.
- **Deliverable:** `pdf_export`.
- **Exit criteria:** both modes tested (binary mocked absent/present); filename validation (`.pdf` suffix required).

---

## Phase 5 — LLM Tools, Default Bundle & Handoff

> Outcome: LLM-powered tools, the one-call bundle for P4, and verified spec conformance.

### Sub-phase 5.1 — `llm_extract`
- **Tasks:** SPEC-002 § 3.6: `input_text`+`instruction`+`output_format`; JSON mode parses (fence-stripping) via `llm_client.complete_json` when available else `complete` + local parse; client resolution order: constructor → `context["llm_client"]` → clear failure.
- **Deliverable:** `llm_extract`.
- **Exit criteria:** `FakeLLMClient` tests for all three output formats + malformed-JSON failure path.

### Sub-phase 5.2 — `llm_synthesize`
- **Tasks:** SPEC-002 § 3.7: source resolution order (`step_results` → `variables` → literal), `unresolved_sources` metadata, `tone`/`max_words` prompt composition.
- **Deliverable:** `llm_synthesize`.
- **Exit criteria:** resolution-order tests; unresolved sources never fail the tool.

### Sub-phase 5.3 — Tool package surface & `default_tools()`
- **Tasks:** `tools/__init__.py` per SPEC-002 § 2: re-export `BaseTool`, `ToolResult`, `ToolRegistry`; `default_tools(config, llm_client)` instantiating all 10 tools (pdf_export mode-detected; shell_command registered but inert per config).
- **Deliverable:** public tool package API.
- **Exit criteria:** bundle test: registry built from `default_tools()` lists exactly the 10 spec names; `list_tools()` shape matches SPEC-002 § 2.

### Sub-phase 5.4 — Capability tags & catalog conformance audit
- **Tasks:** verify every tool's `capabilities` ⊆ SPEC-002 § 4 vocabulary; verify every tool's `description` meets R7 (≤ 300 chars, states inputs/outputs); build a conformance table against SPEC-002 § 3.
- **Deliverable:** conformance matrix appended to Handoff Note.
- **Exit criteria:** 10/10 tools conform; `find_by_capability("llm")` returns exactly the two LLM tools, etc.

### Sub-phase 5.5 — Hardening sweep & handoff
- **Tasks:** full owned suite + coverage ≥ 80 %; ruff/mypy clean; adversarial pass on sandbox & path guards; Handoff Note for P3 (tool failure semantics, `retryable` conventions, `MockTool` guidance), P4 (`default_tools` wiring, plugin-facing exports), P5 (integration fixtures: deterministic tools).
- **Deliverable:** P2 conformance report + handoff.
- **Exit criteria:** SPEC-000 § 6 Definition of Done satisfied for P2.

---

## Status Log (owner-maintained)

### Agent Manifest
```yaml
# ── Agent Manifest ────────────────────────────────────────────
agent_id:        P2-tools-01
name:            Toolsmith
role:            implementer
plan:            planning/plan-2-tools/plan.md
owned_paths:
  - agent_harness/tools/__init__.py
  - agent_harness/tools/base.py
  - agent_harness/tools/web_search.py
  - agent_harness/tools/web_scrape.py
  - agent_harness/tools/code_execute.py
  - agent_harness/tools/file_read.py
  - agent_harness/tools/file_write.py
  - agent_harness/tools/llm_extract.py
  - agent_harness/tools/llm_synthesize.py
  - agent_harness/tools/pdf_export.py
  - agent_harness/tools/csv_process.py
  - agent_harness/tools/shell_command.py
  - tests/test_tools/
consumed_specs:
  - SPEC-000  # architecture boundaries
  - SPEC-001  # core data model (ToolResult)
  - SPEC-002  # tool system (owns)
  - SPEC-004  # LLMClient contract
  - SPEC-006  # config, sandbox, shell whitelist
produces:
  - agent_harness.tools.default_tools()
  - agent_harness.tools.base.ToolResult
  - agent_harness.tools.base.BaseTool
  - agent_harness.tools.base.ToolRegistry
  - tests/test_tools/*
skills_authorized:
  - mcp-tool-builder
  - tdd-test-runner
  - strict-typing-contracts
  - lint-formatting
  - threat-model-sast
  - auth-security
  - secret-credential-scanner
  - env-config-validator
status:          active
started_at:      2026-09-14T00:00:00Z
last_update:     2026-09-14T00:00:00Z
# ──────────────────────────────────────────────────────────────
```

### Phase Execution Log
| Sub-phase | State | Skill ID(s) | Note |
|---|---|---|---|
| 1.1 ToolResult & helpers | done | mcp-tool-builder, strict-typing-contracts, tdd-test-runner, lint-formatting | helpers populate tool_name/duration_ms, frozen fields verified |
| 1.2 BaseTool ABC | done | mcp-tool-builder, strict-typing-contracts, tdd-test-runner | ABC frozen contract, defaults verified |
| 1.3 Execution wrapper R1/R2/R4/R5 | done | mcp-tool-builder, strict-typing-contracts, tdd-test-runner | wrapper catches, validates, truncates, logs |
| 1.4 ToolRegistry | done | mcp-tool-builder, strict-typing-contracts, tdd-test-runner | G1-G5 verified, warnings, ordering |
| 1.5 Shared test doubles & fixtures | done | tdd-test-runner, strict-typing-contracts, mcp-tool-builder | FakeConfig/LLM/Logger/EchoTool pattern, zero network |
| 2.1 Search provider abstraction | done | mcp-tool-builder, strict-typing-contracts, tdd-test-runner | provider matrix & missing-key handling verified |
| 2.2 web_search tool | done | mcp-tool-builder, tdd-test-runner, strict-typing-contracts | empty-result flag, normalized output, retryable errors |
| 2.3 web_scrape tool | done | mcp-tool-builder, tdd-test-runner, strict-typing-contracts | HTML fixture, selector, truncation, timeout retryable |
| 2.4 Network failure classification | done | mcp-tool-builder, tdd-test-runner, threat-model-sast | timeout/429/5xx retryable, 4xx/DNS not, messages include code/URL |
| 2.5 Retrieval tool hardening | done | mcp-tool-builder, tdd-test-runner, strict-typing-contracts, threat-model-sast | coverage 89%, ruff/mypy clean, deterministic ordering |
| 3.1 CodeSandbox core S3/S4/S5/S6/S8 | done | threat-model-sast, auth-security, tdd-test-runner | sandbox isolation, env scrub, timeout, cap, cleanup verified |
| 3.2 Static analysis S1/S2/S7 | pending | — | — |
| 3.3 code_execute surface | pending | — | — |
| 3.4 Task-mode code generation | pending | — | — |
| 3.5 shell_command + whitelist | pending | — | — |
| 4.1 file_read | pending | — | — |
| 4.2 Path-safety guard | pending | — | — |
| 4.3 file_write | pending | — | — |
| 4.4 csv_process | pending | — | — |
| 4.5 pdf_export degraded | pending | — | — |
| 5.1 llm_extract | pending | — | — |
| 5.2 llm_synthesize | pending | — | — |
| 5.3 default_tools bundle | pending | — | — |
| 5.4 Capability tags audit | pending | — | — |
| 5.5 Hardening & handoff | pending | — | — |

### Skill Ledger
| Timestamp (ISO) | Sub-phase | Files | Skill ID(s) | Change summary | Gates passed |
|---|---|---|---|---|---|
| 2026-09-14T13:55:00Z | 1.1 | agent_harness/tools/base.py, agent_harness/tools/__init__.py, tests/test_tools/test_toolresult.py | mcp-tool-builder, strict-typing-contracts, tdd-test-runner, lint-formatting | Implement ToolResult per SPEC-001 §2.3 and ok/fail helpers with R4 defaults | tests, ruff, mypy |
| 2026-09-14T13:56:00Z | 1.2 | agent_harness/tools/base.py, agent_harness/tools/__init__.py, tests/test_tools/test_basetools.py | mcp-tool-builder, strict-typing-contracts, tdd-test-runner | Implement BaseTool ABC per SPEC-002 §1 with R1-R8 docstring | tests, ruff, mypy |
| 2026-09-14T13:57:00Z | 1.3 | agent_harness/tools/base.py, tests/test_tools/test_run_tool.py | mcp-tool-builder, strict-typing-contracts, tdd-test-runner, threat-model-sast | Implement run_tool enforcing R1/R2/R4/R5 with truncation and logging | tests, ruff, mypy |
| 2026-09-14T13:58:00Z | 1.4 | agent_harness/tools/base.py, agent_harness/tools/__init__.py, tests/test_tools/test_registry.py | mcp-tool-builder, strict-typing-contracts, tdd-test-runner | Implement ToolRegistry per SPEC-002 §2 G1-G5 | tests, ruff, mypy |
| 2026-09-14T13:59:00Z | 1.5 | tests/test_tools/doubles.py, tests/test_tools/test_doubles.py | tdd-test-runner, strict-typing-contracts, mcp-tool-builder | Build spec-shaped doubles kit for P3/P4 reuse | tests, ruff, mypy |
| 2026-09-14T14:00:00Z | 2.1 | agent_harness/tools/web_search.py, tests/test_tools/test_search_providers.py | mcp-tool-builder, strict-typing-contracts, tdd-test-runner | Implement search provider abstraction per SPEC-002 §3.1 | tests, ruff, mypy |
| 2026-09-14T14:01:00Z | 2.2 | agent_harness/tools/web_search.py, tests/test_tools/test_web_search.py | mcp-tool-builder, strict-typing-contracts, tdd-test-runner | Implement web_search I/O contract per SPEC-002 §3.1 | tests, ruff, mypy |
| 2026-09-14T14:02:00Z | 2.3 | agent_harness/tools/web_scrape.py, tests/test_tools/test_web_scrape.py | mcp-tool-builder, tdd-test-runner, strict-typing-contracts | Implement web_scrape per SPEC-002 §3.2 (BeautifulSoup, timeout, UA) | tests, ruff, mypy |
| 2026-09-14T14:03:00Z | 2.4 | agent_harness/tools/web_search.py, agent_harness/tools/web_scrape.py, tests/test_tools/test_network_classification.py | mcp-tool-builder, threat-model-sast, tdd-test-runner | Map provider/HTTP errors to retryable with LLM-friendly messages | tests, ruff, mypy |
| 2026-09-14T14:04:00Z | 2.5 | agent_harness/tools/web_search.py, agent_harness/tools/web_scrape.py, tests/test_tools/test_retrieval_hardening.py | mcp-tool-builder, tdd-test-runner, strict-typing-contracts, threat-model-sast | Harden retrieval tools: validation, caps, ordering, coverage ≥80% | tests, ruff, mypy |
| 2026-09-14T14:05:00Z | 3.1 | agent_harness/tools/code_execute.py, tests/test_tools/test_code_sandbox.py | threat-model-sast, auth-security, tdd-test-runner | Implement S3/S4/S5/S6/S8 sandbox core with env-leak and timeout tests | tests, ruff, mypy |
| — | — | — | — | _no source changes permitted yet_ | — |

### Spec/Skill Change Requests
_None filed._

### Handoff Note
_Written at Phase 5.5._
