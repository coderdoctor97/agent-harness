"""LLM extract tool.

Spec: SPEC-002 §3.6
"""

from __future__ import annotations

import json
import time
from typing import Any

from agent_harness.tools.base import BaseTool, ToolResult


def _get_llm_client(configured: Any, context: dict[str, Any]) -> Any | None:
    if configured is not None:
        return configured
    # Fallback to context
    if isinstance(context, dict):
        # Try llm_client, llm, or client
        for key in ("llm_client", "llm", "client"):
            if key in context and context[key] is not None:
                return context[key]
        # Also check nested context variables?
        # Some harnesses store in context["variables"]["llm_client"]
        vars_dict = context.get("variables")
        if isinstance(vars_dict, dict):
            for key in ("llm_client", "llm"):
                if key in vars_dict and vars_dict[key] is not None:
                    return vars_dict[key]
    return None


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        # Remove first line fence and last fence
        parts = t.split("\n", 1)
        if len(parts) == 2:
            t = parts[1]
        # Remove trailing fence
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3].strip()
            # If first fence had language like ```json, remove that
        # Also handle case where fence contains json
        t = t.strip()
        # Remove possible leading language tag leftover
        if t.startswith("json"):
            t = t[4:].strip()
    return t


class LlmExtractTool(BaseTool):
    """LLM extract tool per SPEC-002 §3.6."""

    def __init__(self, config: Any = None, llm_client: Any = None) -> None:
        self._config = config
        self._llm_client = llm_client

    @property
    def name(self) -> str:
        return "llm_extract"

    @property
    def description(self) -> str:
        return (
            "Extracts structured data via LLM. Input: {input_text: str, instruction: str, "
            "output_format: json|text|markdown (default text)}. Output: parsed object or str."
        )

    @property
    def capabilities(self) -> list[str]:
        return ["llm", "extract", "transform"]

    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str]:
        if "input_text" not in input_data:
            return False, "Missing required 'input_text'"
        if "instruction" not in input_data:
            return False, "Missing required 'instruction'"
        if not isinstance(input_data["input_text"], str):
            return False, "'input_text' must be a string"
        if (
            not isinstance(input_data["instruction"], str)
            or not input_data["instruction"].strip()
        ):
            return False, "'instruction' must be a non-empty string"
        if "output_format" in input_data and input_data["output_format"] not in (
            "json",
            "text",
            "markdown",
        ):
            return False, "'output_format' must be 'json', 'text', or 'markdown'"
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

        input_text: str = str(input_data["input_text"])
        instruction: str = str(input_data["instruction"])
        output_format: str = str(input_data.get("output_format", "text"))

        llm = _get_llm_client(self._llm_client, context)
        if llm is None:
            return ToolResult(
                success=False,
                error="TOOL_EXECUTION_FAILED: llm_extract requires an llm_client (constructor or context['llm_client'])",
                metadata={
                    "tool_name": self.name,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                    "retryable": False,
                },
            )

        # Build messages
        prompt = f"Instruction: {instruction}\n\nText:\n{input_text}\n\n"
        if output_format == "json":
            prompt += "Respond with valid JSON only, no fences, no extra text."
        elif output_format == "markdown":
            prompt += "Respond in markdown format."
        else:
            prompt += "Respond in plain text."

        messages = [{"role": "user", "content": prompt}]

        try:
            # Try to use complete_json for json format if available
            if output_format == "json" and hasattr(llm, "complete_json"):
                try:
                    data, resp = llm.complete_json(messages)
                    # Ensure we handle both tuple and single return
                    if isinstance(data, tuple):
                        # In case complete_json returns (data, resp) but data is tuple?
                        pass
                    duration_ms = int((time.monotonic() - start) * 1000)
                    return ToolResult(
                        success=True,
                        output=data,
                        metadata={"tool_name": self.name, "duration_ms": duration_ms},
                    )
                except Exception:  # noqa: BLE001, S110
                    # Fallback to complete and parse
                    pass

            # Generic complete
            if hasattr(llm, "complete"):
                resp = llm.complete(messages)
                text = getattr(resp, "text", str(resp))
            elif callable(llm):
                # If llm is callable
                resp = llm(messages)
                text = getattr(resp, "text", str(resp))
            else:
                return ToolResult(
                    success=False,
                    error="TOOL_EXECUTION_FAILED: llm_client does not have complete method",
                    metadata={
                        "tool_name": self.name,
                        "duration_ms": int((time.monotonic() - start) * 1000),
                        "retryable": False,
                    },
                )

            if output_format == "json":
                # Parse JSON
                cleaned = _strip_fences(str(text))
                try:
                    data = json.loads(cleaned)
                except json.JSONDecodeError as exc:
                    return ToolResult(
                        success=False,
                        error=f"TOOL_EXECUTION_FAILED: JSON parse failed: {exc} (raw: {text[:200]})",
                        metadata={
                            "tool_name": self.name,
                            "duration_ms": int((time.monotonic() - start) * 1000),
                            "retryable": False,
                        },
                    )
                duration_ms = int((time.monotonic() - start) * 1000)
                return ToolResult(
                    success=True,
                    output=data,
                    metadata={"tool_name": self.name, "duration_ms": duration_ms},
                )
            else:
                duration_ms = int((time.monotonic() - start) * 1000)
                return ToolResult(
                    success=True,
                    output=str(text),
                    metadata={"tool_name": self.name, "duration_ms": duration_ms},
                )

        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                error=f"LLM extract failed: {exc}",
                metadata={
                    "tool_name": self.name,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                    "retryable": False,
                },
            )
