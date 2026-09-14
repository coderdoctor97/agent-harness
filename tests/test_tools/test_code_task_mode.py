"""Tests for task-mode code generation (3.4).

Spec: SPEC-002 §3.3 task mode
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from agent_harness.tools.code_execute import CodeExecuteTool
from tests.test_tools.doubles import FakeConfig, FakeLLMClient


def test_task_mode_generates_and_executes() -> None:
    cfg = FakeConfig()
    cfg.execution.temp_dir = tempfile.mkdtemp()
    cfg.security.code_timeout = 5
    # FakeLLM returns simple code
    llm = FakeLLMClient(responses=["print('from llm')"])
    tool = CodeExecuteTool(config=cfg, llm_client=llm)
    result = tool.execute({"task": "print from llm"}, {})
    assert result.success is True
    assert "from llm" in result.output
    assert "generated_code_path" in result.metadata
    path = Path(result.metadata["generated_code_path"])
    assert path.exists()
    assert "print('from llm')" in path.read_text()
    # Cleanup
    path.unlink()
    Path(cfg.execution.temp_dir).rmdir()


def test_task_mode_strips_fences() -> None:
    cfg = FakeConfig()
    cfg.execution.temp_dir = tempfile.mkdtemp()
    llm = FakeLLMClient(responses=["```python\nprint('fenced')\n```"])
    tool = CodeExecuteTool(config=cfg, llm_client=llm)
    result = tool.execute({"task": "fenced"}, {})
    assert result.success is True
    assert "fenced" in result.output
    Path(result.metadata["generated_code_path"]).unlink()
    Path(cfg.execution.temp_dir).rmdir()


def test_task_mode_failure_surfaces_stderr_and_path() -> None:
    cfg = FakeConfig()
    cfg.execution.temp_dir = tempfile.mkdtemp()
    llm = FakeLLMClient(
        responses=[
            "import sys; print('out'); print('my error', file=sys.stderr); sys.exit(1)"
        ]
    )
    tool = CodeExecuteTool(config=cfg, llm_client=llm)
    result = tool.execute({"task": "failing code"}, {})
    assert result.success is False
    assert "my error" in result.metadata["stderr"]
    assert "generated_code_path" in result.metadata
    # Error should contain stderr
    assert "my error" in (result.error or "")
    # Cleanup
    Path(result.metadata["generated_code_path"]).unlink()
    Path(cfg.execution.temp_dir).rmdir()


def test_task_mode_blocked_code_still_rejected() -> None:
    cfg = FakeConfig()
    cfg.execution.temp_dir = tempfile.mkdtemp()
    llm = FakeLLMClient(responses=["import subprocess\nprint('bad')"])
    tool = CodeExecuteTool(config=cfg, llm_client=llm)
    result = tool.execute({"task": "bad"}, {})
    assert result.success is False
    assert result.metadata.get("violation") == "SANDBOX_VIOLATION"
    assert "generated_code_path" in result.metadata
    # Cleanup file still created (generated code saved before sandbox check)
    Path(result.metadata["generated_code_path"]).unlink(missing_ok=True)
    Path(cfg.execution.temp_dir).rmdir()


def test_task_mode_uses_context_llm_when_constructor_none() -> None:
    cfg = FakeConfig()
    cfg.execution.temp_dir = tempfile.mkdtemp()
    llm = FakeLLMClient(responses=["print('ctx')"])
    tool = CodeExecuteTool(config=cfg, llm_client=None)
    result = tool.execute({"task": "ctx test"}, {"llm_client": llm})
    assert result.success is True
    assert "ctx" in result.output
    Path(result.metadata["generated_code_path"]).unlink()
    Path(cfg.execution.temp_dir).rmdir()


def test_task_mode_with_llm_response_object() -> None:
    from tests.test_tools.doubles import LLMResponse

    cfg = FakeConfig()
    cfg.execution.temp_dir = tempfile.mkdtemp()
    llm = FakeLLMClient(responses=[LLMResponse(text="print('resp obj')")])
    tool = CodeExecuteTool(config=cfg, llm_client=llm)
    result = tool.execute({"task": "obj"}, {})
    assert result.success is True
    assert "resp obj" in result.output
    Path(result.metadata["generated_code_path"]).unlink()
    Path(cfg.execution.temp_dir).rmdir()


def test_task_mode_timeout_includes_generated_path() -> None:
    cfg = FakeConfig()
    cfg.execution.temp_dir = tempfile.mkdtemp()
    cfg.security.code_timeout = 1
    llm = FakeLLMClient(responses=["import time; time.sleep(2)"])
    tool = CodeExecuteTool(config=cfg, llm_client=llm)
    result = tool.execute({"task": "sleep"}, {})
    assert result.success is False
    assert result.metadata.get("violation") == "SANDBOX_TIMEOUT"
    assert "generated_code_path" in result.metadata
    Path(result.metadata["generated_code_path"]).unlink(missing_ok=True)
    Path(cfg.execution.temp_dir).rmdir()
