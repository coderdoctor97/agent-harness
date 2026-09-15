"""Provider adapters behind one injected completion boundary. Spec: SPEC-004 §1.3."""

from __future__ import annotations

import importlib
import math
import os
import time
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from agent_harness.config import AgentError, Config
from agent_harness.logging import StructuredLogger

from .client import LLMClient, LLMResponse, LLMUsage, _complete_json, _prepare_messages


class _ProviderClient(LLMClient):
    def __init__(
        self,
        config: Config,
        *,
        sdk: object | None = None,
        logger: StructuredLogger | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Inject SDK, logger and clocks; defer credential lookup. Spec: SPEC-004 §1.3."""
        self._config = deepcopy(config)
        self._usage = LLMUsage()
        self._logger = logger or StructuredLogger.default()
        self._sleep, self._clock = sleep, clock
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._api_key = os.environ.get(config.llm.api_key_env, "")
        if not self._api_key:
            raise AgentError(
                "CONFIG_VALIDATION_FAILED",
                f"Missing API key environment variable: {config.llm.api_key_env}",
                "config",
            )
        try:
            self._sdk: Any = sdk if sdk is not None else self._build_sdk()
        except AgentError:
            raise
        except Exception:
            raise AgentError(
                "CONFIG_VALIDATION_FAILED",
                "Unable to initialize provider SDK",
                "config",
            ) from None

    def _build_sdk(self) -> object:
        raise NotImplementedError

    def _request(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        raise NotImplementedError

    @property
    def usage(self) -> LLMUsage:
        """Return a defensive snapshot of lifetime counters. Spec: SPEC-004 C5."""
        return deepcopy(self._usage)

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Retry transient calls, fallback once, account and redact. Spec: SPEC-004 C1–C6."""
        temperature = (
            self._config.llm.temperature if temperature is None else temperature
        )
        max_tokens = self._config.llm.max_tokens if max_tokens is None else max_tokens
        if (
            type(max_tokens) is not int
            or max_tokens <= 0
            or type(temperature) not in (int, float)
            or not math.isfinite(temperature)
            or not 0 <= temperature <= 2
        ):
            raise AgentError("LLM_CALL_FAILED", "Invalid completion settings", "llm")
        prepared, redactions = _prepare_messages(
            messages, self._config.security.sensitive_patterns, (self._api_key,)
        )
        model = self._config.llm.model
        fallback = self._config.llm.fallback_model
        using_fallback = False
        while True:
            limit = 0 if using_fallback else self._config.llm.max_retries
            for attempt in range(limit + 1):
                self._usage.calls += 1
                started = self._clock()
                response: LLMResponse | None = None
                transient, status, retry_after = False, None, None
                try:
                    response = self._request(
                        deepcopy(prepared), model, temperature, max_tokens
                    )
                except Exception as exc:
                    transient, status, retry_after = self._classify_failure(exc)
                elapsed = max(0, int((self._clock() - started) * 1000))
                if response is not None:
                    response.latency_ms = elapsed
                    response.redactions = redactions
                    self._usage.prompt_tokens += response.prompt_tokens
                    self._usage.completion_tokens += response.completion_tokens
                    self._usage.estimated_cost += (
                        (response.prompt_tokens + response.completion_tokens)
                        * (self._config.llm.cost_per_1k_tokens or 0.0)
                        / 1000
                    )
                success = response is not None and response.finish_reason not in (
                    "content_filter",
                    "error",
                )
                self._logger.info(
                    "llm",
                    "llm_call",
                    duration_ms=elapsed,
                    llm_tokens_used=(
                        response.prompt_tokens + response.completion_tokens
                    )
                    if response
                    else 0,
                    metadata={
                        "model": model,
                        "finish_reason": response.finish_reason
                        if response
                        else "error",
                        "redactions": redactions,
                        "attempt": attempt + 1,
                        "fallback": using_fallback,
                    },
                )
                if success and response is not None:
                    return response
                if transient and attempt < limit:
                    self._sleep(self._retry_delay(attempt, retry_after))
                    continue
                if not transient and fallback and not using_fallback:
                    model, using_fallback = fallback, True
                    break
                code = "LLM_RATE_LIMITED" if status == 429 else "LLM_CALL_FAILED"
                raise AgentError(
                    code,
                    "Provider request failed after allowed attempts",
                    "llm",
                    recoverable=transient,
                ) from None

    @staticmethod
    def _classify_failure(exc: Exception) -> tuple[bool, int | None, str | None]:
        code = getattr(exc, "status_code", None)
        status = code if type(code) is int else None
        transient = (
            isinstance(exc, TimeoutError)
            or "timeout" in type(exc).__name__.lower()
            or status == 429
            or (status is not None and 500 <= status <= 599)
        )
        headers = getattr(getattr(exc, "response", None), "headers", {})
        retry_after = (
            headers.get("retry-after", headers.get("Retry-After"))
            if hasattr(headers, "get")
            else None
        )
        return transient, status, str(retry_after) if retry_after is not None else None

    def _retry_delay(self, attempt: int, retry_after: str | None) -> float:
        delay = float(2**attempt)
        if retry_after is None:
            return delay
        try:
            seconds = float(retry_after)
        except ValueError:
            try:
                date = parsedate_to_datetime(retry_after)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                seconds = (date - self._wall_clock()).total_seconds()
            except (ValueError, TypeError, OverflowError):
                return delay
        return max(delay, seconds) if math.isfinite(seconds) else delay

    def complete_json(
        self,
        messages: list[dict[str, Any]],
        *,
        schema_hint: str = "",
        temperature: float | None = None,
    ) -> tuple[Any, LLMResponse]:
        """Parse fenced JSON with exactly one repair round. Spec: SPEC-004 C3."""
        return _complete_json(
            self, messages, schema_hint=schema_hint, temperature=temperature
        )


class OpenAIClient(_ProviderClient):
    """Official OpenAI SDK adapter, including proxy endpoints. Spec: SPEC-004 §1.3."""

    def _build_sdk(self) -> object:
        module = importlib.import_module("openai")
        return module.OpenAI(
            api_key=self._api_key,
            base_url=self._config.llm.base_url,
            timeout=self._config.llm.timeout,
            max_retries=0,
        )

    def _request(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        raw = self._sdk.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        choice = raw.choices[0]
        text = choice.message.content
        if text is None and choice.finish_reason == "content_filter":
            text = ""
        if not isinstance(text, str):
            raise ValueError("Provider returned no text")
        usage = raw.usage
        return LLMResponse(
            text,
            str(raw.model),
            int(usage.prompt_tokens) if usage else 0,
            int(usage.completion_tokens) if usage else 0,
            str(choice.finish_reason)
            if choice.finish_reason in {"stop", "length", "content_filter", "error"}
            else "error",
            0,
        )


class LocalCompatClient(OpenAIClient):
    """OpenAI-compatible local endpoint with nonempty key indirection. Spec: SPEC-004 §1.3."""


class AnthropicClient(_ProviderClient):
    """Optional Anthropic SDK with system-message translation. Spec: SPEC-004 §1.3."""

    def _build_sdk(self) -> object:
        try:
            module = importlib.import_module("anthropic")
        except ImportError:
            raise AgentError(
                "CONFIG_VALIDATION_FAILED",
                "Install agent-harness[anthropic] to use this provider",
                "config",
            ) from None
        return module.Anthropic(
            api_key=self._api_key,
            base_url=self._config.llm.base_url,
            timeout=self._config.llm.timeout,
            max_retries=0,
        )

    def _request(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        system = "\n\n".join(
            str(m["content"]) for m in messages if m["role"] == "system"
        )
        conversation = [m for m in messages if m["role"] != "system"]
        raw = self._sdk.messages.create(
            model=model,
            system=system,
            messages=conversation,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = "".join(
            str(block.text)
            for block in raw.content
            if getattr(block, "type", "text") == "text"
        )
        reason = {
            "end_turn": "stop",
            "stop_sequence": "stop",
            "max_tokens": "length",
        }.get(str(raw.stop_reason), "error")
        return LLMResponse(
            text,
            str(raw.model),
            int(raw.usage.input_tokens),
            int(raw.usage.output_tokens),
            reason,
            0,
        )


def create_llm_client(
    config: Config, *, logger: StructuredLogger | None = None
) -> LLMClient:
    """Select a provider and defer key resolution until construction. Spec: SPEC-004 §1.3."""
    providers = {
        "openai": OpenAIClient,
        "local": LocalCompatClient,
        "anthropic": AnthropicClient,
    }
    if config.llm.provider not in providers:
        raise AgentError("CONFIG_VALIDATION_FAILED", "Unknown LLM provider", "config")
    return providers[config.llm.provider](config, logger=logger)
