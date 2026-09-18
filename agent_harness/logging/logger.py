"""Injected structured logging with JSONL persistence. Spec: SPEC-006 §6."""

from __future__ import annotations

import json
import math
import os
import sys
from collections.abc import Callable
from copy import copy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import TextIO

from agent_harness.config import AgentError, Config, sensitive_data_filter

EVENTS = frozenset(
    {
        "harness_start",
        "harness_complete",
        "plan_generated",
        "plan_validation_failed",
        "step_started",
        "step_completed",
        "step_failed",
        "step_skipped",
        "recovery_attempted",
        "recovery_succeeded",
        "recovery_exhausted",
        "tool_executed",
        "sandbox_violation",
        "llm_call",
        "plugin_loaded",
        "plugin_failed",
        "config_loaded",
        "output_written",
    }
)
LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}


class StructuredLogger:
    """Run-local logger; child instances share a sink lock. Spec: SPEC-006 §6.2."""

    def __init__(
        self,
        config: Config | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        console_stream: TextIO | None = None,
    ) -> None:
        """Configure lazy sinks and injectable clock. Spec: SPEC-006 §6.2."""
        self._config = config or Config()
        self._file = (
            Path(config.logging.file).expanduser() if config is not None else None
        )
        self._console = config.logging.console if config is not None else False
        self._stream = console_stream if console_stream is not None else sys.stderr
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._component: str | None = None
        self._bound: dict[str, object] = {}
        self._lock = RLock()
        self._secrets = tuple(
            filter(
                None,
                (
                    os.environ.get(self._config.llm.api_key_env, ""),
                    os.environ.get(self._config.search.api_key_env, ""),
                    os.environ.get("ANTHROPIC_API_KEY", ""),
                ),
            )
        )

    @staticmethod
    def default() -> StructuredLogger:
        """Return a fresh no-I/O fallback, never a singleton. Spec: SPEC-006 §6.2."""
        return StructuredLogger()

    def child(self, component: str, **bound_fields: object) -> StructuredLogger:
        """Bind component and contextual fields without mutating parent. Spec: SPEC-006 §6.2."""
        child = copy(self)
        child._component = component
        child._bound = {**self._bound, **bound_fields}
        return child

    def log(self, level: str, component: str, event: str, **fields: object) -> None:
        """Emit one catalog event as JSONL. Spec: SPEC-006 §6.1–6.2."""
        if level not in LEVELS or event not in EVENTS:
            raise ValueError("Unknown logging level or event")
        if LEVELS[level] < LEVELS[self._config.logging.level]:
            return
        record: dict[str, object] = {
            "plan_id": None,
            "step_id": None,
            "step_description": "",
            "tool_name": "",
            "duration_ms": 0,
            "status": "",
            "retry_count": 0,
            "context_size_bytes": 0,
            "llm_tokens_used": 0,
            "metadata": {},
            **self._bound,
            **fields,
        }
        record.update(
            timestamp=self._clock()
            .astimezone(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            level=level,
            component=component,
            event=event,
        )
        safe = self._safe(record)
        line = json.dumps(
            safe, ensure_ascii=False, default=lambda obj: f"<{type(obj).__name__}>"
        )
        try:
            with self._lock:
                if self._file is not None:
                    self._file.parent.mkdir(parents=True, exist_ok=True)
                    with self._file.open("a", encoding="utf-8") as sink:
                        sink.write(line + "\n")
                if self._console:
                    if self._config.logging.format == "json":
                        self._stream.write(line + "\n")
                    else:
                        self._stream.write(
                            f"{level} {self._safe(component)}: {event}\n"
                        )
                    self._stream.flush()
        except OSError as exc:
            raise AgentError(
                "SYSTEM_ERROR", "Unable to write execution log", "harness"
            ) from exc

    def _emit(
        self, level: str, component: str, event: str | None, fields: dict[str, object]
    ) -> None:
        if event is None:
            if self._component is None:
                raise ValueError("A component or bound child is required")
            component, event = self._component, component
        self.log(level, component, event, **fields)

    def debug(self, component: str, event: str | None = None, **fields: object) -> None:
        """Emit a debug event; children may omit component. Spec: SPEC-006 §6.2."""
        self._emit("DEBUG", component, event, fields)

    def info(self, component: str, event: str | None = None, **fields: object) -> None:
        """Emit an informational event. Spec: SPEC-006 §6.2."""
        self._emit("INFO", component, event, fields)

    def warning(
        self, component: str, event: str | None = None, **fields: object
    ) -> None:
        """Emit a warning event. Spec: SPEC-006 §6.2."""
        self._emit("WARNING", component, event, fields)

    def error(self, component: str, event: str | None = None, **fields: object) -> None:
        """Emit an error event. Spec: SPEC-006 §6.2."""
        self._emit("ERROR", component, event, fields)

    def _safe(self, value: object, depth: int = 0) -> object:
        if depth > 20:
            return "[TRUNCATED: nesting limit]"
        if isinstance(value, str):
            text, _ = sensitive_data_filter(
                value, self._config.security.sensitive_patterns, secrets=self._secrets
            )
            return text[:500] + "[TRUNCATED]" if len(text) > 500 else text
        if isinstance(value, dict):
            safe: dict[str, object] = {}
            blocked = {
                "api_key",
                "authorization",
                "password",
                "secret",
                "access_token",
                "credential",
                "messages",
                "request",
                "request_body",
                "response_body",
                "body",
                "headers",
            }
            for key, item in value.items():
                name = str(key) if isinstance(key, (str, int)) else "<key>"
                normalized = name.lower().replace("-", "_")
                confidential = normalized in blocked or normalized.endswith(
                    ("_api_key", "_token", "_secret", "_password", "_authorization")
                )
                safe[str(self._safe(name, depth + 1))] = (
                    "[REDACTED]" if confidential else self._safe(item, depth + 1)
                )
            return safe
        if isinstance(value, (list, tuple)):
            return [self._safe(item, depth + 1) for item in value]
        if isinstance(value, float) and not math.isfinite(value):
            return "[NONFINITE]"
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return f"<{type(value).__name__}>"
