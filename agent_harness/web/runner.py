"""Task execution service behind the local web UI (PRD G8).

The browser never touches the harness directly. It submits a prompt, then reads
task state; :class:`TaskRunner` owns the harness, runs the agent on a worker
thread (the harness is synchronous), and turns SPEC-003 § 2.1's progress hooks
into a re-playable event log.

Design notes
------------
* **One worker.** Runs are serialized. The harness composes one registry, one
  LLM client and one recoverable context store; two concurrent runs would share
  them, and SPEC-005 § 5's reuse guarantee is per-instance, not thread-safe. A
  bounded queue is the honest concurrency model for a single local user, and a
  second submission while busy is *queued*, not rejected.
* **Fresh harness per task.** Each task gets its own harness so a previous run's
  context cannot leak into the next one (SPEC-005 § 5), and ``close()`` runs in
  a ``finally`` so tool cleanup is not skipped when a run raises or is aborted.
* **Events are data, not callbacks.** Hooks fire on the worker thread; the event
  list is the only shared state, guarded by one lock. SSE readers and JSON
  pollers read the same log, so both transports tell the same story.
* **The filesystem is the artifact API.** Anything a run writes lands in
  ``execution.output_dir``; listing and serving are confined to that directory
  by a resolved-path containment check (SKL reliability/threat-model-sast).

Spec: SPEC-003 § 2.1 (hook seam) · SPEC-005 § 1.1 (run lifecycle), § 5 (reuse) ·
SPEC-006 § 3.4 (never log or transmit secrets)
"""

from __future__ import annotations

import importlib
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
TERMINAL_STATUSES = frozenset({"completed", "partial", "failed"})

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

#: Refuse to serve artifacts larger than this over HTTP; a local UI should not be
#: a file-transfer server, and a runaway log should not fill the browser tab.
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


def _utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string with a ``Z`` suffix."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


@dataclass
class Task:
    """The mutable record of one submitted task.

    Attributes:
        id: short opaque identifier, safe to put in a URL.
        prompt: the submitted task text.
        status: one of the lifecycle states in
            :data:`agent_harness.web.schemas.TaskStatus`.
        created_at: when the browser submitted it.
        started_at: when the worker picked it up, or ``None`` while queued.
        finished_at: when it reached a terminal state, or ``None``.
        events: the ordered progress log; index is ``seq - 1``.
        steps: plan steps as rendered to the browser, keyed by step id order.
        metrics: SPEC-001 § 2.5 accounting, once a run has finished.
        final_output: the assembled deliverable.
        files_created: files the run reported creating.
        errors: JSON-safe ``AgentError`` dicts.
        report: the rendered SPEC-006 § 7 execution report.
        error: a human-readable failure reason for a task that never produced a
            result (a bad config, a missing key, a refused prompt).
    """

    id: str
    prompt: str
    status: str = "queued"
    created_at: str = field(default_factory=_utc_now)
    started_at: str | None = None
    finished_at: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] | None = None
    final_output: str | None = None
    files_created: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    report: str | None = None
    error: str | None = None

    @property
    def terminal(self) -> bool:
        """Whether the task will never change again."""
        return self.status in TERMINAL_STATUSES


class ArtifactError(Exception):
    """Raised when a requested artifact is outside the output directory."""


class TaskRunner:
    """Owns the harness lifecycle and the task queue for one web server process.

    The runner is deliberately synchronous underneath: :meth:`submit` returns
    immediately with a queued task, and a single worker thread does the work. That
    keeps the HTTP layer free of any threading assumptions while still never
    blocking a request for the length of an agent run.

    Args:
        config: the loaded :class:`agent_harness.config.schema.Config`.
        harness_factory: how to build a harness from a progress callback. Defaults
            to the real :class:`agent_harness.harness.AgentHarness`; tests inject a
            scripted one (this is the same seam the CLI exposes as
            ``main(harness_factory=…)``).
        clock: monotonic clock, injectable so queue-wait tests do not sleep.
        max_tasks: how many finished tasks to keep in memory.

    Example:
        >>> runner = TaskRunner(Config())                 # doctest: +SKIP
        >>> task = runner.submit("write a haiku")         # doctest: +SKIP
        >>> runner.get(task.id).status                    # doctest: +SKIP
        'queued'
    """

    def __init__(
        self,
        config: Any,
        *,
        harness_factory: Callable[[Callable[[dict[str, Any]], None]], Any]
        | None = None,
        clock: Callable[[], float] = time.monotonic,
        max_tasks: int = 50,
    ) -> None:
        """Wire the config, the harness seam and the single worker."""
        self.config = config
        self._harness_factory = harness_factory or _default_harness_factory
        self._clock = clock
        self._max_tasks = max(1, max_tasks)
        self._tasks: dict[str, Task] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()
        self._worker = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="agent-task"
        )
        self._shutdown = False

    # -- submission -----------------------------------------------------------

    def submit(self, prompt: str) -> Task:
        """Queue a task and return its record immediately.

        Args:
            prompt: the task text. Validation of emptiness and length belongs to
                the harness (SPEC-005 § 1.1 step 1); the API validates the shape
                first so a malformed request never reaches a worker.

        Returns:
            The queued :class:`Task`, with ``status == "queued"``.
        """
        task = Task(id=uuid.uuid4().hex[:12], prompt=prompt)
        with self._lock:
            if self._shutdown:
                raise RuntimeError("runner is shut down")
            self._tasks[task.id] = task
            self._order.append(task.id)
            self._evict()
        self._worker.submit(self._run, task.id)
        return task

    def _run(self, task_id: str) -> None:
        """Execute one task on the worker thread; never raises."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            task.status = "running"
            task.started_at = _utc_now()

        harness: Any = None
        try:
            harness = self._harness_factory(self._progress_writer(task_id))
            result = harness.run(task.prompt)
            with self._lock:
                task.status = str(getattr(result, "status", "failed"))
                task.metrics = _metrics_dict(getattr(result, "metrics", None))
                task.final_output = _as_text(getattr(result, "final_output", None))
                task.files_created = list(getattr(result, "files_created", []) or [])
                task.errors = [dict(e) for e in getattr(result, "errors", []) or []]
                task.steps = _merge_steps(
                    task.steps, _steps_from_plan(getattr(result, "plan", None))
                )
                task.report = getattr(harness, "last_report", None)
                if task.status not in TERMINAL_STATUSES:  # pragma: no cover - defensive
                    task.status = "failed"
        except KeyboardInterrupt:  # pragma: no cover - worker threads cannot get one
            with self._lock:
                task.status = "failed"
                task.error = "interrupted"
        except BaseException as exc:  # noqa: BLE001 - a task must never kill the worker
            with self._lock:
                task.status = "failed"
                task.error = _describe(exc)
                task.errors = [_error_dict(exc)]
        finally:
            if harness is not None:
                _close_quietly(harness)
            with self._lock:
                task.finished_at = _utc_now()
                task.events.append(
                    {
                        "seq": len(task.events) + 1,
                        "at": _utc_now(),
                        "event": "task_finished",
                        "fields": {"status": task.status},
                    }
                )

    def _progress_writer(self, task_id: str) -> Callable[[dict[str, Any]], None]:
        """Build the ``progress`` callback the harness will call per event.

        The callback runs on the worker thread inside the orchestrator's hook
        path, which already isolates exceptions; recording the event must
        therefore be cheap, allocation-light and lock-brief.
        """

        def callback(event: dict[str, Any]) -> None:
            kind = str(event.get("event", ""))
            fields = {key: value for key, value in event.items() if key != "event"}
            with self._lock:
                task = self._tasks.get(task_id)
                if task is None:
                    return
                task.events.append(
                    {
                        "seq": len(task.events) + 1,
                        "at": _utc_now(),
                        "event": kind,
                        "fields": _jsonable(fields),
                    }
                )
                _apply_step_event(task, kind, fields)

        return callback

    # -- reads ----------------------------------------------------------------

    def get(self, task_id: str) -> Task | None:
        """Return one task, or ``None`` when unknown."""
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self, limit: int = 20) -> list[Task]:
        """Return tasks newest-first, capped at ``limit``."""
        with self._lock:
            ids = self._order[-limit:][::-1]
            return [self._tasks[task_id] for task_id in ids if task_id in self._tasks]

    def events_since(
        self, task_id: str, since: int
    ) -> tuple[list[dict[str, Any]], int]:
        """Return events with ``seq > since`` plus the next cursor.

        Args:
            task_id: the task to read.
            since: the last sequence number the caller has seen (``0`` for all).

        Returns:
            A ``(events, next_seq)`` tuple. An unknown task yields ``([], since)``.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return [], since
            fresh = [event for event in task.events if int(event["seq"]) > since]
            return list(fresh), len(task.events)

    def wait_for_event(
        self, task_id: str, since: int, timeout: float, poll: float = 0.05
    ) -> list[dict[str, Any]]:
        """Block until ``task_id`` has events past ``since``, or ``timeout`` elapses.

        This is what lets the SSE endpoint behave like a stream without a message
        bus: the event log is the queue, and this method is the "something
        changed" signal.

        Args:
            task_id: the task to watch.
            since: the caller's cursor.
            timeout: maximum seconds to block.
            poll: how often to re-check.

        Returns:
            The new events, possibly empty on timeout.
        """
        deadline = self._clock() + timeout
        while True:
            events, _ = self.events_since(task_id, since)
            if events or self._clock() >= deadline:
                return events
            time.sleep(poll)

    # -- artifacts ------------------------------------------------------------

    @property
    def output_dir(self) -> Path:
        """The directory the agent writes into (SPEC-006 § 1 ``execution.output_dir``)."""
        return Path(str(self.config.execution.output_dir)).expanduser()

    def list_artifacts(self) -> list[dict[str, Any]]:
        """List files under the output directory, newest first.

        Returns:
            One mapping per file, shaped for
            :class:`agent_harness.web.schemas.ArtifactView`.
        """
        root = self.output_dir
        if not root.is_dir():
            return []
        found: list[dict[str, Any]] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            try:
                stat = path.stat()
            except OSError:  # pragma: no cover - a file removed mid-scan
                continue
            found.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "name": path.name,
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    )
                    .isoformat(timespec="seconds")
                    .replace("+00:00", "Z"),
                    "kind": _KIND_BY_SUFFIX.get(path.suffix.lower(), "other"),
                }
            )
        found.sort(key=lambda item: str(item["modified_at"]), reverse=True)
        return found

    def resolve_artifact(self, relative_path: str) -> Path:
        """Resolve an artifact path inside the output directory, or refuse it.

        Args:
            relative_path: a path as returned by :meth:`list_artifacts`.

        Returns:
            The absolute path, guaranteed to live under the output directory.

        Raises:
            ArtifactError: if the path escapes the output directory, does not
                exist, or is not a regular file. Escaping is checked on the
                *resolved* path, so ``..`` segments and symlinks alike are caught
                (SKL reliability/threat-model-sast).
        """
        root = self.output_dir.resolve()
        candidate = (root / relative_path).resolve()
        if candidate != root and root not in candidate.parents:
            raise ArtifactError("path escapes the output directory")
        if not candidate.is_file():
            raise ArtifactError("no such artifact")
        if candidate.stat().st_size > MAX_ARTIFACT_BYTES:
            raise ArtifactError("artifact is too large to serve")
        return candidate

    # -- lifecycle ------------------------------------------------------------

    def shutdown(self) -> None:
        """Stop accepting work and wait for the running task to finish."""
        with self._lock:
            self._shutdown = True
        self._worker.shutdown(wait=True, cancel_futures=True)

    def _evict(self) -> None:
        """Drop the oldest finished tasks once the history cap is exceeded."""
        while len(self._order) > self._max_tasks:
            oldest = self._order[0]
            task = self._tasks.get(oldest)
            if task is not None and not task.terminal:
                return  # never drop a running task; try again on the next submit
            self._order.pop(0)
            self._tasks.pop(oldest, None)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _default_harness_factory(
    progress: Callable[[dict[str, Any]], None],
) -> Any:
    """Build the real harness with the given progress callback.

    Imported lazily so ``import agent_harness.web`` does not pull the whole agent
    core (or its optional provider SDKs) into a process that only wants the
    schemas.
    """
    harness_module = importlib.import_module("agent_harness.harness")
    config_module = importlib.import_module("agent_harness.config")
    return harness_module.AgentHarness(config_module.Config(), progress=progress)


def _close_quietly(harness: Any) -> None:
    """Close a harness, ignoring a cleanup failure that would mask the result."""
    try:
        harness.close()
    except Exception:  # noqa: BLE001 - cleanup must not change the task outcome
        pass


def _metrics_dict(metrics: Any) -> dict[str, Any] | None:
    """Project SPEC-001 § 2.5 metrics onto JSON-safe keys."""
    if metrics is None:
        return None
    keys = (
        "total_steps",
        "successful_steps",
        "failed_steps",
        "recovered_steps",
        "skipped_steps",
        "total_retries",
        "total_duration_ms",
        "llm_calls",
        "llm_tokens_used",
        "llm_estimated_cost",
    )
    projected: dict[str, Any] = {}
    for key in keys:
        value = getattr(metrics, key, None)
        if value is None:
            to_dict = getattr(metrics, "to_dict", None)
            value = to_dict().get(key, 0) if callable(to_dict) else 0
        projected[key] = value
    projected["tools_used"] = list(getattr(metrics, "tools_used", []) or [])
    projected["files_created"] = list(getattr(metrics, "files_created", []) or [])
    return projected


def _steps_from_plan(plan: Any) -> list[dict[str, Any]]:
    """Project plan steps onto the browser's step view."""
    steps: list[dict[str, Any]] = []
    for step in getattr(plan, "steps", []) or []:
        steps.append(
            {
                "id": str(getattr(step, "id", "")),
                "description": str(getattr(step, "description", "") or ""),
                "tool": str(
                    getattr(step, "tool_name", "")
                    or getattr(step, "tool_hint", "")
                    or ""
                ),
                "status": _status_value(getattr(step, "status", "")),
                "priority": _status_value(getattr(step, "priority", "")),
                "depends_on": [
                    str(dep) for dep in getattr(step, "depends_on", []) or []
                ],
                "duration_ms": int(getattr(step, "duration_ms", 0) or 0),
                "error": getattr(step, "error", None),
            }
        )
    return steps


def _merge_steps(
    from_events: list[dict[str, Any]], from_plan: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge the event-derived step view with the plan projection.

    The event log is what the browser has already rendered, so it defines the
    order and is never discarded; the executed plan is authoritative for the
    fields only it knows (priority, dependencies, final status, error). A plan
    step that the log never saw — a skipped step — is appended, because a user
    looking at "why did only two of three steps run" needs to see the third.

    Args:
        from_events: steps accumulated from progress events, in arrival order.
        from_plan: steps projected from the finished plan.

    Returns:
        One step list carrying both sources' fields.
    """
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
    """Fold one progress event into the step list shown by the browser."""
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
    """Render an enum member as its value, leaving plain values alone."""
    return str(getattr(value, "value", value) or "")


def _as_text(value: Any) -> str | None:
    """Render a harness deliverable as text, or ``None`` when there is none."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _jsonable(value: Any) -> Any:
    """Coerce an event field to something JSON can carry."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return str(value)


def _describe(exc: BaseException) -> str:
    """A one-line, user-facing description of a failure."""
    message = getattr(exc, "message", None)
    code = getattr(exc, "code", None)
    if message:
        return f"{code}: {message}" if code else str(message)
    return f"{type(exc).__name__}: {exc}"


def _error_dict(exc: BaseException) -> dict[str, Any]:
    """Build the ``AgentError``-shaped dict the browser renders for a failure."""
    to_dict = getattr(exc, "to_dict", None)
    if callable(to_dict):
        try:
            return dict(to_dict())
        except Exception:  # pragma: no cover - defensive
            pass
    return {
        "code": str(getattr(exc, "code", "SYSTEM_ERROR")),
        "message": str(getattr(exc, "message", exc)),
        "component": str(getattr(exc, "component", "web")),
        "step_id": getattr(exc, "step_id", None),
    }
