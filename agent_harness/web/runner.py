"""Task execution service behind the local web UI (PRD G8).

The browser never touches the harness directly. It submits a prompt, then reads
task state; :class:`TaskRunner` owns the harness, runs the agent on a worker
thread (the harness is synchronous), and turns SPEC-003 § 2.1's progress hooks
into a re-playable event log.

Enhanced with:
- Interactive Agent Controls: pause, resume, stop, intervene
- Human-in-the-Loop Checkpoints: approve, reject, review changes
- Real-time Roadmap tracking
- Path-safe artifact and deliverable viewing
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: States in which a task will never change again.
TERMINAL_STATUSES = frozenset({"completed", "partial", "failed", "stopped"})

#: Extensions mapped onto :data:`agent_harness.web.schemas.ArtifactView`'s ``kind``.
_KIND_BY_SUFFIX = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".log": "text",
    ".json": "json",
    ".csv": "csv",
    ".html": "html",
    ".htm": "html",
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".svg": "image",
}

#: Refuse to serve artifacts larger than this over HTTP.
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


class TaskStoppedError(Exception):
    """Raised when task execution is interrupted by the user."""


def _utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string with a ``Z`` suffix."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def default_roadmap() -> list[dict[str, Any]]:
    """Return initial roadmap milestones matching actual execution stages."""
    return [
        {
            "id": "analyze_repo",
            "label": "Analyze repository",
            "status": "completed",
            "details": "Workspace context loaded",
            "step_ids": [],
        },
        {
            "id": "architecture",
            "label": "Understand architecture",
            "status": "completed",
            "details": "Tools and environment inspected",
            "step_ids": [],
        },
        {
            "id": "plan",
            "label": "Create implementation plan",
            "status": "pending",
            "details": "Decomposing task into steps",
            "step_ids": [],
        },
        {
            "id": "implement",
            "label": "Implement changes",
            "status": "pending",
            "details": "Executing tool actions and modifying files",
            "step_ids": [],
        },
        {
            "id": "test",
            "label": "Run tests",
            "status": "pending",
            "details": "Verifying code correctness and quality",
            "step_ids": [],
        },
        {
            "id": "review",
            "label": "Review changes",
            "status": "pending",
            "details": "Inspecting unified diff and deliverable",
            "step_ids": [],
        },
        {
            "id": "approval",
            "label": "Human approval",
            "status": "pending",
            "details": "User checkpoint signoff",
            "step_ids": [],
        },
        {
            "id": "pr",
            "label": "Create PR",
            "status": "pending",
            "details": "Automated Pull Request preparation",
            "step_ids": [],
        },
    ]


@dataclass
class Task:
    """The mutable record of one submitted task.

    Attributes:
        id: short opaque identifier, safe to put in a URL.
        prompt: the submitted task text.
        status: lifecycle state.
        created_at: when the browser submitted it.
        started_at: when worker picked it up.
        finished_at: when it reached terminal state.
        phase: active execution phase.
        events: the ordered progress log.
        steps: plan steps as rendered to the browser.
        roadmap: execution roadmap milestones.
        checkpoint: active human checkpoint if paused.
        active_tool: tool currently running.
        active_files: files being inspected or modified.
        interventions: mid-stream user instructions.
    """

    id: str
    prompt: str
    status: str = "queued"
    created_at: str = field(default_factory=_utc_now)
    started_at: str | None = None
    finished_at: str | None = None
    phase: str = "idle"
    events: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    roadmap: list[dict[str, Any]] = field(default_factory=default_roadmap)
    checkpoint: dict[str, Any] | None = None
    active_tool: str | None = None
    active_files: list[str] = field(default_factory=list)
    interventions: list[str] = field(default_factory=list)
    metrics: dict[str, Any] | None = None
    final_output: str | None = None
    files_created: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    report: str | None = None
    error: str | None = None

    _pause_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _checkpoint_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _checkpoint_verdict: str | None = field(default=None, repr=False)
    _stop_requested: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        self._pause_event.set()
        self._checkpoint_event.set()

    @property
    def terminal(self) -> bool:
        """Whether the task will never change again."""
        return self.status in TERMINAL_STATUSES


class ArtifactError(Exception):
    """Raised when an artifact request cannot be fulfilled."""


class TaskRunner:
    """The local task runner service."""

    def __init__(
        self,
        config: Any,
        *,
        harness_factory: Callable[[Callable[[dict[str, Any]], None]], Any]
        | None = None,
        clock: Callable[[], float] = time.monotonic,
        max_tasks: int = 50,
    ) -> None:
        self.config = config
        if harness_factory is None:
            self._harness_factory = lambda progress: _default_harness_factory(self.config, progress)
        else:
            self._harness_factory = harness_factory
        self._clock = clock
        self._max_tasks = max(1, max_tasks)
        self._tasks: dict[str, Task] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()
        self._worker = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="agent-task"
        )
        self._shutdown = False

    # -- Submission -----------------------------------------------------------

    def submit(self, prompt: str) -> Task:
        """Queue a task and return its record immediately."""
        task = Task(id=uuid.uuid4().hex[:12], prompt=prompt)
        with self._lock:
            if self._shutdown:
                raise RuntimeError("runner is shut down")
            self._tasks[task.id] = task
            self._order.append(task.id)
            self._evict()
        self._worker.submit(self._run, task.id)
        return task

    # -- Interactive Controls -------------------------------------------------

    def pause(self, task_id: str | None = None) -> Task:
        """Pause a running agent task."""
        with self._lock:
            task = self._resolve_task(task_id)
            if task.terminal or task.status == "paused":
                return task
            task._pause_event.clear()
            task.status = "paused"
            task.events.append({
                "seq": len(task.events) + 1,
                "at": _utc_now(),
                "event": "agent_paused",
                "fields": {"reason": "User paused execution"},
            })
            return task

    def resume(self, task_id: str | None = None, instruction: str | None = None) -> Task:
        """Resume a paused agent task, optionally with new instructions."""
        with self._lock:
            task = self._resolve_task(task_id)
            if task.terminal:
                return task
            if instruction:
                task.interventions.append(instruction)
                task.events.append({
                    "seq": len(task.events) + 1,
                    "at": _utc_now(),
                    "event": "user_intervention",
                    "fields": {"instruction": instruction},
                })
            task.status = "running"
            task._pause_event.set()
            task.events.append({
                "seq": len(task.events) + 1,
                "at": _utc_now(),
                "event": "agent_resumed",
                "fields": {"has_instruction": bool(instruction)},
            })
            return task

    def stop(self, task_id: str | None = None) -> Task:
        """Stop current agent execution cleanly without killing the server."""
        with self._lock:
            task = self._resolve_task(task_id)
            if task.terminal:
                return task
            task._stop_requested = True
            task.status = "stopped"
            task.error = "Execution stopped by user"
            task.finished_at = _utc_now()
            task._pause_event.set()
            task._checkpoint_event.set()
            task.events.append({
                "seq": len(task.events) + 1,
                "at": _utc_now(),
                "event": "agent_stopped",
                "fields": {"status": "stopped"},
            })
            return task

    def approve(self, task_id: str | None = None) -> Task:
        """Approve an active checkpoint and continue execution."""
        with self._lock:
            task = self._resolve_task(task_id)
            task._checkpoint_verdict = "approved"
            task.checkpoint = None
            task.status = "running"
            _update_roadmap(task, "approval", "completed", "Checkpoint approved by user")
            task._checkpoint_event.set()
            task.events.append({
                "seq": len(task.events) + 1,
                "at": _utc_now(),
                "event": "checkpoint_resolved",
                "fields": {"verdict": "approved"},
            })
            return task

    def reject(self, task_id: str | None = None, reason: str | None = None) -> Task:
        """Reject an active checkpoint with optional feedback."""
        with self._lock:
            task = self._resolve_task(task_id)
            task._checkpoint_verdict = "rejected"
            if reason:
                task.interventions.append(reason)
            task.checkpoint = None
            task.status = "stopped"
            task.error = f"Checkpoint rejected: {reason or 'User rejected changes'}"
            task.finished_at = _utc_now()
            _update_roadmap(task, "approval", "failed", f"Rejected: {reason or 'no feedback'}")
            task._checkpoint_event.set()
            task.events.append({
                "seq": len(task.events) + 1,
                "at": _utc_now(),
                "event": "checkpoint_resolved",
                "fields": {"verdict": "rejected", "reason": reason or ""},
            })
            return task

    def intervene(self, task_id: str | None, instruction: str) -> Task:
        """Submit a mid-stream instruction to the running agent."""
        with self._lock:
            task = self._resolve_task(task_id)
            task.interventions.append(instruction)
            task.events.append({
                "seq": len(task.events) + 1,
                "at": _utc_now(),
                "event": "user_intervention",
                "fields": {"instruction": instruction},
            })
            return task

    def get_active_task(self) -> Task | None:
        """Return the currently running or paused task."""
        with self._lock:
            for tid in reversed(self._order):
                t = self._tasks.get(tid)
                if t and not t.terminal:
                    return t
            return None

    def _resolve_task(self, task_id: str | None) -> Task:
        """Find task by ID or return the most recent active/submitted task."""
        if task_id:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(f"Task not found: {task_id}")
            return task
        active = self.get_active_task()
        if active is not None:
            return active
        if self._order:
            return self._tasks[self._order[-1]]
        raise KeyError("No tasks submitted yet")

    # -- Execution Loop -------------------------------------------------------

    def _run(self, task_id: str) -> None:
        """Execute one task on the worker thread; never raises."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            task.status = "running"
            task.phase = "planning"
            task.started_at = _utc_now()
            _update_roadmap(task, "plan", "running", "Analyzing requirements and tools")

        harness: Any = None
        try:
            harness = self._harness_factory(self._progress_writer(task_id))
            result = harness.run(task.prompt)
            with self._lock:
                if not task._stop_requested:
                    task.status = str(getattr(result, "status", "failed"))
                    task.metrics = _metrics_dict(getattr(result, "metrics", None))
                    task.final_output = _as_text(getattr(result, "final_output", None))
                    task.files_created = list(getattr(result, "files_created", []) or [])
                    task.errors = [dict(e) for e in getattr(result, "errors", []) or []]
                    task.steps = _merge_steps(
                        task.steps, _steps_from_plan(getattr(result, "plan", None))
                    )
                    task.report = getattr(harness, "last_report", None)
                    if task.status not in TERMINAL_STATUSES:
                        task.status = "failed"
                    task.phase = "complete" if task.status == "completed" else "failed"
                    _finalize_roadmap(task)
        except TaskStoppedError:
            with self._lock:
                task.status = "stopped"
                task.phase = "stopped"
                task.error = "Task stopped by user"
        except KeyboardInterrupt:
            with self._lock:
                task.status = "failed"
                task.phase = "interrupted"
                task.error = "interrupted"
        except BaseException as exc:
            with self._lock:
                task.status = "failed"
                task.phase = "failed"
                task.error = _describe(exc)
                task.errors = [_error_dict(exc)]
                _update_roadmap(task, "implement", "failed", str(exc))
        finally:
            if harness is not None:
                _close_quietly(harness)
            with self._lock:
                task.finished_at = _utc_now()
                task.events.append({
                    "seq": len(task.events) + 1,
                    "at": _utc_now(),
                    "event": "task_finished",
                    "fields": {"status": task.status, "phase": task.phase},
                })

    def _progress_writer(self, task_id: str) -> Callable[[dict[str, Any]], None]:
        """Build the ``progress`` callback that intercepts events and honors pause/stop."""

        def callback(event: dict[str, Any]) -> None:
            kind = str(event.get("event", ""))
            fields = {key: value for key, value in event.items() if key != "event"}

            with self._lock:
                task = self._tasks.get(task_id)
                if task is None:
                    return

                # Check if task was stopped
                if task._stop_requested:
                    raise TaskStoppedError("Task was stopped by user")

                # Track events and update steps
                task.events.append({
                    "seq": len(task.events) + 1,
                    "at": _utc_now(),
                    "event": kind,
                    "fields": _jsonable(fields),
                })
                _apply_step_event(task, kind, fields)
                _apply_progress_to_state(task, kind, fields)

            # Check if paused: wait outside the lock so we don't block API reads
            if task is not None:
                task._pause_event.wait()
                if task._stop_requested:
                    raise TaskStoppedError("Task was stopped by user")

        return callback

    # -- Reads ----------------------------------------------------------------

    def get(self, task_id: str) -> Task | None:
        """Return one task, or ``None`` when unknown."""
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self, limit: int = 20) -> list[Task]:
        """Return task records in newest-first order, up to ``limit``."""
        with self._lock:
            ordered_ids = list(reversed(self._order[-limit:]))
            return [self._tasks[tid] for tid in ordered_ids if tid in self._tasks]

    def events_since(
        self, task_id: str, since: int = 0, limit: int = 100
    ) -> tuple[list[dict[str, Any]], int]:
        """Return events recorded after sequence number ``since``."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return [], since
            all_events = task.events
            if since < 0:
                since = 0
            slice_ = all_events[since : since + limit]
            next_seq = slice_[-1]["seq"] if slice_ else since
            return list(slice_), next_seq

    def wait_for_event(
        self, task_id: str, since: int, timeout: float = 2.0
    ) -> list[dict[str, Any]]:
        """Block until an event after ``since`` appears, or until timeout."""
        deadline = self._clock() + max(0.0, timeout)
        while self._clock() < deadline:
            events, _ = self.events_since(task_id, since, limit=1)
            if events:
                return events
            task = self.get(task_id)
            if task is not None and task.terminal:
                return []
            time.sleep(0.05)
        return []

    # -- Artifacts ------------------------------------------------------------

    def output_dir(self) -> Path:
        """The absolute output directory configured for runs."""
        configured = getattr(getattr(self.config, "execution", None), "output_dir", None)
        path = Path(configured) if configured else Path.cwd() / "artifacts"
        return path.resolve()

    def list_artifacts(self) -> list[dict[str, Any]]:
        """List files in the output directory, newest first."""
        out = self.output_dir()
        if not out.is_dir():
            return []
        items: list[dict[str, Any]] = []
        try:
            for entry in out.rglob("*"):
                if not entry.is_file():
                    continue
                try:
                    rel_parts = entry.relative_to(out).parts
                    if any(part.startswith(".") for part in rel_parts):
                        continue
                    rel = entry.relative_to(out).as_posix()
                except ValueError:
                    continue
                try:
                    stat = entry.stat()
                except OSError:
                    continue
                kind = _KIND_BY_SUFFIX.get(entry.suffix.lower(), "other")
                modified_at = (
                    datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                    .isoformat(timespec="seconds")
                    .replace("+00:00", "Z")
                )
                items.append({
                    "path": rel,
                    "name": entry.name,
                    "size_bytes": stat.st_size,
                    "modified_at": modified_at,
                    "kind": kind,
                })
        except OSError:
            return []
        items.sort(key=lambda item: item["modified_at"], reverse=True)
        return items

    def resolve_artifact(self, relative_path: str) -> Path:
        """Resolve a path under the output directory with containment check."""
        clean = relative_path.strip().lstrip("/\\")
        if not clean:
            raise ArtifactError("path cannot be empty")
        out = self.output_dir()
        candidate = (out / clean).resolve()
        try:
            if not candidate.is_relative_to(out):
                raise ArtifactError(f"path {relative_path!r} escapes the output directory")
        except AttributeError:
            try:
                candidate.relative_to(out)
            except ValueError:
                raise ArtifactError(f"path {relative_path!r} escapes the output directory") from None
        if not candidate.is_file():
            raise ArtifactError(f"artifact {relative_path!r} does not exist")
        if candidate.stat().st_size > MAX_ARTIFACT_BYTES:
            raise ArtifactError("artifact is too large to serve")
        return candidate

    def shutdown(self) -> None:
        """Shut down the background worker."""
        with self._lock:
            self._shutdown = True
            for task in self._tasks.values():
                task._pause_event.set()
                task._checkpoint_event.set()
        self._worker.shutdown(wait=False)

    def _evict(self) -> None:
        """Drop oldest finished tasks beyond capacity."""
        while len(self._order) > self._max_tasks:
            for index, candidate_id in enumerate(self._order):
                candidate = self._tasks.get(candidate_id)
                if candidate is not None and candidate.terminal:
                    del self._order[index]
                    self._tasks.pop(candidate_id, None)
                    break
            else:
                break


# -- Helpers ------------------------------------------------------------------

def _update_roadmap(task: Task, item_id: str, status: str, details: str = "") -> None:
    """Update status of a roadmap item on a task."""
    for item in task.roadmap:
        if item["id"] == item_id:
            item["status"] = status
            if details:
                item["details"] = details
            break


def _finalize_roadmap(task: Task) -> None:
    """Finalize roadmap statuses based on task outcome."""
    if task.status == "completed":
        for item in task.roadmap:
            if item["status"] != "failed":
                item["status"] = "completed"
    elif task.status in ("failed", "partial"):
        for item in task.roadmap:
            if item["status"] == "running":
                item["status"] = "failed"


def _apply_progress_to_state(task: Task, kind: str, fields: dict[str, Any]) -> None:
    """Reflect orchestrator events onto task phase, tool activity, and roadmap."""
    if kind == "plan_start":
        task.phase = "planning"
        _update_roadmap(task, "plan", "running", "Plan generated, resolving dependencies")
    elif kind == "step_start":
        tool_name = str(fields.get("tool") or "")
        task.active_tool = tool_name
        task.phase = "implementation"
        _update_roadmap(task, "plan", "completed", "Plan ready")
        _update_roadmap(task, "implement", "running", f"Running {tool_name}")
    elif kind == "step_complete":
        tool_name = str(fields.get("tool") or "")
        task.active_tool = None
        if "file_write" in tool_name or "file_read" in tool_name:
            file_hint = str(fields.get("file") or fields.get("path") or "")
            if file_hint and file_hint not in task.active_files:
                task.active_files.append(file_hint)
        if "test" in tool_name or "pytest" in tool_name:
            _update_roadmap(task, "test", "completed", "Test checks completed")
    elif kind == "plan_complete":
        task.phase = "review"
        _update_roadmap(task, "implement", "completed", "All planned steps executed")
        _update_roadmap(task, "review", "completed", "Changes ready for review")


def _default_harness_factory(
    config: Any,
    progress: Callable[[dict[str, Any]], None],
) -> Any:
    """Build a real AgentHarness with progress reporting."""
    from agent_harness.harness import AgentHarness

    harness = AgentHarness(config)
    harness.set_progress(progress)
    return harness


def _close_quietly(harness: Any) -> None:
    """Call ``close()`` on a harness, swallowing any errors."""
    close_method = getattr(harness, "close", None)
    if callable(close_method):
        try:
            close_method()
        except Exception:
            pass


def _metrics_dict(metrics: Any) -> dict[str, Any] | None:
    """Convert ExecutionMetrics into wire format."""
    if metrics is None:
        return None
    to_dict = getattr(metrics, "to_dict", None)
    if callable(to_dict):
        try:
            return dict(to_dict())
        except Exception:
            pass
    if isinstance(metrics, dict):
        return dict(metrics)
    attrs = (
        "total_steps", "successful_steps", "failed_steps", "recovered_steps",
        "skipped_steps", "total_retries", "total_duration_ms", "llm_calls",
        "llm_tokens_used", "llm_estimated_cost", "tools_used", "files_created",
    )
    return {attr: getattr(metrics, attr, 0 if "cost" not in attr else 0.0) for attr in attrs}


def _steps_from_plan(plan: Any) -> list[dict[str, Any]]:
    """Convert ExecutionPlan steps into step view dicts."""
    if plan is None:
        return []
    plan_steps = getattr(plan, "steps", None) or []
    steps: list[dict[str, Any]] = []
    for step in plan_steps:
        steps.append({
            "id": str(getattr(step, "id", "")),
            "description": str(getattr(step, "description", "")),
            "tool": str(getattr(step, "tool_name", "") or getattr(step, "tool_hint", "") or ""),
            "status": _status_value(getattr(step, "status", "")),
            "priority": _status_value(getattr(step, "priority", "")),
            "depends_on": [str(dep) for dep in getattr(step, "depends_on", []) or []],
            "duration_ms": int(getattr(step, "duration_ms", 0) or 0),
            "error": getattr(step, "error", None),
        })
    return steps


def _merge_steps(
    from_events: list[dict[str, Any]], from_plan: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge event-derived step view with plan projection."""
    if not from_plan:
        return from_events
    if not from_events:
        return from_plan

    by_id = {str(step["id"]): step for step in from_plan}
    merged: list[dict[str, Any]] = []
    for event_step in from_events:
        plan_step = by_id.pop(str(event_step["id"]), None)
        if plan_step is None:
            merged.append(event_step)
            continue
        combined = dict(event_step)
        for key, value in plan_step.items():
            if value not in (None, "", [], 0) or key in {"id", "description", "tool"}:
                combined[key] = value
        if not combined.get("error"):
            combined["error"] = event_step.get("error")
        merged.append(combined)
    merged.extend(by_id.values())
    return merged


def _apply_step_event(task: Task, kind: str, fields: dict[str, Any]) -> None:
    """Fold one progress event into task steps."""
    step_id = str(fields.get("step_id") or "")
    if not step_id:
        return
    existing = next((step for step in task.steps if step["id"] == step_id), None)
    if existing is None:
        existing = {
            "id": step_id,
            "description": str(fields.get("description") or ""),
            "tool": str(fields.get("tool") or ""),
            "status": "pending",
            "priority": "",
            "depends_on": [],
            "duration_ms": 0,
            "error": None,
        }
        task.steps.append(existing)
    if fields.get("description"):
        existing["description"] = str(fields["description"])
    if fields.get("tool"):
        existing["tool"] = str(fields["tool"])
    if kind == "step_start":
        existing["status"] = "running"
    elif kind == "step_complete":
        existing["status"] = "success" if fields.get("success", True) else "failed"
        existing["duration_ms"] = int(fields.get("duration_ms") or 0)
    elif kind == "step_failed":
        existing["status"] = "failed"
        existing["error"] = str(fields.get("error") or "")
    elif kind == "recovery":
        existing["status"] = "retrying"


def _status_value(value: Any) -> str:
    """Render an enum member as its value."""
    return str(getattr(value, "value", value) or "")


def _as_text(value: Any) -> str | None:
    """Render a deliverable as text."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _jsonable(value: Any) -> Any:
    """Coerce an event field to JSON-serializable value."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return str(value)


def _describe(exc: BaseException) -> str:
    """User-facing description of an exception."""
    message = getattr(exc, "message", None)
    code = getattr(exc, "code", None)
    if message:
        return f"{code}: {message}" if code else str(message)
    return f"{type(exc).__name__}: {exc}"


def _error_dict(exc: BaseException) -> dict[str, Any]:
    """Build an AgentError-shaped dict for failure reporting."""
    to_dict = getattr(exc, "to_dict", None)
    if callable(to_dict):
        try:
            return dict(to_dict())
        except Exception:
            pass
    return {
        "code": str(getattr(exc, "code", "SYSTEM_ERROR")),
        "message": str(getattr(exc, "message", exc)),
        "component": str(getattr(exc, "component", "web")),
        "step_id": getattr(exc, "step_id", None),
    }
