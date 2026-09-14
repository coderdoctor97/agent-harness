# SPEC-001 — Core Data Model

**Version:** 1.0.0 · **Status:** FROZEN · **Implemented by:** Plan 1 (`agent_harness/config/schema.py`) · **Consumed by:** Plans 2–5

Source of truth: vision § 5 (Data Model), § 13.2 (Error Response Contract), § 14.2 (Tracking).

---

## 1. Enumerations

### 1.1 `StepStatus(Enum)` — FROZEN

| Member | Value | Meaning |
|---|---|---|
| `PENDING` | `"pending"` | Created, not started |
| `RUNNING` | `"running"` | Currently executing |
| `SUCCESS` | `"success"` | Completed successfully |
| `FAILED` | `"failed"` | Failed after all recovery levels |
| `SKIPPED` | `"skipped"` | Deliberately skipped (non-critical failure escalation) |
| `RETRYING` | `"retrying"` | In a retry/fallback attempt |

### 1.2 `TaskPriority(Enum)` — FROZEN

| Member | Value | Failure semantics |
|---|---|---|
| `CRITICAL` | `"critical"` | Failure blocks/aborts entire plan |
| `HIGH` | `"high"` | Failure triggers fallback; if unrecovered → degraded output, plan continues |
| `MEDIUM` | `"medium"` | Failure logged; step skipped; plan continues with note |
| `LOW` | `"low"` | Best-effort; skip silently |

---

## 2. Dataclasses

All dataclasses live in `agent_harness/config/schema.py` and are re-exported from
`agent_harness.config`. Field names, types, and defaults below are **FROZEN**.

### 2.1 `Step`

```python
@dataclass
class Step:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str = ""
    tool_hint: str = ""            # suggested tool name from planner
    tool_name: str = ""            # resolved tool name (may change on fallback)
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: Any = None
    status: StepStatus = StepStatus.PENDING
    error: Optional[str] = None
    retries: int = 0
    max_retries: int = 2
    fallback_tools: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)   # step IDs
    priority: TaskPriority = TaskPriority.HIGH
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
```

**Invariants**
- `id` unique within a plan; canonical planner-assigned IDs are `"step_0"`, `"step_1"`, …
  (index-based). Auto-generated UUID fragments apply only to programmatically built steps.
- `depends_on` entries MUST reference IDs that exist in the same plan (validated pre-execution).
- `retries ≤ max_retries` always.
- `status == SUCCESS` ⇒ `error is None`; `status == FAILED` ⇒ `error is not None`.

**Required methods**
- `to_dict() -> dict` / `Step.from_dict(d) -> Step` — JSON-safe round-trip (enums serialize
  to their `.value`; datetimes to ISO-8601 strings).
- `duration_ms -> Optional[int]` (property; `None` unless both timestamps set).

### 2.2 `ExecutionPlan`

```python
@dataclass
class ExecutionPlan:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    original_prompt: str = ""
    steps: list[Step] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    status: StepStatus = StepStatus.PENDING
    final_output: Any = None
```

**Invariants & methods**
- `len(steps) ≤ config.execution.max_steps` (enforced by planner validation, SPEC-004 § 4).
- Plan `status` is `SUCCESS` only if all CRITICAL/HIGH steps succeeded (skipped MEDIUM/LOW
  allowed → then status is `SUCCESS` with `metadata["degraded"]=True` on the result; if any
  required step FAILED → plan `FAILED`; partial assembly → see SPEC-003 § 6).
- `to_dict()` / `from_dict()`; `step_by_id(sid) -> Optional[Step]`.

### 2.3 `ToolResult`

Defined in `agent_harness/tools/base.py` (Plan 2) but specified here because it is a
cross-plan contract — **FROZEN**:

```python
@dataclass
class ToolResult:
    success: bool
    output: Any = None
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

**Metadata conventions** (keys any consumer may rely on):

| Key | Type | Meaning |
|---|---|---|
| `retryable` | `bool` | Error is transient (rate limit, timeout) — retry likely to help |
| `duration_ms` | `int` | Tool-internal execution time |
| `tool_name` | `str` | Tool that produced the result |
| `llm_tokens_used` | `int` | Tokens consumed, if the tool called an LLM |

### 2.4 `AgentError`

```python
@dataclass
class AgentError:
    code: str                        # see § 3 catalog
    message: str
    component: str                   # "planner" | "orchestrator" | "tools" | "recovery" | "harness" | "config" | "llm" | "plugins"
    step_id: Optional[str] = None
    recoverable: bool = False
    recovery_action: Optional[str] = None
    original_error: Optional[str] = None
```

Methods: `to_dict()`, `__str__` renders `"[code] component(step_id): message"`.

### 2.5 `ExecutionMetrics`

```python
@dataclass
class ExecutionMetrics:
    plan_id: str
    prompt_length: int
    total_steps: int
    successful_steps: int
    failed_steps: int
    recovered_steps: int
    skipped_steps: int
    total_retries: int
    total_duration_ms: int
    llm_calls: int
    llm_tokens_used: int
    llm_estimated_cost: float
    tools_used: list[str]
    files_created: list[str]
    errors: list[dict]
```

Method: `to_dict()`; classmethod `from_plan(plan, timings, llm_usage) -> ExecutionMetrics`
(computation rules in SPEC-003 § 7).

---

## 3. Error Code Catalog — FROZEN

| Code | Raised by | Meaning |
|---|---|---|
| `CONFIG_LOAD_FAILED` | config | Missing/invalid config file or env |
| `CONFIG_VALIDATION_FAILED` | config | Schema violation in config values |
| `PROMPT_INVALID` | harness | Empty/too-long/unsupported prompt |
| `PLAN_PARSE_FAILED` | planner | LLM output not valid plan JSON after repair loop |
| `PLAN_VALIDATION_FAILED` | planner | Circular deps, unknown step refs, too many steps |
| `TOOL_NOT_FOUND` | orchestrator | `tool_hint` unresolvable and LLM selection failed |
| `TOOL_INPUT_INVALID` | tools | `validate_input()` rejected input |
| `TOOL_EXECUTION_FAILED` | tools | Tool returned `success=False` |
| `SANDBOX_VIOLATION` | tools | Blocked pattern / whitelist rejection |
| `SANDBOX_TIMEOUT` | tools | Code execution exceeded timeout |
| `LLM_CALL_FAILED` | llm | Provider error after internal retries |
| `LLM_RATE_LIMITED` | llm | 429-class response |
| `RECOVERY_EXHAUSTED` | recovery | All 4 recovery levels failed for a step |
| `PLAN_ABORTED` | orchestrator | Critical step failure aborted the plan |
| `PLUGIN_LOAD_FAILED` | plugins | A plugin file failed discovery/instantiation (isolated; never fatal) |
| `SYSTEM_ERROR` | any | Disk full, permission denied, OOM class failures |

---

## 4. Serialization Rules

- Single serializer style: dataclass → plain `dict` (JSON-safe) → JSON string.
- Enums serialize to their string `value`; parse back via `Enum(value)`.
- `datetime` ↔ ISO-8601 (`datetime.isoformat()` / `datetime.fromisoformat()`).
- Unknown keys in `from_dict` are ignored (forward compatibility); missing keys use
  dataclass defaults; wrong types raise `AgentError(code="PLAN_PARSE_FAILED", ...)` or
  `ValueError` for non-plan types.
- `ExecutionPlan.to_dict()` MUST round-trip: `ExecutionPlan.from_dict(p.to_dict()) == p`
  (equality on all fields).
