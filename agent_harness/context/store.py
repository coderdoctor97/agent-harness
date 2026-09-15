"""Fresh, run-local shared execution context. Spec: SPEC-003 §4.1."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, cast

from agent_harness.config import AgentError, Config, Step


class ContextStore:
    """Dictionary-compatible state carrier without higher-layer imports. Spec: SPEC-003 §4."""

    def __init__(
        self,
        config: Config | None = None,
        *,
        variables: dict[str, Any] | None = None,
        llm_client: object = None,
        allowed_read_paths: list[str] | None = None,
        allowed_write_paths: list[str] | None = None,
        max_output_bytes: int = 1_000_000,
    ) -> None:
        """Allocate independent state for one execution. Spec: SPEC-003 §4.1."""
        if max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        self._max_output_bytes = max_output_bytes
        self._data: dict[str, Any] = {
            "config": (config or Config()).to_dict(),
            "step_results": {},
            "variables": deepcopy(variables or {}),
            "errors": [],
            "files_created": [],
            "llm_client": llm_client,
            "allowed_read_paths": list(allowed_read_paths or []),
            "allowed_write_paths": list(allowed_write_paths or []),
        }

    @classmethod
    def fresh(cls, config: Config | None = None) -> ContextStore:
        """Construct a fresh run without process-global state. Spec: SPEC-003 §4.1."""
        return cls(config)

    def as_dict(self) -> dict[str, Any]:
        """Return the live plain mapping consumed by tools. Spec: SPEC-003 §4.1."""
        return self._data

    @property
    def step_results(self) -> dict[str, dict[str, Any]]:
        """Per-step execution records. Spec: SPEC-003 §4.1."""
        return cast(dict[str, dict[str, Any]], self._data["step_results"])

    @property
    def variables(self) -> dict[str, Any]:
        """Run-local variables. Spec: SPEC-003 §4.1."""
        return cast(dict[str, Any], self._data["variables"])

    @property
    def files_created(self) -> list[str]:
        """Artifacts in creation order. Spec: SPEC-003 §4.1."""
        return cast(list[str], self._data["files_created"])

    @property
    def errors(self) -> list[dict[str, Any]]:
        """Recovery/error history. Spec: SPEC-003 §4.1."""
        return cast(list[dict[str, Any]], self._data["errors"])

    def record_step_result(self, step: Step) -> None:
        """Record frozen fields with a soft output cap. Spec: SPEC-003 §4.1.

        Oversized outputs become a typed truncation envelope. The cap applies to
        the retained preview, not the envelope or total context size.
        """
        step.validate()
        output = deepcopy(step.to_dict()["output_data"])
        encoded = json.dumps(output, ensure_ascii=False).encode("utf-8")
        if len(encoded) > self._max_output_bytes:
            output = {
                "truncated": True,
                "original_type": type(output).__name__,
                "original_size_bytes": len(encoded),
                "preview": encoded[: self._max_output_bytes].decode(
                    "utf-8", errors="ignore"
                ),
                "marker": "[TRUNCATED]",
            }
        self.step_results[step.id] = {
            "status": step.status.value,
            "output": output,
            "error": step.error,
            "tool_name": step.tool_name,
            "duration_ms": step.duration_ms or 0,
            "retries": step.retries,
        }

    def add_file(self, path: str) -> None:
        """Append a new artifact once, preserving order. Spec: SPEC-003 §4.1."""
        if path not in self.files_created:
            self.files_created.append(path)

    def add_error(
        self,
        error: AgentError | str,
        *,
        step_id: str | None = None,
        attempt: int = 0,
        recovered: bool = False,
        level: int = 0,
    ) -> None:
        """Record the frozen recovery entry shape. Spec: SPEC-003 §4.1."""
        self.errors.append(
            {
                "step_id": step_id
                if step_id is not None
                else (error.step_id if isinstance(error, AgentError) else None),
                "attempt": attempt,
                "error": str(error),
                "recovered": recovered,
                "level": level,
            }
        )

    @property
    def context_size_bytes(self) -> int:
        """Measure UTF-8 JSON bytes, replacing the opaque client. Spec: SPEC-006 §6."""
        snapshot = dict(self._data)
        snapshot["llm_client"] = (
            "<LLMClient>" if snapshot["llm_client"] is not None else None
        )
        return len(json.dumps(snapshot, ensure_ascii=False).encode("utf-8"))
