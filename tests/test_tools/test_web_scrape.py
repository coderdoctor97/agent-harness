"""Tests for web_scrape tool.

Spec: SPEC-002 §3.2
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import requests

from agent_harness.tools.web_scrape import WebScrapeTool, _strip_and_extract


def _mock_response(text: str, status_code: int = 200) -> Mock:
    m = Mock()
    m.text = text
    m.status_code = status_code
    if status_code >= 400:
        # raise HTTPError on raise_for_status
        http_err = requests.exceptions.HTTPError(f"{status_code} Error")
        http_err.response = m  # type: ignore[attr-defined]
        m.raise_for_status.side_effect = http_err
    else:
        m.raise_for_status.return_value = None
    return m


def test_web_scrape_capabilities_and_description() -> None:
    tool = WebScrapeTool()
    assert tool.name == "web_scrape"
    assert set(tool.capabilities) == {"web", "scrape", "extract"}
    assert len(tool.description) <= 300
    assert "url" in tool.description.lower()


def test_validate_input() -> None:
    tool = WebScrapeTool()
    assert tool.validate_input({})[0] is False
    assert tool.validate_input({"url": "not a url"})[0] is False
    assert tool.validate_input({"url": "ftp://example.com"})[0] is False
    assert tool.validate_input({"url": "http://example.com"})[0] is True
    assert (
        tool.validate_input({"url": "https://example.com", "selector": 123})[0] is False
    )
    assert (
        tool.validate_input({"url": "https://example.com", "max_length": "5000"})[0]
        is False
    )
    assert (
        tool.validate_input({"url": "https://example.com", "max_length": 0})[0] is False
    )
    assert (
        tool.validate_input({"url": "https://example.com", "selector": "div.a"})[0]
        is True
    )


def test_strip_and_extract_basic() -> None:
    html = "<html><head><style>body{}</style></head><body><script>alert(1)</script><nav>menu</nav><p>Hello <b>World</b></p></body></html>"
    text = _strip_and_extract(html, None)
    assert "Hello World" in text
    assert "alert" not in text
    assert "menu" not in text
    assert "body{" not in text


def test_selector_hit() -> None:
    html = '<html><body><div class="main">Main Content</div><div class="other">Other</div></body></html>'
    text = _strip_and_extract(html, "div.main")
    assert text == "Main Content"
    assert "Other" not in text


def test_selector_miss_returns_empty() -> None:
    html = "<html><body><div>Hi</div></body></html>"
    text = _strip_and_extract(html, "span.missing")
    assert text == ""


@patch("agent_harness.tools.web_scrape.requests.get")
def test_execute_success_no_selector(mock_get: Mock) -> None:
    html = "<html><body><p>Extracted</p></body></html>"
    mock_get.return_value = _mock_response(html)
    tool = WebScrapeTool()
    result = tool.execute({"url": "http://example.com"}, {})
    assert result.success is True
    assert "Extracted" in result.output  # type: ignore[operator]
    assert result.metadata["url"] == "http://example.com"
    # Verify User-Agent and timeout
    _args, kwargs = mock_get.call_args
    assert kwargs["headers"]["User-Agent"].startswith("AgentHarness")
    assert kwargs["timeout"] == 20


@patch("agent_harness.tools.web_scrape.requests.get")
def test_execute_with_selector(mock_get: Mock) -> None:
    html = "<html><body><article>Desired</article><footer>Footer</footer></body></html>"
    mock_get.return_value = _mock_response(html)
    tool = WebScrapeTool()
    result = tool.execute({"url": "http://example.com", "selector": "article"}, {})
    assert result.success is True
    assert result.output == "Desired"  # type: ignore[union-attr]


@patch("agent_harness.tools.web_scrape.requests.get")
def test_execute_max_length_truncation(mock_get: Mock) -> None:
    html = "<html><body><p>" + "a" * 100 + "</p></body></html>"
    mock_get.return_value = _mock_response(html)
    tool = WebScrapeTool()
    result = tool.execute({"url": "http://example.com", "max_length": 10}, {})
    assert result.success is True
    assert len(result.output) == 10  # type: ignore[arg-type]
    assert result.metadata.get("truncated") is True


@patch("agent_harness.tools.web_scrape.requests.get")
def test_execute_non_200_retryable_false_for_404(mock_get: Mock) -> None:
    mock_get.return_value = _mock_response("Not found", status_code=404)
    tool = WebScrapeTool()
    result = tool.execute({"url": "http://example.com"}, {})
    assert result.success is False
    assert result.metadata.get("retryable") is False
    assert "404" in result.error  # type: ignore[union-attr]


@patch("agent_harness.tools.web_scrape.requests.get")
def test_execute_timeout_retryable_true(mock_get: Mock) -> None:
    mock_get.side_effect = requests.exceptions.Timeout("timed out")
    tool = WebScrapeTool()
    result = tool.execute({"url": "http://example.com"}, {})
    assert result.success is False
    assert result.metadata.get("retryable") is True
    assert "timeout" in result.error.lower()  # type: ignore[union-attr]


@patch("agent_harness.tools.web_scrape.requests.get")
def test_execute_429_retryable_true(mock_get: Mock) -> None:
    err = requests.exceptions.HTTPError("429 Too Many Requests")
    err.response = _mock_response("", status_code=429)  # type: ignore[attr-defined]
    mock_get.return_value = _mock_response("", status_code=429)
    # Already set to raise, but we override side_effect for get to raise directly
    mock_get.side_effect = err
    tool = WebScrapeTool()
    result = tool.execute({"url": "http://example.com"}, {})
    assert result.success is False
    assert result.metadata.get("retryable") is True


@patch("agent_harness.tools.web_scrape.requests.get")
def test_execute_invalid_url_rejected_by_validate(mock_get: Mock) -> None:
    tool = WebScrapeTool()
    result = tool.execute({"url": "javascript:alert(1)"}, {})
    assert result.success is False
    assert "TOOL_INPUT_INVALID" in result.error  # type: ignore[union-attr]
    mock_get.assert_not_called()


def test_execute_input_validation_error_returns_input_invalid() -> None:
    tool = WebScrapeTool()
    result = tool.execute({"url": ""}, {})
    assert result.success is False
    assert result.metadata["retryable"] is False
