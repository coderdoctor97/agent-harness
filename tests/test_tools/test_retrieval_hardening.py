"""Hardening tests for retrieval tools (2.5).

Spec: SPEC-002 §3.1 §3.2 — validation, caps, ordering, metadata.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import requests

from agent_harness.tools.web_scrape import WebScrapeTool
from agent_harness.tools.web_search import (
    BingProvider,
    GoogleProvider,
    SerpApiProvider,
    WebSearchTool,
)
from tests.test_tools.doubles import FakeConfig


def _mock_resp(json_data: dict[str, object], status: int = 200) -> Mock:
    m = Mock()
    m.json.return_value = json_data
    m.status_code = status
    m.raise_for_status.return_value = None
    if status >= 400:
        err = requests.exceptions.HTTPError(f"{status}")
        err.response = m
        m.raise_for_status.side_effect = err
    return m


@patch("agent_harness.tools.web_search.requests.get")
def test_serpapi_provider_parses(mock_get: Mock) -> None:
    mock_get.return_value = _mock_resp(
        {
            "organic_results": [
                {"title": "T1", "link": "http://a.com", "snippet": "S1"},
                {"title": "T2", "link": "http://b.com", "snippet": "S2"},
            ]
        }
    )
    p = SerpApiProvider("fake")
    res = p.search("query", 2)
    assert len(res) == 2
    assert res[0]["title"] == "T1"
    assert res[0]["url"] == "http://a.com"
    assert res[0]["snippet"] == "S1"
    # deterministic ordering as returned
    assert res[0]["title"] == "T1" and res[1]["title"] == "T2"


@patch("agent_harness.tools.web_search.requests.get")
def test_bing_provider_parses(mock_get: Mock) -> None:
    mock_get.return_value = _mock_resp(
        {
            "webPages": {
                "value": [{"name": "B1", "url": "http://bing.com", "snippet": "BS1"}]
            }
        }
    )
    p = BingProvider("fake")
    res = p.search("q", 1)
    assert res[0]["title"] == "B1"
    assert res[0]["url"] == "http://bing.com"


@patch("agent_harness.tools.web_search.requests.get")
def test_google_provider_parses(mock_get: Mock) -> None:
    mock_get.return_value = _mock_resp(
        {"items": [{"title": "G1", "link": "http://google.com", "snippet": "GS1"}]}
    )
    p = GoogleProvider("fake")
    res = p.search("q", 1)
    assert res[0]["title"] == "G1"


def test_duckduckgo_provider_parses() -> None:
    # Mock duckduckgo_search module
    import sys
    from unittest.mock import MagicMock
    mock_ddgs = MagicMock()
    mock_ddgs.text.return_value = [
        {"title": "D1", "href": "http://d.com", "body": "DS1"},
        {"title": "D2", "href": "http://d2.com", "body": "DS2"},
    ]
    mock_ddgs_instance = MagicMock()
    mock_ddgs_instance.__enter__.return_value = mock_ddgs
    mock_ddgs_instance.__exit__.return_value = False
    mock_module = MagicMock(DDGS=MagicMock(return_value=mock_ddgs_instance))
    sys.modules["duckduckgo_search"] = mock_module
    try:
        from agent_harness.tools.web_search import DuckDuckGoProvider
        p = DuckDuckGoProvider()
        res = p.search("q", 2)
        assert res[0]["title"] == "D1"
        assert res[0]["url"] == "http://d.com"
        assert res[0]["snippet"] == "DS1"
    finally:
        sys.modules.pop("duckduckgo_search", None)


def test_web_search_output_deterministic_ordering() -> None:
    # Ensure results are returned in provider order, not sorted
    class OrderedProvider:
        name = "ordered"

        def search(
            self, query: str, num_results: int, region: str | None = None
        ) -> list[dict[str, str]]:
            return [
                {"title": str(i), "url": f"http://{i}.com", "snippet": f"s{i}"}
                for i in [3, 1, 2]
            ]

    tool = WebSearchTool(provider=OrderedProvider())
    result = tool.execute({"query": "q", "num_results": 3}, {})
    assert [r["title"] for r in result.output] == ["3", "1", "2"]


def test_web_search_metadata_query_provider_present() -> None:
    class P:
        name = "my_provider"

        def search(
            self, query: str, num_results: int, region: str | None = None
        ) -> list[dict[str, str]]:
            return [{"title": "t", "url": "u", "snippet": "s"}]

    tool = WebSearchTool(config=FakeConfig(), provider=P())
    result = tool.execute({"query": "hello world"}, {})
    assert result.metadata["query"] == "hello world"
    assert result.metadata["provider"] == "my_provider"


def test_web_scrape_input_validation_completeness() -> None:
    tool = WebScrapeTool()
    # missing url
    assert tool.validate_input({})[0] is False
    # empty
    assert tool.validate_input({"url": ""})[0] is False
    # non-http
    assert tool.validate_input({"url": "ftp://x"})[0] is False
    # bad selector type
    assert tool.validate_input({"url": "http://x", "selector": 123})[0] is False
    # bad max_length
    assert tool.validate_input({"url": "http://x", "max_length": -5})[0] is False
    # valid with all
    assert (
        tool.validate_input({"url": "http://x", "selector": ".a", "max_length": 100})[0]
        is True
    )


def test_retrieval_output_size_caps_via_wrapper() -> None:
    # R5: textual output truncated via run_tool
    from agent_harness.tools.base import run_tool
    from tests.test_tools.doubles import FakeConfig as FC

    class LongProvider:
        name = "long"

        def search(
            self, query: str, num_results: int, region: str | None = None
        ) -> list[dict[str, str]]:
            # Return with very long snippet
            return [{"title": "t", "url": "u", "snippet": "x" * 5000}]

    cfg = FC()
    cfg.security.max_output_bytes = 100  # tiny
    _tool = WebSearchTool(config=cfg, provider=LongProvider())
    # Direct execute without wrapper returns long; wrapper should truncate if output were string.
    # For list output, wrapper does not truncate (only strings). So we test string truncation path via web_scrape
    from agent_harness.tools.web_scrape import WebScrapeTool as WS

    with patch("agent_harness.tools.web_scrape.requests.get") as mock_get:
        mock_resp = Mock()
        mock_resp.text = "<html><body><p>" + "y" * 2000 + "</p></body></html>"
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp
        scrape_tool = WS()
        # Use run_tool to get truncation
        result = run_tool(scrape_tool, {"url": "http://example.com"}, {}, config=cfg)
        # If scraped text >100 bytes, should be truncated with marker
        if len("y" * 2000) > 100:
            # run_tool will truncate string output
            assert (
                result.metadata.get("truncated") is True
                or len(result.output.encode("utf-8")) <= 150
            )


def test_web_search_num_results_boundaries() -> None:
    tool = WebSearchTool()
    # 0 invalid
    assert tool.validate_input({"query": "q", "num_results": 0})[0] is False
    # 1 valid
    assert tool.validate_input({"query": "q", "num_results": 1})[0] is True
    # 50 valid
    assert tool.validate_input({"query": "q", "num_results": 50})[0] is True
    # 51 invalid
    assert tool.validate_input({"query": "q", "num_results": 51})[0] is False
    # negative invalid
    assert tool.validate_input({"query": "q", "num_results": -1})[0] is False
    # empty query invalid
    assert tool.validate_input({"query": ""})[0] is False
    # whitespace query invalid
    assert tool.validate_input({"query": "   "})[0] is False
    # unicode query valid
    assert tool.validate_input({"query": "hällö 🌍"})[0] is True
