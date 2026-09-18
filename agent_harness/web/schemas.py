"""API contract for the local web UI (PRD G8).

Every request and response body the HTTP surface accepts or returns is declared
here once, as a pydantic model. FastAPI derives the OpenAPI 3.1 document from
these models and validates inbound bodies against them, so the browser can never
send a shape the server did not announce, and a response cannot drift from the
contract without failing the schema tests (SKL frontend/openapi-contract).

Nothing in this module imports the rest of ``agent_harness``: the web layer is
optional (``pip install agent-harness[web]``) and the agent core must stay usable
without it.

Spec: documentations/Agent_Harness_PRD_Developer_README.md G8 (web UI) ·
SPEC-001 § 2.5 (``ExecutionMetrics``) · SPEC-005 § 1 (harness API)
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

#: The largest task prompt accepted over HTTP, mirroring SPEC-005 § 1.1 step 1
#: (``MAX_PROMPT_CHARS``). Declared here rather than imported so this module stays
#: free of agent-core imports; a test pins the two values together.
MAX_PROMPT_CHARS = 20_000

#: Lifecycle states of a submitted task. ``queued`` and ``running`` are the only
#: non-terminal ones; the browser keeps streaming until it sees a terminal state.
TaskStatus = Literal["queued", "running", "completed", "partial", "failed"]


class TaskRequest(BaseModel):
    """A task submission from the browser."""

    prompt: str = Field(
        ...,
        min_length=1,
        max_length=MAX_PROMPT_CHARS,
        description="The natural-language task for the agent to execute.",
        examples=["Research the top 3 Python web frameworks and write a comparison."],
    )


class StepView(BaseModel):
    """One step of the executed plan (SPEC-001 § 2.1)."""

    id: str
    description: str = ""
    tool: str = ""
    status: str = ""
    priority: str = ""
    depends_on: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    error: str | None = None


class MetricsView(BaseModel):
    """Post-run accounting (SPEC-001 § 2.5)."""

    total_steps: int = 0
    successful_steps: int = 0
    failed_steps: int = 0
    recovered_steps: int = 0
    skipped_steps: int = 0
    total_retries: int = 0
    total_duration_ms: int = 0
    llm_calls: int = 0
    llm_tokens_used: int = 0
    llm_estimated_cost: float = 0.0
    tools_used: list[str] = Field(default_factory=list)
    files_created: list[str] = Field(default_factory=list)


class TaskSummary(BaseModel):
    """The list-row view of a task."""

    id: str
    prompt: str
    status: TaskStatus
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    event_count: int = 0


class TaskDetail(TaskSummary):
    """Everything the detail pane needs, in one response."""

    steps: list[StepView] = Field(default_factory=list)
    metrics: MetricsView | None = None
    final_output: str | None = None
    files_created: list[str] = Field(default_factory=list)
    errors: list[dict[str, object]] = Field(default_factory=list)
    report: str | None = None


class EventView(BaseModel):
    """One progress event, forwarded from the orchestrator hook seam.

    ``event`` is one of SPEC-003 § 2.1's six hook kinds; ``seq`` is a
    per-task monotonic counter the browser uses to resume a stream after a
    reconnect without replaying or skipping events.
    """

    seq: int
    at: str
    event: str
    fields: dict[str, object] = Field(default_factory=dict)


class EventPage(BaseModel):
    """A batch of events plus the cursor to ask for the next batch."""

    events: list[EventView] = Field(default_factory=list)
    next_seq: int = 0
    terminal: bool = False


class ToolView(BaseModel):
    """One registered tool (SPEC-005 § 1 ``list_tools``)."""

    name: str
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)


class ArtifactView(BaseModel):
    """One file under ``execution.output_dir``."""

    path: str
    name: str
    size_bytes: int
    modified_at: str
    kind: Literal["markdown", "text", "json", "csv", "html", "pdf", "image", "other"]


class HealthView(BaseModel):
    """Server and configuration summary shown in the header.

    Only non-secret, derived fields appear here: the provider *name* and whether
    a key is configured — never the key itself, and never ``to_dict()`` raw
    (SPEC-006 § 3.4).
    """

    ok: bool
    version: str
    python: str
    provider: str
    model: str
    output_dir: str
    api_key_configured: bool
    plugin_errors: int = 0


class ErrorView(BaseModel):
    """The error body every non-2xx response uses."""

    code: str
    message: str
    component: str = "web"
    step_id: str | None = None
