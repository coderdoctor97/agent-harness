"""Web scrape tool.

Spec: SPEC-002 §3.2
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from agent_harness.tools.base import BaseTool, ToolResult

USER_AGENT = "AgentHarness/0.1 (+https://github.com/coderdoctor97/agent-harness)"
TIMEOUT_S = 20


def _is_valid_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:  # noqa: BLE001
        return False


def _strip_and_extract(html: str, selector: str | None) -> str:
    soup = BeautifulSoup(html, "html.parser")
    # Strip script/style/nav
    for tag in soup(["script", "style", "nav"]):
        tag.decompose()
    if selector:
        # Use CSS selector; if not found, fallback to whole body
        elements = soup.select(selector)
        if elements:
            texts = [el.get_text(separator=" ", strip=True) for el in elements]
            return " ".join(t for t in texts if t)
        # selector miss -> return empty or fallback? Spec says optional selector
        # If selector yields nothing, return extracted text of body (maybe empty)
        # We'll return empty string to let caller decide; but we should fallback to whole text?
        # For now return "" to indicate miss, but tool should still succeed with empty.
        return ""
    # No selector: get text from body or whole doc
    text = soup.get_text(separator=" ", strip=True)
    # Collapse whitespace
    return " ".join(text.split())


def _classify_scrape_error(exc: Exception, url: str) -> tuple[str, bool]:
    msg = str(exc)
    if isinstance(exc, requests.exceptions.Timeout):
        return f"Scrape timeout for {url}: {msg}", True
    if isinstance(exc, requests.exceptions.ConnectionError):
        # Could be DNS failure vs connection; DNS often shows NameOrServiceNotKnown
        lower = msg.lower()
        if "name" in lower or "dns" in lower or "getaddrinfo" in lower:
            return f"Scrape DNS failure for {url}: {msg}", False
        return f"Scrape connection error for {url}: {msg}", True
    if isinstance(exc, requests.exceptions.HTTPError):
        resp = getattr(exc, "response", None)
        status: int | None = None
        if resp is not None:
            status = getattr(resp, "status_code", None)
        if status is not None:
            if status == 429 or 500 <= status < 600:
                return f"Scrape HTTP {status} for {url}: {msg}", True
            return f"Scrape HTTP {status} for {url}: {msg}", False
        return f"Scrape HTTP error for {url}: {msg}", True
    return f"Scrape error for {url}: {msg}", False


class WebScrapeTool(BaseTool):
    """Web scrape tool per SPEC-002 §3.2."""

    def __init__(self, config: Any = None) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "web_scrape"

    @property
    def description(self) -> str:
        return (
            "Fetches URL and extracts text. Input: {url: str (http(s) required), "
            "selector: str (optional CSS), max_length: int (default 5000)}. "
            "Output: extracted text content. Strips script/style/nav, 20s timeout."
        )

    @property
    def capabilities(self) -> list[str]:
        return ["web", "scrape", "extract"]

    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str]:
        if "url" not in input_data:
            return False, "Missing required 'url'"
        url = input_data["url"]
        if not isinstance(url, str) or not url.strip():
            return False, "'url' must be a non-empty string"
        if not _is_valid_http_url(url):
            return False, "'url' must be http(s) URL"
        if "selector" in input_data and not isinstance(input_data["selector"], str):
            return False, "'selector' must be a string"
        if "max_length" in input_data:
            ml = input_data["max_length"]
            if not isinstance(ml, int) or ml <= 0:
                return False, "'max_length' must be a positive int"
        return True, ""

    def execute(
        self, input_data: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        start = time.monotonic()
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
        url: str = str(input_data["url"]).strip()
        selector: str | None = input_data.get("selector")
        max_length: int = int(input_data.get("max_length", 5000))

        headers = {"User-Agent": USER_AGENT}
        try:
            resp = requests.get(url, headers=headers, timeout=TIMEOUT_S)
            # Raise for status to enable classification
            resp.raise_for_status()
            html = resp.text
        except Exception as exc:  # noqa: BLE001
            msg, retryable = _classify_scrape_error(exc, url)
            return ToolResult(
                success=False,
                error=msg,
                metadata={
                    "tool_name": self.name,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                    "retryable": retryable,
                    "url": url,
                },
            )

        try:
            text = _strip_and_extract(html, selector)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                error=f"Scrape parse error for {url}: {exc}",
                metadata={
                    "tool_name": self.name,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                    "retryable": False,
                    "url": url,
                },
            )

        # Apply max_length truncation (R5 also applies via wrapper)
        truncated = False
        if len(text) > max_length:
            text = text[:max_length]
            truncated = True

        duration_ms = int((time.monotonic() - start) * 1000)
        # Output cap via config security.max_output_bytes is handled by wrapper,
        # but we enforce max_length already.
        meta: dict[str, Any] = {
            "tool_name": self.name,
            "duration_ms": duration_ms,
            "url": url,
        }
        if truncated:
            meta["truncated"] = True
        # Context parameter not used but required by signature
        _ = context
        return ToolResult(success=True, output=text, metadata=meta)
