"""Tests for static analysis layers S1/S2/S7.

Spec: SPEC-006 §4
"""

from __future__ import annotations

from agent_harness.tools.code_execute import (
    BLOCKED_PATTERNS,
    _check_ast,
    _check_blocked_patterns,
    check_code_safety,
)


def test_s1_every_blocked_pattern_rejected() -> None:
    for pat in BLOCKED_PATTERNS:
        code = f"x = 1\n{pat}\nprint(x)"
        # For patterns that are substrings, ensure they are caught even when embedded
        # Some patterns like \"eval(\" need to appear exactly
        # Use the pattern itself as code snippet
        found = _check_blocked_patterns(pat)
        assert found == pat, f"Pattern {pat!r} not detected via S1"
        is_safe, msg = check_code_safety(code)
        assert is_safe is False
        assert "Blocked pattern" in msg or "Blocked" in msg
        assert pat in msg or pat.split()[0] in msg


def test_s1_substrings_caught() -> None:
    assert _check_blocked_patterns("import subprocess") == "subprocess"
    assert _check_blocked_patterns("x = eval('2+2')") == "eval("
    assert _check_blocked_patterns("code = open('/etc/passwd').read()") == "open('/etc"
    assert _check_blocked_patterns("ctypes.windll") == "ctypes"


def test_s2_blocked_imports() -> None:
    for mod in [
        "subprocess",
        "ctypes",
        "socket",
        "shutil",
        "multiprocessing",
        "importlib",
    ]:
        code = f"import {mod}"
        violation = _check_ast(code)
        assert violation is not None, f"Should block import {mod}"
        assert "Blocked import" in violation
        # Also test from import
        code2 = f"from {mod} import something"
        violation2 = _check_ast(code2)
        assert violation2 is not None


def test_s2_blocked_calls() -> None:
    for call in ["eval", "exec", "compile", "__import__"]:
        code = f"{call}('1+1')"
        violation = _check_ast(code)
        assert violation is not None, f"Should block call {call}"
        assert "Blocked call" in violation


def test_s2_dunder_access() -> None:
    for attr in ["__globals__", "__subclasses__", "__builtins__"]:
        code = f"print(obj.{attr})"
        violation = _check_ast(code)
        assert violation is not None, f"Should block dunder {attr}"
        assert "Blocked dunder" in violation


def test_s7_network_blocked_when_disabled() -> None:
    for mod in ["socket", "urllib.request", "http.client", "requests", "httpx"]:
        code = f"import {mod}"
        violation = _check_ast(code, network_in_code=False)
        assert violation is not None, f"Should block network import {mod} when disabled"
    # Also test top-level urllib
    assert _check_ast("import urllib", network_in_code=False) is not None


def test_s7_network_allowed_when_enabled() -> None:
    for mod in ["socket", "urllib.request", "http.client", "requests", "httpx"]:
        code = f"import {mod}"
        violation = _check_ast(code, network_in_code=True)
        # When network enabled, only blocked if also in BLOCKED_IMPORTS (socket is)
        # socket is in both lists, so it will still be blocked as blocked import even when network allowed
        # For other pure network modules like requests, httpx, they should be allowed
        if mod == "socket":
            assert violation is not None  # still blocked as blocked import
        else:
            # urllib.request etc not in BLOCKED_IMPORTS, so should be allowed when network enabled
            # But our logic blocks them only when network_in_code False, so should be None
            assert violation is None, (
                f"{mod} should be allowed when network enabled, got {violation}"
            )


def test_benign_code_passes() -> None:
    benign_samples = [
        "for i in range(10):\n    print(i)",
        "import math\nprint(math.sqrt(16))",
        "import json\nprint(json.dumps({'a': 1}))",
        "import csv\nprint(csv.__name__)",
        "x = [1,2,3]\ny = sorted(x)\nprint(y)",
        "def foo(n):\n    return n*2\nprint(foo(3))",
        "import pathlib\nprint(pathlib.Path('/tmp'))",
        "import os\nprint(os.path.join('a', 'b'))",  # os import itself not blocked unless os.environ or os.system?
    ]
    for code in benign_samples:
        # S1 should not trigger for benign
        pat = _check_blocked_patterns(code)
        # Need to ensure benign doesn't contain blocked substring like "subprocess"
        assert pat is None, f"Benign code incorrectly flagged by S1: {code!r} -> {pat}"
        violation = _check_ast(code)
        # os import is not in blocked list, so should pass
        # But "import os" contains "os" but not blocked pattern? Blocked import list doesn't include os
        assert violation is None, (
            f"Benign code should pass AST: {code!r} -> {violation}"
        )


def test_malformed_syntax_not_flagged_as_violation() -> None:
    code = "def foo(:\n    pass"
    # Syntax error should not be considered violation, just return None
    assert _check_ast(code) is None
    is_safe, _ = check_code_safety(code)
    # Since S1 doesn't match and AST returns None, it is safe at static level (syntax error will be caught at exec)
    assert is_safe is True


def test_check_code_safety_combined() -> None:
    # S1 takes precedence
    code = "eval('1')"
    is_safe, msg = check_code_safety(code)
    assert is_safe is False
    assert "Blocked pattern" in msg or "Blocked" in msg

    # S2 violation when S1 not triggered
    code2 = "import importlib\nprint('hi')"
    # This contains "importlib" in BLOCKED_PATTERNS? No, BLOCKED_PATTERNS has "importlib"?? Let's check list: BLOCKED_PATTERNS includes "subprocess" etc but not "importlib" as separate? Actually BLOCKED_PATTERNS list includes subprocess, but importlib not in S1 list, so S1 won't catch, but S2 will
    # Ensure S1 check for "importlib" not present, so it goes to AST
    pat = _check_blocked_patterns(code2)
    if pat is None:
        violation = _check_ast(code2)
        assert violation is not None

    # Benign passes both
    is_safe2, _ = check_code_safety("print('hello')")
    assert is_safe2 is True


def test_s1_precedence_over_ast() -> None:
    # Code with both pattern and ast violation should be caught at S1 first
    code = "import subprocess\nprint('hi')"
    is_safe, msg = check_code_safety(code)
    assert is_safe is False
    # Since S1 pattern "subprocess" matches, message should mention pattern
    assert "subprocess" in msg


def test_network_flag_behavior() -> None:
    # When network_in_code False, requests should be blocked
    is_safe, msg = check_code_safety("import requests", network_in_code=False)
    assert is_safe is False
    assert "network" in msg.lower() or "Blocked" in msg
    # When True, allowed
    is_safe2, _ = check_code_safety("import requests", network_in_code=True)
    assert is_safe2 is True


def test_dunder_not_overblocked() -> None:
    # Normal attribute access should not be blocked
    code = "obj.attr\nobj.normal_method()"
    assert _check_ast(code) is None
    # Dunder not in blocked list like __name__ should not be blocked? Our list includes only specific dunders
    # Our implementation currently blocks only listed dunders; __name__ not listed, so should pass
    assert _check_ast("print(obj.__name__)") is None
