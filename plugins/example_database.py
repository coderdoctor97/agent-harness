"""A read-only SQLite query plugin — the Developer README's full-featured example.

This is the canonical "real" plugin: it shows a non-zero-argument constructor
supplied by ``PLUGIN_SETTINGS``, a ``validate_input`` gate, and per-query
connection handling.

Security notice
---------------
A database tool is the highest-risk thing a plugin can be, so this file is
deliberately stricter than the README snippet it comes from. Three independent
layers stand between a plan step and your data:

1. **Driver level** — the connection is opened ``mode=ro`` and with
   ``PRAGMA query_only = ON``. Even if statement validation were bypassed
   entirely, SQLite refuses the write.
2. **Statement level** — only a single ``SELECT``/``WITH`` statement is
   accepted. Comments and string literals are removed before the keyword scan,
   so ``SEL/**/ECT`` cannot smuggle anything past and a literal such as
   ``'DROP TABLE'`` inside a ``WHERE`` clause is not mistaken for a statement.
3. **Keyword level** — write and schema keywords are rejected on word
   boundaries, so ``created_at`` is not rejected for containing ``CREATE``.

Nothing here is imported by the package; the loader executes this file under
the synthetic module name ``agent_harness_plugin_example_database``.

Spec: SPEC-005 § 3.1 · Developer README § Writing Custom Tools
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, ClassVar
from urllib.request import pathname2url

from agent_harness.tools.base import BaseTool, ToolResult

#: Keywords that mutate data or schema. Matched on word boundaries after
#: comments and string literals have been removed, so identifiers such as
#: ``created_at`` or ``updated_by`` are unaffected.
DANGEROUS_KEYWORDS = (
    "ALTER",
    "ANALYZE",
    "ATTACH",
    "CREATE",
    "DELETE",
    "DETACH",
    "DROP",
    "INSERT",
    "PRAGMA",
    "REINDEX",
    "REPLACE",
    "TRUNCATE",
    "UPDATE",
    "VACUUM",
)

#: Statements the tool will run. ``WITH`` is included because a common table
#: expression is a read that legitimately starts with something other than
#: ``SELECT``.
ALLOWED_STATEMENTS = ("SELECT", "WITH")

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'", re.DOTALL)
_KEYWORD_PATTERN = re.compile(
    r"\b(" + "|".join(DANGEROUS_KEYWORDS) + r")\b", re.IGNORECASE
)


def _strip_noise(query: str) -> str:
    """Remove comments and string literals so the keyword scan sees real SQL.

    Stripping is what makes the scan both stricter and kinder: a keyword hidden
    inside a comment can no longer dodge the check, and a keyword that is merely
    *data* (``WHERE note = 'DROP me a line'``) no longer trips it.

    Args:
        query: the raw statement.

    Returns:
        The statement with comments and literals removed.
    """
    without_blocks = _BLOCK_COMMENT.sub(" ", query)
    without_lines = _LINE_COMMENT.sub(" ", without_blocks)
    return _STRING_LITERAL.sub("''", without_lines)


# The type: ignore below is temporary and listed on the 5.1 swap checklist:
# agent_harness.tools.base is Plan 2's module and does not exist until integration
# window step I1, so mypy sees BaseTool as Any. Remove it once Plan 2 has landed.
class DatabaseQueryTool(BaseTool):  # type: ignore[misc]
    """Executes read-only SQL queries against a SQLite database.

    The constructor takes ``db_path``, which the plugin loader supplies from
    :attr:`PLUGIN_SETTINGS` (SPEC-005 § 3 step 4, third convention). Rename that
    mapping or set ``plugins.dirs`` to point at your own copy to change the
    target database.
    """

    #: Literal constructor kwargs used when the loader builds this class
    #: (SPEC-005 § 3 step 4). Edit here, not in the harness.
    PLUGIN_SETTINGS: ClassVar[dict[str, Any]] = {"db_path": "./data/app.db"}

    def __init__(self, db_path: str) -> None:
        """Store the target path; no connection is opened until a query runs."""
        self._db_path = db_path

    @property
    def name(self) -> str:
        """Unique snake_case identifier (SPEC-002 R6)."""
        return "database_query"

    @property
    def description(self) -> str:
        """Written for LLM consumption (SPEC-002 R7)."""
        return (
            "Executes read-only SQL queries against the SQLite database at "
            f"{self._db_path}. Input: {{query: 'SELECT ...'}}"
        )

    @property
    def capabilities(self) -> list[str]:
        """Capability tags used for capability-based lookup."""
        return ["database", "sql", "data_retrieval"]

    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str]:
        """Refuse anything that is not a single read-only statement.

        Args:
            input_data: must carry a ``query`` string.

        Returns:
            ``(True, "")`` when the statement may run, else ``(False, reason)``.
        """
        if not isinstance(input_data, dict) or "query" not in input_data:
            return False, "Missing required 'query' field"

        query = input_data["query"]
        if not isinstance(query, str) or not query.strip():
            return False, "'query' must be a non-empty string"

        statement = _strip_noise(query).strip().rstrip(";").strip()
        if not statement:
            return False, "Query is empty once comments are removed"

        # One statement only: a trailing semicolon is fine, a second one is a
        # piggybacked write.
        if ";" in statement:
            return False, "Only a single statement is allowed"

        head = statement.upper()
        if not head.startswith(ALLOWED_STATEMENTS):
            return False, (
                "Only SELECT (or WITH ... SELECT) queries are allowed (read-only)"
            )

        match = _KEYWORD_PATTERN.search(statement)
        if match is not None:
            return False, f"Dangerous keyword '{match.group(1).upper()}' detected"

        return True, ""

    def execute(
        self,
        input_data: dict[str, Any],
        context: dict[str, Any],  # noqa: ARG002 - signature fixed by SPEC-002 R1
    ) -> ToolResult:
        """Run a validated read-only query and return its rows.

        Args:
            input_data: the ``query`` to run.
            context: the run context; this tool needs nothing from it.

        Returns:
            A :class:`ToolResult` whose ``output`` is a list of row dicts.
        """
        is_valid, error_msg = self.validate_input(input_data)
        if not is_valid:
            return ToolResult(success=False, error=error_msg)

        try:
            with self._connect() as connection:
                cursor = connection.execute(input_data["query"])
                rows = [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as exc:
            return ToolResult(success=False, error=f"SQLite error: {exc}")
        except OSError as exc:
            return ToolResult(success=False, error=f"Cannot open database: {exc}")

        return ToolResult(
            success=True,
            output=rows,
            metadata={"row_count": len(rows), "db_path": self._db_path},
        )

    def _connect(self) -> sqlite3.Connection:
        """Open a connection that cannot write.

        ``mode=ro`` makes SQLite reject writes and refuse to create the file, so
        a missing database is an error rather than a silently empty one.
        ``PRAGMA query_only`` is the second lock: it stays in force even if a
        future caller forgets the URI.

        Returns:
            A read-only connection with row-dict access.
        """
        resolved = Path(self._db_path).expanduser().resolve()
        uri = f"file:{pathname2url(str(resolved))}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection

    def cleanup(self) -> None:
        """Nothing to release: connections are opened and closed per query."""
