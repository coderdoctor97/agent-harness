"""Tests for file_write (4.3).

Spec: SPEC-002 §3.5
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from agent_harness.tools.file_write import FileWriteTool
from tests.test_tools.doubles import FakeConfig


def test_file_write_creates_and_overwrites() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "output"
        out_dir.mkdir()
        cfg = FakeConfig()
        cfg.execution.output_dir = str(out_dir)
        tool = FileWriteTool(config=cfg)
        target = out_dir / "sub" / "file.txt"
        # Create with parents
        result = tool.execute({"path": str(target), "content": "hello"}, {})
        assert result.success is True
        assert result.output == str(target)
        assert target.read_text(encoding="utf-8") == "hello"
        # Overwrite
        result2 = tool.execute({"path": str(target), "content": "world"}, {})
        assert result2.success is True
        assert target.read_text(encoding="utf-8") == "world"


def test_file_write_create_dirs_false() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "output"
        out_dir.mkdir()
        cfg = FakeConfig()
        cfg.execution.output_dir = str(out_dir)
        tool = FileWriteTool(config=cfg)
        target = out_dir / "missing" / "file.txt"
        result = tool.execute(
            {"path": str(target), "content": "hi", "create_dirs": False}, {}
        )
        assert result.success is False
        assert "Parent directory" in result.error  # type: ignore[union-attr]


def test_file_write_enforces_output_dir() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "output"
        out_dir.mkdir()
        other_dir = Path(tmp) / "other"
        other_dir.mkdir()
        cfg = FakeConfig()
        cfg.execution.output_dir = str(out_dir)
        tool = FileWriteTool(config=cfg)
        # Try to write outside output_dir without allowed_write_paths
        outside = other_dir / "evil.txt"
        result = tool.execute({"path": str(outside), "content": "bad"}, {})
        assert result.success is False
        assert result.metadata.get("violation") == "SANDBOX_VIOLATION"
        assert "not inside allowed directories" in result.error.lower()  # type: ignore[union-attr]
        assert str(out_dir.resolve()) in result.error  # type: ignore[union-attr]


def test_file_write_allowed_via_context() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "output"
        out_dir.mkdir()
        custom_dir = Path(tmp) / "custom"
        custom_dir.mkdir()
        cfg = FakeConfig()
        cfg.execution.output_dir = str(out_dir)
        tool = FileWriteTool(config=cfg)
        target = custom_dir / "allowed.txt"
        ctx = {"allowed_write_paths": [str(custom_dir)]}
        result = tool.execute({"path": str(target), "content": "ok"}, ctx)
        assert result.success is True
        assert target.read_text(encoding="utf-8") == "ok"


def test_file_write_atomicity_no_temp_leak() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "output"
        out_dir.mkdir()
        cfg = FakeConfig()
        cfg.execution.output_dir = str(out_dir)
        tool = FileWriteTool(config=cfg)
        target = out_dir / "atomic.txt"
        result = tool.execute({"path": str(target), "content": "data"}, {})
        assert result.success is True
        # Ensure no temp files left in out_dir
        leftovers = list(out_dir.glob("*.tmp")) + list(out_dir.glob("tmp*"))
        # mkstemp creates files like tmpXXXXXX; we already replaced, so none should remain
        assert len(leftovers) == 0


def test_file_write_validate_input() -> None:
    tool = FileWriteTool()
    assert tool.validate_input({})[0] is False
    assert tool.validate_input({"path": "a.txt"})[0] is False
    assert tool.validate_input({"path": "", "content": "x"})[0] is False
    assert tool.validate_input({"path": "a.txt", "content": 123})[0] is False  # type: ignore[dict-item]
    assert (
        tool.validate_input({"path": "a.txt", "content": "x", "create_dirs": "yes"})[0]
        is False
    )  # type: ignore[dict-item]
    assert tool.validate_input({"path": "a.txt", "content": "x"})[0] is True


def test_file_write_capabilities() -> None:
    tool = FileWriteTool()
    assert tool.name == "file_write"
    assert set(tool.capabilities) == {"file", "write", "io"}
    assert len(tool.description) <= 300


def test_file_write_does_not_mutate_context() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "output"
        out_dir.mkdir()
        cfg = FakeConfig()
        cfg.execution.output_dir = str(out_dir)
        tool = FileWriteTool(config=cfg)
        target = out_dir / "file.txt"
        ctx: dict[str, object] = {}
        result = tool.execute({"path": str(target), "content": "hi"}, ctx)  # type: ignore[arg-type]
        assert result.success is True
        # Context should remain empty (tool reads but must not mutate)
        assert ctx == {}


def test_file_write_absolute_escape_blocked() -> None:
    cfg = FakeConfig()
    cfg.execution.output_dir = "/tmp/my_output_safe"
    Path("/tmp/my_output_safe").mkdir(exist_ok=True)
    tool = FileWriteTool(config=cfg)
    result = tool.execute({"path": "/etc/passwd", "content": "evil"}, {})
    assert result.success is False
    assert result.metadata.get("violation") == "SANDBOX_VIOLATION"
