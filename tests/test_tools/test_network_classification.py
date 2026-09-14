"""Network failure classification matrix tests.

Spec: SPEC-002 §3.1, §3.2 retryable mapping
Covers timeouts, 429/5xx retryable; 4xx, DNS, invalid URL not retryable.
"""

from __future__ import annotations

import requests

from agent_harness.tools.web_scrape import WebScrapeTool, _classify_scrape_error
from agent_harness.tools.web_search import WebSearchTool, _classify_search_error


def _make_http_error(status: int) -> requests.exceptions.HTTPError:
    err = requests.exceptions.HTTPError(f"{status} Error")
    mock_resp = type("Resp", (), {"status_code": status})()
    err.response = mock_resp  # type: ignore[attr-defined]
    return err


def test_search_timeout_retryable() -> None:
    msg, retry = _classify_search_error(requests.exceptions.Timeout("timeout"), "bing")
    assert retry is True
    assert "timeout" in msg.lower()
    assert "bing" in msg.lower()


def test_search_429_retryable() -> None:
    err = _make_http_error(429)
    msg, retry = _classify_search_error(err, "serpapi")
    assert retry is True
    assert "429" in msg
    assert "serpapi" in msg or "429" in msg


def test_search_500_retryable() -> None:
    err = _make_http_error(500)
    _msg, retry = _classify_search_error(err, "google")
    assert retry is True


def test_search_502_retryable() -> None:
    err = _make_http_error(502)
    _, retry = _classify_search_error(err, "duckduckgo")
    assert retry is True


def test_search_404_not_retryable() -> None:
    err = _make_http_error(404)
    msg, retry = _classify_search_error(err, "bing")
    assert retry is False
    assert "404" in msg


def test_search_400_not_retryable() -> None:
    err = _make_http_error(400)
    _, retry = _classify_search_error(err, "bing")
    assert retry is False


def test_search_dns_not_retryable() -> None:
    err = requests.exceptions.ConnectionError("Name or service not known")
    msg, retry = _classify_search_error(err, "bing")
    assert retry is False
    assert "dns" in msg.lower() or "name" in msg.lower()


def test_search_connection_retryable_when_not_dns() -> None:
    err = requests.exceptions.ConnectionError("Connection refused")
    _, retry = _classify_search_error(err, "bing")
    assert retry is True


def test_search_missing_key_not_retryable() -> None:
    err = ValueError(
        "Missing API key for search provider 'serpapi': env var 'SEARCH_API_KEY' not set"
    )
    msg, retry = _classify_search_error(err, "serpapi")
    assert retry is False
    assert "missing api key" in msg.lower()


def test_search_runtime_rate_retryable() -> None:
    err = RuntimeError("Rate limited by provider")
    _, retry = _classify_search_error(err, "bing")
    assert retry is True


def test_search_generic_error_not_retryable() -> None:
    err = RuntimeError("some other error")
    _, retry = _classify_search_error(err, "bing")
    assert retry is False


# Scrape classification


def test_scrape_timeout_retryable_with_url() -> None:
    url = "http://example.com/page"
    msg, retry = _classify_scrape_error(requests.exceptions.Timeout("timeout"), url)
    assert retry is True
    assert url in msg
    assert "timeout" in msg.lower()


def test_scrape_429_retryable_with_url() -> None:
    url = "http://example.com/a"
    err = _make_http_error(429)
    msg, retry = _classify_scrape_error(err, url)
    assert retry is True
    assert "429" in msg
    assert url in msg


def test_scrape_5xx_retryable() -> None:
    url = "http://example.com/b"
    err = _make_http_error(503)
    _, retry = _classify_scrape_error(err, url)
    assert retry is True


def test_scrape_404_not_retryable() -> None:
    url = "http://example.com/c"
    err = _make_http_error(404)
    msg, retry = _classify_scrape_error(err, url)
    assert retry is False
    assert "404" in msg


def test_scrape_dns_not_retryable() -> None:
    url = "http://example.com/d"
    err = requests.exceptions.ConnectionError("getaddrinfo failed")
    msg, retry = _classify_scrape_error(err, url)
    assert retry is False
    assert url in msg
    assert "dns" in msg.lower() or "getaddrinfo" in msg.lower()


def test_scrape_connection_retryable_when_not_dns() -> None:
    url = "http://example.com/e"
    err = requests.exceptions.ConnectionError("Connection reset by peer")
    _, retry = _classify_scrape_error(err, url)
    assert retry is True


def test_scrape_invalid_url_not_retryable_via_validate() -> None:
    tool = WebScrapeTool()
    result = tool.execute({"url": "ht!tp:// bad"}, {})
    assert result.success is False
    assert result.metadata.get("retryable") is False
    assert "TOOL_INPUT_INVALID" in result.error  # type: ignore[union-attr]


def test_search_invalid_query_not_retryable() -> None:
    tool = WebSearchTool()
    result = tool.execute({"query": ""}, {})
    assert result.success is False
    assert result.metadata.get("retryable") is False


def test_classify_messages_worded_for_llm() -> None:
    # Ensure messages contain status code and URL/provider for LLM re-planning
    search_msg, _ = _classify_search_error(_make_http_error(429), "serpapi")
    assert "429" in search_msg and "serpapi" in search_msg
    scrape_msg, _ = _classify_scrape_error(
        _make_http_error(500), "http://example.com/x"
    )
    assert "500" in scrape_msg and "http://example.com/x" in scrape_msg
