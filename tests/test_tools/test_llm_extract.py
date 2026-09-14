"""Tests for llm_extract (5.1).

Spec: SPEC-002 §3.6
"""

from __future__ import annotations

from agent_harness.tools.llm_extract import LlmExtractTool
from tests.test_tools.doubles import FakeLLMClient, LLMResponse


def test_llm_extract_json() -> None:
    llm = FakeLLMClient(responses=['{"name": "Alice", "age": 30}'])
    tool = LlmExtractTool(llm_client=llm)
    result = tool.execute(
        {
            "input_text": "Alice is 30",
            "instruction": "Extract name and age",
            "output_format": "json",
        },
        {},
    )
    assert result.success is True
    assert result.output["name"] == "Alice"  # type: ignore[index]
    assert result.metadata["tool_name"] == "llm_extract"


def test_llm_extract_json_with_fences() -> None:
    llm = FakeLLMClient(responses=['```json\n{"key": "value"}\n```'])
    tool = LlmExtractTool(llm_client=llm)
    result = tool.execute(
        {"input_text": "text", "instruction": "extract", "output_format": "json"}, {}
    )
    assert result.success is True
    assert result.output["key"] == "value"  # type: ignore[index]


def test_llm_extract_text() -> None:
    llm = FakeLLMClient(responses=["plain text result"])
    tool = LlmExtractTool(llm_client=llm)
    result = tool.execute({"input_text": "hello", "instruction": "summarize"}, {})
    assert result.success is True
    assert result.output == "plain text result"
    assert result.metadata["tool_name"] == "llm_extract"


def test_llm_extract_markdown() -> None:
    llm = FakeLLMClient(responses=["# Title\nContent"])
    tool = LlmExtractTool(llm_client=llm)
    result = tool.execute(
        {"input_text": "hello", "instruction": "format", "output_format": "markdown"},
        {},
    )
    assert result.success is True
    assert "# Title" in result.output  # type: ignore[operator]


def test_llm_extract_via_context() -> None:
    llm = FakeLLMClient(responses=["from context"])
    tool = LlmExtractTool()  # no constructor client
    result = tool.execute({"input_text": "t", "instruction": "i"}, {"llm_client": llm})
    assert result.success is True
    assert result.output == "from context"


def test_llm_extract_missing_llm_fails() -> None:
    tool = LlmExtractTool()
    result = tool.execute({"input_text": "t", "instruction": "i"}, {})
    assert result.success is False
    assert "TOOL_EXECUTION_FAILED" in result.error  # type: ignore[union-attr]
    assert "llm_client" in result.error.lower()  # type: ignore[union-attr]


def test_llm_extract_validate_input() -> None:
    tool = LlmExtractTool(llm_client=FakeLLMClient())
    assert tool.validate_input({})[0] is False
    assert tool.validate_input({"input_text": "a"})[0] is False
    assert tool.validate_input({"input_text": "a", "instruction": ""})[0] is False
    assert (
        tool.validate_input(
            {"input_text": "a", "instruction": "b", "output_format": "bad"}
        )[0]
        is False
    )
    assert tool.validate_input({"input_text": "a", "instruction": "b"})[0] is True


def test_llm_extract_json_via_complete_json() -> None:
    llm = FakeLLMClient(json_responses=[{"extracted": 123}])
    tool = LlmExtractTool(llm_client=llm)
    result = tool.execute(
        {"input_text": "t", "instruction": "i", "output_format": "json"}, {}
    )
    assert result.success is True
    assert result.output["extracted"] == 123  # type: ignore[index]


def test_llm_extract_capabilities() -> None:
    tool = LlmExtractTool()
    assert tool.name == "llm_extract"
    assert set(tool.capabilities) == {"llm", "extract", "transform"}
    assert len(tool.description) <= 300


def test_llm_extract_llm_response_object() -> None:
    llm = FakeLLMClient(responses=[LLMResponse(text='{"a": 1}')])
    tool = LlmExtractTool(llm_client=llm)
    result = tool.execute(
        {"input_text": "t", "instruction": "i", "output_format": "json"}, {}
    )
    assert result.success is True
    assert result.output["a"] == 1  # type: ignore[index]
