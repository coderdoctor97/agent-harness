"""CLI contract tests (SPEC-005 § 2).

Every test here is deterministic: no network, no LLM, no subprocess unless a
test says so explicitly. Sub-phase 4.1 covers parsing and the flag-to-config
override mapping; dispatch, exit codes and rendering arrive in 4.2-4.5.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _p4_doubles as doubles  # after the sys.path bootstrap above

from agent_harness import __main__ as cli_module
from agent_harness.__main__ import (
    LOG_LEVELS,
    USAGE,
    apply_cli_overrides,
    build_parser,
    parse_args,
    read_prompt,
    resolve_config_path,
)


def test_the_real_modules_are_installed() -> None:
    """Guard: the CLI suite runs against the composed system, never over a fake one."""
    import agent_harness.tools as tools_module

    assert tools_module.BaseTool is doubles.BaseTool
    assert doubles.Config().execution.max_steps == 20


# ---------------------------------------------------------------------------
# Sub-phase 4.1 — the parser
# ---------------------------------------------------------------------------


class TestParserSurface:
    """SPEC-005 § 2 — the flag table, verbatim."""

    def test_the_documented_flags_all_exist(self) -> None:
        """Every flag in the spec's usage line is a real option."""
        parser = build_parser()
        options = {
            option for action in parser._actions for option in action.option_strings
        }

        assert {
            "--config",
            "--output-dir",
            "--log-level",
            "--dry-run",
            "--list-tools",
            "--max-steps",
            "--no-fallback",
            "-h",
        } <= options

    def test_usage_matches_the_frozen_contract(self) -> None:
        """The printed usage is the one the spec froze.

        Compared whitespace-normalised, because argparse re-wraps the line to
        the terminal width while the spec's block is wrapped by hand.
        """
        parser = build_parser()
        printed = " ".join(parser.format_usage().split())

        assert parser.prog == "python -m agent_harness"
        assert printed == " ".join(USAGE.split())

    def test_defaults(self) -> None:
        """Nothing set means every override stays ``None``."""
        args = parse_args(["Summarise the report"])

        assert args.prompt == "Summarise the report"
        assert args.config is None
        assert args.output_dir is None
        assert args.log_level is None
        assert args.max_steps is None
        assert args.dry_run is False
        assert args.list_tools is False
        assert args.no_fallback is False

    def test_every_flag_can_be_set_at_once(self) -> None:
        """The full command line parses."""
        args = parse_args(
            [
                "--config",
                "/tmp/c.yaml",
                "--output-dir",
                "/tmp/out",
                "--log-level",
                "DEBUG",
                "--dry-run",
                "--max-steps",
                "7",
                "--no-fallback",
                "Do the thing",
            ]
        )

        assert args.config == "/tmp/c.yaml"
        assert args.output_dir == "/tmp/out"
        assert args.log_level == "DEBUG"
        assert args.dry_run is True
        assert args.max_steps == 7
        assert args.no_fallback is True
        assert args.prompt == "Do the thing"

    def test_list_tools_needs_no_prompt(self) -> None:
        """SPEC-005 § 2 — the one command that works without a task."""
        args = parse_args(["--list-tools"])

        assert args.list_tools is True
        assert args.prompt is None

    def test_a_missing_prompt_without_list_tools_is_a_usage_error(self) -> None:
        """Nothing to do and nothing to list means the user made a mistake."""
        with pytest.raises(SystemExit) as exit_info:
            parse_args([])

        assert exit_info.value.code == 2

    def test_an_unknown_flag_is_a_usage_error(self) -> None:
        """Exit code 2 is argparse's, and the spec keeps it."""
        with pytest.raises(SystemExit) as exit_info:
            parse_args(["--nonsense", "hello"])

        assert exit_info.value.code == 2

    def test_help_exits_zero(self) -> None:
        """``-h`` is not an error."""
        with pytest.raises(SystemExit) as exit_info:
            parse_args(["-h"])

        assert exit_info.value.code == 0


class TestLogLevel:
    """SPEC-005 § 2 — ``DEBUG|INFO|WARNING|ERROR``."""

    def test_the_four_levels_are_the_documented_ones(self) -> None:
        """The constant the parser is built from matches the spec."""
        assert LOG_LEVELS == ("DEBUG", "INFO", "WARNING", "ERROR")

    @pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR"])
    def test_each_documented_level_is_accepted(self, level: str) -> None:
        """All four parse."""
        assert parse_args(["--log-level", level, "task"]).log_level == level

    def test_levels_are_case_insensitive(self) -> None:
        """Users type lowercase; the config value is upper case."""
        args = parse_args(["--log-level", "debug", "task"])

        assert args.log_level == "DEBUG"

    def test_an_undocumented_level_is_a_usage_error(self) -> None:
        """``TRACE`` and ``CRITICAL`` are not in the contract."""
        with pytest.raises(SystemExit) as exit_info:
            parse_args(["--log-level", "TRACE", "task"])

        assert exit_info.value.code == 2


class TestMaxSteps:
    """SPEC-005 § 2 — a positive integer."""

    def test_a_positive_integer_is_accepted(self) -> None:
        """The normal case."""
        assert parse_args(["--max-steps", "12", "task"]).max_steps == 12

    def test_one_is_accepted(self) -> None:
        """The boundary of 'positive'."""
        assert parse_args(["--max-steps", "1", "task"]).max_steps == 1

    @pytest.mark.parametrize("bad", ["0", "-1", "-20"])
    def test_a_non_positive_integer_is_a_usage_error(self, bad: str) -> None:
        """Plan 4.4 exit criterion: ``--max-steps 0`` exits 2."""
        with pytest.raises(SystemExit) as exit_info:
            parse_args(["--max-steps", bad, "task"])

        assert exit_info.value.code == 2

    @pytest.mark.parametrize("bad", ["abc", "1.5", ""])
    def test_a_non_integer_is_a_usage_error(self, bad: str) -> None:
        """Not a number at all."""
        with pytest.raises(SystemExit) as exit_info:
            parse_args(["--max-steps", bad, "task"])

        assert exit_info.value.code == 2

    def test_the_error_message_names_the_flag(self) -> None:
        """A bare 'invalid int value' does not help the user."""
        parser = build_parser()

        with pytest.raises(SystemExit):
            parser.parse_args(["--max-steps", "0"])

        assert "--max-steps" in parser.format_usage()


class TestPromptFromStdin:
    """SPEC-005 § 2 — ``-`` reads the prompt from stdin."""

    def test_a_dash_reads_stdin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The piped-prompt form."""
        import io

        monkeypatch.setattr(sys, "stdin", io.StringIO("Summarise this\n"))

        prompt = read_prompt(parse_args(["-"]))

        assert prompt == "Summarise this"

    def test_stdin_is_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Trailing newlines from a pipe are not part of the task."""
        import io

        monkeypatch.setattr(sys, "stdin", io.StringIO("\n  Do it  \n\n"))

        assert read_prompt(parse_args(["-"])) == "Do it"

    def test_an_empty_stdin_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty prompt is a usage error, not an empty task."""
        import io

        monkeypatch.setattr(sys, "stdin", io.StringIO("   \n"))

        with pytest.raises(SystemExit) as exit_info:
            read_prompt(parse_args(["-"]))

        assert exit_info.value.code == 2

    def test_a_literal_prompt_is_returned_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``-`` is special only when it is the whole argument."""
        import io

        monkeypatch.setattr(sys, "stdin", io.StringIO("never read"))

        assert read_prompt(parse_args(["say - please"])) == "say - please"

    def test_no_prompt_returns_none(self) -> None:
        """``--list-tools`` has nothing to read."""
        assert read_prompt(parse_args(["--list-tools"])) is None


class TestConfigPathResolution:
    """SPEC-005 § 2 — ``./config.yaml``, then ``AGENT_HARNESS_CONFIG``."""

    def test_an_explicit_flag_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CLI beats environment (SPEC-006 § 1.2)."""
        monkeypatch.setenv("AGENT_HARNESS_CONFIG", "/env/config.yaml")

        args = parse_args(["--config", "/flag/config.yaml", "--list-tools"])

        assert resolve_config_path(args) == "/flag/config.yaml"

    def test_the_environment_variable_is_next(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No flag means the env var decides."""
        monkeypatch.setenv("AGENT_HARNESS_CONFIG", "/env/config.yaml")

        assert resolve_config_path(parse_args(["--list-tools"])) == "/env/config.yaml"

    def test_the_default_is_the_documented_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing set means ``./config.yaml``."""
        monkeypatch.delenv("AGENT_HARNESS_CONFIG", raising=False)

        assert resolve_config_path(parse_args(["--list-tools"])) == "./config.yaml"

    def test_an_empty_environment_variable_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``AGENT_HARNESS_CONFIG=`` is unset, not a path."""
        monkeypatch.setenv("AGENT_HARNESS_CONFIG", "")

        assert resolve_config_path(parse_args(["--list-tools"])) == "./config.yaml"


class TestOverrideMapping:
    """Plan 4.1 exit criterion: every flag produces the documented override."""

    def test_no_flags_leave_the_config_alone(self) -> None:
        """The mapping is opt-in."""
        config = doubles.Config()
        before = config.to_dict(redact_secrets=False)

        apply_cli_overrides(config, parse_args(["task"]))

        assert config.to_dict(redact_secrets=False) == before

    def test_output_dir_maps_to_execution_output_dir(self) -> None:
        """SPEC-005 § 2 row 3."""
        config = doubles.Config()

        apply_cli_overrides(config, parse_args(["--output-dir", "/tmp/out", "task"]))

        assert config.execution.output_dir == "/tmp/out"

    def test_max_steps_maps_to_execution_max_steps(self) -> None:
        """SPEC-005 § 2 row 8."""
        config = doubles.Config()

        apply_cli_overrides(config, parse_args(["--max-steps", "5", "task"]))

        assert config.execution.max_steps == 5

    def test_log_level_maps_to_logging_level(self) -> None:
        """SPEC-005 § 2 row 4."""
        config = doubles.Config()

        apply_cli_overrides(config, parse_args(["--log-level", "ERROR", "task"]))

        assert config.logging.level == "ERROR"

    def test_no_fallback_disables_replan(self) -> None:
        """SPEC-005 § 2 row 9 — the config half of the flag."""
        config = doubles.Config()
        assert config.execution.enable_replan is True

        apply_cli_overrides(config, parse_args(["--no-fallback", "task"]))

        assert config.execution.enable_replan is False

    def test_log_level_from_the_environment_applies_without_a_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SPEC-006 § 1.2 — env sits between CLI and file."""
        monkeypatch.setenv("AGENT_HARNESS_LOG_LEVEL", "WARNING")
        config = doubles.Config()

        apply_cli_overrides(config, parse_args(["task"]))

        assert config.logging.level == "WARNING"

    def test_the_flag_beats_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLI is highest precedence."""
        monkeypatch.setenv("AGENT_HARNESS_LOG_LEVEL", "WARNING")
        config = doubles.Config()

        apply_cli_overrides(config, parse_args(["--log-level", "DEBUG", "task"]))

        assert config.logging.level == "DEBUG"

    def test_an_invalid_environment_level_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A typo in the environment must not corrupt the config."""
        monkeypatch.setenv("AGENT_HARNESS_LOG_LEVEL", "shouty")
        config = doubles.Config()

        apply_cli_overrides(config, parse_args(["task"]))

        assert config.logging.level == "INFO"

    def test_several_flags_apply_together(self) -> None:
        """The whole table at once."""
        config = doubles.Config()

        apply_cli_overrides(
            config,
            parse_args(
                [
                    "--output-dir",
                    "/o",
                    "--max-steps",
                    "3",
                    "--log-level",
                    "DEBUG",
                    "--no-fallback",
                    "task",
                ]
            ),
        )

        assert config.execution.output_dir == "/o"
        assert config.execution.max_steps == 3
        assert config.logging.level == "DEBUG"
        assert config.execution.enable_replan is False

    def test_a_config_with_apply_overrides_is_used_when_present(self) -> None:
        """Plan 1's ``apply_overrides`` is the seam, and its hooks are flat names.

        SPEC-006 § 1.2 names the hooks ``output_dir`` / ``log_level`` / ``max_steps`` /
        ``no_fallback``, so Plan 4 translates its dotted paths before the call. The
        stub-era assertion pinned a *positional mapping*, which the shipped
        keyword-only signature rejects (SCR-P4-11).
        """
        calls: list[dict[str, Any]] = []

        class RecordingConfig:
            def apply_overrides(self, **hooks: Any) -> None:
                """Capture the hooks P1 is asked to apply."""
                calls.append(hooks)

        config = RecordingConfig()

        apply_cli_overrides(
            config, parse_args(["--max-steps", "9", "--no-fallback", "task"])
        )

        assert calls == [{"max_steps": 9, "no_fallback": True}]

    def test_the_hook_translation_covers_every_dotted_path(self) -> None:
        """No path :func:`collect_overrides` can emit lacks a hook name (SCR-P4-9)."""
        from agent_harness.__main__ import OVERRIDE_PATHS, _hook_kwargs

        translated = _hook_kwargs(dict.fromkeys(OVERRIDE_PATHS.values(), 1))

        assert set(translated) == set(OVERRIDE_PATHS)
        assert _hook_kwargs({"execution.enable_replan": False}) == {"no_fallback": True}

    def test_the_override_mapping_is_dotted_paths(self) -> None:
        """The seam takes ``config.get``-style keys, not attribute names."""
        config = doubles.Config()

        apply_cli_overrides(config, parse_args(["--output-dir", "/x", "task"]))

        assert config.get("execution.output_dir") == "/x"


class TestParserObject:
    """The parser is a plain, inspectable ``ArgumentParser``."""

    def test_it_is_an_argument_parser(self) -> None:
        """So ``--help`` and error handling are argparse's own."""
        assert isinstance(build_parser(), argparse.ArgumentParser)

    def test_it_is_rebuilt_fresh_each_call(self) -> None:
        """No module-level parser state leaking between invocations."""
        assert build_parser() is not build_parser()


# ---------------------------------------------------------------------------
# Sub-phase 4.2 — dispatch and exit codes
# ---------------------------------------------------------------------------

from agent_harness.__main__ import (  # noqa: E402
    EXIT_FAILED,
    EXIT_INTERRUPTED,
    EXIT_OK,
    EXIT_PARTIAL,
    EXIT_USAGE,
    main,
)


def _fake_plan(n_steps: int = 2) -> Any:
    """A small execution plan for dry-run rendering."""
    plan = doubles.ExecutionPlan(original_prompt="do things")
    for index in range(n_steps):
        plan.steps.append(
            doubles.Step(
                id=f"step{index + 1}",
                description=f"Do step {index + 1}",
                tool_name="echo",
                depends_on=[] if index == 0 else [f"step{index}"],
            )
        )
    return plan


def _fake_result(status: str) -> Any:
    """A ``HarnessResult`` with the given terminal status."""
    from agent_harness.harness import HarnessResult

    return HarnessResult(
        status=status,
        final_output="all done" if status == "completed" else None,
        plan=_fake_plan(),
        metrics=None,
        files_created=[],
        errors=[],
    )


class _FakeHarness:
    """A harness double recording every call the CLI makes."""

    def __init__(
        self,
        config: Any,
        *,
        tools: list[dict[str, Any]] | None = None,
        plan: Any = None,
        result: Any = None,
        run_error: BaseException | None = None,
        plan_error: BaseException | None = None,
        plugin_errors: list[Any] | None = None,
    ) -> None:
        """Store the canned responses."""
        self.config = config
        self.tools = tools if tools is not None else [{"name": "echo"}]
        # Named ``plan_value``, not ``plan``: the attribute would otherwise
        # shadow the ``plan()`` method below.
        self.plan_value = plan if plan is not None else _fake_plan()
        self.result = result if result is not None else _fake_result("completed")
        self.run_error = run_error
        self.plan_error = plan_error
        self.plugin_errors = plugin_errors or []
        self.calls: list[str] = []
        self.closed = 0
        self.progress_callback: Any = None
        self.run_kwargs: dict[str, Any] = {}

    def set_progress(self, callback: Any) -> None:
        """Record the CLI's progress renderer."""
        self.progress_callback = callback

    def list_tools(self) -> list[dict[str, Any]]:
        """Record and return the registry."""
        self.calls.append("list_tools")
        return self.tools

    def plan(self, prompt: str) -> Any:
        """Record and return (or raise) the plan."""
        self.calls.append(f"plan:{prompt}")
        if self.plan_error is not None:
            raise self.plan_error
        return self.plan_value

    def run(self, prompt: str, **kwargs: Any) -> Any:
        """Record and return (or raise) the result."""
        self.calls.append(f"run:{prompt}")
        self.run_kwargs = kwargs
        if self.run_error is not None:
            raise self.run_error
        return self.result

    def close(self) -> None:
        """Record teardown."""
        self.calls.append("close")
        self.closed += 1


def _factory_for(harness: _FakeHarness) -> Any:
    """A harness factory that always returns the same double."""

    def factory(config: Any) -> _FakeHarness:
        harness.config = config
        return harness

    return factory


def _agent_error(message: str = "boom") -> Any:
    """An ``AgentError`` from the doubles."""
    return doubles.AgentError(
        code="TOOL_EXECUTION_FAILED", message=message, component="test"
    )


class TestListToolsDispatch:
    """SPEC-005 § 2 row 6 and SPEC-006 K5."""

    def test_lists_the_registry_and_exits_zero(self, capsys: Any) -> None:
        """The happy path for ``--list-tools``."""
        harness = _FakeHarness(
            None,
            tools=[
                {
                    "name": "echo",
                    "description": "Echoes input.",
                    "capabilities": ["testing"],
                }
            ],
        )

        code = main(["--list-tools"], harness_factory=_factory_for(harness))
        out = capsys.readouterr().out

        assert code == EXIT_OK
        assert "echo" in out
        assert "Echoes input." in out
        assert "testing" in out

    def test_it_needs_no_api_key(self, monkeypatch: Any) -> None:
        """SPEC-006 K5: listing works with no credentials at all."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        harness = _FakeHarness(None)

        assert main(["--list-tools"], harness_factory=_factory_for(harness)) == EXIT_OK

    def test_it_never_runs_a_task(self) -> None:
        """``--list-tools`` must not plan or execute."""
        harness = _FakeHarness(None)

        main(["--list-tools"], harness_factory=_factory_for(harness))

        assert "list_tools" in harness.calls
        assert not any(c.startswith("run:") for c in harness.calls)
        assert not any(c.startswith("plan:") for c in harness.calls)

    def test_plugin_failures_appear_in_a_footer(self, capsys: Any) -> None:
        """SPEC-005 § 3 step 6 — surfaced in the ``--list-tools`` footer."""
        harness = _FakeHarness(None, plugin_errors=[_agent_error("plugin is broken")])

        code = main(["--list-tools"], harness_factory=_factory_for(harness))
        out = capsys.readouterr().out

        assert code == EXIT_OK
        assert "plugin is broken" in out

    def test_an_empty_registry_is_not_an_error(self, capsys: Any) -> None:
        """No tools is a valid state, printed as such."""
        harness = _FakeHarness(None, tools=[])

        code = main(["--list-tools"], harness_factory=_factory_for(harness))
        out = capsys.readouterr().out

        assert code == EXIT_OK
        assert "No tools" in out


class TestDryRunDispatch:
    """SPEC-005 § 2 row 5 — print the plan, do not execute."""

    def test_prints_the_plan_and_exits_zero(self, capsys: Any) -> None:
        """Steps, tools, dependencies and priorities are the spec's list."""
        harness = _FakeHarness(None)

        code = main(["--dry-run", "do things"], harness_factory=_factory_for(harness))
        out = capsys.readouterr().out

        assert code == EXIT_OK
        assert "step1" in out
        assert "Do step 1" in out
        assert "echo" in out

    def test_it_never_executes(self) -> None:
        """The whole point of a dry run."""
        harness = _FakeHarness(None)

        main(["--dry-run", "do things"], harness_factory=_factory_for(harness))

        assert any(c.startswith("plan:") for c in harness.calls)
        assert not any(c.startswith("run:") for c in harness.calls)

    def test_the_prompt_reaches_the_planner(self) -> None:
        """Dispatch passes the task through untouched."""
        harness = _FakeHarness(None)

        main(
            ["--dry-run", "  count the files  "],
            harness_factory=_factory_for(harness),
        )

        assert "plan:  count the files  " in harness.calls

    def test_a_planning_failure_exits_one(self, capsys: Any) -> None:
        """An unhandled ``AgentError`` is exit 1 (SPEC-005 § 2.1)."""
        harness = _FakeHarness(None, plan_error=_agent_error("planner exploded"))

        code = main(["--dry-run", "x"], harness_factory=_factory_for(harness))
        err = capsys.readouterr().err

        assert code == EXIT_FAILED
        assert "planner exploded" in err


class TestRunDispatch:
    """SPEC-005 § 2.1 — status to exit code."""

    def test_completed_exits_zero(self, capsys: Any) -> None:
        """Row 1."""
        harness = _FakeHarness(None, result=_fake_result("completed"))

        code = main(["do things"], harness_factory=_factory_for(harness))
        out = capsys.readouterr().out

        assert code == EXIT_OK
        assert "all done" in out

    def test_partial_exits_three(self) -> None:
        """Row 4 — the code that makes a partial success visible to scripts."""
        harness = _FakeHarness(None, result=_fake_result("partial"))

        code = main(["do things"], harness_factory=_factory_for(harness))

        assert code == EXIT_PARTIAL

    def test_failed_exits_one(self) -> None:
        """Row 2."""
        harness = _FakeHarness(None, result=_fake_result("failed"))

        assert main(["do things"], harness_factory=_factory_for(harness)) == EXIT_FAILED

    def test_the_prompt_is_forwarded_to_run(self) -> None:
        """And the run seam is the documented one."""
        harness = _FakeHarness(None)

        main(["summarise it"], harness_factory=_factory_for(harness))

        assert "run:summarise it" in harness.calls

    def test_an_unhandled_agent_error_exits_one(self, capsys: Any) -> None:
        """Row 2 — an error that escapes ``run()``."""
        harness = _FakeHarness(None, run_error=_agent_error("run exploded"))

        code = main(["x"], harness_factory=_factory_for(harness))
        err = capsys.readouterr().err

        assert code == EXIT_FAILED
        assert "run exploded" in err

    def test_an_interrupt_exits_130(self) -> None:
        """Row 5 — SIGINT is 128 + 2."""
        harness = _FakeHarness(None, run_error=KeyboardInterrupt())

        assert main(["x"], harness_factory=_factory_for(harness)) == EXIT_INTERRUPTED

    def test_a_config_error_exits_one(self, capsys: Any, tmp_path: Any) -> None:
        """A config file the loader cannot parse is an unhandled ``AgentError``.

        The stub-era version of this test relied on the stub refusing to parse *any*
        existing file; the shipped loader parses valid YAML, so the file has to be
        genuinely unreadable to reach the ``CONFIG_LOAD_FAILED`` path (SCR-P4-11).
        """
        config_file = tmp_path / "config.yaml"
        config_file.write_text("llm: [unclosed\n", encoding="utf-8")
        harness = _FakeHarness(None)

        code = main(
            ["--config", str(config_file), "x"], harness_factory=_factory_for(harness)
        )
        err = capsys.readouterr().err

        assert code == EXIT_FAILED
        assert "CONFIG_LOAD_FAILED" in err
        assert not any(c.startswith("run:") for c in harness.calls)


class TestUsageAndTeardown:
    """Exit code 2, and a harness that is always closed."""

    def test_a_usage_error_exits_two(self) -> None:
        """Row 3 — argparse's own code, unchanged."""
        assert main([]) == EXIT_USAGE

    def test_an_unknown_flag_exits_two(self) -> None:
        """Also argparse."""
        assert main(["--wat", "hi"]) == EXIT_USAGE

    def test_the_harness_is_closed_on_success(self) -> None:
        """Teardown runs on the happy path."""
        harness = _FakeHarness(None)

        main(["x"], harness_factory=_factory_for(harness))

        assert harness.closed == 1

    def test_the_harness_is_closed_after_a_failure(self) -> None:
        """And on the unhappy one, so tool cleanup is not skipped."""
        harness = _FakeHarness(None, run_error=_agent_error("nope"))

        main(["x"], harness_factory=_factory_for(harness))

        assert harness.closed == 1

    def test_the_harness_is_closed_after_an_interrupt(self) -> None:
        """Even when the user hits Ctrl-C."""
        harness = _FakeHarness(None, run_error=KeyboardInterrupt())

        main(["x"], harness_factory=_factory_for(harness))

        assert harness.closed == 1

    def test_the_config_reaches_the_factory(self) -> None:
        """CLI overrides are applied before the harness is built."""
        harness = _FakeHarness(None)

        main(["--max-steps", "4", "x"], harness_factory=_factory_for(harness))

        assert harness.config.get("execution.max_steps") == 4

    def test_the_exit_code_constants_match_the_spec(self) -> None:
        """Guard the table itself, not just the behaviour."""
        assert (EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_PARTIAL, EXIT_INTERRUPTED) == (
            0,
            1,
            2,
            3,
            130,
        )


# ---------------------------------------------------------------------------
# Sub-phase 4.2 — process-level exit codes
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Runs the real ``python -m agent_harness`` entry point inside a subprocess against
#: the **composed system** (I1). The exit code is what is asserted, so the run must go
#: through ``main()`` for real; the only injection is a scripted ``MockLLMClient``, so
#: no process here needs credentials or a network.
_SUBPROCESS_SCRIPT = """
import os
import sys
sys.path.insert(0, {tests!r})
sys.path.insert(0, {root!r})

import _p4_doubles as doubles

mode = sys.argv[1]
argv = sys.argv[2:]

from agent_harness import AgentHarness, Config
from agent_harness.__main__ import main

if mode == "module":
    # The real entry point, with the real composition root: used for the keyless
    # ``--list-tools`` and missing-credential cases.
    sys.argv = ["agent_harness", *argv]
    import runpy

    runpy.run_module("agent_harness", run_name="__main__")
else:
    # ``main`` mode: a scripted client, so a *completed* run can be asserted
    # without credentials and without touching the network.
    config = Config()
    config.execution.output_dir = os.path.join(os.environ["HARNESS_SCRATCH"], "out")
    config.execution.temp_dir = os.path.join(os.environ["HARNESS_SCRATCH"], "tmp")
    client = doubles.MockLLMClient(
        [{{"steps": [{{"description": "write the result", "tool_hint": "file_write",
                      "input_data": {{
                          "path": os.path.join(config.execution.output_dir, "out.txt"),
                          "content": "done"}},
                      "priority": "critical"}}]}}]
    )

    def factory(_config):
        return AgentHarness(config, llm_client=client)

    raise SystemExit(main(argv, harness_factory=factory))
"""


def _subprocess_env(scratch: str, **extra: str) -> dict[str, str]:
    """The current environment plus the run's scratch directory and overrides."""
    import os

    env = {**os.environ, "HARNESS_SCRATCH": scratch, **extra}
    env.setdefault("OPENAI_API_KEY", "test-key-not-a-secret")
    return env


def _run_cli_subprocess(mode: str, *argv: str, **env: str) -> Any:
    """Run the CLI in a fresh interpreter and return the completed process."""
    import subprocess
    import tempfile

    script = _SUBPROCESS_SCRIPT.format(
        tests=str(REPO_ROOT / "tests"), root=str(REPO_ROOT)
    )
    scratch = tempfile.mkdtemp(prefix="agent-harness-cli-")
    return subprocess.run(
        [sys.executable, "-c", script, mode, *argv],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=str(REPO_ROOT),
        env=_subprocess_env(scratch, **env),
    )


class TestProcessLevelExitCodes:
    """SPEC-005 § 2.1, asserted on real process exit statuses."""

    def test_help_exits_zero_in_a_subprocess(self) -> None:
        """``python -m agent_harness --help`` is the documented entry point."""
        proc = _run_cli_subprocess("module", "--help")

        assert proc.returncode == 0
        assert "python -m agent_harness" in proc.stdout

    def test_a_usage_error_exits_two_in_a_subprocess(self) -> None:
        """No prompt and no ``--list-tools``."""
        proc = _run_cli_subprocess("module")

        assert proc.returncode == EXIT_USAGE
        assert "prompt is required" in proc.stderr

    def test_an_invalid_max_steps_exits_two_in_a_subprocess(self) -> None:
        """Validation happens before anything is imported from Plan 1-3."""
        proc = _run_cli_subprocess("module", "--max-steps", "0", "hi")

        assert proc.returncode == EXIT_USAGE

    def test_list_tools_exits_zero_in_a_subprocess(self) -> None:
        """A full run of the dispatch path, in a real process."""
        proc = _run_cli_subprocess("module", "--list-tools")

        assert proc.returncode == EXIT_OK
        assert "web_search" in proc.stdout

    def test_a_completed_run_exits_zero_in_a_subprocess(self) -> None:
        """End to end through ``main()`` with a scripted client (I1: real harness)."""
        proc = _run_cli_subprocess("main", "do something")

        assert proc.returncode == EXIT_OK
        assert "Status: completed" in proc.stdout

    def test_no_api_key_is_needed_for_list_tools_in_a_subprocess(self) -> None:
        """SPEC-006 K5, at process level, against the real composition root."""
        proc = _run_cli_subprocess("module", "--list-tools", OPENAI_API_KEY="")

        assert proc.returncode == EXIT_OK

    def test_a_missing_api_key_makes_a_run_exit_one(self) -> None:
        """The companion case: a real run *does* need credentials."""
        proc = _run_cli_subprocess("module", "do something", OPENAI_API_KEY="")

        assert proc.returncode == EXIT_FAILED
        assert "OPENAI_API_KEY" in proc.stderr


# ---------------------------------------------------------------------------
# Sub-phase 4.3 — Rich rendering and graceful degradation
# ---------------------------------------------------------------------------

import re  # noqa: E402

from agent_harness.__main__ import (  # noqa: E402
    _render_plan,
    _render_result,
    _render_tools,
    use_rich,
)

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class _FakeTTY:
    """A stream that claims to be a terminal."""

    def isatty(self) -> bool:
        """Pretend to be attached to a terminal."""
        return True


class _FakePipe:
    """A stream that is not a terminal."""

    def isatty(self) -> bool:
        """Pretend to be redirected."""
        return False


@pytest.fixture(name="clean_env")
def _clean_env(monkeypatch: Any) -> Any:
    """Remove every setting that forces plain text."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("TERM", raising=False)
    return monkeypatch


@pytest.mark.usefixtures("clean_env")
class TestConsoleMode:
    """SPEC-005 § 2.2 — Rich when available, plain otherwise."""

    def test_a_tty_with_no_overrides_uses_rich(self) -> None:
        """The default interactive case."""
        assert use_rich(_FakeTTY()) is True

    def test_a_pipe_does_not(self) -> None:
        """Redirected output must stay greppable."""
        assert use_rich(_FakePipe()) is False

    def test_no_color_forces_plain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The NO_COLOR convention is honoured."""
        monkeypatch.setenv("NO_COLOR", "1")

        assert use_rich(_FakeTTY()) is False

    def test_an_empty_no_color_does_not_force_plain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``NO_COLOR=`` means unset, per the convention."""
        monkeypatch.setenv("NO_COLOR", "")

        assert use_rich(_FakeTTY()) is True

    def test_term_dumb_forces_plain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The other documented override."""
        monkeypatch.setenv("TERM", "dumb")

        assert use_rich(_FakeTTY()) is False

    def test_another_term_value_keeps_rich(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only ``dumb`` is special."""
        monkeypatch.setenv("TERM", "xterm-256color")

        assert use_rich(_FakeTTY()) is True

    def test_rich_being_uninstalled_forces_plain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing optional dependency degrades instead of crashing.

        ``importlib.import_module`` is what :func:`use_rich` calls, and it does
        not go through ``builtins.__import__``, so that is what gets blocked.
        """
        real_import_module = importlib.import_module

        def blocked(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "rich" or name.startswith("rich."):
                raise ImportError("rich is not installed")
            return real_import_module(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", blocked)

        assert use_rich(_FakeTTY()) is False


#: A two-row registry, used by both the plain and the styled rendering tests.
SAMPLE_TOOLS: list[dict[str, Any]] = [
    {"name": "echo", "description": "Echoes input.", "capabilities": ["testing"]},
    {"name": "web_search", "description": "Searches.", "capabilities": ["web"]},
]


@pytest.mark.usefixtures("clean_env")
class TestPlainRendering:
    """Piped output carries no escape codes, ever."""

    def test_the_tools_table_is_plain(self) -> None:
        """No ANSI in the plain renderer."""
        assert ANSI.search(_render_tools(SAMPLE_TOOLS)) is None

    def test_the_plan_table_is_plain(self) -> None:
        """Nor in the plan renderer."""
        assert ANSI.search(_render_plan(_fake_plan())) is None

    def test_the_result_is_plain(self) -> None:
        """Nor in the result renderer."""
        assert ANSI.search(_render_result(_fake_result("completed"))) is None

    def test_piped_list_tools_output_has_no_escape_codes(self, capsys: Any) -> None:
        """The whole dispatch path, captured as a pipe would see it."""
        harness = _FakeHarness(None, tools=SAMPLE_TOOLS)

        main(["--list-tools"], harness_factory=_factory_for(harness))

        assert ANSI.search(capsys.readouterr().out) is None

    def test_piped_dry_run_output_has_no_escape_codes(self, capsys: Any) -> None:
        """Capsys is not a TTY, so this is the piped case."""
        harness = _FakeHarness(None)

        main(["--dry-run", "x"], harness_factory=_factory_for(harness))

        assert ANSI.search(capsys.readouterr().out) is None


@pytest.mark.usefixtures("clean_env")
class TestRichRendering:
    """Interactive output is styled."""

    def test_the_tools_table_is_styled(self) -> None:
        """Rich mode emits escape codes."""
        text = _render_tools(SAMPLE_TOOLS, rich=True)

        assert ANSI.search(text) is not None
        assert "echo" in text

    def test_the_plan_table_is_styled(self) -> None:
        """And shows every column the spec lists."""
        text = _render_plan(_fake_plan(), rich=True)

        assert ANSI.search(text) is not None
        for token in ("step1", "Do step 1", "echo", "HIGH", "PRIORITY", "DEPENDS"):
            assert token in text

    def test_the_result_is_styled(self) -> None:
        """The final report keeps its content under styling."""
        text = _render_result(_fake_result("completed"), rich=True)

        assert ANSI.search(text) is not None
        assert "all done" in text

    def test_plain_and_rich_carry_the_same_content(self) -> None:
        """Styling must not drop information."""
        plain = ANSI.sub("", _render_plan(_fake_plan(), rich=True))
        bare = _render_plan(_fake_plan())

        for token in ("step1", "step2", "Do step 1", "echo"):
            assert token in plain
            assert token in bare


class TestLiveProgress:
    """SPEC-005 § 2.2 — live step progress through the Phase 2.3 hook seam."""

    def test_the_harness_is_given_a_progress_callback(self) -> None:
        """The CLI wires the renderer onto the harness's ``progress`` seam."""
        harness = _FakeHarness(None)

        main(["x"], harness_factory=_factory_for(harness))

        assert harness.progress_callback is not None

    def test_step_events_are_printed(self, capsys: Any) -> None:
        """A step start and completion both reach the console."""
        harness = _FakeHarness(None)

        main(["x"], harness_factory=_factory_for(harness))
        harness.progress_callback({"event": "step_start", "step_id": "s1"})
        harness.progress_callback({"event": "step_complete", "step_id": "s1"})
        err = capsys.readouterr().err

        assert "s1" in err

    def test_a_failure_event_is_printed(self, capsys: Any) -> None:
        """Failures are the events a user most needs to see live."""
        harness = _FakeHarness(None)

        main(["x"], harness_factory=_factory_for(harness))
        harness.progress_callback(
            {"event": "step_failed", "step_id": "s2", "error": "tool exploded"}
        )
        err = capsys.readouterr().err

        assert "s2" in err
        assert "tool exploded" in err

    def test_an_unknown_event_is_ignored(self, capsys: Any) -> None:
        """Forward compatibility: new events must not crash the console."""
        harness = _FakeHarness(None)

        main(["x"], harness_factory=_factory_for(harness))
        harness.progress_callback({"event": "something_new", "detail": 1})

        assert capsys.readouterr().err == ""

    def test_a_broken_stream_does_not_break_the_run(self, monkeypatch: Any) -> None:
        """SPEC-003 § 2.1 — progress delivery is best effort."""
        harness = _FakeHarness(None)

        class ExplodingStream:
            def write(self, text: str) -> int:
                """Refuse to render anything, however long the line is."""
                raise OSError(f"console is gone, refused {len(text)} chars")

            def flush(self) -> None:
                """Nothing to flush."""

        monkeypatch.setattr(sys, "stderr", ExplodingStream())

        code = main(["x"], harness_factory=_factory_for(harness))
        harness.progress_callback({"event": "step_start", "step_id": "s1"})

        assert code == EXIT_OK

    def test_progress_is_quiet_for_list_tools(self) -> None:
        """No run means no progress."""
        harness = _FakeHarness(None)

        main(["--list-tools"], harness_factory=_factory_for(harness))

        assert harness.progress_callback is None


class TestStyledDispatch:
    """The interactive path through ``main()`` itself.

    ``use_rich`` is monkeypatched rather than ``sys.stdout``: pytest replaces
    ``sys.stdout`` with its own capture object *after* fixtures run, so patching
    it in a fixture does not reach the test body. Patching the decision point
    tests the part that matters here — that ``main`` passes the styling decision
    down to the renderers — while ``TestConsoleMode`` covers the detection
    itself and ``TestPlainRendering`` covers the default piped path.
    """

    @pytest.fixture(name="styled", autouse=True)
    def _styled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Force the styled branch on."""
        monkeypatch.setattr(cli_module, "use_rich", lambda _stream=None: True)

    def test_list_tools_is_styled(self, capsys: Any) -> None:
        """``main()`` picks the rich renderer when the decision is yes."""
        harness = _FakeHarness(None, tools=SAMPLE_TOOLS)

        code = main(["--list-tools"], harness_factory=_factory_for(harness))
        out = capsys.readouterr().out

        assert code == EXIT_OK
        assert ANSI.search(out) is not None
        assert "echo" in ANSI.sub("", out)

    def test_dry_run_is_styled(self, capsys: Any) -> None:
        """Same for the plan table."""
        harness = _FakeHarness(None)

        code = main(["--dry-run", "x"], harness_factory=_factory_for(harness))
        out = capsys.readouterr().out

        assert code == EXIT_OK
        assert ANSI.search(out) is not None

    def test_a_run_is_styled(self, capsys: Any) -> None:
        """And for the final result panel."""
        harness = _FakeHarness(None)

        code = main(["x"], harness_factory=_factory_for(harness))
        out = capsys.readouterr().out

        assert code == EXIT_OK
        assert ANSI.search(out) is not None
        assert "all done" in ANSI.sub("", out)

    def test_styling_never_drops_content(self, capsys: Any) -> None:
        """Every row survives the styling."""
        harness = _FakeHarness(None, tools=SAMPLE_TOOLS)

        main(["--list-tools"], harness_factory=_factory_for(harness))
        out = ANSI.sub("", capsys.readouterr().out)

        for token in ("echo", "web_search", "Echoes input.", "Searches."):
            assert token in out


# ---------------------------------------------------------------------------
# Sub-phase 4.4 — behaviour flags, end to end
# ---------------------------------------------------------------------------


class _FallbackPlanner(doubles.Planner):
    """Plans one step that carries a fallback tool."""

    def plan(
        self,
        prompt: str,
        available_tools: list[dict[str, Any]],
        *,
        context: dict[str, Any] | None = None,
    ) -> doubles.ExecutionPlan:
        """Return a single-step plan asking for a fallback."""
        return doubles.ExecutionPlan(
            original_prompt=prompt,
            context={"available_tools": available_tools, "planner_context": context},
            steps=[
                doubles.Step(
                    id="s1",
                    description="first",
                    tool_name="echo",
                    fallback_tools=["echo_backup", "shell_command"],
                )
            ],
        )


class _CapturingOrchestrator(doubles.Orchestrator):
    """Records the plan it was handed."""

    def __init__(self) -> None:
        """Start empty."""
        super().__init__(doubles.ToolRegistry(), doubles.Config())
        self.seen: doubles.ExecutionPlan | None = None

    def execute(self, plan: doubles.ExecutionPlan) -> doubles.ExecutionPlan:
        """Record the plan and mark it successful."""
        self.seen = plan
        for step in plan.steps:
            step.status = doubles.StepStatus.SUCCESS
        plan.status = doubles.StepStatus.SUCCESS
        return plan


def _real_harness_factory(
    orchestrator: _CapturingOrchestrator,
) -> Any:
    """A factory building a real harness around the capturing orchestrator."""
    from agent_harness.harness import AgentHarness

    def factory(config: Any) -> Any:
        return AgentHarness(
            config,
            llm_client=doubles.MockLLMClient(),
            planner=_FallbackPlanner(doubles.MockLLMClient(), config),
            orchestrator=orchestrator,
        )

    return factory


class TestNoFallbackFlag:
    """SPEC-005 § 2 row 9 — the flag, followed all the way to the plan."""

    def test_no_fallback_strips_the_fallback_lists(self) -> None:
        """CLI flag to config to plan, with a real harness in between."""
        orchestrator = _CapturingOrchestrator()

        code = main(
            ["--no-fallback", "do things"],
            harness_factory=_real_harness_factory(orchestrator),
        )

        assert code == EXIT_OK
        assert orchestrator.seen is not None
        assert orchestrator.seen.steps[0].fallback_tools == []

    def test_without_the_flag_the_fallback_lists_stay(self) -> None:
        """The default leaves Level 2 recovery available."""
        orchestrator = _CapturingOrchestrator()

        code = main(["do things"], harness_factory=_real_harness_factory(orchestrator))

        assert code == EXIT_OK
        assert orchestrator.seen is not None
        assert orchestrator.seen.steps[0].fallback_tools == [
            "echo_backup",
            "shell_command",
        ]

    def test_no_fallback_also_disables_replan_in_the_config(self) -> None:
        """The other half of the flag, which turns off Level 3."""
        harness = _FakeHarness(None)

        main(["--no-fallback", "x"], harness_factory=_factory_for(harness))

        assert harness.config.get("execution.enable_replan") is False


class TestLogLevelChain:
    """SPEC-006 § 1.2 — CLI over environment over file, end to end."""

    def test_the_flag_reaches_the_harness_config(self) -> None:
        """Highest precedence."""
        harness = _FakeHarness(None)

        main(["--log-level", "ERROR", "x"], harness_factory=_factory_for(harness))

        assert harness.config.get("logging.level") == "ERROR"

    def test_the_environment_reaches_the_harness_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Middle precedence, when no flag is given."""
        monkeypatch.setenv("AGENT_HARNESS_LOG_LEVEL", "WARNING")
        harness = _FakeHarness(None)

        main(["x"], harness_factory=_factory_for(harness))

        assert harness.config.get("logging.level") == "WARNING"

    def test_the_default_is_left_alone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Lowest precedence: whatever the file or the defaults say."""
        monkeypatch.delenv("AGENT_HARNESS_LOG_LEVEL", raising=False)
        harness = _FakeHarness(None)

        main(["x"], harness_factory=_factory_for(harness))

        assert harness.config.get("logging.level") == "INFO"

    def test_max_steps_reaches_the_harness_config(self) -> None:
        """The last guard flag, checked at the same boundary."""
        harness = _FakeHarness(None)

        main(["--max-steps", "2", "x"], harness_factory=_factory_for(harness))

        assert harness.config.get("execution.max_steps") == 2


# ---------------------------------------------------------------------------
# Sub-phase 4.5 — CLI smoke suite
# ---------------------------------------------------------------------------


class _SmokePlanner(doubles.Planner):
    """Plans a fixed two-step task against the ``echo`` tool."""

    def __init__(self, llm_client: Any, config: Any, **kwargs: Any) -> None:
        """Store collaborators and start the record of what was planned."""
        super().__init__(llm_client, config, **kwargs)
        self.seen_tools: list[dict[str, Any]] = []
        self.seen_prompt = ""

    def plan(
        self,
        prompt: str,
        available_tools: list[dict[str, Any]],
        *,
        context: dict[str, Any] | None = None,
    ) -> doubles.ExecutionPlan:
        """Return a deterministic plan; the tools list is recorded, not needed."""
        self.seen_tools = available_tools
        self.seen_prompt = prompt
        return doubles.ExecutionPlan(
            original_prompt=prompt,
            context={"planner_context": context},
            steps=[
                doubles.Step(id="s1", description="Gather input", tool_name="echo"),
                doubles.Step(
                    id="s2",
                    description="Write the report",
                    tool_name="echo",
                    depends_on=["s1"],
                ),
            ],
        )


class _SmokeOrchestrator(doubles.Orchestrator):
    """Executes the plan to a chosen outcome."""

    def __init__(self, outcome: str = "completed") -> None:
        """Store the outcome to simulate."""
        super().__init__(doubles.ToolRegistry(), doubles.Config())
        self._outcome = outcome

    def execute(self, plan: doubles.ExecutionPlan) -> doubles.ExecutionPlan:
        """Mark the steps so the assembler derives the intended status.

        ``failed`` must fail *every* step: the stub assembler calls a run
        partial as soon as one step succeeds, so a single surviving success
        turns this scenario into exit 3 instead of 1.
        """
        if self._outcome == "interrupt":
            raise KeyboardInterrupt
        for index, step in enumerate(plan.steps):
            succeeded = self._outcome == "completed" or (
                self._outcome == "partial" and index == 0
            )
            if succeeded:
                step.status = doubles.StepStatus.SUCCESS
                step.output_data = f"{step.description}: done"
            else:
                step.status = doubles.StepStatus.FAILED
                step.error = "tool returned an error"
        plan.status = (
            doubles.StepStatus.SUCCESS
            if self._outcome == "completed"
            else doubles.StepStatus.FAILED
        )
        return plan


def _smoke_factory(outcome: str = "completed") -> Any:
    """A factory building a real harness that ends in ``outcome``."""
    from agent_harness.harness import AgentHarness

    def factory(config: Any) -> Any:
        return AgentHarness(
            config,
            llm_client=doubles.MockLLMClient(),
            planner=_SmokePlanner(doubles.MockLLMClient(), config),
            orchestrator=_SmokeOrchestrator(outcome),
        )

    return factory


class TestCliSmoke:
    """Every documented command, through ``main()``, against a real harness."""

    def test_list_tools(self, capsys: Any) -> None:
        """Exit 0, registry table, no escape codes in piped output."""
        code = main(["--list-tools"], harness_factory=_smoke_factory())
        out = capsys.readouterr().out

        assert code == EXIT_OK
        assert out.startswith("Tools (")
        assert "echo" in out
        assert ANSI.search(out) is None

    def test_dry_run(self, capsys: Any) -> None:
        """Exit 0, plan table with the spec's five columns."""
        code = main(["--dry-run", "Write a report"], harness_factory=_smoke_factory())
        out = capsys.readouterr().out

        assert code == EXIT_OK
        assert out.startswith("Plan (2 steps)")
        for token in ("ID", "TOOL", "PRIORITY", "DEPENDS ON", "DESCRIPTION"):
            assert token in out
        assert "s1" in out and "s2" in out
        assert "Gather input" in out
        assert ANSI.search(out) is None

    def test_dry_run_shows_the_dependency(self, capsys: Any) -> None:
        """The dependency edge is rendered, not dropped."""
        main(["--dry-run", "x"], harness_factory=_smoke_factory())
        out = capsys.readouterr().out
        line = next(line for line in out.splitlines() if line.strip().startswith("s2"))

        assert "s1" in line

    def test_successful_run(self, capsys: Any) -> None:
        """Exit 0, the deliverable, and a status line."""
        code = main(["Write a report"], harness_factory=_smoke_factory("completed"))
        out = capsys.readouterr().out

        assert code == EXIT_OK
        assert "Gather input: done" in out
        assert "Status: completed" in out

    def test_partial_run(self, capsys: Any) -> None:
        """Exit 3 - the code that tells a script the job half worked."""
        code = main(["Write a report"], harness_factory=_smoke_factory("partial"))
        out = capsys.readouterr().out

        assert code == EXIT_PARTIAL
        assert "Status: partial" in out

    def test_failed_run(self, capsys: Any) -> None:
        """Exit 1."""
        code = main(["Write a report"], harness_factory=_smoke_factory("failed"))
        out = capsys.readouterr().out

        assert code == EXIT_FAILED
        assert "Status: failed" in out

    def test_interrupt(self, capsys: Any) -> None:
        """Exit 130, with a note on stderr."""
        code = main(["Write a report"], harness_factory=_smoke_factory("interrupt"))
        captured = capsys.readouterr()

        assert code == EXIT_INTERRUPTED
        assert "Interrupted" in captured.err

    def test_the_prompt_can_come_from_stdin(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``-`` reads the task, and it reaches the planner."""
        import io

        monkeypatch.setattr(sys, "stdin", io.StringIO("Write a report from stdin\n"))
        seen: dict[str, Any] = {}

        def factory(config: Any) -> Any:
            from agent_harness.harness import AgentHarness

            planner = _SmokePlanner(doubles.MockLLMClient(), config)
            seen["planner"] = planner
            return AgentHarness(
                config,
                llm_client=doubles.MockLLMClient(),
                planner=planner,
                orchestrator=_SmokeOrchestrator("completed"),
            )

        code = main(["-"], harness_factory=factory)

        assert code == EXIT_OK
        assert seen["planner"].seen_prompt == "Write a report from stdin"

    def test_a_broken_plugin_is_reported_in_the_footer(
        self, capsys: Any, tmp_path: Any
    ) -> None:
        """The whole discovery path, through the real harness."""
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        (plugin_dir / "broken.py").write_text(
            "class Broken(BaseTool:\n    pass\n", encoding="utf-8"
        )
        config = doubles.Config()
        config.plugins.dirs = [str(plugin_dir)]
        config_file = tmp_path / "config.yaml"
        config_file.write_text("logging:\n  level: INFO\n", encoding="utf-8")

        def factory(cfg: Any) -> Any:
            from agent_harness.harness import AgentHarness

            return AgentHarness(
                cfg,
                llm_client=doubles.MockLLMClient(),
                planner=_SmokePlanner(doubles.MockLLMClient(), cfg),
                orchestrator=_SmokeOrchestrator("completed"),
            )

        code = main(
            ["--config", str(config_file), "--list-tools"],
            harness_factory=_factory_with_config(factory, config),
        )
        out = capsys.readouterr().out

        assert code == EXIT_OK
        assert "failed to load" in out
        assert "broken.py" in out

    def test_output_is_deterministic(self, capsys: Any) -> None:
        """Two identical invocations produce identical stdout."""
        main(["--dry-run", "x"], harness_factory=_smoke_factory())
        first = capsys.readouterr().out
        main(["--dry-run", "x"], harness_factory=_smoke_factory())
        second = capsys.readouterr().out

        assert first == second


def _factory_with_config(inner: Any, config: Any) -> Any:
    """Wrap a factory so it receives a specific config regardless of the flag."""

    def factory(_config: Any) -> Any:
        return inner(config)

    return factory


class TestNoNetwork:
    """The suite must not touch the network, ever."""

    def test_no_socket_is_opened_during_a_full_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Opening a socket fails the test instead of making a call."""
        import socket

        def refused(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("the CLI smoke suite must not use the network")

        monkeypatch.setattr(socket, "socket", refused)
        monkeypatch.setattr(socket, "create_connection", refused)

        assert main(["--list-tools"], harness_factory=_smoke_factory()) == EXIT_OK
        assert main(["--dry-run", "x"], harness_factory=_smoke_factory()) == EXIT_OK
        assert main(["x"], harness_factory=_smoke_factory()) == EXIT_OK
