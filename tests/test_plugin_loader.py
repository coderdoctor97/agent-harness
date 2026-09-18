"""Unit tests for the Plan 4 plugin loader.

Owned by Plan 4 (SPEC-000 § 3.4). Deterministic: plugin fixtures are written to
``tmp_path`` so no test depends on the repository layout except the two that
deliberately exercise the shipped examples.

Spec: SPEC-005 § 3 · SPEC-002 § 1 · SPEC-001 § 2.4
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import _p4_doubles as doubles
import pytest


@pytest.fixture(autouse=True)
def _real_tools() -> Iterator[None]:
    """Assert the plugin tests run against Plan 2's shipped ``BaseTool``.

    These tests import ``agent_harness.tools.base`` from the plugin files they
    write, so the fixture pins that the real module is the one in play (I1).
    """
    import agent_harness.tools as tools_module

    assert tools_module.BaseTool is doubles.BaseTool
    yield


HELLO_PLUGIN = '''"""A minimal example plugin."""

from agent_harness.tools.base import BaseTool, ToolResult


class HelloTool(BaseTool):
    @property
    def name(self) -> str:
        return "hello"

    @property
    def description(self) -> str:
        return "Says hello. Input: {name: str}. Output: str."

    def execute(self, input_data, context):
        name = input_data.get('name', 'World')
        return ToolResult(success=True, output=f"Hello, {name}!")
'''


def write_plugin(directory: Path, filename: str, source: str) -> Path:
    """Write a plugin source file and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(source, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Sub-phase 3.1 — directory scanning and module loading
# ---------------------------------------------------------------------------


class TestPluginScanning:
    """SPEC-005 § 3 steps 1-2."""

    def test_discovers_python_files_in_a_directory(self, tmp_path: Path) -> None:
        """Every ``*.py`` file in the directory is found."""
        from agent_harness.plugins.loader import _iter_plugin_files

        write_plugin(tmp_path, "alpha.py", HELLO_PLUGIN)
        write_plugin(tmp_path, "beta.py", HELLO_PLUGIN)

        found = [p.name for p in _iter_plugin_files([str(tmp_path)])]

        assert found == ["alpha.py", "beta.py"]

    def test_scan_order_is_deterministic(self, tmp_path: Path) -> None:
        """Sorted order, repeated identically across calls and directories."""
        from agent_harness.plugins.loader import _iter_plugin_files

        first_dir, second_dir = tmp_path / "a", tmp_path / "b"
        write_plugin(second_dir, "zeta.py", HELLO_PLUGIN)
        write_plugin(first_dir, "mid.py", HELLO_PLUGIN)
        write_plugin(first_dir, "alpha.py", HELLO_PLUGIN)

        dirs = [str(second_dir), str(first_dir)]
        once = [p.name for p in _iter_plugin_files(dirs)]
        again = [p.name for p in _iter_plugin_files(dirs)]

        # Directories are visited in argument order; files inside one are sorted.
        assert once == ["zeta.py", "alpha.py", "mid.py"]
        assert again == once
        assert [p.name for p in _iter_plugin_files([str(first_dir)])] == [
            "alpha.py",
            "mid.py",
        ]

    def test_nonexistent_directory_is_skipped_silently(self, tmp_path: Path) -> None:
        """A missing directory is not an error and produces nothing."""
        from agent_harness.plugins.loader import _iter_plugin_files

        write_plugin(tmp_path, "real.py", HELLO_PLUGIN)
        missing = tmp_path / "does-not-exist"

        found = [p.name for p in _iter_plugin_files([str(missing), str(tmp_path)])]

        assert found == ["real.py"]

    def test_nonexistent_directory_is_logged_at_debug(self, tmp_path: Path) -> None:
        """Silent to the user, visible in the log."""
        from agent_harness.plugins.loader import _iter_plugin_files

        logger = doubles.RecordingLogger()
        missing = tmp_path / "nope"

        list(_iter_plugin_files([str(missing)], logger=logger))

        skipped = [r for r in logger.records if r["event"] == "plugin_dir_skipped"]
        assert len(skipped) == 1
        assert skipped[0]["level"] == "DEBUG"

    def test_empty_directory_list_yields_nothing(self) -> None:
        """No directories means no plugins."""
        from agent_harness.plugins.loader import _iter_plugin_files

        assert list(_iter_plugin_files([])) == []

    def test_tilde_is_expanded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``~/.agent_harness/plugins`` from the default config resolves."""
        from agent_harness.plugins.loader import _iter_plugin_files

        monkeypatch.setenv("HOME", str(tmp_path))
        write_plugin(
            tmp_path / ".agent_harness" / "plugins", "home_tool.py", HELLO_PLUGIN
        )

        found = [p.name for p in _iter_plugin_files(["~/.agent_harness/plugins"])]

        assert found == ["home_tool.py"]

    def test_private_and_package_files_are_ignored(self, tmp_path: Path) -> None:
        """``__init__.py`` and ``_helpers.py`` are not plugins."""
        from agent_harness.plugins.loader import _iter_plugin_files

        write_plugin(tmp_path, "__init__.py", "")
        write_plugin(tmp_path, "_helpers.py", "VALUE = 1\n")
        write_plugin(tmp_path, "real_tool.py", HELLO_PLUGIN)

        found = [p.name for p in _iter_plugin_files([str(tmp_path)])]

        assert found == ["real_tool.py"]

    def test_a_file_is_not_treated_as_a_directory(self, tmp_path: Path) -> None:
        """Pointing at a file rather than a directory yields nothing."""
        from agent_harness.plugins.loader import _iter_plugin_files

        path = write_plugin(tmp_path, "real_tool.py", HELLO_PLUGIN)

        assert list(_iter_plugin_files([str(path)])) == []

    def test_modules_load_under_synthetic_names(self, tmp_path: Path) -> None:
        """SPEC-005 § 3 step 2 — ``agent_harness_plugin_<stem>``."""
        import sys

        from agent_harness.plugins.loader import _load_plugin_module

        path = write_plugin(tmp_path, "my_tool.py", HELLO_PLUGIN)

        module = _load_plugin_module(path)

        assert module.__name__ == "agent_harness_plugin_my_tool"
        assert sys.modules["agent_harness_plugin_my_tool"] is module

    def test_loaded_module_exposes_its_classes(self, tmp_path: Path) -> None:
        """The loaded module really was executed."""
        from agent_harness.plugins.loader import _load_plugin_module

        path = write_plugin(tmp_path, "my_tool.py", HELLO_PLUGIN)

        module = _load_plugin_module(path)

        assert hasattr(module, "HelloTool")

    def test_a_syntax_error_becomes_an_agent_error_not_a_crash(
        self, tmp_path: Path
    ) -> None:
        """Loading arbitrary user code must never take down startup."""
        from agent_harness.plugins.loader import _load_plugin_module

        path = write_plugin(tmp_path, "broken.py", "def (:\n")

        error = _load_plugin_module(path)

        assert isinstance(error, doubles.AgentError)
        assert error.code == "PLUGIN_LOAD_FAILED"
        assert error.recoverable is False
        assert "broken.py" in error.message

    def test_an_import_error_is_isolated(self, tmp_path: Path) -> None:
        """A plugin importing something unavailable does not abort discovery."""
        from agent_harness.plugins.loader import _load_plugin_module

        path = write_plugin(
            tmp_path, "needs_missing.py", "import definitely_not_installed_xyz\n"
        )

        error = _load_plugin_module(path)

        assert isinstance(error, doubles.AgentError)
        assert error.code == "PLUGIN_LOAD_FAILED"


class TestDiscoverToolsSignature:
    """SPEC-005 § 3 — the frozen entry point."""

    def test_signature_matches_the_spec(self) -> None:
        """Argument names, order and defaults are exactly as FROZEN."""
        import inspect

        from agent_harness.plugins.loader import discover_tools

        signature = inspect.signature(discover_tools)
        params = list(signature.parameters)

        assert params == ["plugin_dirs", "config", "llm_client", "logger"]
        assert (
            signature.parameters["plugin_dirs"].kind
            is inspect.Parameter.POSITIONAL_OR_KEYWORD
        )
        for name in ("config", "llm_client", "logger"):
            assert signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
            assert signature.parameters[name].default is None

    def test_returns_a_tuple_of_tools_and_errors(self) -> None:
        """The second element is always present, even with nothing to scan."""
        from agent_harness.plugins.loader import discover_tools

        result = discover_tools([])

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result == ([], [])

    def test_the_package_re_exports_discover_tools(self) -> None:
        """``agent_harness.plugins.discover_tools`` is the public import site."""
        import agent_harness.plugins as plugins_package
        from agent_harness.plugins.loader import discover_tools

        assert plugins_package.discover_tools is discover_tools


# ---------------------------------------------------------------------------
# Sub-phase 3.2 — class detection and instantiation conventions
# ---------------------------------------------------------------------------

ABSTRACT_PLUGIN = '''"""Defines an incomplete tool that must be skipped."""

from agent_harness.tools.base import BaseTool, ToolResult


class IncompleteTool(BaseTool):
    @property
    def name(self) -> str:
        return "incomplete"

    # description and execute are never implemented: still abstract.
'''

NON_TOOL_PLUGIN = '''"""Defines classes that are not tools at all."""


class NotATool:
    def run(self) -> str:
        return "nope"
'''

ZERO_ARG_PLUGIN = '''"""A tool with a zero-argument constructor."""

from agent_harness.tools.base import BaseTool, ToolResult


class ZeroArgTool(BaseTool):
    @property
    def name(self) -> str:
        return "zero_arg"

    @property
    def description(self) -> str:
        return "Zero-arg tool. Input: {}. Output: str."

    def execute(self, input_data, context):
        return ToolResult(success=True, output="ok")
'''

CONFIG_PLUGIN = '''"""A tool that asks for the config."""

from agent_harness.tools.base import BaseTool, ToolResult


class ConfigTool(BaseTool):
    def __init__(self, config):
        self.config = config

    @property
    def name(self) -> str:
        return "config_tool"

    @property
    def description(self) -> str:
        return "Config-aware tool. Input: {}. Output: str."

    def execute(self, input_data, context):
        return ToolResult(success=True, output=str(self.config))
'''

LLM_PLUGIN = '''"""A tool that asks for the LLM client."""

from agent_harness.tools.base import BaseTool, ToolResult


class LlmTool(BaseTool):
    def __init__(self, llm_client):
        self.llm_client = llm_client

    @property
    def name(self) -> str:
        return "llm_tool"

    @property
    def description(self) -> str:
        return "LLM-aware tool. Input: {}. Output: str."

    def execute(self, input_data, context):
        return ToolResult(success=True, output="ok")
'''

BOTH_PLUGIN = '''"""A tool that asks for both collaborators."""

from agent_harness.tools.base import BaseTool, ToolResult


class BothTool(BaseTool):
    def __init__(self, config, llm_client):
        self.config = config
        self.llm_client = llm_client

    @property
    def name(self) -> str:
        return "both_tool"

    @property
    def description(self) -> str:
        return "Both-aware tool. Input: {}. Output: str."

    def execute(self, input_data, context):
        return ToolResult(success=True, output="ok")
'''

SETTINGS_PLUGIN = '''"""A tool with literal settings."""

from agent_harness.tools.base import BaseTool, ToolResult


class SettingsTool(BaseTool):
    PLUGIN_SETTINGS = {"db_path": "./data/app.db", "timeout": 30}

    def __init__(self, db_path, timeout):
        self.db_path = db_path
        self.timeout = timeout

    @property
    def name(self) -> str:
        return "settings_tool"

    @property
    def description(self) -> str:
        return "Settings tool. Input: {}. Output: str."

    def execute(self, input_data, context):
        return ToolResult(success=True, output=self.db_path)
'''

UNINSTANTIABLE_PLUGIN = '''"""A tool that cannot be built."""

from agent_harness.tools.base import BaseTool, ToolResult


class NeedsUnknownTool(BaseTool):
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url

    @property
    def name(self) -> str:
        return "needs_unknown"

    @property
    def description(self) -> str:
        return "Unbuildable tool. Input: {}. Output: str."

    def execute(self, input_data, context):
        return ToolResult(success=True, output="never")
'''

RAISING_CTOR_PLUGIN = '''"""A tool whose constructor raises."""

from agent_harness.tools.base import BaseTool, ToolResult


class ExplodingTool(BaseTool):
    def __init__(self):
        raise RuntimeError("constructor exploded")

    @property
    def name(self) -> str:
        return "exploding"

    @property
    def description(self) -> str:
        return "Exploding tool. Input: {}. Output: str."

    def execute(self, input_data, context):
        return ToolResult(success=True, output="never")
'''

MULTI_PLUGIN = '''"""Two tools in one file."""

from agent_harness.tools.base import BaseTool, ToolResult


class FirstTool(BaseTool):
    @property
    def name(self) -> str:
        return "first"

    @property
    def description(self) -> str:
        return "First tool. Input: {}. Output: str."

    def execute(self, input_data, context):
        return ToolResult(success=True, output="1")


class SecondTool(BaseTool):
    @property
    def name(self) -> str:
        return "second"

    @property
    def description(self) -> str:
        return "Second tool. Input: {}. Output: str."

    def execute(self, input_data, context):
        return ToolResult(success=True, output="2")
'''


class TestClassDetection:
    """SPEC-005 § 3 step 3."""

    def test_concrete_tool_is_discovered(self, tmp_path: Path) -> None:
        """A concrete ``BaseTool`` subclass becomes a usable instance."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "zero.py", ZERO_ARG_PLUGIN)

        tools, errors = discover_tools([str(tmp_path)])

        assert errors == []
        assert [t.name for t in tools] == ["zero_arg"]
        assert isinstance(tools[0], doubles.BaseTool)

    def test_abstract_subclass_is_skipped(self, tmp_path: Path) -> None:
        """A class with unimplemented abstract methods is not instantiated."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "abstract.py", ABSTRACT_PLUGIN)

        tools, errors = discover_tools([str(tmp_path)])

        assert tools == []
        assert errors == []  # skipping an abstract class is not a failure

    def test_base_tool_itself_is_skipped(self, tmp_path: Path) -> None:
        """``obj is not BaseTool`` from the spec."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(
            tmp_path,
            "only_base.py",
            "from agent_harness.tools.base import BaseTool\n\n__all__ = ['BaseTool']\n",
        )

        tools, errors = discover_tools([str(tmp_path)])

        assert tools == []
        assert errors == []

    def test_non_tool_classes_are_ignored(self, tmp_path: Path) -> None:
        """A class that is not a ``BaseTool`` is not a plugin."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "notool.py", NON_TOOL_PLUGIN)

        tools, errors = discover_tools([str(tmp_path)])

        assert tools == []
        assert errors == []

    def test_several_tools_in_one_file_are_all_collected(self, tmp_path: Path) -> None:
        """Discovery is per class, not per file."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "multi.py", MULTI_PLUGIN)

        tools, _ = discover_tools([str(tmp_path)])

        assert sorted(t.name for t in tools) == ["first", "second"]

    def test_discovery_order_is_stable(self, tmp_path: Path) -> None:
        """Classes are ordered by name, not by ``getmembers`` luck."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "multi.py", MULTI_PLUGIN)

        first, _ = discover_tools([str(tmp_path)])
        second, _ = discover_tools([str(tmp_path)])

        assert [t.name for t in first] == [t.name for t in second]
        assert [t.name for t in second] == ["first", "second"]


class TestInstantiationConventions:
    """SPEC-005 § 3 step 4 — the injection matrix."""

    def test_config_is_injected_by_keyword(self, tmp_path: Path) -> None:
        """A constructor parameter named ``config`` receives the config."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "cfg.py", CONFIG_PLUGIN)
        config = doubles.Config()

        tools, errors = discover_tools([str(tmp_path)], config=config)

        assert errors == []
        assert tools[0].config is config

    def test_llm_client_is_injected_by_keyword(self, tmp_path: Path) -> None:
        """A constructor parameter named ``llm_client`` receives the client."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "llm.py", LLM_PLUGIN)
        client = doubles.MockLLMClient()

        tools, errors = discover_tools([str(tmp_path)], llm_client=client)

        assert errors == []
        assert tools[0].llm_client is client

    def test_both_collaborators_are_injected(self, tmp_path: Path) -> None:
        """A constructor asking for both gets both."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "both.py", BOTH_PLUGIN)
        config, client = doubles.Config(), doubles.MockLLMClient()

        tools, _ = discover_tools([str(tmp_path)], config=config, llm_client=client)

        assert tools[0].config is config
        assert tools[0].llm_client is client

    def test_plugin_settings_supply_literal_kwargs(self, tmp_path: Path) -> None:
        """``PLUGIN_SETTINGS`` feeds the remaining required parameters."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "settings.py", SETTINGS_PLUGIN)

        tools, errors = discover_tools([str(tmp_path)])

        assert errors == []
        assert tools[0].db_path == "./data/app.db"
        assert tools[0].timeout == 30

    def test_a_missing_required_parameter_is_an_error(self, tmp_path: Path) -> None:
        """No ``PLUGIN_SETTINGS`` and no injection point means it cannot be built."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "needs.py", UNINSTANTIABLE_PLUGIN)

        tools, errors = discover_tools([str(tmp_path)])

        assert tools == []
        assert len(errors) == 1
        assert errors[0].code == "PLUGIN_LOAD_FAILED"
        assert "webhook_url" in errors[0].message

    def test_a_raising_constructor_is_contained(self, tmp_path: Path) -> None:
        """An exception in ``__init__`` is contained."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "boom.py", RAISING_CTOR_PLUGIN)

        tools, errors = discover_tools([str(tmp_path)])

        assert tools == []
        assert len(errors) == 1
        assert "constructor exploded" in errors[0].message

    def test_one_bad_plugin_does_not_stop_the_others(self, tmp_path: Path) -> None:
        """Discovery continues past a failure and reports both outcomes."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "a_good.py", ZERO_ARG_PLUGIN)
        write_plugin(tmp_path, "b_bad.py", UNINSTANTIABLE_PLUGIN)
        write_plugin(tmp_path, "c_good.py", MULTI_PLUGIN)

        tools, errors = discover_tools([str(tmp_path)])

        assert sorted(t.name for t in tools) == ["first", "second", "zero_arg"]
        assert len(errors) == 1

    def test_optional_parameters_need_no_settings(self, tmp_path: Path) -> None:
        """A defaulted parameter is not treated as required."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(
            tmp_path,
            "optional.py",
            '''"""A tool with an optional parameter."""

from agent_harness.tools.base import BaseTool, ToolResult


class OptionalTool(BaseTool):
    def __init__(self, label="default"):
        self.label = label

    @property
    def name(self) -> str:
        return "optional_tool"

    @property
    def description(self) -> str:
        return "Optional tool. Input: {}. Output: str."

    def execute(self, input_data, context):
        return ToolResult(success=True, output=self.label)
''',
        )

        tools, errors = discover_tools([str(tmp_path)])

        assert errors == []
        assert tools[0].label == "default"

    def test_an_uninspectable_signature_falls_back_to_zero_arg(
        self, tmp_path: Path
    ) -> None:
        """A C-level ``__init__`` has no signature; try building it anyway."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(
            tmp_path,
            "builtin_init.py",
            '''"""A tool whose __init__ is a slot wrapper with no signature."""

from agent_harness.tools.base import BaseTool, ToolResult


class BuiltinInitTool(BaseTool):
    __init__ = object.__init__

    @property
    def name(self) -> str:
        return "builtin_init"

    @property
    def description(self) -> str:
        return "Opaque tool. Input: {}. Output: str."

    def execute(self, input_data, context):
        return ToolResult(success=True, output="ok")
''',
        )

        tools, errors = discover_tools([str(tmp_path)])

        assert errors == []
        assert [t.name for t in tools] == ["builtin_init"]


# ---------------------------------------------------------------------------
# Sub-phase 3.3 — isolation, collisions, auto_load
# ---------------------------------------------------------------------------

SYNTAX_ERROR_PLUGIN = '''"""A plugin that does not even parse."""


class Broken(BaseTool:
    pass
'''

IMPORT_ERROR_PLUGIN = '''"""A plugin importing a module that does not exist."""

import agent_harness_plugin_does_not_exist  # noqa: F401
'''

RAISING_NAME_PLUGIN = '''"""A tool whose name property raises."""

from agent_harness.tools.base import BaseTool, ToolResult


class BadNameTool(BaseTool):
    @property
    def name(self) -> str:
        raise RuntimeError("name blew up")

    @property
    def description(self) -> str:
        return "Bad name. Input: {}. Output: str."

    def execute(self, input_data, context):
        return ToolResult(success=True, output="ok")
'''


def hello_tool_named(name: str) -> str:
    """Plugin source for a zero-arg tool with a chosen ``name``."""
    return f'''"""A tool called {name}."""

from agent_harness.tools.base import BaseTool, ToolResult


class NamedTool(BaseTool):
    @property
    def name(self) -> str:
        return "{name}"

    @property
    def description(self) -> str:
        return "Named tool. Input: {{}}. Output: str."

    def execute(self, input_data, context):
        return ToolResult(success=True, output="{name}")
'''


class TestPoisonedPlugins:
    """SPEC-005 § 3 step 6 — a bad plugin is loud but harmless."""

    def test_syntax_error_is_contained(self, tmp_path: Path) -> None:
        """A file that will not parse yields one error and no crash."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "broken.py", SYNTAX_ERROR_PLUGIN)

        tools, errors = discover_tools([str(tmp_path)])

        assert tools == []
        assert len(errors) == 1
        assert errors[0].code == "PLUGIN_LOAD_FAILED"
        assert errors[0].recoverable is False
        assert "broken.py" in errors[0].message

    def test_import_error_is_contained(self, tmp_path: Path) -> None:
        """A failing module-level import does the same."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "missing.py", IMPORT_ERROR_PLUGIN)

        tools, errors = discover_tools([str(tmp_path)])

        assert tools == []
        assert len(errors) == 1
        assert "missing.py" in errors[0].message

    def test_a_raising_name_property_is_contained(self, tmp_path: Path) -> None:
        """The tool instance itself may be hostile; the log line must not be."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "badname.py", RAISING_NAME_PLUGIN)

        tools, errors = discover_tools([str(tmp_path)])

        assert tools == []
        assert len(errors) == 1
        assert "name blew up" in errors[0].message

    def test_every_plugin_broken_still_returns(self, tmp_path: Path) -> None:
        """Discovery never raises, however bad the directory is."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "a.py", SYNTAX_ERROR_PLUGIN)
        write_plugin(tmp_path, "b.py", IMPORT_ERROR_PLUGIN)
        write_plugin(tmp_path, "c.py", RAISING_NAME_PLUGIN)
        write_plugin(tmp_path, "d.py", RAISING_CTOR_PLUGIN)

        tools, errors = discover_tools([str(tmp_path)])

        assert tools == []
        assert len(errors) == 4

    def test_good_plugins_survive_the_bad_ones(self, tmp_path: Path) -> None:
        """One poisoned file costs its own tool only."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "a_bad.py", SYNTAX_ERROR_PLUGIN)
        write_plugin(tmp_path, "b_good.py", ZERO_ARG_PLUGIN)

        tools, errors = discover_tools([str(tmp_path)])

        assert [t.name for t in tools] == ["zero_arg"]
        assert len(errors) == 1

    def test_failed_load_leaves_no_module_behind(self, tmp_path: Path) -> None:
        """The half-built synthetic module is cleaned out of ``sys.modules``."""
        from agent_harness.plugins.loader import MODULE_PREFIX, discover_tools

        write_plugin(tmp_path, "broken.py", SYNTAX_ERROR_PLUGIN)

        discover_tools([str(tmp_path)])

        assert f"{MODULE_PREFIX}broken" not in sys.modules

    def test_failure_is_logged_as_plugin_failed(self, tmp_path: Path) -> None:
        """SPEC-006 § 6.1 requires a ``plugin_failed`` WARNING."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "broken.py", SYNTAX_ERROR_PLUGIN)
        logger = doubles.RecordingLogger()

        discover_tools([str(tmp_path)], logger=logger)

        failed = [r for r in logger.records if r["event"] == "plugin_failed"]
        assert len(failed) == 1
        assert failed[0]["level"] == "WARNING"


class TestCollisions:
    """SPEC-005 § 3 step 5 — built-ins win."""

    def test_a_plugin_cannot_displace_a_built_in(self, tmp_path: Path) -> None:
        """Registering a colliding name is refused and the built-in stays."""
        from agent_harness.plugins.loader import discover_tools, register_discovered

        write_plugin(tmp_path, "echo.py", hello_tool_named("echo"))
        tools, _ = discover_tools([str(tmp_path)])
        registry = doubles.ToolRegistry()
        builtin = doubles.StubEchoTool("echo")
        registry.register(builtin)
        logger = doubles.RecordingLogger()

        kept = register_discovered(registry, tools, logger=logger)

        assert kept == []
        assert registry.get("echo") is builtin

    def test_the_collision_is_logged_at_warning(self, tmp_path: Path) -> None:
        """The refusal is visible, never silent."""
        from agent_harness.plugins.loader import discover_tools, register_discovered

        write_plugin(tmp_path, "echo.py", hello_tool_named("echo"))
        tools, _ = discover_tools([str(tmp_path)])
        registry = doubles.ToolRegistry()
        registry.register(doubles.StubEchoTool("echo"))
        logger = doubles.RecordingLogger()

        register_discovered(registry, tools, logger=logger)

        clashes = [r for r in logger.records if r["event"] == "plugin_name_collision"]
        assert len(clashes) == 1
        assert clashes[0]["level"] == "WARNING"
        assert clashes[0]["tool"] == "echo"

    def test_a_free_name_is_registered(self, tmp_path: Path) -> None:
        """No collision means the tool joins the registry."""
        from agent_harness.plugins.loader import discover_tools, register_discovered

        write_plugin(tmp_path, "fresh.py", hello_tool_named("fresh"))
        tools, _ = discover_tools([str(tmp_path)])
        registry = doubles.ToolRegistry()

        kept = register_discovered(registry, tools)

        assert [t.name for t in kept] == ["fresh"]
        assert registry.get("fresh") is tools[0]

    def test_two_plugins_with_one_name_keep_the_first(self, tmp_path: Path) -> None:
        """The same rule settles plugin-versus-plugin clashes deterministically."""
        from agent_harness.plugins.loader import discover_tools, register_discovered

        write_plugin(tmp_path, "a_first.py", hello_tool_named("dupe"))
        write_plugin(tmp_path, "b_second.py", hello_tool_named("dupe"))
        tools, _ = discover_tools([str(tmp_path)])
        registry = doubles.ToolRegistry()

        kept = register_discovered(registry, tools)

        assert len(kept) == 1
        assert len(registry.list_tools()) == 1

    def test_a_built_in_registered_later_still_wins_nothing(self) -> None:
        """Registration order is what protects built-ins: they come first."""
        from agent_harness.plugins.loader import register_discovered

        registry = doubles.ToolRegistry()
        plugin_tool = doubles.StubEchoTool("late")

        kept = register_discovered(registry, [plugin_tool])

        assert [t.name for t in kept] == ["late"]


class TestAutoLoad:
    """SPEC-005 § 3 step 7 — the kill switch."""

    def test_auto_load_false_skips_scanning(self, tmp_path: Path) -> None:
        """Nothing is imported at all, so nothing can go wrong."""
        from agent_harness.plugins.loader import MODULE_PREFIX, discover_tools

        # A stem no other test uses: a successful load legitimately caches its
        # module in sys.modules, so the probe must be unique to this test.
        write_plugin(tmp_path, "autoload_probe.py", ZERO_ARG_PLUGIN)
        config = doubles.Config()
        config.plugins.auto_load = False

        tools, errors = discover_tools([str(tmp_path)], config=config)

        assert tools == []
        assert errors == []
        assert f"{MODULE_PREFIX}autoload_probe" not in sys.modules

    def test_auto_load_true_scans(self, tmp_path: Path) -> None:
        """The default is on, matching SPEC-006 § 1."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "zero.py", ZERO_ARG_PLUGIN)
        config = doubles.Config()
        assert config.plugins.auto_load is True

        tools, _ = discover_tools([str(tmp_path)], config=config)

        assert [t.name for t in tools] == ["zero_arg"]

    def test_no_config_means_scanning_happens(self, tmp_path: Path) -> None:
        """A caller with no config still gets the documented default."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "zero.py", ZERO_ARG_PLUGIN)

        tools, _ = discover_tools([str(tmp_path)])

        assert [t.name for t in tools] == ["zero_arg"]

    def test_a_broken_directory_is_only_a_debug_note(self, tmp_path: Path) -> None:
        """The default config names a directory most users never create."""
        from agent_harness.plugins.loader import discover_tools

        logger = doubles.RecordingLogger()

        tools, errors = discover_tools([str(tmp_path / "absent")], logger=logger)

        assert (tools, errors) == ([], [])
        skipped = [r for r in logger.records if r["event"] == "plugin_dir_skipped"]
        assert len(skipped) == 1
        assert skipped[0]["level"] == "DEBUG"


# ---------------------------------------------------------------------------
# Sub-phase 3.4 — the shipped examples
# ---------------------------------------------------------------------------

PLUGINS_DIR = Path(__file__).resolve().parent.parent / "plugins"


@pytest.fixture(name="demo_db")
def demo_db(tmp_path: Path) -> Iterator[Path]:
    """A throwaway SQLite database holding one small table."""
    import sqlite3

    path = tmp_path / "app.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        conn.executemany(
            "INSERT INTO users (name) VALUES (?)", [("Ada",), ("Grace",), ("Alan",)]
        )
    yield path


def _load_shipped(name: str) -> Any:
    """Load a shipped example by module name and return the module."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        f"shipped_{name}", PLUGINS_DIR / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestShippedExamples:
    """SPEC-005 § 3.1 — the two files Plan 4 ships in ``plugins/``."""

    def test_both_examples_exist(self) -> None:
        """The spec names both files exactly."""
        assert (PLUGINS_DIR / "example_hello.py").is_file()
        assert (PLUGINS_DIR / "example_database.py").is_file()

    def test_both_examples_are_discoverable(self) -> None:
        """They are real plugins: the loader finds and builds them."""
        from agent_harness.plugins.loader import discover_tools

        tools, errors = discover_tools([str(PLUGINS_DIR)])

        assert errors == []
        assert sorted(t.name for t in tools) == ["database_query", "hello"]

    def test_no_package_init_in_plugins_dir(self) -> None:
        """``plugins/`` is a scan target, not an importable package."""
        assert not (PLUGINS_DIR / "__init__.py").exists()

    def test_hello_matches_the_readme_shape(self) -> None:
        """Name, description and capabilities are the documented ones."""
        hello = _load_shipped("example_hello").HelloTool()

        assert hello.name == "hello"
        assert hello.description == (
            "Says hello with a custom message. Use for testing."
        )
        assert hello.capabilities == ["greeting", "testing"]

    def test_hello_greets_the_world_by_default(self) -> None:
        """The README's default argument."""
        hello = _load_shipped("example_hello").HelloTool()

        result = hello.execute({}, {})

        assert result.success is True
        assert result.output == "Hello, World! The agent harness is working."

    def test_hello_greets_a_given_name(self) -> None:
        """And honours ``name`` when one is supplied."""
        hello = _load_shipped("example_hello").HelloTool()

        result = hello.execute({"name": "Ada"}, {})

        assert result.output == "Hello, Ada! The agent harness is working."
        assert result.metadata == {"greeted": "Ada"}

    def test_hello_rejects_a_non_string_name(self) -> None:
        """``validate_input`` is a gate, not decoration."""
        hello = _load_shipped("example_hello").HelloTool()

        ok, reason = hello.validate_input({"name": 7})
        result = hello.execute({"name": 7}, {})

        assert ok is False
        assert result.success is False
        assert result.error == reason

    def test_database_tool_loads_via_plugin_settings(self) -> None:
        """The loader supplies ``db_path`` from ``PLUGIN_SETTINGS``."""
        from agent_harness.plugins.loader import discover_tools

        tools, errors = discover_tools([str(PLUGINS_DIR)])

        assert errors == []
        db_tool = next(t for t in tools if t.name == "database_query")
        assert db_tool.PLUGIN_SETTINGS["db_path"] == "./data/app.db"

    def test_database_tool_is_read_only_by_description(self) -> None:
        """The description tells the LLM the contract."""
        db_tool = _load_shipped("example_database").DatabaseQueryTool("./x.db")

        assert "read-only" in db_tool.description
        assert db_tool.capabilities == ["database", "sql", "data_retrieval"]

    @pytest.mark.parametrize(
        "query",
        [
            "DROP TABLE users",
            "DELETE FROM users",
            "INSERT INTO users (name) VALUES ('x')",
            "UPDATE users SET name = 'x'",
            "CREATE TABLE evil (a int)",
            "ALTER TABLE users ADD COLUMN evil int",
            "ATTACH DATABASE ':memory:' AS evil",
            "PRAGMA journal_mode = OFF",
            "VACUUM",
        ],
    )
    def test_writes_are_refused(self, query: str) -> None:
        """Every write keyword in the README's list, plus the ones it missed."""
        db_tool = _load_shipped("example_database").DatabaseQueryTool("./x.db")

        ok, reason = db_tool.validate_input({"query": query})

        assert ok is False
        assert reason

    def test_a_missing_query_field_is_refused(self) -> None:
        """The README's first check."""
        db_tool = _load_shipped("example_database").DatabaseQueryTool("./x.db")

        assert db_tool.validate_input({}) == (False, "Missing required 'query' field")

    def test_a_second_statement_is_refused(self) -> None:
        """``SELECT 1; DROP TABLE users`` must not piggyback."""
        db_tool = _load_shipped("example_database").DatabaseQueryTool("./x.db")

        ok, reason = db_tool.validate_input({"query": "SELECT 1; DROP TABLE users"})

        assert ok is False
        assert "single statement" in reason

    def test_a_comment_cannot_hide_the_statement_head(self) -> None:
        """``/* SELECT */ DROP TABLE`` is scanned as the DROP it really is."""
        db_tool = _load_shipped("example_database").DatabaseQueryTool("./x.db")

        ok, reason = db_tool.validate_input({"query": "/* SELECT */ DROP TABLE users"})

        assert ok is False
        # The head check fires first: once the comment is gone the statement is
        # plainly a DROP, so it never reaches the keyword scan.
        assert "read-only" in reason

    def test_a_comment_split_head_keyword_is_refused(self) -> None:
        """Conservative: ``SEL/**/ECT`` is not a recognisable SELECT."""
        db_tool = _load_shipped("example_database").DatabaseQueryTool("./x.db")

        ok, reason = db_tool.validate_input({"query": "SEL/**/ECT 1"})

        assert ok is False
        assert "read-only" in reason

    def test_a_trailing_line_comment_still_leaves_one_statement(
        self, demo_db: Path
    ) -> None:
        """SQLite treats the comment as inert, and so does the scan."""
        db_tool = _load_shipped("example_database").DatabaseQueryTool(str(demo_db))

        result = db_tool.execute(
            {"query": "SELECT COUNT(*) AS n FROM users -- total"}, {}
        )

        assert result.success is True
        assert result.output == [{"n": 3}]

    def test_a_keyword_inside_a_literal_is_allowed(self) -> None:
        """Data that merely mentions a keyword is not a write."""
        db_tool = _load_shipped("example_database").DatabaseQueryTool("./x.db")

        ok, reason = db_tool.validate_input(
            {"query": "SELECT * FROM notes WHERE body = 'DROP me a line'"}
        )

        assert (ok, reason) == (True, "")

    def test_an_identifier_containing_a_keyword_is_allowed(self) -> None:
        """Word-boundary matching: ``created_at`` is not ``CREATE``."""
        db_tool = _load_shipped("example_database").DatabaseQueryTool("./x.db")

        ok, reason = db_tool.validate_input(
            {"query": "SELECT created_at, updated_by FROM audit_log"}
        )

        assert (ok, reason) == (True, "")

    def test_a_cte_is_allowed(self) -> None:
        """``WITH ... SELECT`` is a read."""
        db_tool = _load_shipped("example_database").DatabaseQueryTool("./x.db")

        ok, _ = db_tool.validate_input(
            {"query": "WITH t AS (SELECT 1 AS n) SELECT n FROM t"}
        )

        assert ok is True

    def test_a_query_returns_rows(self, demo_db: Path) -> None:
        """End to end against a real database."""
        db_tool = _load_shipped("example_database").DatabaseQueryTool(str(demo_db))

        result = db_tool.execute({"query": "SELECT name FROM users ORDER BY id"}, {})

        assert result.success is True
        assert [row["name"] for row in result.output] == ["Ada", "Grace", "Alan"]
        assert result.metadata["row_count"] == 3
        assert result.metadata["db_path"] == str(demo_db)

    def test_a_bad_statement_returns_a_failure_not_an_exception(
        self, demo_db: Path
    ) -> None:
        """SPEC-002 R1 — a tool never raises."""
        db_tool = _load_shipped("example_database").DatabaseQueryTool(str(demo_db))

        result = db_tool.execute({"query": "SELECT * FROM no_such_table"}, {})

        assert result.success is False
        assert result.error is not None and "SQLite error" in result.error

    def test_the_connection_cannot_write_even_if_validation_is_bypassed(
        self, demo_db: Path
    ) -> None:
        """Layer 1: the driver itself refuses the write."""
        import sqlite3

        db_tool = _load_shipped("example_database").DatabaseQueryTool(str(demo_db))

        with pytest.raises(sqlite3.OperationalError), db_tool._connect() as conn:
            conn.execute("INSERT INTO users (name) VALUES ('Eve')")

    def test_a_missing_database_is_an_error_not_a_new_file(
        self, tmp_path: Path
    ) -> None:
        """``mode=ro`` never creates the target."""
        target = tmp_path / "absent.db"
        db_tool = _load_shipped("example_database").DatabaseQueryTool(str(target))

        result = db_tool.execute({"query": "SELECT 1"}, {})

        assert result.success is False
        assert not target.exists()

    def test_cleanup_is_a_no_op(self, demo_db: Path) -> None:
        """SPEC-002 R8 — idempotent teardown."""
        db_tool = _load_shipped("example_database").DatabaseQueryTool(str(demo_db))

        assert db_tool.cleanup() is None
        assert db_tool.cleanup() is None


# ---------------------------------------------------------------------------
# Sub-phase 3.5 — plugins/README.md, including the compile-the-docs test
# ---------------------------------------------------------------------------

BEGIN_MARKER = "<!-- BEGIN-COPYABLE-PLUGIN -->"
END_MARKER = "<!-- END-COPYABLE-PLUGIN -->"


def _readme_text() -> str:
    """The plugin author guide."""
    return (PLUGINS_DIR / "README.md").read_text(encoding="utf-8")


def _copyable_plugin_source() -> str:
    """Extract the fenced block the README tells readers to copy."""
    text = _readme_text()
    assert BEGIN_MARKER in text, "README lost its BEGIN-COPYABLE-PLUGIN marker"
    assert END_MARKER in text, "README lost its END-COPYABLE-PLUGIN marker"
    block = text.split(BEGIN_MARKER, 1)[1].split(END_MARKER, 1)[0]
    code = [line for line in block.splitlines() if not line.startswith("```")]
    return "\n".join(code).strip("\n") + "\n"


class TestReadmeExampleCompiles:
    """Plan 3.5 exit criterion: the documented example is working code."""

    def test_the_documented_plugin_loads_and_registers(self, tmp_path: Path) -> None:
        """Write-to-tmp, discover, register - exactly what a user does."""
        from agent_harness.plugins.loader import discover_tools, register_discovered

        write_plugin(tmp_path, "word_count.py", _copyable_plugin_source())
        tools, errors = discover_tools([str(tmp_path)])

        assert errors == []
        assert [t.name for t in tools] == ["word_count"]

        registry = doubles.ToolRegistry()
        registered = register_discovered(registry, tools)

        assert [t.name for t in registered] == ["word_count"]
        assert registry.get("word_count") is tools[0]

    def test_the_documented_plugin_actually_works(self, tmp_path: Path) -> None:
        """Discovery is not enough; the tool must return the right answer."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "word_count.py", _copyable_plugin_source())
        (tool,) = discover_tools([str(tmp_path)])[0]

        result = tool.execute({"text": "the quick brown fox"}, {})

        assert result.success is True
        assert result.output == 4
        assert result.metadata == {"characters": 19, "empty": False}

    def test_the_documented_plugin_gates_its_input(self, tmp_path: Path) -> None:
        """The example demonstrates ``validate_input``, so it must really gate."""
        from agent_harness.plugins.loader import discover_tools

        write_plugin(tmp_path, "word_count.py", _copyable_plugin_source())
        (tool,) = discover_tools([str(tmp_path)])[0]

        assert tool.validate_input({}) == (False, "Missing required 'text' field")
        bad = tool.execute({"text": 42}, {})

        assert bad.success is False
        assert bad.error == "'text' must be a string"

    def test_the_documented_plugin_is_importable_python(self) -> None:
        """Compile the block directly, so a doc typo fails loudly."""
        compile(_copyable_plugin_source(), "plugins/word_count.py", "exec")


class TestReadmeContent:
    """The guide must cover what plan 3.5 asks for."""

    def test_it_explains_where_plugins_live(self) -> None:
        """Installation instructions name both default directories."""
        text = _readme_text()

        assert "./plugins" in text
        assert "~/.agent_harness/plugins" in text
        assert "auto_load" in text

    def test_it_documents_the_settings_convention(self) -> None:
        """``PLUGIN_SETTINGS`` is the third construction convention."""
        text = _readme_text()

        assert "PLUGIN_SETTINGS" in text
        assert "llm_client" in text

    def test_it_points_at_the_capability_vocabulary(self) -> None:
        """Plan 3.5 requires a pointer to SPEC-002 § 4."""
        text = _readme_text()

        assert "SPEC-002" in text
        assert "data_retrieval" in text
        assert "greeting" in text

    def test_it_carries_the_security_notice(self) -> None:
        """Full privileges, review before install."""
        text = _readme_text()

        assert "Security notice" in text
        assert "full privileges" in text
        assert "Review the source" in text

    def test_it_explains_the_shell_opt_in(self) -> None:
        """Shell-capable plugins need ``allow_shell`` and bypass its whitelist."""
        text = _readme_text()

        assert "security.allow_shell" in text
        assert "whitelist" in text

    def test_it_documents_the_failure_contract(self) -> None:
        """Authors need to know a failure is reported, not fatal."""
        text = _readme_text()

        assert "PLUGIN_LOAD_FAILED" in text
        assert "plugin_name_collision" in text
        assert "plugin_failed" in text

    def test_it_links_both_shipped_examples(self) -> None:
        """The examples are the reference implementation."""
        text = _readme_text()

        assert "example_hello.py" in text
        assert "example_database.py" in text
