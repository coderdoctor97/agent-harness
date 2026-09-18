"""Unit tests for the Plan 4 public API surface.

Owned by Plan 4 (SPEC-000 § 3.4). Deterministic: no network, no live LLM calls, no
wall-clock dependence (SPEC-000 § 5.2/§ 5.5). Plans 1-3 modules are supplied as
the real Plan 1-3 modules, with collaborator doubles from ``tests/_p4_doubles.py``.

Spec: SPEC-005 § 1 · SPEC-001 § 2 · SPEC-000 § 5
"""

from __future__ import annotations

import dataclasses
import importlib.metadata
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import _p4_doubles as doubles
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

OPTIONAL_DEPENDENCIES = (
    "rich",
    "openai",
    "anthropic",
    "yaml",
    "dotenv",
    "requests",
    "bs4",
    "pdfkit",
    "duckduckgo_search",
)


@pytest.fixture(autouse=True)
def _fake_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every test an obviously-fake key; tests may delete it to go keyless."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-a-secret")


# ---------------------------------------------------------------------------
# Sub-phase 1.1 — package exports
# ---------------------------------------------------------------------------


class TestPackageExports:
    """SPEC-005 § 1 — the frozen public surface."""

    def test_all_matches_spec_verbatim(self) -> None:
        """``__all__`` is exactly the four names the FROZEN spec lists, in order."""
        import agent_harness

        assert agent_harness.__all__ == [
            "AgentHarness",
            "Config",
            "HarnessResult",
            "__version__",
        ]

    def test_all_has_no_extra_names(self) -> None:
        """No undeclared names leak into the surface (SPEC-000 § 2 L3 minimalism)."""
        import agent_harness

        assert len(agent_harness.__all__) == 4
        assert len(set(agent_harness.__all__)) == 4

    def test_version_is_a_non_empty_semver_string(self) -> None:
        """``__version__`` is present and shaped like a version number."""
        import agent_harness

        assert isinstance(agent_harness.__version__, str)
        assert agent_harness.__version__
        assert re.fullmatch(r"\d+\.\d+\.\d+(?:[.-].+)?", agent_harness.__version__)


class TestVersionResolution:
    """Sub-phase 1.1 exit criterion: ``__version__`` sourced from package metadata."""

    def test_prefers_installed_package_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the distribution is installed, metadata wins over the fallback."""
        import agent_harness

        monkeypatch.setattr(importlib.metadata, "version", lambda _name: "9.9.9")
        assert agent_harness._resolve_version() == "9.9.9"

    def test_falls_back_when_distribution_is_not_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without installed metadata the documented fallback version is used."""
        import agent_harness

        def _missing(_name: str) -> str:
            raise importlib.metadata.PackageNotFoundError(_name)

        monkeypatch.setattr(importlib.metadata, "version", _missing)
        assert agent_harness._resolve_version() == agent_harness._FALLBACK_VERSION

    def test_fallback_matches_the_documented_release(self) -> None:
        """The fallback is the v0.1.0 release named in the Developer README."""
        import agent_harness

        assert agent_harness._FALLBACK_VERSION == "0.1.0"


class TestImportIsLazy:
    """Sub-phase 1.1: ``import agent_harness`` never fails on optional deps."""

    def test_package_imports_with_every_optional_dependency_blocked(self) -> None:
        """Importing in a child process with optional deps unimportable must succeed."""
        script = (
            "import sys, importlib.abc\n"
            f"BLOCK = {set(OPTIONAL_DEPENDENCIES)!r}\n"
            "class Blocker(importlib.abc.MetaPathFinder):\n"
            "    def find_spec(self, fullname, path=None, target=None):\n"
            "        if fullname.split('.')[0] in BLOCK:\n"
            "            raise ImportError('blocked optional dep: ' + fullname)\n"
            "        return None\n"
            "sys.meta_path.insert(0, Blocker())\n"
            "import agent_harness\n"
            "print(','.join(agent_harness.__all__))\n"
            "print(agent_harness.__version__)\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert completed.returncode == 0, completed.stderr
        stdout_lines = completed.stdout.strip().splitlines()
        assert stdout_lines[0] == "AgentHarness,Config,HarnessResult,__version__"
        assert stdout_lines[1]


# ---------------------------------------------------------------------------
# Sub-phase 1.1 — HarnessResult
# ---------------------------------------------------------------------------


class TestHarnessResult:
    """SPEC-005 § 1 — the ``HarnessResult`` dataclass."""

    def test_is_a_dataclass(self) -> None:
        """``HarnessResult`` is a dataclass, as the spec declares it."""
        from agent_harness.harness import HarnessResult

        assert dataclasses.is_dataclass(HarnessResult)

    def test_field_names_and_order_match_spec_verbatim(self) -> None:
        """Field names and their order are exactly as FROZEN in SPEC-005 § 1."""
        from agent_harness.harness import HarnessResult

        assert [f.name for f in dataclasses.fields(HarnessResult)] == [
            "status",
            "final_output",
            "plan",
            "metrics",
            "files_created",
            "errors",
        ]

    def test_carries_the_values_it_is_given(self) -> None:
        """Every field round-trips without coercion."""
        from agent_harness.harness import HarnessResult

        plan = doubles.ExecutionPlan(id="plan-1", original_prompt="do a thing")
        metrics = doubles.ExecutionMetrics(
            plan_id="plan-1",
            prompt_length=9,
            total_steps=2,
            successful_steps=2,
            failed_steps=0,
            recovered_steps=0,
            skipped_steps=0,
            total_retries=0,
            total_duration_ms=12,
            llm_calls=1,
            llm_tokens_used=15,
            llm_estimated_cost=0.001,
            tools_used=["web_search"],
            files_created=["output/a.md"],
            errors=[],
        )
        result = HarnessResult(
            status="completed",
            final_output="all done",
            plan=plan,
            metrics=metrics,
            files_created=["output/a.md"],
            errors=[],
        )

        assert result.status == "completed"
        assert result.final_output == "all done"
        assert result.plan is plan
        assert result.metrics is metrics
        assert result.files_created == ["output/a.md"]
        assert result.errors == []

    def test_errors_hold_agent_error_dicts(self) -> None:
        """``errors`` mirrors ``context['errors']`` — plain JSON-safe dicts."""
        from agent_harness.harness import HarnessResult

        error = doubles.AgentError(
            code="TOOL_EXECUTION_FAILED",
            message="boom",
            component="tools",
            step_id="step_0",
        )
        result = HarnessResult(
            status="failed",
            final_output=None,
            plan=doubles.ExecutionPlan(),
            metrics=doubles.ExecutionMetrics(
                plan_id="p",
                prompt_length=0,
                total_steps=1,
                successful_steps=0,
                failed_steps=1,
                recovered_steps=0,
                skipped_steps=0,
                total_retries=0,
                total_duration_ms=0,
                llm_calls=0,
                llm_tokens_used=0,
                llm_estimated_cost=0.0,
                tools_used=[],
                files_created=[],
                errors=[error.to_dict()],
            ),
            files_created=[],
            errors=[error.to_dict()],
        )

        assert result.errors[0]["code"] == "TOOL_EXECUTION_FAILED"
        assert result.errors[0]["step_id"] == "step_0"


# ---------------------------------------------------------------------------
# Integration-window sanity — the swap has happened (I1)
# ---------------------------------------------------------------------------


class TestRealModuleSeam:
    """After I1 the composition root composes the real Plan 1-3 modules.

    The stub-era assertions this class replaces (SCR-P4-11) compared *identity*
    with ``tests/_p4_stubs.py`` objects, which can only hold while the real modules
    are unimportable. These assertions pin the post-swap truth instead: every name
    Plan 4 resolves is the shipped class, and no fabricating module is loaded.
    """

    def test_every_resolved_name_is_the_shipped_object(self) -> None:
        """Plan 4's doubles are the real classes, not stand-ins (SPEC-000 § 2)."""
        import agent_harness.config as config_module
        import agent_harness.orchestration as orchestration_module
        import agent_harness.planning as planning_module
        import agent_harness.tools as tools_module

        assert tools_module.BaseTool is doubles.BaseTool
        assert tools_module.ToolRegistry is doubles.ToolRegistry
        assert config_module.Config is doubles.Config
        assert config_module.AgentError is doubles.AgentError
        assert planning_module.Planner is doubles.Planner
        assert orchestration_module.Orchestrator is doubles.Orchestrator
        assert orchestration_module.Assembler is doubles.Assembler

    def test_the_pristine_stand_ins_are_gone(self) -> None:
        """No test-only module fabricates ``agent_harness.*`` names any more."""
        assert not hasattr(doubles, "stub_modules")
        assert "_p4_stubs" not in sys.modules


# ---------------------------------------------------------------------------
# Sub-phase 1.2 — AgentHarness skeleton
# ---------------------------------------------------------------------------


class TestHarnessConstruction:
    """SPEC-005 § 1 — constructor and ``from_config``."""

    def test_accepts_a_config(self) -> None:
        """The documented single-argument constructor works."""
        from agent_harness import AgentHarness

        harness = AgentHarness(doubles.Config())
        assert harness.config is not None

    def test_from_config_returns_a_harness(self, tmp_path: Path) -> None:
        """``from_config(path)`` is a classmethod producing the same type.

        Post-I1 this reads a real YAML file through Plan 1's loader, so the file has
        to exist; the stub-era version of this test passed a missing path, which the
        shipped loader correctly rejects with ``CONFIG_LOAD_FAILED`` (SCR-P4-11).
        """
        from agent_harness import AgentHarness

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "execution:\n"
            f"  output_dir: {tmp_path / 'out'}\n"
            f"  temp_dir: {tmp_path / 'tmp'}\n"
            "logging:\n"
            "  level: WARNING\n",
            encoding="utf-8",
        )

        harness = AgentHarness.from_config(str(config_file))

        assert isinstance(harness, AgentHarness)
        assert harness.config.execution.output_dir == str(tmp_path / "out")
        assert harness.config.logging.level == "WARNING"

    def test_from_config_rejects_a_missing_path(self, tmp_path: Path) -> None:
        """An *explicit* path that does not exist is a load error, not defaults."""
        from agent_harness import AgentHarness

        with pytest.raises(doubles.AgentError) as excinfo:
            AgentHarness.from_config(str(tmp_path / "missing.yaml"))

        assert excinfo.value.code == "CONFIG_LOAD_FAILED"

    def test_from_config_default_path_is_the_documented_one(self) -> None:
        """SPEC-005 § 1: the default is ``./config.yaml``."""
        import inspect

        from agent_harness import AgentHarness

        signature = inspect.signature(AgentHarness.from_config)
        assert signature.parameters["path"].default == "./config.yaml"

    def test_init_does_not_require_an_api_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SPEC-006 K5 — construction must succeed with no credentials present."""
        from agent_harness import AgentHarness

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        config = doubles.Config()
        config.execution.output_dir = str(tmp_path / "out")
        config.execution.temp_dir = str(tmp_path / "tmp")
        AgentHarness(config)  # must not raise


class TestOutputDirectories:
    """SPEC-005 § 1.2 — output/temp directory management at init."""

    def test_creates_missing_output_and_temp_dirs(self, tmp_path: Path) -> None:
        """Both directories are created when absent."""
        from agent_harness import AgentHarness

        out, tmp = tmp_path / "nested" / "out", tmp_path / "nested" / "tmp"
        config = doubles.Config()
        config.execution.output_dir = str(out)
        config.execution.temp_dir = str(tmp)
        AgentHarness(config)
        assert out.is_dir()
        assert tmp.is_dir()

    def test_leaves_existing_dirs_alone(self, tmp_path: Path) -> None:
        """Pre-existing directories are not disturbed."""
        from agent_harness import AgentHarness

        out = tmp_path / "out"
        out.mkdir()
        marker = out / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        config = doubles.Config()
        config.execution.output_dir = str(out)
        config.execution.temp_dir = str(tmp_path / "tmp")
        AgentHarness(config)
        assert marker.read_text(encoding="utf-8") == "keep"


class TestInjectionSeams:
    """Sub-phase 1.2 — the five documented test seams are honoured end-to-end."""

    SEAMS = ("llm_client", "planner", "orchestrator", "assembler", "registry")

    def _config(self, tmp_path: Path) -> Any:
        config = doubles.Config()
        config.execution.output_dir = str(tmp_path / "out")
        config.execution.temp_dir = str(tmp_path / "tmp")
        return config

    @pytest.mark.parametrize("seam", SEAMS)
    def test_injected_seam_is_retained_by_identity(
        self, tmp_path: Path, seam: str
    ) -> None:
        """Each seam, when injected, is the very object the harness holds."""
        from agent_harness import AgentHarness

        sentinel = object()
        harness = AgentHarness(self._config(tmp_path), **{seam: sentinel})
        assert getattr(harness, f"_{seam}") is sentinel

    def test_no_seam_is_constructed_eagerly(self, tmp_path: Path) -> None:
        """Nothing is built at init, so a keyless construction cannot fail."""
        from agent_harness import AgentHarness

        harness = AgentHarness(self._config(tmp_path))
        for seam in self.SEAMS:
            assert getattr(harness, f"_{seam}") is None

    def test_injected_llm_client_short_circuits_the_factory(
        self, tmp_path: Path
    ) -> None:
        """An injected client means ``create_llm_client`` is never called."""
        import agent_harness.llm as llm_module
        from agent_harness import AgentHarness

        calls: list[Any] = []
        original = llm_module.create_llm_client

        def _counting(config: Any) -> Any:
            calls.append(config)
            return original(config)

        llm_module.create_llm_client = _counting
        try:
            client = doubles.MockLLMClient()
            harness = AgentHarness(self._config(tmp_path), llm_client=client)
            assert harness._resolve_llm_client() is client
            assert calls == []
        finally:
            llm_module.create_llm_client = original

    def test_missing_api_key_raises_with_remediation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SPEC-005 § 4 — the failure names the variable and the fix."""
        from agent_harness import AgentHarness

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        harness = AgentHarness(self._config(tmp_path))
        with pytest.raises(doubles.AgentError) as excinfo:
            harness._resolve_llm_client()
        error = excinfo.value
        assert error.code == "CONFIG_VALIDATION_FAILED"
        assert "OPENAI_API_KEY" in error.message
        assert "cp .env.example .env" in error.message

    def test_absent_seams_are_built_from_the_real_module_paths(
        self, tmp_path: Path
    ) -> None:
        """With no injection, Plan 1's factory supplies the real client (I1)."""
        import agent_harness.llm as llm_module
        from agent_harness import AgentHarness

        harness = AgentHarness(self._config(tmp_path))
        client = harness._resolve_llm_client()

        assert isinstance(client, llm_module.LLMClient)
        assert type(client).__module__.startswith("agent_harness.llm")
        assert harness._resolve_llm_client() is client  # cached, not rebuilt


# ---------------------------------------------------------------------------
# Sub-phase 1.3 — plan() dry-run entry point
# ---------------------------------------------------------------------------


class _FixedPlanner(doubles.StubPlanner):
    """A planner that always returns a fixed plan, recording what it was asked."""

    def __init__(self, plan: doubles.ExecutionPlan) -> None:
        """Seed the canned plan (returned by identity, hence ``fresh=False``)."""
        super().__init__(plan, fresh=False)


class TestPlanOnly:
    """SPEC-005 § 1 — ``plan()`` plans without executing."""

    def _harness(self, tmp_path: Path, **seams: Any) -> Any:
        from agent_harness import AgentHarness

        config = doubles.Config()
        config.execution.output_dir = str(tmp_path / "out")
        config.execution.temp_dir = str(tmp_path / "tmp")
        return AgentHarness(config, **seams)

    def test_returns_the_planner_execution_plan(self, tmp_path: Path) -> None:
        """The object the planner produced is the object returned."""
        plan = doubles.ExecutionPlan(id="plan-9", original_prompt="do it")
        planner = _FixedPlanner(plan)
        harness = self._harness(tmp_path, planner=planner)

        assert harness.plan("do it") is plan
        assert planner.prompts == ["do it"]

    def test_executes_zero_tools(self, tmp_path: Path) -> None:
        """Planning must not run anything — asserted through a counting tool."""
        counting = doubles.StubEchoTool("web_search")
        registry = doubles.ToolRegistry()
        registry.register(counting)
        planner = doubles.StubPlanner(doubles.one_step_plan(tool="web_search"))
        harness = self._harness(tmp_path, registry=registry, planner=planner)

        result = harness.plan("Research something and write a file")

        assert isinstance(result, doubles.ExecutionPlan)
        assert counting.execute_calls == 0
        assert counting.cleanup_calls == 0

    def test_planner_receives_the_registry_tool_list(self, tmp_path: Path) -> None:
        """SPEC-005 § 1.1 step 5 — the planner is handed the available tools."""
        registry = doubles.ToolRegistry()
        registry.register(doubles.StubEchoTool("web_search"))
        registry.register(doubles.StubEchoTool("file_write"))
        planner = doubles.StubPlanner()
        harness = self._harness(tmp_path, registry=registry, planner=planner)

        harness.plan("a task")

        assert planner.plan_calls[0]["prompt"] == "a task"
        assert [t["name"] for t in planner.plan_calls[0]["available_tools"]] == [
            "web_search",
            "file_write",
        ]

    def test_rejects_an_empty_prompt(self, tmp_path: Path) -> None:
        """Prompt validation is shared with ``run()`` (SPEC-005 § 1.1 step 1)."""
        harness = self._harness(tmp_path)
        with pytest.raises(doubles.AgentError) as excinfo:
            harness.plan("   ")
        assert excinfo.value.code == "PROMPT_INVALID"

    def test_the_real_planner_builds_real_model_objects(self, tmp_path: Path) -> None:
        """SCR-P3-6 at I1: no planner injected → Plan 1's classes come back.

        Plan 3's planner builds its plan through an injected ``ModelProvider``. The
        composition root supplies :class:`_SchemaModels`, so the returned plan and its
        steps are the SPEC-001 classes owned by Plan 1 — not Plan 3's stand-ins.
        """
        payload = {
            "steps": [
                {
                    "description": "search the web",
                    "tool_hint": "web_search",
                    "input_data": {"query": "Research a topic"},
                    "priority": "high",
                }
            ]
        }
        harness = self._harness(tmp_path, llm_client=doubles.MockLLMClient([payload]))

        plan = harness.plan("Research a topic")

        assert isinstance(plan, doubles.ExecutionPlan)
        assert type(plan).__module__ == "agent_harness.config.schema"
        assert type(plan.steps[0]).__module__ == "agent_harness.config.schema"
        assert plan.original_prompt == "Research a topic"
        assert len(plan.steps) == 1
        assert plan.steps[0].tool_hint == "web_search"
        assert plan.steps[0].priority is doubles.TaskPriority.HIGH


# ---------------------------------------------------------------------------
# Sub-phase 1.4 — runtime tool registration
# ---------------------------------------------------------------------------


class TestRuntimeToolRegistration:
    """SPEC-005 § 1/§ 5 — ``register_tool`` and ``list_tools``."""

    def _harness(self, tmp_path: Path, **seams: Any) -> Any:
        from agent_harness import AgentHarness

        config = doubles.Config()
        config.execution.output_dir = str(tmp_path / "out")
        config.execution.temp_dir = str(tmp_path / "tmp")
        return AgentHarness(config, **seams)

    def test_register_then_list(self, tmp_path: Path) -> None:
        """A registered tool appears in ``list_tools()``."""
        registry = doubles.ToolRegistry()
        registry.register(doubles.StubEchoTool("web_search"))
        harness = self._harness(tmp_path, registry=registry)

        harness.register_tool(doubles.StubEchoTool("my_custom_tool"))
        names = [t["name"] for t in harness.list_tools()]

        assert "my_custom_tool" in names
        assert "web_search" in names

    def test_list_tools_delegates_to_the_registry(self, tmp_path: Path) -> None:
        """``list_tools()`` returns the registry's own dicts, unchanged."""
        registry = doubles.ToolRegistry()
        tool = doubles.StubEchoTool("web_search")
        registry.register(tool)
        harness = self._harness(tmp_path, registry=registry)

        assert harness.list_tools() == registry.list_tools()
        assert harness.list_tools()[0]["capabilities"] == tool.capabilities

    def test_rejects_a_non_tool_object(self, tmp_path: Path) -> None:
        """SPEC-002 G1 passes straight through: ``TypeError`` for a non-tool."""
        registry = doubles.ToolRegistry()
        harness = self._harness(tmp_path, registry=registry)

        with pytest.raises(TypeError):
            harness.register_tool(object())

    def test_rejects_a_tool_class_rather_than_an_instance(self, tmp_path: Path) -> None:
        """The guard is on instances, not classes."""
        harness = self._harness(tmp_path, registry=doubles.ToolRegistry())

        with pytest.raises(TypeError):
            harness.register_tool(doubles.StubEchoTool)

    def test_registration_after_a_run_affects_later_runs_only(
        self, tmp_path: Path
    ) -> None:
        """SPEC-005 § 5 — the earlier plan never saw the late-registered tool."""
        planner = _FixedPlanner(doubles.ExecutionPlan(id="p", original_prompt="t"))
        registry = doubles.ToolRegistry()
        registry.register(doubles.StubEchoTool("web_search"))
        harness = self._harness(tmp_path, registry=registry, planner=planner)

        harness.plan("first task")
        harness.register_tool(doubles.StubEchoTool("late_tool"))
        harness.plan("second task")

        first = [t["name"] for t in planner.calls[0]["available_tools"]]
        second = [t["name"] for t in planner.calls[1]["available_tools"]]
        assert "late_tool" not in first
        assert "late_tool" in second

    def test_registration_before_first_use_is_visible(self, tmp_path: Path) -> None:
        """Registering before any run lands in the same registry the planner sees."""
        planner = _FixedPlanner(doubles.ExecutionPlan(id="p", original_prompt="t"))
        harness = self._harness(tmp_path, planner=planner)

        harness.register_tool(doubles.StubEchoTool("early_tool"))
        harness.plan("a task")

        names = [t["name"] for t in planner.calls[0]["available_tools"]]
        assert "early_tool" in names

    def test_reregistering_a_name_overwrites(self, tmp_path: Path) -> None:
        """SPEC-002 G2 — the last registration wins."""
        registry = doubles.ToolRegistry()
        registry.register(doubles.StubEchoTool("shared"))
        harness = self._harness(tmp_path, registry=registry)

        harness.register_tool(doubles.StubEchoTool("shared"))

        assert [t["name"] for t in harness.list_tools()].count("shared") == 1


# ---------------------------------------------------------------------------
# Sub-phase 1.5 — prompt validation boundaries and the error surface
# ---------------------------------------------------------------------------


class TestPromptValidation:
    """SPEC-005 § 1.1 step 1 — the input gate, shared by ``run()`` and ``plan()``."""

    def _harness(self, tmp_path: Path) -> Any:
        from agent_harness import AgentHarness

        config = doubles.Config()
        config.execution.output_dir = str(tmp_path / "out")
        config.execution.temp_dir = str(tmp_path / "tmp")
        return AgentHarness(config)

    @pytest.mark.parametrize("prompt", ["", " ", "   ", "\t", "\n", " \n\t "])
    def test_rejects_empty_and_whitespace_prompts(
        self, tmp_path: Path, prompt: str
    ) -> None:
        """A prompt that is blank after stripping is rejected."""
        harness = self._harness(tmp_path)
        with pytest.raises(doubles.AgentError) as excinfo:
            harness.plan(prompt)
        assert excinfo.value.code == "PROMPT_INVALID"
        assert excinfo.value.component == "harness"

    @pytest.mark.parametrize("prompt", [None, 123, ["a task"], {"prompt": "x"}])
    def test_rejects_non_string_prompts(self, tmp_path: Path, prompt: Any) -> None:
        """The gate never lets a non-string through to the LLM."""
        harness = self._harness(tmp_path)
        with pytest.raises(doubles.AgentError) as excinfo:
            harness.plan(prompt)
        assert excinfo.value.code == "PROMPT_INVALID"

    def test_accepts_exactly_the_maximum_length(self, tmp_path: Path) -> None:
        """20 000 characters is inside the boundary, not outside it."""
        from agent_harness.harness import MAX_PROMPT_CHARS

        harness = self._harness(tmp_path)
        planner = _FixedPlanner(doubles.ExecutionPlan(id="p", original_prompt="x"))
        harness._planner = planner

        harness.plan("a" * MAX_PROMPT_CHARS)

        assert len(planner.prompts[0]) == MAX_PROMPT_CHARS

    def test_rejects_one_character_over_the_maximum(self, tmp_path: Path) -> None:
        """20 001 characters is rejected, and the message states both numbers."""
        from agent_harness.harness import MAX_PROMPT_CHARS

        harness = self._harness(tmp_path)
        with pytest.raises(doubles.AgentError) as excinfo:
            harness.plan("a" * (MAX_PROMPT_CHARS + 1))
        error = excinfo.value
        assert error.code == "PROMPT_INVALID"
        assert str(MAX_PROMPT_CHARS + 1) in error.message
        assert str(MAX_PROMPT_CHARS) in error.message

    def test_the_limit_is_the_one_the_spec_freezes(self) -> None:
        """SPEC-005 § 1.1 step 1 fixes the bound at 20 000 characters."""
        from agent_harness.harness import MAX_PROMPT_CHARS

        assert MAX_PROMPT_CHARS == 20_000

    def test_length_is_measured_before_stripping(self, tmp_path: Path) -> None:
        """Padding does not let an oversized prompt slip through."""
        from agent_harness.harness import MAX_PROMPT_CHARS

        harness = self._harness(tmp_path)
        with pytest.raises(doubles.AgentError):
            harness.plan("  " + "a" * MAX_PROMPT_CHARS + "  ")

    def test_multibyte_characters_count_as_one(self, tmp_path: Path) -> None:
        """The bound is on characters, not bytes."""
        from agent_harness.harness import MAX_PROMPT_CHARS

        harness = self._harness(tmp_path)
        harness._planner = _FixedPlanner(doubles.ExecutionPlan(id="p"))

        harness.plan("é" * MAX_PROMPT_CHARS)  # 2 bytes each; must still be accepted


class TestErrorPropagationPolicy:
    """SPEC-005 § 1.1 — which lifecycle steps raise and which are contained."""

    def test_raising_steps_are_three_through_five(self) -> None:
        """Client/registry/planner failures propagate to the caller."""
        from agent_harness.harness import RAISING_LIFECYCLE_STEPS

        assert sorted(RAISING_LIFECYCLE_STEPS) == [3, 4, 5]

    def test_contained_steps_are_six_through_eight(self) -> None:
        """Execute/assemble/metrics failures are surfaced on the result."""
        from agent_harness.harness import CONTAINED_LIFECYCLE_STEPS

        assert sorted(CONTAINED_LIFECYCLE_STEPS) == [6, 7, 8]

    def test_the_two_policies_do_not_overlap(self) -> None:
        """A step cannot both raise and be contained."""
        from agent_harness.harness import (
            CONTAINED_LIFECYCLE_STEPS,
            RAISING_LIFECYCLE_STEPS,
        )

        assert not RAISING_LIFECYCLE_STEPS & CONTAINED_LIFECYCLE_STEPS


class TestContainedFailureResult:
    """SPEC-005 § 1.1/§ 1.2 — a contained failure still returns a result."""

    def _harness(self, tmp_path: Path) -> Any:
        from agent_harness import AgentHarness

        config = doubles.Config()
        config.execution.output_dir = str(tmp_path / "out")
        config.execution.temp_dir = str(tmp_path / "tmp")
        return AgentHarness(config)

    def test_failure_result_carries_the_status_and_errors(self, tmp_path: Path) -> None:
        """The result is ``failed`` and its ``errors`` mirror the context."""
        harness = self._harness(tmp_path)
        plan = doubles.ExecutionPlan(id="p1", original_prompt="task")
        errors = [
            {
                "step_id": "step_0",
                "attempt": 1,
                "error": "boom",
                "recovered": False,
                "level": 1,
            }
        ]

        result = harness._failure_result(plan, errors)

        assert result.status == "failed"
        assert result.errors == errors
        assert result.plan is plan

    def test_partial_status_is_preserved(self, tmp_path: Path) -> None:
        """The assembler's ``partial`` verdict is not flattened to ``failed``."""
        harness = self._harness(tmp_path)
        result = harness._failure_result(
            doubles.ExecutionPlan(id="p"), [], status="partial"
        )
        assert result.status == "partial"

    def test_files_created_is_deduplicated_and_ordered(self, tmp_path: Path) -> None:
        """SPEC-005 § 1.2 — mirrors ``context['files_created']``, deduped, in order."""
        harness = self._harness(tmp_path)
        plan = doubles.ExecutionPlan(id="p")
        plan.context["files_created"] = ["b.md", "a.md", "b.md", "c.md"]

        result = harness._failure_result(plan, [])

        assert result.files_created == ["b.md", "a.md", "c.md"]

    def test_missing_metrics_are_zeroed_not_absent(self, tmp_path: Path) -> None:
        """A contained failure still yields a well-formed metrics object."""
        harness = self._harness(tmp_path)
        plan = doubles.ExecutionPlan(id="p7", original_prompt="a task")

        result = harness._failure_result(plan, [])

        assert result.metrics.plan_id == "p7"
        assert result.metrics.total_steps == 0
        assert result.metrics.prompt_length == len("a task")


# ---------------------------------------------------------------------------
# Sub-phase 2.1 — startup sequence (lifecycle steps 1-4)
# ---------------------------------------------------------------------------

#: SPEC-003 § 4.1 — the FROZEN context layout.
FROZEN_CONTEXT_KEYS = {
    "config",
    "step_results",
    "variables",
    "errors",
    "files_created",
    "llm_client",
    "allowed_read_paths",
    "allowed_write_paths",
}


class TestStartupSequence:
    """SPEC-005 § 1.1 steps 1-4 — validate, fresh context, client, registry."""

    def _harness(self, tmp_path: Path, **seams: Any) -> Any:
        from agent_harness import AgentHarness

        config = doubles.Config()
        config.execution.output_dir = str(tmp_path / "out")
        config.execution.temp_dir = str(tmp_path / "tmp")
        return AgentHarness(config, **seams)

    def test_context_carries_exactly_the_frozen_keys(self, tmp_path: Path) -> None:
        """SPEC-003 § 4.1 — no key added, none missing."""
        harness = self._harness(tmp_path)
        run_context = harness._prepare_run("a task", None)
        assert set(run_context) == FROZEN_CONTEXT_KEYS

    def test_variables_are_seeded_from_the_context_argument(
        self, tmp_path: Path
    ) -> None:
        """SPEC-005 § 1.1 step 2 — user-supplied context becomes variables."""
        harness = self._harness(tmp_path)
        supplied = {"data_file": "./data/sales.csv", "audience": "executives"}

        run_context = harness._prepare_run("a task", supplied)

        assert run_context["variables"] == supplied
        assert run_context["variables"] is not supplied  # copied, not aliased

    def test_file_paths_are_seeded_into_allowed_read_paths(
        self, tmp_path: Path
    ) -> None:
        """Only path-shaped values are promoted to read permissions."""
        harness = self._harness(tmp_path)
        supplied = {
            "data_file": "./data/sales.csv",
            "note": "hello world",
            "count": 3,
            "nested": {"source": "reports/q1.json"},
            "batch": ["a.txt", "not a path at all"],
        }

        run_context = harness._prepare_run("a task", supplied)

        assert run_context["allowed_read_paths"] == [
            "./data/sales.csv",
            "reports/q1.json",
            "a.txt",
        ]

    def test_no_context_argument_leaves_seeds_empty(self, tmp_path: Path) -> None:
        """``context=None`` is valid and produces empty seeds."""
        harness = self._harness(tmp_path)
        run_context = harness._prepare_run("a task", None)
        assert run_context["variables"] == {}
        assert run_context["allowed_read_paths"] == []

    def test_llm_client_is_created_before_the_registry(self, tmp_path: Path) -> None:
        """The registry is built from the client, so the client must exist first."""
        import agent_harness.llm as llm_module
        import agent_harness.tools as tools_module

        order: list[str] = []
        real_client = llm_module.create_llm_client
        real_tools = tools_module.default_tools

        def _client(config: Any) -> Any:
            order.append("create_llm_client")
            return real_client(config)

        def _tools(config: Any, llm_client: Any) -> Any:
            order.append("default_tools")
            return real_tools(config, llm_client)

        llm_module.create_llm_client = _client
        tools_module.default_tools = _tools
        try:
            harness = self._harness(tmp_path)
            harness._prepare_run("a task", None)
        finally:
            llm_module.create_llm_client = real_client
            tools_module.default_tools = real_tools

        assert order == ["create_llm_client", "default_tools"]

    def test_the_registry_receives_the_resolved_client(self, tmp_path: Path) -> None:
        """SPEC-002 § 2 — ``default_tools(config, llm_client)`` is threaded through."""
        harness = self._harness(tmp_path)

        harness._prepare_run("a task", None)

        llm_tool = harness._registry.get("llm_synthesize")
        assert llm_tool is not None
        assert llm_tool._llm_client is harness._llm_client

    def test_each_prepare_produces_a_fresh_context(self, tmp_path: Path) -> None:
        """SPEC-005 § 1.1 step 2 — a fresh ContextStore per run, no leakage."""
        harness = self._harness(tmp_path)
        first = harness._prepare_run("task one", {"a": 1})
        first["files_created"].append("leaked.md")
        second = harness._prepare_run("task two", None)

        assert first is not second
        assert second["files_created"] == []
        assert second["variables"] == {}

    def test_runtime_registered_tools_survive_into_the_registry(
        self, tmp_path: Path
    ) -> None:
        """SPEC-005 § 1.1 step 4 — built-ins plus runtime tools."""
        harness = self._harness(tmp_path)
        harness.register_tool(doubles.StubEchoTool("custom_tool"))

        harness._prepare_run("a task", None)

        names = [t["name"] for t in harness.list_tools()]
        assert "custom_tool" in names
        assert "web_search" in names

    def test_an_invalid_prompt_short_circuits_before_any_construction(
        self, tmp_path: Path
    ) -> None:
        """Step 1 runs first: no client or registry is built for a bad prompt."""
        import agent_harness.llm as llm_module

        calls: list[str] = []
        real_client = llm_module.create_llm_client

        def _client(config: Any) -> Any:
            calls.append("create_llm_client")
            return real_client(config)

        llm_module.create_llm_client = _client
        try:
            harness = self._harness(tmp_path)
            with pytest.raises(doubles.AgentError):
                harness._prepare_run("   ", None)
        finally:
            llm_module.create_llm_client = real_client

        assert calls == []


# ---------------------------------------------------------------------------
# Sub-phase 2.2 — execute -> assemble -> report -> HarnessResult
# ---------------------------------------------------------------------------


class _TwoStepPlanner(doubles.Planner):
    """Plans one step against a working tool and one against a failing tool."""

    def __init__(
        self, llm_client: doubles.LLMClient, config: doubles.Config, **kwargs: Any
    ) -> None:
        """Store collaborators and start the call log."""
        super().__init__(llm_client, config, **kwargs)
        self.calls: list[dict[str, Any]] = []

    def plan(
        self,
        prompt: str,
        available_tools: list[dict[str, Any]],
        *,
        context: dict[str, Any] | None = None,
    ) -> doubles.ExecutionPlan:
        """Return a two-step plan so one step can succeed and one can fail."""
        self.calls.append(
            {"prompt": prompt, "available_tools": available_tools, "context": context}
        )
        return doubles.ExecutionPlan(
            original_prompt=prompt,
            steps=[
                doubles.Step(id="step_0", description="works", tool_hint="good_tool"),
                doubles.Step(id="step_1", description="fails", tool_hint="bad_tool"),
            ],
        )


class _ExplodingOrchestrator(doubles.Orchestrator):
    """An orchestrator whose ``execute`` always fails, for containment tests."""

    def __init__(self, message: str = "orchestrator exploded") -> None:
        """Store the message to raise."""
        super().__init__(doubles.ToolRegistry(), doubles.Config())
        self._message = message
        self.plans: list[doubles.ExecutionPlan] = []

    @property
    def calls(self) -> int:
        """How many times ``execute`` was invoked."""
        return len(self.plans)

    def execute(self, plan: doubles.ExecutionPlan) -> doubles.ExecutionPlan:
        """Record the plan, then raise."""
        self.plans.append(plan)
        raise RuntimeError(self._message)


class _ExplodingAssembler(doubles.Assembler):
    """An assembler whose ``assemble`` always fails."""

    def __init__(self) -> None:
        """No collaborators needed."""
        super().__init__(doubles.Config())
        self.seen: list[tuple[doubles.ExecutionPlan, dict[str, Any]]] = []

    def assemble(
        self, plan: doubles.ExecutionPlan, context: dict[str, Any]
    ) -> doubles.AssemblyResult:
        """Record the call, then raise."""
        self.seen.append((plan, context))
        raise RuntimeError("assembler exploded")


def _plumbing_seams() -> dict[str, Any]:
    """The default collaborator doubles for pipeline tests.

    Every test in :class:`TestRunPipeline` exercises the *harness's* lifecycle, so
    the plan is scripted and the tools are echo doubles: no LLM round, no network.
    A test that wants the real planner or registry simply overrides the seam.
    """
    return {
        "llm_client": doubles.MockLLMClient(),
        "registry": doubles.stub_registry(),
        "planner": doubles.StubPlanner(doubles.one_step_plan(tool="web_search")),
    }


class TestRunPipeline:
    """SPEC-005 § 1.1 steps 5-9."""

    def _harness(self, tmp_path: Path, **seams: Any) -> Any:
        from agent_harness import AgentHarness

        config = doubles.Config()
        config.execution.output_dir = str(tmp_path / "out")
        config.execution.temp_dir = str(tmp_path / "tmp")
        merged = _plumbing_seams()
        merged.update(seams)
        return AgentHarness(config, **merged)

    def test_completed_run_returns_assembled_output(self, tmp_path: Path) -> None:
        """A fully successful run reports ``completed`` with the assembly output."""
        harness = self._harness(tmp_path)

        result = harness.run("Research a topic and write a summary")

        assert result.status == "completed"
        assert "do the thing" in str(result.final_output)
        assert isinstance(result.plan, doubles.ExecutionPlan)
        assert result.metrics.total_steps == 1
        assert result.metrics.successful_steps == 1
        assert result.errors == []

    def test_result_is_a_harness_result(self, tmp_path: Path) -> None:
        """The public type is returned, not an internal one."""
        from agent_harness import HarnessResult

        result = self._harness(tmp_path).run("a task")
        assert isinstance(result, HarnessResult)

    def test_partial_status_is_reported_as_partial(self, tmp_path: Path) -> None:
        """SPEC-003 § 6 rule 3 — a deliverable with a missing step is ``partial``."""
        registry = doubles.ToolRegistry()
        registry.register(doubles.StubEchoTool("good_tool"))
        registry.register(doubles.StubEchoTool("bad_tool", fail=True))
        harness = self._harness(
            tmp_path,
            registry=registry,
            planner=_TwoStepPlanner(doubles.MockLLMClient(), doubles.Config()),
        )

        result = harness.run("a task")

        assert result.status == "partial"
        assert result.metrics.successful_steps == 1
        assert result.metrics.failed_steps == 1
        assert result.final_output  # a deliverable still exists

    def test_no_deliverable_at_all_reports_failed(self, tmp_path: Path) -> None:
        """SPEC-003 § 6 rule 4 — nothing produced means ``failed``, not ``partial``."""
        registry = doubles.ToolRegistry()
        registry.register(doubles.StubEchoTool("bad_tool", fail=True))
        harness = self._harness(
            tmp_path,
            registry=registry,
            planner=_TwoStepPlanner(doubles.MockLLMClient(), doubles.Config()),
        )

        result = harness.run("a task")

        assert result.status == "failed"

    def test_failed_run_reports_failed_without_raising(self, tmp_path: Path) -> None:
        """No deliverable at all is ``failed`` — still a returned result."""
        registry = doubles.ToolRegistry()  # empty: the planner gets no tools
        harness = self._harness(tmp_path, registry=registry)

        result = harness.run("a task")

        assert result.status == "failed"

    def test_metrics_are_computed_from_the_executed_plan(self, tmp_path: Path) -> None:
        """SPEC-005 § 1.1 step 8."""
        harness = self._harness(tmp_path)

        result = harness.run("Research something")

        assert result.metrics.plan_id == result.plan.id
        assert result.metrics.prompt_length == len("Research something")
        assert result.metrics.tools_used == ["web_search"]

    def test_llm_usage_flows_into_metrics(self, tmp_path: Path) -> None:
        """SPEC-003 § 7 — counters come from the client the harness holds."""
        client = doubles.MockLLMClient()
        harness = self._harness(tmp_path, llm_client=client)

        result = harness.run("a task")

        assert result.metrics.llm_calls == client.usage.calls
        assert result.metrics.llm_tokens_used == (
            client.usage.prompt_tokens + client.usage.completion_tokens
        )

    def test_report_is_rendered_through_logging_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SPEC-005 § 1.1 step 8 — the report comes from ``logging/report.py``."""
        import agent_harness.logging.report as report_module

        calls: list[dict[str, Any]] = []
        real = report_module.render_report

        def _recorder(plan: Any, metrics: Any, *, style: str = "text") -> str:
            calls.append({"plan_id": plan.id, "style": style})
            rendered: str = real(plan, metrics, style=style)
            return rendered

        monkeypatch.setattr(report_module, "render_report", _recorder)
        harness = self._harness(tmp_path)

        result = harness.run("a task")

        assert calls and calls[0]["plan_id"] == result.plan.id
        assert harness.last_report

    def test_files_created_mirror_the_context_deduplicated(
        self, tmp_path: Path
    ) -> None:
        """SPEC-005 § 1.2."""
        harness = self._harness(tmp_path)

        class _Seeding(doubles.Orchestrator):
            def execute(self, plan: doubles.ExecutionPlan) -> doubles.ExecutionPlan:
                plan.context["files_created"] = ["out/a.md", "out/b.md", "out/a.md"]
                return super().execute(plan)

        harness._orchestrator = _Seeding(doubles.ToolRegistry(), harness.config)
        result = harness.run("a task")

        assert result.files_created == ["out/a.md", "out/b.md"]

    def test_errors_mirror_context_errors(self, tmp_path: Path) -> None:
        """``HarnessResult.errors`` mirrors ``context['errors']``."""
        harness = self._harness(tmp_path)

        class _Erroring(doubles.Orchestrator):
            def execute(self, plan: doubles.ExecutionPlan) -> doubles.ExecutionPlan:
                plan.context["errors"] = [
                    {
                        "step_id": "step_0",
                        "attempt": 1,
                        "error": "boom",
                        "recovered": False,
                        "level": 1,
                    }
                ]
                return super().execute(plan)

        harness._orchestrator = _Erroring(doubles.ToolRegistry(), harness.config)
        result = harness.run("a task")

        assert result.errors[0]["error"] == "boom"

    def test_an_orchestrator_crash_is_contained_not_raised(
        self, tmp_path: Path
    ) -> None:
        """SPEC-005 § 1.1 — step 6 failures surface on the result."""
        exploding = _ExplodingOrchestrator()
        harness = self._harness(tmp_path, orchestrator=exploding)

        result = harness.run("a task")

        assert exploding.calls == 1
        assert result.status == "failed"
        assert any(
            "orchestrator exploded" in str(e.get("error", "")) for e in result.errors
        )
        assert any(e.get("code") == "SYSTEM_ERROR" for e in result.errors)

    def test_an_assembler_crash_is_contained_not_raised(self, tmp_path: Path) -> None:
        """SPEC-005 § 1.1 — step 7 failures surface on the result."""
        harness = self._harness(tmp_path, assembler=_ExplodingAssembler())

        result = harness.run("a task")

        assert result.status == "failed"
        assert any(
            "assembler exploded" in str(e.get("error", "")) for e in result.errors
        )

    def test_a_planner_failure_propagates(self, tmp_path: Path) -> None:
        """SPEC-005 § 1.1 — step 5 is a *raising* step, not a contained one."""

        class _BadPlanner(doubles.Planner):
            def __init__(self) -> None:
                """No collaborators needed."""
                super().__init__(doubles.MockLLMClient(), doubles.Config())
                self.attempts: list[dict[str, Any]] = []

            def plan(
                self,
                prompt: str,
                available_tools: list[dict[str, Any]],
                *,
                context: dict[str, Any] | None = None,
            ) -> doubles.ExecutionPlan:
                """Record the attempt, then raise a planner-class error."""
                self.attempts.append(
                    {
                        "prompt": prompt,
                        "available_tools": available_tools,
                        "context": context,
                    }
                )
                raise doubles.AgentError(
                    code="PLAN_VALIDATION_FAILED",
                    message="circular dependency",
                    component="planner",
                )

        harness = self._harness(tmp_path, planner=_BadPlanner())

        with pytest.raises(doubles.AgentError) as excinfo:
            harness.run("a task")
        assert excinfo.value.code == "PLAN_VALIDATION_FAILED"

    def test_output_format_is_exposed_to_the_assembler(self, tmp_path: Path) -> None:
        """``run(output_format=...)`` reaches the context the assembler reads."""
        harness = self._harness(tmp_path)
        seen: dict[str, Any] = {}

        class _Watching(doubles.Assembler):
            def assemble(
                self, plan: doubles.ExecutionPlan, context: dict[str, Any]
            ) -> doubles.AssemblyResult:
                seen.update(context)
                return super().assemble(plan, context)

        harness._assembler = _Watching(harness.config)
        harness.run("a task", output_format="json")

        assert seen["output_format"] == "json"

    def test_invalid_prompt_raises_before_any_step(self, tmp_path: Path) -> None:
        """Step 1 gates everything."""
        harness = self._harness(tmp_path)
        with pytest.raises(doubles.AgentError) as excinfo:
            harness.run("")
        assert excinfo.value.code == "PROMPT_INVALID"

    def test_duration_is_measured_with_the_injected_clock(self, tmp_path: Path) -> None:
        """SPEC-000 § 5.5 — deterministic timing via injection, not wall clock."""
        ticks = iter([1000.0, 1002.5])
        harness = self._harness(tmp_path, clock=lambda: next(ticks))

        result = harness.run("a task")

        assert result.metrics.total_duration_ms == 2500


# ---------------------------------------------------------------------------
# Sub-phase 2.3 — ExecutionHooks -> progress callback
# ---------------------------------------------------------------------------


class _RecordingProgress:
    """A ``progress`` callback that keeps every event for assertion."""

    def __init__(self) -> None:
        """Start with an empty log."""
        self.events: list[dict[str, Any]] = []

    def __call__(self, event: dict[str, Any]) -> None:
        """Record the event."""
        self.events.append(event)


class _FiringOrchestrator(doubles.Orchestrator):
    """An orchestrator that fires every hook, to test the bridge in isolation."""

    def __init__(self, *, fail_step: bool = False) -> None:
        """Optionally make the single step fail."""
        super().__init__(doubles.ToolRegistry(), doubles.Config())
        self._fail_step = fail_step
        self.fired: list[str] = []

    def execute(self, plan: doubles.ExecutionPlan) -> doubles.ExecutionPlan:
        """Fire the full hook sequence in the documented order."""
        hooks = self.hooks
        assert hooks is not None, "harness must attach hooks before executing"
        step = plan.steps[0]
        step.tool_name = step.tool_hint
        if hooks.on_plan_start:
            hooks.on_plan_start(plan)
        if hooks.on_step_start:
            hooks.on_step_start(step)
        if hooks.on_recovery:
            hooks.on_recovery(step, 1, "retry")
        if self._fail_step:
            step.status = doubles.StepStatus.FAILED
            step.error = "tool failed"
            if hooks.on_step_failed:
                hooks.on_step_failed(step, "tool failed")
        else:
            step.status = doubles.StepStatus.SUCCESS
            step.output_data = "done"
            if hooks.on_step_complete:
                hooks.on_step_complete(step, doubles.ToolResult(success=True))
        plan.status = (
            doubles.StepStatus.FAILED if self._fail_step else doubles.StepStatus.SUCCESS
        )
        if hooks.on_plan_complete:
            hooks.on_plan_complete(plan)
        return plan


class TestProgressHooks:
    """SPEC-003 § 2.1 / SPEC-005 § 2.2 — the progress seam."""

    def _harness(self, tmp_path: Path, **seams: Any) -> Any:
        from agent_harness import AgentHarness

        config = doubles.Config()
        config.execution.output_dir = str(tmp_path / "out")
        config.execution.temp_dir = str(tmp_path / "tmp")
        merged = _plumbing_seams()
        merged.update(seams)
        return AgentHarness(config, **merged)

    def test_no_progress_callback_is_the_default_and_is_safe(
        self, tmp_path: Path
    ) -> None:
        """With nothing injected the run still completes."""
        harness = self._harness(tmp_path)
        assert harness._progress is None
        assert harness.run("a task").status == "completed"

    def test_hooks_are_attached_to_the_orchestrator(self, tmp_path: Path) -> None:
        """SPEC-003 § 2.1 — the seam is wired, not merely available."""
        orchestrator = _FiringOrchestrator()
        harness = self._harness(
            tmp_path, orchestrator=orchestrator, progress=_RecordingProgress()
        )

        harness.run("a task")

        assert orchestrator.hooks is not None
        assert orchestrator.hooks.on_step_start is not None

    def test_events_arrive_in_lifecycle_order(self, tmp_path: Path) -> None:
        """plan_start -> step_start -> recovery -> step_complete -> plan_complete."""
        events: list[dict[str, Any]] = []
        orchestrator = _FiringOrchestrator()
        harness = self._harness(
            tmp_path, orchestrator=orchestrator, progress=events.append
        )

        harness.run("a task")

        assert [e["event"] for e in events] == [
            "plan_start",
            "step_start",
            "recovery",
            "step_complete",
            "plan_complete",
        ]

    def test_failure_events_are_reported(self, tmp_path: Path) -> None:
        """A failing step surfaces ``step_failed`` with the error text."""
        events: list[dict[str, Any]] = []
        orchestrator = _FiringOrchestrator(fail_step=True)
        harness = self._harness(
            tmp_path, orchestrator=orchestrator, progress=events.append
        )

        harness.run("a task")

        failed = [e for e in events if e["event"] == "step_failed"]
        assert failed and failed[0]["error"] == "tool failed"
        assert [e["event"] for e in events][-1] == "plan_complete"

    def test_step_events_carry_identifying_fields(self, tmp_path: Path) -> None:
        """The CLI needs enough to render a live progress line."""
        events: list[dict[str, Any]] = []
        harness = self._harness(
            tmp_path, orchestrator=_FiringOrchestrator(), progress=events.append
        )

        harness.run("a task")

        started = next(e for e in events if e["event"] == "step_start")
        assert started["step_id"] == "step_0"
        assert started["tool"] == "web_search"
        assert started["description"]

    def test_a_raising_callback_never_aborts_the_run(self, tmp_path: Path) -> None:
        """SPEC-003 § 2.1 — hooks are best-effort."""

        def _explode(event: dict[str, Any]) -> None:
            raise RuntimeError(f"progress renderer exploded on {event['event']}")

        harness = self._harness(
            tmp_path, orchestrator=_FiringOrchestrator(), progress=_explode
        )

        result = harness.run("a task")

        assert result.status == "completed"

    def test_a_raising_callback_is_logged_not_swallowed(self, tmp_path: Path) -> None:
        """The isolation is recorded, so a broken renderer is diagnosable."""
        logger = doubles.RecordingLogger()

        def _explode(event: dict[str, Any]) -> None:
            raise RuntimeError(f"progress renderer exploded on {event['event']}")

        harness = self._harness(
            tmp_path,
            orchestrator=_FiringOrchestrator(),
            progress=_explode,
            logger=logger,
        )

        harness.run("a task")

        warnings = [r for r in logger.records if r["level"] == "WARNING"]
        assert any(r["event"] == "progress_callback_failed" for r in warnings)
        assert any(
            "progress renderer exploded" in str(r.get("error")) for r in warnings
        )

    def test_build_hooks_produces_every_documented_hook(self, tmp_path: Path) -> None:
        """All six SPEC-003 § 2.1 seams are populated."""
        harness = self._harness(tmp_path, progress=_RecordingProgress())
        hooks = harness._build_hooks()

        for name in (
            "on_plan_start",
            "on_step_start",
            "on_step_complete",
            "on_step_failed",
            "on_recovery",
            "on_plan_complete",
        ):
            assert getattr(hooks, name) is not None, name


# ---------------------------------------------------------------------------
# Sub-phase 2.4 — reuse, shutdown and interrupt semantics
# ---------------------------------------------------------------------------


class _InterruptingOrchestrator(doubles.Orchestrator):
    """An orchestrator that is interrupted mid-step, per SPEC-003 § 2."""

    def __init__(self, registry: doubles.ToolRegistry) -> None:
        """Store the registry."""
        super().__init__(registry, doubles.Config())

    def execute(self, plan: doubles.ExecutionPlan) -> doubles.ExecutionPlan:
        """Mark the active step failed, then re-raise, as the spec requires."""
        step = plan.steps[0]
        step.status = doubles.StepStatus.FAILED
        step.error = "interrupted"
        raise KeyboardInterrupt


class TestInstanceReuse:
    """SPEC-005 § 5 — a harness is reusable across runs."""

    def _harness(self, tmp_path: Path, **seams: Any) -> Any:
        from agent_harness import AgentHarness

        config = doubles.Config()
        config.execution.output_dir = str(tmp_path / "out")
        config.execution.temp_dir = str(tmp_path / "tmp")
        merged = _plumbing_seams()
        merged.update(seams)
        return AgentHarness(config, **merged)

    def test_registry_and_client_are_reused(self, tmp_path: Path) -> None:
        """The expensive collaborators are built once, not per run."""
        harness = self._harness(tmp_path)

        first = harness.run("task one")
        registry_after_first = harness._registry
        client_after_first = harness._llm_client
        second = harness.run("task two")

        assert harness._registry is registry_after_first
        assert harness._llm_client is client_after_first
        assert first.plan is not second.plan

    def test_contexts_do_not_leak_between_runs(self, tmp_path: Path) -> None:
        """A file created in run one is absent from run two's result."""
        harness = self._harness(tmp_path)

        class _Seeding(doubles.Orchestrator):
            def __init__(self) -> None:
                super().__init__(doubles.ToolRegistry(), doubles.Config())
                self.n = 0

            def execute(self, plan: doubles.ExecutionPlan) -> doubles.ExecutionPlan:
                self.n += 1
                if self.n == 1:
                    plan.context["files_created"] = ["run1.md"]
                return super().execute(plan)

        harness._orchestrator = _Seeding()
        first = harness.run("task one")
        second = harness.run("task two")

        assert first.files_created == ["run1.md"]
        assert second.files_created == []

    def test_usage_counters_accumulate_across_runs(self, tmp_path: Path) -> None:
        """SPEC-005 § 5 — documented accumulation on a reused instance.

        The real planner is used here (``planner=None`` leaves the seam empty), so
        each run makes exactly one scripted ``complete_json`` round and the client's
        lifetime counters are measurable.
        """

        def payload(description: str) -> dict[str, Any]:
            return {
                "steps": [
                    {
                        "description": description,
                        "tool_hint": "web_search",
                        "priority": "high",
                    }
                ]
            }

        # Two scripted replies per run: one planning round, one assembler synthesis
        # (SPEC-003 § 6 rule 5). Four replies therefore cover two runs.
        client = doubles.MockLLMClient(
            [payload("one"), "assembled one", payload("two"), "assembled two"]
        )
        harness = self._harness(tmp_path, llm_client=client, planner=None)

        first = harness.run("task one")
        second = harness.run("task two")

        assert first.metrics.llm_calls == 2
        assert second.metrics.llm_calls > first.metrics.llm_calls
        assert second.metrics.llm_calls == client.usage.calls

    def test_plans_are_independent_objects(self, tmp_path: Path) -> None:
        """Mutating one plan cannot affect the next run."""
        harness = self._harness(tmp_path)

        first = harness.run("task one")
        first.plan.steps[0].status = doubles.StepStatus.SKIPPED
        second = harness.run("task two")

        assert second.plan.steps[0].status is not doubles.StepStatus.SKIPPED


class TestShutdown:
    """SPEC-002 R8 — tool cleanup on shutdown."""

    def _harness(self, tmp_path: Path, **seams: Any) -> Any:
        from agent_harness import AgentHarness

        config = doubles.Config()
        config.execution.output_dir = str(tmp_path / "out")
        config.execution.temp_dir = str(tmp_path / "tmp")
        merged = _plumbing_seams()
        merged.update(seams)
        return AgentHarness(config, **merged)

    def test_close_calls_cleanup_on_every_tool(self, tmp_path: Path) -> None:
        """Every registered tool gets torn down."""
        a, b = doubles.StubEchoTool("a"), doubles.StubEchoTool("b")
        registry = doubles.ToolRegistry()
        registry.register(a)
        registry.register(b)
        harness = self._harness(tmp_path, registry=registry)

        harness.close()

        assert a.cleanup_calls == 1
        assert b.cleanup_calls == 1

    def test_close_is_idempotent(self, tmp_path: Path) -> None:
        """SPEC-002 R8 — calling it twice must not double up."""
        tool = doubles.StubEchoTool("a")
        registry = doubles.ToolRegistry()
        registry.register(tool)
        harness = self._harness(tmp_path, registry=registry)

        harness.close()
        harness.close()

        assert tool.cleanup_calls == 1

    def test_context_manager_closes_on_exit(self, tmp_path: Path) -> None:
        """``with AgentHarness(...) as harness`` cleans up automatically."""
        from agent_harness import AgentHarness

        config = doubles.Config()
        config.execution.output_dir = str(tmp_path / "out")
        config.execution.temp_dir = str(tmp_path / "tmp")
        tool = doubles.StubEchoTool("a")
        registry = doubles.ToolRegistry()
        registry.register(tool)

        with AgentHarness(
            config, **{**_plumbing_seams(), "registry": registry}
        ) as harness:
            harness.run("a task")

        assert tool.cleanup_calls == 1

    def test_cleanup_runs_even_when_the_run_fails(self, tmp_path: Path) -> None:
        """A contained failure must not skip teardown."""
        tool = doubles.StubEchoTool("a")
        registry = doubles.ToolRegistry()
        registry.register(tool)
        harness = self._harness(
            tmp_path, registry=registry, orchestrator=_ExplodingOrchestrator()
        )

        try:
            harness.run("a task")
        finally:
            harness.close()

        assert tool.cleanup_calls == 1

    def test_a_tool_raising_in_cleanup_does_not_stop_the_others(
        self, tmp_path: Path
    ) -> None:
        """One bad teardown cannot prevent the rest, and is not silenced."""

        class _BadCleanup(doubles.StubEchoTool):
            def cleanup(self) -> None:
                raise RuntimeError("cleanup exploded")

        bad, good = _BadCleanup("bad"), doubles.StubEchoTool("good")
        registry = doubles.ToolRegistry()
        registry.register(bad)
        registry.register(good)
        logger = doubles.RecordingLogger()
        harness = self._harness(tmp_path, registry=registry, logger=logger)

        harness.close()

        assert good.cleanup_calls == 1
        assert any(r["event"] == "tool_cleanup_failed" for r in logger.records)


class TestInterrupt:
    """SPEC-003 § 2 / SPEC-005 § 2.1 — SIGINT handling."""

    def _harness(self, tmp_path: Path, **seams: Any) -> Any:
        from agent_harness import AgentHarness

        config = doubles.Config()
        config.execution.output_dir = str(tmp_path / "out")
        config.execution.temp_dir = str(tmp_path / "tmp")
        merged = _plumbing_seams()
        merged.update(seams)
        return AgentHarness(config, **merged)

    def test_interrupt_propagates_so_the_cli_can_exit_130(self, tmp_path: Path) -> None:
        """The interrupt is never swallowed (agent.md F7)."""
        harness = self._harness(
            tmp_path, orchestrator=_InterruptingOrchestrator(doubles.ToolRegistry())
        )

        with pytest.raises(KeyboardInterrupt):
            harness.run("a task")

    def test_interrupt_still_produces_a_failed_result(self, tmp_path: Path) -> None:
        """The interrupted run is inspectable after the fact."""
        harness = self._harness(
            tmp_path, orchestrator=_InterruptingOrchestrator(doubles.ToolRegistry())
        )

        with pytest.raises(KeyboardInterrupt):
            harness.run("a task")

        result = harness.last_result
        assert result is not None
        assert result.status == "failed"
        assert any(e.get("error") == "interrupted" for e in result.errors)
        assert result.plan.status is doubles.StepStatus.FAILED

    def test_interrupt_is_logged(self, tmp_path: Path) -> None:
        """An interrupted run leaves a trace in the log."""
        logger = doubles.RecordingLogger()
        harness = self._harness(
            tmp_path,
            orchestrator=_InterruptingOrchestrator(doubles.ToolRegistry()),
            logger=logger,
        )

        with pytest.raises(KeyboardInterrupt):
            harness.run("a task")

        assert any(r["event"] == "run_interrupted" for r in logger.records)


# ---------------------------------------------------------------------------
# Sub-phase 2.5 — startup warnings (SPEC-005 § 4)
# ---------------------------------------------------------------------------

#: An obviously-fake key matching SPEC-006 § 1 ``security.sensitive_patterns``.
FAKE_SECRET = "sk-" + "0" * 48


class TestStartupWarnings:
    """SPEC-005 § 4 — one-time startup warnings, values never disclosed."""

    def _config(self, tmp_path: Path) -> Any:
        config = doubles.Config()
        config.execution.output_dir = str(tmp_path / "out")
        config.execution.temp_dir = str(tmp_path / "tmp")
        return config

    def _harness(self, tmp_path: Path, **seams: Any) -> Any:
        from agent_harness import AgentHarness

        return AgentHarness(self._config(tmp_path), **seams)

    def test_allow_shell_produces_exactly_one_warning(self, tmp_path: Path) -> None:
        """Enabling shell execution is announced once, at startup."""
        config = self._config(tmp_path)
        config.security.allow_shell = True
        logger = doubles.RecordingLogger()

        from agent_harness import AgentHarness

        AgentHarness(config, logger=logger)

        shell = [r for r in logger.records if r["event"] == "shell_execution_enabled"]
        assert len(shell) == 1
        assert shell[0]["level"] == "WARNING"

    def test_no_shell_warning_when_shell_is_disabled(self, tmp_path: Path) -> None:
        """The default (opt-in off) stays quiet."""
        logger = doubles.RecordingLogger()
        self._harness(tmp_path, logger=logger)
        shell = [r for r in logger.records if r["event"] == "shell_execution_enabled"]
        assert not shell

    def test_missing_wkhtmltopdf_is_an_info_note(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Degraded PDF export is informational, not an error."""
        monkeypatch.setattr(shutil, "which", lambda _name: None)
        logger = doubles.RecordingLogger()
        self._harness(tmp_path, logger=logger)

        pdf = [r for r in logger.records if r["event"] == "pdf_export_degraded"]
        assert len(pdf) == 1
        assert pdf[0]["level"] == "INFO"
        assert "degraded" in str(pdf[0].get("note", "")).lower()

    def test_present_wkhtmltopdf_stays_quiet(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No note when the binary is available."""
        monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/wkhtmltopdf")
        logger = doubles.RecordingLogger()
        self._harness(tmp_path, logger=logger)

        assert not [r for r in logger.records if r["event"] == "pdf_export_degraded"]

    def test_env_vars_to_be_transmitted_are_named(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SPEC-005 § 4 — the *names* of transmitted variables are announced."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(
            f"OPENAI_API_KEY={FAKE_SECRET}\nSEARCH_API_KEY=fake-search-key\n",
            encoding="utf-8",
        )
        logger = doubles.RecordingLogger()
        self._harness(tmp_path, logger=logger)

        transmitted = [
            r for r in logger.records if r["event"] == "credentials_transmitted"
        ]
        assert len(transmitted) == 1
        assert sorted(transmitted[0]["env_vars"]) == [
            "OPENAI_API_KEY",
            "SEARCH_API_KEY",
        ]

    def test_transmitted_warning_never_contains_a_secret_value(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SKL-RELIABILITY-013 — names are visible, values are not."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(
            f"OPENAI_API_KEY={FAKE_SECRET}\n", encoding="utf-8"
        )
        logger = doubles.RecordingLogger()
        self._harness(tmp_path, logger=logger)

        rendered = [str(record) for record in logger.records]
        assert not any(FAKE_SECRET in line for line in rendered)

    def test_no_log_record_matches_a_sensitive_pattern(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every startup record survives the configured redaction patterns."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(
            f"OPENAI_API_KEY={FAKE_SECRET}\n", encoding="utf-8"
        )
        logger = doubles.RecordingLogger()
        self._harness(tmp_path, logger=logger)

        for record in logger.records:
            _, count = doubles.sensitive_data_filter(str(record))
            assert count == 0, record

    def test_no_dotenv_file_is_not_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing ``.env`` produces no crash and no transmitted warning."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        logger = doubles.RecordingLogger()
        self._harness(tmp_path, logger=logger)

        assert not [
            r for r in logger.records if r["event"] == "credentials_transmitted"
        ]

    def test_malformed_dotenv_is_tolerated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A junk line cannot break startup."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(
            "# comment\n\n=novalue\nNOT_AN_ASSIGNMENT\nOPENAI_API_KEY=x\n",
            encoding="utf-8",
        )
        logger = doubles.RecordingLogger()
        self._harness(tmp_path, logger=logger)

        names = [
            r["env_vars"]
            for r in logger.records
            if r["event"] == "credentials_transmitted"
        ]
        assert names == [["OPENAI_API_KEY"]]

    def test_missing_api_key_names_the_remediation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SPEC-005 § 4 — the user is told how to fix it."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        logger = doubles.RecordingLogger()
        self._harness(tmp_path, logger=logger)

        missing = [r for r in logger.records if r["event"] == "api_key_missing"]
        assert len(missing) == 1
        assert missing[0]["env_var"] == "OPENAI_API_KEY"
        assert "cp .env.example .env" in str(missing[0]["remediation"])

    def test_warnings_are_emitted_once_per_instance(self, tmp_path: Path) -> None:
        """Re-running the emitter must not duplicate any warning."""
        config = self._config(tmp_path)
        config.security.allow_shell = True
        logger = doubles.RecordingLogger()

        from agent_harness import AgentHarness

        harness = AgentHarness(config, logger=logger)
        harness._emit_startup_warnings()
        harness._emit_startup_warnings()

        shell = [r for r in logger.records if r["event"] == "shell_execution_enabled"]
        assert len(shell) == 1


# ---------------------------------------------------------------------------
# Sub-phase 4.4 — the --no-fallback recovery policy
# ---------------------------------------------------------------------------


class _FallbackPlanner(doubles.Planner):
    """Plans two steps that each carry fallback tools."""

    def plan(
        self,
        prompt: str,
        available_tools: list[dict[str, Any]],
        *,
        context: dict[str, Any] | None = None,
    ) -> doubles.ExecutionPlan:
        """Return a plan whose steps ask for fallback tools."""
        return doubles.ExecutionPlan(
            original_prompt=prompt,
            context={
                "available_tools": available_tools,
                "planner_context": context,
            },
            steps=[
                doubles.Step(
                    id="s1",
                    description="first",
                    tool_name="echo",
                    fallback_tools=["echo_backup", "shell_command"],
                ),
                doubles.Step(
                    id="s2",
                    description="second",
                    tool_name="echo",
                    depends_on=["s1"],
                    fallback_tools=["echo_backup"],
                ),
            ],
        )


class _CapturingOrchestrator(doubles.Orchestrator):
    """Records the exact plan object it was handed."""

    def __init__(self) -> None:
        """Start with an empty registry and no recorded plan."""
        super().__init__(doubles.ToolRegistry(), doubles.Config())
        self.seen: doubles.ExecutionPlan | None = None

    def execute(self, plan: doubles.ExecutionPlan) -> doubles.ExecutionPlan:
        """Record the plan, mark every step successful, and return it."""
        self.seen = plan
        for step in plan.steps:
            step.status = doubles.StepStatus.SUCCESS
        plan.status = doubles.StepStatus.SUCCESS
        return plan


class TestNoFallbackPolicy:
    """SPEC-005 § 2 — ``--no-fallback`` limits recovery to Level 1."""

    def test_fallbacks_survive_by_default(self) -> None:
        """With replan enabled the orchestrator gets the planner's fallbacks."""
        from agent_harness import AgentHarness

        config = doubles.Config()
        orchestrator = _CapturingOrchestrator()
        harness = AgentHarness(
            config,
            llm_client=doubles.MockLLMClient(),
            planner=_FallbackPlanner(doubles.MockLLMClient(), config),
            orchestrator=orchestrator,
        )

        result = harness.run("do things")

        # The run must actually succeed; a contained failure would still leave
        # ``seen`` populated and hide a broken double.
        assert result.status == "completed"
        assert orchestrator.seen is not None
        assert orchestrator.seen.steps[0].fallback_tools == [
            "echo_backup",
            "shell_command",
        ]

    def test_fallbacks_are_stripped_when_replan_is_disabled(self) -> None:
        """The flag the CLI sets: no Level 2 and no Level 3 recovery."""
        from agent_harness import AgentHarness

        config = doubles.Config()
        config.execution.enable_replan = False
        orchestrator = _CapturingOrchestrator()
        harness = AgentHarness(
            config,
            llm_client=doubles.MockLLMClient(),
            planner=_FallbackPlanner(doubles.MockLLMClient(), config),
            orchestrator=orchestrator,
        )

        result = harness.run("do things")

        assert result.status == "completed"
        assert orchestrator.seen is not None
        assert all(not step.fallback_tools for step in orchestrator.seen.steps)

    def test_stripping_does_not_touch_the_rest_of_the_step(self) -> None:
        """Only the fallback list changes."""
        from agent_harness import AgentHarness

        config = doubles.Config()
        config.execution.enable_replan = False
        orchestrator = _CapturingOrchestrator()
        harness = AgentHarness(
            config,
            llm_client=doubles.MockLLMClient(),
            planner=_FallbackPlanner(doubles.MockLLMClient(), config),
            orchestrator=orchestrator,
        )

        harness.run("do things")

        assert orchestrator.seen is not None
        first = orchestrator.seen.steps[0]
        assert first.tool_name == "echo"
        assert first.description == "first"
        assert first.depends_on == []
        assert orchestrator.seen.steps[1].depends_on == ["s1"]

    def test_the_policy_is_applied_per_run(self) -> None:
        """Flipping the flag between runs changes what the next run gets."""
        from agent_harness import AgentHarness

        config = doubles.Config()
        orchestrator = _CapturingOrchestrator()
        harness = AgentHarness(
            config,
            llm_client=doubles.MockLLMClient(),
            planner=_FallbackPlanner(doubles.MockLLMClient(), config),
            orchestrator=orchestrator,
        )

        harness.run("first run")
        assert orchestrator.seen is not None
        assert orchestrator.seen.steps[0].fallback_tools

        config.execution.enable_replan = False
        harness.run("second run")

        assert orchestrator.seen is not None
        assert not orchestrator.seen.steps[0].fallback_tools


# ---------------------------------------------------------------------------
# Sub-phase 5.1 — the stub-to-real-module swap checklist (integration step I1)
# ---------------------------------------------------------------------------

#: Every cross-plan module the composition root resolves by dotted name. These
#: are the swap targets: at I1 the stub behind each name is replaced by the real
#: Plan 1-3 module, and nothing in this plan changes.
#:
#: The swap grew the table by one: SCR-P3-6's ``ModelProvider`` seam makes the
#: planner's ``Step``/``ExecutionPlan``/``TaskPriority`` and its ``ToolResult``
#: Plan 1/2's real classes, and SPEC-003 § 5's recovery cascade has to be composed
#: from ``agent_harness.orchestration`` — recorded as SCR-P4-12.
RESOLVED_MODULES = frozenset(
    {
        "agent_harness.config",
        "agent_harness.config.schema",
        "agent_harness.context",
        "agent_harness.llm",
        "agent_harness.logging",
        "agent_harness.logging.report",
        "agent_harness.orchestration",
        "agent_harness.planning",
        "agent_harness.tools",
        "agent_harness.tools.base",
    }
)

#: The symbol read off each resolved module. This is the contract the real
#: modules must satisfy for the swap to be a no-op.
RESOLVED_SYMBOLS = frozenset(
    {
        "AgentError",
        "Assembler",
        "Config",
        "ContextStore",
        "ExecutionHooks",
        "ExecutionMetrics",
        "ExecutionPlan",
        "Orchestrator",
        "Planner",
        "RecoveryManager",
        "Step",
        "StepStatus",
        "StructuredLogger",
        "TaskPriority",
        "ToolRegistry",
        "ToolResult",
        "create_llm_client",
        "default_tools",
        "render_report",
    }
)


def _harness_source() -> str:
    """The composition root's source, read from disk."""
    return (
        Path(__file__).resolve().parent.parent / "agent_harness" / "harness.py"
    ).read_text(encoding="utf-8")


def _resolved_modules_in_source() -> set[str]:
    """Extract every ``importlib.import_module("...")`` target from the source."""
    import re

    return set(re.findall(r'import_module\("([^"]+)"\)', _harness_source()))


class TestSwapChecklist:
    """The I1 checklist is a contract, so it is tested rather than trusted."""

    def test_the_documented_module_list_matches_the_code(self) -> None:
        """No seam may be added or removed without updating the checklist.

        ``agent_harness.plugins.loader`` is deliberately excluded: it is this
        plan's own module, not a swap target.
        """
        found = _resolved_modules_in_source() - {"agent_harness.plugins.loader"}

        assert found == set(RESOLVED_MODULES)

    def test_the_documented_symbol_list_matches_the_code(self) -> None:
        """Every symbol the harness reads off a resolved module is listed."""
        import re

        found = set(re.findall(r"_module\.([A-Za-z_]+)", _harness_source()))

        assert found == set(RESOLVED_SYMBOLS)

    def test_the_plan_checklist_names_every_seam(self) -> None:
        """The written checklist cannot drift from the code it describes."""
        plan = (
            Path(__file__).resolve().parent.parent
            / "planning"
            / "plan-4-interface"
            / "plan.md"
        ).read_text(encoding="utf-8")
        section = plan.split("### I1 swap checklist", 1)

        assert len(section) == 2, "plan.md lost its '### I1 swap checklist' section"
        checklist = section[1]
        missing = [
            name
            for name in sorted(RESOLVED_MODULES | RESOLVED_SYMBOLS)
            if name not in checklist
        ]

        assert missing == [], f"checklist is missing: {missing}"

    def test_no_stub_module_name_is_hard_coded_in_the_root(self) -> None:
        """The swap must not need edits: no ``_p4_stubs`` reference ships."""
        assert "_p4_stubs" not in _harness_source()

    def test_every_resolved_module_is_a_shipped_package_module(self) -> None:
        """I1 swapped what the names resolve to; the names must resolve for real."""
        import importlib
        import pathlib

        package_root = (
            pathlib.Path(importlib.import_module("agent_harness").__file__ or "")
            .resolve()
            .parent
        )

        for dotted in sorted(RESOLVED_MODULES):
            module = importlib.import_module(dotted)
            source = getattr(module, "__file__", None)

            assert module.__name__ == dotted
            assert source is not None, f"{dotted} is not a real module"
            assert package_root in pathlib.Path(source).resolve().parents


# ---------------------------------------------------------------------------
# Sub-phase 5.2 - programmatic API documentation
# ---------------------------------------------------------------------------

PUBLIC_METHODS = (
    "__init__",
    "__enter__",
    "__exit__",
    "from_config",
    "run",
    "plan",
    "register_tool",
    "list_tools",
    "set_progress",
    "close",
)


class TestApiDocumentation:
    """Plan 5.2 exit criterion: every public method documents its own usage."""

    def _methods(self) -> dict[str, Any]:
        """The public surface of ``AgentHarness``, keyed by name."""
        import ast

        found: dict[str, Any] = {}
        for node in ast.walk(ast.parse(_harness_source())):
            if isinstance(node, ast.ClassDef) and node.name == "AgentHarness":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        found[item.name] = item
        return found

    def test_every_public_method_has_a_usage_example(self) -> None:
        """No public entry point ships without one."""
        import ast

        methods = self._methods()
        missing = [
            name
            for name in PUBLIC_METHODS
            if "Example:" not in (ast.get_docstring(methods[name]) or "")
        ]

        assert missing == [], f"missing usage example: {missing}"

    def test_every_public_method_has_a_docstring(self) -> None:
        """The example check would be meaningless without this one."""
        import ast

        methods = self._methods()
        missing = [
            name for name in PUBLIC_METHODS if not ast.get_docstring(methods[name])
        ]

        assert missing == [], f"missing docstring: {missing}"

    def test_the_module_docstring_shows_the_quick_start(self) -> None:
        """The package itself documents the shortest useful program."""
        import agent_harness

        doc = agent_harness.__doc__ or ""

        assert "AgentHarness" in doc
        assert "run(" in doc

    def test_the_pure_api_doctests_actually_pass(self) -> None:
        """Examples needing no Plan 1-3 module are executed, not skipped."""
        import doctest

        import agent_harness

        results = doctest.testmod(agent_harness, verbose=False)

        assert results.failed == 0, f"{results.failed} doctest failure(s)"
        assert results.attempted > 0, "no doctest ran, so the examples are not real"

    def test_every_skipped_example_says_why(self) -> None:
        """A skipped doctest must name I1, so it is un-skipped at the swap.

        These examples construct a harness, which needs the real Plan 1-3
        modules. They stay skipped until integration step I1, and the marker is
        what keeps that debt visible rather than silently permanent.
        """
        skips = [
            line for line in _harness_source().splitlines() if "doctest: +SKIP" in line
        ]
        unexplained = [line.strip() for line in skips if "needs I1" not in line]

        assert skips, "expected composition examples to be present"
        assert unexplained == [], f"skipped without a reason: {unexplained}"


# ---------------------------------------------------------------------------
# Sub-phase 5.3 - config-surface verification
# ---------------------------------------------------------------------------

#: Every key in the SPEC-006 1 config.yaml schema, by section.
CONFIG_SCHEMA = {
    "llm": (
        "provider",
        "model",
        "fallback_model",
        "api_key_env",
        "base_url",
        "max_tokens",
        "temperature",
        "timeout",
        "max_retries",
        "cost_per_1k_tokens",
    ),
    "execution": (
        "max_steps",
        "step_timeout",
        "max_retries",
        "retry_backoff",
        "retry_base_delay",
        "enable_replan",
        "abort_on_critical_failure",
        "output_dir",
        "temp_dir",
    ),
    "search": ("provider", "api_key_env", "max_results"),
    "security": (
        "sandbox_code",
        "code_timeout",
        "max_output_bytes",
        "network_in_code",
        "allow_shell",
        "sensitive_patterns",
    ),
    "logging": ("level", "file", "format", "console"),
    "plugins": ("dirs", "auto_load"),
}

#: Keys this plan *reads*. Writing the audit as a test found three that an
#: informal reading missed: ``llm.provider``, ``search.provider`` and
#: ``search.api_key_env`` are all read by the startup warning that reports
#: transmitted credentials (SPEC-005 4), which cannot name the environment
#: variables at risk without knowing which providers are configured.
READ_BY_P4 = frozenset(
    {
        "execution.enable_replan",
        "execution.output_dir",
        "execution.temp_dir",
        "llm.api_key_env",
        "llm.provider",
        "plugins.auto_load",
        "plugins.dirs",
        "search.api_key_env",
        "search.provider",
        "security.allow_shell",
    }
)

#: Keys this plan *writes* from a command line flag (SPEC-005 2). Two of them -
#: ``execution.max_steps`` and ``logging.level`` - are written but never read
#: here; the layers that consume them are P3 and P1 respectively.
OVERRIDDEN_BY_CLI = frozenset(
    {
        "execution.enable_replan",
        "execution.max_steps",
        "execution.output_dir",
        "logging.level",
    }
)

#: The union: every key P4 touches at all. The remaining 22 are passed through
#: untouched, which is the correct outcome for a composition root - P4 must not
#: interpret another layer's configuration.
CONSUMED_BY_P4 = READ_BY_P4 | OVERRIDDEN_BY_CLI


def _owned_sources() -> str:
    """Concatenate every source file this plan owns."""
    root = Path(__file__).resolve().parent.parent
    parts = [
        root / "agent_harness" / "harness.py",
        root / "agent_harness" / "__main__.py",
        root / "agent_harness" / "plugins" / "loader.py",
    ]
    return "\n".join(p.read_text(encoding="utf-8") for p in parts)


class TestConfigSurface:
    """Plan 5.3: every config key is consumed by someone, and we know who."""

    def test_the_schema_is_the_documented_one(self) -> None:
        """Guard the audit itself against a stale key list."""
        assert sum(len(v) for v in CONFIG_SCHEMA.values()) == 34
        assert set(CONFIG_SCHEMA) == {
            "llm",
            "execution",
            "search",
            "security",
            "logging",
            "plugins",
        }

    def test_every_consumed_key_is_a_real_schema_key(self) -> None:
        """No phantom keys in the matrix."""
        valid = {f"{s}.{k}" for s, keys in CONFIG_SCHEMA.items() for k in keys}
        bogus = sorted(CONSUMED_BY_P4 - valid)

        assert bogus == [], f"not in SPEC-006 1: {bogus}"

    def test_the_code_reads_exactly_the_documented_keys(self) -> None:
        """Attribute access and dotted lookups, both of them."""
        import re

        source = _owned_sources()
        valid = {f"{s}.{k}" for s, keys in CONFIG_SCHEMA.items() for k in keys}
        attribute = {f"{a}.{b}" for a, b in re.findall(r"config\.(\w+)\.(\w+)", source)}
        dotted = set(re.findall(r'get\(\s*"(\w+\.\w+)"', source))

        assert (attribute | dotted) & valid == set(READ_BY_P4)

    def test_every_consumed_key_is_accounted_for(self) -> None:
        """The matrix covers 12 of 34 keys; the other 22 are pass-through."""
        assert len(CONSUMED_BY_P4) == 12
        assert len(OVERRIDDEN_BY_CLI) == 4
        assert READ_BY_P4 - OVERRIDDEN_BY_CLI  # reads that are not CLI targets

    def test_the_cli_overrides_cover_the_documented_four(self) -> None:
        """SPEC-005 2 lists four overridable settings; all four are wired."""
        from agent_harness.__main__ import OVERRIDE_PATHS

        assert set(OVERRIDE_PATHS.values()) == {
            "execution.output_dir",
            "execution.max_steps",
            "logging.level",
        }
        # --no-fallback writes the fourth, execution.enable_replan, in
        # collect_overrides because it is a flag rather than a value.
        from agent_harness.__main__ import collect_overrides, parse_args

        overrides = collect_overrides(parse_args(["--no-fallback", "x"]))

        assert overrides["execution.enable_replan"] is False

    def test_llm_and_search_tuning_is_never_interpreted(self) -> None:
        """P4 reads provider and key *names* only, never tuning.

        Model, temperature, timeouts and result counts belong to P1 and P2. The
        provider and ``*_env`` names are the narrow exception: the startup
        warning has to know which providers are live and which environment
        variables they would transmit.
        """
        forbidden = {
            "llm.model",
            "llm.fallback_model",
            "llm.base_url",
            "llm.max_tokens",
            "llm.temperature",
            "llm.timeout",
            "llm.max_retries",
            "llm.cost_per_1k_tokens",
            "search.max_results",
            "security.sandbox_code",
            "security.code_timeout",
            "security.max_output_bytes",
            "security.network_in_code",
            "security.sensitive_patterns",
            "execution.step_timeout",
            "execution.max_retries",
            "execution.retry_backoff",
            "execution.retry_base_delay",
            "execution.abort_on_critical_failure",
            "logging.file",
            "logging.format",
            "logging.console",
        }

        assert not (forbidden & set(READ_BY_P4))
        assert len(forbidden) == 22  # the pass-through half of the matrix


# ---------------------------------------------------------------------------
# Sub-phase 5.4 - troubleshooting alignment
# ---------------------------------------------------------------------------


class TestTroubleshootingMessages:
    """Each Developer README troubleshooting entry has a concrete P4 signal.

    The README documents a symptom; these tests pin the message, event name or
    exit code this plan actually produces for it, so the documented fix stays
    true.
    """

    def test_missing_api_key_names_the_variable_and_the_fix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """README: ``OPENAI_API_KEY not set``."""
        from agent_harness.harness import AgentHarness

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        logger = doubles.RecordingLogger()

        AgentHarness(doubles.Config(), logger=logger)

        records = [r for r in logger.records if r["event"] == "api_key_missing"]

        assert len(records) == 1
        assert records[0]["level"] == "WARNING"
        assert "OPENAI_API_KEY" in str(records[0])
        assert "cp .env.example .env" in records[0]["remediation"]

    def test_wkhtmltopdf_missing_is_informational_not_fatal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """README: ``wkhtmltopdf not found`` (PDF export fails)."""
        import shutil

        from agent_harness.harness import AgentHarness

        monkeypatch.setattr(shutil, "which", lambda _name: None)
        logger = doubles.RecordingLogger()

        harness = AgentHarness(doubles.Config(), logger=logger)

        records = [r for r in logger.records if r["event"] == "pdf_export_degraded"]

        assert len(records) == 1
        assert records[0]["level"] == "INFO"
        assert "wkhtmltopdf" in str(records[0])
        assert harness is not None  # construction still succeeded

    def test_shell_enabled_is_warned_about(self) -> None:
        """Not in the README, but the same class of surprise: an opt-in risk."""
        from agent_harness.harness import AgentHarness

        config = doubles.Config()
        config.security.allow_shell = True
        logger = doubles.RecordingLogger()

        AgentHarness(config, logger=logger)

        records = [r for r in logger.records if r["event"] == "shell_execution_enabled"]

        assert len(records) == 1
        assert records[0]["level"] == "WARNING"

    def test_a_missing_module_names_the_module(self) -> None:
        """README: ``ModuleNotFoundError: No module named 'agent_harness'``.

        The lazy surface must not fail silently: the ImportError names the module
        that could not be imported, which is the difference between a debuggable
        message and a guess.
        """
        import agent_harness

        # A variable rather than a literal: ruff B018 rejects a bare attribute
        # expression and B009 rejects getattr with a constant name.
        absent = "DefinitelyNotExported"
        with pytest.raises(AttributeError) as missing:
            getattr(agent_harness, absent)

        assert "DefinitelyNotExported" in str(missing.value)

    def test_too_many_steps_has_a_flag_and_a_validated_one(self) -> None:
        """README: ``Agent produces too many steps``.

        The fix is ``--max-steps``; the guard is that a nonsense value is a usage
        error rather than a silent no-op.
        """
        from agent_harness.__main__ import parse_args

        assert parse_args(["--max-steps", "3", "x"]).max_steps == 3

        with pytest.raises(SystemExit) as usage:
            parse_args(["--max-steps", "0", "x"])

        assert usage.value.code == 2

    def test_rate_limits_and_hangs_are_surfaced_not_swallowed(self) -> None:
        """README: ``Rate limit exceeded`` and ``Code execution hangs``.

        Both are owned by P3 (recovery cascade) and P2 (``step_timeout``)
        respectively. What this plan guarantees is the surfacing: the failure
        lands in ``HarnessResult.errors`` and the exit code distinguishes a
        partial from a failed run, so neither is invisible to a caller.
        """
        from agent_harness.__main__ import EXIT_FAILED, EXIT_PARTIAL, STATUS_EXIT_CODES

        assert STATUS_EXIT_CODES["partial"] == EXIT_PARTIAL
        assert STATUS_EXIT_CODES["failed"] == EXIT_FAILED
        assert EXIT_PARTIAL != EXIT_FAILED
