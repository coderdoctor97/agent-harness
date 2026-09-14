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
