# SPEC-005 — Harness API, CLI & Plugin System

**Version:** 1.0.0 · **Status:** FROZEN · **Implemented by:** Plan 4 · **Consumed by:** Plan 5 (integration tests), end users

Source of truth: Developer README § Usage, § Plugin Auto-Discovery, § Request Lifecycle; vision § 12 US-4.

---

## 1. Public API — FROZEN

`agent_harness/__init__.py` exports exactly:

```python
__all__ = ["AgentHarness", "Config", "HarnessResult", "__version__"]
```

```python
class AgentHarness:
    @classmethod
    def from_config(cls, path: str = "./config.yaml") -> "AgentHarness": ...
    def __init__(self, config: Config) -> None: ...

    def run(self, prompt: str, *, context: dict | None = None,
            output_format: str = "markdown") -> HarnessResult: ...
    def plan(self, prompt: str) -> ExecutionPlan: ...          # dry-run: plan only
    def register_tool(self, tool: BaseTool) -> None: ...
    def list_tools(self) -> list[dict]: ...
```

```python
@dataclass
class HarnessResult:
    status: str                    # "completed" | "partial" | "failed"
    final_output: Any
    plan: ExecutionPlan
    metrics: ExecutionMetrics
    files_created: list[str]
    errors: list[dict]
```

### 1.1 `run()` lifecycle (composition root)

```text
1. Validate prompt: non-empty after strip; ≤ 20 000 chars → else AgentError(PROMPT_INVALID)
2. Fresh ContextStore per run; seed context["variables"] from `context` argument;
   seed allowed_read_paths with any file paths found in the `context` argument
3. Create LLMClient (unless already injected for tests)
4. Build ToolRegistry: default_tools(config, llm_client) + plugin discovery
   (config.plugins.auto_load) + runtime-registered tools
5. Planner.plan(prompt, registry.list_tools())
6. Orchestrator.execute(plan)          # includes recovery cascade
7. Assembler.assemble(plan, context)   # → AssemblyResult
8. ExecutionMetrics.from_plan(...)     # → report via logging/report.py
9. Return HarnessResult
```

Failure inside steps 3–5 raises; failure inside 6–8 is **contained** and surfaced via
`HarnessResult.status`/`errors` (the harness always returns a result once a plan exists).

### 1.2 Output directory management

- `config.execution.output_dir` and `temp_dir` are created at harness init if missing.
- `files_created` in the result mirrors `context["files_created"]` (deduplicated, ordered).

---

## 2. CLI Contract — FROZEN

Entry point: `python -m agent_harness` (`agent_harness/__main__.py`).

```text
usage: python -m agent_harness [-h] [--config PATH] [--output-dir DIR]
                               [--log-level LEVEL] [--dry-run] [--list-tools]
                               [--max-steps N] [--no-fallback]
                               [prompt]
```

| Flag | Behavior |
|---|---|
| `prompt` (positional) | Task text. Required unless `--list-tools`. `-` reads prompt from stdin. |
| `--config PATH` | Config file (default `./config.yaml`, then `AGENT_HARNESS_CONFIG` env) |
| `--output-dir DIR` | Overrides `execution.output_dir` |
| `--log-level LEVEL` | `DEBUG\|INFO\|WARNING\|ERROR`; overrides config + `AGENT_HARNESS_LOG_LEVEL` |
| `--dry-run` | Print the plan (steps, tools, deps, priorities) and exit without executing |
| `--list-tools` | Print registry table (name, capabilities, description) and exit; no prompt needed |
| `--max-steps N` | Overrides `execution.max_steps` (positive int) |
| `--no-fallback` | Sets `execution.enable_replan=false` and strips fallback tools; recovery limited to Level 1 |

### 2.1 Exit codes

| Code | Meaning |
|---|---|
| 0 | `completed` (or `--dry-run`/`--list-tools` succeeded) |
| 1 | `failed` result or unhandled `AgentError` |
| 2 | CLI usage error (argparse) |
| 3 | `partial` result |
| 130 | Interrupted (SIGINT) |

### 2.2 Console rendering

- Uses `rich` when available (declared dependency): plan table, live step progress
  (via `ExecutionHooks`, SPEC-003 § 2.1), final execution report (SPEC-006 § 7).
- Degrades to plain text when stdout is not a TTY or `NO_COLOR`/`TERM=dumb` is set.
- Structured JSON logs always go to the log file regardless of console mode.

---

## 3. Plugin System — FROZEN behavior

Location: `agent_harness/plugins/loader.py`.

```python
def discover_tools(plugin_dirs: list[str], *, config=None, llm_client=None,
                   logger=None) -> tuple[list[BaseTool], list[AgentError]]
```

Discovery algorithm (per vision, Developer README § Plugin Auto-Discovery):

1. Expand `~`; skip nonexistent directories silently (log at `DEBUG`).
2. For each `*.py` file (sorted, for determinism): load via
   `importlib.util.spec_from_file_location(module_name, path)` under a synthetic module
   name `agent_harness_plugin_<stem>`.
3. Collect classes where `inspect.isclass(obj) and issubclass(obj, BaseTool) and obj is not BaseTool`
   and the class is **concrete** (no remaining abstract methods).
4. Instantiation convention:
   - zero-arg constructor → instantiate directly;
   - constructor params named `config` / `llm_client` → injected by keyword;
   - other required params → class may declare `PLUGIN_SETTINGS: dict` giving literal
     kwargs; if still uninstantiable, record `AgentError(PLUGIN_LOAD_FAILED)` and continue.
5. Register discovered instances with the registry; name collisions with built-ins are
   refused (built-ins win) with a `WARNING`.
6. **Isolation:** any exception in one plugin file is caught, converted to
   `AgentError(code="PLUGIN_LOAD_FAILED", recoverable=False)`, logged, and never aborts
   startup. Errors are returned (second tuple element) and surfaced in `--list-tools`
   footer and the startup log.
7. Scanning is skipped entirely when `config.plugins.auto_load` is false.

### 3.1 Shipped examples (owned by Plan 4, in `plugins/`)

| File | Content |
|---|---|
| `plugins/example_hello.py` | `HelloTool` — minimal example, exactly the shape from the Developer README |
| `plugins/example_database.py` | `DatabaseQueryTool` — read-only SQLite with `validate_input` keyword blocking, per Developer README |
| `plugins/README.md` | How to add plugins; settings conventions; security notice |

---

## 4. Startup Warnings & UX Rules

| Condition | Behavior |
|---|---|
| `.env` contains keys that will be transmitted to the LLM provider | One-time startup warning naming the env vars (never the values) — vision § 9.3 |
| `wkhtmltopdf` missing | INFO note that `pdf_export` runs in degraded markdown mode |
| `config.security.allow_shell` true | WARNING at startup that shell execution is enabled |
| Missing API key for selected provider | Fatal at harness init with remediation text (`cp .env.example .env`) |

---

## 5. Programmatic Usage Guarantees

- `AgentHarness` instances are reusable for multiple `run()` calls; each run gets a fresh
  context and plan; registry and LLM client are reused; `usage` counters accumulate
  across runs (documented).
- Thread-safety: **not guaranteed** in v0.1 (single-session design, vision NG4).
- `register_tool()` after a run affects subsequent runs only.
