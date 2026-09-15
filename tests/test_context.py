"""Isolated context contract tests. Spec: SPEC-003 §4.1."""

import pytest

from agent_harness.context import ContextStore


def test_layout_and_fresh_state() -> None:
    """Every frozen key exists and each run is isolated. Spec: SPEC-003 §4.1."""
    a, b = ContextStore.fresh(), ContextStore.fresh()
    assert set(a.as_dict()) == {
        "config",
        "step_results",
        "variables",
        "errors",
        "files_created",
        "llm_client",
        "allowed_read_paths",
        "allowed_write_paths",
    }
    a.variables["x"] = [1]
    a.step_results["step"] = {"output": 1}
    a.files_created.append("a")
    a.errors.append({"error": "x"})
    assert b.variables == {} and b.step_results == {}
    assert b.errors == [] and b.files_created == []
    assert a.as_dict()["step_results"] is a.step_results
    values = {"nested": [1]}
    store = ContextStore(variables=values)
    store.variables["nested"].append(2)
    assert values == {"nested": [1]}


def test_recording_size_and_guards() -> None:
    """Record exact fields with dedupe and UTF-8 truncation. Spec: SPEC-003 §4.1."""
    import json

    import pytest

    from agent_harness.config import AgentError, Step, StepStatus

    with pytest.raises(ValueError):
        ContextStore(max_output_bytes=0)
    store = ContextStore(max_output_bytes=16, llm_client=object())
    store.record_step_result(Step(id="a", status=StepStatus.SUCCESS, output_data="ok"))
    assert store.step_results["a"] == {
        "status": "success",
        "output": "ok",
        "error": None,
        "tool_name": "",
        "duration_ms": 0,
        "retries": 0,
    }
    store.record_step_result(Step(id="b", output_data="🙂" * 30))
    result = store.step_results["b"]["output"]
    assert result["truncated"] and result["original_type"] == "str"
    assert result["marker"] == "[TRUNCATED]"
    assert len(result["preview"].encode()) <= 16
    for path in ["b", "a", "b"]:
        store.add_file(path)
    assert store.files_created == ["b", "a"]
    store.add_error("failure", step_id="a", attempt=1, level=2)
    store.add_error(AgentError("SYSTEM_ERROR", "error", "harness", "b"), recovered=True)
    assert set(store.errors[0]) == {"step_id", "attempt", "error", "recovered", "level"}
    assert store.errors[1]["step_id"] == "b"
    snapshot = dict(store.as_dict(), llm_client="<LLMClient>")
    assert store.context_size_bytes == len(
        json.dumps(snapshot, ensure_ascii=False).encode()
    )
    assert ContextStore().context_size_bytes > 0


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
