"""Tests for `agent_harness.orchestration.dependency` — SPEC-003 § 8 (FROZEN).

Sub-phase 3.1. The section is FROZEN and points at vision § 7.2 for the algorithm, so
the cases below are derived from both: the four shapes the plan's exit criteria name
(linear chain, diamond, cycle, dangling dependency) plus the boundary and determinism
cases SKL-CORE-TDD and SKL-REL-FUZZ require for a function every other plan consumes.

Independence (SPEC-000 § 5.4, agent.md F3): no concrete Plan 1/2 module is imported.
Steps are P3's own spec-conformant `Step` stand-in and the logger is a local recording
double — deliberately *not* imported from `tests/test_planner.py`, because two
independently collected test modules must not depend on each other (SCR-P3-3).
"""

from __future__ import annotations

import ast
import inspect
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest

from agent_harness.orchestration import dependency
from agent_harness.orchestration.dependency import resolve_execution_order
from agent_harness.planning.planner import Step

# ── Doubles ───────────────────────────────────────────────────────────────────


class FakeLogger:
    """Spec-shaped stand-in for `StructuredLogger` (SPEC-006 § 6.2). Records events."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str, str, dict[str, Any]]] = []

    def log(self, level: str, component: str, event: str, **fields: Any) -> None:
        """Record one structured event."""
        self.records.append((level, component, event, fields))

    def debug(self, component: str, event: str, **fields: Any) -> None:
        """Record a DEBUG event."""
        self.log("DEBUG", component, event, **fields)

    def info(self, component: str, event: str, **fields: Any) -> None:
        """Record an INFO event."""
        self.log("INFO", component, event, **fields)

    def warning(self, component: str, event: str, **fields: Any) -> None:
        """Record a WARNING event."""
        self.log("WARNING", component, event, **fields)

    def error(self, component: str, event: str, **fields: Any) -> None:
        """Record an ERROR event."""
        self.log("ERROR", component, event, **fields)

    def child(self, component: str, **bound: Any) -> FakeLogger:
        """Return a logger sharing this one's record list."""
        clone = FakeLogger()
        clone.records = self.records
        return clone

    def events(self) -> list[str]:
        """Every recorded event name, in order."""
        return [record[2] for record in self.records]

    def levels(self) -> list[str]:
        """Every recorded level, in order."""
        return [record[0] for record in self.records]


def _steps(*specs: tuple[str, Sequence[str]]) -> list[Step]:
    """Build steps from ``(id, depends_on)`` pairs, in the order given."""
    return [
        Step(id=step_id, description=f"do {step_id}", depends_on=list(depends_on))
        for step_id, depends_on in specs
    ]


def _ids(steps: Sequence[Step]) -> list[str]:
    """The ids of *steps*, in order."""
    return [step.id for step in steps]


def _signature_parameters(func: Any) -> list[tuple[str, str, Any]]:
    """`(name, kind, default)` triples — the SPEC-000 § 5.4 contract-test shape."""
    return [
        (name, str(parameter.kind), parameter.default)
        for name, parameter in inspect.signature(func).parameters.items()
    ]


# ── The frozen contract ───────────────────────────────────────────────────────


class TestResolveExecutionOrderContract:
    """SPEC-003 § 8 is FROZEN; `logger` is the additive SCR-P3-6 parameter."""

    def test_the_signature_is_steps_then_keyword_logger(self) -> None:
        assert _signature_parameters(resolve_execution_order) == [
            ("steps", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
            ("logger", "KEYWORD_ONLY", None),
        ]

    def test_it_is_exported_from_the_package(self) -> None:
        assert "resolve_execution_order" in dependency.__all__

    def test_the_module_imports_no_concrete_plan_1_or_plan_2_module(self) -> None:
        # agent.md F3: dependencies arrive by injection, never by import. Checked on
        # the AST rather than the source text, because the module docstring *names*
        # the forbidden modules while explaining that it does not import them.
        tree = ast.parse(inspect.getsource(dependency))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.append(node.module)
        forbidden = {
            "agent_harness.tools",
            "agent_harness.config",
            "agent_harness.llm",
            "agent_harness.context",
            "agent_harness.logging",
        }
        assert not forbidden.intersection(imported)
        # What it *may* import: the shared structural-contract kit (SPEC-000 § 3.3
        # gives this plan no separate contracts module).
        first_party = [name for name in imported if name.startswith("agent_harness")]
        assert first_party == ["agent_harness.planning.planner"]

    def test_it_returns_a_new_list_of_the_same_step_objects(self) -> None:
        steps = _steps(("step_0", []), ("step_1", ["step_0"]))
        ordered = resolve_execution_order(steps)
        assert ordered is not steps
        assert all(any(found is original for original in steps) for found in ordered)


# ── The four vision-derived shapes (plan § 3.1 exit criteria) ─────────────────


class TestLinearChain:
    """A → B → C must come out in dependency order, not input order."""

    def test_a_forward_chain_keeps_its_order(self) -> None:
        steps = _steps(("step_0", []), ("step_1", ["step_0"]), ("step_2", ["step_1"]))
        assert _ids(resolve_execution_order(steps)) == ["step_0", "step_1", "step_2"]

    def test_a_chain_listed_in_reverse_is_reordered(self) -> None:
        steps = _steps(("step_2", ["step_1"]), ("step_1", ["step_0"]), ("step_0", []))
        assert _ids(resolve_execution_order(steps)) == ["step_0", "step_1", "step_2"]

    def test_a_long_chain_is_fully_ordered(self) -> None:
        size = 200
        steps = _steps(
            *[(f"step_{i}", [] if i == 0 else [f"step_{i - 1}"]) for i in range(size)]
        )
        assert _ids(resolve_execution_order(steps)) == [
            f"step_{i}" for i in range(size)
        ]

    def test_a_chain_of_duplicate_dependency_entries_is_not_stalled(self) -> None:
        # The same dependency listed twice must not leave the step permanently ready.
        steps = _steps(
            ("step_0", []), ("step_1", ["step_0", "step_0"]), ("step_2", ["step_1"])
        )
        assert _ids(resolve_execution_order(steps)) == ["step_0", "step_1", "step_2"]


class TestDiamond:
    """The vision's diamond: A → (B, C) → D."""

    def test_the_diamond_orders_root_then_branches_then_join(self) -> None:
        steps = _steps(
            ("step_0", []),
            ("step_1", ["step_0"]),
            ("step_2", ["step_0"]),
            ("step_3", ["step_1", "step_2"]),
        )
        assert _ids(resolve_execution_order(steps)) == [
            "step_0",
            "step_1",
            "step_2",
            "step_3",
        ]

    def test_the_diamond_listed_join_first_is_still_ordered(self) -> None:
        steps = _steps(
            ("step_3", ["step_1", "step_2"]),
            ("step_2", ["step_0"]),
            ("step_1", ["step_0"]),
            ("step_0", []),
        )
        assert _ids(resolve_execution_order(steps)) == [
            "step_0",
            "step_2",
            "step_1",
            "step_3",
        ]

    def test_branch_release_order_follows_the_dependants_own_index(self) -> None:
        # "Stable by original list index" (§ 8) is about where the DEPENDANT sits in
        # the input list, not the order in which it named its dependencies: the join
        # declares step_1 before step_2, yet step_2 is released first because it is
        # the earlier of the two in the input.
        steps = _steps(
            ("join", ["step_1", "step_2"]),
            ("step_2", ["root"]),
            ("step_1", ["root"]),
            ("root", []),
        )
        assert _ids(resolve_execution_order(steps)) == [
            "root",
            "step_2",
            "step_1",
            "join",
        ]

    def test_a_join_with_one_branch_missing_a_dependency_waits_for_both(self) -> None:
        steps = _steps(
            ("step_0", []),
            ("step_1", ["step_0"]),
            ("step_2", ["step_1"]),
            ("step_3", ["step_0", "step_2"]),
        )
        ordered = _ids(resolve_execution_order(steps))
        assert ordered.index("step_2") < ordered.index("step_3")
        assert ordered.index("step_0") < ordered.index("step_1")


class TestCycleRaises:
    """SPEC-003 § 8: `ValueError("Circular dependency detected in execution plan")`."""

    MESSAGE = "Circular dependency detected in execution plan"

    def test_a_two_step_cycle_raises_the_frozen_message(self) -> None:
        steps = _steps(("step_0", ["step_1"]), ("step_1", ["step_0"]))
        with pytest.raises(ValueError) as caught:
            resolve_execution_order(steps)
        assert str(caught.value) == self.MESSAGE

    def test_a_three_step_cycle_raises(self) -> None:
        steps = _steps(
            ("step_0", ["step_2"]), ("step_1", ["step_0"]), ("step_2", ["step_1"])
        )
        with pytest.raises(ValueError) as caught:
            resolve_execution_order(steps)
        assert str(caught.value) == self.MESSAGE

    def test_a_self_dependency_is_a_cycle(self) -> None:
        steps = _steps(("step_0", ["step_0"]))
        with pytest.raises(ValueError) as caught:
            resolve_execution_order(steps)
        assert str(caught.value) == self.MESSAGE

    def test_a_cycle_downstream_of_a_valid_prefix_still_raises(self) -> None:
        steps = _steps(
            ("step_0", []),
            ("step_1", ["step_0"]),
            ("step_2", ["step_3"]),
            ("step_3", ["step_2"]),
        )
        with pytest.raises(ValueError) as caught:
            resolve_execution_order(steps)
        assert str(caught.value) == self.MESSAGE

    def test_the_error_is_a_plain_value_error_not_a_spec_error(self) -> None:
        # § 8 names ValueError; validation (SPEC-004 § 4.3 V5) is what turns it into
        # AgentError(code="PLAN_VALIDATION_FAILED").
        steps = _steps(("step_0", ["step_0"]))
        with pytest.raises(ValueError) as caught:
            resolve_execution_order(steps)
        assert type(caught.value) is ValueError

    def test_duplicate_step_ids_cannot_be_ordered_and_raise(self) -> None:
        # Documented consequence of the § 8 rule "ordered output shorter than the
        # input": two steps sharing an id collapse into one graph node.
        steps = _steps(("step_0", []), ("step_0", []))
        with pytest.raises(ValueError) as caught:
            resolve_execution_order(steps)
        assert str(caught.value) == self.MESSAGE


class TestDanglingDependency:
    """§ 8: unknown ids are ignored with a WARNING, never deadlocking the plan."""

    def test_a_dangling_dependency_is_ignored_and_the_step_still_runs(self) -> None:
        steps = _steps(("step_0", ["ghost"]), ("step_1", ["step_0"]))
        assert _ids(resolve_execution_order(steps)) == ["step_0", "step_1"]

    def test_the_warning_is_emitted_at_warning_level_by_the_orchestrator(self) -> None:
        logger = FakeLogger()
        resolve_execution_order(_steps(("step_0", ["ghost"])), logger=logger)
        assert logger.levels() == ["WARNING"]
        assert logger.records[0][1] == "orchestrator"
        assert logger.events() == ["dependency_ignored"]

    def test_the_warning_names_the_step_and_the_missing_dependency(self) -> None:
        logger = FakeLogger()
        resolve_execution_order(_steps(("step_2", ["ghost"])), logger=logger)
        fields = logger.records[0][3]
        assert fields["step_id"] == "step_2"
        assert fields["dependency"] == "ghost"

    def test_one_warning_is_emitted_per_dangling_reference(self) -> None:
        logger = FakeLogger()
        steps = _steps(("step_0", ["ghost_a", "ghost_b"]), ("step_1", ["ghost_a"]))
        assert _ids(resolve_execution_order(steps, logger=logger)) == [
            "step_0",
            "step_1",
        ]
        assert logger.events() == ["dependency_ignored"] * 3

    def test_a_mixed_valid_and_dangling_dependency_keeps_only_the_valid_edge(
        self,
    ) -> None:
        steps = _steps(("step_0", []), ("step_1", ["step_0", "ghost"]))
        assert _ids(resolve_execution_order(steps)) == ["step_0", "step_1"]

    def test_a_non_string_dependency_id_is_treated_as_dangling(self) -> None:
        logger = FakeLogger()
        steps = [Step(id="step_0", description="a", depends_on=[0, None, 7.5])]  # type: ignore[list-item]
        assert _ids(resolve_execution_order(steps, logger=logger)) == ["step_0"]
        assert logger.events() == ["dependency_ignored"] * 3

    def test_no_logger_injected_means_no_crash(self) -> None:
        assert _ids(resolve_execution_order(_steps(("step_0", ["ghost"])))) == [
            "step_0"
        ]

    def test_a_cycle_is_still_reported_when_a_dangling_dependency_is_also_present(
        self,
    ) -> None:
        steps = _steps(("step_0", ["step_1", "ghost"]), ("step_1", ["step_0"]))
        with pytest.raises(ValueError):
            resolve_execution_order(steps)


class TestTieBreakingAndDeterminism:
    """§ 8: stable by original list index, so ordering is deterministic and testable."""

    def test_independent_steps_keep_their_original_index_order(self) -> None:
        steps = _steps(*[(f"step_{i}", []) for i in range(6)])
        assert _ids(resolve_execution_order(steps)) == [f"step_{i}" for i in range(6)]

    def test_steps_that_become_ready_together_are_emitted_in_index_order(self) -> None:
        # adjacency lists are built in step order, so a shared parent releases its
        # dependants by original index.
        steps = _steps(
            ("step_0", []),
            ("step_1", ["step_0"]),
            ("step_2", ["step_0"]),
            ("step_3", ["step_0"]),
        )
        assert _ids(resolve_execution_order(steps)) == [
            "step_0",
            "step_1",
            "step_2",
            "step_3",
        ]

    def test_the_initial_ready_set_is_seeded_in_index_order(self) -> None:
        steps = _steps(("step_3", []), ("step_1", []), ("step_2", []), ("step_0", []))
        # Ids are arbitrary; what is stable is the *input* order.
        assert _ids(resolve_execution_order(steps)) == [
            "step_3",
            "step_1",
            "step_2",
            "step_0",
        ]

    def test_repeated_calls_return_an_identical_ordering(self) -> None:
        steps = _steps(
            ("step_0", []),
            ("step_1", ["step_0"]),
            ("step_2", ["step_0"]),
            ("step_3", ["step_1", "step_2"]),
            ("step_4", []),
            ("step_5", ["step_3", "step_4"]),
        )
        first = _ids(resolve_execution_order(steps))
        for _ in range(50):
            assert _ids(resolve_execution_order(steps)) == first

    def test_the_order_does_not_depend_on_dict_or_hash_seeding(self) -> None:
        # Ids chosen so that a set/hash-driven iteration order would differ from the
        # insertion order; `y` is ready from the start and is seeded after `z`.
        steps = _steps(
            ("z", []), ("a", ["z"]), ("m", ["z"]), ("b", ["a", "m"]), ("y", [])
        )
        assert _ids(resolve_execution_order(steps)) == ["z", "y", "a", "m", "b"]
        assert _ids(resolve_execution_order(steps)) == _ids(
            resolve_execution_order(steps)
        )

    def test_a_step_released_later_keeps_its_breadth_first_position(self) -> None:
        # Documented reading of "BFS with a deque": `step_1` becomes ready while
        # `step_3` is still queued, so it runs before the lower-indexed `step_0`,
        # which only becomes ready when `step_3` is popped. A strict "always take the
        # smallest ready index" tie-break would instead yield
        # [step_2, step_1, step_3, step_0]; both are deterministic, and this pins the
        # vision § 7.2 deque behaviour that SPEC-003 § 8 names (SCR-P3-10).
        steps = _steps(
            ("step_0", ["step_3"]),
            ("step_1", ["step_2"]),
            ("step_2", []),
            ("step_3", []),
        )
        assert _ids(resolve_execution_order(steps)) == [
            "step_2",
            "step_3",
            "step_1",
            "step_0",
        ]


class TestBoundaries:
    """0 / 1 / N, and no mutation of the caller's data."""

    def test_an_empty_plan_orders_to_an_empty_list(self) -> None:
        assert resolve_execution_order([]) == []

    def test_a_single_step_orders_to_itself(self) -> None:
        steps = _steps(("step_0", []))
        assert resolve_execution_order(steps) == steps

    def test_a_single_step_with_only_a_dangling_dependency_still_orders(self) -> None:
        assert _ids(resolve_execution_order(_steps(("step_0", ["ghost"])))) == [
            "step_0"
        ]

    def test_the_input_list_is_not_mutated(self) -> None:
        steps = _steps(("step_1", ["step_0"]), ("step_0", []))
        snapshot = [(step.id, list(step.depends_on)) for step in steps]
        resolve_execution_order(steps)
        assert [(step.id, list(step.depends_on)) for step in steps] == snapshot
        assert _ids(steps) == ["step_1", "step_0"]

    def test_a_tuple_of_steps_is_accepted(self) -> None:
        steps = tuple(_steps(("step_1", ["step_0"]), ("step_0", [])))
        assert _ids(resolve_execution_order(steps)) == ["step_0", "step_1"]

    def test_a_wide_fan_out_is_ordered(self) -> None:
        size = 300
        steps = _steps(("root", []), *[(f"leaf_{i}", ["root"]) for i in range(size)])
        ordered = _ids(resolve_execution_order(steps))
        assert ordered[0] == "root"
        assert ordered[1:] == [f"leaf_{i}" for i in range(size)]

    def test_a_wide_fan_in_is_ordered(self) -> None:
        size = 300
        steps = _steps(
            *[(f"leaf_{i}", []) for i in range(size)],
            ("join", [f"leaf_{i}" for i in range(size)]),
        )
        ordered = _ids(resolve_execution_order(steps))
        assert ordered[-1] == "join"
        assert ordered[:-1] == [f"leaf_{i}" for i in range(size)]

    def test_ten_thousand_steps_resolve_in_bounded_time(self) -> None:
        # Kahn's algorithm is O(V + E); a quadratic implementation would not finish a
        # 10k-step chain inside this budget (SKL-REL-FUZZ: boundedness is verified).
        size = 10_000
        steps = _steps(
            *[(f"step_{i}", [] if i == 0 else [f"step_{i - 1}"]) for i in range(size)]
        )
        started = time.monotonic()
        ordered = resolve_execution_order(steps)
        elapsed = time.monotonic() - started
        assert len(ordered) == size
        assert elapsed < 10.0

    def test_a_step_subclass_is_accepted_and_its_type_is_preserved(self) -> None:
        # The signature is generic over the step type, so a caller that passes a
        # narrower step gets that type back rather than the structural protocol:
        # Plan 1's real Step (SPEC-001 § 2.1) satisfies StepLike, and a list of them
        # comes back as a list of them — which is why the orchestrator needs no cast
        # when it writes statuses onto the ordered steps.
        @dataclass
        class RichStep(Step):
            unrelated: dict[str, Any] = field(default_factory=dict)

        steps = [
            RichStep(id="b", description="second", depends_on=["a"]),
            RichStep(id="a", description="first"),
        ]
        ordered = resolve_execution_order(steps)
        assert [step.id for step in ordered] == ["a", "b"]
        assert all(isinstance(step, RichStep) for step in ordered)
        assert ordered[0].unrelated == {}


# ── The event-catalog seam (SCR-P3-10) ────────────────────────────────────────

#: SPEC-006 § 6.1's required events, transcribed from the spec table.
CATALOG_EVENTS = frozenset(
    {
        "harness_start",
        "harness_complete",
        "plan_generated",
        "plan_validation_failed",
        "step_started",
        "step_completed",
        "step_failed",
        "step_skipped",
        "recovery_attempted",
        "recovery_succeeded",
        "recovery_exhausted",
        "tool_executed",
        "sandbox_violation",
        "llm_call",
        "plugin_loaded",
        "plugin_failed",
        "config_loaded",
        "output_written",
    }
)


class ClosedCatalogLogger:
    """A logger that treats SPEC-006 § 6.1 as a CLOSED whitelist, and raises.

    This mirrors Plan 1's merged ``agent_harness/logging/logger.py``, whose ``log()``
    rejects any event outside the 18 catalog names with
    ``ValueError("Unknown logging level or event")``. It is declared here rather than
    imported (agent.md F3, SCR-P3-3): P3 must not import a concrete Plan 1 module, and
    the point of the double is to pin what happens when the two specs meet.
    """

    def __init__(self) -> None:
        self.records: list[tuple[str, str, str, dict[str, Any]]] = []

    def log(self, level: str, component: str, event: str, **fields: Any) -> None:
        """Record the event, or raise exactly as the closed catalog does."""
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR"} or (
            event not in CATALOG_EVENTS
        ):
            raise ValueError("Unknown logging level or event")
        self.records.append((level, component, event, fields))

    def debug(self, component: str, event: str, **fields: Any) -> None:
        """Record a DEBUG event."""
        self.log("DEBUG", component, event, **fields)

    def info(self, component: str, event: str, **fields: Any) -> None:
        """Record an INFO event."""
        self.log("INFO", component, event, **fields)

    def warning(self, component: str, event: str, **fields: Any) -> None:
        """Record a WARNING event."""
        self.log("WARNING", component, event, **fields)

    def error(self, component: str, event: str, **fields: Any) -> None:
        """Record an ERROR event."""
        self.log("ERROR", component, event, **fields)

    def child(self, component: str, **bound: Any) -> ClosedCatalogLogger:
        """Return a logger sharing this one's record list."""
        clone = ClosedCatalogLogger()
        clone.records = self.records
        return clone


class TestTheEventCatalogSeam:
    """SPEC-003 § 8 mandates a WARNING that SPEC-006 § 6.1 has no event name for."""

    def test_the_warning_name_is_additive_not_a_misspelling_of_the_catalog(
        self,
    ) -> None:
        assert "dependency_ignored" not in CATALOG_EVENTS

    def test_a_closed_catalog_logger_surfaces_the_conflict(self) -> None:
        # SCR-P3-10: P3 emits the additive name and never catches the rejection, so
        # composing with today's Plan 1 logger fails loudly at integration (I4) instead
        # of silently dropping a warning the spec requires. A blanket `except
        # ValueError` here would also swallow the cycle error, which is why the
        # behaviour is pinned rather than left to a reviewer.
        logger = ClosedCatalogLogger()
        with pytest.raises(ValueError) as caught:
            resolve_execution_order(_steps(("step_0", ["ghost"])), logger=logger)
        assert str(caught.value) == "Unknown logging level or event"
        assert logger.records == []

    def test_a_closed_catalog_logger_is_unaffected_when_nothing_dangles(self) -> None:
        logger = ClosedCatalogLogger()
        steps = _steps(("step_0", []), ("step_1", ["step_0"]))
        assert _ids(resolve_execution_order(steps, logger=logger)) == [
            "step_0",
            "step_1",
        ]
        assert logger.records == []

    def test_a_closed_catalog_logger_still_reports_a_cycle(self) -> None:
        # The cycle ValueError must win, and must not be confused with the catalog one.
        logger = ClosedCatalogLogger()
        with pytest.raises(ValueError) as caught:
            resolve_execution_order(_steps(("step_0", ["step_0"])), logger=logger)
        assert str(caught.value) == "Circular dependency detected in execution plan"
