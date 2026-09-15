"""File read tool.

Spec: SPEC-002 §3.4
"""

from __future__ import annotations

import csv
import difflib
import json
import time
from pathlib import Path
from typing import Any

from agent_harness.tools.base import BaseTool, ToolResult


def _detect_format(path: str, fmt: str | None) -> str:
    if fmt:
        return fmt.lower().lstrip(".")
    suffix = Path(path).suffix.lower().lstrip(".")
    if not suffix:
        return "txt"
    # Normalize md/txt etc
    if suffix in ("csv", "json", "txt", "md", "pdf"):
        return suffix
    return suffix


def _suggest_similar(missing: Path) -> list[str]:
    try:
        parent = missing.parent
        if not parent.exists() or not parent.is_dir():
            return []
        candidates = [p.name for p in parent.iterdir()]
        # Use difflib to find close matches
        matches = difflib.get_close_matches(missing.name, candidates, n=3, cutoff=0.6)
        return matches
    except Exception:  # noqa: BLE001
        return []


def _read_csv(path: Path, encoding: str) -> list[dict[str, Any]]:
    with path.open("r", encoding=encoding, newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def _read_json(path: Path, encoding: str) -> Any:
    with path.open("r", encoding=encoding) as f:
        return json.load(f)


def _read_text(path: Path, encoding: str) -> str:
    with path.open("r", encoding=encoding) as f:
        return f.read()


def _read_pdf(path: Path) -> str:
    # Try pypdf, fallback to pdfminer, else error
    import importlib

    try:
        mod: Any = importlib.import_module("pypdf")
        PdfReader = mod.PdfReader
        reader = PdfReader(str(path))
        texts: list[str] = []
        for page in reader.pages:
            t = page.extract_text() or ""
            texts.append(t)
        return "\n".join(texts)
    except ImportError:
        try:
            mod2: Any = importlib.import_module("pdfminer.high_level")
            extract_text = mod2.extract_text
            return str(extract_text(str(path)))
        except ImportError:
            raise RuntimeError("PDF reading requires pypdf or pdfminer.six")
    except Exception as exc:
        raise RuntimeError(f"PDF extraction failed: {exc}") from exc


class FileReadTool(BaseTool):
    """File read tool per SPEC-002 §3.4."""

    def __init__(self, config: Any = None) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "file_read"

    @property
    def description(self) -> str:
        return (
            "Reads local files. Input: {path: str (required), format: str (optional, auto-detected), "
            "encoding: str (default utf-8)}. Output by format: csv→list[dict], json→object, txt/md→str, pdf→str. "
            "Missing path suggests similar filenames."
        )

    @property
    def capabilities(self) -> list[str]:
        return ["file", "read", "io"]

    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str]:
        if "path" not in input_data:
            return False, "Missing required 'path'"
        p = input_data["path"]
        if not isinstance(p, str) or not p.strip():
            return False, "'path' must be a non-empty string"
        if "format" in input_data and not isinstance(input_data["format"], str):
            return False, "'format' must be a string"
        if "encoding" in input_data and not isinstance(input_data["encoding"], str):
            return False, "'encoding' must be a string"
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
        fmt: str | None = input_data.get("format")
        encoding: str = str(input_data.get("encoding", "utf-8"))
        fmt_detected = _detect_format(raw_path, fmt)

        # Basic traversal check (full guard in 4.2)
        if ".." in Path(raw_path).parts:
            return ToolResult(
                success=False,
                error="SANDBOX_VIOLATION: path traversal not allowed",
                metadata={
                    "tool_name": self.name,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                    "retryable": False,
                    "violation": "SANDBOX_VIOLATION",
                },
            )

        # Resolve path: try absolute or relative to cwd, plus output_dir from config if present
        path = Path(raw_path)
        # If not absolute, try to resolve relative; also consider allowed roots later (4.2)
        # For now, just use path as given
        if not path.exists():
            suggestions: list[str] = _suggest_similar(path)
            meta: dict[str, Any] = {
                "tool_name": self.name,
                "duration_ms": int((time.monotonic() - start) * 1000),
                "retryable": False,
            }
            if suggestions:
                meta["suggestions"] = suggestions
            return ToolResult(
                success=False,
                error=f"File not found: {raw_path}",
                metadata=meta,
            )

        # Path safety hook for 4.2 — duck-typed allowed roots
        # Try to import guard if available
        try:
            import importlib

            paths_mod: Any = importlib.import_module("agent_harness.tools._paths")
            is_path_allowed = paths_mod.is_path_allowed
            # Use guard if available
            allowed, why = is_path_allowed(
                str(path.resolve()), self._config, context, mode="read"
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

        data: object = None
        try:
            if fmt_detected == "csv":
                data = _read_csv(path, encoding)
            elif fmt_detected == "json":
                data = _read_json(path, encoding)
            elif fmt_detected in ("txt", "md"):
                data = _read_text(path, encoding)
            elif fmt_detected == "pdf":
                try:
                    data = _read_pdf(path)
                except RuntimeError as exc:
                    return ToolResult(
                        success=False,
                        error=str(exc),
                        metadata={
                            "tool_name": self.name,
                            "duration_ms": int((time.monotonic() - start) * 1000),
                            "retryable": False,
                        },
                    )
            else:
                # Unknown format -> treat as text
                data = _read_text(path, encoding)
        except FileNotFoundError:
            suggestions2: list[str] = _suggest_similar(path)
            meta2: dict[str, Any] = {
                "tool_name": self.name,
                "duration_ms": int((time.monotonic() - start) * 1000),
                "retryable": False,
            }
            if suggestions2:
                meta2["suggestions"] = suggestions2
            return ToolResult(
                success=False, error=f"File not found: {raw_path}", metadata=meta2
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                error=f"Read failed: {exc}",
                metadata={
                    "tool_name": self.name,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                    "retryable": False,
                },
            )

        duration_ms = int((time.monotonic() - start) * 1000)
        return ToolResult(
            success=True,
            output=data,
            metadata={"tool_name": self.name, "duration_ms": duration_ms},
        )
