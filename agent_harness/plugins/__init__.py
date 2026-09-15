"""Plugin auto-discovery — drop a ``BaseTool`` file into a directory, get it registered.

Public entry point:

.. code-block:: python

    from agent_harness.plugins import discover_tools

    dirs = config.plugins.dirs
    tools, errors = discover_tools(dirs, config=config, llm_client=client)

Spec: SPEC-005 § 3
"""

from __future__ import annotations

from agent_harness.plugins.loader import discover_tools

__all__ = ["discover_tools"]
