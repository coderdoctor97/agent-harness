"""Web search provider abstraction and tool.

Spec: SPEC-002 §3.1, SPEC-006 §1 search config
"""

from __future__ import annotations

import os
from typing import Any, Protocol

import requests


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
