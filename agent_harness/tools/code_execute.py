"""Code execution sandbox.

Spec: SPEC-002 §3.3, SPEC-006 §4 S3/S4/S5/S6/S8
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# S1 blocked patterns (verbatim list extended from vision §9.1) — used in 3.2
BLOCKED_PATTERNS: list[str] = [
    "import os; os.system",
    "subprocess",
    "shutil.rmtree",
    "__import__('os').system",
    "eval(",
    "exec(",
    "open('/etc",
    "open('C:\\\\Windows",
    "os.environ",
    "socket.",
    "ctypes",
    "__subclasses__",
]

# S2/S7 blocked imports and calls
BLOCKED_IMPORTS: set[str] = {
    "subprocess",
    "ctypes",
    "socket",
    "shutil",
    "multiprocessing",
    "importlib",
}

NETWORK_MODULES: set[str] = {
    "socket",
    "urllib.request",
    "http.client",
    "requests",
    "httpx",
    "urllib",
    "http",
}

BLOCKED_CALLS: set[str] = {"eval", "exec", "compile", "__import__"}

DUNDER_ATTRS: set[str] = {
    "__globals__",
    "__subclasses__",
    "__builtins__",
    "__dict__",
    "__class__",
}


def _check_blocked_patterns(code: str) -> str | None:
    """S1 — check verbatim blocked patterns.

    Returns matched pattern or None.
    Spec: SPEC-006 §4 S1
    """
    for pat in BLOCKED_PATTERNS:
        if pat in code:
            return pat
    return None


def _check_ast(code: str, network_in_code: bool = False) -> str | None:
    """S2/S7 — AST analysis for blocked imports/calls/dunder.

    Returns violation description or None.
    Spec: SPEC-006 §4 S2/S7
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # Syntax errors are not sandbox violations; let execution handle
        return None

    for node in ast.walk(tree):
        # Check imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                full = alias.name
                if mod in BLOCKED_IMPORTS or full in BLOCKED_IMPORTS:
                    return f"Blocked import: {alias.name}"
                if not network_in_code and (
                    full in NETWORK_MODULES or mod in NETWORK_MODULES
                ):
                    return f"Blocked network import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            top = mod.split(".")[0] if mod else ""
            if top in BLOCKED_IMPORTS or mod in BLOCKED_IMPORTS:
                return f"Blocked import: {mod}"
            if not network_in_code and (
                mod in NETWORK_MODULES or top in NETWORK_MODULES
            ):
                return f"Blocked network import: {mod}"
        # Check calls to eval/exec/compile/__import__
        elif isinstance(node, ast.Call):
            # Direct calls like eval(...)
            if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
                return f"Blocked call: {node.func.id}"
            # Also check attribute calls? Not needed per spec
        # Check dunder attribute access
        elif isinstance(node, ast.Attribute):
            if node.attr in DUNDER_ATTRS:
                return f"Blocked dunder access: {node.attr}"
            # Also check for any dunder-like attr
            if node.attr.startswith("__") and node.attr.endswith("__"):
                # Be conservative: block any dunder if it's in blocked set, already handled
                # So only block the specific ones above; but spec says dunder attributes
                # We'll block any __*__ that is not normal? Safer to only block listed.
                pass
        # Also check for Subscript with dunder? Not needed
    return None


def check_code_safety(code: str, *, network_in_code: bool = False) -> tuple[bool, str]:
    """Combine S1/S2/S7 checks.

    Returns (is_safe, violation_message). If not safe, message describes violation.
    """
    pat = _check_blocked_patterns(code)
    if pat is not None:
        return False, f"Blocked pattern detected: {pat}"
    ast_violation = _check_ast(code, network_in_code=network_in_code)
    if ast_violation is not None:
        return False, f"Blocked AST construct: {ast_violation}"
    return True, ""


def _scrubbed_env() -> dict[str, str]:
    """Return child env limited to allowed keys per S4.

    Spec: SPEC-006 §4 S4 — only PATH, PYTHONPATH=\"\", LANG, TMPDIR, PYTHONIOENCODING.
    """
    env: dict[str, str] = {}
    # PATH — preserve if present
    if "PATH" in os.environ:
        env["PATH"] = os.environ["PATH"]
    # PYTHONPATH forced empty
    env["PYTHONPATH"] = ""
    # LANG if present
    if "LANG" in os.environ:
        env["LANG"] = os.environ["LANG"]
    # TMPDIR — use tempfile.gettempdir() or env TMPDIR
    env["TMPDIR"] = tempfile.gettempdir()
    if "TMPDIR" in os.environ:
        # Use system tmpdir, not inherited user value? Spec says TMPDIR allowed, so pass through
        # But we set to tempfile.gettempdir() for determinism; also allow override if present
        env["TMPDIR"] = os.environ.get("TMPDIR", env["TMPDIR"])
    # PYTHONIOENCODING forced utf-8
    env["PYTHONIOENCODING"] = "utf-8"
    # Also allow LC_ALL? Not in spec, so not included.
    return env


def _truncate_bytes(data: str, max_bytes: int) -> tuple[str, bool]:
    enc = data.encode("utf-8")
    if len(enc) <= max_bytes:
        return data, False
    marker = "...[truncated]"
    mb = marker.encode("utf-8")
    allowed = max_bytes - len(mb)
    allowed = max(allowed, 0)
    truncated = enc[:allowed].decode("utf-8", errors="ignore") + marker
    return truncated, True


def _get_config_value(config: Any, path: str, default: Any) -> Any:
    cur: Any = config
    for part in path.split("."):
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(part, default)
        else:
            cur = getattr(cur, part, default)
        if cur is default:
            return default
    return cur


def _resolve_code_settings(config: Any) -> tuple[bool, int, int, bool, str]:
    sandbox_code: bool = bool(_get_config_value(config, "security.sandbox_code", True))
    code_timeout: int = int(_get_config_value(config, "security.code_timeout", 30))
    max_output: int = int(
        _get_config_value(config, "security.max_output_bytes", 1_000_000)
    )
    network_in_code: bool = bool(
        _get_config_value(config, "security.network_in_code", False)
    )
    temp_dir: str = str(
        _get_config_value(config, "execution.temp_dir", tempfile.gettempdir())
    )
    return sandbox_code, code_timeout, max_output, network_in_code, temp_dir


def execute_code_sandboxed(
    code: str,
    *,
    timeout: int = 30,
    max_output_bytes: int = 1_000_000,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Execute code in isolated subprocess per S3/S4/S5/S6/S8.

    Returns dict with stdout, stderr, returncode, timed_out, truncated.
    """
    scrub_env = env if env is not None else _scrubbed_env()
    tmp_path: Path | None = None
    start = time.monotonic()
    try:
        # Write temp script
        fd, tmp_name = tempfile.mkstemp(suffix=".py", dir=tempfile.gettempdir())
        tmp_path = Path(tmp_name)
        # Close fd and write
        os.close(fd)
        tmp_path.write_text(code, encoding="utf-8")

        # Build command: [sys.executable, tmp_path]
        cmd = [sys.executable, str(tmp_path)]
        # Platform-specific process group handling
        popen_kwargs: dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "env": scrub_env,
            "cwd": tempfile.gettempdir(),
            "shell": False,
        }
        # On Unix, create new session for group kill
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True

        try:
            result = subprocess.run(cmd, timeout=timeout, check=False, **popen_kwargs)
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            returncode = result.returncode
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            # Kill process group if needed (run already tried to kill)
            # Ensure we capture partial output
            stdout = ""
            stderr = f"Code execution timed out ({timeout}s)"
            if exc.stdout:
                # TimeoutExpired may have stdout/stderr as bytes or str depending on text mode
                try:
                    stdout = (
                        exc.stdout.decode("utf-8", errors="ignore")
                        if isinstance(exc.stdout, bytes)
                        else str(exc.stdout)
                    )
                except Exception:  # noqa: BLE001
                    stdout = ""
            if exc.stderr:
                try:
                    stderr_part = (
                        exc.stderr.decode("utf-8", errors="ignore")
                        if isinstance(exc.stderr, bytes)
                        else str(exc.stderr)
                    )
                    stderr = stderr_part + "\n" + stderr
                except Exception:  # noqa: BLE001, S110
                    pass
            returncode = -1
            timed_out = True
            # Try to kill process group if on Unix
            # The subprocess.run already killed, but for nested children we attempt
            # No extra handling needed for now
            _ = time.monotonic() - start

        # Apply output cap S6
        truncated = False
        stdout, t1 = _truncate_bytes(stdout, max_output_bytes)
        stderr_trunc, t2 = _truncate_bytes(stderr, max_output_bytes)
        if t1 or t2:
            truncated = True
        stderr = stderr_trunc

        return {
            "stdout": stdout,
            "stderr": stderr,
            "returncode": returncode,
            "timed_out": timed_out,
            "truncated": truncated,
            "duration_ms": int((time.monotonic() - start) * 1000),
        }
    finally:
        # S8 guaranteed cleanup
        if tmp_path is not None:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:  # noqa: BLE001, S110
                pass


# ── Tool surface (SPEC-002 §3.3) ─────────────────────────────────────────────

from agent_harness.tools.base import BaseTool, ToolResult


class CodeExecuteTool(BaseTool):
    """Code execution tool with sandbox enforcement.

    Spec: SPEC-002 §3.3, SPEC-006 §4
    """

    def __init__(self, config: Any = None, llm_client: Any = None) -> None:
        self._config = config
        self._llm_client = llm_client

    @property
    def name(self) -> str:
        return "code_execute"

    @property
    def description(self) -> str:
        return (
            "Executes Python code. Input: {code: str (python code) OR task: str (LLM generates code), "
            "language: str (default python)}. Output: stdout. "
            "Stderr/returncode in metadata. Sandboxed with timeout and pattern checks."
        )

    @property
    def capabilities(self) -> list[str]:
        return ["code", "execution", "compute"]

    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str]:
        has_code = "code" in input_data
        has_task = "task" in input_data
        if has_code and has_task:
            return False, "Provide exactly one of 'code' or 'task', not both"
        if not has_code and not has_task:
            return False, "Provide exactly one of 'code' or 'task'"
        if has_code:
            code = input_data["code"]
            if not isinstance(code, str) or not code.strip():
                return False, "'code' must be a non-empty string"
        if has_task:
            task = input_data["task"]
            if not isinstance(task, str) or not task.strip():
                return False, "'task' must be a non-empty string"
            if "language" in input_data and not isinstance(input_data["language"], str):
                return False, "'language' must be a string"
            lang = input_data.get("language", "python")
            if lang != "python":
                return False, "Only 'python' language is supported"
        return True, ""

    def execute(
        self, input_data: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        start = time.monotonic()
        # R2 validate first
        is_valid, err = self.validate_input(input_data)
        if not is_valid:
            return ToolResult(
                success=False,
                error=f"TOOL_INPUT_INVALID: {err}",
                metadata={
                    "tool_name": self.name,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                    "retryable": False,
                },
            )

        sandbox_code, code_timeout, max_output, network_in_code, temp_dir = (
            _resolve_code_settings(self._config)
        )

        # Resolve code source: either direct code or task-generated
        code_str: str | None = None
        generated_path: str | None = None

        if "code" in input_data:
            code_str = str(input_data["code"])
        else:
            # task mode — delegate to 3.4 logic; for 3.3 we handle minimal
            task = str(input_data["task"])
            language = str(input_data.get("language", "python"))
            # Task mode requires llm_client
            llm = self._llm_client
            # Fallback to context injection per SPEC-002 §3.3
            if llm is None:
                llm = context.get("llm_client") if isinstance(context, dict) else None
            if llm is None:
                return ToolResult(
                    success=False,
                    error="TOOL_EXECUTION_FAILED: llm_client required for task mode",
                    metadata={
                        "tool_name": self.name,
                        "duration_ms": int((time.monotonic() - start) * 1000),
                        "retryable": False,
                    },
                )
            # Generate code via llm (3.4 will expand, but implement basic here)
            try:
                # Prefer complete_json? For code generation we prompt for code
                prompt_messages = [
                    {
                        "role": "system",
                        "content": "You are a code generator. Return only Python code.",
                    },
                    {
                        "role": "user",
                        "content": f"Task: {task}\nLanguage: {language}\nGenerate code.",
                    },
                ]
                if hasattr(llm, "complete"):
                    resp = llm.complete(prompt_messages)
                    generated = resp.text if hasattr(resp, "text") else str(resp)
                else:
                    generated = str(task)
                # Strip fences if present
                generated = generated.strip()
                if generated.startswith("```"):
                    # Remove markdown fences
                    lines = generated.split("\n")
                    # Remove first fence line
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    # Remove last fence if present
                    if lines and lines[-1].strip().startswith("```"):
                        lines = lines[:-1]
                    generated = "\n".join(lines)
                code_str = generated
                # Save to temp_dir for inspection per spec
                try:
                    Path(temp_dir).mkdir(parents=True, exist_ok=True)
                    tmp_file = Path(tempfile.mkstemp(suffix=".py", dir=temp_dir)[1])
                    Path(tmp_file).write_text(code_str, encoding="utf-8")
                    generated_path = str(tmp_file)
                except Exception:  # noqa: BLE001
                    generated_path = None
            except Exception as exc:  # noqa: BLE001
                return ToolResult(
                    success=False,
                    error=f"LLM code generation failed: {exc}",
                    metadata={
                        "tool_name": self.name,
                        "duration_ms": int((time.monotonic() - start) * 1000),
                        "retryable": False,
                    },
                )

        assert code_str is not None  # for mypy

        # S1/S2/S7 pre-check
        is_safe, violation = check_code_safety(
            code_str, network_in_code=network_in_code
        )
        if not is_safe:
            meta_violation: dict[str, object] = {
                "tool_name": self.name,
                "duration_ms": int((time.monotonic() - start) * 1000),
                "retryable": False,
                "violation": "SANDBOX_VIOLATION",
            }
            if generated_path:
                meta_violation["generated_code_path"] = generated_path
            return ToolResult(
                success=False,
                error=violation,
                metadata=meta_violation,
            )

        # If sandbox disabled, do direct exec (documented risk)
        if not sandbox_code:
            return self._direct_execute(code_str, start, generated_path, max_output)

        # Sandboxed execution S3-S6/S8
        result = execute_code_sandboxed(
            code_str, timeout=code_timeout, max_output_bytes=max_output
        )
        duration_ms = result["duration_ms"]

        if result["timed_out"]:
            meta: dict[str, Any] = {
                "tool_name": self.name,
                "duration_ms": duration_ms,
                "retryable": False,
                "violation": "SANDBOX_TIMEOUT",
                "stderr": result["stderr"],
                "returncode": result["returncode"],
            }
            if generated_path:
                meta["generated_code_path"] = generated_path
            if result["truncated"]:
                meta["truncated"] = True
            return ToolResult(
                success=False,
                error=f"SANDBOX_TIMEOUT: Code execution timed out ({code_timeout}s)",
                metadata=meta,
            )

        stdout: str = result["stdout"]
        stderr: str = result["stderr"]
        returncode: int = result["returncode"]
        truncated: bool = result["truncated"]

        if returncode != 0:
            meta2: dict[str, Any] = {
                "tool_name": self.name,
                "duration_ms": duration_ms,
                "retryable": False,
                "stderr": stderr,
                "returncode": returncode,
            }
            if generated_path:
                meta2["generated_code_path"] = generated_path
            if truncated:
                meta2["truncated"] = True
            # Include stdout as output even on failure per spec? Spec says stderr/returncode in metadata, stdout as output
            # But failure should have output as stdout? We'll return stdout as output with success False
            return ToolResult(
                success=False,
                output=stdout,
                error=stderr or f"Code exited with {returncode}",
                metadata=meta2,
            )

        meta3: dict[str, Any] = {
            "tool_name": self.name,
            "duration_ms": duration_ms,
            "stderr": stderr,
            "returncode": returncode,
        }
        if generated_path:
            meta3["generated_code_path"] = generated_path
        if truncated:
            meta3["truncated"] = True
        return ToolResult(success=True, output=stdout, metadata=meta3)

    def _direct_execute(
        self, code: str, start: float, generated_path: str | None, max_output: int
    ) -> ToolResult:
        """Direct exec when sandbox disabled (documented risk)."""
        import contextlib
        import io

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        try:
            with (
                contextlib.redirect_stdout(stdout_buf),
                contextlib.redirect_stderr(stderr_buf),
            ):
                exec(code, {"__builtins__": __builtins__}, {})  # noqa: S102
            stdout = stdout_buf.getvalue()
            stderr = stderr_buf.getvalue()
            # Truncate if needed
            trunc = False
            if len(stdout.encode("utf-8")) > max_output:
                stdout, _ = _truncate_bytes(stdout, max_output)
                trunc = True
            if len(stderr.encode("utf-8")) > max_output:
                stderr, _ = _truncate_bytes(stderr, max_output)
                trunc = True
            meta: dict[str, Any] = {
                "tool_name": self.name,
                "duration_ms": int((time.monotonic() - start) * 1000),
                "stderr": stderr,
                "returncode": 0,
            }
            if generated_path:
                meta["generated_code_path"] = generated_path
            if trunc:
                meta["truncated"] = True
            return ToolResult(success=True, output=stdout, metadata=meta)
        except Exception as exc:  # noqa: BLE001
            stdout = stdout_buf.getvalue()
            stderr = stderr_buf.getvalue() + f"\n{exc}"
            meta2: dict[str, Any] = {
                "tool_name": self.name,
                "duration_ms": int((time.monotonic() - start) * 1000),
                "stderr": stderr,
                "returncode": 1,
                "retryable": False,
            }
            if generated_path:
                meta2["generated_code_path"] = generated_path
            return ToolResult(
                success=False, output=stdout, error=str(exc), metadata=meta2
            )
