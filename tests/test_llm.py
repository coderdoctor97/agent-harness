"""Deterministic LLM contracts and stubbed providers. Spec: SPEC-004 §1."""

from __future__ import annotations

import inspect
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

from agent_harness.llm import LLMClient, LLMResponse, LLMUsage


def test_frozen_llm_signatures() -> None:
    """Anchor for consumer mock agreement. Spec: SPEC-004 §1."""
    expected = {
        "complete": ["self", "messages", "temperature", "max_tokens"],
        "complete_json": ["self", "messages", "schema_hint", "temperature"],
    }
    for name, params in expected.items():
        signature = inspect.signature(getattr(LLMClient, name))
        assert list(signature.parameters) == params
        assert (
            signature.parameters["temperature"].kind == inspect.Parameter.KEYWORD_ONLY
        )
        assert signature.parameters["temperature"].default is None
    assert LLMClient.__abstractmethods__ == {"complete", "complete_json", "usage"}
    assert [f.name for f in fields(LLMUsage)] == [
        "calls",
        "prompt_tokens",
        "completion_tokens",
        "estimated_cost",
    ]
    response = LLMResponse("text", "model", 1, 2, "stop", 0)
    assert response.metadata == {"redactions": 0}
    assert LLMUsage().calls == 0


def test_scripted_mock_queue_and_usage() -> None:
    """Mock consumes deterministic scripts and fails explicitly. Spec: SPEC-004 C7."""
    import pytest

    from agent_harness.config import AgentError
    from agent_harness.llm import MockLLMClient

    messages = [{"role": "user", "content": "two words"}]
    client = MockLLMClient(
        ["hello", {"ok": True}, LLMResponse("exact", "fixed", 7, 3, "stop", 4)]
    )
    assert client.complete(messages).text == "hello"
    assert client.complete_json(messages)[0] == {"ok": True}
    assert client.complete(messages).model == "fixed"
    assert client.usage.calls == 3 and client.usage.prompt_tokens == 15
    snapshot = client.usage
    snapshot.calls = 100
    assert client.usage.calls == 3
    with pytest.raises(AgentError, match="queue exhausted"):
        client.complete(messages)
    with pytest.raises(AgentError, match="Injected"):
        MockLLMClient(["unused"], raise_on_call=1).complete(messages)
    with pytest.raises(AgentError, match="SCRIPT"):
        MockLLMClient([AgentError("LLM_CALL_FAILED", "SCRIPT", "llm")]).complete(
            messages
        )
    with pytest.raises(AgentError, match="PLAN_PARSE_FAILED"):
        MockLLMClient(["invalid", "still invalid"]).complete_json(messages)
    client = MockLLMClient(["ok"])
    client.complete([{"role": "user", "content": "123-45-6789"}])
    assert "123-45-6789" not in str(client.requests)


def test_provider_adapters_and_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider SDK boundaries are entirely faked. Spec: SPEC-004 §1.3."""
    from types import SimpleNamespace

    from agent_harness.config import AgentError, Config
    from agent_harness.llm import (
        AnthropicClient,
        LocalCompatClient,
        OpenAIClient,
        create_llm_client,
    )

    monkeypatch.setenv("P1_KEY", "fake-provider-key")
    config = Config.from_dict(
        {"llm": {"api_key_env": "P1_KEY", "base_url": "https://example.invalid/v1"}}
    )
    calls: list[dict[str, Any]] = []

    def openai_create(**kwargs: Any) -> object:
        calls.append(kwargs)
        return SimpleNamespace(
            model="model",
            usage=SimpleNamespace(prompt_tokens=2, completion_tokens=3),
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"ok": true}'),
                    finish_reason="stop",
                )
            ],
        )

    sdk = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=openai_create))
    )
    ticks = iter([1.0, 1.25, 2.0, 2.25])
    client = OpenAIClient(config, sdk=sdk, clock=lambda: next(ticks))
    assert (
        client.complete(
            [{"role": "user", "content": "test"}], temperature=0, max_tokens=10
        ).latency_ms
        == 250
    )
    assert calls[0]["temperature"] == 0 and calls[0]["max_tokens"] == 10
    assert client.complete_json([])[0] == {"ok": True}
    assert client.usage.calls == 2 and client.usage.completion_tokens == 6

    def anthropic_create(**kwargs: Any) -> object:
        calls.append(kwargs)
        return SimpleNamespace(
            model="claude",
            content=[SimpleNamespace(type="text", text="text")],
            usage=SimpleNamespace(input_tokens=1, output_tokens=2),
            stop_reason="end_turn",
        )

    anthropic = AnthropicClient(
        config, sdk=SimpleNamespace(messages=SimpleNamespace(create=anthropic_create))
    )
    assert (
        anthropic.complete(
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "user"},
            ]
        ).text
        == "text"
    )
    assert calls[-1]["system"] == "system" and len(calls[-1]["messages"]) == 1
    constructed: list[dict[str, Any]] = []

    def constructor(**kwargs: Any) -> object:
        constructed.append(kwargs)
        return sdk

    def importer(name: str) -> object:
        if name == "anthropic":
            raise ImportError("not installed")
        return SimpleNamespace(OpenAI=constructor)

    monkeypatch.setattr("agent_harness.llm.providers.importlib.import_module", importer)
    assert isinstance(create_llm_client(config), OpenAIClient)
    assert constructed[-1]["base_url"] == "https://example.invalid/v1"
    assert constructed[-1]["max_retries"] == 0
    config.llm.provider = "local"
    assert isinstance(create_llm_client(config), LocalCompatClient)
    config.llm.provider = "anthropic"
    with pytest.raises(AgentError, match="anthropic"):
        create_llm_client(config)
    config.llm.provider = "invalid"
    with pytest.raises(AgentError):
        create_llm_client(config)
    config.llm.provider = "openai"
    monkeypatch.delenv("P1_KEY")
    with pytest.raises(AgentError, match="P1_KEY"):
        create_llm_client(config)


class _HTTPError(Exception):
    def __init__(self, code: int, retry_after: str | None = None) -> None:
        from types import SimpleNamespace

        super().__init__("provider body must never leak")
        self.status_code = code
        self.response = SimpleNamespace(
            headers={"Retry-After": retry_after} if retry_after is not None else {}
        )


def _raw(text: str | None = "ok", finish: str = "stop") -> object:
    from types import SimpleNamespace

    return SimpleNamespace(
        model="model",
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish)
        ],
    )


def _scripted_sdk(items: list[object]) -> tuple[object, list[dict[str, Any]]]:
    from collections import deque
    from types import SimpleNamespace

    queue = deque(items)
    calls: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> object:
        calls.append(kwargs)
        item = queue.popleft()
        if isinstance(item, Exception):
            raise item
        return item

    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    ), calls


@pytest.mark.parametrize(
    "failure", [_HTTPError(429, "3"), _HTTPError(503), TimeoutError()]
)
def test_transient_retry_and_usage(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    """Retries count every actual request and honor backoff. Spec: SPEC-004 C1, C5."""
    from agent_harness.config import Config
    from agent_harness.llm import OpenAIClient

    monkeypatch.setenv("P1_KEY", "dummy")
    config = Config.from_dict(
        {"llm": {"api_key_env": "P1_KEY", "cost_per_1k_tokens": 2}}
    )
    sdk, calls = _scripted_sdk([failure, failure, _raw()])
    sleeps: list[float] = []
    client = OpenAIClient(config, sdk=sdk, sleep=sleeps.append)
    assert client.complete([]).text == "ok"
    assert sleeps == (
        [3, 3]
        if isinstance(failure, _HTTPError) and failure.status_code == 429
        else [1, 2]
    )
    assert len(calls) == client.usage.calls == 3
    assert client.usage.prompt_tokens == 10 and client.usage.completion_tokens == 5
    assert client.usage.estimated_cost == pytest.approx(0.03)


@pytest.mark.parametrize(
    "header,delay",
    [("bad", 1.0), ("NaN", 1.0), ("-2", 1.0), ("Thu, 01 Jan 2026 00:00:05 GMT", 5.0)],
)
def test_retry_after_dates(
    monkeypatch: pytest.MonkeyPatch, header: str, delay: float
) -> None:
    """Retry-After dates use an injected wall clock. Spec: SPEC-004 C1."""
    from datetime import datetime, timezone

    from agent_harness.config import Config
    from agent_harness.llm import OpenAIClient

    monkeypatch.setenv("P1_KEY", "dummy")
    sdk, _ = _scripted_sdk([_HTTPError(429, header), _raw()])
    sleeps: list[float] = []
    client = OpenAIClient(
        Config.from_dict({"llm": {"api_key_env": "P1_KEY"}}),
        sdk=sdk,
        sleep=sleeps.append,
        wall_clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    client.complete([])
    assert sleeps == [delay]


def test_exhaustion_fallback_and_filtered_accounting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fallback occurs only once after nontransient primary failure. Spec: SPEC-004 C1–C2."""
    from agent_harness.config import AgentError, Config
    from agent_harness.llm import OpenAIClient

    monkeypatch.setenv("P1_KEY", "dummy")
    config = Config.from_dict(
        {
            "llm": {
                "api_key_env": "P1_KEY",
                "model": "primary",
                "fallback_model": "fallback",
                "max_retries": 2,
            }
        }
    )
    for first in [
        _HTTPError(400),
        _raw(None, "content_filter"),
        _raw("", "tool_calls"),
    ]:
        sdk, calls = _scripted_sdk([first, _raw()])
        client = OpenAIClient(config, sdk=sdk, sleep=lambda _: None)
        assert client.complete([]).text == "ok"
        assert [call["model"] for call in calls] == ["primary", "fallback"]
        if not isinstance(first, Exception):
            assert client.usage.prompt_tokens == 20
    for code in [429, 503]:
        sdk, calls = _scripted_sdk([_HTTPError(code)] * 3)
        client = OpenAIClient(config, sdk=sdk, sleep=lambda _: None)
        with pytest.raises(AgentError) as caught:
            client.complete([])
        assert caught.value.code == (
            "LLM_RATE_LIMITED" if code == 429 else "LLM_CALL_FAILED"
        )
        assert len(calls) == 3 and all(c["model"] == "primary" for c in calls)
        assert "provider body" not in str(caught.value)
    sdk, calls = _scripted_sdk([_HTTPError(400), TimeoutError()])
    with pytest.raises(AgentError):
        OpenAIClient(config, sdk=sdk, sleep=lambda _: None).complete([])
    assert len(calls) == 2
    config.llm.fallback_model = None
    sdk, _ = _scripted_sdk([_raw(None)])
    with pytest.raises(AgentError):
        OpenAIClient(config, sdk=sdk).complete([])


def test_json_repair_fences_and_validation() -> None:
    """Exactly one repair round; caller messages stay unchanged. Spec: SPEC-004 C3."""
    from copy import deepcopy

    from agent_harness.config import AgentError
    from agent_harness.llm import MockLLMClient

    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
    ]
    before = deepcopy(messages)
    client = MockLLMClient(["bad JSON", '```json\n{"ok": true}\n```'])
    result, _ = client.complete_json(messages, schema_hint="ok: boolean")
    assert result == {"ok": True} and client.usage.calls == 2
    assert "ok: boolean" in client.requests[0][0]["content"]
    assert client.requests[1][-2]["content"] == "bad JSON"
    assert messages == before
    with pytest.raises(AgentError, match="PLAN_PARSE_FAILED"):
        MockLLMClient(["NaN", "still bad"]).complete_json([])
    for message in [{"role": "other", "content": "x"}, {"role": "user", "content": 1}]:
        with pytest.raises(AgentError, match="Invalid message"):
            assert isinstance(message, dict)
            MockLLMClient(["unused"]).complete([message])


def test_outbound_and_log_redaction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No raw credentials or request bodies reach logs or the SDK. Spec: SPEC-004 C4–C6."""
    from copy import deepcopy

    from agent_harness.config import AgentError, Config
    from agent_harness.llm import OpenAIClient
    from agent_harness.logging import StructuredLogger

    secret = "private-provider-test-key"
    monkeypatch.setenv("P1_KEY", secret)
    config = Config.from_dict(
        {
            "llm": {"api_key_env": "P1_KEY"},
            "logging": {"file": str(tmp_path / "log"), "console": False},
        }
    )
    config.security.sensitive_patterns.append("confidential")
    sdk, calls = _scripted_sdk([_raw()])
    client = OpenAIClient(config, sdk=sdk, logger=StructuredLogger(config))
    messages = [{"role": "user", "content": f"{secret} confidential 123-45-6789"}]
    before = deepcopy(messages)
    response = client.complete(messages)
    assert response.redactions == 3 and response.metadata["redactions"] == 3
    assert calls[0]["messages"][0]["content"] == "[REDACTED] [REDACTED] [REDACTED]"
    assert messages == before
    log = (tmp_path / "log").read_text()
    assert secret not in log and "confidential" not in log and "123-45-6789" not in log
    assert '"redactions": 3' in log
    with pytest.raises(AgentError):
        client.complete([], max_tokens=0)
    with pytest.raises(AgentError):
        client.complete([], temperature=3)


def test_provider_json_repair_and_sdk_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider shares the repair engine; optional SDK setup stays guarded. Spec: SPEC-004 C3."""
    from types import SimpleNamespace

    from agent_harness.config import AgentError, Config
    from agent_harness.llm import AnthropicClient, OpenAIClient

    monkeypatch.setenv("P1_KEY", "dummy")
    config = Config.from_dict({"llm": {"api_key_env": "P1_KEY"}})
    sdk, calls = _scripted_sdk([_raw("bad"), _raw('{"fixed": 1}')])
    client = OpenAIClient(config, sdk=sdk)
    assert client.complete_json([], schema_hint="fixed: integer")[0] == {"fixed": 1}
    assert len(calls) == 2
    captured: list[dict[str, Any]] = []

    def constructor(**kwargs: Any) -> object:
        captured.append(kwargs)
        return object()

    monkeypatch.setattr(
        "agent_harness.llm.providers.importlib.import_module",
        lambda _: SimpleNamespace(Anthropic=constructor),
    )
    assert isinstance(AnthropicClient(config), AnthropicClient)
    assert captured[0]["max_retries"] == 0
    with pytest.raises(AgentError, match="initialize"):
        OpenAIClient(config)


def test_mock_script_errors_and_return_type_contract() -> None:
    """Script failures remain structured; return annotations match. Spec: SPEC-004 §1."""
    from typing import get_args, get_type_hints

    from agent_harness.config import AgentError
    from agent_harness.llm import MockLLMClient

    error = AgentError(code="LLM_CALL_FAILED", message="script", component="llm")
    with pytest.raises(AgentError, match="script"):
        MockLLMClient([error]).complete([])
    with pytest.raises(AgentError, match="not JSON serializable"):
        MockLLMClient([object()]).complete([])
    for cls in [LLMClient, MockLLMClient]:
        assert get_type_hints(cls.complete)["return"] is LLMResponse
        assert get_args(get_type_hints(cls.complete_json)["return"])[1] is LLMResponse


@pytest.fixture(autouse=True)
def _offline_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject network access and isolate ambient overrides. Spec: SPEC-000 §5."""

    def reject(*args: object, **kwargs: object) -> None:
        raise AssertionError("Live network calls are forbidden in P1 unit tests")

    monkeypatch.setattr("socket.socket.connect", reject)
    monkeypatch.setattr("socket.socket.connect_ex", reject)
    monkeypatch.setattr("socket.create_connection", reject)
    for key in (
        "AGENT_HARNESS_CONFIG",
        "AGENT_HARNESS_LOG_LEVEL",
        "AGENT_HARNESS_OUTPUT_DIR",
    ):
        monkeypatch.delenv(key, raising=False)
