"""Tests for file_read (4.1).

Spec: SPEC-002 §3.4
"""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from agent_harness.tools.file_read import FileReadTool


def test_file_read_txt() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "hello.txt"
        p.write_text("hello txt", encoding="utf-8")
        tool = FileReadTool()
        result = tool.execute({"path": str(p)}, {})
        assert result.success is True
        assert result.output == "hello txt"
        assert result.metadata["tool_name"] == "file_read"


def test_file_read_md() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "readme.md"
        p.write_text("# Title", encoding="utf-8")
        tool = FileReadTool()
        result = tool.execute({"path": str(p)}, {})
        assert result.success is True
        assert "# Title" in result.output  # type: ignore[operator]


def test_file_read_csv() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "data.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["a", "b"])
            w.writeheader()
            w.writerow({"a": "1", "b": "2"})
            w.writerow({"a": "3", "b": "4"})
        tool = FileReadTool()
        result = tool.execute({"path": str(p)}, {})
        assert result.success is True
        assert isinstance(result.output, list)
        assert result.output[0]["a"] == "1"  # type: ignore[index]


def test_file_read_csv_explicit_format() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "data.txt"
        # File has csv content but extension txt; explicit format csv should parse as csv
        p.write_text("a,b\n1,2\n", encoding="utf-8")
        tool = FileReadTool()
        result = tool.execute({"path": str(p), "format": "csv"}, {})
        assert result.success is True
        assert result.output[0]["a"] == "1"  # type: ignore[index]


def test_file_read_json() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "data.json"
        p.write_text(json.dumps({"key": "value", "num": 42}), encoding="utf-8")
        tool = FileReadTool()
        result = tool.execute({"path": str(p)}, {})
        assert result.success is True
        assert result.output["key"] == "value"  # type: ignore[index]


def test_file_read_encoding() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "latin.txt"
        p.write_text("caf\u00e9", encoding="latin-1")
        tool = FileReadTool()
        result = tool.execute({"path": str(p), "encoding": "latin-1"}, {})
        assert result.success is True
        assert "caf" in result.output  # type: ignore[operator]


def test_file_read_missing_suggestions() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        # Create similar files
        (Path(tmp) / "report.csv").write_text("a", encoding="utf-8")
        (Path(tmp) / "reports.csv").write_text("a", encoding="utf-8")
        (Path(tmp) / "report_final.csv").write_text("a", encoding="utf-8")
        missing = Path(tmp) / "reprot.csv"  # typo
        tool = FileReadTool()
        result = tool.execute({"path": str(missing)}, {})
        assert result.success is False
        assert "suggestions" in result.metadata
        assert len(result.metadata["suggestions"]) <= 3
        # Should suggest at least one similar
        assert any("report" in s for s in result.metadata["suggestions"])


def test_file_read_missing_no_suggestions_when_parent_missing() -> None:
    tool = FileReadTool()
    result = tool.execute({"path": "/nonexistent_dir_xyz/missing.txt"}, {})
    assert result.success is False
    # No suggestions because parent doesn't exist
    assert "suggestions" not in result.metadata or result.metadata["suggestions"] == []


def test_file_read_pdf_unavailable_degrades() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "doc.pdf"
        p.write_bytes(b"%PDF-1.4 fake")
        tool = FileReadTool()
        # Mock both pypdf and pdfminer missing
        orig_import = __import__

        def fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name in ("pypdf", "pdfminer.high_level"):
                raise ImportError("No module")
            return orig_import(name, *args, **kwargs)  # type: ignore[call-arg]

        with patch("builtins.__import__", side_effect=fake_import):
            result = tool.execute({"path": str(p)}, {})
            # Should return failure with clear error about pdf requirement
            assert result.success is False
            assert "pypdf" in result.error.lower() or "pdfminer" in result.error.lower()  # type: ignore[union-attr]


def test_file_read_path_traversal_blocked() -> None:
    tool = FileReadTool()
    result = tool.execute({"path": "../secret.txt"}, {})
    assert result.success is False
    assert result.metadata.get("violation") == "SANDBOX_VIOLATION"
    assert "traversal" in result.error.lower()  # type: ignore[union-attr]


def test_file_read_auto_detection_and_unknown_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "unknown.xyz"
        p.write_text("fallback text", encoding="utf-8")
        tool = FileReadTool()
        result = tool.execute({"path": str(p)}, {})
        assert result.success is True
        assert result.output == "fallback text"


def test_file_read_validate_input() -> None:
    tool = FileReadTool()
    assert tool.validate_input({})[0] is False
    assert tool.validate_input({"path": ""})[0] is False
    assert tool.validate_input({"path": "a.txt", "format": 123})[0] is False  # type: ignore[dict-item]
    assert tool.validate_input({"path": "a.txt", "encoding": 123})[0] is False  # type: ignore[dict-item]
    assert tool.validate_input({"path": "a.txt"})[0] is True


def test_file_read_capabilities_description() -> None:
    tool = FileReadTool()
    assert tool.name == "file_read"
    assert set(tool.capabilities) == {"file", "read", "io"}
    assert len(tool.description) <= 300
