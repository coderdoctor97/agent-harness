# SPEC-003 — Orchestration, Recovery & Assembly

**Version:** 1.0.0 · **Status:** FROZEN · **Implemented by:** Plan 3 (`agent_harness/orchestration/`) · **Consumed by:** Plans 4, 5

Source of truth: vision § 4 (Architecture), § 7 (Orchestration Engine), § 10.2 (Execution Report), § 14 (Success Metrics).

---

## 1. Module Map

| File | Responsibility |
|---|---|
| `orchestration/orchestrator.py` | `Orchestrator` — the POEA step loop |
| `orchestration/dependency.py` | `resolve_execution_order()` — topological sort + cycle detection |
| `orchestration/recovery.py` | `RecoveryManager` — the 4-level recovery cascade |
| `orchestration/assembler.py` | `Assembler` — final deliverable synthesis |

---

## 2. `Orchestrator` Public Interface — FROZEN

```python
class Orchestrator:
    def __init__(self, registry: ToolRegistry, config: Config, *,
                 llm_client: LLMClient | None = None,
                 planner: Planner | None = None,
                 context_store: ContextStore | None = None,
                 logger: StructuredLogger | None = None,
                 hooks: ExecutionHooks | None = None) -> None: ...

    def execute(self, plan: ExecutionPlan) -> ExecutionPlan: ...
```

- Returns the **same plan object**, mutated in place, with every `Step` carrying a terminal
  status (`SUCCESS` / `FAILED` / `SKIPPED`), `output_data`, `error`, `retries`, and timings.
- `planner` is required only when re-planning is enabled; if `None` and recovery reaches
  Level 3, Level 3 is skipped and the cascade proceeds to Level 4.
- `execute()` raises `AgentError(code="PLAN_ABORTED")` **only** when a CRITICAL step fails
  and `config.execution.abort_on_critical_failure` is true. Otherwise the plan is returned
  with `status = FAILED`.
- `KeyboardInterrupt` during a step: mark the step `FAILED` with `error="interrupted"`,
  call `cleanup()` on the active tool, set plan status `FAILED`, and re-raise.

### 2.1 `ExecutionHooks` (observability seam)

```python
@dataclass
class ExecutionHooks:
    on_plan_start:    Callable[[ExecutionPlan], None] | None = None
    on_step_start:    Callable[[Step], None] | None = None
    on_step_complete: Callable[[Step, ToolResult], None] | None = None
    on_step_failed:   Callable[[Step, str], None] | None = None
    on_recovery:      Callable[[Step, int, str], None] | None = None   # (step, level, action)
    on_plan_complete: Callable[[ExecutionPlan], None] | None = None
```

Hooks are **best-effort**: an exception inside a hook is logged at `WARNING` and never
aborts execution. This seam is how Plan 4 wires Rich console progress and how a future web
UI will attach — no orchestrator change required.

---

## 3. Step Loop Algorithm — FROZEN

```text
order = resolve_execution_order(plan.steps)
FOR step IN order:
  1. DEPENDENCIES — every id in step.depends_on must have status SUCCESS
                    (or SKIPPED with priority < CRITICAL); otherwise mark step
                    SKIPPED with error "dependency <id> not satisfied" and continue
  2. RESOLVE TOOL — registry.get(step.tool_hint)
                    → if None: registry.get(step.tool_name)
                    → if still None and llm_client available: LLM tool selection
                      over registry.list_tools(); write result to step.tool_name
                    → if still None: fail step with TOOL_NOT_FOUND, enter recovery
  3. PREPARE INPUT — step.input_data merged with resolved placeholders (§ 4.2)
  4. VALIDATE — tool.validate_input(prepared); on rejection fail with
                TOOL_INPUT_INVALID (no retry — a bad input won't fix itself;
                recovery jumps to Level 2)
  5. EXECUTE — status = RUNNING; started_at = now; result = tool.execute(prepared, context)
  6. OBSERVE:
       result.success → status = SUCCESS; output_data = result.output
       else           → RecoveryManager.attempt_recovery(step, result.error, context)
  7. RECORD — completed_at = now; context["step_results"][step.id] = {...} (§ 4.1);
              emit log event `step_completed`; fire hooks
  8. GUARDS — if total executed steps ≥ config.execution.max_steps → stop loop,
              mark remaining steps SKIPPED with error "max_steps exceeded"
              if elapsed step time > config.execution.step_timeout → treat as failure
```

---

## 4. Context Management

### 4.1 Layout — FROZEN

```python
context = {
    "config": {...},                      # resolved config subset (no secrets)
    "step_results": {
        "<step_id>": {"status": str, "output": Any, "error": str | None,
                      "tool_name": str, "duration_ms": int, "retries": int},
    },
    "variables": {...},                   # user-supplied + planner-extracted
    "errors": [{"step_id", "attempt", "error", "recovered": bool, "level": int}],
    "files_created": [str, ...],
    "llm_client": LLMClient,              # optional; for tools needing LLM access
    "allowed_read_paths": [str, ...],
    "allowed_write_paths": [str, ...],
}
```

Writes are performed **only** by the orchestrator (SPEC-002 R3). After a successful
`file_write`, the orchestrator appends the returned path to `files_created`.

### 4.2 Placeholder resolution in `input_data`

String values in `input_data` may reference prior work. Resolution order, applied
recursively to nested dicts/lists:

| Pattern | Resolves to |
|---|---|
| `{{step:<id>}}` | `context["step_results"][id]["output"]` |
| `{{step:<id>.output}}` | same as above (explicit form) |
| `{{var:<name>}}` | `context["variables"][name]` |
| `{{config:<dotted.path>}}` | resolved config value (secrets excluded) |
| `{{prompt}}` | `plan.original_prompt` |

A whole-value placeholder (`"{{step:step_0}}"`) substitutes the raw object (list/dict
preserved). A placeholder embedded in a larger string is substituted as `str(value)`.
Unresolvable placeholders leave the literal text in place and log a `WARNING`; they do not
fail the step.

---

## 5. Recovery Cascade — FROZEN

```text
Level 1 RETRY      same tool, same prepared input, up to step.max_retries
                   delay per config.execution.retry_backoff:
                     exponential → base * 2^(n-1)
                     linear      → base * n
                     fixed       → base
                   status transitions RUNNING → RETRYING → RUNNING
Level 2 FALLBACK   for name in step.fallback_tools:
                     skip if not in registry; try execute; on success set
                     step.tool_name = name and metadata["recovered_via"]="fallback:<name>"
                   A fallback tool receives the SAME prepared input. If it declares
                   different required keys and validation fails, that fallback is
                   skipped (logged), not counted as an attempt.
Level 3 RE-PLAN    planner.replan_step(step, error, context) → list[Step]
                   each replacement step executed immediately in order;
                   first success recovers the original step (its output_data is
                   set from the successful replacement, retries preserved)
                   skipped entirely when config.execution.enable_replan is false
                   or no planner is available
Level 4 ESCALATE   CRITICAL → if abort_on_critical_failure: raise AgentError(PLAN_ABORTED)
                              else plan.status = FAILED, step FAILED
                   HIGH     → step FAILED, plan continues, result marked degraded
                   MEDIUM   → step SKIPPED, note added to context["errors"]
                   LOW      → step SKIPPED, no note in final output
```

`RecoveryManager` interface:

```python
class RecoveryManager:
    def __init__(self, planner, registry: ToolRegistry, config, *, logger=None,
                 sleep: Callable[[float], None] = time.sleep) -> None: ...
    def attempt_recovery(self, step: Step, error: str, context: dict
                        ) -> tuple[bool, ToolResult | None]: ...
```

- `sleep` is injectable so tests never wait in real time (deterministic per SPEC-000 § 5.5).
- Every attempt appends to `context["errors"]` with the level number.
- A step whose input validation failed skips Level 1 (retrying identical invalid input is
  pointless) and starts at Level 2.
- `metadata["retryable"] == False` on the failing result also skips Level 1.

---

## 6. `Assembler`

```python
class Assembler:
    def __init__(self, config, *, llm_client=None, logger=None) -> None: ...
    def assemble(self, plan: ExecutionPlan, context: dict) -> AssemblyResult: ...

@dataclass
class AssemblyResult:
    status: str                # "completed" | "partial" | "failed"
    final_output: Any          # str for text/markdown; dict for structured
    output_format: str         # "text" | "markdown" | "json" | "file"
    files_created: list[str]
    notes: list[str]           # skipped/degraded steps explained to the user
```

Rules:
1. Collect outputs of all `SUCCESS` steps in execution order.
2. If the plan's terminal CRITICAL step produced a file (`files_created` non-empty),
   `status = "completed"` and `final_output` is a summary referencing the file paths.
3. If any required step was `SKIPPED`/`FAILED` but a deliverable still exists →
   `status = "partial"`, and `notes` states exactly what is missing and why.
4. If no deliverable exists → `status = "failed"`, `final_output` is a human-readable
   failure explanation including the error chain.
5. Synthesis mode: when `llm_client` is available and the requested output is prose, the
   assembler calls it once with a bounded context (step outputs truncated to fit
   `config.llm.max_tokens`). On LLM failure it falls back to **template mode**: a
   deterministic markdown document with one section per step. Template mode must always
   work without an LLM — this guarantees the harness never returns nothing.
6. `notes` are always appended to the output, never silently dropped (realizes vision
   US-3 acceptance criteria).

---

## 7. Metrics Computation (`ExecutionMetrics.from_plan`)

| Field | Rule |
|---|---|
| `total_steps` | `len(plan.steps)` |
| `successful_steps` | count `status == SUCCESS` |
| `failed_steps` | count `status == FAILED` |
| `skipped_steps` | count `status == SKIPPED` |
| `recovered_steps` | count steps with `retries > 0` **or** `metadata["recovered_via"]` set, that ended `SUCCESS` |
| `total_retries` | `sum(step.retries)` |
| `total_duration_ms` | plan wall-clock (orchestrator-measured), not the sum of step durations |
| `llm_calls`, `llm_tokens_used` | accumulated from `LLMClient` usage counters (SPEC-004 § 5.3) |
| `llm_estimated_cost` | `tokens × config.llm.cost_per_1k_tokens / 1000`; `0.0` when unset |
| `tools_used` | unique resolved `tool_name`s in first-use order |
| `files_created` | `context["files_created"]` |
| `errors` | `context["errors"]` |

---

## 8. Dependency Resolution — FROZEN

`resolve_execution_order(steps: list[Step]) -> list[Step]`

- Kahn's algorithm (BFS with a `deque`), matching vision § 7.2.
- Raises `ValueError("Circular dependency detected in execution plan")` when the ordered
  output is shorter than the input.
- `depends_on` entries referencing unknown IDs are ignored with a `WARNING` (a dangling
  dependency must not deadlock the plan).
- Tie-breaking among ready steps is **stable by original list index**, so ordering is
  deterministic and testable.
- v0.1 executes sequentially; the returned order is the single contract a future parallel
  executor will also honor.
