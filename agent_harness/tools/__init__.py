"""Tool package public surface.

Spec: SPEC-002 §2
"""

from __future__ import annotations

from typing import Any

from agent_harness.tools.base import (
    BaseTool,
    ToolRegistry,
    ToolResult,
    fail,
    ok,
    run_tool,
)
from agent_harness.tools.code_execute import CodeExecuteTool
from agent_harness.tools.csv_process import CsvProcessTool
from agent_harness.tools.file_read import FileReadTool
from agent_harness.tools.file_write import FileWriteTool
from agent_harness.tools.llm_extract import LlmExtractTool
from agent_harness.tools.llm_synthesize import LlmSynthesizeTool
from agent_harness.tools.pdf_export import PdfExportTool
from agent_harness.tools.shell_command import ShellCommandTool
from agent_harness.tools.web_scrape import WebScrapeTool
from agent_harness.tools.web_search import WebSearchTool

__all__ = [
    "BaseTool",
    "ToolRegistry",
    "ToolResult",
    "default_tools",
    "fail",
    "ok",
    "run_tool",
]


def default_tools(config: Any = None, llm_client: Any = None) -> list[BaseTool]:
    """Return instances of all built-in tools.

    Spec: SPEC-002 §2 default_tools(config, llm_client).

    Tools that require LLM (code_execute, llm_extract, llm_synthesize) receive
    llm_client. All tools receive config for duck-typed security/output settings.
    PdfExportTool is always included (degrades to markdown if wkhtmltopdf missing).
    ShellCommandTool is always included but inert unless security.allow_shell true.
    """
    return [
        WebSearchTool(config=config),
        WebScrapeTool(config=config),
        CodeExecuteTool(config=config, llm_client=llm_client),
        FileReadTool(config=config),
        FileWriteTool(config=config),
        LlmExtractTool(config=config, llm_client=llm_client),
        LlmSynthesizeTool(config=config, llm_client=llm_client),
        PdfExportTool(config=config),
        CsvProcessTool(config=config),
        ShellCommandTool(config=config),
    ]
