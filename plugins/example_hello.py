"""A minimal example plugin — the shape from the Developer README.

Copy this file into any directory listed under ``plugins.dirs`` in
``config.yaml`` and the harness discovers ``HelloTool`` on the next start.
Nothing here is imported by the package: the plugin loader executes the file
under the synthetic module name ``agent_harness_plugin_example_hello``.

Spec: SPEC-005 § 3.1 · Developer README § Writing Custom Tools
"""

from __future__ import annotations

from typing import Any

from agent_harness.tools.base import BaseTool, ToolResult


# The type: ignore below is temporary and listed on the 5.1 swap checklist:
# agent_harness.tools.base is Plan 2's module and does not exist until integration
# window step I1, so mypy sees BaseTool as Any. Remove it once Plan 2 has landed.
class HelloTool(BaseTool):  # type: ignore[misc]
    """A simple example tool that greets the user.

    Zero-argument constructor, so the loader instantiates it directly
    (SPEC-005 § 3 step 4, first convention).
    """

    @property
    def name(self) -> str:
        """Unique snake_case identifier (SPEC-002 R6)."""
        return "hello"

    @property
    def description(self) -> str:
        """Written for LLM consumption (SPEC-002 R7)."""
        return "Says hello with a custom message. Use for testing."

    @property
    def capabilities(self) -> list[str]:
        """Capability tags used for capability-based lookup."""
        return ["greeting", "testing"]

    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str]:
        """Anything is acceptable; ``name`` simply defaults to ``World``."""
        if not isinstance(input_data, dict):
            return False, "Input must be a dict"
        name = input_data.get("name", "World")
        if not isinstance(name, str):
            return False, "'name' must be a string"
        return True, ""

    def execute(
        self,
        input_data: dict[str, Any],
        context: dict[str, Any],  # noqa: ARG002 - signature fixed by SPEC-002 R1
    ) -> ToolResult:
        """Greet ``input_data['name']``.

        Args:
            input_data: optional ``name`` key.
            context: the run context; this tool needs nothing from it.

        Returns:
            A successful :class:`ToolResult` carrying the greeting.
        """
        is_valid, error_msg = self.validate_input(input_data)
        if not is_valid:
            return ToolResult(success=False, error=error_msg)
        name = input_data.get("name", "World")
        message = f"Hello, {name}! The agent harness is working."
        return ToolResult(success=True, output=message, metadata={"greeted": name})

    def cleanup(self) -> None:
        """Nothing to release (SPEC-002 R8 keeps this idempotent)."""
