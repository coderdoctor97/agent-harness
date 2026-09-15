"""Shell command tool with whitelist.

Spec: SPEC-002 §3.10, SPEC-006 §5
"""

from __future__ import annotations

import subprocess
import time
from typing import Any

from agent_harness.tools.base import BaseTool, ToolResult

WHITELIST_SINGLE: set[str] = {
    "ls",
    "dir",
    "cat",
    "head",
    "tail",
    "wc",
    "grep",
    "find",
    "echo",
    "date",
    "pwd",
    "python",
    "pip",
    "node",
    "npm",
    "curl",
    "wget",
}

WHITELIST_GIT: set[str] = {
    "git status",
    "git log",
    "git diff",
}

METACHARS: list[str] = [";", "&&", "||", "|", "`", "$(", ">", "<", "\n", "\r"]


def _get_allow_shell(config: Any) -> bool:
    if config is None:
        return False
    try:
        sec = getattr(config, "security", None)
        if sec is None and isinstance(config, dict):
            sec = config.get("security")
        if sec is None:
            return False
        if isinstance(sec, dict):
            return bool(sec.get("allow_shell", False))
        return bool(getattr(sec, "allow_shell", False))
    except Exception:  # noqa: BLE001
        return False


def _get_max_output_bytes(config: Any) -> int:
    default = 1_000_000
    if config is None:
        return default
    try:
        sec = getattr(config, "security", None)
        if sec is None and isinstance(config, dict):
            sec = config.get("security")
        if sec is None:
            return default
        if isinstance(sec, dict):
            val = sec.get("max_output_bytes", default)
        else:
            val = getattr(sec, "max_output_bytes", default)
        if isinstance(val, int) and val > 0:
            return val
        return default
    except Exception:  # noqa: BLE001
        return default


def _check_metachars(text: str) -> str | None:
    for m in METACHARS:
        if m in text:
            return m
    return None


def _is_whitelisted(command: str, args: list[str] | None) -> tuple[bool, str]:
    """Check whitelist per SPEC-006 §5.

    Returns (is_allowed, reason).
    """
    cmd_part = command.strip()
    if not cmd_part:
        return False, "Empty command"
    effective = cmd_part.split() + (args or [])
    if not effective:
        return False, "Empty command"
    first = effective[0]
    if first == "git":
        if len(effective) < 2:
            return False, f"Git command requires subcommand, got {command!r}"
        two = f"{effective[0]} {effective[1]}"
        if two in WHITELIST_GIT:
            return True, ""
        return False, f"Command {two!r} not in whitelist"
    # Single-token whitelist
    if first in WHITELIST_SINGLE:
        return True, ""
    return False, f"Command {first!r} not in whitelist"


class ShellCommandTool(BaseTool):
    """Shell command tool (whitelisted, disabled by default).

    Spec: SPEC-002 §3.10
    """

    def __init__(self, config: Any = None) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "shell_command"

    @property
    def description(self) -> str:
        return (
            "Runs a whitelisted shell command. Input: {command: str (required), "
            "args: list[str] (optional)}. Output: stdout. "
            "Whitelist: ls, cat, head, tail, wc, grep, find, echo, date, pwd, "
            "python, pip, node, npm, curl, wget, git status/log/diff. "
            "Disabled unless security.allow_shell=true."
        )

    @property
    def capabilities(self) -> list[str]:
        return ["shell", "system", "execution"]

    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str]:
        if "command" not in input_data:
            return False, "Missing required 'command'"
        cmd = input_data["command"]
        if not isinstance(cmd, str) or not cmd.strip():
            return False, "'command' must be a non-empty string"
        if "args" in input_data:
            args = input_data["args"]
            if not isinstance(args, list):
                return False, "'args' must be a list"
            for a in args:
                if not isinstance(a, str):
                    return False, "Each arg must be a string"
        # Note: whitelist and metachars are checked in execute for proper error code
        return True, ""

    def execute(
        self, input_data: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        start = time.monotonic()
        # Validate first
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

        # Check allow_shell
        allow = _get_allow_shell(self._config)
        if not allow:
            return ToolResult(
                success=False,
                error="TOOL_EXECUTION_FAILED: shell_command is disabled; set security.allow_shell: true to enable",
                metadata={
                    "tool_name": self.name,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                    "retryable": False,
                },
            )

        command: str = str(input_data["command"]).strip()
        args: list[str] = list(input_data.get("args", []))

        # Metachar check (command + args)
        for text, label in [(command, "command"), *[(a, f"arg {a!r}") for a in args]]:
            bad = _check_metachars(text)
            if bad is not None:
                return ToolResult(
                    success=False,
                    error=f"SANDBOX_VIOLATION: shell metacharacter {bad!r} not allowed in {label}",
                    metadata={
                        "tool_name": self.name,
                        "duration_ms": int((time.monotonic() - start) * 1000),
                        "retryable": False,
                        "violation": "SANDBOX_VIOLATION",
                    },
                )

        # Whitelist check
        allowed, reason = _is_whitelisted(command, args)
        if not allowed:
            return ToolResult(
                success=False,
                error=f"SANDBOX_VIOLATION: {reason}",
                metadata={
                    "tool_name": self.name,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                    "retryable": False,
                    "violation": "SANDBOX_VIOLATION",
                },
            )

        # Build argv: command split + args
        # For git two-word, command may be "git status" or "git" + args
        # Split command into tokens and extend with args
        argv = command.split() + args

        max_output = _get_max_output_bytes(self._config)
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
                check=False,
            )
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            returncode = result.returncode
            # Truncate per S6 (R5)
            truncated = False
            if len(stdout.encode("utf-8")) > max_output:
                marker = "...[truncated]"
                stdout = (
                    stdout.encode("utf-8")[
                        : max_output - len(marker.encode("utf-8"))
                    ].decode("utf-8", errors="ignore")
                    + marker
                )
                truncated = True
            if len(stderr.encode("utf-8")) > max_output:
                marker = "...[truncated]"
                stderr = (
                    stderr.encode("utf-8")[
                        : max_output - len(marker.encode("utf-8"))
                    ].decode("utf-8", errors="ignore")
                    + marker
                )
                truncated = True

            duration_ms = int((time.monotonic() - start) * 1000)
            if returncode != 0:
                meta: dict[str, Any] = {
                    "tool_name": self.name,
                    "duration_ms": duration_ms,
                    "stderr": stderr,
                    "returncode": returncode,
                }
                if truncated:
                    meta["truncated"] = True
                return ToolResult(
                    success=False,
                    output=stdout,
                    error=stderr or f"Command exited {returncode}",
                    metadata=meta,
                )
            meta2: dict[str, Any] = {
                "tool_name": self.name,
                "duration_ms": duration_ms,
                "stderr": stderr,
                "returncode": returncode,
            }
            if truncated:
                meta2["truncated"] = True
            # Context not used
            _ = context
            return ToolResult(success=True, output=stdout, metadata=meta2)
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                error="Code execution timed out (30s)",
                metadata={
                    "tool_name": self.name,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                    "retryable": True,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                error=f"Shell execution failed: {exc}",
                metadata={
                    "tool_name": self.name,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                    "retryable": False,
                },
            )
