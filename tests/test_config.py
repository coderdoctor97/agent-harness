"""Foundation contract tests. Spec: SPEC-000 §4–6, SPEC-001, SPEC-006."""

from importlib.metadata import metadata
from pathlib import Path

import pytest


def test_packaging_metadata() -> None:
    """The editable distribution exposes the frozen baseline. Spec: SPEC-000 §4."""
    project = metadata("agent-harness")
    assert project["Version"] == "0.1.0"
    assert project["Requires-Python"] == ">=3.9"
    requires = project.get_all("Requires-Dist") or []
    assert any(item.startswith("openai>=1.12.0") for item in requires)
    assert any(item.startswith("pytest>=7.0") for item in requires)


def test_owned_namespaces() -> None:
    """Owned namespaces import without higher layers. Spec: SPEC-000 §2."""
    import importlib

    for name in ("config", "context", "logging", "llm"):
        assert importlib.import_module("agent_harness." + name).__doc__


def test_shipped_defaults_match_spec() -> None:
    """Shipped YAML exactly matches the frozen schema. Spec: SPEC-006 §1."""
    import importlib
    from pathlib import Path

    yaml = importlib.import_module("yaml")
    root = Path(__file__).resolve().parents[1]
    spec = (root / "spec/SPEC-006-config-security-logging.md").read_text()
    expected = yaml.safe_load(spec.split("```yaml\n", 1)[1].split("```", 1)[0])
    assert yaml.safe_load((root / "config.yaml").read_text()) == expected


def test_env_template_is_safe() -> None:
    """All env names exist without matching secret patterns. Spec: SPEC-006 §2–3."""
    import re
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / ".env.example").read_text()
    for key in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "SEARCH_API_KEY",
        "AGENT_HARNESS_CONFIG",
        "AGENT_HARNESS_LOG_LEVEL",
        "AGENT_HARNESS_OUTPUT_DIR",
    ):
        assert key + "=" in text
    assert not re.search(r"\b\d{3}-\d{2}-\d{4}\b|sk-[a-zA-Z0-9]{48}", text)


def test_enum_contracts() -> None:
    """Enum members and values are frozen. Spec: SPEC-001 §1."""
    from agent_harness.config import StepStatus, TaskPriority

    assert {s.name: s.value for s in StepStatus} == {
        name.upper(): name
        for name in ["pending", "running", "success", "failed", "skipped", "retrying"]
    }
    assert [p.value for p in TaskPriority] == ["critical", "high", "medium", "low"]
    assert StepStatus("pending") is StepStatus.PENDING


def test_step_invariants_and_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate each status/retry invariant and timestamps. Spec: SPEC-001 §2.1."""
    from datetime import datetime, timedelta
    from uuid import UUID

    import pytest

    from agent_harness.config import AgentError, Step, StepStatus

    identifiers = iter(
        [
            UUID("10000000-0000-0000-0000-000000000000"),
            UUID("20000000-0000-0000-0000-000000000000"),
        ]
    )
    with monkeypatch.context() as scoped:
        scoped.setattr(
            "agent_harness.config.schema.uuid.uuid4", lambda: next(identifiers)
        )
        a, b = Step(), Step()
    assert a.id != b.id and len(a.id) == 8
    a.input_data["a"] = 1
    assert b.input_data == {}
    a.validate()
    assert a.duration_ms is None
    a.started_at = datetime(2026, 1, 1)
    a.completed_at = a.started_at + timedelta(milliseconds=1234)
    assert a.duration_ms == 1234
    for step in [
        Step(retries=3),
        Step(retries=-1),
        Step(status=StepStatus.SUCCESS, error="failure"),
        Step(status=StepStatus.FAILED),
    ]:
        with pytest.raises(AgentError):
            step.validate()
    Step(retries=2).validate()
    Step(status=StepStatus.SUCCESS).validate()
    Step(status=StepStatus.FAILED, error="failure").validate()


def test_plan_status_and_lookup() -> None:
    """Status derivation respects priorities without side effects. Spec: SPEC-001 §2.2."""
    from agent_harness.config import (
        ExecutionPlan,
        Step,
        StepStatus,
        TaskPriority,
        derive_plan_status,
    )

    required = Step(id="required", status=StepStatus.SUCCESS)
    optional = Step(priority=TaskPriority.LOW, status=StepStatus.SKIPPED)
    plan = ExecutionPlan(steps=[required, optional])
    assert plan.step_by_id("required") is required
    assert plan.step_by_id("absent") is None
    assert derive_plan_status(plan) == (StepStatus.SUCCESS, {"degraded": True})
    assert plan.status == StepStatus.PENDING
    required.status = StepStatus.FAILED
    assert derive_plan_status(plan)[0] == StepStatus.FAILED
    required.status = StepStatus.RUNNING
    assert derive_plan_status(plan)[0] == StepStatus.PENDING
    assert derive_plan_status(ExecutionPlan()) == (
        StepStatus.SUCCESS,
        {"degraded": False},
    )


def test_error_catalog_and_exception_contract() -> None:
    """Errors are catchable with every catalog entry. Spec: SPEC-001 §2.4, §3."""
    import re
    from pathlib import Path

    from agent_harness.config import AgentError, ErrorCode

    spec = (
        Path(__file__).resolve().parents[1] / "spec/SPEC-001-core-data-model.md"
    ).read_text()
    assert {e.value for e in ErrorCode} == set(
        re.findall(r"^\| `([A-Z_]+)`", spec.split("## 3. Error Code Catalog")[1], re.M)
    )
    error = AgentError("LLM_CALL_FAILED", "Unavailable", "llm", "step_0")
    assert isinstance(error, Exception)
    assert str(error) == "[LLM_CALL_FAILED] llm(step_0): Unavailable"


def test_serialization_and_metrics() -> None:
    """Round trips cover nested plans and every status. Spec: SPEC-001 §4."""
    import json
    from datetime import datetime
    from types import SimpleNamespace

    import pytest

    from agent_harness.config import (
        AgentError,
        ExecutionMetrics,
        ExecutionPlan,
        Step,
        StepStatus,
    )

    steps = [
        Step(
            id=s.value,
            status=s,
            error="failed" if s == StepStatus.FAILED else None,
            started_at=datetime(2026, 1, 1),
            input_data={"nested": [1, True, None]},
            tool_name="tool",
        )
        for s in StepStatus
    ]
    steps[2].retries = 1
    plan = ExecutionPlan(
        steps=steps, context={"files_created": ["a"], "errors": [{"error": "x"}]}
    )
    assert ExecutionPlan.from_dict(json.loads(json.dumps(plan.to_dict()))) == plan
    assert Step.from_dict({"unknown": 1}).description == ""
    error = AgentError("SYSTEM_ERROR", "problem", "config")
    assert AgentError.from_dict(error.to_dict()) == error
    usage = SimpleNamespace(
        calls=2, prompt_tokens=10, completion_tokens=5, estimated_cost=0.02
    )
    metrics = ExecutionMetrics.from_plan(plan, {"total_duration_ms": 250}, usage)
    assert metrics.llm_tokens_used == 15 and metrics.recovered_steps == 1
    assert metrics.tools_used == ["tool"] and metrics.total_duration_ms == 250
    assert ExecutionMetrics.from_dict(metrics.to_dict()) == metrics
    assert ExecutionMetrics.from_plan(plan, {}, {"calls": 1}).llm_calls == 1
    for payload in [
        {"retries": "two"},
        {"depends_on": "id"},
        {"input_data": []},
        {"description": True},
        {"started_at": 1},
        {"status": "invalid"},
        {"input_data": {1: "invalid"}},
        {"output_data": float("nan")},
    ]:
        with pytest.raises(AgentError):
            assert isinstance(payload, dict)
            Step.from_dict(payload)
    for payload in [
        {"steps": [{"id": "a"}, {"id": "a"}]},
        {"steps": [{"id": "a", "depends_on": ["missing"]}]},
    ]:
        with pytest.raises(AgentError):
            assert isinstance(payload, dict)
            ExecutionPlan.from_dict(payload)
    with pytest.raises(ValueError):
        AgentError.from_dict({"code": 1})
    with pytest.raises(ValueError):
        Step(output_data=object()).to_dict()


def test_typed_config_defaults() -> None:
    """Typed sections and dotted paths mirror shipped defaults. Spec: SPEC-006 §1."""
    import importlib
    from pathlib import Path

    from agent_harness.config import Config

    expected = importlib.import_module("yaml").safe_load(
        (Path(__file__).resolve().parents[1] / "config.yaml").read_text()
    )
    config = Config()
    assert config.to_dict() == expected
    assert config.get("execution.max_steps") == 20
    assert config.get("execution.absent", "fallback") == "fallback"
    assert config.get("llm.model.unknown") is None
    assert config.get("__class__") is None
    config.security.sensitive_patterns.append("custom")
    assert "custom" not in Config().security.sensitive_patterns


def test_yaml_loader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Loader errors and unknown-key handling are explicit. Spec: SPEC-006 §1."""
    from agent_harness.config import AgentError, Config

    path = tmp_path / "config.yaml"
    path.write_text("llm:\n  model: test-model\n")
    (tmp_path / ".env").write_text("P1_TEST_DOTENV=example\n")
    monkeypatch.delenv("P1_TEST_DOTENV", raising=False)
    import os

    assert Config.from_file(path).llm.model == "test-model"
    assert os.environ["P1_TEST_DOTENV"] == "example"
    monkeypatch.delenv("P1_TEST_DOTENV")
    with pytest.warns(UserWarning, match="Unknown key"):
        assert Config.from_dict({"llm": {"future_key": 123}}).llm.model == "gpt-4o"
    for data in [{"unknown": {}}, {"llm": []}, {"llm": {"max_tokens": "many"}}]:
        with pytest.raises(AgentError, match="CONFIG_VALIDATION_FAILED"):
            assert isinstance(data, dict)
            Config.from_dict(data)
    with pytest.raises(AgentError, match="CONFIG_LOAD_FAILED"):
        Config.from_file(tmp_path / "missing.yaml")
    for text in ["[", "- item"]:
        path.write_text(text)
        with pytest.raises(AgentError):
            Config.from_file(path)
    path.write_text("")
    assert Config.from_file(path) == Config()


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("llm", "provider", "unknown"),
        ("execution", "retry_backoff", "unknown"),
        ("search", "provider", "unknown"),
        ("logging", "level", "TRACE"),
        ("logging", "format", "xml"),
        ("execution", "max_steps", 0),
        ("llm", "max_retries", -1),
        ("llm", "temperature", 2.1),
        ("llm", "temperature", -0.1),
        ("llm", "cost_per_1k_tokens", -1),
        ("security", "sensitive_patterns", ["["]),
        ("security", "sandbox_code", "yes"),
    ],
)
def test_config_validation(section: str, key: str, value: object) -> None:
    """Invalid enums, ranges and regexes fail closed. Spec: SPEC-006 K1–K3."""
    from agent_harness.config import AgentError, Config

    with pytest.raises(AgentError, match="CONFIG_VALIDATION_FAILED"):
        Config.from_dict({section: {key: value}})


def test_config_loading_is_side_effect_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Directories and API key checks are deferred. Spec: SPEC-006 K4–K5."""
    from agent_harness.config import Config

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = Config.from_dict(
        {
            "execution": {"output_dir": str(tmp_path / "absent")},
            "llm": {"temperature": 0, "cost_per_1k_tokens": 0},
        }
    )
    assert config.llm.temperature == 0.0
    assert not (tmp_path / "absent").exists()
    assert Config.from_dict({"llm": {"temperature": 2}}).llm.temperature == 2.0


def test_precedence_and_atomic_cli_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI > env > file > defaults, including config path. Spec: SPEC-006 §1.2."""
    from agent_harness.config import AgentError, Config

    file = tmp_path / "config.yaml"
    file.write_text(
        "logging:\n  level: WARNING\nexecution:\n  output_dir: file-output\n"
    )
    explicit = tmp_path / "explicit.yaml"
    explicit.write_text("llm:\n  model: explicit\n")
    assert Config.from_file(file).logging.level == "WARNING"
    monkeypatch.setenv("AGENT_HARNESS_CONFIG", str(file))
    monkeypatch.setenv("AGENT_HARNESS_LOG_LEVEL", "ERROR")
    monkeypatch.setenv("AGENT_HARNESS_OUTPUT_DIR", "env-output")
    config = Config.from_file()
    assert (
        config.logging.level == "ERROR" and config.execution.output_dir == "env-output"
    )
    assert Config.from_file(explicit).llm.model == "explicit"
    assert (
        config.apply_overrides(
            output_dir="cli-output", log_level="DEBUG", max_steps=2, no_fallback=True
        )
        is config
    )
    assert (
        config.logging.level == "DEBUG" and config.execution.output_dir == "cli-output"
    )
    assert config.execution.max_steps == 2 and not config.execution.enable_replan
    config.apply_overrides(log_level=None, no_fallback=False)
    before = config.to_dict()
    for kwargs in [{"max_steps": -1}, {"no_fallback": "yes"}, {"unknown": True}]:
        with pytest.raises(AgentError):
            assert isinstance(kwargs, dict)
            config.apply_overrides(**kwargs)
        assert config.to_dict() == before


def test_secret_indirection_and_redaction(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolved credentials stay out of dumps. Spec: SPEC-006 §3."""
    import json

    from agent_harness.config import AgentError, Config, sensitive_data_filter

    secret = "test-provider-credential"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    config = Config.from_dict({})
    assert secret not in json.dumps(config.to_dict())
    assert config.to_dict()["llm"]["api_key_env"] == "OPENAI_API_KEY"
    config.llm.model = secret
    assert config.to_dict()["llm"]["model"] == "[REDACTED]"
    assert config.to_dict(False)["llm"]["model"] == secret
    redacted, count = sensitive_data_filter("123-45-6789 " + "sk-" + "x" * 48)
    assert redacted == "[REDACTED] [REDACTED]" and count == 2
    assert sensitive_data_filter("custom", ["custom"]) == ("[REDACTED]", 1)
    assert sensitive_data_filter(secret, [], secrets=[secret, ""]) == ("[REDACTED]", 1)
    with pytest.raises(AgentError):
        sensitive_data_filter("text", ["["])


def test_owned_api_documentation_and_layering() -> None:
    """Audit Python 3.9 syntax, spec citations and owned imports. Spec: SPEC-000 §2, §4."""
    import ast

    root = Path(__file__).resolve().parents[1]
    forbidden = (
        "agent_harness.tools",
        "agent_harness.planning",
        "agent_harness.orchestration",
        "agent_harness.harness",
        "agent_harness.plugins",
    )

    def audit_public(nodes: list[ast.stmt]) -> None:
        for node in nodes:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_") and node.name not in (
                    "__init__",
                    "__str__",
                    "__post_init__",
                ):
                    continue
                assert "Spec:" in (ast.get_docstring(node) or ""), node.name
                if isinstance(node, ast.ClassDef):
                    audit_public(node.body)

    for area in ("config", "context", "logging", "llm"):
        for path in (root / "agent_harness" / area).glob("*.py"):
            tree = ast.parse(path.read_text(), feature_version=(3, 9))
            assert "Spec:" in (ast.get_docstring(tree) or "")
            audit_public(tree.body)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    assert not (node.module or "").startswith(forbidden)
                elif isinstance(node, ast.Import):
                    assert not any(
                        alias.name.startswith(forbidden) for alias in node.names
                    )


def test_error_deepcopy_and_recovered_metrics() -> None:
    """Keyword-built exceptions copy and metrics include fallback recovery. Spec: SPEC-001 §2."""
    from copy import deepcopy

    from agent_harness.config import (
        AgentError,
        ErrorCode,
        ExecutionMetrics,
        ExecutionPlan,
        Step,
        StepStatus,
    )

    error = AgentError(code=ErrorCode.SYSTEM_ERROR, message="test", component="harness")
    assert deepcopy(error) == error
    assert str(error) == "[SYSTEM_ERROR] harness(None): test"
    plan = ExecutionPlan(
        steps=[Step(id="s", status=StepStatus.SUCCESS)],
        context={
            "errors": [
                {
                    "step_id": "s",
                    "attempt": 0,
                    "error": "fallback",
                    "recovered": True,
                    "level": 2,
                }
            ],
            "config": {"llm": {"cost_per_1k_tokens": 2.0}},
        },
    )
    metrics = ExecutionMetrics.from_plan(
        plan, {}, {"prompt_tokens": 5, "completion_tokens": 5}
    )
    assert metrics.recovered_steps == 1 and metrics.llm_estimated_cost == 0.02
    metrics.errors[0]["error"] = "modified"
    assert plan.context["errors"][0]["error"] == "fallback"


def test_config_injected_events(tmp_path: Path) -> None:
    """Config emits catalog events without storing credentials. Spec: SPEC-006 §6.1."""
    import json

    from agent_harness.config import Config
    from agent_harness.logging import StructuredLogger

    logfile = tmp_path / "log"
    logger = StructuredLogger(
        Config.from_dict({"logging": {"file": str(logfile), "console": False}})
    )
    configfile = tmp_path / "config.yaml"
    configfile.write_text("llm:\n  unused: true\n")
    with pytest.warns(UserWarning):
        Config.from_file(configfile, logger=logger)
    events = [json.loads(line) for line in logfile.read_text().splitlines()]
    assert all(event["event"] == "config_loaded" for event in events)
    assert any(event["level"] == "WARNING" for event in events)
    assert events[-1]["metadata"]["path"] == str(configfile)


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
