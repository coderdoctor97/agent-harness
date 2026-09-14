"""Web search provider abstraction and tool.

Spec: SPEC-002 §3.1, SPEC-006 §1 search config
"""

from __future__ import annotations

import os
import time
from typing import Any, Protocol

import requests

from agent_harness.tools.base import BaseTool, ToolResult


class SearchProvider(Protocol):
    """Protocol for search providers."""

    def search(
        self, query: str, num_results: int, region: str | None = None
    ) -> list[dict[str, str]]:
        """Search and return normalized results."""
        ...


class DuckDuckGoProvider:
    """DuckDuckGo provider (keyless, default)."""

    name: str = "duckduckgo"

    def search(
        self, query: str, num_results: int, region: str | None = None
    ) -> list[dict[str, str]]:
        try:
            from duckduckgo_search import DDGS  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "duckduckgo-search not installed; install duckduckgo-search or use another provider"
            ) from exc
        # Use DDGS text search
        kwargs: dict[str, Any] = {"keywords": query, "max_results": num_results}
        if region:
            kwargs["region"] = region
        try:
            with DDGS() as ddgs:
                raw = list(ddgs.text(**kwargs))
        except Exception as exc:
            raise RuntimeError(f"DuckDuckGo search failed: {exc}") from exc
        out: list[dict[str, str]] = []
        for r in raw[:num_results]:
            out.append(
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", r.get("url", "")),
                    "snippet": r.get("body", r.get("snippet", "")),
                }
            )
        return out


class SerpApiProvider:
    """SerpAPI provider."""

    name: str = "serpapi"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def search(
        self, query: str, num_results: int, region: str | None = None
    ) -> list[dict[str, str]]:
        params: dict[str, Any] = {
            "engine": "google",
            "q": query,
            "num": num_results,
            "api_key": self.api_key,
        }
        if region:
            params["gl"] = region
        resp = requests.get(
            "https://serpapi.com/search.json", params=params, timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        organic = data.get("organic_results", [])
        out: list[dict[str, str]] = []
        for item in organic[:num_results]:
            out.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                }
            )
        return out


class BingProvider:
    """Bing Search provider."""

    name: str = "bing"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def search(
        self, query: str, num_results: int, region: str | None = None
    ) -> list[dict[str, str]]:
        headers = {"Ocp-Apim-Subscription-Key": self.api_key}
        params: dict[str, Any] = {"q": query, "count": num_results}
        if region:
            params["mkt"] = region
        resp = requests.get(
            "https://api.bing.microsoft.com/v7.0/search",
            headers=headers,
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("webPages", {}).get("value", [])
        out: list[dict[str, str]] = []
        for item in items[:num_results]:
            out.append(
                {
                    "title": item.get("name", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("snippet", ""),
                }
            )
        return out


class GoogleProvider:
    """Google Custom Search provider."""

    name: str = "google"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def search(
        self, query: str, num_results: int, region: str | None = None
    ) -> list[dict[str, str]]:
        params: dict[str, Any] = {
            "key": self.api_key,
            "cx": "google",
            "q": query,
            "num": num_results,
        }
        if region:
            params["gl"] = region
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1", params=params, timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        out: list[dict[str, str]] = []
        for item in items[:num_results]:
            out.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                }
            )
        return out


def _get_api_key(config: Any) -> str | None:
    """Resolve API key via config.search.api_key_env."""
    if config is None:
        return None
    try:
        search_cfg = getattr(config, "search", None)
        if search_cfg is None and isinstance(config, dict):
            search_cfg = config.get("search")
        if search_cfg is None:
            return None
        if isinstance(search_cfg, dict):
            env_name = search_cfg.get("api_key_env", "SEARCH_API_KEY")
        else:
            env_name = getattr(search_cfg, "api_key_env", "SEARCH_API_KEY")
        # Resolve from env
        return os.environ.get(env_name)
    except Exception:  # noqa: BLE001
        return None


def _get_provider_name(config: Any) -> str:
    """Resolve provider name from config, default duckduckgo."""
    default = "duckduckgo"
    if config is None:
        return default
    try:
        search_cfg = getattr(config, "search", None)
        if search_cfg is None and isinstance(config, dict):
            search_cfg = config.get("search")
        if search_cfg is None:
            return default
        if isinstance(search_cfg, dict):
            val = search_cfg.get("provider", default)
        else:
            val = getattr(search_cfg, "provider", default)
        if isinstance(val, str) and val:
            return val.lower()
        return default
    except Exception:  # noqa: BLE001
        return default


def _get_max_results(config: Any) -> int:
    default = 10
    if config is None:
        return default
    try:
        search_cfg = getattr(config, "search", None)
        if search_cfg is None and isinstance(config, dict):
            search_cfg = config.get("search")
        if search_cfg is None:
            return default
        if isinstance(search_cfg, dict):
            val = search_cfg.get("max_results", default)
        else:
            val = getattr(search_cfg, "max_results", default)
        if isinstance(val, int) and val > 0:
            return val
        return default
    except Exception:  # noqa: BLE001
        return default


def create_search_provider(config: Any) -> SearchProvider:
    """Factory selecting provider by config.search.provider.

    Spec: SPEC-002 §3.1 provider selection.
    """
    name = _get_provider_name(config)
    if name == "duckduckgo":
        return DuckDuckGoProvider()
    # For keyed providers, resolve API key
    api_key = _get_api_key(config)
    if not api_key:
        # Resolve env name for error message
        env_name = "SEARCH_API_KEY"
        try:
            sc = getattr(config, "search", None)
            if isinstance(sc, dict):
                env_name = sc.get("api_key_env", env_name)
            elif sc is not None:
                env_name = getattr(sc, "api_key_env", env_name)
        except Exception:  # noqa: BLE001, S110
            pass
        raise ValueError(
            f"Missing API key for search provider {name!r}: env var {env_name!r} not set"
        )
    if name == "serpapi":
        return SerpApiProvider(api_key)
    if name == "bing":
        return BingProvider(api_key)
    if name == "google":
        return GoogleProvider(api_key)
    # Unknown provider → fallback to duckduckgo with warning? But spec says enum.
    raise ValueError(f"Unknown search provider {name!r}")


def _classify_search_error(exc: Exception, provider_name: str) -> tuple[str, bool]:
    """Map search exception to (message, retryable). Spec: SPEC-002 §3.1."""
    msg = str(exc)
    # Timeout vs connection vs http status
    if isinstance(exc, requests.exceptions.Timeout):
        return f"Search timeout ({provider_name}): {msg}", True
    if isinstance(exc, requests.exceptions.ConnectionError):
        return f"Search connection error ({provider_name}): {msg}", True
    if isinstance(exc, requests.exceptions.HTTPError):
        # Try to extract status code
        resp = getattr(exc, "response", None)
        status: int | None = None
        if resp is not None:
            status = getattr(resp, "status_code", None)
        # Fallback parse from message
        if status is None:
            # Check if msg contains 429 etc
            if "429" in msg:
                status = 429
            elif "500" in msg:
                status = 500
        if status is not None:
            if status == 429 or 500 <= status < 600:
                return f"Search HTTP {status} ({provider_name}): {msg}", True
            # 4xx not retryable (except 429)
            return f"Search HTTP {status} ({provider_name}): {msg}", False
        return f"Search HTTP error ({provider_name}): {msg}", True
    # ValueError for missing key is not retryable
    if isinstance(exc, ValueError) and "Missing API key" in msg:
        return msg, False
    # RuntimeError from duckduckgo etc
    if isinstance(exc, RuntimeError):
        # Check if rate-limit like
        lower = msg.lower()
        if "rate" in lower or "429" in lower:
            return f"Search error ({provider_name}): {msg}", True
        return f"Search error ({provider_name}): {msg}", False
    return f"Search error ({provider_name}): {msg}", False


class WebSearchTool(BaseTool):
    """Web search tool (research entry point).

    Spec: SPEC-002 §3.1
    """

    def __init__(
        self,
        config: Any = None,
        provider: SearchProvider | None = None,
    ) -> None:
        self._config = config
        self._provider_override = provider

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Searches the web. Input: {query: str (required), "
            "num_results: int (default config.search.max_results), "
            "region: str (optional)}. Output: list of {title, url, snippet}. "
            "Empty results succeed with metadata no_results."
        )

    @property
    def capabilities(self) -> list[str]:
        return ["search", "web", "research"]

    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str]:
        if "query" not in input_data:
            return False, "Missing required 'query'"
        q = input_data["query"]
        if not isinstance(q, str) or not q.strip():
            return False, "'query' must be a non-empty string"
        if "num_results" in input_data:
            nr = input_data["num_results"]
            if not isinstance(nr, int) or nr <= 0:
                return False, "'num_results' must be a positive int"
            if nr > 50:
                return False, "'num_results' must be <= 50"
        if "region" in input_data and not isinstance(input_data["region"], str):
            return False, "'region' must be a string"
        return True, ""

    def execute(
        self, input_data: dict[str, Any], context: dict[str, Any]
    ) -> ToolResult:
        start = time.monotonic()
        # Validate first (also enforced by run_tool but we handle directly)
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
        query: str = str(input_data["query"]).strip()
        num_results: int = int(
            input_data.get("num_results", _get_max_results(self._config))
        )
        region: str | None = input_data.get("region")

        # Resolve provider
        provider: SearchProvider | None = self._provider_override
        provider_name = "unknown"
        try:
            if provider is None:
                provider = create_search_provider(self._config)
            provider_name = getattr(provider, "name", type(provider).__name__)
            results = provider.search(query, num_results, region)
        except Exception as exc:  # noqa: BLE001
            msg, retryable = _classify_search_error(exc, provider_name)
            return ToolResult(
                success=False,
                error=msg,
                metadata={
                    "tool_name": self.name,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                    "retryable": retryable,
                    "provider": provider_name,
                    "query": query,
                },
            )

        duration_ms = int((time.monotonic() - start) * 1000)
        if not results:
            return ToolResult(
                success=True,
                output=[],
                metadata={
                    "tool_name": self.name,
                    "duration_ms": duration_ms,
                    "no_results": True,
                    "provider": provider_name,
                    "query": query,
                },
            )
        # Deterministic ordering (as returned), ensure shape
        normalized: list[dict[str, str]] = []
        for r in results:
            normalized.append(
                {
                    "title": str(r.get("title", "")),
                    "url": str(r.get("url", "")),
                    "snippet": str(r.get("snippet", "")),
                }
            )
        # Apply overall output cap via config if needed — wrapper handles R5, but we also
        # ensure we don't exceed drastically by truncating list length to num_results
        normalized = normalized[:num_results]
        return ToolResult(
            success=True,
            output=normalized,
            metadata={
                "tool_name": self.name,
                "duration_ms": duration_ms,
                "provider": provider_name,
                "query": query,
            },
        )
