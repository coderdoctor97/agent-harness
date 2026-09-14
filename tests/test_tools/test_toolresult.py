"""Tests for ToolResult frozen shape and helpers.

Spec: SPEC-001 §2.3, SPEC-002 §1.1 R4
"""

from __future__ import annotations

from dataclasses import fields

from agent_harness.tools.base import ToolResult, fail, ok


def test_toolresult_frozen_fields() -> None:
    field_names = {f.name for f in fields(ToolResult)}
    assert field_names == {"success", "output", "error", "metadata"}
    # Check defaults
    r = ToolResult(success=True)
    assert r.output is None
    assert r.error is None
    assert r.metadata == {}


def test_toolresult_success_field_types() -> None:
    r = ToolResult(
        success=True, output="hello", error=None, metadata={"tool_name": "x"}
    )
    assert r.success is True
    assert r.output == "hello"
    assert r.error is None
    assert r.metadata["tool_name"] == "x"


def test_ok_helper_sets_required_metadata() -> None:
    r = ok("out", tool_name="my_tool", duration_ms=123)
    assert r.success is True
    assert r.output == "out"
    assert r.error is None
    assert r.metadata["tool_name"] == "my_tool"
    assert r.metadata["duration_ms"] == 123


def test_ok_helper_defaults_metadata_when_missing() -> None:
    r = ok("out")
    assert r.metadata["tool_name"] == ""
    assert r.metadata["duration_ms"] == 0


def test_ok_helper_preserves_extra_metadata() -> None:
    r = ok("out", tool_name="t", duration_ms=5, extra="value")
    assert r.metadata["extra"] == "value"


def test_fail_helper_sets_retryable_and_defaults() -> None:
    r = fail("oops", retryable=True, tool_name="t2", duration_ms=10)
    assert r.success is False
    assert r.error == "oops"
    assert r.output is None
    assert r.metadata["retryable"] is True
    assert r.metadata["tool_name"] == "t2"
    assert r.metadata["duration_ms"] == 10


def test_fail_helper_default_retryable_false() -> None:
    r = fail("oops")
    assert r.metadata["retryable"] is False
    assert r.metadata["tool_name"] == ""
    assert r.metadata["duration_ms"] == 0


def test_fail_helper_retryable_false_explicit() -> None:
    r = fail("oops", retryable=False)
    assert r.metadata["retryable"] is False
