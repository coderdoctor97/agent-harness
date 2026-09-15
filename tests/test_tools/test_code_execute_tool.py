"""Tests for code_execute tool surface (3.3).

Spec: SPEC-002 §3.3
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from agent_harness.tools.code_execute import CodeExecuteTool
from tests.test_tools.doubles import FakeConfig, FakeLLMClient


def test_code_execute_validate_exactly_one() -> None:
    tool = CodeExecuteTool()
    assert tool.validate_input({})[0] is False
    assert tool.validate_input({"code": "print(1)", "task": "do thing"})[0] is False
    assert tool.validate_input({"code": ""})[0] is False
    assert tool.validate_input({"code": "print(1)"})[0] is True
    assert tool.validate_input({"task": "do thing"})[0] is True
    assert tool.validate_input({"task": ""})[0] is False
    assert tool.validate_input({"task": "hi", "language": "javascript"})[0] is False
    assert tool.validate_input({"task": "hi", "language": "python"})[0] is True


def test_code_execute_success_stdout_metadata() -> None:
    cfg = FakeConfig()
    cfg.security.code_timeout = 5
    tool = CodeExecuteTool(config=cfg)
    result = tool.execute({"code": "print('hello world')"}, {})
    assert result.success is True
    assert "hello world" in result.output
    assert result.metadata["tool_name"] == "code_execute"
    assert "duration_ms" in result.metadata
    assert result.metadata["returncode"] == 0
    assert "stderr" in result.metadata


def test_code_execute_non_zero_exit() -> None:
    tool = CodeExecuteTool(config=FakeConfig())
    # Code that writes to stderr and exits 1
    result = tool.execute(
        {
            "code": "import sys; print('out'); print('err', file=sys.stderr); sys.exit(1)"
        },
        {},
    )
    assert result.success is False
    assert result.output == "out\n" or "out" in result.output
    assert result.metadata["returncode"] == 1
    assert "err" in result.metadata["stderr"]
    assert result.metadata["tool_name"] == "code_execute"


def test_code_execute_syntax_error() -> None:
    tool = CodeExecuteTool(config=FakeConfig())
    result = tool.execute({"code": "def foo(:\n  pass"}, {})
    assert result.success is False
    assert result.metadata["returncode"] != 0
    # Error should contain syntax info
    assert result.error is not None
    assert result.metadata["tool_name"] == "code_execute"


def test_code_execute_timeout_sandbox_timeout() -> None:
    cfg = FakeConfig()
    cfg.security.code_timeout = 1
    tool = CodeExecuteTool(config=cfg)
    result = tool.execute({"code": "import time; time.sleep(2)"}, {})
    assert result.success is False
    assert "SANDBOX_TIMEOUT" in (result.error or "")
    assert result.metadata.get("violation") == "SANDBOX_TIMEOUT"
    assert result.metadata.get("retryable") is False
    assert "timed out" in (result.error or "").lower()


def test_code_execute_sandbox_violation_blocked_pattern() -> None:
    tool = CodeExecuteTool(config=FakeConfig())
    result = tool.execute({"code": "import subprocess; subprocess.run(['ls'])"}, {})
    assert result.success is False
    assert (
        "SANDBOX_VIOLATION" in result.metadata.get("violation", "")
        or "Blocked" in (result.error or "")
    )
    assert result.metadata.get("retryable") is False
    assert "blocked" in (result.error or "").lower()


def test_code_execute_sandbox_violation_ast() -> None:
    tool = CodeExecuteTool(config=FakeConfig())
    result = tool.execute({"code": "import socket"}, {})
    assert result.success is False
    assert result.metadata.get("violation") == "SANDBOX_VIOLATION"
    assert result.metadata.get("retryable") is False


def test_code_execute_direct_exec_when_sandbox_disabled() -> None:
    cfg = FakeConfig()
    cfg.security.sandbox_code = False
    tool = CodeExecuteTool(config=cfg)
    result = tool.execute({"code": "print('direct')"}, {})
    assert result.success is True
    assert "direct" in result.output
    assert result.metadata["returncode"] == 0


def test_code_execute_capabilities_and_description() -> None:
    tool = CodeExecuteTool()
    assert tool.name == "code_execute"
    assert set(tool.capabilities) == {"code", "execution", "compute"}
    assert len(tool.description) <= 300
    assert "code" in tool.description.lower()


def test_code_execute_output_truncation() -> None:
    cfg = FakeConfig()
    cfg.security.max_output_bytes = 50
    tool = CodeExecuteTool(config=cfg)
    result = tool.execute({"code": "print('A'*1000)"}, {})
    # Should be truncated via sandbox layer
    assert result.success is True
    assert result.metadata.get("truncated") is True or "...[truncated]" in result.output


def test_code_execute_task_mode_requires_llm() -> None:
    tool = CodeExecuteTool(config=FakeConfig(), llm_client=None)
    result = tool.execute({"task": "print hello"}, {})
    assert result.success is False
    assert "llm_client" in (result.error or "").lower()


def test_code_execute_task_mode_with_fake_llm() -> None:
    # Task mode basic generation (3.4 will expand, but ensure 3.3 handles simple)
    cfg = FakeConfig()
    cfg.execution.temp_dir = tempfile.mkdtemp()
    llm = FakeLLMClient(responses=["print('generated')"])
    tool = CodeExecuteTool(config=cfg, llm_client=llm)
    result = tool.execute({"task": "print generated"}, {})
    # The FakeLLM returns print('generated'), which should be executed
    assert result.success is True
    assert "generated" in result.output
    # Generated code path should be reported
    assert "generated_code_path" in result.metadata
    # File should exist
    path = result.metadata["generated_code_path"]
    assert Path(path).exists()
    # Cleanup
    Path(path).unlink(missing_ok=True)
    Path(cfg.execution.temp_dir).rmdir()


def test_code_execute_task_mode_via_context_llm() -> None:
    cfg = FakeConfig()
    cfg.execution.temp_dir = tempfile.mkdtemp()
    llm = FakeLLMClient(responses=["print('from context')"])
    tool = CodeExecuteTool(config=cfg, llm_client=None)
    result = tool.execute({"task": "do"}, {"llm_client": llm})
    assert result.success is True
    assert "from context" in result.output
    # cleanup
    if "generated_code_path" in result.metadata:
        Path(result.metadata["generated_code_path"]).unlink(missing_ok=True)
        Path(cfg.execution.temp_dir).rmdir()
