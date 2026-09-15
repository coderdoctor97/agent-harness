"""Agent Harness — the L3 surface package.

``import agent_harness`` must never fail because an *optional* dependency (``rich``,
``openai``, ``anthropic``, ``pdfkit``, …) is missing, so every heavy symbol is resolved
lazily through :func:`__getattr__` (PEP 562) rather than imported at module scope.

Public surface (FROZEN):

.. code-block:: python

    __all__ = ["AgentHarness", "Config", "HarnessResult", "__version__"]

Spec: SPEC-005 § 1 · SPEC-000 § 2 (L3 Surface)
"""

from __future__ import annotations

import importlib.metadata
from typing import Any

#: Used when the distribution metadata is unavailable (e.g. a source checkout that was
#: never ``pip install``-ed). Once installed, the metadata value always wins.
_FALLBACK_VERSION = "0.1.0"

__all__ = ["AgentHarness", "Config", "HarnessResult", "__version__"]

#: Lazy resolution table. Values are ``(module, attribute)`` pairs, so importing this
#: package touches nothing but the standard library.
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "AgentHarness": ("agent_harness.harness", "AgentHarness"),
    "Config": ("agent_harness.config", "Config"),
    "HarnessResult": ("agent_harness.harness", "HarnessResult"),
}


def _resolve_version() -> str:
    """Return the package version, preferring installed distribution metadata.

    Returns:
        The version reported by ``importlib.metadata`` for the ``agent-harness``
        distribution, or :data:`_FALLBACK_VERSION` when it is not installed.
    """
    for distribution in ("agent-harness", "agent_harness"):
        try:
            return importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            continue
    return _FALLBACK_VERSION


__version__ = _resolve_version()


def __getattr__(name: str) -> Any:
    """Resolve the public surface on first access (PEP 562).

    Args:
        name: the attribute being accessed.

    Returns:
        The resolved public symbol.

    Raises:
        AttributeError: if ``name`` is not part of :data:`__all__`.
        ImportError: if the owning module cannot be imported — the message names the
            module so the cause is never silent.
    """
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:  # pragma: no cover - exercised only pre-integration
        raise ImportError(
            f"cannot resolve agent_harness.{name}: module {module_name!r} is "
            f"unavailable ({exc})"
        ) from exc
    return getattr(module, attribute)


def __dir__() -> list[str]:
    """Advertise the public surface plus the version constant."""
    return sorted([*__all__])
