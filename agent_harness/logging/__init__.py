"""Public injected observability. Spec: SPEC-006 §6–7."""

from .logger import StructuredLogger
from .report import render_report

__all__ = ["StructuredLogger", "render_report"]
