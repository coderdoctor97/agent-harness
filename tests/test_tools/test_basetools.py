"""Tests for BaseTool ABC contract.

Spec: SPEC-002 §1
"""

from __future__ import annotations

import pytest

from agent_harness.tools.base import BaseTool, ToolResult


def test_basetools_cannot_instantiate_abstract() -> None:
    with pytest.raises(TypeError):
        BaseTool()  # type: ignore[abstract]


def test_basetools_concrete_minimal_implementation() -> None:
    class MinimalTool(BaseTool):
        @property
        def name(self) -> str:
            return "minimal_tool"

        @property
        def description(self) -> str:
            return "Minimal tool for testing BaseTool contract."

        def execute(self, input_data: dict, context: dict) -> ToolResult:
            return ToolResult(success=True, output="ok", metadata={})

    tool = MinimalTool()
    assert tool.name == "minimal_tool"
    assert tool.description == "Minimal tool for testing BaseTool contract."
    assert tool.capabilities == []
    assert tool.validate_input({}) == (True, "")
    # cleanup should be idempotent and not raise even if never executed
    tool.cleanup()
    tool.cleanup()
    result = tool.execute({}, {})
    assert result.success is True


def test_basetools_capabilities_and_validate_defaults() -> None:
    class DummyTool(BaseTool):
        @property
        def name(self) -> str:
            return "dummy"

        @property
        def description(self) -> str:
            return "dummy desc"

        def execute(self, input_data: dict, context: dict) -> ToolResult:
            return ToolResult(success=True, output=None, metadata={})

    t = DummyTool()
    assert t.capabilities == []
    is_valid, msg = t.validate_input({"any": 1})
    assert is_valid is True
    assert msg == ""
    # cleanup idempotent
    t.cleanup()
    assert t.cleanup() is None


def test_basetools_subclass_must_implement_name_description_execute() -> None:
    # Missing execute should still be abstract
    class IncompleteTool(BaseTool):
        @property
        def name(self) -> str:
            return "incomplete"

        @property
        def description(self) -> str:
            return "incomplete"

    with pytest.raises(TypeError):
        IncompleteTool()  # type: ignore[abstract]
