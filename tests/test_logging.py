"""Deterministic observability tests. Spec: SPEC-006 §3, §6–7."""

from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pytest

from agent_harness.config import Config
from agent_harness.logging import StructuredLogger


def test_jsonl_schema_children_and_levels(tmp_path: Path) -> None:
    """Frozen fields and child binding survive JSON serialization. Spec: SPEC-006 §6."""
    import json

    config = Config.from_dict(
        {"logging": {"file": str(tmp_path / "logs/run.jsonl"), "level": "DEBUG"}}
    )
    console = StringIO()
    logger = StructuredLogger(
        config,
        console_stream=console,
        clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert not (tmp_path / "logs").exists()
    child = logger.child("orchestrator", plan_id="p")
    child.info("step_started", step_id="a")
    child.debug("orchestrator", "step_completed")
    child.warning("step_skipped")
    logger.error("harness", "harness_complete")
    records = [
        json.loads(line) for line in Path(config.logging.file).read_text().splitlines()
    ]
    assert records[0]["timestamp"] == "2026-01-01T00:00:00.000Z"
    assert records[0]["plan_id"] == "p" and records[0]["step_id"] == "a"
    assert records[-1]["plan_id"] is None
    assert set(records[0]) == {
        "timestamp",
        "level",
        "component",
        "event",
        "plan_id",
        "step_id",
        "step_description",
        "tool_name",
        "duration_ms",
        "status",
        "retry_count",
        "context_size_bytes",
        "llm_tokens_used",
        "metadata",
    }
    assert len(console.getvalue().splitlines()) == 4
    with pytest.raises(ValueError):
        logger.info("step_started")
    # Unknown events are now allowed through (open catalog — SCR-P3-10, SCR-P4-10).
    # The event name is preserved verbatim so consumers can still filter on it.
    logger.info("harness", "unknown")  # should NOT raise
    assert StructuredLogger.default() is not StructuredLogger.default()
    StructuredLogger.default().info("harness", "harness_start")


def test_log_safety_filtering_and_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Redact secrets, bodies and long blobs before all sinks. Spec: SPEC-006 §3.4."""
    import json

    from agent_harness.config import AgentError

    secret = "private-test-credential"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    config = Config.from_dict(
        {"logging": {"file": str(tmp_path / "run.jsonl"), "format": "text"}}
    )
    console = StringIO()
    logger = StructuredLogger(config, console_stream=console)
    logger.debug("harness", "harness_start")
    assert not Path(config.logging.file).exists()
    logger.info(
        "harness",
        "harness_start",
        metadata={
            "key": secret,
            "fake": "sk-" + "x" * 48,
            "blob": "z" * 800,
            "messages": [{"content": "never-log-this"}],
            "api_key": "another-credential",
            secret: "123-45-6789",
            "nested": [{"password": "hidden"}],
            "opaque": object(),
        },
    )
    text = Path(config.logging.file).read_text()
    for forbidden in [
        secret,
        "never-log-this",
        "another-credential",
        "123-45-6789",
        "hidden",
        "z" * 501,
    ]:
        assert forbidden not in text and forbidden not in console.getvalue()
    assert "[REDACTED]" in text and "[TRUNCATED]" in text
    record = json.loads(text)
    assert record["metadata"]["opaque"] == "<object>"
    assert "INFO harness: harness_start" in console.getvalue()
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    logger.info("harness", "harness_complete", metadata=cyclic)
    assert "nesting limit" in Path(config.logging.file).read_text()
    path = tmp_path / "directory"
    path.mkdir()
    broken = StructuredLogger(Config.from_dict({"logging": {"file": str(path)}}))
    with pytest.raises(AgentError, match="SYSTEM_ERROR"):
        broken.info("harness", "harness_start")


def test_report_golden_and_purity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inline goldens keep fixtures within P1 ownership. Spec: SPEC-006 §7."""
    from agent_harness.config import ExecutionMetrics, ExecutionPlan, Step, StepStatus
    from agent_harness.logging import render_report

    plan = ExecutionPlan(
        id="p",
        original_prompt="Task",
        status=StepStatus.SUCCESS,
        steps=[
            Step(
                id="a", description="Work", tool_name="tool", status=StepStatus.SUCCESS
            )
        ],
    )
    metrics = ExecutionMetrics.from_plan(plan, {"total_duration_ms": 1000}, {})
    body = (
        'Plan ID: p\nPrompt: "Task"\nStatus: COMPLETED\nDuration: 1.0s\n'
        "Steps: 1 total | 1 success | 0 failed | 0 skipped | 0 retried (recovered)\n"
        "LLM Tokens: 0 (est. cost: $0.000)\nFiles Created: None\n\n"
        "Step Details:\n[✓] Step 1: Work (0.0s, tool)\n\nErrors Encountered:\nNone\n"
    )
    banner = "═" * 59 + "\n"

    def forbid(*args: object, **kwargs: object) -> None:
        raise AssertionError("report attempted I/O")

    monkeypatch.setattr("builtins.open", forbid)
    assert (
        render_report(plan, metrics)
        == banner + "EXECUTION REPORT\n" + banner + body + banner
    )
    markdown = "# EXECUTION REPORT\n\n" + body.replace(
        "Step Details:", "## Step Details"
    ).replace("Errors Encountered:", "## Errors Encountered").replace("[✓]", "- [✓]")
    assert render_report(plan, metrics, style="markdown") == markdown
    with pytest.raises(ValueError):
        render_report(plan, metrics, style="html")
    plan.status = StepStatus.FAILED
    plan.steps = [
        Step(status=StepStatus.SUCCESS, retries=1),
        Step(status=StepStatus.FAILED, error="x"),
        Step(status=StepStatus.SKIPPED),
    ]
    metrics.errors = [{"step_id": "a", "attempt": 1, "error": "x", "recovered": True}]
    text = render_report(plan, metrics)
    assert all(marker in text for marker in ["[⟳]", "[✗]", "[–]", "→ recovered"])


def test_nonfinite_metadata_remains_valid_json(tmp_path: Path) -> None:
    """Invalid JSON number values cannot corrupt JSONL. Spec: SPEC-006 §6."""
    path = tmp_path / "log"
    config = Config.from_dict({"logging": {"file": str(path), "console": False}})
    StructuredLogger(config).info(
        "harness", "harness_start", metadata={"value": float("nan")}
    )
    assert "NaN" not in path.read_text() and "[NONFINITE]" in path.read_text()


@pytest.fixture(autouse=True)
def _offline_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject network access and isolate ambient overrides. Spec: SPEC-000 §5."""

    def reject(*args: object, **kwargs: object) -> None:
        raise AssertionError("Live network calls are forbidden in P1 unit tests")

    monkeypatch.setattr("socket.socket.connect", reject)
    monkeypatch.setattr("socket.socket.connect_ex", reject)
    monkeypatch.setattr("socket.create_connection", reject)
    for key in (
        "AGENT_HARNESS_CONFIG",
        "AGENT_HARNESS_LOG_LEVEL",
        "AGENT_HARNESS_OUTPUT_DIR",
    ):
        monkeypatch.delenv(key, raising=False)


def test_credential_field_aliases(tmp_path: Path) -> None:
    """Alternate credential field spellings also fail closed. Spec: SPEC-006 §3.4."""
    path = tmp_path / "log"
    logger = StructuredLogger(
        Config.from_dict({"logging": {"file": str(path), "console": False}})
    )
    logger.info(
        "harness",
        "harness_start",
        metadata={
            "X-API-Key": "unrecognized-key-format",
            "access-token": "opaque-token",
        },
    )
    assert "unrecognized-key-format" not in path.read_text()
    assert "opaque-token" not in path.read_text()
