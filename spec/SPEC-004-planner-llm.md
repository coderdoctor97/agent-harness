# SPEC-004 — Planner & LLM Client

**Version:** 1.0.0 · **Status:** FROZEN
**Implemented by:** Plan 3 (`agent_harness/planning/`), Plan 1 (`agent_harness/llm/`)
**Consumed by:** Plans 2, 4, 5

Source of truth: vision § 8 (Planner System), § 11 (Configuration), Developer README § Using Local/Self-Hosted Models.

---

## 1. `LLMClient` Interface (Plan 1) — FROZEN

Location: `agent_harness/llm/client.py`. Every LLM consumer (planner, recovery re-plan,
assembler, `llm_extract`, `llm_synthesize`, `code_execute` task-mode) depends **only** on
this interface — never on a provider SDK directly.

```python
class LLMClient(ABC):
    @abstractmethod
    def complete(self, messages: list[dict], *, temperature: float | None = None,
                 max_tokens: int | None = None) -> LLMResponse: ...

    @abstractmethod
    def complete_json(self, messages: list[dict], *, schema_hint: str = "",
                      temperature: float | None = None) -> tuple[Any, LLMResponse]: ...

    @property
    @abstractmethod
    def usage(self) -> LLMUsage: ...
```

```python
@dataclass
class LLMResponse:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str            # "stop" | "length" | "content_filter" | "error"
    latency_ms: int

@dataclass
class LLMUsage:                   # cumulative counters for the process lifetime
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost: float = 0.0
```

### 1.1 Message format

`messages` is the OpenAI-style list `[{"role": "system"|"user"|"assistant", "content": str}]`.
Provider adapters translate to their native format (Anthropic: system extracted to the
`system` parameter).

### 1.2 Behavioral rules

| Rule | Detail |
|---|---|
| C1 — Retries | Transient failures (timeout, 429, 5xx) retried up to `config.llm.max_retries` (default 3) with exponential backoff honoring `Retry-After` when present. |
| C2 — Model fallback | If `config.llm.fallback_model` is set and the primary model errors non-transiently (e.g. unknown model, content filter), retry once on the fallback. |
| C3 — `complete_json` | Appends `schema_hint` to the system message, requests JSON, strips code fences, parses. On parse failure it performs one **repair round**: sends the error back to the model with the invalid output and asks for corrected JSON. Raises `AgentError(code="PLAN_PARSE_FAILED" or "LLM_CALL_FAILED")` if repair fails. |
| C4 — Redaction | Before any network call, `config.security.sensitive_patterns` are applied to message content (replace with `[REDACTED]`). Redaction counts are exposed in `metadata` of the response object (`LLMResponse` may carry `redactions: int`). |
| C5 — Usage accounting | Every call increments `usage`; cost estimated via `config.llm.cost_per_1k_tokens` when provided. |
| C6 — No secrets in logs | API keys are resolved from env (`api_key_env`) at construction and never logged or placed in context. |
| C7 — Offline mode | `MockLLMClient` (scripted responses from a list/queue) MUST be provided in `agent_harness/llm/client.py` for tests and `--dry-run` demos. All other plans use it in their unit tests. |

### 1.3 Providers (Plan 1, `agent_harness/llm/providers.py`)

| Provider | Selection | Notes |
|---|---|---|
| `OpenAIClient` | `llm.provider: openai` | Official SDK; honors `base_url` for proxies/local servers (Ollama, LM Studio) |
| `AnthropicClient` | `llm.provider: anthropic` | Optional dependency (`anthropic` extra); import guarded with a clear error if missing |
| `LocalCompatClient` | `llm.provider: local` | Any OpenAI-compatible endpoint; `api_key` may be any non-empty string |

Factory: `create_llm_client(config) -> LLMClient` — raises `AgentError(code="CONFIG_VALIDATION_FAILED")`
when the API key env var is missing, with a message naming the variable.

---

## 2. `Planner` Interface (Plan 3) — FROZEN

Location: `agent_harness/planning/planner.py`.

```python
class Planner:
    def __init__(self, llm_client: LLMClient, config, *, logger=None) -> None: ...
    def plan(self, prompt: str, available_tools: list[dict],
             *, context: dict | None = None) -> ExecutionPlan: ...
    def replan_step(self, step: Step, error: str, context: dict,
                    available_tools: list[dict] | None = None) -> list[Step]: ...
    def select_tool(self, step: Step, available_tools: list[dict]) -> str | None: ...
```

- `available_tools` is exactly `ToolRegistry.list_tools()` output (SPEC-002 § 2) — the
  planner must not import the registry itself (layering rule SPEC-000 § 2).
- `plan()` raises `AgentError(code="PLAN_PARSE_FAILED")` or `PLAN_VALIDATION_FAILED`; it
  never returns an invalid plan.
- `replan_step()` returns `[]` when the model cannot propose an alternative (recovery then
  escalates to Level 4).
- `select_tool()` returns a tool name or `None`; used by the orchestrator when a
  `tool_hint` is unresolvable.

---

## 3. Prompt Templates (Plan 3, `agent_harness/planning/prompts.py`)

### 3.1 `PLANNING_SYSTEM_PROMPT` — content FROZEN (verbatim from vision § 8.1)

```text
You are a task planning agent. Given a user's request, decompose it into a structured
execution plan with ordered steps. Available tools: {tool_descriptions}

For each step, specify:
- description: What this step accomplishes
- tool_hint: Which tool to use (from available tools)
- input_data: Parameters for the tool
- priority: "critical" | "high" | "medium" | "low"
- depends_on: List of step indices this step depends on (e.g., ["step_0"])
- fallback_tools: Alternative tools if the primary fails

Rules:
1. Break complex tasks into atomic, testable steps
2. Each step should have a single clear objective
3. Declare dependencies explicitly — don't assume sequential execution
4. Always include fallback tools where alternatives exist
5. Mark steps that produce the final deliverable as "critical" priority
6. Prefer specific tool hints over generic ones

Respond with valid JSON matching the ExecutionPlan schema.
```

`{tool_descriptions}` is rendered from `available_tools` as a deterministic list:
`- name: description [capabilities: a, b]`.

### 3.2 `REPLAN_PROMPT` — content FROZEN (verbatim from vision § 8.2)

```text
A step in the execution plan has failed after all retries and fallbacks.

Failed step: {step_description}
Tool used: {tool_name}
Error: {error_message}
Previous attempts: {attempt_history}
Available tools: {tool_descriptions}
Current context: {context_summary}

Generate an alternative step (or sequence of steps) to achieve the same goal using a
different approach. Respond with valid JSON.
```

`{context_summary}` is bounded: step outputs truncated to 500 chars each, total ≤ 4000 chars.

### 3.3 `TOOL_SELECTION_PROMPT` (additive, Plan 3)

Given a step description and the tool list, respond with a single JSON object
`{"tool": "<name>"}` or `{"tool": null}`.

---

## 4. Plan JSON Schema & Validation

### 4.1 Expected LLM output

```json
{
  "steps": [
    {
      "description": "string (required, non-empty)",
      "tool_hint": "string (required, should match a registered tool name)",
      "input_data": { "…": "tool-specific (may be omitted → {})" },
      "priority": "critical | high | medium | low   (optional → high)",
      "depends_on": ["step_0", "…"],
      "fallback_tools": ["…"]
    }
  ]
}
```

### 4.2 Parsing & normalization rules

1. Strip markdown code fences; parse JSON (via `LLMClient.complete_json`, which includes
   the repair round).
2. Assign canonical IDs `step_0 … step_n` in array order **before** resolving
   `depends_on`; integer references (`0`, `"0"`, `"step_0"`) all normalize to `"step_<i>"`.
3. Unknown enum values → default (`priority` → `high`); unknown keys → ignored.
4. `max_retries` per step = `config.execution.max_retries`.

### 4.3 Validation (all failures → `AgentError(code="PLAN_VALIDATION_FAILED")`)

| Check | Failure condition |
|---|---|
| V1 | `steps` missing, not a list, or empty |
| V2 | `len(steps) > config.execution.max_steps` |
| V3 | Any step missing non-empty `description` |
| V4 | `depends_on` references an out-of-range/nonexistent step |
| V5 | Cycle detected (reuse `resolve_execution_order` in validation mode) |
| V6 | Self-dependency (`step_i` depends on `step_i`) |
| V7 | More than one CRITICAL deliverable-producing step is allowed, but **zero** steps
with `priority == "critical"` produces a `WARNING` (not a failure) |

Unknown `tool_hint` values are **not** a validation failure — the orchestrator resolves or
re-selects at runtime (SPEC-003 § 3 step 2). The planner records them in
`plan.context["unresolved_hints"]` for the report.

---

## 5. Determinism & Cost Controls

| Control | Rule |
|---|---|
| Temperature | Planning calls use `config.llm.temperature` (default 0.2). Re-planning uses the same. Tool selection uses 0.0. |
| Token budget | One `plan()` call ≤ 1 LLM round + 1 repair round. One `replan_step()` ≤ 1 round + 1 repair. `select_tool()` ≤ 1 round, no repair. |
| Dry run | `--dry-run` (SPEC-005) still performs the planning LLM call, then renders the plan and exits without executing. |
| No-execution guarantee | `Planner` never executes tools and never mutates the passed `context`. |
