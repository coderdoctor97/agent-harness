"""The FastAPI application behind the local web UI (PRD G8).

Route map
---------
``GET  /``                    the single-page UI
``GET  /api/health``          server + non-secret config summary
``GET  /api/tools``           the registry's tools (SPEC-005 § 1)
``POST /api/tasks``           submit a task, return the queued record
``GET  /api/tasks``           task history, newest first
``GET  /api/tasks/{id}``      task detail: steps, metrics, output, report
``GET  /api/tasks/{id}/events``  pollable event batch (cursor in ``since``)
``GET  /api/tasks/{id}/stream``  the same events as Server-Sent Events
``GET  /api/artifacts``       files under ``execution.output_dir``
``GET  /api/artifacts/{path}``   one artifact's bytes, containment-checked

Two deliberate choices:

* **Polling is a first-class transport, not a fallback.** The events endpoint
  takes a ``since`` cursor and returns a batch; the SSE endpoint is that same
  read in a loop. A proxy that buffers or drops streams therefore degrades to
  polling instead of breaking the UI, and both transports are tested.
* **The server owns no agent state of its own.** Everything the UI shows comes
  from :class:`agent_harness.web.runner.TaskRunner`, so the same objects are
  reachable from Python for scripting and tests.

Spec: PRD G8 · SPEC-003 § 2.1 (progress hooks) · SPEC-006 § 3.4 (no secret ever
leaves the process) · SPEC-005 § 2.1 (interrupt convention)
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

from agent_harness.web.runner import ArtifactError, Task, TaskRunner
from agent_harness.web.schemas import (
    ArtifactView,
    ErrorView,
    EventPage,
    EventView,
    HealthView,
    MetricsView,
    StepView,
    TaskDetail,
    TaskRequest,
    TaskSummary,
    ToolView,
)

#: The UI is one static file served from the package, so there is no build step,
#: no bundler and no CDN dependency: ``start.bat`` works offline (PRD G6).
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_INDEX = _STATIC_DIR / "index.html"

#: How long an SSE read blocks before emitting a keep-alive comment.
_STREAM_POLL_SECONDS = 15.0


def create_app(config: Any = None, *, runner: TaskRunner | None = None) -> FastAPI:
    """Build the ASGI app.

    Args:
        config: a :class:`agent_harness.config.schema.Config`; loaded from the
            standard sources when omitted.
        runner: an existing :class:`~agent_harness.web.runner.TaskRunner`, for
            tests and for embedding the UI in a larger process.

    Returns:
        A configured :class:`fastapi.FastAPI` instance.
    """
    if runner is None:
        if config is None:
            config_module = importlib.import_module("agent_harness.config")
            config = config_module.Config()
        runner = TaskRunner(config)
    resolved_config = config if config is not None else runner.config

    app = FastAPI(
        lifespan=_lifespan(runner),
        title="Agent Harness — local web UI",
        version=_version(),
        summary="Submit tasks to the local agent and watch them execute.",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.runner = runner
    app.state.config = resolved_config

    # Static assets are served from the package itself (no build step, no CDN).
    if _STATIC_DIR.is_dir():  # pragma: no branch - always true in a real install
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    # -- UI -------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> HTMLResponse:
        """Serve the single-page UI."""
        if not _INDEX.is_file():  # pragma: no cover - packaging accident
            raise HTTPException(status_code=500, detail="UI assets are missing")
        return HTMLResponse(_INDEX.read_text(encoding="utf-8"))

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> JSONResponse:
        """Answer the browser's automatic favicon probe without a 404."""
        return JSONResponse({"detail": "no favicon"}, status_code=204)

    # -- meta -----------------------------------------------------------------

    @app.get("/api/health", response_model=HealthView)
    def health() -> HealthView:
        """Report liveness plus the non-secret parts of the live configuration."""
        return HealthView(
            ok=True,
            version=_version(),
            python=platform.python_version(),
            provider=str(_cfg(resolved_config, "llm.provider", "unknown")),
            model=str(_cfg(resolved_config, "llm.model", "unknown")),
            output_dir=str(_cfg(resolved_config, "execution.output_dir", "./output")),
            api_key_configured=_api_key_configured(resolved_config),
            plugin_errors=_plugin_error_count(resolved_config),
        )

    @app.get("/api/tools", response_model=list[ToolView])
    def tools() -> list[ToolView]:
        """List the registry's tools, in the registry's own order."""
        descriptors = _list_tools(runner)
        return [ToolView(**descriptor) for descriptor in descriptors]

    # -- tasks ----------------------------------------------------------------

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
        """Return the events the caller has not seen yet."""
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
        """Stream a task's events as Server-Sent Events.

        The stream ends when the task reaches a terminal state *and* the client's
        cursor has caught up, so a completed task never leaves a connection
        hanging open. An async generator is used (rather than a sync one off a
        thread) so the disconnect probe can be awaited between frames.
        """
        _require_task(runner, task_id)
        return StreamingResponse(
            _event_stream(runner, task_id, since, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # -- artifacts ------------------------------------------------------------

    @app.get("/api/artifacts", response_model=list[ArtifactView])
    def list_artifacts() -> list[ArtifactView]:
        """List files the agent has written to the output directory."""
        return [ArtifactView(**item) for item in runner.list_artifacts()]

    @app.get("/api/artifacts/{relative_path:path}", include_in_schema=False)
    def get_artifact(relative_path: str) -> FileResponse:
        """Serve one artifact, or refuse a path outside the output directory."""
        try:
            path = runner.resolve_artifact(relative_path)
        except ArtifactError as exc:
            raise _bad_request("ARTIFACT_INVALID", str(exc)) from exc
        media_type, _ = mimetypes.guess_type(path.name)
        return FileResponse(path, media_type=media_type or "application/octet-stream")

    @app.exception_handler(ArtifactError)
    def _artifact_error(_request: Request, exc: ArtifactError) -> JSONResponse:
        """Render a refused artifact as the shared error body."""
        return JSONResponse(
            status_code=400,
            content=ErrorView(code="ARTIFACT_INVALID", message=str(exc)).model_dump(),
        )

    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lifespan(runner: TaskRunner) -> Any:
    """Build the app lifespan: shut the worker down when the server stops.

    A task thread must never outlive the process it belongs to, and shutdown must
    wait for the in-flight run rather than abandon it (SPEC-005 § 1.2 cleanup).
    """

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await run_in_threadpool(runner.shutdown)

    return lifespan


def _version() -> str:
    """The package version, or ``"0"`` when metadata is unavailable."""
    try:
        import agent_harness

        return str(getattr(agent_harness, "__version__", "0"))
    except Exception:  # noqa: BLE001 - never fail a response over a version string
        return "0"


def _cfg(config: Any, dotted: str, default: Any) -> Any:
    """Read a dotted config value with a default, tolerating an absent section."""
    getter = getattr(config, "get", None)
    if callable(getter):
        try:
            value = getter(dotted)
        except Exception:  # noqa: BLE001 - an unknown path is not an error here
            value = None
        if value is not None:
            return value
    section, _, key = dotted.partition(".")
    holder = getattr(config, section, None)
    return getattr(holder, key, default) if holder is not None else default


def _api_key_configured(config: Any) -> bool:
    """Whether the configured provider's key is present, by *name* only."""
    import os

    env_name = str(_cfg(config, "llm.api_key_env", "") or "")
    if env_name:
        return bool(os.environ.get(env_name))
    provider = str(_cfg(config, "llm.provider", ""))
    return bool(os.environ.get(f"{provider.upper()}_API_KEY"))


def _require_task(runner: TaskRunner, task_id: str) -> Task:
    """Fetch a task or raise the API's 404."""
    task = runner.get(task_id)
    if task is None:
        raise _not_found(task_id)
    return task


def _not_found(task_id: str) -> HTTPException:
    """Build the shared 404."""
    return HTTPException(
        status_code=404,
        detail=ErrorView(
            code="TASK_NOT_FOUND", message=f"no task with id {task_id!r}"
        ).model_dump(),
    )


def _bad_request(code: str, message: str) -> HTTPException:
    """Build the shared 400."""
    return HTTPException(
        status_code=400, detail=ErrorView(code=code, message=message).model_dump()
    )


def _summary(task: Task) -> TaskSummary:
    """Project a task onto its list-row view."""
    return TaskSummary(
        id=task.id,
        prompt=task.prompt,
        status=task.status,  # type: ignore[arg-type]
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        error=task.error,
        event_count=len(task.events),
    )


def _detail(task: Task) -> TaskDetail:
    """Project a task onto the detail view."""
    return TaskDetail(
        **_summary(task).model_dump(),
        steps=[StepView(**step) for step in task.steps],
        metrics=MetricsView(**task.metrics) if task.metrics else None,
        final_output=task.final_output,
        files_created=task.files_created,
        errors=task.errors,
        report=task.report,
    )


def _event_view(event: dict[str, Any]) -> EventView:
    """Project a stored event onto the wire shape."""
    return EventView(
        seq=int(event.get("seq", 0)),
        at=str(event.get("at", "")),
        event=str(event.get("event", "")),
        fields=dict(event.get("fields", {})),
    )


async def _event_stream(
    runner: TaskRunner, task_id: str, since: int, request: Request
) -> AsyncIterator[str]:
    """Yield SSE frames for one task until it finishes or the client leaves.

    The event log is the queue: each pass reads with a cursor, and when there is
    nothing new the loop blocks briefly through :meth:`TaskRunner.wait_for_event`
    (which releases the event loop for the duration) before emitting a
    keep-alive comment. That keeps one worker thread per open tab without
    polling the log in a hot loop.

    Args:
        runner: the task service.
        task_id: the task being watched.
        since: the client's starting cursor.
        request: the inbound request, used for the disconnect probe.

    Yields:
        SSE frames: ``event: <kind>``, a JSON ``data:`` line, then a blank line.
    """
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
    """Read the registry's descriptors through a throwaway harness.

    The registry is built lazily by the harness (SPEC-005 § 1.1 step 4) and
    includes plugin tools, so asking the harness is the only way to answer with
    the truth; a build failure returns an empty list rather than a 500, because
    the tools panel is informational.
    """
    harness_module = importlib.import_module("agent_harness.harness")
    logging_module = importlib.import_module("agent_harness.logging")
    try:
        # A throwaway harness that must not spam the server console with the
        # startup warnings a *real* run should show: the tools panel is a read,
        # not a run (SPEC-005 § 4 warnings belong to the UI's own run path).
        harness = harness_module.AgentHarness(
            runner.config, logger=_quiet_logger(logging_module, runner.config)
        )
        try:
            return list(harness.list_tools())
        finally:
            with contextlib.suppress(Exception):
                harness.close()
    except Exception:  # noqa: BLE001 - informational endpoint, never fatal
        return []


def _quiet_logger(logging_module: Any, config: Any) -> Any:
    """A logger whose console sink goes nowhere, used where warnings are noise.

    ``StructuredLogger`` writes to ``console_stream`` when the config enables the
    console; pointing that stream at an in-memory buffer keeps the HTTP read path
    silent without touching the user's log level or the on-disk sink.
    """
    return logging_module.StructuredLogger(config, console_stream=io.StringIO())


def _plugin_error_count(config: Any) -> int:
    """How many plugins failed to load, without building a harness.

    Reads the plugin directories directly so the header stays honest even when
    the registry cannot be built (for example with no credentials configured).
    """
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
    except Exception:  # noqa: BLE001 - informational only
        return 0


def _as_list(value: Any) -> list[str]:
    """Coerce a config value that should be a list of strings."""
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return []


def app_for_script() -> FastAPI:
    """Factory used by ``uvicorn agent_harness.web.app:app``-style invocations."""
    return create_app()


if sys.version_info < (3, 9):  # pragma: no cover - declared in pyproject
    raise RuntimeError("the web UI requires Python 3.9+")
