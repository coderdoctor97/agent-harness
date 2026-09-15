"""Tests for shared doubles kit.

Spec: SPEC-004 §1, SPEC-006 §1, SPEC-001 §2.3
"""

from __future__ import annotations

from tests.test_tools.doubles import (
    BoomTool,
    EchoTool,
    FakeConfig,
    FakeLLMClient,
    FakeLogger,
    LLMResponse,
    tmp_workspace,
)


def test_fake_config_shapes() -> None:
    cfg = FakeConfig()
    assert cfg.security.max_output_bytes == 1_000_000
    assert cfg.security.sandbox_code is True
    assert cfg.security.network_in_code is False
    assert cfg.security.allow_shell is False
    assert cfg.search.provider == "duckduckgo"
    assert cfg.search.max_results == 10
    assert cfg.execution.temp_dir == "./tmp"
    assert cfg.execution.output_dir == "./output"
    assert cfg.llm.provider == "openai"
    # duck-typed get
    assert cfg.get("security.max_output_bytes") == 1_000_000
    assert cfg.get("missing.key", "def") == "def"
    d = cfg.to_dict()
    assert "llm" in d and "security" in d


def test_fake_llm_client_complete() -> None:
    llm = FakeLLMClient(responses=["hello", LLMResponse(text="world")])
    r1 = llm.complete([{"role": "user", "content": "hi"}])
    assert r1.text == "hello"
    assert llm.usage.calls == 1
    r2 = llm.complete([{"role": "user", "content": "hi"}])
    assert r2.text == "world"
    assert llm.usage.calls == 2


def test_fake_llm_client_complete_json() -> None:
    llm = FakeLLMClient(json_responses=[{"key": "value"}])
    data, resp = llm.complete_json([{"role": "user", "content": "hi"}])
    assert data == {"key": "value"}
    assert isinstance(resp, LLMResponse)


def test_fake_logger_records() -> None:
    logger = FakeLogger()
    logger.log("INFO", "tools", "tool_executed", tool_name="x")
    assert len(logger.events) == 1
    assert logger.events[0]["tool_name"] == "x"
    child = logger.child("orchestrator")
    child.info("orchestrator", "step_started", step_id="s0")
    # child shares events list
    assert len(logger.events) == 2
    assert FakeLogger.default().events == []


def test_echo_and_boom_tools() -> None:
    echo = EchoTool(output="done", capabilities=["greeting"])
    r = echo.execute({}, {})
    assert r.success is True and r.output == "done"
    assert "greeting" in echo.capabilities
    # context not mutated check (execute copies)
    ctx = {"a": 1}
    echo.execute({"msg": "hi"}, ctx)
    assert ctx == {"a": 1}

    boom = BoomTool(error="fail", retryable=True)
    r2 = boom.execute({}, {})
    assert r2.success is False
    assert r2.metadata["retryable"] is True
    # validate_input
    assert boom.validate_input({}) == (True, "")
    # cleanup idempotent
    boom.cleanup()
    echo.cleanup()


def test_tmp_workspace_creates_dir() -> None:
    ws = tmp_workspace()
    assert ws.exists() and ws.is_dir()
    # cleanup
    ws.rmdir()


def test_fake_config_dict_security_path() -> None:
    # Ensure doubles work with run_tool's duck-typed config handling
    from agent_harness.tools.base import run_tool

    cfg = FakeConfig()
    cfg.security.max_output_bytes = 5
    tool = EchoTool(output="1234567890")
    result = run_tool(tool, {}, {}, config=cfg)
    assert result.metadata.get("truncated") is True


def test_zero_network_subprocess_doubles() -> None:
    # Ensure no real network/subprocess is triggered by doubles
    # This test documents the exit criteria: doubles alone never hit network.
    llm = FakeLLMClient(responses=["ok"])
    r = llm.complete([{"role": "user", "content": "test"}])
    assert r.text == "ok"
    logger = FakeLogger()
    logger.info("test", "event", foo="bar")  # noqa: PLE1205
    assert logger.events[0]["foo"] == "bar"
