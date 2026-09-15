"""Tests for csv_process (4.4).

Spec: SPEC-002 §3.9
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

from agent_harness.tools.csv_process import CsvProcessTool
from tests.test_tools.doubles import FakeConfig


def _make_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def test_csv_filter_and_sort() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "data.csv"
        _make_csv(p, [{"a": "1", "b": "x"}, {"a": "2", "b": "y"}, {"a": "1", "b": "z"}])
        cfg = FakeConfig()
        cfg.execution.output_dir = tmp
        tool = CsvProcessTool(config=cfg)
        result = tool.execute(
            {
                "path": str(p),
                "operations": [
                    {"type": "filter", "column": "a", "value": "1"},
                    {"type": "sort", "column": "b", "order": "desc"},
                ],
            },
            {},
        )
        assert result.success is True
        assert len(result.output) == 2  # type: ignore[arg-type]
        # After filter, b values are x and z, sorted desc -> z, x
        assert result.output[0]["b"] == "z"  # type: ignore[index]
        assert result.output[1]["b"] == "x"  # type: ignore[index]


def test_csv_head_tail_select() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "data.csv"
        _make_csv(p, [{"a": str(i), "b": str(i * 10)} for i in range(10)])
        cfg = FakeConfig()
        cfg.execution.output_dir = tmp
        tool = CsvProcessTool(config=cfg)
        result = tool.execute(
            {"path": str(p), "operations": [{"type": "head", "n": 3}]}, {}
        )
        assert result.success is True
        assert len(result.output) == 3  # type: ignore[arg-type]
        result2 = tool.execute(
            {"path": str(p), "operations": [{"type": "tail", "n": 2}]}, {}
        )
        assert result2.success is True
        assert len(result2.output) == 2  # type: ignore[arg-type]
        assert result2.output[0]["a"] == "8"  # type: ignore[index]
        result3 = tool.execute(
            {"path": str(p), "operations": [{"type": "select", "columns": ["a"]}]}, {}
        )
        assert result3.success is True
        assert list(result3.output[0].keys()) == ["a"]  # type: ignore[index]


def test_csv_rename() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "data.csv"
        _make_csv(p, [{"a": "1", "b": "2"}])
        cfg = FakeConfig()
        cfg.execution.output_dir = tmp
        tool = CsvProcessTool(config=cfg)
        result = tool.execute(
            {
                "path": str(p),
                "operations": [{"type": "rename", "mapping": {"a": "alpha"}}],
            },
            {},
        )
        assert result.success is True
        assert "alpha" in result.output[0]  # type: ignore[index]
        assert "a" not in result.output[0]  # type: ignore[index]


def test_csv_aggregate_sum_and_count() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "data.csv"
        _make_csv(
            p, [{"g": "x", "v": "10"}, {"g": "x", "v": "20"}, {"g": "y", "v": "5"}]
        )
        cfg = FakeConfig()
        cfg.execution.output_dir = tmp
        tool = CsvProcessTool(config=cfg)
        result = tool.execute(
            {
                "path": str(p),
                "operations": [
                    {"type": "aggregate", "group_by": "g", "column": "v", "func": "sum"}
                ],
            },
            {},
        )
        assert result.success is True
        # Find group x sum 30
        by_g = {r["g"]: r for r in result.output}  # type: ignore[attr-defined]
        assert by_g["x"]["sum_v"] == "30"
        assert by_g["y"]["sum_v"] == "5"
        result2 = tool.execute(
            {
                "path": str(p),
                "operations": [
                    {
                        "type": "aggregate",
                        "group_by": "g",
                        "column": "v",
                        "func": "count",
                    }
                ],
            },
            {},
        )
        assert result2.success is True
        by_g2 = {r["g"]: r for r in result2.output}  # type: ignore[attr-defined]
        assert by_g2["x"]["count_v"] == "2"


def test_csv_output_path_writes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "data.csv"
        out = Path(tmp) / "out.csv"
        _make_csv(p, [{"a": "1"}, {"a": "2"}])
        cfg = FakeConfig()
        cfg.execution.output_dir = tmp
        tool = CsvProcessTool(config=cfg)
        result = tool.execute(
            {
                "path": str(p),
                "operations": [{"type": "head", "n": 1}],
                "output_path": str(out),
            },
            {},
        )
        assert result.success is True
        assert result.metadata["output_path"] == str(out)
        assert out.exists()
        with out.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 1
            assert rows[0]["a"] == "1"


def test_csv_unknown_operation_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "data.csv"
        _make_csv(p, [{"a": "1"}])
        cfg = FakeConfig()
        cfg.execution.output_dir = tmp
        tool = CsvProcessTool(config=cfg)
        result = tool.execute(
            {"path": str(p), "operations": [{"type": "unknown_op"}]}, {}
        )
        assert result.success is False
        assert "TOOL_INPUT_INVALID" in result.error  # type: ignore[union-attr]
        assert "unknown type" in result.error.lower()  # type: ignore[union-attr]


def test_csv_missing_column_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "data.csv"
        _make_csv(p, [{"a": "1"}])
        cfg = FakeConfig()
        cfg.execution.output_dir = tmp
        tool = CsvProcessTool(config=cfg)
        result = tool.execute(
            {
                "path": str(p),
                "operations": [{"type": "filter", "column": "missing", "value": "x"}],
            },
            {},
        )
        assert result.success is False
        assert "TOOL_INPUT_INVALID" in result.error  # type: ignore[union-attr]
        assert "column" in result.error.lower()  # type: ignore[union-attr]


def test_csv_chain_operations() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "data.csv"
        _make_csv(p, [{"a": "1", "b": "2"}, {"a": "1", "b": "3"}, {"a": "2", "b": "4"}])
        cfg = FakeConfig()
        cfg.execution.output_dir = tmp
        tool = CsvProcessTool(config=cfg)
        result = tool.execute(
            {
                "path": str(p),
                "operations": [
                    {"type": "filter", "column": "a", "value": "1"},
                    {"type": "select", "columns": ["b"]},
                    {"type": "sort", "column": "b", "order": "desc"},
                ],
            },
            {},
        )
        assert result.success is True
        assert len(result.output) == 2  # type: ignore[arg-type]
        assert result.output[0]["b"] == "3"  # type: ignore[index]


def test_csv_validate_input() -> None:
    tool = CsvProcessTool()
    assert tool.validate_input({})[0] is False
    assert tool.validate_input({"path": "a.csv"})[0] is False
    assert tool.validate_input({"path": "a.csv", "operations": []})[0] is False
    assert (
        tool.validate_input({"path": "a.csv", "operations": [{"type": "filter"}]})[0]
        is False
    )
    assert (
        tool.validate_input(
            {"path": "a.csv", "operations": [{"type": "head", "n": 1}]}
        )[0]
        is True
    )


def test_csv_capabilities() -> None:
    tool = CsvProcessTool()
    assert tool.name == "csv_process"
    assert set(tool.capabilities) == {"csv", "data", "transform"}
