"""Dependency resolution: the execution-order contract every consumer honors.

Spec: SPEC-003 § 8 (``resolve_execution_order``, FROZEN), § 3 step 1 (the step loop
consumes this order), § 3 note ("v0.1 executes sequentially; the returned order is
the single contract a future parallel executor will also honor"); vision § 7.2
(reference implementation of the algorithm § 8 mandates); SPEC-004 § 4.3 V5
(validation reuses this function in validation mode).

Layering and parallel execution
------------------------------
L2 Cognition, like :mod:`agent_harness.planning`. No concrete module from Plan 1
(``agent_harness.config``, ``agent_harness.llm``, ``agent_harness.context``,
``agent_harness.logging``) or Plan 2 (``agent_harness.tools``) is imported
(SPEC-000 § 4, agent.md F3); the logger arrives by injection and is typed
structurally.

The step and logger contracts are imported from :mod:`agent_harness.planning.planner`
because SPEC-000 § 3.3 gives this plan no separate contracts module, and its section A
already hosts the shared injected-contract kit for this package (documented there).
:func:`agent_harness.planning.planner.validate_plan` calls back into this module for
check V5, so that call site uses a **deferred import**: a module-level import in both
directions would be circular.

Typing note
-----------
SPEC-003 § 8 freezes ``resolve_execution_order(steps: list[Step]) -> list[Step]``.
The signature below accepts any ``Sequence`` and is generic over the step type, which
is a type-level widening only: a ``list[Step]`` argument still returns a
``list[Step]``, while the orchestrator can pass ``plan.steps`` (a ``Sequence``, since
``list`` is invariant) without a cast. Runtime behavior is identical to the frozen
contract, and ``StepLike`` is structural, so Plan 1's real ``Step`` satisfies it
unchanged at integration (SCR-P3-6).

The type bound stays the full ``StepLike`` protocol because that is the frozen
signature's ``Step``, even though this function reads only ``id`` and ``depends_on``:
narrowing the bound to a two-field protocol would add a second public step contract
for no caller's benefit.

Skills applied: SKL-CORE-TDD (core-coding/tdd-test-runner), SKL-CORE-TYPES
(core-coding/strict-typing-contracts), SKL-PLAN-FMEA (planning/failure-mode-analysis —
the dangling-dependency and cycle failure modes are specified, not discovered),
SKL-REL-FUZZ (reliability/api-fuzz-tester — bounded, non-crashing handling of ids this
function cannot resolve).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from typing import TypeVar

from agent_harness.planning.planner import LoggerLike, NullLogger, StepLike

__all__ = ["resolve_execution_order"]

_StepT = TypeVar("_StepT", bound=StepLike)


def resolve_execution_order(
    steps: Sequence[_StepT], *, logger: LoggerLike | None = None
) -> list[_StepT]:
    """Return *steps* in dependency order, or raise on a cycle.

    Kahn's algorithm with a ``deque``, matching vision § 7.2 and SPEC-003 § 8:

    1. Build ``in_degree`` (count of resolvable dependencies), ``adjacency``
       (dependency → dependants) and ``step_map`` (id → step), each keyed in input
       order so insertion order equals the original list index.
    2. Seed the queue with every zero-degree id, in input order.
    3. Pop from the left, append the step to the output, decrement each dependant and
       enqueue it the moment its last dependency is satisfied.
    4. If the output is shorter than the input, some step was never ready — a cycle —
       and ``ValueError`` is raised.

    Guarantees and boundaries:

    * **Deterministic.** The output is a pure function of the input. Two ordering
      rules follow from building every dict in input order: the initial ready set is
      seeded by original list index, and when one parent releases several dependants
      at once they are enqueued by *their own* original index — not by the order in
      which they named that parent (§ 8's "stable by original list index"). Across
      parents, release order is the order in which the parents are popped. A step
      that only becomes ready *after* another was already queued therefore keeps its
      breadth-first position even when its own index is lower; § 8 names the vision's
      deque algorithm, so this pins FIFO readiness rather than a strict
      smallest-index-first tie-break. The two readings differ, and SCR-P3-11 records
      the discrepancy with a counterexample.
    * **Dangling dependencies are ignored with a ``WARNING``** (§ 8) instead of
      deadlocking the plan: an id that names no step in *steps* contributes no edge,
      and one ``dependency_ignored`` event is emitted per dangling reference with
      ``step_id`` and ``dependency`` fields. The event name is additive — SPEC-006
      § 6.1 lists the *required* events and names none for this case, while § 8
      mandates the warning (SCR-P3-10). With no logger injected the warning is
      discarded by :class:`~agent_harness.planning.planner.NullLogger`; nothing is
      ever raised for a dangling id.
    * **Duplicate ids cannot be ordered.** Two steps sharing an id collapse into one
      graph node, so the output is shorter than the input and ``ValueError`` is
      raised. That is the § 8 length rule rather than a separate check, and it cannot
      fire for a parsed plan: SPEC-004 § 4.2 rule 2 assigns canonical ``step_<i>``
      ids before dependency resolution, so ids are unique by construction. Only a
      hand-built step list can reach it, and it is reported as unorderable.
    * **Duplicate entries in one ``depends_on``** are consistent: each occurrence adds
      one edge and one unit of in-degree, so the step is still released exactly once.
    * A **self-dependency** is a cycle and raises.
    * Non-string ids are treated as dangling (they name no step). ``depends_on`` is
      typed ``list[str]`` by the structural contract, so an *unhashable* id is a
      caller programming error and is not defended against here.

    The function never mutates *steps*, the list that holds them, or any step's
    ``depends_on``; it returns a new list holding the same step objects, so a caller
    can observe status changes on the ordered steps exactly as on the originals.

    Complexity is O(V + E) with no recursion, so a 10,000-step chain is ordered
    without approaching the interpreter's recursion limit.

    Args:
        steps: The plan's steps, in declaration order.
        logger: Optional structured logger (SPEC-006 § 6.2), used only for the
            dangling-dependency ``WARNING``. Additive, keyword-only, defaulted
            (SCR-P3-6) so SPEC-003 § 3's ``resolve_execution_order(plan.steps)`` call
            site stays valid; module-level logger singletons are forbidden (§ 6.2).

    Returns:
        A new list of the same step objects in dependency order.

    Raises:
        ValueError: When the ordered output is shorter than the input, i.e. the
            dependency graph contains a cycle. The message is frozen by § 8:
            ``"Circular dependency detected in execution plan"``.
    """
    log: LoggerLike = logger if logger is not None else NullLogger()
    step_map: dict[str, _StepT] = {step.id: step for step in steps}
    in_degree: dict[str, int] = {step.id: 0 for step in steps}
    adjacency: dict[str, list[str]] = {step.id: [] for step in steps}
    for step in steps:
        for dep_id in step.depends_on:
            if dep_id not in step_map:
                # § 8: a dangling dependency must not deadlock the plan — drop the
                # edge, keep the step runnable, and make the loss observable.
                log.warning(
                    "orchestrator",
                    "dependency_ignored",
                    step_id=step.id,
                    dependency=dep_id,
                )
                continue
            adjacency[dep_id].append(step.id)
            in_degree[step.id] += 1
    queue = deque(step_id for step_id, degree in in_degree.items() if degree == 0)
    ordered: list[_StepT] = []
    while queue:
        step_id = queue.popleft()
        ordered.append(step_map[step_id])
        for dependent in adjacency[step_id]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)
    if len(ordered) != len(steps):
        raise ValueError("Circular dependency detected in execution plan")
    return ordered
