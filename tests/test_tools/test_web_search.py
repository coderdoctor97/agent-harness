"""Tests for web_search tool contract.

Spec: SPEC-002 §3.1
"""

from __future__ import annotations

from typing import Any

import requests

from agent_harness.tools.web_search import WebSearchTool, _classify_search_error
from tests.test_tools.doubles import FakeConfig


class FakeSuccessProvider:
    name = "fake_success"

    def __init__(self, results: list[dict[str, str]]) -> None:
        self.results = results
        self.calls: list[tuple[str, int, Any]] = []

    def search(
        self, query: str, num_results: int, region: str | None = None
    ) -> list[dict[str, str]]:
        self.calls.append((query, num_results, region))
        return self.results[:num_results]


class FakeEmptyProvider:
    name = "fake_empty"

    def search(
        self, query: str, num_results: int, region: str | None = None
    ) -> list[dict[str, str]]:
        return []


class FakeFailingProvider:
    name = "fake_failing"

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def search(
        self, query: str, num_results: int, region: str | None = None
    ) -> list[dict[str, str]]:
        raise self.exc


def test_web_search_capabilities_and_description() -> None:
    tool = WebSearchTool()
    assert tool.name == "web_search"
    assert set(tool.capabilities) == {"search", "web", "research"}
    assert len(tool.description) <= 300
    # description should mention inputs/outputs
    assert "query" in tool.description.lower()
    assert "title" in tool.description.lower() or "snippet" in tool.description.lower()


def test_web_search_validate_input() -> None:
    tool = WebSearchTool()
    assert tool.validate_input({})[0] is False
    assert tool.validate_input({"query": ""})[0] is False
    assert tool.validate_input({"query": "hello"})[0] is True
    assert tool.validate_input({"query": "hi", "num_results": 0})[0] is False
    assert tool.validate_input({"query": "hi", "num_results": 5})[0] is True
    assert tool.validate_input({"query": "hi", "num_results": "5"})[0] is False  # type: int required
    assert tool.validate_input({"query": "hi", "region": 123})[0] is False
    assert tool.validate_input({"query": "hi", "region": "us-en"})[0] is True


def test_web_search_empty_results_success_with_flag() -> None:
    cfg = FakeConfig()
    tool = WebSearchTool(config=cfg, provider=FakeEmptyProvider())
    result = tool.execute({"query": "nonexistent xyz"}, {})
    assert result.success is True
    assert result.output == []
    assert result.metadata.get("no_results") is True
    assert result.metadata["tool_name"] == "web_search"
    assert "duration_ms" in result.metadata
    assert result.metadata["query"] == "nonexistent xyz"


def test_web_search_success_normalizes_output() -> None:
    fake_results = [
        {"title": "T1", "url": "http://a.com", "snippet": "S1"},
        {"title": "T2", "url": "http://b.com", "snippet": "S2"},
    ]
    provider = FakeSuccessProvider(fake_results)
    tool = WebSearchTool(config=FakeConfig(), provider=provider)
    result = tool.execute({"query": "test", "num_results": 1}, {})
    assert result.success is True
    assert len(result.output) == 1
    assert result.output[0]["title"] == "T1"
    assert result.metadata["provider"] == "fake_success"
    assert result.metadata["query"] == "test"
    # deterministic ordering as provided
    assert provider.calls[0] == ("test", 1, None)


def test_web_search_default_num_results_from_config() -> None:
    cfg = FakeConfig()
    cfg.search.max_results = 3
    provider = FakeSuccessProvider(
        [{"title": str(i), "url": "u", "snippet": "s"} for i in range(10)]
    )
    tool = WebSearchTool(config=cfg, provider=provider)
    result = tool.execute({"query": "hi"}, {})
    assert len(result.output) == 3  # defaults to 3


def test_web_search_region_passthrough() -> None:
    provider = FakeSuccessProvider([{"title": "t", "url": "u", "snippet": "s"}])
    tool = WebSearchTool(provider=provider)
    tool.execute({"query": "q", "region": "de-de"}, {})
    assert provider.calls[0][2] == "de-de"


def test_web_search_retryable_on_timeout() -> None:
    exc = requests.exceptions.Timeout("timed out")
    tool = WebSearchTool(provider=FakeFailingProvider(exc))
    result = tool.execute({"query": "q"}, {})
    assert result.success is False
    assert result.metadata.get("retryable") is True
    assert "timeout" in result.error.lower()  # type: ignore[union-attr]


def test_web_search_missing_key_not_retryable() -> None:
    # Using real provider factory path: missing key via config
    cfg = FakeConfig()
    cfg.search.provider = "serpapi"
    cfg.search.api_key_env = "NONEXISTENT_ENV_12345"
    tool = WebSearchTool(config=cfg)
    result = tool.execute({"query": "hello"}, {})
    assert result.success is False
    assert result.metadata.get("retryable") is False
    assert "missing api key" in result.error.lower()  # type: ignore[union-attr]


def test_web_search_classify_helper() -> None:
    # Directly test classification
    msg, retry = _classify_search_error(requests.exceptions.Timeout("t"), "bing")
    assert retry is True
    assert "timeout" in msg.lower()
    # HTTP 429 retryable
    err = requests.exceptions.HTTPError("429 Client Error")
    err.response = type("R", (), {"status_code": 429})()  # type: ignore[attr-defined]
    _msg2, retry2 = _classify_search_error(err, "bing")
    assert retry2 is True
    # HTTP 404 not retryable
    err2 = requests.exceptions.HTTPError("404 Not Found")
    err2.response = type("R2", (), {"status_code": 404})()  # type: ignore[attr-defined]
    _msg3, retry3 = _classify_search_error(err2, "bing")
    assert retry3 is False


def test_web_search_invalid_input_returns_tool_input_invalid() -> None:
    tool = WebSearchTool(provider=FakeSuccessProvider([]))
    result = tool.execute({"query": ""}, {})
    assert result.success is False
    assert "TOOL_INPUT_INVALID" in result.error  # type: ignore[union-attr]
    assert result.metadata["retryable"] is False
