"""The FastAPI application behind the local web UI (PRD G8).

Full-featured local AI development environment API:
- Workspace inspection and hierarchical file tree
- Path-safe file viewing and saving (path traversal protection)
- Real-time Git diff and status
- Interactive agent controls (pause, resume, stop, intervene)
- Human-in-the-loop checkpoints (approve, reject, continue)
- Controlled terminal execution (pytest, ruff, git)
- PR automation and MCP integration layer
"""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import mimetypes
import platform
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from agent_harness.web.mcp import MCPClientAdapter
from agent_harness.web.runner import ArtifactError, Task, TaskRunner
from agent_harness.web.schemas import (
    ArtifactView,
    BranchSwitchRequest,
    CheckpointActionRequest,
    CheckpointView,
    DiffResponse,
    ErrorView,
    EventPage,
    EventView,
    FileContentView,
    FileListResponse,
    FileSaveRequest,
    GitHubStatusView,
    HealthView,
    InterventionRequest,
    MetricsView,
    PRCreateRequest,
    PRPrepareResponse,
    RoadmapItemView,
    StepView,
    TaskDetail,
    TaskRequest,
    TaskSummary,
    TerminalRunRequest,
    TerminalRunResponse,
    ToolView,
    WorkspaceView,
)
from agent_harness.web.workspace import SecurityError, WorkspaceService

#: Static assets served from the package itself (no bundler, offline-capable).
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_INDEX = _STATIC_DIR / "index.html"

#: How long an SSE read blocks before emitting a keep-alive comment.
_STREAM_POLL_SECONDS = 15.0


def create_app(
    config: Any = None,
    *,
    runner: TaskRunner | None = None,
    workspace: WorkspaceService | None = None,
    mcp: MCPClientAdapter | None = None,
) -> FastAPI:
    """Build the ASGI app."""
    if runner is None:
        if config is None:
            config_module = importlib.import_module("agent_harness.config")
            config = config_module.Config()
        runner = TaskRunner(config)
    resolved_config = config if config is not None else runner.config

    if workspace is None:
        workspace = WorkspaceService()
    if mcp is None:
        mcp = MCPClientAdapter()

    app = FastAPI(
        lifespan=_lifespan(runner),
        title="Agent Harness — AI Development Environment",
        version=_version(),
        summary="Local-first autonomous agent environment with human-in-the-loop control.",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.runner = runner
    app.state.config = resolved_config
    app.state.workspace = workspace
    app.state.mcp = mcp

    # Static assets mount
    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    # -- UI -------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> HTMLResponse:
        """Serve the single-page IDE."""
        if not _INDEX.is_file():
            raise HTTPException(status_code=500, detail="UI assets are missing")
        return HTMLResponse(_INDEX.read_text(encoding="utf-8"))

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> JSONResponse:
        """Answer the browser's automatic favicon probe without a 404."""
        return JSONResponse({"detail": "no favicon"}, status_code=204)

    # -- Health & Status ------------------------------------------------------

    @app.get("/api/health", response_model=HealthView)
    def health() -> HealthView:
        """Report liveness plus non-secret configuration summary."""
        ws_info = workspace.get_workspace_info()
        return HealthView(
            ok=True,
            version=_version(),
            python=platform.python_version(),
            provider=str(_cfg(resolved_config, "llm.provider", "unknown")),
            model=str(_cfg(resolved_config, "llm.model", "unknown")),
            output_dir=str(_cfg(resolved_config, "execution.output_dir", "./output")),
            api_key_configured=_api_key_configured(resolved_config),
            plugin_errors=_plugin_error_count(resolved_config),
            workspace=ws_info["name"],
            branch=ws_info.get("branch"),
            connection_state=ws_info.get("connection_state", "local"),
        )

    @app.get("/api/status")
    def overall_status() -> dict[str, Any]:
        """Comprehensive developer-environment status."""
        active = runner.get_active_task()
        git_info = workspace.get_git_info()
        return {
            "ok": True,
            "agent_state": active.status if active else "idle",
            "active_task_id": active.id if active else None,
            "workspace": workspace.get_workspace_info(),
            "git": git_info,
            "mcp": mcp.status(),
            "version": _version(),
            "provider": str(_cfg(resolved_config, "llm.provider", "unknown")),
            "model": str(_cfg(resolved_config, "llm.model", "unknown")),
            "api_key_configured": _api_key_configured(resolved_config),
        }

    @app.get("/api/tools", response_model=list[ToolView])
    def tools() -> list[ToolView]:
        """List registered tools."""
        descriptors = _list_tools(runner)
        return [ToolView(**descriptor) for descriptor in descriptors]

    # -- Tasks ----------------------------------------------------------------

    @app.post("/api/tasks", response_model=TaskDetail, status_code=201)
    def create_task(payload: TaskRequest) -> TaskDetail:
        """Queue a task and return its initial state."""
        prompt = payload.prompt.strip()
        if not prompt:
            raise _bad_request("PROMPT_INVALID", "prompt must not be blank")
        task = runner.submit(prompt)
        return _detail(task)

    @app.get("/api/tasks", response_model=list[TaskSummary])
    def list_tasks(limit: int = 20) -> list[TaskSummary]:
        """Return recent tasks, newest first."""
        return [
            _summary(task) for task in runner.list_tasks(limit=max(1, min(limit, 200)))
        ]

    @app.get("/api/tasks/{task_id}", response_model=TaskDetail)
    def task_detail(task_id: str) -> TaskDetail:
        """Return one task's full state."""
        task = _require_task(runner, task_id)
        return _detail(task)

    @app.get("/api/tasks/{task_id}/events", response_model=EventPage)
    def task_events(task_id: str, since: int = 0) -> EventPage:
        """Return events caller has not seen yet."""
        task = _require_task(runner, task_id)
        events, next_seq = runner.events_since(task_id, since)
        return EventPage(
            events=[_event_view(event) for event in events],
            next_seq=next_seq,
            terminal=task.terminal,
        )

    @app.get("/api/tasks/{task_id}/stream", include_in_schema=False)
    def task_stream(
        task_id: str, request: Request, since: int = 0
    ) -> StreamingResponse:
        """Stream a task's events as Server-Sent Events."""
        _require_task(runner, task_id)
        return StreamingResponse(
            _event_stream(runner, task_id, since, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/events", response_model=EventPage)
    def global_events(since: int = 0) -> EventPage:
        """Return events from the active or most recent task."""
        active = runner.get_active_task()
        if active is None:
            tasks = runner.list_tasks(limit=1)
            active = tasks[0] if tasks else None
        if active is None:
            return EventPage(events=[], next_seq=0, terminal=True)
        events, next_seq = runner.events_since(active.id, since)
        return EventPage(
            events=[_event_view(event) for event in events],
            next_seq=next_seq,
            terminal=active.terminal,
        )

    # -- Interactive Agent Controls & Checkpoints ------------------------------

    @app.post("/api/agent/pause", response_model=TaskDetail)
    def pause_agent(payload: CheckpointActionRequest | None = None) -> TaskDetail:
        """Pause running agent execution."""
        task_id = payload.task_id if payload else None
        try:
            task = runner.pause(task_id)
            return _detail(task)
        except KeyError as exc:
            raise _not_found("TASK_NOT_FOUND", str(exc)) from exc

    @app.post("/api/agent/resume", response_model=TaskDetail)
    def resume_agent(payload: InterventionRequest | None = None) -> TaskDetail:
        """Resume paused agent execution, optionally with updated instructions."""
        task_id = payload.task_id if payload else None
        instruction = payload.instruction if payload else None
        try:
            task = runner.resume(task_id, instruction=instruction)
            return _detail(task)
        except KeyError as exc:
            raise _not_found("TASK_NOT_FOUND", str(exc)) from exc

    @app.post("/api/agent/stop", response_model=TaskDetail)
    def stop_agent(payload: CheckpointActionRequest | None = None) -> TaskDetail:
        """Stop current agent execution safely without terminating the server."""
        task_id = payload.task_id if payload else None
        try:
            task = runner.stop(task_id)
            return _detail(task)
        except KeyError as exc:
            raise _not_found("TASK_NOT_FOUND", str(exc)) from exc

    @app.post("/api/agent/approve", response_model=TaskDetail)
    def approve_checkpoint(payload: CheckpointActionRequest | None = None) -> TaskDetail:
        """Approve checkpoint and continue execution."""
        task_id = payload.task_id if payload else None
        try:
            task = runner.approve(task_id)
            return _detail(task)
        except KeyError as exc:
            raise _not_found("TASK_NOT_FOUND", str(exc)) from exc

    @app.post("/api/agent/reject", response_model=TaskDetail)
    def reject_checkpoint(payload: CheckpointActionRequest | None = None) -> TaskDetail:
        """Reject checkpoint with optional feedback note."""
        task_id = payload.task_id if payload else None
        reason = payload.reason if payload else None
        try:
            task = runner.reject(task_id, reason=reason)
            return _detail(task)
        except KeyError as exc:
            raise _not_found("TASK_NOT_FOUND", str(exc)) from exc

    @app.post("/api/agent/intervene", response_model=TaskDetail)
    def intervene_agent(payload: InterventionRequest) -> TaskDetail:
        """Submit mid-stream user instructions to the running agent."""
        try:
            task = runner.intervene(payload.task_id, payload.instruction)
            return _detail(task)
        except KeyError as exc:
            raise _not_found("TASK_NOT_FOUND", str(exc)) from exc

    # -- Workspace & Files API ------------------------------------------------

    @app.get("/api/workspace", response_model=WorkspaceView)
    def get_workspace() -> WorkspaceView:
        """Get overview of the local workspace root."""
        return WorkspaceView(**workspace.get_workspace_info())

    @app.get("/api/files", response_model=FileListResponse)
    def list_workspace_files() -> FileListResponse:
        """Return hierarchical file tree of workspace root."""
        return FileListResponse(**workspace.list_files())

    @app.get("/api/files/{relative_path:path}", response_model=FileContentView)
    def read_workspace_file(relative_path: str) -> FileContentView:
        """Read a file's content safely within workspace bounds."""
        try:
            data = workspace.read_file(relative_path)
            return FileContentView(**data)
        except SecurityError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/files/save")
    def save_workspace_file(payload: FileSaveRequest) -> dict[str, Any]:
        """Save text content to a file safely within workspace root."""
        try:
            return workspace.save_file(payload.path, payload.content)
        except SecurityError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not save file: {exc}") from exc

    # -- Diff API -------------------------------------------------------------

    @app.get("/api/diff", response_model=DiffResponse)
    def get_diff() -> DiffResponse:
        """Compute unified diff across all changed files in workspace."""
        data = workspace.get_diff()
        return DiffResponse(**data)

    # -- Git & PR Automation --------------------------------------------------

    @app.get("/api/github/status", response_model=GitHubStatusView)
    def github_status() -> GitHubStatusView:
        """Inspect Git & GitHub connectivity."""
        return GitHubStatusView(**workspace.get_git_info())

    @app.post("/api/git/branch")
    def switch_branch(payload: BranchSwitchRequest) -> dict[str, Any]:
        """Switch Git branch safely."""
        try:
            return workspace.switch_branch(payload.branch, force=payload.force)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/pr/prepare", response_model=PRPrepareResponse)
    def prepare_pull_request() -> PRPrepareResponse:
        """Prepare Pull Request summary based on real workspace changes."""
        return PRPrepareResponse(**workspace.prepare_pr())

    @app.post("/api/pr/create")
    def create_pull_request(payload: PRCreateRequest) -> dict[str, Any]:
        """Submit Pull Request using gh CLI."""
        try:
            return workspace.create_pr(payload.title, payload.description)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # -- Terminal Execution API -----------------------------------------------

    @app.post("/api/terminal/run", response_model=TerminalRunResponse)
    def run_terminal_command(payload: TerminalRunRequest) -> TerminalRunResponse:
        """Execute safe developer tool commands in the workspace root."""
        try:
            res = workspace.run_command(payload.command)
            return TerminalRunResponse(**res)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # -- Artifacts ------------------------------------------------------------

    @app.get("/api/artifacts", response_model=list[ArtifactView])
    def list_artifacts() -> list[ArtifactView]:
        """List files the agent has written to the output directory."""
        return [ArtifactView(**item) for item in runner.list_artifacts()]

    @app.get("/api/artifacts/{relative_path:path}", include_in_schema=False)
    def get_artifact(relative_path: str) -> FileResponse:
        """Serve one artifact from output directory."""
        try:
            path = runner.resolve_artifact(relative_path)
        except ArtifactError as exc:
            raise _bad_request("ARTIFACT_INVALID", str(exc)) from exc
        media_type, _ = mimetypes.guess_type(path.name)
        return FileResponse(path, media_type=media_type or "application/octet-stream")

    # -- Exception Handlers ---------------------------------------------------

    @app.exception_handler(ArtifactError)
    def _artifact_error(_request: Request, exc: ArtifactError) -> JSONResponse:
        """Render refused artifact as shared error body."""
        return JSONResponse(
            status_code=400,
            content=ErrorView(code="ARTIFACT_INVALID", message=str(exc)).model_dump(),
        )

    @app.exception_handler(SecurityError)
    def _security_error(_request: Request, exc: SecurityError) -> JSONResponse:
        """Render security rejection as 403."""
        return JSONResponse(
            status_code=403,
            content=ErrorView(code="ACCESS_DENIED", message=str(exc)).model_dump(),
        )

    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lifespan(runner: TaskRunner) -> Any:
    """Build app lifespan: cleanly shut the worker down."""

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await run_in_threadpool(runner.shutdown)

    return lifespan


def _version() -> str:
    """Package version or fallback."""
    try:
        import agent_harness

        return str(getattr(agent_harness, "__version__", "0.1.0"))
    except Exception:
        return "0.1.0"


def _api_key_configured(config: Any) -> bool:
    """True when the configured LLM API key environment variable is set."""
    env_name = _cfg(config, "llm.api_key_env", "OPENAI_API_KEY")
    if not isinstance(env_name, str) or not env_name.strip():
        return False
    import os

    return bool(os.environ.get(env_name.strip(), "").strip())


def _cfg(config: Any, dotted: str, default: Any = None) -> Any:
    """Read a dotted path from Config or dict."""
    if config is None:
        return default
    current = config
    for part in dotted.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
        if current is None:
            return default
    return current


def _bad_request(code: str, message: str) -> HTTPException:
    """Build a 400 error matching ErrorView."""
    return HTTPException(status_code=400, detail={"code": code, "message": message})


def _not_found(code: str, message: str) -> HTTPException:
    """Build a 404 error matching ErrorView."""
    return HTTPException(status_code=404, detail={"code": code, "message": message})


def _require_task(runner: TaskRunner, task_id: str) -> Task:
    """Return task or raise 404."""
    task = runner.get(task_id)
    if task is None:
        raise _not_found("TASK_NOT_FOUND", f"task {task_id!r} does not exist")
    return task


def _summary(task: Task) -> TaskSummary:
    """Project task to list row."""
    return TaskSummary(
        id=task.id,
        prompt=task.prompt,
        status=task.status,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        error=task.error,
        event_count=len(task.events),
        phase=task.phase,
        checkpoint=CheckpointView(**task.checkpoint) if task.checkpoint else None,
    )


def _detail(task: Task) -> TaskDetail:
    """Project task to detail view."""
    return TaskDetail(
        id=task.id,
        prompt=task.prompt,
        status=task.status,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        error=task.error,
        event_count=len(task.events),
        phase=task.phase,
        checkpoint=CheckpointView(**task.checkpoint) if task.checkpoint else None,
        roadmap=[RoadmapItemView(**item) for item in task.roadmap],
        active_tool=task.active_tool,
        active_files=task.active_files,
        steps=[StepView(**s) for s in task.steps],
        metrics=MetricsView(**task.metrics) if task.metrics else None,
        final_output=task.final_output,
        files_created=task.files_created,
        errors=task.errors,
        report=task.report,
    )


def _event_view(event: dict[str, Any]) -> EventView:
    """Project stored event to EventView."""
    return EventView(
        seq=int(event.get("seq", 0)),
        at=str(event.get("at", "")),
        event=str(event.get("event", "")),
        fields=dict(event.get("fields", {})),
    )


async def _event_stream(
    runner: TaskRunner, task_id: str, since: int, request: Request
) -> AsyncIterator[str]:
    """Yield SSE frames for one task until it finishes or client leaves."""
    cursor = since
    while True:
        if await request.is_disconnected():
            return

        events, _ = runner.events_since(task_id, cursor)
        if not events:
            events = await run_in_threadpool(
                runner.wait_for_event, task_id, cursor, 2.0
            )
            if not events:
                task = runner.get(task_id)
                if task is not None and task.terminal:
                    yield "event: done\ndata: {}\n\n"
                    return
                yield ": keep-alive\n\n"
                continue

        for event in events:
            view = _event_view(event)
            cursor = view.seq
            payload = json.dumps(
                {
                    "seq": view.seq,
                    "at": view.at,
                    "event": view.event,
                    "fields": view.fields,
                }
            )
            yield f"event: {view.event}\ndata: {payload}\n\n"


def _list_tools(runner: TaskRunner) -> list[dict[str, Any]]:
    """Read registry's descriptors through throwaway harness."""
    harness_module = importlib.import_module("agent_harness.harness")
    logging_module = importlib.import_module("agent_harness.logging")
    try:
        harness = harness_module.AgentHarness(
            runner.config, logger=_quiet_logger(logging_module, runner.config)
        )
        try:
            return list(harness.list_tools())
        finally:
            with contextlib.suppress(Exception):
                harness.close()
    except Exception:
        return []


def _quiet_logger(logging_module: Any, config: Any) -> Any:
    """Logger whose console sink goes nowhere."""
    return logging_module.StructuredLogger(config, console_stream=io.StringIO())


def _plugin_error_count(config: Any) -> int:
    """How many plugins failed to load."""
    try:
        loader = importlib.import_module("agent_harness.plugins.loader")
        dirs = _cfg(config, "plugins.dirs", []) or []
        if not _cfg(config, "plugins.auto_load", True):
            return 0
        tools, errors = loader.discover_tools(
            _as_list(dirs), config=config, llm_client=None, logger=None
        )
        del tools
        return len(errors)
    except Exception:
        return 0


def _as_list(value: Any) -> list[str]:
    """Coerce value to list of strings."""
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return []


def app_for_script() -> FastAPI:
    """Factory used by ``uvicorn agent_harness.web.app:app``."""
    return create_app()


if sys.version_info < (3, 9):
    raise RuntimeError("the web UI requires Python 3.9+")
