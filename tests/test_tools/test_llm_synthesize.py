"""Tests for llm_synthesize (5.2).

Spec: SPEC-002 §3.7
"""

from __future__ import annotations

from agent_harness.tools.llm_synthesize import LlmSynthesizeTool
from tests.test_tools.doubles import FakeLLMClient


def test_llm_synthesize_basic() -> None:
    llm = FakeLLMClient(responses=["generated content"])
    tool = LlmSynthesizeTool(llm_client=llm)
    result = tool.execute({"instruction": "Write summary"}, {})
    assert result.success is True
    assert result.output == "generated content"
    assert result.metadata["tool_name"] == "llm_synthesize"


def test_llm_synthesize_source_step_results() -> None:
    llm = FakeLLMClient(responses=["synthesized"])
    tool = LlmSynthesizeTool(llm_client=llm)
    ctx = {"step_results": {"step_1": {"output": "result one"}}, "llm_client": llm}
    # Use tool without constructor client, via context
    tool2 = LlmSynthesizeTool()
    result = tool2.execute({"instruction": "Combine", "sources": ["step_1"]}, ctx)
    assert result.success is True
    # Check that llm was called with source content
    assert len(llm.calls) == 1
    # The prompt should contain result one
    assert "result one" in llm.calls[0][0]["content"]


def test_llm_synthesize_source_variables() -> None:
    llm = FakeLLMClient(responses=["out"])
    tool = LlmSynthesizeTool(llm_client=llm)
    ctx = {"variables": {"my_var": "var content"}}
    result = tool.execute({"instruction": "Use var", "sources": ["my_var"]}, ctx)
    assert result.success is True
    assert "var content" in llm.calls[0][0]["content"]


def test_llm_synthesize_source_literal_and_unresolved() -> None:
    llm = FakeLLMClient(responses=["out"])
    tool = LlmSynthesizeTool(llm_client=llm)
    result = tool.execute(
        {"instruction": "test", "sources": ["literal text", "missing_key"]},
        {"variables": {}},
    )
    assert result.success is True
    # Both sources are literal fallback, so they should be in unresolved?
    # Our implementation marks literal fallback as unresolved
    assert "unresolved_sources" in result.metadata
    assert "missing_key" in result.metadata["unresolved_sources"]
    # Also literal text should be in unresolved
    assert "literal text" in result.metadata["unresolved_sources"]


def test_llm_synthesize_tone_and_max_words() -> None:
    llm = FakeLLMClient(responses=["one two three four five six"])
    tool = LlmSynthesizeTool(llm_client=llm)
    result = tool.execute(
        {"instruction": "Write", "tone": "formal", "max_words": 3}, {}
    )
    assert result.success is True
    # Should be truncated to 3 words
    assert result.output == "one two three"  # type: ignore[operator]
    # Prompt should contain tone
    assert "formal" in llm.calls[0][0]["content"]


def test_llm_synthesize_via_context_llm() -> None:
    llm = FakeLLMClient(responses=["from context"])
    tool = LlmSynthesizeTool()
    result = tool.execute({"instruction": "hi"}, {"llm_client": llm})
    assert result.success is True
    assert result.output == "from context"


def test_llm_synthesize_missing_llm_fails() -> None:
    tool = LlmSynthesizeTool()
    result = tool.execute({"instruction": "hi"}, {})
    assert result.success is False
    assert "TOOL_EXECUTION_FAILED" in result.error  # type: ignore[union-attr]


def test_llm_synthesize_validate_input() -> None:
    tool = LlmSynthesizeTool(llm_client=FakeLLMClient())
    assert tool.validate_input({})[0] is False
    assert tool.validate_input({"instruction": ""})[0] is False
    assert tool.validate_input({"instruction": "ok", "sources": "not list"})[0] is False  # type: ignore[dict-item]
    assert tool.validate_input({"instruction": "ok", "sources": [123]})[0] is False  # type: ignore[dict-item]
    assert tool.validate_input({"instruction": "ok", "tone": 123})[0] is False  # type: ignore[dict-item]
    assert tool.validate_input({"instruction": "ok", "max_words": -1})[0] is False
    assert tool.validate_input({"instruction": "ok"})[0] is True
    assert tool.validate_input({"instruction": "ok", "sources": ["a"]})[0] is True


def test_llm_synthesize_step_output_suffix() -> None:
    llm = FakeLLMClient(responses=["out"])
    tool = LlmSynthesizeTool(llm_client=llm)
    ctx = {"step_results": {"step_1": {"output": "hello world"}}}
    result = tool.execute({"instruction": "test", "sources": ["step_1_output"]}, ctx)
    assert result.success is True
    assert "hello world" in llm.calls[0][0]["content"]


def test_llm_synthesize_capabilities() -> None:
    tool = LlmSynthesizeTool()
    assert tool.name == "llm_synthesize"
    assert set(tool.capabilities) == {"llm", "synthesize", "generate"}
    assert len(tool.description) <= 300
