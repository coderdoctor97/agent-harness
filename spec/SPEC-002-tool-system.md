# SPEC-002 — Tool System

**Version:** 1.0.0 · **Status:** FROZEN · **Implemented by:** Plan 2 (`agent_harness/tools/`) · **Consumed by:** Plans 3, 4, 5

Source of truth: vision § 6 (Tool System), § 9 (Security & Sandboxing), Developer README § Built-in Tools Reference.

---

## 1. `BaseTool` Contract — FROZEN

Location: `agent_harness/tools/base.py`.

```python
class BaseTool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    def capabilities(self) -> list[str]:
        return []

    @abstractmethod
    def execute(self, input_data: dict, context: dict) -> ToolResult: ...

    def validate_input(self, input_data: dict) -> tuple[bool, str]:
        return True, ""

    def cleanup(self) -> None:
        pass
```

### 1.1 Behavioral rules

| Rule | Detail |
|---|---|
| R1 — Never raise | `execute()` MUST catch its own exceptions and return `ToolResult(success=False, error=...)`. An escaping exception is a defect. |
| R2 — Validate first | `execute()` MUST call `validate_input()` and return `TOOL_INPUT_INVALID`-class error result on rejection. |
| R3 — Pure w.r.t. context | Tools read from `context` but MUST NOT mutate it. The orchestrator owns all context writes (SPEC-003 § 4). |
| R4 — Metadata | Every result MUST set `metadata["tool_name"]` and `metadata["duration_ms"]`; set `retryable` when the failure is transient. |
| R5 — Output limits | Textual output is truncated to `config.security.max_output_bytes` with a trailing `"...[truncated]"` marker and `metadata["truncated"]=True`. |
| R6 — Naming | `name` is `snake_case`, unique across the registry, ≤ 40 chars. |
| R7 — Description | `description` is written for LLM consumption: states what it does, required input keys, and output shape in ≤ 300 chars. |
| R8 — Cleanup | `cleanup()` is idempotent and safe to call even if `execute()` never ran. |

### 1.2 `ToolResult`

See SPEC-001 § 2.3 (FROZEN). Plan 2 re-exports it from `agent_harness.tools.base` so that
plugin authors have a single import site, matching the vision's custom-tool examples.

---

## 2. `ToolRegistry` Contract — FROZEN

```python
class ToolRegistry:
    def register(self, tool: BaseTool) -> None
    def get(self, name: str) -> BaseTool | None
    def find_by_capability(self, capability: str) -> list[BaseTool]
    def list_tools(self) -> list[dict]      # [{"name", "description", "capabilities"}]
    def deregister(self, name: str) -> None
    def names(self) -> list[str]            # sorted, for deterministic prompts
```

| Rule | Detail |
|---|---|
| G1 | `register()` raises `TypeError` if the argument is not a `BaseTool` instance. |
| G2 | Re-registering an existing name **overwrites** and logs a `WARNING`. |
| G3 | `list_tools()` ordering is deterministic (insertion order) so planning prompts are reproducible. |
| G4 | Registry is not thread-safe by contract; the orchestrator executes steps sequentially in v0.1. |
| G5 | `deregister()` of an unknown name is a no-op. |

`agent_harness/tools/__init__.py` exports:

```python
def default_tools(config, llm_client) -> list[BaseTool]
```

returning instances of all built-in tools that are usable given `config` (e.g. `pdf_export`
is included only if the wkhtmltopdf binary is detected; otherwise it is registered in
"degraded" mode per § 3.8). Plan 4 calls this at composition time.

---

## 3. Built-in Tool Catalog — I/O contracts FROZEN

Every tool below MUST implement `validate_input()` enforcing the required keys.

### 3.1 `web_search`

| | |
|---|---|
| Capabilities | `["search", "web", "research"]` |
| Input | `query: str` (required), `num_results: int` (default `config.search.max_results`), `region: str` (optional) |
| Output | `list[{"title": str, "url": str, "snippet": str}]` |
| Providers | `duckduckgo` (default, keyless) · `serpapi` · `bing` · `google` — selected by `config.search.provider` |
| Fallback | `cached_search`, `web_scrape` |
| Errors | Empty result set is **not** a failure: `success=True, output=[], metadata["no_results"]=True`. Network/rate-limit failures set `retryable=True`. |

### 3.2 `web_scrape`

| | |
|---|---|
| Capabilities | `["web", "scrape", "extract"]` |
| Input | `url: str` (required, must be `http(s)`), `selector: str` (optional CSS), `max_length: int` (default 5000) |
| Output | `str` — extracted text content |
| Rules | Timeout 20 s; sends a descriptive User-Agent; strips `script`/`style`/`nav`; honors `max_length` truncation (R5). |
| Fallback | `web_search` with a refined query |

### 3.3 `code_execute`

| | |
|---|---|
| Capabilities | `["code", "execution", "compute"]` |
| Input | **either** `code: str` **or** `task: str` (+ `language: str`, default `"python"`); exactly one of `code`/`task` is required |
| Output | `str` — captured stdout; stderr and returncode go to `metadata["stderr"]`, `metadata["returncode"]` |
| `task` mode | The tool asks the injected `llm_client` to generate code from `task` plus `metadata`/context summary, then executes it. Generated code is saved to `config.execution.temp_dir` and its path returned in `metadata["generated_code_path"]`. |
| Sandbox | See SPEC-006 § 4 — subprocess isolation, blocked patterns, env scrub, timeout, output cap |
| Fallback | Re-generate code with error context (handled by recovery, SPEC-003 § 5) |

### 3.4 `file_read`

| | |
|---|---|
| Capabilities | `["file", "read", "io"]` |
| Input | `path: str` (required), `format: str` (optional; auto-detected from extension), `encoding: str` (default `utf-8`) |
| Output by format | `csv` → `list[dict]` · `json` → parsed object · `txt`/`md` → `str` · `pdf` → extracted `str` |
| Errors | Missing path → `success=False` with `metadata["suggestions"]` containing up to 3 similar filenames from the parent directory. |
| Safety | Path must resolve inside an allowed root (workspace, `config.execution.output_dir`, or a path present in `context["allowed_read_paths"]`). Traversal (`..`) that escapes is rejected with `SANDBOX_VIOLATION`. |

### 3.5 `file_write`

| | |
|---|---|
| Capabilities | `["file", "write", "io"]` |
| Input | `path: str` (required), `content: str` (required), `format: str` (optional), `create_dirs: bool` (default `True`) |
| Output | `str` — the confirmed written path |
| Rules | Atomic write (temp file + `os.replace`); parent dirs created when `create_dirs`; appends to `context` **via return value only** (R3) — the orchestrator records it in `files_created`. |
| Safety | Writes are restricted to `config.execution.output_dir` unless `path` is explicitly listed in `context["allowed_write_paths"]`. |

### 3.6 `llm_extract`

| | |
|---|---|
| Capabilities | `["llm", "extract", "transform"]` |
| Input | `input_text: str` (required), `instruction: str` (required), `output_format: "json" \| "text" \| "markdown"` (default `text`) |
| Output | `json` → parsed object · `text`/`markdown` → `str` |
| LLM access | Constructor-injected `llm_client` (SPEC-004 § 5); if absent, falls back to `context["llm_client"]`; if neither → `TOOL_EXECUTION_FAILED` with a clear message. |
| Fallback | Retry with a simplified instruction (recovery Level 1) |

### 3.7 `llm_synthesize`

| | |
|---|---|
| Capabilities | `["llm", "synthesize", "generate"]` |
| Input | `instruction: str` (required), `sources: list[str]` (context keys or step IDs, e.g. `"step_1_output"`), `tone: str` (optional), `max_words: int` (optional) |
| Output | `str` — generated content |
| Source resolution | Each entry resolves in order: `context["step_results"][sid]["output"]` → `context["variables"][key]` → literal string. Unresolvable sources are reported in `metadata["unresolved_sources"]` and do not fail the tool. |

### 3.8 `pdf_export`

| | |
|---|---|
| Capabilities | `["export", "pdf", "document"]` |
| Input | `content: str` (required, markdown or HTML), `filename: str` (required, must end `.pdf`), `format: "markdown" \| "html"` (default `markdown`), `page_size: str` (default `A4`) |
| Output | `str` — created PDF path inside `config.execution.output_dir` |
| Degraded mode | If `wkhtmltopdf` is unavailable: write `<filename>.md` instead and return `success=True` with `metadata["degraded"]=True`, `metadata["actual_format"]="markdown"`. This realizes the vision's "fallback to markdown file". |

### 3.9 `csv_process`

| | |
|---|---|
| Capabilities | `["csv", "data", "transform"]` |
| Input | `path: str` (required), `operations: list[dict]` (required, applied in order), `output_path: str` (optional) |
| Operation types | `filter {column, value, op?="eq"}` · `sort {column, order="asc"\|"desc"}` · `head {n}` · `tail {n}` · `select {columns: list}` · `rename {mapping: dict}` · `aggregate {group_by, column, func="sum"\|"mean"\|"count"}` |
| Output | `list[dict]` — processed rows; if `output_path` given, also writes CSV and reports it in `metadata["output_path"]` |
| Errors | Unknown operation type or missing column → `TOOL_INPUT_INVALID` listing the offending operation index. |
| Fallback | `code_execute` with pandas |

### 3.10 `shell_command`

| | |
|---|---|
| Capabilities | `["shell", "system", "execution"]` |
| Input | `command: str` (required), `args: list[str]` (optional) |
| Output | `str` — stdout; stderr/returncode in metadata |
| Whitelist | Exact set from SPEC-006 § 5. Multi-word entries (`git status`) match on the first two tokens. |
| Rules | No shell interpolation — `subprocess.run([...], shell=False)` with `shlex`-safe arg list; `&&`, `;`, `|`, backticks, `$(` in args are rejected with `SANDBOX_VIOLATION`. |
| Default | Disabled unless `config.security.allow_shell: true` (default `false`). When disabled, `execute()` returns a `TOOL_EXECUTION_FAILED` result explaining how to enable it. |

---

## 4. Capability Tag Vocabulary

Free-form but drawn from this controlled list to keep `find_by_capability()` useful:
`search`, `web`, `scrape`, `extract`, `code`, `execution`, `compute`, `file`, `read`,
`write`, `io`, `llm`, `transform`, `synthesize`, `generate`, `export`, `pdf`, `document`,
`csv`, `data`, `shell`, `system`, `notification`, `messaging`, `database`, `sql`,
`data_retrieval`, `testing`, `greeting`.

---

## 5. Custom / Plugin Tools

Plugin tools live outside the package (user `plugins/` dirs) and MUST satisfy § 1 with no
additional required imports beyond `agent_harness.tools.base`. Constructor conventions and
auto-discovery are specified in SPEC-005 § 5. Plan 2's responsibility ends at the contract
plus two documented examples of *shape* (in its handoff note); the shipped example plugins
are owned by Plan 4.
