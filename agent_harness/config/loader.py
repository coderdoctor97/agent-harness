"""YAML and environment configuration loading. Spec: SPEC-006 §1–3."""

from __future__ import annotations

import importlib
import math
import os
import re
import warnings
from collections.abc import Sequence
from dataclasses import fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dotenv import load_dotenv

from .schema import AgentError, Config, _Serializable

if TYPE_CHECKING:
    from agent_harness.logging import StructuredLogger


def load_config_dict(
    d: dict[str, Any],
    *,
    apply_env: bool = True,
    logger: StructuredLogger | None = None,
    source_path: str | None = None,
) -> Config:
    """Build typed sections without storing resolved keys. Spec: SPEC-006 §1."""
    if not isinstance(d, dict):
        raise AgentError(
            "CONFIG_VALIDATION_FAILED", "Configuration must be a mapping", "config"
        )
    config = Config()
    known = {f.name for f in fields(config)}
    if set(d) - known:
        raise AgentError(
            "CONFIG_VALIDATION_FAILED", "Unknown configuration section", "config"
        )
    for name, raw in d.items():
        if not isinstance(raw, dict):
            raise AgentError(
                "CONFIG_VALIDATION_FAILED", f"{name} must be a mapping", "config"
            )
        section = getattr(config, name)
        allowed = {f.name for f in fields(section)}
        if set(raw) - allowed:
            if logger is not None:
                logger.warning(
                    "config",
                    "config_loaded",
                    metadata={"warning": "unknown key ignored", "section": name},
                )
            warnings.warn(f"Unknown key in {name} ignored", UserWarning, stacklevel=2)
        try:
            section_type: type[_Serializable] = type(section)
            setattr(config, name, section_type.from_dict(raw))
        except ValueError as exc:
            raise AgentError(
                "CONFIG_VALIDATION_FAILED", f"Invalid {name} field type", "config"
            ) from exc
    if apply_env:
        config.logging.level = os.environ.get(
            "AGENT_HARNESS_LOG_LEVEL", config.logging.level
        )
        config.execution.output_dir = os.environ.get(
            "AGENT_HARNESS_OUTPUT_DIR", config.execution.output_dir
        )
    validate_config(config)
    if logger is not None:
        logger.info(
            "config",
            "config_loaded",
            metadata={
                "path": source_path,
                "provider": config.llm.provider,
                "overrides": [
                    key
                    for key in ("AGENT_HARNESS_LOG_LEVEL", "AGENT_HARNESS_OUTPUT_DIR")
                    if apply_env and key in os.environ
                ],
            },
        )
    return config


def load_config_file(
    path: str | Path | None, *, logger: StructuredLogger | None = None
) -> Config:
    """Read YAML and adjacent .env without creating directories. Spec: SPEC-006 §1."""
    selected = Path(
        path
        if path is not None
        else os.environ.get("AGENT_HARNESS_CONFIG", "config.yaml")
    ).expanduser()
    yaml = importlib.import_module("yaml")
    try:
        load_dotenv(selected.parent / ".env", override=False)
        raw: object = yaml.safe_load(selected.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise AgentError(
            "CONFIG_LOAD_FAILED", "Unable to read configuration YAML", "config"
        ) from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise AgentError(
            "CONFIG_VALIDATION_FAILED", "Configuration must be a mapping", "config"
        )
    return load_config_dict(raw, logger=logger, source_path=str(selected))


def validate_config(config: Config) -> None:
    """Enforce K1–K5 without resolving keys or making directories. Spec: SPEC-006 §1.3."""
    enums = {
        "llm.provider": {"openai", "anthropic", "local"},
        "execution.retry_backoff": {"exponential", "linear", "fixed"},
        "search.provider": {"serpapi", "bing", "duckduckgo", "google"},
        "logging.level": {"DEBUG", "INFO", "WARNING", "ERROR"},
        "logging.format": {"json", "text"},
    }
    for path, allowed in enums.items():
        if config.get(path) not in allowed:
            raise AgentError(
                "CONFIG_VALIDATION_FAILED",
                f"{path} allowed: {', '.join(sorted(allowed))}",
                "config",
            )
    for section in fields(config):
        for key, value in getattr(config, section.name).to_dict().items():
            if type(value) is int and value <= 0:
                raise AgentError(
                    "CONFIG_VALIDATION_FAILED",
                    f"{section.name}.{key} must be positive",
                    "config",
                )
    if (
        not math.isfinite(config.llm.temperature)
        or not 0 <= config.llm.temperature <= 2
    ):
        raise AgentError(
            "CONFIG_VALIDATION_FAILED", "llm.temperature must be in [0, 2]", "config"
        )
    cost = config.llm.cost_per_1k_tokens
    if cost is not None and (not math.isfinite(cost) or cost < 0):
        raise AgentError(
            "CONFIG_VALIDATION_FAILED",
            "llm.cost_per_1k_tokens must be nonnegative",
            "config",
        )
    for pattern in config.security.sensitive_patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise AgentError(
                "CONFIG_VALIDATION_FAILED",
                f"Invalid sensitive pattern: {pattern}",
                "config",
            ) from exc


def sensitive_data_filter(
    text: str,
    patterns: Sequence[str] | None = None,
    *,
    secrets: Sequence[str] = (),
) -> tuple[str, int]:
    """Redact configured patterns and optional exact credentials. Spec: SPEC-006 §3.2.

    The one-argument form uses frozen security defaults. Inject configured patterns
    explicitly to avoid process-global configuration and cross-run leakage.
    """
    from .schema import SecurityConfig

    count = 0
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            text, replaced = re.subn(re.escape(secret), "[REDACTED]", text)
            count += replaced
    for pattern in (
        SecurityConfig().sensitive_patterns if patterns is None else patterns
    ):
        try:
            text, replaced = re.subn(pattern, "[REDACTED]", text)
        except re.error as exc:
            raise AgentError(
                "CONFIG_VALIDATION_FAILED", "Invalid redaction pattern", "config"
            ) from exc
        count += replaced
    return text, count
