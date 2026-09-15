"""Tests for default_tools bundle (5.3) and capability audit (5.4).

Spec: SPEC-002 §2, §4
"""

from __future__ import annotations

from agent_harness.tools import default_tools
from agent_harness.tools.base import ToolRegistry
from tests.test_tools.doubles import FakeConfig, FakeLLMClient


def test_default_tools_returns_ten() -> None:
    cfg = FakeConfig()
    llm = FakeLLMClient()
    tools = default_tools(config=cfg, llm_client=llm)
    assert len(tools) == 10
    names = [t.name for t in tools]
    assert len(set(names)) == 10  # unique
    # Check all expected names present
    expected = {
        "web_search",
        "web_scrape",
        "code_execute",
        "file_read",
        "file_write",
        "llm_extract",
        "llm_synthesize",
        "pdf_export",
        "csv_process",
        "shell_command",
    }
    assert set(names) == expected


def test_default_tools_capabilities() -> None:
    tools = default_tools()
    by_name = {t.name: t for t in tools}
    assert set(by_name["web_search"].capabilities) == {"search", "web", "research"}
    assert set(by_name["web_scrape"].capabilities) == {"web", "scrape", "extract"}
    assert set(by_name["code_execute"].capabilities) == {"code", "execution", "compute"}
    assert set(by_name["file_read"].capabilities) == {"file", "read", "io"}
    assert set(by_name["file_write"].capabilities) == {"file", "write", "io"}
    assert set(by_name["llm_extract"].capabilities) == {"llm", "extract", "transform"}
    assert set(by_name["llm_synthesize"].capabilities) == {
        "llm",
        "synthesize",
        "generate",
    }
    assert set(by_name["pdf_export"].capabilities) == {"export", "pdf", "document"}
    assert set(by_name["csv_process"].capabilities) == {"csv", "data", "transform"}
    assert set(by_name["shell_command"].capabilities) == {
        "shell",
        "system",
        "execution",
    }
    # Descriptions <=300
    for t in tools:
        assert len(t.description) <= 300
        assert len(t.name) <= 40


def test_default_tools_llm_injection() -> None:
    llm = FakeLLMClient(responses=["hi"])
    tools = default_tools(llm_client=llm)
    # Code execute, llm_extract, llm_synthesize should have llm_client
    by_name = {t.name: t for t in tools}
    # They store llm_client in _llm_client or similar; we can test via execute
    # For llm_extract, without explicit llm, it should succeed via injected client
    extract = by_name["llm_extract"]
    result = extract.execute({"input_text": "t", "instruction": "i"}, {})
    assert result.success is True
    assert result.output == "hi"

    # For llm_synthesize
    llm2 = FakeLLMClient(responses=["synth"])
    tools2 = default_tools(llm_client=llm2)
    synth = {t.name: t for t in tools2}["llm_synthesize"]
    result2 = synth.execute({"instruction": "do"}, {})
    assert result2.success is True
    assert result2.output == "synth"


def test_default_tools_registry_and_find_by_capability() -> None:
    tools = default_tools()
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    assert len(reg.names()) == 10
    # Find by capability
    llm_tools = reg.find_by_capability("llm")
    assert len(llm_tools) == 2
    assert {t.name for t in llm_tools} == {"llm_extract", "llm_synthesize"}

    file_tools = reg.find_by_capability("file")
    assert len(file_tools) == 2
    assert {t.name for t in file_tools} == {"file_read", "file_write"}

    search_tools = reg.find_by_capability("search")
    assert len(search_tools) == 1
    assert search_tools[0].name == "web_search"

    # Capability not present returns empty
    assert reg.find_by_capability("nonexistent") == []

    # list_tools ordering is insertion order
    listed = reg.list_tools()
    assert [d["name"] for d in listed] == [t.name for t in tools]


def test_default_tools_with_none_config() -> None:
    tools = default_tools(config=None, llm_client=None)
    assert len(tools) == 10
    # Should not raise


def test_default_tools_duck_typed_config() -> None:
    # Pass dict config
    cfg = {
        "execution": {"output_dir": "/tmp", "temp_dir": "/tmp"},
        "security": {"allow_shell": False},
    }
    tools = default_tools(config=cfg)
    assert len(tools) == 10
