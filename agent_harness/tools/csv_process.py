"""CSV process tool.

Spec: SPEC-002 §3.9
"""

from __future__ import annotations

import csv
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from agent_harness.tools.base import BaseTool, ToolResult

VALID_OPS = {"filter", "sort", "head", "tail", "select", "rename", "aggregate"}
FILTER_OPS = {"eq", "ne", "gt", "lt", "gte", "lte", "contains"}


def _validate_operations(ops: Any) -> tuple[bool, str]:
    if not isinstance(ops, list):
        return False, "'operations' must be a list"
    if not ops:
        return False, "'operations' must not be empty"
    for idx, op in enumerate(ops):
        if not isinstance(op, dict):
            return False, f"Operation {idx} must be a dict"
        if "type" not in op:
            return False, f"Operation {idx} missing 'type'"
        t = op["type"]
        if t not in VALID_OPS:
            return False, f"Operation {idx} has unknown type {t!r}"
        # Validate required fields per type
        if t == "filter":
            if "column" not in op or "value" not in op:
                return False, f"Operation {idx} filter requires 'column' and 'value'"
        elif t == "sort":
            if "column" not in op:
                return False, f"Operation {idx} sort requires 'column'"
            if "order" in op and op["order"] not in ("asc", "desc"):
                return False, f"Operation {idx} sort order must be 'asc' or 'desc'"
        elif t in ("head", "tail"):
            if "n" not in op:
                return False, f"Operation {idx} {t} requires 'n'"
            if not isinstance(op["n"], int) or op["n"] < 0:
                return False, f"Operation {idx} {t} 'n' must be a non-negative int"
        elif t == "select":
            if "columns" not in op or not isinstance(op["columns"], list):
                return False, f"Operation {idx} select requires 'columns' list"
        elif t == "rename":
            if "mapping" not in op or not isinstance(op["mapping"], dict):
                return False, f"Operation {idx} rename requires 'mapping' dict"
        elif t == "aggregate":
            if "group_by" not in op or "column" not in op:
                return (
                    False,
                    f"Operation {idx} aggregate requires 'group_by' and 'column'",
                )
            if "func" in op and op["func"] not in ("sum", "mean", "count"):
                return False, f"Operation {idx} aggregate func must be sum|mean|count"
    return True, ""


def _apply_filter(
    rows: list[dict[str, str]], op: dict[str, Any]
) -> list[dict[str, str]]:
    col = str(op["column"])
    val = op["value"]
    oper = str(op.get("op", "eq"))
    if oper not in FILTER_OPS:
        oper = "eq"
    # Check column exists
    if rows and col not in rows[0]:
        raise ValueError(f"Column {col!r} not found")
    result: list[dict[str, str]] = []
    for r in rows:
        cell = r.get(col, "")
        # For numeric comparisons, try to convert
        if oper == "eq":
            if str(cell) == str(val):
                result.append(r)
        elif oper == "ne":
            if str(cell) != str(val):
                result.append(r)
        elif oper == "contains":
            if str(val) in str(cell):
                result.append(r)
        elif oper in ("gt", "lt", "gte", "lte"):
            # Try numeric
            try:
                a = float(cell)
                b = float(val)
            except (ValueError, TypeError):
                # Fallback to string compare
                a_s = str(cell)
                b_s = str(val)
                if (
                    oper == "gt"
                    and a_s > b_s
                    or oper == "lt"
                    and a_s < b_s
                    or oper == "gte"
                    and a_s >= b_s
                    or oper == "lte"
                    and a_s <= b_s
                ):
                    result.append(r)
                continue
            if (
                oper == "gt"
                and a > b
                or oper == "lt"
                and a < b
                or oper == "gte"
                and a >= b
                or oper == "lte"
                and a <= b
            ):
                result.append(r)
    return result


def _apply_sort(rows: list[dict[str, str]], op: dict[str, Any]) -> list[dict[str, str]]:
    col = str(op["column"])
    order = str(op.get("order", "asc"))
    if rows and col not in rows[0]:
        raise ValueError(f"Column {col!r} not found")
    reverse = order == "desc"

    # Try numeric sort, fallback to string
    def sort_key(r: dict[str, str]) -> Any:
        v = r.get(col, "")
        try:
            return float(v)
        except (ValueError, TypeError):
            return v

    return sorted(rows, key=sort_key, reverse=reverse)


def _apply_select(
    rows: list[dict[str, str]], op: dict[str, Any]
) -> list[dict[str, str]]:
    cols: list[str] = [str(c) for c in op["columns"]]
    if rows:
        for c in cols:
            if c not in rows[0]:
                raise ValueError(f"Column {c!r} not found")
    return [{c: r[c] for c in cols} for r in rows]


def _apply_rename(
    rows: list[dict[str, str]], op: dict[str, Any]
) -> list[dict[str, str]]:
    mapping: dict[str, str] = {str(k): str(v) for k, v in op["mapping"].items()}
    # Check that source columns exist
    if rows:
        for src in mapping:
            if src not in rows[0]:
                raise ValueError(f"Column {src!r} not found")
    result: list[dict[str, str]] = []
    for r in rows:
        new_r = {}
        for k, v in r.items():
            new_k = mapping.get(k, k)
            new_r[new_k] = v
        result.append(new_r)
    return result


def _apply_aggregate(
    rows: list[dict[str, str]], op: dict[str, Any]
) -> list[dict[str, str]]:
    group_by = str(op["group_by"])
    column = str(op["column"])
    func = str(op.get("func", "sum"))
    if rows:
        if group_by not in rows[0]:
            raise ValueError(f"Column {group_by!r} not found")
        if column not in rows[0] and func != "count":
            raise ValueError(f"Column {column!r} not found")
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        key = r.get(group_by, "")
        grouped[key].append(r)
    result: list[dict[str, str]] = []
    for key, group in grouped.items():
        if func == "count":
            val = len(group)
            result.append({group_by: key, f"{func}_{column}": str(val)})
        elif func == "sum":
            total = 0.0
            for g in group:
                try:
                    total += float(g.get(column, 0) or 0)
                except (ValueError, TypeError):
                    continue
            # If total is int-like, keep int formatting?
            if total.is_integer():
                result.append({group_by: key, f"{func}_{column}": str(int(total))})
            else:
                result.append({group_by: key, f"{func}_{column}": str(total)})
        elif func == "mean":
            total2 = 0.0
            count = 0
            for g in group:
                try:
                    total2 += float(g.get(column, 0) or 0)
                    count += 1
                except (ValueError, TypeError):
                    continue
            mean = total2 / count if count else 0.0
            result.append({group_by: key, f"{func}_{column}": str(mean)})
    return result


class CsvProcessTool(BaseTool):
    """CSV process tool per SPEC-002 §3.9."""

    def __init__(self, config: Any = None) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "csv_process"

    @property
    def description(self) -> str:
        return (
            "Processes CSV files. Input: {path: str, operations: list[dict], output_path: str (optional)}. "
            "Ops: filter, sort, head, tail, select, rename, aggregate. Output: list[dict]."
        )

    @property
    def capabilities(self) -> list[str]:
        return ["csv", "data", "transform"]

    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str]:
        if "path" not in input_data:
            return False, "Missing required 'path'"
        if "operations" not in input_data:
            return False, "Missing required 'operations'"
        if not isinstance(input_data["path"], str) or not input_data["path"].strip():
            return False, "'path' must be a non-empty string"
        if "output_path" in input_data and not isinstance(
            input_data["output_path"], str
        ):
            return False, "'output_path' must be a string"
        is_valid, err = _validate_operations(input_data["operations"])
        if not is_valid:
            return False, err
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

        path: str = str(input_data["path"]).strip()
        ops: list[dict[str, Any]] = list(input_data["operations"])
        output_path: str | None = input_data.get("output_path")
        if isinstance(output_path, str):
            output_path = output_path.strip() or None

        # Path safety for input (read)
        try:
            import importlib

            paths_mod: Any = importlib.import_module("agent_harness.tools._paths")
            is_path_allowed = paths_mod.is_path_allowed
            allowed, why = is_path_allowed(path, self._config, context, mode="read")
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
            if output_path:
                allowed_w, why_w = is_path_allowed(
                    output_path, self._config, context, mode="write"
                )
                if not allowed_w:
                    return ToolResult(
                        success=False,
                        error=f"SANDBOX_VIOLATION: {why_w}",
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

        # Read CSV
        try:
            p = Path(path)
            if not p.exists():
                return ToolResult(
                    success=False,
                    error=f"File not found: {path}",
                    metadata={
                        "tool_name": self.name,
                        "duration_ms": int((time.monotonic() - start) * 1000),
                        "retryable": False,
                    },
                )
            with p.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    rows: list[dict[str, str]] = []
                else:
                    rows = [dict(row) for row in reader]
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

        # Apply operations in order
        try:
            for idx, op in enumerate(ops):
                t = op["type"]
                try:
                    if t == "filter":
                        rows = _apply_filter(rows, op)
                    elif t == "sort":
                        rows = _apply_sort(rows, op)
                    elif t == "head":
                        n = int(op["n"])
                        rows = rows[:n]
                    elif t == "tail":
                        n = int(op["n"])
                        rows = rows[-n:] if n else []
                    elif t == "select":
                        rows = _apply_select(rows, op)
                    elif t == "rename":
                        rows = _apply_rename(rows, op)
                    elif t == "aggregate":
                        rows = _apply_aggregate(rows, op)
                except ValueError as ve:
                    return ToolResult(
                        success=False,
                        error=f"TOOL_INPUT_INVALID: Operation {idx} ({t}) failed: {ve}",
                        metadata={
                            "tool_name": self.name,
                            "duration_ms": int((time.monotonic() - start) * 1000),
                            "retryable": False,
                        },
                    )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                error=f"Processing failed: {exc}",
                metadata={
                    "tool_name": self.name,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                    "retryable": False,
                },
            )

        # Write output if requested
        metadata: dict[str, Any] = {
            "tool_name": self.name,
            "duration_ms": int((time.monotonic() - start) * 1000),
        }
        if output_path:
            try:
                out_p = Path(output_path)
                parent = out_p.parent
                if parent != Path(".") and not parent.exists():
                    parent.mkdir(parents=True, exist_ok=True)
                # Determine fieldnames
                if rows:
                    fieldnames = list(rows[0].keys())
                else:
                    # If no rows, need to infer from input header? Use empty
                    fieldnames = []
                # Atomic write via temp file
                import os
                import tempfile

                dir_for_temp = (
                    str(parent) if parent != Path("") and parent != Path(".") else "."
                )
                fd, tmp_name = tempfile.mkstemp(dir=dir_for_temp)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                        if fieldnames:
                            w = csv.DictWriter(f, fieldnames=fieldnames)
                            w.writeheader()
                            w.writerows(rows)
                        else:
                            # Write empty
                            pass
                    os.replace(tmp_name, str(out_p))
                except Exception:
                    try:
                        if os.path.exists(tmp_name):
                            os.remove(tmp_name)
                    except Exception:  # noqa: BLE001, S110
                        pass
                    raise
                metadata["output_path"] = str(out_p)
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

        return ToolResult(success=True, output=rows, metadata=metadata)
