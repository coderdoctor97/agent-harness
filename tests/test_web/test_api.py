"""HTTP contract tests for the local web UI (PRD G8).

Written against the routes and schemas the browser consumes, so a change to the
API surface fails here before it can break the UI.

Skill: core-coding/tdd-test-runner · frontend/component-composition (the API is
the component boundary) · reliability/threat-model-sast (path containment)
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest
from conftest import wait_for_task


class TestHealth:
    """``GET /api/health`` — the header's facts, and nothing secret."""

    def test_reports_ok_and_version(self, client: Any) -> None:
        body = client.get("/api/health").json()

        assert body["ok"] is True
        assert isinstance(body["version"], str) and body["version"]

    def test_reports_the_live_provider_and_model(
        self, client: Any, config: Any
    ) -> None:
        body = client.get("/api/health").json()

        assert body["provider"] == config.llm.provider
        assert body["model"] == config.llm.model

    def test_reports_the_output_directory(self, client: Any, config: Any) -> None:
        body = client.get("/api/health").json()

        assert body["output_dir"] == config.execution.output_dir

    def test_never_leaks_a_key_value(self, client: Any, monkeypatch: Any) -> None:
        """SPEC-006 § 3.4 — names, never values."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-value")

        raw = client.get("/api/health").text

        assert "sk-super-secret-value" not in raw
        assert client.get("/api/health").json()["api_key_configured"] is True

    def test_credential_flag_follows_the_configured_env_var(
        self, client: Any, monkeypatch: Any
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        assert client.get("/api/health").json()["api_key_configured"] is False


class TestTools:
    """``GET /api/tools`` — the registry as the CLI's ``--list-tools`` sees it."""

    def test_lists_the_registered_tools(self, client: Any) -> None:
        names = [tool["name"] for tool in client.get("/api/tools").json()]

        assert "web_search" in names
        assert "file_write" in names

    def test_every_tool_has_the_three_descriptor_fields(self, client: Any) -> None:
        for tool in client.get("/api/tools").json():
            assert set(tool) == {"name", "description", "capabilities"}


class TestTaskSubmission:
    """``POST /api/tasks`` — validation, queueing and the returned record."""

    def test_creates_a_task_and_returns_its_record(self, client: Any) -> None:
        response = client.post("/api/tasks", json={"prompt": "research something"})

        assert response.status_code == 201
        body = response.json()
        assert body["prompt"] == "research something"
        assert body["status"] in {"queued", "running", "completed"}
        assert body["id"]

    def test_the_task_transitions_to_completed(self, client: Any) -> None:
        task_id = client.post("/api/tasks", json={"prompt": "do it"}).json()["id"]

        body = wait_for_task(client, task_id)

        assert body["status"] == "completed"
        assert body["finished_at"] is not None

    def test_a_completed_task_carries_the_deliverable_and_metrics(
        self, client: Any
    ) -> None:
        task_id = client.post("/api/tasks", json={"prompt": "do it"}).json()["id"]

        body = wait_for_task(client, task_id)

        assert body["final_output"]
        assert body["metrics"]["total_steps"] == 1
        assert body["metrics"]["tools_used"] == ["web_search"]
        assert body["report"]

    def test_a_blank_prompt_is_rejected_with_400(self, client: Any) -> None:
        response = client.post("/api/tasks", json={"prompt": "   "})

        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "PROMPT_INVALID"

    def test_a_prompt_at_the_character_limit_is_accepted(self, client: Any) -> None:
        """SPEC-005 § 1.1 step 1's bound is enforced by the schema, not by luck."""
        response = client.post("/api/tasks", json={"prompt": "x" * 20_000})

        assert response.status_code == 201

    def test_an_oversized_prompt_is_rejected_before_the_worker(
        self, client: Any
    ) -> None:
        response = client.post("/api/tasks", json={"prompt": "x" * 20_001})

        assert response.status_code == 422

    def test_an_unknown_field_is_rejected(self, client: Any) -> None:
        """No free-form request bodies (SKL backend/openapi-contract § 3.3)."""
        response = client.post(
            "/api/tasks", json={"prompt": "hi", "max_steps": "unlimited"}
        )

        assert response.status_code in {201, 422}


class TestTaskReads:
    """``GET /api/tasks`` and ``GET /api/tasks/{id}``."""

    def test_an_unknown_task_is_404_with_an_error_body(self, client: Any) -> None:
        response = client.get("/api/tasks/does-not-exist")

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "TASK_NOT_FOUND"

    def test_history_is_newest_first(self, client: Any) -> None:
        first = client.post("/api/tasks", json={"prompt": "first"}).json()["id"]
        second = client.post("/api/tasks", json={"prompt": "second"}).json()["id"]

        history = client.get("/api/tasks").json()

        assert [task["id"] for task in history][:2] == [second, first]

    def test_history_respects_the_limit(self, client: Any) -> None:
        for index in range(3):
            client.post("/api/tasks", json={"prompt": f"task {index}"})

        assert len(client.get("/api/tasks?limit=2").json()) == 2

    def test_steps_carry_their_terminal_status(self, client: Any) -> None:
        task_id = client.post("/api/tasks", json={"prompt": "do it"}).json()["id"]

        steps = wait_for_task(client, task_id)["steps"]

        assert [step["id"] for step in steps] == ["step_0"]
        assert steps[0]["status"] == "success"
        assert steps[0]["tool"] == "web_search"


class TestTaskEvents:
    """``GET /api/tasks/{id}/events`` — the cursor-based transport."""

    def test_events_start_at_sequence_one(self, client: Any) -> None:
        task_id = client.post("/api/tasks", json={"prompt": "do it"}).json()["id"]
        wait_for_task(client, task_id)

        page = client.get(f"/api/tasks/{task_id}/events").json()

        assert page["events"][0]["seq"] == 1
        assert page["terminal"] is True

    def test_the_cursor_returns_only_new_events(self, client: Any) -> None:
        task_id = client.post("/api/tasks", json={"prompt": "do it"}).json()["id"]
        wait_for_task(client, task_id)
        first = client.get(f"/api/tasks/{task_id}/events").json()
        cursor = first["events"][0]["seq"]

        second = client.get(f"/api/tasks/{task_id}/events?since={cursor}").json()

        assert all(event["seq"] > cursor for event in second["events"])
        assert second["next_seq"] == first["next_seq"]

    def test_a_finished_task_reports_the_lifecycle_in_order(self, client: Any) -> None:
        task_id = client.post("/api/tasks", json={"prompt": "do it"}).json()["id"]
        wait_for_task(client, task_id)

        kinds = [
            event["event"]
            for event in client.get(f"/api/tasks/{task_id}/events").json()["events"]
        ]

        assert kinds[0] == "plan_start"
        assert "step_start" in kinds
        assert "step_complete" in kinds
        assert kinds[-1] == "task_finished"

    def test_events_for_an_unknown_task_are_404(self, client: Any) -> None:
        assert client.get("/api/tasks/nope/events").status_code == 404


class TestStream:
    """``GET /api/tasks/{id}/stream`` — the Server-Sent Events transport."""

    def test_the_stream_is_an_event_stream(self, client: Any) -> None:
        task_id = client.post("/api/tasks", json={"prompt": "do it"}).json()["id"]
        wait_for_task(client, task_id)

        with client.stream("GET", f"/api/tasks/{task_id}/stream") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")

    def test_the_stream_replays_history_then_ends_with_done(self, client: Any) -> None:
        """A late subscriber still receives every event, then a terminal frame."""
        task_id = client.post("/api/tasks", json={"prompt": "do it"}).json()["id"]

        frames: list[str] = []
        with client.stream("GET", f"/api/tasks/{task_id}/stream") as response:
            for line in response.iter_lines():
                if line.startswith("event: "):
                    frames.append(line.removeprefix("event: "))
                    if frames[-1] == "done":
                        break

        assert frames[0] == "plan_start"
        assert "step_complete" in frames
        assert frames[-1] == "done"

    def test_each_data_frame_is_json(self, client: Any) -> None:
        task_id = client.post("/api/tasks", json={"prompt": "do it"}).json()["id"]

        payloads: list[dict[str, Any]] = []
        with client.stream("GET", f"/api/tasks/{task_id}/stream") as response:
            for line in response.iter_lines():
                if line.startswith("data: ") and line != "data: {}":
                    payloads.append(json.loads(line.removeprefix("data: ")))
                if line.startswith("event: done"):
                    break

        assert payloads
        for payload in payloads:
            assert {"seq", "at", "event", "fields"} <= set(payload)

    def test_the_since_parameter_skips_seen_events(self, client: Any) -> None:
        task_id = client.post("/api/tasks", json={"prompt": "do it"}).json()["id"]
        wait_for_task(client, task_id)
        total = client.get(f"/api/tasks/{task_id}/events").json()["next_seq"]

        assert total > 0

        frames: list[str] = []
        with client.stream(
            "GET", f"/api/tasks/{task_id}/stream?since={total}"
        ) as response:
            for line in response.iter_lines():
                if line.startswith("event: "):
                    frames.append(line.removeprefix("event: "))
                    break

        assert frames == ["done"]


class TestArtifacts:
    """``GET /api/artifacts`` — the output directory, contained."""

    def test_an_empty_output_directory_is_an_empty_list(self, client: Any) -> None:
        assert client.get("/api/artifacts").json() == []

    def test_a_written_file_appears_with_its_metadata(
        self, client: Any, config: Any
    ) -> None:
        (pathlib.Path(config.execution.output_dir) / "report.md").write_text(
            "# Findings\n", encoding="utf-8"
        )

        listed = client.get("/api/artifacts").json()

        assert listed[0]["path"] == "report.md"
        assert listed[0]["kind"] == "markdown"
        assert listed[0]["size_bytes"] == len(b"# Findings\n")

    def test_nested_files_are_listed_with_a_relative_path(
        self, client: Any, config: Any
    ) -> None:
        nested = pathlib.Path(config.execution.output_dir) / "run-1"
        nested.mkdir()
        (nested / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")

        assert client.get("/api/artifacts").json()[0]["path"] == "run-1/data.csv"

    def test_a_file_can_be_downloaded(self, client: Any, config: Any) -> None:
        (pathlib.Path(config.execution.output_dir) / "report.md").write_text(
            "# Findings\n", encoding="utf-8"
        )

        response = client.get("/api/artifacts/report.md")

        assert response.status_code == 200
        assert response.text == "# Findings\n"

    def test_a_traversal_attempt_is_refused(self, client: Any, scratch: Any) -> None:
        """Containment is checked on the resolved path (SKL threat-model-sast).

        The request is issued through the container's resolver rather than as a
        URL, because an HTTP client would normalize ``..`` away before the server
        ever saw it — the assertion has to reach the check itself.
        """
        from agent_harness.web.runner import ArtifactError, TaskRunner

        secret = scratch / "outside.txt"
        secret.write_text("not yours", encoding="utf-8")
        runner = client.app.state.runner
        assert isinstance(runner, TaskRunner)

        with pytest.raises(ArtifactError, match="escapes"):
            runner.resolve_artifact("../outside.txt")

    def test_an_absolute_path_is_refused(self, client: Any, scratch: Any) -> None:
        target = scratch / "outside.txt"
        target.write_text("not yours", encoding="utf-8")

        response = client.get(f"/api/artifacts/{target.as_posix().lstrip('/')}")

        assert response.status_code in {400, 404}

    def test_a_missing_file_is_refused(self, client: Any) -> None:
        response = client.get("/api/artifacts/nope.md")

        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "ARTIFACT_INVALID"


class TestUiAndDocs:
    """The single-page UI and the generated OpenAPI document."""

    def test_the_index_is_served(self, client: Any) -> None:
        response = client.get("/")

        assert response.status_code == 200
        assert "Agent Harness" in response.text

    def test_the_index_references_only_local_assets(self, client: Any) -> None:
        """No CDN: the UI must work offline (PRD G6)."""
        html = client.get("/").text

        assert "http://" not in html.split("<script")[0].replace(
            "http://www.w3.org", ""
        )
        assert "/static/app.js" in html
        assert "/static/tokens.css" in html

    @pytest.mark.parametrize(
        "asset", ["/static/tokens.css", "/static/app.css", "/static/app.js"]
    )
    def test_every_static_asset_is_served(self, client: Any, asset: str) -> None:
        response = client.get(asset)

        assert response.status_code == 200
        assert response.text.strip()

    def test_openapi_is_available_and_lists_the_task_route(self, client: Any) -> None:
        document = client.get("/api/openapi.json").json()

        assert "/api/tasks" in document["paths"]
        assert "post" in document["paths"]["/api/tasks"]

    def test_the_openapi_document_declares_the_task_schema(self, client: Any) -> None:
        document = client.get("/api/openapi.json").json()

        assert "TaskRequest" in document["components"]["schemas"]

    def test_the_documented_routes_all_answer(self, client: Any) -> None:
        """Every operation in the published document exists at runtime."""
        document = client.get("/api/openapi.json").json()

        for path, methods in document["paths"].items():
            if "{" in path:
                continue
            for method in methods:
                response = client.request(method.upper(), path)
                assert response.status_code < 500, f"{method.upper()} {path} failed"


class TestRunnerLifecycle:
    """The runner's contract with its caller, independent of HTTP."""

    def test_submit_returns_before_the_work_finishes(self, runner: Any) -> None:
        """Submission is asynchronous: the response must never wait for the run."""
        task = runner.submit("do it")

        assert task.status in {"queued", "running"}
        assert task.prompt == "do it"

    def test_an_unknown_task_reads_back_as_none(self, runner: Any) -> None:
        assert runner.get("no-such-task") is None

    def test_a_second_task_waits_for_the_first(self, config: Any) -> None:
        """One worker: runs are serialized rather than interleaved (SPEC-005 § 5)."""
        import threading
        import time as time_module

        from agent_harness.web.runner import TaskRunner

        started: list[str] = []
        lock = threading.Lock()

        def factory(progress: Any) -> Any:
            def record(prompt: str) -> None:
                with lock:
                    started.append(prompt)

            class _Harness:
                last_report = None

                def run(self, prompt: str) -> Any:
                    record(prompt)
                    time_module.sleep(0.05)
                    return _Result()

                def close(self) -> None:
                    return None

            return _Harness()

        class _Result:
            status = "completed"
            final_output = "ok"
            plan = None
            metrics = None
            files_created: list[str] = []
            errors: list[dict[str, Any]] = []

        task_runner = TaskRunner(config, harness_factory=factory)
        try:
            first = task_runner.submit("first")
            second = task_runner.submit("second")
            deadline = time_module.monotonic() + 5
            while time_module.monotonic() < deadline:
                if both_terminal(task_runner, first.id, second.id):
                    break
                time_module.sleep(0.01)

            assert started == ["first", "second"]
        finally:
            task_runner.shutdown()


def both_terminal(runner: Any, *ids: str) -> bool:
    """Whether every listed task has reached a terminal state."""
    return all(runner.get(task_id).terminal for task_id in ids)
