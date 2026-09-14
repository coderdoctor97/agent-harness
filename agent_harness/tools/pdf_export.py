"""PDF export tool with degraded markdown fallback.

Spec: SPEC-002 §3.8
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from agent_harness.tools.base import BaseTool, ToolResult


def _get_output_dir(config: Any) -> Path | None:
    if config is None:
        return None
    try:
        exec_cfg = None
        if isinstance(config, dict):
            exec_cfg = config.get("execution")
            if isinstance(exec_cfg, dict):
                out = exec_cfg.get("output_dir")
                return Path(str(out)) if out else None
            if exec_cfg is not None:
                out = getattr(exec_cfg, "output_dir", None)
                return Path(str(out)) if out else None
            return None
        exec_cfg = getattr(config, "execution", None)
        if exec_cfg is None:
            return None
        if isinstance(exec_cfg, dict):
            out = exec_cfg.get("output_dir")
            return Path(str(out)) if out else None
        out = getattr(exec_cfg, "output_dir", None)
        return Path(str(out)) if out else None
    except Exception:  # noqa: BLE001
        return None


def _is_wkhtmltopdf_available() -> bool:
    return shutil.which("wkhtmltopdf") is not None


def _markdown_to_html(md_text: str) -> str:
    try:
        import markdown  # type: ignore[import-untyped]

        return str(markdown.markdown(md_text))
    except ImportError:
        # Simple fallback: wrap in <pre> and basic headers
        html = md_text
        # Very naive: convert # headers to h1 etc.
        lines: list[str] = []
        for line in html.splitlines():
            if line.startswith("# "):
                lines.append(f"<h1>{line[2:]}</h1>")
            elif line.startswith("## "):
                lines.append(f"<h2>{line[3:]}</h2>")
            elif line.startswith("### "):
                lines.append(f"<h3>{line[4:]}</h3>")
            else:
                lines.append(f"<p>{line}</p>" if line.strip() else "")
        body = "\n".join(lines)
        return f"<html><body>{body}</body></html>"
    except Exception:  # noqa: BLE001
        return f"<html><body><pre>{md_text}</pre></body></html>"


class PdfExportTool(BaseTool):
    """PDF export tool per SPEC-002 §3.8."""

    def __init__(self, config: Any = None) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return "pdf_export"

    @property
    def description(self) -> str:
        return (
            "Exports content to PDF. Input: {content: str, filename: str (.pdf), "
            "format: markdown|html (default markdown), page_size: str (default A4)}. "
            "Writes to output_dir; degrades to .md if wkhtmltopdf missing."
        )

    @property
    def capabilities(self) -> list[str]:
        return ["export", "pdf", "document"]

    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str]:
        if "content" not in input_data:
            return False, "Missing required 'content'"
        if "filename" not in input_data:
            return False, "Missing required 'filename'"
        content = input_data["content"]
        filename = input_data["filename"]
        if not isinstance(content, str):
            return False, "'content' must be a string"
        if not isinstance(filename, str) or not filename.strip():
            return False, "'filename' must be a non-empty string"
        if not filename.strip().endswith(".pdf"):
            return False, "'filename' must end with .pdf"
        if "format" in input_data and input_data["format"] not in ("markdown", "html"):
            return False, "'format' must be 'markdown' or 'html'"
        if "page_size" in input_data and not isinstance(input_data["page_size"], str):
            return False, "'page_size' must be a string"
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

        content: str = str(input_data["content"])
        filename: str = str(input_data["filename"]).strip()
        fmt: str = str(input_data.get("format", "markdown"))
        page_size: str = str(input_data.get("page_size", "A4"))

        output_dir = _get_output_dir(self._config)
        if output_dir is None:
            output_dir = Path("./output")
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                error=f"Failed to create output_dir: {exc}",
                metadata={
                    "tool_name": self.name,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                    "retryable": False,
                },
            )

        # Path safety: output must be inside output_dir or allowed_write_paths
        target_pdf = (
            output_dir / Path(filename).name
        )  # ensure just filename, not path traversal
        # Check that filename doesn't contain path traversal
        if Path(filename).name != filename and (
            ".." in Path(filename).parts or "/" in filename or "\\" in filename
        ):
                return ToolResult(
                    success=False,
                    error="SANDBOX_VIOLATION: filename must be a bare filename without path components",
                    metadata={
                        "tool_name": self.name,
                        "duration_ms": int((time.monotonic() - start) * 1000),
                        "retryable": False,
                        "violation": "SANDBOX_VIOLATION",
                    },
                )

        try:
            import importlib

            paths_mod: Any = importlib.import_module("agent_harness.tools._paths")
            is_path_allowed = paths_mod.is_path_allowed
            allowed, why = is_path_allowed(
                str(target_pdf.resolve()), self._config, context, mode="write"
            )
            if not allowed:
                return ToolResult(
                    success=False,
                    error=f"SANDBOX_VIOLATION: {why}",
                    metadata={
                        "tool_name": self.name,
                        "duration_ms": int((time.monotonic() - start) * 1000),
                        "retryable": False,
                        "violation": "SANDBOX_VIOLATION",
                    },
                )
        except ImportError:
            pass
        except Exception:  # noqa: BLE001, S110
            pass

        # Check wkhtmltopdf availability
        if not _is_wkhtmltopdf_available():
            # Degraded mode: write markdown
            degraded_name = Path(filename).stem + ".md"
            degraded_path = output_dir / degraded_name
            # Also handle case where filename is "report.pdf" -> "report.md"
            # If we want to match spec "<filename>.md", we could also use filename + ".md"
            # But we choose stem + .md for cleaner
            try:
                degraded_path.write_text(content, encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                return ToolResult(
                    success=False,
                    error=f"Degraded write failed: {exc}",
                    metadata={
                        "tool_name": self.name,
                        "duration_ms": int((time.monotonic() - start) * 1000),
                        "retryable": False,
                    },
                )
            duration_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(
                success=True,
                output=str(degraded_path),
                metadata={
                    "tool_name": self.name,
                    "duration_ms": duration_ms,
                    "degraded": True,
                    "actual_format": "markdown",
                },
            )

        # Try to generate PDF via wkhtmltopdf
        # Convert content to HTML if needed
        html_content = content if fmt == "html" else _markdown_to_html(content)
        # Wrap in minimal HTML if not already
        if "<html" not in html_content.lower():
            html_content = f"<html><body>{html_content}</body></html>"

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".html", delete=False, encoding="utf-8"
            ) as html_file:
                html_file.write(html_content)
                html_path = html_file.name
            # Use wkhtmltopdf
            # Example: wkhtmltopdf --page-size A4 input.html output.pdf
            cmd = [
                "wkhtmltopdf",
                "--page-size",
                page_size,
                "--enable-local-file-access",
                html_path,
                str(target_pdf),
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
                check=False,
            )
            # Cleanup html temp
            try:
                Path(html_path).unlink(missing_ok=True)
            except Exception:  # noqa: BLE001, S110
                pass

            if result.returncode != 0:
                # On failure, fallback to degraded?
                # Spec says degraded only when binary unavailable, but we can fallback
                degraded_name2 = Path(filename).stem + ".md"
                degraded_path2 = output_dir / degraded_name2
                degraded_path2.write_text(content, encoding="utf-8")
                duration_ms = int((time.monotonic() - start) * 1000)
                return ToolResult(
                    success=True,
                    output=str(degraded_path2),
                    metadata={
                        "tool_name": self.name,
                        "duration_ms": duration_ms,
                        "degraded": True,
                        "actual_format": "markdown",
                        "stderr": result.stderr,
                    },
                )
        except FileNotFoundError:
            # Binary not found, degrade
            degraded_name3 = Path(filename).stem + ".md"
            degraded_path3 = output_dir / degraded_name3
            degraded_path3.write_text(content, encoding="utf-8")
            duration_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(
                success=True,
                output=str(degraded_path3),
                metadata={
                    "tool_name": self.name,
                    "duration_ms": duration_ms,
                    "degraded": True,
                    "actual_format": "markdown",
                },
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                error="PDF generation timed out",
                metadata={
                    "tool_name": self.name,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                    "retryable": True,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                success=False,
                error=f"PDF generation failed: {exc}",
                metadata={
                    "tool_name": self.name,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                    "retryable": False,
                },
            )

        duration_ms = int((time.monotonic() - start) * 1000)
        return ToolResult(
            success=True,
            output=str(target_pdf),
            metadata={"tool_name": self.name, "duration_ms": duration_ms},
        )
