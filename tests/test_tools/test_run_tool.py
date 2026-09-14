"""Tests for run_tool wrapper R1/R2/R4/R5.

Spec: SPEC-002 §1.1
"""

from __future__ import annotations

from typing import Any

from agent_harness.tools.base import BaseTool, ToolResult, run_tool


class BoomTool(BaseTool):
    @property
    def name(self) -> str:
        return "boom_tool"

    @property
    def description(self) -> str:
        return "Tool that always raises."

    def execute(
        self, input_data: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        raise RuntimeError("kaboom")


class EchoTool(BaseTool):
    @property
    def name(self) -> str:
        return "echo_tool"

    @property
    def description(self) -> str:
        return "Echoes input."

    def execute(
        self, input_data: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        return ToolResult(success=True, output=input_data.get("msg", ""), metadata={})


class ValidatingTool(BaseTool):
    @property
    def name(self) -> str:
        return "validating_tool"

    @property
    def description(self) -> str:
        return "Requires foo."

    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str]:
        if "foo" not in input_data:
            return False, "Missing required 'foo'"
        return True, ""

    def execute(
        self, input_data: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        return ToolResult(success=True, output=input_data["foo"], metadata={})


class FakeLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def log(self, level: str, component: str, event: str, **fields: Any) -> None:
        self.events.append(
            {"level": level, "component": component, "event": event, **fields}
        )


class FakeConfig:
    def __init__(self, max_output_bytes: int = 1_000_000) -> None:
        sec = type("Sec", (), {"max_output_bytes": max_output_bytes})()
        self.security = sec


def test_run_tool_catches_exception_r1() -> None:
    tool = BoomTool()
    result = run_tool(tool, {}, {}, config=FakeConfig(), logger=None)
    assert result.success is False
    assert "kaboom" in (result.error or "")
    assert result.metadata["tool_name"] == "boom_tool"
    assert "duration_ms" in result.metadata
    # Never raises
    assert isinstance(result, ToolResult)


def test_run_tool_validate_first_r2() -> None:
    tool = ValidatingTool()
    result = run_tool(tool, {}, {}, config=FakeConfig())
    assert result.success is False
    assert "TOOL_INPUT_INVALID" in (result.error or "")
    assert result.metadata["retryable"] is False
    assert result.metadata["tool_name"] == "validating_tool"


def test_run_tool_validate_success_calls_execute() -> None:
    tool = ValidatingTool()
    result = run_tool(tool, {"foo": "bar"}, {}, config=FakeConfig())
    assert result.success is True
    assert result.output == "bar"


def test_run_tool_sets_r4_metadata() -> None:
    tool = EchoTool()
    result = run_tool(tool, {"msg": "hi"}, {}, config=FakeConfig())
    assert result.metadata["tool_name"] == "echo_tool"
    assert isinstance(result.metadata["duration_ms"], int)
    assert result.success is True


def test_run_tool_truncates_output_r5() -> None:
    tool = EchoTool()
    # small limit to trigger truncation
    config = FakeConfig(max_output_bytes=10)
    long_msg = "a" * 100
    result = run_tool(tool, {"msg": long_msg}, {}, config=config)
    assert result.success is True
    assert result.metadata.get("truncated") is True
    assert result.output.endswith("...[truncated]")
    # length should be <= max_bytes when encoded
    assert (
        len(result.output.encode("utf-8")) <= 10 + len("...[truncated]".encode("utf-8"))
        or len(result.output.encode("utf-8")) <= 10 + 20
    )  # allow marker
    # Ensure original long not fully present
    assert len(result.output) < len(long_msg)


def test_run_tool_no_truncation_when_small() -> None:
    tool = EchoTool()
    config = FakeConfig(max_output_bytes=1000)
    result = run_tool(tool, {"msg": "short"}, {}, config=config)
    assert result.metadata.get("truncated") is not True
    assert result.output == "short"


def test_run_tool_emits_tool_executed_log() -> None:
    tool = EchoTool()
    logger = FakeLogger()
    result = run_tool(tool, {"msg": "hi"}, {}, config=FakeConfig(), logger=logger)
    assert result.success is True
    assert len(logger.events) == 1
    evt = logger.events[0]
    assert evt["event"] == "tool_executed"
    assert evt["tool_name"] == "echo_tool"
    assert evt["status"] == "success"
    assert "duration_ms" in evt


def test_run_tool_log_on_failure() -> None:
    tool = BoomTool()
    logger = FakeLogger()
    result = run_tool(tool, {}, {}, config=FakeConfig(), logger=logger)
    assert result.success is False
    assert len(logger.events) == 1
    assert logger.events[0]["status"] == "failure"


def test_run_tool_handles_dict_config() -> None:
    tool = EchoTool()
    config = {"security": {"max_output_bytes": 5}}
    result = run_tool(tool, {"msg": "1234567890"}, {}, config=config)  # type: ignore[arg-type]
    assert result.metadata.get("truncated") is True


def test_run_tool_config_none_uses_default() -> None:
    tool = EchoTool()
    result = run_tool(tool, {"msg": "hi"}, {}, config=None)
    assert result.success is True
    assert result.metadata["tool_name"] == "echo_tool"
