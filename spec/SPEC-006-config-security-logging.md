# SPEC-006 — Configuration, Security & Observability

**Version:** 1.0.0 · **Status:** FROZEN
**Implemented by:** Plan 1 (`config/`, `logging/`), Plan 2 (sandbox enforcement)
**Consumed by:** All plans

Source of truth: vision § 9 (Security & Sandboxing), § 10 (Logging & Observability), § 11 (Configuration), § 13 (Error Handling).

---

## 1. Configuration Schema — FROZEN

`agent_harness/config/loader.py` loads YAML + env into typed dataclasses
(`agent_harness/config/schema.py`). Every key below must exist with the stated default.
Unknown top-level sections raise `AgentError(code="CONFIG_VALIDATION_FAILED")`; unknown
keys inside a known section produce a `WARNING` and are ignored.

```yaml
llm:
  provider: "openai"              # openai | anthropic | local
  model: "gpt-4o"
  fallback_model: null            # optional cheaper/alternate model
  api_key_env: "OPENAI_API_KEY"   # name of env var; never the key itself
  base_url: null                  # override for local/proxy endpoints
  max_tokens: 4096
  temperature: 0.2
  timeout: 60
  max_retries: 3
  cost_per_1k_tokens: null        # optional float, for cost estimates

execution:
  max_steps: 20
  step_timeout: 120
  max_retries: 2
  retry_backoff: "exponential"    # exponential | linear | fixed
  retry_base_delay: 2
  enable_replan: true
  abort_on_critical_failure: true
  output_dir: "./output"
  temp_dir: "./tmp"

search:
  provider: "duckduckgo"          # serpapi | bing | duckduckgo | google
  api_key_env: "SEARCH_API_KEY"
  max_results: 10

security:
  sandbox_code: true
  code_timeout: 30
  max_output_bytes: 1000000
  network_in_code: false
  allow_shell: false              # ADDITIVE to vision; shell_command is opt-in
  sensitive_patterns:
    - "\\b\\d{3}-\\d{2}-\\d{4}\\b"
    - "sk-[a-zA-Z0-9]{48}"

logging:
  level: "INFO"                   # DEBUG | INFO | WARNING | ERROR
  file: "./logs/agent_harness.log"
  format: "json"                  # json | text
  console: true

plugins:
  dirs: ["./plugins", "~/.agent_harness/plugins"]
  auto_load: true
```

### 1.1 Typed accessors

```python
Config.from_file(path) -> Config
Config.from_dict(d) -> Config
config.llm.provider            # attribute access, typed dataclasses per section
config.get("execution.max_steps", default=None)   # dotted-path lookup
config.to_dict(redact_secrets=True) -> dict       # safe for logs/context
```

`to_dict()` MUST exclude any resolved secret values; only `*_env` names appear.

### 1.2 Precedence (highest → lowest)

1. Explicit CLI flag (`--output-dir`, `--log-level`, `--max-steps`, `--no-fallback`)
2. Environment variable (`AGENT_HARNESS_CONFIG`, `AGENT_HARNESS_LOG_LEVEL`, `AGENT_HARNESS_OUTPUT_DIR`)
3. Config file
4. Built-in defaults from this spec

### 1.3 Validation rules

| Rule | Detail |
|---|---|
| K1 | `provider`, `retry_backoff`, `search.provider`, `logging.level`, `logging.format` are enums; invalid value → `CONFIG_VALIDATION_FAILED` naming the allowed set |
| K2 | All integers > 0; `temperature` in `[0.0, 2.0]` |
| K3 | `sensitive_patterns` must compile as regexes; invalid pattern → error naming the pattern |
| K4 | `output_dir`/`temp_dir`/`logging.file` parent dirs are created lazily by consumers, never by the loader |
| K5 | Missing API key env var is detected at `create_llm_client()` time, not config load (so `--list-tools` works without keys) |

---

## 2. Environment Variables

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Default LLM credential |
| `ANTHROPIC_API_KEY` | Anthropic provider credential |
| `SEARCH_API_KEY` | SerpAPI/Bing search credential (optional) |
| `AGENT_HARNESS_CONFIG` | Config path override |
| `AGENT_HARNESS_LOG_LEVEL` | Log level override |
| `AGENT_HARNESS_OUTPUT_DIR` | Output dir override (additive) |

`.env.example` (Plan 1) lists all of the above with placeholder values and comments; it
contains **no real secrets**. `.env` is gitignored (Plan 5).

---

## 3. Data Privacy Controls — FROZEN

1. All execution is local; the only outbound traffic is LLM API calls plus explicitly
   invoked web tools.
2. `sensitive_data_filter(text) -> tuple[str, int]` lives in `agent_harness/config/loader.py`
   (shared utility) and applies every `security.sensitive_patterns` regex, replacing
   matches with `[REDACTED]`. Applied to **all** outbound LLM message content
   (SPEC-004 § 1.2 C4).
3. Startup warns when `.env` defines keys that will be transmitted (SPEC-005 § 4).
4. Logs never contain: API keys, full request bodies to LLM providers, or file contents
   larger than 500 chars (truncate with an explicit marker).

---

## 4. Code Execution Sandbox — FROZEN

Applies to `code_execute` (Plan 2). Enforcement is layered; each layer is independently
tested.

| Layer | Rule |
|---|---|
| S1 — Static blocklist | Reject before execution if any `BLOCKED_PATTERNS` entry appears in the code (verbatim list from vision § 9.1, extended below) |
| S2 — AST analysis | Parse with `ast`; reject `Import`/`ImportFrom` of blocked modules (`subprocess`, `ctypes`, `socket`, `shutil`, `multiprocessing`, `importlib`), calls to `eval`/`exec`/`compile`/`__import__`, and access to dunder attributes (`__globals__`, `__subclasses__`, `__builtins__`) |
| S3 — Process isolation | `subprocess.run([sys.executable, tmpfile], shell=False)` in `tempfile.gettempdir()` |
| S4 — Env scrub | Child env limited to `PATH`, `PYTHONPATH=""`, `LANG`, `TMPDIR`, plus `PYTHONIOENCODING=utf-8`. **No API keys, no `HOME`, no user env leakage.** |
| S5 — Timeout | `config.security.code_timeout` (default 30 s); on expiry kill the process group and return `AgentError`-class result `SANDBOX_TIMEOUT` |
| S6 — Output cap | stdout/stderr truncated to `config.security.max_output_bytes` |
| S7 — Network | When `security.network_in_code` is false, blocked at the AST layer (`socket`, `urllib.request`, `http.client`, `requests`, `httpx`) — best-effort static control, documented as such |
| S8 — Cleanup | Temp script always removed in a `finally` block |

Blocked-pattern list (extends vision § 9.1):

```text
"import os; os.system"   "subprocess"        "shutil.rmtree"
"__import__('os').system" "eval("            "exec("
"open('/etc"             "open('C:\\Windows" "os.environ"
"socket."                "ctypes"            "__subclasses__"
```

A rejected run returns `ToolResult(success=False, error="Blocked pattern detected: <p>",
metadata={"violation": "SANDBOX_VIOLATION", "retryable": False})`. Sandbox violations are
**never** retried at Level 1 (SPEC-003 § 5).

---

## 5. Shell Command Whitelist — FROZEN

```text
ls  dir  cat  head  tail  wc  grep  find  echo  date  pwd
python  pip  node  npm  curl  wget
git status   git log   git diff
```

Rules: match the first token (or first two for `git …`); everything else rejected with
`SANDBOX_VIOLATION`, `retryable=False`. No shell metacharacters permitted in `command` or
`args` (`;`, `&&`, `||`, `|`, `` ` ``, `$(`, `>`, `<`, newline). The whole tool is inert
unless `security.allow_shell: true`.

---

## 6. Logging Schema — FROZEN

`agent_harness/logging/logger.py` provides `StructuredLogger`. One JSON object per line
(JSONL) to `logging.file`, plus optional human-readable console output.

```json
{
  "timestamp": "2024-12-15T10:23:45.123Z",
  "level": "INFO",
  "component": "orchestrator",
  "event": "step_completed",
  "plan_id": "a1b2c3d4",
  "step_id": "step_0",
  "step_description": "Search for GPT-4 usage statistics",
  "tool_name": "web_search",
  "duration_ms": 2340,
  "status": "success",
  "retry_count": 0,
  "context_size_bytes": 4521,
  "llm_tokens_used": 0,
  "metadata": { "results_count": 10, "query": "…" }
}
```

### 6.1 Required events

| Event | Emitted by | When |
|---|---|---|
| `harness_start` / `harness_complete` | harness | Run boundaries |
| `plan_generated` | planner | After successful validation (includes step count, unresolved hints) |
| `plan_validation_failed` | planner | On `PLAN_VALIDATION_FAILED` |
| `step_started` / `step_completed` / `step_failed` | orchestrator | Step boundaries |
| `step_skipped` | orchestrator | Dependency unmet or escalation |
| `recovery_attempted` | recovery | Each level, with `metadata.level` ∈ {1,2,3,4} and `metadata.action` |
| `recovery_succeeded` / `recovery_exhausted` | recovery | Outcome |
| `tool_executed` | tools (via orchestrator) | Every tool call incl. retries |
| `sandbox_violation` | tools | Blocked pattern / whitelist rejection |
| `llm_call` | llm client | Model, tokens, latency, finish_reason, redaction count |
| `plugin_loaded` / `plugin_failed` | plugins | Per plugin file |
| `config_loaded` | config | Path, provider, effective overrides (secrets redacted) |
| `output_written` | orchestrator | Each entry appended to `files_created` |

### 6.2 Logger API

```python
class StructuredLogger:
    def __init__(self, config) -> None: ...
    def log(self, level: str, component: str, event: str, **fields) -> None: ...
    def debug/info/warning/error(self, component, event, **fields) -> None
    def child(self, component: str, **bound_fields) -> "StructuredLogger"
    @staticmethod
    def default() -> "StructuredLogger"     # no-config fallback for tests
```

`child()` binds `component`/`plan_id` so call sites stay terse. Logger is dependency-injected
everywhere; module-level singletons are forbidden.

---

## 7. Execution Report

`agent_harness/logging/report.py`:

```python
def render_report(plan: ExecutionPlan, metrics: ExecutionMetrics, *,
                  style: str = "text") -> str
```

`style="text"` reproduces the vision § 10.2 layout (banner, plan ID, prompt, status,
duration, step counters, token/cost line, files created, per-step lines with
`[✓] [✗] [⟳] [–]` markers, then an "Errors Encountered" section). `style="markdown"`
emits the same content as a markdown document suitable for writing into `output_dir`.
Report rendering is **pure** — it reads the plan and metrics and never performs I/O.

---

## 8. Error Category → Handling Matrix

| Category | Examples | Handling |
|---|---|---|
| LLM | timeout, rate limit, invalid response | Client-level retry w/ backoff → fallback model → `LLM_CALL_FAILED` |
| Tool | search API down, file not found, code syntax error | Tool retry → fallback tool → re-plan (SPEC-003 § 5) |
| Planning | circular deps, invalid refs | Validate before execution; re-plan once; then `PLAN_VALIDATION_FAILED` |
| System | disk full, permission denied, OOM | Abort with `SYSTEM_ERROR` and remediation text |
| User input | empty prompt, oversized prompt | Reject at entry with `PROMPT_INVALID`; CLI exits 2 |
