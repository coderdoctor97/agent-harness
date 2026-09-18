"""File write tool.

Spec: SPEC-002 §3.5
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any

from agent_harness.tools.base import BaseTool, ToolResult


class FileWriteTool(BaseTool):
    """File write tool per SPEC-002 §3.5."""

    def __init__(self, config: Any = None) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "file_write"

    @property
    def description(self) -> str:
        return (
            "Writes content to a file. Input: {path: str (required), content: str (required), "
            "format: str (optional), create_dirs: bool (default True)}. Output: confirmed path. "
            "Writes restricted to output_dir unless allowed_write_paths."
        )

    @property
    def capabilities(self) -> list[str]:
        return ["file", "write", "io"]

    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str]:
        if "path" not in input_data:
            return False, "Missing required 'path'"
        if "content" not in input_data:
            return False, "Missing required 'content'"
        p = input_data["path"]
        c = input_data["content"]
        if not isinstance(p, str) or not p.strip():
            return False, "'path' must be a non-empty string"
        if not isinstance(c, str):
            return False, "'content' must be a string"
        if "format" in input_data and not isinstance(input_data["format"], str):
            return False, "'format' must be a string"
        if "create_dirs" in input_data and not isinstance(
            input_data["create_dirs"], bool
        ):
            return False, "'create_dirs' must be a bool"
        return True, ""

    def execute(
        self, input_data: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        start = time.monotonic()
        is_valid, err = self.validate_input(input_data)
        if not is_valid:
            return ToolResult(
                success=False,
                error=f"TOOL_INPUT_INVALID: {err}",
                metadata={
                    "tool_name": self.name,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                    "retryable": False,
                },
            )

        raw_path: str = str(input_data["path"]).strip()
        content: str = str(input_data["content"])
        create_dirs: bool = bool(input_data.get("create_dirs", True))

        # Path safety check (write mode)
        try:
            import importlib

            paths_mod: Any = importlib.import_module("agent_harness.tools._paths")
            is_path_allowed = paths_mod.is_path_allowed
            allowed, why = is_path_allowed(
                raw_path, self._config, context, mode="write"
            )
            if not allowed:
                return ToolResult(
                    success=False,
                    error=f"SANDBOX_VIOLATION: {why}",
                    metadata={
                        "tool_name": self.name,
                        "duration_ms": int((time.monotonic() - start) * 1000),
                        "retryable": False,
                        "violation": "SANDBOX_VIOLATION",
                    },
                )
        except ImportError:
            pass
        except Exception:  # noqa: BLE001, S110
            pass

        target = Path(raw_path)
        # If path is relative, resolve against cwd or output_dir? Use resolve
        # Ensure parent dirs
        parent = target.parent
        if parent != Path(".") and not parent.exists():
            if not create_dirs:
                return ToolResult(
                    success=False,
                    error=f"Parent directory does not exist: {parent}",
                    metadata={
                        "tool_name": self.name,
                        "duration_ms": int((time.monotonic() - start) * 1000),
                        "retryable": False,
                    },
                )
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except Exception as exc:  # noqa: BLE001
                return ToolResult(
                    success=False,
                    error=f"Failed to create directories: {exc}",
                    metadata={
                        "tool_name": self.name,
                        "duration_ms": int((time.monotonic() - start) * 1000),
                        "retryable": False,
                    },
                )

        # Atomic write: write to temp file then replace
        try:
            # Ensure parent exists for temp file creation
            if parent != Path(".") and not parent.exists():
                # Should have been created above, but double-check
                parent.mkdir(parents=True, exist_ok=True)
            # Create temp file in same directory to ensure atomic replace on same filesystem
            dir_for_temp = str(parent) if parent != Path("") else "."
            # Use mkstemp to create temp file
            fd, tmp_path = tempfile.mkstemp(dir=dir_for_temp)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                # Atomic replace
                os.replace(tmp_path, str(target))
            except Exception:
                # Cleanup temp file on failure
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:  # noqa: BLE001, S110
                    pass
                raise
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                error=f"Write failed: {exc}",
                metadata={
                    "tool_name": self.name,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                    "retryable": False,
                },
            )

        duration_ms = int((time.monotonic() - start) * 1000)
        return ToolResult(
            success=True,
            output=str(target),
            metadata={"tool_name": self.name, "duration_ms": duration_ms},
        )
