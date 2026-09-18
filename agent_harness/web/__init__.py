"""Local web UI for the agent harness (PRD goal G8).

A thin FastAPI surface over the same :class:`agent_harness.harness.AgentHarness`
the CLI uses: submit a task, watch SPEC-003 § 2.1's progress hook stream, read
the assembled deliverable and browse the files the run produced.

The package is optional. ``agent_harness`` itself never imports it, and it is
installed through the ``web`` extra::

    pip install "agent-harness[web]"

Importing this package is cheap and imports no server code; reach for
:mod:`agent_harness.web.app` (ASGI app) or :mod:`agent_harness.web.server`
(launcher) explicitly, or run ``python -m agent_harness.web``.

Example:
    >>> from agent_harness.web.schemas import TaskRequest       # doctest: +SKIP
    >>> TaskRequest(prompt="write a haiku").prompt              # doctest: +SKIP
    'write a haiku'

Spec: SPEC-003 § 2.1 (progress seam) · SPEC-005 § 1 (harness API) · PRD G8
"""

from __future__ import annotations

__all__ = ["__version__"]

#: Tracks the package version; the web layer has no release cadence of its own.
__version__ = "0.1.0"
