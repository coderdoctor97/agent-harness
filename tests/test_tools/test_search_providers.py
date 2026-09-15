"""Tests for search provider abstraction (2.1).

Spec: SPEC-002 §3.1
"""

from __future__ import annotations

import os

import pytest

from agent_harness.tools.web_search import (
    BingProvider,
    DuckDuckGoProvider,
    GoogleProvider,
    SerpApiProvider,
    create_search_provider,
)
from tests.test_tools.doubles import FakeConfig


def test_provider_selection_duckduckgo_default() -> None:
    cfg = FakeConfig()
    cfg.search.provider = "duckduckgo"
    provider = create_search_provider(cfg)
    assert isinstance(provider, DuckDuckGoProvider)
    assert provider.name == "duckduckgo"


def test_provider_selection_serpapi_with_key() -> None:
    cfg = FakeConfig()
    cfg.search.provider = "serpapi"
    cfg.search.api_key_env = "SEARCH_API_KEY"
    os.environ["SEARCH_API_KEY"] = "fake-serp-key"
    try:
        provider = create_search_provider(cfg)
        assert isinstance(provider, SerpApiProvider)
        assert provider.api_key == "fake-serp-key"
    finally:
        os.environ.pop("SEARCH_API_KEY", None)


def test_provider_selection_bing_with_key() -> None:
    cfg = FakeConfig()
    cfg.search.provider = "bing"
    cfg.search.api_key_env = "BING_KEY"
    os.environ["BING_KEY"] = "bing-fake"
    try:
        provider = create_search_provider(cfg)
        assert isinstance(provider, BingProvider)
    finally:
        os.environ.pop("BING_KEY", None)


def test_provider_selection_google_with_key() -> None:
    cfg = FakeConfig()
    cfg.search.provider = "google"
    cfg.search.api_key_env = "GOOGLE_KEY"
    os.environ["GOOGLE_KEY"] = "google-fake"
    try:
        provider = create_search_provider(cfg)
        assert isinstance(provider, GoogleProvider)
    finally:
        os.environ.pop("GOOGLE_KEY", None)


def test_provider_missing_key_raises_clear_error() -> None:
    cfg = FakeConfig()
    cfg.search.provider = "serpapi"
    cfg.search.api_key_env = "MISSING_KEY_ENV"
    os.environ.pop("MISSING_KEY_ENV", None)
    with pytest.raises(ValueError) as exc:
        create_search_provider(cfg)
    msg = str(exc.value).lower()
    assert "missing api key" in msg
    assert "missing_key_env" in msg.lower()


def test_provider_missing_key_for_bing() -> None:
    cfg = FakeConfig()
    cfg.search.provider = "bing"
    cfg.search.api_key_env = "BING_MISSING"
    os.environ.pop("BING_MISSING", None)
    with pytest.raises(ValueError) as exc:
        create_search_provider(cfg)
    assert "bing" in str(exc.value).lower()


def test_provider_unknown_raises() -> None:
    cfg = FakeConfig()
    cfg.search.provider = "unknown_provider"
    # unknown with duckduckgo fallback? Our implementation raises ValueError
    # Need to ensure we set api key so not missing-key path triggers first
    # For unknown, we raise unknown provider error regardless of key.
    # First, set a key so missing-key not triggered, then unknown should still raise.
    cfg.search.api_key_env = "SEARCH_API_KEY"
    os.environ["SEARCH_API_KEY"] = "x"
    try:
        with pytest.raises(ValueError) as exc:
            create_search_provider(cfg)
        assert "unknown" in str(exc.value).lower()
    finally:
        os.environ.pop("SEARCH_API_KEY", None)


def test_provider_case_insensitive() -> None:
    cfg = FakeConfig()
    cfg.search.provider = "DuckDuckGo"
    provider = create_search_provider(cfg)
    assert isinstance(provider, DuckDuckGoProvider)


def test_provider_default_when_config_none() -> None:
    provider = create_search_provider(None)
    assert isinstance(provider, DuckDuckGoProvider)


def test_provider_default_when_missing_search_section() -> None:
    provider = create_search_provider({})
    assert isinstance(provider, DuckDuckGoProvider)


def test_get_max_results_and_provider_name_helpers() -> None:
    from agent_harness.tools.web_search import _get_max_results, _get_provider_name

    cfg = FakeConfig()
    cfg.search.max_results = 7
    assert _get_max_results(cfg) == 7
    assert _get_provider_name(cfg) == "duckduckgo"
    assert _get_max_results(None) == 10
    assert _get_provider_name(None) == "duckduckgo"
