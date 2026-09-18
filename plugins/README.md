# Writing Plugins for Agent Harness

A plugin is a single Python file that defines one or more
[`BaseTool`](../spec/SPEC-002-tool-system.md) subclasses. Drop the file into a
plugin directory, start the harness, and the tool is available to the planner
on the next run — no import, no registration call, no config entry.

> **Read the [security notice](#security-notice) before installing anyone
> else's plugin.** Plugins are executed in-process with your full privileges.

---

## 1. Where plugins live

The harness scans every directory listed under `plugins.dirs` in
`config.yaml`:

```yaml
plugins:
  dirs:
    - ./plugins                      # shipped examples, and a good place for yours
    - ~/.agent_harness/plugins       # per-user plugins, shared across projects
  auto_load: true                    # set false to disable discovery entirely
```

Rules the loader applies (`agent_harness/plugins/loader.py`, SPEC-005 § 3):

| Rule | Behaviour |
|---|---|
| Missing directory | Skipped, logged at `DEBUG` as `plugin_dir_skipped`. Not an error — most users never create `~/.agent_harness/plugins`. |
| `~` in a path | Expanded to your home directory. |
| File selection | `*.py` only, **sorted by name** so discovery order is reproducible. |
| Skipped files | Anything starting with `_`, including `__init__.py` and `_helpers.py`. Use a leading underscore for shared helpers that are not plugins. |
| Directory order | Directories are visited in the order listed; files within each directory are alphabetical. |
| `auto_load: false` | Nothing is imported at all, so nothing can fail. |

`plugins/` is deliberately **not** a Python package — there is no
`__init__.py`. Files here are executed by path under the synthetic module name
`agent_harness_plugin_<stem>`, which keeps a plugin from shadowing a real
`agent_harness` submodule.

---

## 2. The tool contract

Subclass `BaseTool` and implement the members below. The full contract is
SPEC-002 § 1, rules R1–R8.

| Member | Kind | Requirement |
|---|---|---|
| `name` | property, required | Unique `snake_case` identifier. The planner refers to tools by this name. |
| `description` | property, required | Written **for an LLM to read**. State what the tool does and the expected input shape; a vague description costs you correct tool selection. |
| `capabilities` | property, optional | Tag list for `find_by_capability()`. Defaults to `[]`. |
| `validate_input(input_data)` | method, optional | Return `(True, "")` or `(False, reason)`. The base implementation accepts anything. |
| `execute(input_data, context)` | method, required | **Never raises.** Return a `ToolResult`. |
| `cleanup()` | method, optional | Idempotent teardown, called once when the harness closes. |

`ToolResult` is the only thing `execute` may return:

```python
ToolResult(success: bool, output: Any = None, error: str | None = None,
           metadata: dict = {})
```

Set `success=False` with an `error` string for a *handled* failure — the
orchestrator can retry, re-plan, or fall back around it. Letting an exception
escape `execute` violates R1 and is treated as a tool fault.

### Capability tags

Free-form, but draw them from the controlled vocabulary in SPEC-002 § 4 so
capability lookup stays useful: `search`, `web`, `scrape`, `extract`, `code`,
`execution`, `compute`, `file`, `read`, `write`, `io`, `llm`, `transform`,
`synthesize`, `generate`, `export`, `pdf`, `document`, `csv`, `data`, `shell`,
`system`, `notification`, `messaging`, `database`, `sql`, `data_retrieval`,
`testing`, `greeting`.

---

## 3. Construction conventions

The loader picks the first convention that fits your constructor, in this
order:

1. **Zero arguments** — `def __init__(self)`. Instantiated directly. This is
   the common case.
2. **Injected collaborators** — a parameter *named* `config` or `llm_client`
   receives the harness's own object:

   ```python
   def __init__(self, config, llm_client):
       self._max_rows = config.get("execution.max_steps")
       self._llm = llm_client
   ```

3. **Literal settings** — any other required parameter is looked up in a
   class-level `PLUGIN_SETTINGS` mapping. This is how
   [`example_database.py`](./example_database.py) receives its `db_path`:

   ```python
   class DatabaseQueryTool(BaseTool):
       PLUGIN_SETTINGS: ClassVar[dict[str, Any]] = {"db_path": "./data/app.db"}

       def __init__(self, db_path: str):
           self._db_path = db_path
   ```

   Parameters with defaults never need an entry. To point the shipped database
   example at your own file, copy it, edit `PLUGIN_SETTINGS`, and keep the copy
   in a directory listed in `plugins.dirs`.

A required parameter that has no source under any of the three conventions
produces `AgentError(code="PLUGIN_LOAD_FAILED")` naming the parameter, and the
scan continues.

---

## 4. Failures are reported, never fatal

One bad plugin must not stop the harness, so every failure is contained and
surfaced instead:

| Situation | Outcome |
|---|---|
| File does not parse | `AgentError(PLUGIN_LOAD_FAILED)`, `WARNING plugin_failed`, other plugins still load. |
| Module-level import fails | Same. |
| Constructor raises | Same. |
| `name` property raises | Same — the instance cannot be registered, so it is dropped and reported. |
| Abstract class (unimplemented members) | Silently skipped, so you can ship a shared abstract base in a plugin file. |
| Name already registered | Plugin **loses**; `WARNING plugin_name_collision`. |

Failed plugins are listed in the `--list-tools` footer and in the startup log.
Nothing is silently swallowed: if your tool is missing, the reason is in one of
those two places.

### Name collisions

Built-in tools are registered **before** plugins, and a plugin can never
displace a name that is already taken. This is deliberate: a plugin must not be
able to replace `file_read` with something that looks like it. If your plugin's
tool is missing and you see `plugin_name_collision`, rename the tool.

---

## 5. Security notice

**Plugins run in-process, as you, with your full privileges.** There is no
sandbox, no chroot, no permission prompt, and no network restriction. A plugin
can read `~/.ssh`, export your environment variables, open outbound sockets,
and write anywhere your user account can. The loader's isolation covers
*failures* — it stops one plugin from breaking startup. It does **not**
restrict what a working plugin may do.

Therefore:

- **Review the source of every plugin before you install it.** Treat a plugin
  like a shell script you are about to run, not like a data file.
- **Do not install plugins from untrusted sources**, and pin the revision if
  you vendor one. A plugin that is safe today is not necessarily safe after its
  author's next push.
- **Prefer narrow tools.** A plugin that queries one database is easier to
  audit than one that shells out.
- **Shell-capable plugins are opt-in twice over.** The built-in
  `shell_command` tool exists only when `security.allow_shell: true`
  (SPEC-006 § 4), and even then it is restricted to the configured command
  whitelist. A plugin that spawns subprocesses on its own bypasses that
  whitelist entirely — `allow_shell` does not apply to it, and reviewing the
  plugin is the only control you have.
- **Credentials.** A plugin asking for `config` receives the whole
  configuration object. Assume anything in it can be transmitted by that
  plugin. Log redaction (`sensitive_data_filter`) protects your log files, not
  a plugin's own outbound requests.

The shipped examples are written to be safe to read as reference:
[`example_hello.py`](./example_hello.py) touches nothing outside its return
value, and [`example_database.py`](./example_database.py) opens its database
read-only at the driver level so it cannot write even if its own validation
were bypassed.

---

## 6. Complete example: a plugin you can copy

Everything above in one file. Save it as `plugins/word_count.py` and run
`python -m agent_harness --list-tools` — `word_count` should appear.

<!-- BEGIN-COPYABLE-PLUGIN -->
```python
# plugins/word_count.py
"""Counts words in a piece of text — a complete, minimal plugin."""

from __future__ import annotations

from typing import Any

from agent_harness.tools.base import BaseTool, ToolResult


class WordCountTool(BaseTool):
    """Counts words, and demonstrates every part of the tool contract."""

    @property
    def name(self) -> str:
        return "word_count"

    @property
    def description(self) -> str:
        return (
            "Counts the words in a piece of text. "
            "Input: {text: 'the passage to measure'}. Output: an integer count."
        )

    @property
    def capabilities(self) -> list[str]:
        return ["compute", "transform"]

    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str]:
        if not isinstance(input_data, dict) or "text" not in input_data:
            return False, "Missing required 'text' field"
        if not isinstance(input_data["text"], str):
            return False, "'text' must be a string"
        return True, ""

    def execute(
        self,
        input_data: dict[str, Any],
        context: dict[str, Any],  # noqa: ARG002 - signature fixed by SPEC-002 R1
    ) -> ToolResult:
        is_valid, error_msg = self.validate_input(input_data)
        if not is_valid:
            return ToolResult(success=False, error=error_msg)
        text = input_data["text"]
        words = text.split()
        return ToolResult(
            success=True,
            output=len(words),
            metadata={"characters": len(text), "empty": not words},
        )

    def cleanup(self) -> None:
        """Nothing to release; kept here to show the hook exists."""
```
<!-- END-COPYABLE-PLUGIN -->

The test suite compiles exactly this block: it writes it to a temporary
directory, runs discovery over it, and registers the result, so the documented
example cannot drift from working code.

---

## 7. Manual registration

Discovery is a convenience, not a requirement. To register a tool yourself —
useful in tests, or when a tool needs arguments the loader cannot supply:

```python
from agent_harness import AgentHarness

harness = AgentHarness.from_config("./config.yaml")
harness.register_tool(MyTool(api_key="..."))
print(harness.list_tools())
```

Manually registered tools are added after the built-ins and the discovered
plugins, so the same collision rule applies: an existing name wins.

---

## 8. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Tool does not appear in `--list-tools` | Check `plugins.dirs` includes your directory; check the filename does not start with `_`; check for a `plugin_failed` warning in the log. |
| `plugin_failed` with a `SyntaxError` | The file does not parse. Run `python -m py_compile your_plugin.py`. |
| `plugin_failed` naming a required parameter | The constructor needs a value the loader cannot supply. Add it to `PLUGIN_SETTINGS`, or rename it `config` / `llm_client`. |
| `plugin_name_collision` | A built-in, or an alphabetically earlier plugin, already owns that name. Rename your tool's `name`. |
| Tool appears but the planner never picks it | Your `description` is too vague. Describe the input shape and when to use it — that text is what the planner reads. |
| Nothing loads at all | `plugins.auto_load` may be `false` in `config.yaml`. |

---

*Spec references: SPEC-005 § 3 (discovery algorithm), SPEC-002 § 1 and § 4
(tool contract, capability vocabulary), SPEC-006 § 4 (shell opt-in),
SPEC-001 § 2.3–2.4 (`ToolResult`, `AgentError`).*
