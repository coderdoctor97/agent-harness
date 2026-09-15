"""Provider-neutral completion contracts. Spec: SPEC-004 §1."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from agent_harness.config import AgentError, sensitive_data_filter


@dataclass
class LLMResponse:
    """Normalized provider response; never contains credentials. Spec: SPEC-004 §1."""

    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str
    latency_ms: int
    redactions: int = 0

    @property
    def metadata(self) -> dict[str, int]:
        """Expose outbound redaction accounting. Spec: SPEC-004 §1.2 C4."""
        return {"redactions": self.redactions}


@dataclass
class LLMUsage:
    """Cumulative lifetime usage counters. Spec: SPEC-004 §1."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost: float = 0.0


class LLMClient(ABC):
    """The single LLM boundary consumed by all plans. Spec: SPEC-004 §1."""

    @abstractmethod
    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Complete a conversation using optional per-call settings. Spec: SPEC-004 §1."""
        raise NotImplementedError

    @abstractmethod
    def complete_json(
        self,
        messages: list[dict[str, Any]],
        *,
        schema_hint: str = "",
        temperature: float | None = None,
    ) -> tuple[Any, LLMResponse]:
        """Return decoded JSON and its provider response. Spec: SPEC-004 §1."""
        raise NotImplementedError

    @property
    @abstractmethod
    def usage(self) -> LLMUsage:
        """Return lifetime counters. Spec: SPEC-004 §1."""
        raise NotImplementedError


class MockLLMClient(LLMClient):
    """Scripted offline gateway with deterministic counters. Spec: SPEC-004 §1.2 C7."""

    def __init__(
        self, responses: Sequence[object] = (), *, raise_on_call: int | None = None
    ) -> None:
        """Queue strings, JSON payloads, responses or AgentError instances. Spec: SPEC-004 C7."""
        self._responses = deque(deepcopy(responses))
        self._usage = LLMUsage()
        self._raise_on_call = raise_on_call
        self.requests: list[list[dict[str, Any]]] = []

    @property
    def usage(self) -> LLMUsage:
        """Return a defensive snapshot of cumulative usage. Spec: SPEC-004 C5, C7."""
        return deepcopy(self._usage)

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Consume exactly one scripted item; exhaustion is explicit. Spec: SPEC-004 C7."""
        self._usage.calls += 1
        prepared, redactions = _prepare_messages(messages)
        self.requests.append(prepared)
        if self._usage.calls == self._raise_on_call:
            raise AgentError("LLM_CALL_FAILED", "Injected mock failure", "llm")
        if not self._responses:
            raise AgentError("LLM_CALL_FAILED", "Mock response queue exhausted", "llm")
        item = self._responses.popleft()
        if isinstance(item, AgentError):
            raise item
        if isinstance(item, LLMResponse):
            response = deepcopy(item)
        else:
            try:
                text = (
                    item
                    if isinstance(item, str)
                    else json.dumps(item, ensure_ascii=False, allow_nan=False)
                )
            except (TypeError, ValueError):
                raise AgentError(
                    "LLM_CALL_FAILED",
                    "Mock script item is not JSON serializable",
                    "llm",
                ) from None
            response = LLMResponse(
                text,
                "mock",
                sum(len(str(m.get("content", "")).split()) for m in messages),
                len(text.split()),
                "stop",
                0,
            )
        response.redactions += redactions
        self._usage.prompt_tokens += response.prompt_tokens
        self._usage.completion_tokens += response.completion_tokens
        return response

    def complete_json(
        self,
        messages: list[dict[str, Any]],
        *,
        schema_hint: str = "",
        temperature: float | None = None,
    ) -> tuple[Any, LLMResponse]:
        """Decode a scripted JSON response. Spec: SPEC-004 C3, C7."""
        return _complete_json(
            self, messages, schema_hint=schema_hint, temperature=temperature
        )


def _prepare_messages(
    messages: list[dict[str, Any]],
    patterns: Sequence[str] | None = None,
    secrets: Sequence[str] = (),
) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(messages, list):
        raise AgentError("LLM_CALL_FAILED", "Messages must be a list", "llm")
    prepared: list[dict[str, Any]] = []
    count = 0
    for message in messages:
        if (
            not isinstance(message, dict)
            or message.get("role") not in ("system", "user", "assistant")
            or not isinstance(message.get("content"), str)
        ):
            raise AgentError(
                "LLM_CALL_FAILED", "Invalid message role or content", "llm"
            )
        content, redactions = sensitive_data_filter(
            message["content"], patterns, secrets=secrets
        )
        prepared.append({"role": message["role"], "content": content})
        count += redactions
    return prepared, count


def _reject_constant(value: str) -> None:
    raise ValueError("Non-finite JSON value")


def _complete_json(
    client: LLMClient,
    messages: list[dict[str, Any]],
    *,
    schema_hint: str,
    temperature: float | None,
) -> tuple[Any, LLMResponse]:
    # Validation happens before editing so invalid payloads never become provider calls.
    _prepare_messages(messages)
    conversation = deepcopy(messages)
    instruction = "Return valid JSON only. " + schema_hint
    system = next((m for m in conversation if m["role"] == "system"), None)
    if system is None:
        conversation.insert(0, {"role": "system", "content": instruction})
    else:
        system["content"] += "\n" + instruction
    for attempt in range(2):
        response = client.complete(conversation, temperature=temperature)
        text = response.text.strip()
        fence = re.fullmatch(
            r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE
        )
        if fence:
            text = fence.group(1)
        try:
            return json.loads(text, parse_constant=_reject_constant), response
        except ValueError as exc:
            if attempt == 1:
                raise AgentError(
                    "PLAN_PARSE_FAILED", "JSON repair failed", "llm"
                ) from None
            conversation.extend(
                [
                    {"role": "assistant", "content": response.text},
                    {
                        "role": "user",
                        "content": f"JSON parsing failed ({type(exc).__name__}). Correct the previous output and return JSON only.",
                    },
                ]
            )
    raise AssertionError("unreachable JSON repair state")
