"""Tests for ToolRegistry G1–G5.

Spec: SPEC-002 §2
"""

from __future__ import annotations

import warnings

import pytest

from agent_harness.tools.base import BaseTool, ToolRegistry, ToolResult


class DummyTool(BaseTool):
    def __init__(self, tool_name: str, caps: list[str] | None = None) -> None:
        self._name = tool_name
        self._caps = caps or []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"dummy {self._name} tool"

    @property
    def capabilities(self) -> list[str]:
        return self._caps

    def execute(self, input_data: dict, context: dict) -> ToolResult:
        return ToolResult(success=True, output="ok", metadata={})


def test_registry_g1_rejects_non_basetools() -> None:
    reg = ToolRegistry()
    with pytest.raises(TypeError):
        reg.register(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        reg.register("not a tool")  # type: ignore[arg-type]


def test_registry_register_and_get() -> None:
    reg = ToolRegistry()
    t = DummyTool("alpha")
    reg.register(t)
    assert reg.get("alpha") is t
    assert reg.get("missing") is None


def test_registry_g2_overwrite_warns() -> None:
    reg = ToolRegistry()
    t1 = DummyTool("dup")
    t2 = DummyTool("dup")
    reg.register(t1)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        reg.register(t2)
        assert len(w) == 1
        assert issubclass(w[0].category, UserWarning)
        assert "already registered" in str(w[0].message)
    assert reg.get("dup") is t2


def test_registry_g3_list_tools_insertion_order() -> None:
    reg = ToolRegistry()
    names = ["zeta", "alpha", "middle"]
    for n in names:
        reg.register(DummyTool(n))
    listed = reg.list_tools()
    assert [d["name"] for d in listed] == names
    for d in listed:
        assert "description" in d
        assert "capabilities" in d


def test_registry_find_by_capability() -> None:
    reg = ToolRegistry()
    reg.register(DummyTool("a", caps=["search", "web"]))
    reg.register(DummyTool("b", caps=["code"]))
    reg.register(DummyTool("c", caps=["search"]))
    found = reg.find_by_capability("search")
    assert {t.name for t in found} == {"a", "c"}
    assert reg.find_by_capability("missing") == []


def test_registry_g5_deregister_noop() -> None:
    reg = ToolRegistry()
    # no-op on unknown
    reg.deregister("ghost")
    t = DummyTool("to_remove")
    reg.register(t)
    assert reg.get("to_remove") is t
    reg.deregister("to_remove")
    assert reg.get("to_remove") is None
    # again no-op
    reg.deregister("to_remove")


def test_registry_names_sorted() -> None:
    reg = ToolRegistry()
    for n in ["charlie", "bravo", "alpha"]:
        reg.register(DummyTool(n))
    assert reg.names() == ["alpha", "bravo", "charlie"]


def test_registry_list_tools_shape_matches_spec() -> None:
    reg = ToolRegistry()
    t = DummyTool("my_tool", caps=["x", "y"])
    reg.register(t)
    lst = reg.list_tools()
    assert len(lst) == 1
    entry = lst[0]
    assert set(entry.keys()) == {"name", "description", "capabilities"}
    assert entry["name"] == "my_tool"
    assert isinstance(entry["capabilities"], list)
