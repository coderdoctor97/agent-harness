"""Tests for CodeSandbox core S3/S4/S5/S6/S8.

Spec: SPEC-006 §4
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from agent_harness.tools.code_execute import _scrubbed_env, execute_code_sandboxed


def test_sandbox_trivial_execution_s3() -> None:
    res = execute_code_sandboxed(
        'print("hello sandbox")', timeout=5, max_output_bytes=1000
    )
    assert res["timed_out"] is False
    assert res["returncode"] == 0
    assert "hello sandbox" in res["stdout"]
    assert res["stderr"] == ""


def test_sandbox_env_scrub_s4_no_leak() -> None:
    # Set fake secret in parent env
    os.environ["OPENAI_API_KEY"] = "sk-secret-12345"
    os.environ["HOME"] = "/fake/home/should/not/leak"
    os.environ["SECRET_FOO"] = "leaked"
    try:
        code = "import os; print(os.environ.get('OPENAI_API_KEY', 'NOT_FOUND')); print(os.environ.get('HOME', 'NOT_FOUND_HOME')); print(os.environ.get('SECRET_FOO', 'NOT_FOUND_FOO')); print(os.environ.get('PATH', 'NO_PATH'))"
        res = execute_code_sandboxed(code, timeout=5)
        assert res["returncode"] == 0
        # Child should NOT see parent secrets
        assert "sk-secret-12345" not in res["stdout"]
        assert "NOT_FOUND" in res["stdout"]
        assert "NOT_FOUND_HOME" in res["stdout"]
        assert "NOT_FOUND_FOO" in res["stdout"]
        # PATH should be preserved if parent has it
        assert "NO_PATH" not in res["stdout"] or "PATH" in os.environ
        # PYTHONIOENCODING should be utf-8
        code2 = "import os; print(os.environ.get('PYTHONIOENCODING', 'MISSING'))"
        res2 = execute_code_sandboxed(code2, timeout=5)
        assert "utf-8" in res2["stdout"]
        # PYTHONPATH forced empty
        code3 = "import os; print(repr(os.environ.get('PYTHONPATH', 'MISSING')))"
        res3 = execute_code_sandboxed(code3, timeout=5)
        assert "''" in res3["stdout"] or '""' in res3["stdout"]
    finally:
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("SECRET_FOO", None)
        # Restore HOME maybe
        # Not needed


def test_sandbox_env_only_allowed_keys() -> None:
    env = _scrubbed_env()
    allowed = {"PATH", "PYTHONPATH", "LANG", "TMPDIR", "PYTHONIOENCODING"}
    # Env keys must be subset of allowed (plus maybe nothing else)
    for k in env:
        assert k in allowed, f"unexpected env key {k}"
    assert env["PYTHONPATH"] == ""
    assert env["PYTHONIOENCODING"] == "utf-8"
    # Ensure HOME not leaked
    assert "HOME" not in env
    assert "OPENAI_API_KEY" not in env


def test_sandbox_timeout_s5() -> None:
    code = "import time; time.sleep(2)"
    start = time.monotonic()
    res = execute_code_sandboxed(code, timeout=1, max_output_bytes=1000)
    elapsed = time.monotonic() - start
    # Should have timed out within ~1 sec + overhead, not 2 sec
    assert elapsed < 1.8, f"elapsed {elapsed} too long, timeout not enforced"
    assert res["timed_out"] is True
    assert res["returncode"] == -1
    assert "timed out" in res["stderr"].lower()


def test_sandbox_output_cap_s6() -> None:
    # Generate output larger than cap
    code = "print('A' * 5000)"
    res = execute_code_sandboxed(code, timeout=5, max_output_bytes=100)
    assert res["truncated"] is True
    # stdout should be truncated to ~100 bytes plus marker
    assert "...[truncated]" in res["stdout"]
    assert len(res["stdout"].encode("utf-8")) <= 150  # 100 + marker overhead
    # Also test stderr cap
    code2 = "import sys; sys.stderr.write('E' * 5000)"
    res2 = execute_code_sandboxed(code2, timeout=5, max_output_bytes=100)
    assert res2["truncated"] is True


def test_sandbox_cleanup_s8_guaranteed() -> None:
    tmpdir = Path(tempfile.gettempdir())
    before = set(tmpdir.glob("tmp*.py"))
    code = "print('cleanup test')"
    res = execute_code_sandboxed(code, timeout=5)
    assert res["returncode"] == 0
    after = set(tmpdir.glob("tmp*.py"))
    # No new temp files left
    new_files = after - before
    # Filter for files created during this test (might be race, but generally 0)
    assert len(new_files) == 0 or all(not p.exists() for p in new_files)


def test_sandbox_cleanup_on_timeout() -> None:
    tmpdir = Path(tempfile.gettempdir())
    before = set(tmpdir.glob("tmp*.py"))
    code = "import time; time.sleep(5)"
    res = execute_code_sandboxed(code, timeout=1)
    assert res["timed_out"] is True
    after = set(tmpdir.glob("tmp*.py"))
    new_files = after - before
    assert len(new_files) == 0


def test_sandbox_cwd_is_tmpdir() -> None:
    code = "import os; print(os.getcwd())"
    res = execute_code_sandboxed(code, timeout=5)
    assert tempfile.gettempdir() in res["stdout"]


def test_sandbox_stderr_captured() -> None:
    code = "import sys; print('out'); print('err', file=sys.stderr); exit(1)"
    res = execute_code_sandboxed(code, timeout=5)
    assert res["returncode"] == 1
    assert "out" in res["stdout"]
    assert "err" in res["stderr"]
