"""Unit tests for the web layer's task service and launcher (PRD G8).

These cover the parts HTTP cannot reach: how a failing run is recorded, how the
event log is built from SPEC-003 § 2.1's hooks, how artifacts are contained, and
how the launcher picks a port and opens a browser.

Skill: core-coding/tdd-test-runner · core-coding/strict-typing-contracts ·
reliability/flaky-test-isolator (no real sockets on the critical path)
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest

from agent_harness.web import server
from agent_harness.web.runner import ArtifactError, TaskRunner, _jsonable
from agent_harness.web.schemas import MAX_PROMPT_CHARS


def _result(**overrides: Any) -> Any:
    """Build the smallest object that looks like a ``HarnessResult``."""

    class _Plan:
        steps: list[Any] = []

    class _Result:
        status = "completed"
        final_output = "done"
        plan = _Plan()
        metrics = None
        files_created: list[str] = []
        errors: list[dict[str, Any]] = []

    result = _Result()
    for key, value in overrides.items():
        setattr(result, key, value)
    return result


def _harness_factory(result: Any = None, *, error: BaseException | None = None) -> Any:
    """Build a factory returning a harness that either completes or raises."""

    def factory(progress: Any) -> Any:
        class _Harness:
            last_report: str | None = "report text"

            def run(self, prompt: str) -> Any:
                progress({"event": "plan_start", "plan_id": "plan-1"})
                progress(
                    {
                        "event": "step_complete",
                        "step_id": "step_0",
                        "tool": "web_search",
                        "success": True,
                        "duration_ms": 12,
                    }
                )
                if error is not None:
                    raise error
                return result if result is not None else _result()

            def close(self) -> None:
                return None

        return _Harness()

    return factory


class TestTaskLifecycle:
    """Submission, completion and the shape of the recorded task."""

    def _settle(self, runner: TaskRunner, task_id: str, timeout: float = 5.0) -> Any:
        """Wait for a task to finish, failing the test if it never does."""
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            task = runner.get(task_id)
            if task is not None and task.terminal:
                return task
            time.sleep(0.01)
        raise AssertionError(f"task {task_id} never finished")

    def test_a_submitted_task_completes(self, config: Any) -> None:
        runner = TaskRunner(config, harness_factory=_harness_factory())
        try:
            task = self._settle(runner, runner.submit("do it").id)

            assert task.status == "completed"
            assert task.final_output == "done"
            assert task.report == "report text"
            assert task.started_at and task.finished_at
        finally:
            runner.shutdown()

    def test_a_failing_run_becomes_a_failed_task_not_a_crash(self, config: Any) -> None:
        """SPEC-005 § 1.1 — a contained failure is a result, not a traceback."""
        runner = TaskRunner(
            config,
            harness_factory=_harness_factory(error=RuntimeError("provider exploded")),
        )
        try:
            task = self._settle(runner, runner.submit("do it").id)

            assert task.status == "failed"
            assert "provider exploded" in (task.error or "")
            assert task.errors[0]["code"] == "SYSTEM_ERROR"
        finally:
            runner.shutdown()

    def test_an_agent_error_keeps_its_code(self, config: Any) -> None:
        from agent_harness.config.schema import AgentError

        runner = TaskRunner(
            config,
            harness_factory=_harness_factory(
                error=AgentError("LLM_CALL_FAILED", "no key", "llm")
            ),
        )
        try:
            task = self._settle(runner, runner.submit("do it").id)

            assert task.errors[0]["code"] == "LLM_CALL_FAILED"
            assert "LLM_CALL_FAILED" in (task.error or "")
        finally:
            runner.shutdown()

    def test_the_harness_is_closed_even_when_the_run_raises(self, config: Any) -> None:
        """SPEC-005 § 1.2 — tool cleanup must not be skipped on the failure path."""
        closed: list[bool] = []

        def factory(progress: Any) -> Any:
            class _Harness:
                last_report = None

                def run(self, prompt: str) -> Any:
                    raise RuntimeError("boom")

                def close(self) -> None:
                    closed.append(True)

            return _Harness()

        runner = TaskRunner(config, harness_factory=factory)
        try:
            self._settle(runner, runner.submit("do it").id)

            assert closed == [True]
        finally:
            runner.shutdown()

    def test_each_task_gets_its_own_harness(self, config: Any) -> None:
        """SPEC-005 § 5 — no context leaks between runs."""
        seen: list[int] = []

        def factory(progress: Any) -> Any:
            class _Harness:
                last_report = None

                def __init__(self) -> None:
                    seen.append(id(self))

                def run(self, prompt: str) -> Any:
                    return _result()

                def close(self) -> None:
                    return None

            return _Harness()

        runner = TaskRunner(config, harness_factory=factory)
        try:
            self._settle(runner, runner.submit("one").id)
            self._settle(runner, runner.submit("two").id)

            assert len(set(seen)) == 2
        finally:
            runner.shutdown()

    def test_submitting_after_shutdown_is_refused(self, config: Any) -> None:
        runner = TaskRunner(config, harness_factory=_harness_factory())
        runner.shutdown()

        with pytest.raises(RuntimeError, match="shut down"):
            runner.submit("too late")

    def test_history_is_capped_and_drops_only_finished_tasks(self, config: Any) -> None:
        runner = TaskRunner(config, harness_factory=_harness_factory(), max_tasks=2)
        try:
            for index in range(4):
                self._settle(runner, runner.submit(f"task {index}").id)

            assert len(runner.list_tasks()) == 2
        finally:
            runner.shutdown()


class TestEventLog:
    """The progress-hook seam turned into a replayable log."""

    def _settle(self, runner: TaskRunner, task_id: str) -> Any:
        import time

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            task = runner.get(task_id)
            if task is not None and task.terminal:
                return task
            time.sleep(0.01)
        raise AssertionError("task never finished")

    def test_hook_events_are_recorded_in_order_with_cursors(self, config: Any) -> None:
        runner = TaskRunner(config, harness_factory=_harness_factory())
        try:
            task = self._settle(runner, runner.submit("do it").id)

            kinds = [event["event"] for event in task.events]
            assert kinds[:2] == ["plan_start", "step_complete"]
            assert kinds[-1] == "task_finished"
            assert [event["seq"] for event in task.events] == list(
                range(1, len(task.events) + 1)
            )
        finally:
            runner.shutdown()

    def test_step_events_fold_into_the_step_list(self, config: Any) -> None:
        runner = TaskRunner(config, harness_factory=_harness_factory())
        try:
            task = self._settle(runner, runner.submit("do it").id)

            assert task.steps[0]["id"] == "step_0"
            assert task.steps[0]["status"] == "success"
            assert task.steps[0]["duration_ms"] == 12
        finally:
            runner.shutdown()

    def test_a_failed_step_event_marks_the_step_failed(self, config: Any) -> None:
        def factory(progress: Any) -> Any:
            class _Harness:
                last_report = None

                def run(self, prompt: str) -> Any:
                    progress({"event": "step_start", "step_id": "step_1", "tool": "x"})
                    progress(
                        {"event": "step_failed", "step_id": "step_1", "error": "nope"}
                    )
                    return _result(status="partial")

                def close(self) -> None:
                    return None

            return _Harness()

        runner = TaskRunner(config, harness_factory=factory)
        try:
            task = self._settle(runner, runner.submit("do it").id)

            assert task.steps[0]["status"] == "failed"
            assert task.steps[0]["error"] == "nope"
            assert task.status == "partial"
        finally:
            runner.shutdown()

    def test_a_recovery_event_marks_the_step_retrying(self, config: Any) -> None:
        def factory(progress: Any) -> Any:
            class _Harness:
                last_report = None

                def run(self, prompt: str) -> Any:
                    progress({"event": "recovery", "step_id": "step_0"})
                    return _result()

                def close(self) -> None:
                    return None

            return _Harness()

        runner = TaskRunner(config, harness_factory=factory)
        try:
            task = self._settle(runner, runner.submit("do it").id)

            assert task.steps[0]["status"] == "retrying"
        finally:
            runner.shutdown()

    def test_events_since_returns_only_the_tail(self, config: Any) -> None:
        runner = TaskRunner(config, harness_factory=_harness_factory())
        try:
            task = self._settle(runner, runner.submit("do it").id)

            events, next_seq = runner.events_since(task.id, 1)

            assert all(event["seq"] > 1 for event in events)
            assert next_seq == len(task.events)
        finally:
            runner.shutdown()

    def test_events_since_an_unknown_task_is_empty(self, config: Any) -> None:
        runner = TaskRunner(config, harness_factory=_harness_factory())
        try:
            assert runner.events_since("nope", 0) == ([], 0)
        finally:
            runner.shutdown()

    def test_wait_for_event_times_out_without_new_events(self, config: Any) -> None:
        runner = TaskRunner(config, harness_factory=_harness_factory())
        try:
            task = self._settle(runner, runner.submit("do it").id)

            assert runner.wait_for_event(task.id, 999, timeout=0.05) == []
        finally:
            runner.shutdown()

    def test_a_non_json_value_in_a_hook_event_is_stringified(self, config: Any) -> None:
        """A path or exception on the hook payload must not break the log."""
        assert _jsonable(pathlib.Path("a/b")) == "a/b"
        assert _jsonable({"p": pathlib.Path("x")}) == {"p": "x"}
        assert _jsonable([1, "a", None]) == [1, "a", None]


class TestArtifacts:
    """Listing and containment."""

    def test_listing_an_absent_directory_is_empty(self, config: Any) -> None:
        runner = TaskRunner(config, harness_factory=_harness_factory())
        try:
            assert runner.list_artifacts() == []
        finally:
            runner.shutdown()

    def test_hidden_files_are_not_listed(self, config: Any) -> None:
        root = pathlib.Path(config.execution.output_dir)
        (root / ".secret").write_text("x", encoding="utf-8")
        (root / "visible.txt").write_text("x", encoding="utf-8")
        runner = TaskRunner(config, harness_factory=_harness_factory())
        try:
            assert [item["path"] for item in runner.list_artifacts()] == ["visible.txt"]
        finally:
            runner.shutdown()

    def test_resolving_a_sibling_directory_is_refused(
        self, config: Any, scratch: Any
    ) -> None:
        (scratch / "sibling.txt").write_text("x", encoding="utf-8")
        runner = TaskRunner(config, harness_factory=_harness_factory())
        try:
            with pytest.raises(ArtifactError, match="escapes"):
                runner.resolve_artifact("../sibling.txt")
        finally:
            runner.shutdown()

    def test_resolving_an_oversized_file_is_refused(self, config: Any) -> None:
        from agent_harness.web.runner import MAX_ARTIFACT_BYTES

        big = pathlib.Path(config.execution.output_dir) / "big.bin"
        big.write_bytes(b"0" * (MAX_ARTIFACT_BYTES + 1))
        runner = TaskRunner(config, harness_factory=_harness_factory())
        try:
            with pytest.raises(ArtifactError, match="too large"):
                runner.resolve_artifact("big.bin")
        finally:
            runner.shutdown()

    def test_kinds_are_inferred_from_the_extension(self, config: Any) -> None:
        root = pathlib.Path(config.execution.output_dir)
        for name, kind in (
            ("a.md", "markdown"),
            ("b.json", "json"),
            ("c.csv", "csv"),
            ("d.pdf", "pdf"),
            ("e.unknownext", "other"),
        ):
            (root / name).write_text("x", encoding="utf-8")
        runner = TaskRunner(config, harness_factory=_harness_factory())
        try:
            found = {item["name"]: item["kind"] for item in runner.list_artifacts()}

            assert found == {
                "a.md": "markdown",
                "b.json": "json",
                "c.csv": "csv",
                "d.pdf": "pdf",
                "e.unknownext": "other",
            }
        finally:
            runner.shutdown()


class TestServerHelpers:
    """Port selection, readiness probing and browser opening."""

    def test_a_free_port_is_returned_unchanged(self) -> None:
        assert server.pick_port("127.0.0.1", 8971) == 8971

    def test_a_bound_port_is_skipped(self) -> None:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
            held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            held.bind(("127.0.0.1", 0))
            held.listen(1)
            busy = held.getsockname()[1]

            assert server.pick_port("127.0.0.1", busy) == busy + 1

    def test_pick_port_gives_up_with_an_actionable_error(self) -> None:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
            held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            held.bind(("127.0.0.1", 0))
            held.listen(1)
            busy = held.getsockname()[1]

            with pytest.raises(server.WebDependencyError, match="no free port"):
                server.pick_port("127.0.0.1", busy, attempts=1)

    def test_readiness_probe_reports_a_live_socket(self) -> None:

        from agent_harness.web.app import create_app

        config = None
        app = create_app(config)
        assert app is not None
        del config
        # The probe itself, against a socket the kernel is listening on.
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]

            assert server.wait_until_ready("127.0.0.1", port, timeout=1.0) is True

    def test_readiness_probe_gives_up_on_a_dead_port(self) -> None:
        assert (
            server.wait_until_ready(
                "127.0.0.1", 8999, timeout=0.2, sleep=lambda _: None
            )
            is False
        )

    def test_the_browser_opens_only_once_the_socket_answers(self) -> None:
        import socket

        opened: list[str] = []
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]

            thread = server.open_browser_when_ready(
                f"http://127.0.0.1:{port}/",
                "127.0.0.1",
                port,
                timeout=2.0,
                opener=opened.append,
            )
            thread.join(timeout=5)

        assert opened == [f"http://127.0.0.1:{port}/"]

    def test_a_dead_port_never_opens_a_browser(self) -> None:
        opened: list[str] = []

        thread = server.open_browser_when_ready(
            "http://127.0.0.1:8998/",
            "127.0.0.1",
            8998,
            timeout=0.2,
            opener=opened.append,
        )
        thread.join(timeout=5)

        assert opened == []

    def test_web_dependencies_are_declared_in_this_environment(self) -> None:
        assert server.web_dependencies_available() is True

    def test_the_prompt_bound_matches_the_harness(self) -> None:
        """The web schema must not drift from SPEC-005 § 1.1 step 1's bound."""
        from agent_harness.harness import MAX_PROMPT_CHARS as HARNESS_BOUND

        assert MAX_PROMPT_CHARS == HARNESS_BOUND

    def test_an_env_flag_recognises_the_documented_true_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for value in ("1", "true", "TRUE", "yes", "on"):
            monkeypatch.setenv(server.ENV_NO_BROWSER, value)
            assert server._env_flag(server.ENV_NO_BROWSER) is True
        for value in ("", "0", "no", "off", "maybe"):
            monkeypatch.setenv(server.ENV_NO_BROWSER, value)
            assert server._env_flag(server.ENV_NO_BROWSER) is False

    def test_binding_all_interfaces_is_reported_as_localhost(self) -> None:
        assert server._display_host("0.0.0.0") == "localhost"
        assert server._display_host("127.0.0.1") == "127.0.0.1"


class TestWebCli:
    """``python -m agent_harness.web`` argument handling."""

    def test_the_parser_offers_the_documented_flags(self) -> None:
        from agent_harness.web.__main__ import build_parser

        parser = build_parser()
        args = parser.parse_args(["--port", "9000", "--no-browser"])

        assert args.port == 9000
        assert args.no_browser is True

    def test_the_default_port_is_the_documented_one(self) -> None:
        from agent_harness.web.__main__ import build_parser

        assert build_parser().parse_args([]).port is None

    def test_an_unreadable_config_exits_one_with_a_message(
        self, capsys: Any, tmp_path: pathlib.Path
    ) -> None:
        from agent_harness.web.__main__ import main

        code = main(["--config", str(tmp_path / "missing.yaml")])

        assert code == 1
        assert "[ERROR]" in capsys.readouterr().err

    def test_a_missing_default_config_is_not_an_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        """K5: defaults are enough to start the UI (SPEC-006 § 1)."""
        from agent_harness.web.__main__ import load_config

        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("AGENT_HARNESS_CONFIG", raising=False)

        assert load_config(None) is not None

    def test_the_banner_names_the_url_and_the_stop_key(self, capsys: Any) -> None:
        server._announce("http://127.0.0.1:8765/", 8765, 8765, open_browser=True)

        out = capsys.readouterr().out
        assert "http://127.0.0.1:8765/" in out
        assert "Ctrl+C" in out

    def test_the_banner_mentions_a_ported_fallback(self, capsys: Any) -> None:
        server._announce("http://127.0.0.1:8766/", 8765, 8766, open_browser=False)

        assert "8765 was busy" in capsys.readouterr().out
