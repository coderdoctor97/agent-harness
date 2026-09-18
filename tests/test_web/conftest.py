"""Fixtures for the web UI suite.

Local to ``tests/test_web`` on purpose: ``tests/conftest.py`` is Plan 5's shared
fixture module (P5 sub-phase 1.1) and this plan does not edit another plan's
files. Everything these tests need is built here from the real objects, with the
harness reached through its documented seams — the same ones the CLI uses.

Skill: core-coding/tdd-test-runner · reliability/flaky-test-isolator (no network,
no sleeps on the critical path)
"""

from __future__ import annotations

import pathlib
import sys
import time
from typing import Any

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import _p4_doubles as doubles  # noqa: E402  (path set above)

from agent_harness.config import Config  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every test offline: a fake key satisfies config validation only."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    monkeypatch.delenv("AGENT_HARNESS_CONFIG", raising=False)


@pytest.fixture
def scratch(tmp_path: pathlib.Path) -> pathlib.Path:
    """A private output/temp root, so no test writes into the working tree."""
    (tmp_path / "out").mkdir()
    (tmp_path / "tmp").mkdir()
    return tmp_path


@pytest.fixture
def config(scratch: pathlib.Path) -> Config:
    """A real :class:`Config` pointing at this test's scratch directories."""
    config = Config()
    config.execution.output_dir = str(scratch / "out")
    config.execution.temp_dir = str(scratch / "tmp")
    return config


#: A SPEC-004 § 4.1 shaped plan payload: the planner's own key names.
PLAN_PAYLOAD: dict[str, Any] = {
    "steps": [
        {
            "description": "search the web for frameworks",
            "tool_hint": "web_search",
            "input_data": {"query": "python web frameworks"},
            "priority": "critical",
        }
    ]
}


def scripted_factory(config: Config, replies: list[Any] | None = None) -> Any:
    """Build a ``harness_factory`` returning a harness wired to doubles.

    Args:
        config: the config the harness is built with.
        replies: scripted LLM replies; defaults to one plan plus one synthesis.

    Returns:
        A factory taking the progress callback, exactly as
        :class:`agent_harness.web.runner.TaskRunner` calls it.
    """

    def factory(progress: Any) -> Any:
        from agent_harness.harness import AgentHarness

        client = doubles.MockLLMClient(
            replies if replies is not None else [PLAN_PAYLOAD, "assembled deliverable"]
        )
        return AgentHarness(
            config,
            llm_client=client,
            planner=doubles.StubPlanner(doubles.one_step_plan(tool="web_search")),
            registry=doubles.stub_registry(),
            progress=progress,
        )

    return factory


def wait_for_task(client: Any, task_id: str, timeout: float = 10.0) -> dict[str, Any]:
    """Block until a task reaches a terminal state and return its detail.

    Submission is deliberately asynchronous — ``POST /api/tasks`` returns as soon
    as the task is *queued* — so a test that reads immediately is racing the
    worker. Waiting on the observable contract (the task's own status) keeps the
    suite deterministic without reaching into the runner's internals.

    Args:
        client: a :class:`fastapi.testclient.TestClient`.
        task_id: the task to wait for.
        timeout: maximum seconds to wait.

    Returns:
        The terminal task detail.

    Raises:
        AssertionError: if the task has not finished within ``timeout``.
    """
    deadline = time.monotonic() + timeout
    body: dict[str, Any] = {}
    while time.monotonic() < deadline:
        body = client.get(f"/api/tasks/{task_id}").json()
        if body.get("status") in {"completed", "partial", "failed"}:
            return body
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} did not finish within {timeout}s: {body}")


@pytest.fixture
def runner(config: Config) -> Any:
    """A :class:`TaskRunner` on scripted doubles, torn down after the test."""
    from agent_harness.web.runner import TaskRunner

    task_runner = TaskRunner(config, harness_factory=scripted_factory(config))
    yield task_runner
    task_runner.shutdown()


@pytest.fixture
def client(config: Config, runner: Any) -> Any:
    """A FastAPI test client bound to the scripted runner."""
    from fastapi.testclient import TestClient

    from agent_harness.web.app import create_app

    with TestClient(create_app(config, runner=runner)) as test_client:
        yield test_client
