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

#: Lifecycle states of a submitted task. Includes human-in-the-loop and pause states.
TaskStatus = Literal[
    "queued",
    "running",
    "paused",
    "awaiting_input",
    "completed",
    "partial",
    "failed",
    "stopped",
]


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


class CheckpointView(BaseModel):
    """Human-in-the-loop checkpoint payload."""

    id: str
    phase: str
    message: str = "The agent completed this phase."
    files_changed: int = 0
    tests_passed: int = 0
    options: list[str] = Field(default_factory=lambda: ["review", "approve", "reject"])
    created_at: str = ""


class RoadmapItemView(BaseModel):
    """One milestone in the agent's execution roadmap."""

    id: str
    label: str
    status: Literal["pending", "running", "completed", "failed", "skipped"] = "pending"
    details: str = ""
    step_ids: list[str] = Field(default_factory=list)


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
    phase: str = "idle"
    checkpoint: CheckpointView | None = None


class TaskDetail(TaskSummary):
    """Everything the detail pane needs, in one response."""

    steps: list[StepView] = Field(default_factory=list)
    metrics: MetricsView | None = None
    final_output: str | None = None
    files_created: list[str] = Field(default_factory=list)
    errors: list[dict[str, object]] = Field(default_factory=list)
    report: str | None = None
    roadmap: list[RoadmapItemView] = Field(default_factory=list)
    active_tool: str | None = None
    active_files: list[str] = Field(default_factory=list)


class EventView(BaseModel):
    """One progress event, forwarded from the orchestrator hook seam."""

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
    """Server and configuration summary shown in the header."""

    ok: bool
    version: str
    python: str
    provider: str
    model: str
    output_dir: str
    api_key_configured: bool
    plugin_errors: int = 0
    workspace: str = ""
    branch: str | None = None
    connection_state: Literal["local", "github_connected", "github_disconnected"] = "local"


class ErrorView(BaseModel):
    """The error body every non-2xx response uses."""

    code: str
    message: str
    component: str = "web"
    step_id: str | None = None


# -- Workspace & Files Models -------------------------------------------------

class FileNodeView(BaseModel):
    """Node in workspace directory hierarchy."""

    name: str
    path: str
    type: Literal["file", "directory"]
    size: int = 0
    modified: bool = False
    status_code: str = ""
    children: list[FileNodeView] = Field(default_factory=list)


class WorkspaceView(BaseModel):
    """Overview of workspace root."""

    name: str
    root_path: str
    is_git: bool
    branch: str | None = None
    connection_state: str = "local"
    remote_url: str | None = None
    modified_count: int = 0


class FileListResponse(BaseModel):
    """Workspace tree response."""

    root: str
    tree: list[FileNodeView] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)


class FileContentView(BaseModel):
    """Content of a single file in the workspace."""

    path: str
    name: str
    content: str
    size: int
    language: str
    modified: bool = False


class FileSaveRequest(BaseModel):
    """Request to safely save a file in workspace."""

    path: str
    content: str


# -- Diff Models --------------------------------------------------------------

class DiffLine(BaseModel):
    """One line in a diff chunk."""

    type: Literal["add", "delete", "context"]
    content: str
    old_num: int | None = None
    new_num: int | None = None


class DiffChunkView(BaseModel):
    """One diff chunk @@ ... @@."""

    header: str
    lines: list[DiffLine] = Field(default_factory=list)


class FileDiffView(BaseModel):
    """Diff for one changed file."""

    path: str
    status: Literal["modified", "added", "deleted"] = "modified"
    insertions: int = 0
    deletions: int = 0
    chunks: list[DiffChunkView] = Field(default_factory=list)
    raw: str = ""


class DiffSummaryView(BaseModel):
    """Aggregated stats of the workspace diff."""

    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0
    description: str = ""


class DiffResponse(BaseModel):
    """Full diff response for the workspace."""

    summary: DiffSummaryView
    files: list[FileDiffView] = Field(default_factory=list)
    raw: str = ""


# -- Agent Controls & Checkpoints ---------------------------------------------

class InterventionRequest(BaseModel):
    """Instruction submitted mid-stream by user."""

    instruction: str = Field(..., min_length=1, max_length=MAX_PROMPT_CHARS)
    task_id: str | None = None


class CheckpointActionRequest(BaseModel):
    """Approve or reject a checkpoint."""

    task_id: str | None = None
    reason: str | None = None


# -- Git & PR Models ----------------------------------------------------------

class GitHubStatusView(BaseModel):
    """Git & GitHub integration status."""

    is_git: bool
    branch: str | None = None
    is_github: bool = False
    remote_url: str | None = None
    modified_count: int = 0
    latest_commit: str | None = None
    gh_available: bool = False


class BranchSwitchRequest(BaseModel):
    """Request to switch git branch."""

    branch: str
    force: bool = False


class PRTestItem(BaseModel):
    """Verification item in PR preview."""

    name: str
    passed: bool = True


class PRPrepareResponse(BaseModel):
    """Prepared Pull Request details."""

    ready: bool
    is_github: bool
    branch: str
    title: str
    description: str
    files_changed: list[str] = Field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    tests_checklist: list[PRTestItem] = Field(default_factory=list)
    message: str | None = None


class PRCreateRequest(BaseModel):
    """Submit a Pull Request."""

    title: str
    description: str


# -- Terminal Runner Models ---------------------------------------------------

class TerminalRunRequest(BaseModel):
    """Developer command to run in terminal."""

    command: str = Field(..., min_length=1, max_length=1000)


class TerminalRunResponse(BaseModel):
    """Subprocess execution output."""

    command: str
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
