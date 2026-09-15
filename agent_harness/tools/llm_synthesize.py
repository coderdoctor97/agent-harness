"""LLM synthesize tool.

Spec: SPEC-002 §3.7
"""

from __future__ import annotations

import time
from typing import Any

from agent_harness.tools.base import BaseTool, ToolResult


def _get_llm_client(configured: Any, context: dict[str, Any]) -> Any | None:
    if configured is not None:
        return configured
    if isinstance(context, dict):
        for key in ("llm_client", "llm", "client"):
            if key in context and context[key] is not None:
                return context[key]
        vars_dict = context.get("variables")
        if isinstance(vars_dict, dict):
            for key in ("llm_client", "llm"):
                if key in vars_dict and vars_dict[key] is not None:
                    return vars_dict[key]
    return None


def _resolve_sources(
    sources: list[str], context: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Resolve sources per SPEC-002 §3.7.

    Returns (resolved_texts, unresolved).
    """
    resolved: list[str] = []
    unresolved: list[str] = []
    step_results = context.get("step_results") if isinstance(context, dict) else None
    variables = context.get("variables") if isinstance(context, dict) else None
    if not isinstance(step_results, dict):
        step_results = {}
    if not isinstance(variables, dict):
        variables = {}

    for src in sources:
        if not isinstance(src, str):
            unresolved.append(str(src))
            continue
        # Try step_results: s could be step_id like "step_1" or "step_1_output"
        # We check direct key, and also with suffix handling
        found = False
        # Check step_results directly
        if src in step_results:
            val = step_results[src]
            if isinstance(val, dict) and "output" in val:
                resolved.append(str(val["output"]))
            else:
                resolved.append(str(val))
            found = True
        elif variables and src in variables:
            resolved.append(str(variables[src]))
            found = True
        elif isinstance(context, dict) and src in context:
            # Direct context key (e.g., "step_1_output" stored directly)
            # Avoid treating llm_client etc as source; but if present, use it
            val2 = context[src]
            # If val2 is llm_client, don't use
            if src not in ("llm_client", "llm", "client", "variables", "step_results"):
                resolved.append(str(val2))
                found = True
            else:
                # Don't consider llm_client as resolvable source
                found = False
        # Also try variables with step_id prefix? For "step_1_output", maybe step_results contains "step_1"
        if not found:  # noqa: SIM102
            # Try to handle "step_1_output" -> "step_1"
            if src.endswith("_output") and src[:-7] in step_results:
                val = step_results[src[:-7]]
                if isinstance(val, dict) and "output" in val:
                    resolved.append(str(val["output"]))
                else:
                    resolved.append(str(val))
                found = True

        if not found:
            # Literal fallback: use src itself as literal content
            # But per spec, we should track unresolved
            resolved.append(src)
            unresolved.append(src)

    return resolved, unresolved


class LlmSynthesizeTool(BaseTool):
    """LLM synthesize tool per SPEC-002 §3.7."""

    def __init__(self, config: Any = None, llm_client: Any = None) -> None:
        self._config = config
        self._llm_client = llm_client

    @property
    def name(self) -> str:
        return "llm_synthesize"

    @property
    def description(self) -> str:
        return (
            "Synthesizes content via LLM. Input: {instruction: str, sources: list[str], "
            "tone: str (optional), max_words: int (optional)}. Output: str with unresolved tracking."
        )

    @property
    def capabilities(self) -> list[str]:
        return ["llm", "synthesize", "generate"]

    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str]:
        if "instruction" not in input_data:
            return False, "Missing required 'instruction'"
        if (
            not isinstance(input_data["instruction"], str)
            or not input_data["instruction"].strip()
        ):
            return False, "'instruction' must be a non-empty string"
        if "sources" in input_data:
            src = input_data["sources"]
            if not isinstance(src, list):
                return False, "'sources' must be a list"
            for item in src:
                if not isinstance(item, str):
                    return False, "Each source must be a string"
        if "tone" in input_data and not isinstance(input_data["tone"], str):
            return False, "'tone' must be a string"
        if "max_words" in input_data:
            mw = input_data["max_words"]
            if not isinstance(mw, int) or mw <= 0:
                return False, "'max_words' must be a positive int"
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

        instruction: str = str(input_data["instruction"])
        sources: list[str] = list(input_data.get("sources", []))
        tone: str | None = input_data.get("tone")
        max_words: int | None = input_data.get("max_words")

        llm = _get_llm_client(self._llm_client, context)
        if llm is None:
            return ToolResult(
                success=False,
                error="TOOL_EXECUTION_FAILED: llm_synthesize requires an llm_client (constructor or context['llm_client'])",
                metadata={
                    "tool_name": self.name,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                    "retryable": False,
                },
            )

        # Resolve sources
        resolved_texts, unresolved = _resolve_sources(
            sources, context if isinstance(context, dict) else {}
        )

        # Build prompt
        prompt_parts: list[str] = [f"Instruction: {instruction}"]
        if tone:
            prompt_parts.append(f"Tone: {tone}")
        if max_words:
            prompt_parts.append(f"Max words: {max_words}")
        if resolved_texts:
            prompt_parts.append("\nSources:")
            for idx, txt in enumerate(resolved_texts, 1):
                prompt_parts.append(f"Source {idx}:\n{txt}\n")
        prompt_parts.append("\nGenerate the requested content.")
        prompt = "\n".join(prompt_parts)

        messages = [{"role": "user", "content": prompt}]

        try:
            if hasattr(llm, "complete"):
                resp = llm.complete(messages)
                text = getattr(resp, "text", str(resp))
            elif callable(llm):
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

            # Enforce max_words if provided (truncate)
            output = str(text)
            if max_words is not None:
                words = output.split()
                if len(words) > max_words:
                    output = " ".join(words[:max_words])

            duration_ms = int((time.monotonic() - start) * 1000)
            metadata: dict[str, Any] = {
                "tool_name": self.name,
                "duration_ms": duration_ms,
            }
            if unresolved:
                metadata["unresolved_sources"] = unresolved

            return ToolResult(success=True, output=output, metadata=metadata)

        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                error=f"LLM synthesize failed: {exc}",
                metadata={
                    "tool_name": self.name,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                    "retryable": False,
                },
            )
